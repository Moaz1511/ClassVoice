"""Validated, idempotent generation-job lifecycle service."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from app.core.text_validation import (
    MAX_GENERATION_TEXT_CHARACTERS,
    GenerationTextValidationError,
    normalize_generation_text,
)
from app.domains.voices.lifecycle import VoiceLifecycleService
from app.inference.model_registry import ModelRegistry, ModelRegistryError

GenerationStatus = Literal[
    "created", "queued", "processing", "succeeded", "failed", "cancel_requested", "canceled"
]
OutputFormat = Literal["wav", "mp3"]
MAX_INPUT_CHARACTERS = MAX_GENERATION_TEXT_CHARACTERS
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2}|-[A-Z][a-z]{2,4})?$")
_VISIBLE_IDEMPOTENCY_RE = re.compile(r"^[^\x00-\x20\x7f]+$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_TRANSITIONS: dict[GenerationStatus, frozenset[GenerationStatus]] = {
    "created": frozenset({"queued", "cancel_requested", "canceled"}),
    "queued": frozenset({"processing", "cancel_requested", "canceled", "failed"}),
    "processing": frozenset({"succeeded", "failed", "cancel_requested", "canceled"}),
    "succeeded": frozenset(),
    "failed": frozenset({"created"}),
    "cancel_requested": frozenset({"canceled", "processing", "failed"}),
    "canceled": frozenset({"created"}),
}


class GenerationError(ValueError):
    """A stable, user-safe generation validation or lifecycle error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class GenerationJob:
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    voice_profile_id: UUID
    requested_by: UUID
    status: GenerationStatus
    input_text: str
    input_text_sha256: str
    language_code: str
    output_format: OutputFormat
    speed: float
    stability: float | None
    style: float | None
    seed: int | None
    model_key: str
    model_version: str
    checkpoint_sha256: str
    model_metadata: Mapping[str, object]
    idempotency_key: str
    error_code: str | None
    error_message_safe: str | None
    retryable: bool
    queue_attempts: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None

    def as_dict(self, *, include_text: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "project_id": str(self.project_id) if self.project_id else None,
            "voice_profile_id": str(self.voice_profile_id),
            "requested_by": str(self.requested_by),
            "status": self.status,
            "input_text_sha256": self.input_text_sha256,
            "language_code": self.language_code,
            "output_format": self.output_format,
            "speed": self.speed,
            "stability": self.stability,
            "style": self.style,
            "seed": self.seed,
            "model": dict(self.model_metadata),
            "idempotency_key": self.idempotency_key,
            "error_code": self.error_code,
            "error_message_safe": self.error_message_safe,
            "retryable": self.retryable,
            "queue_attempts": self.queue_attempts,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "canceled_at": self.canceled_at.isoformat() if self.canceled_at else None,
        }
        if include_text:
            result["input_text"] = self.input_text
        return result


@dataclass(frozen=True, slots=True)
class GenerationAuditEvent:
    id: UUID
    workspace_id: UUID
    actor_id: UUID
    action: str
    job_id: UUID
    created_at: datetime
    details: Mapping[str, object]


class GenerationStore(Protocol):
    async def get(self, job_id: UUID) -> GenerationJob | None: ...

    async def list(self, workspace_id: UUID) -> tuple[GenerationJob, ...]: ...

    async def put(self, job: GenerationJob) -> None: ...

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, GenerationJob] | None: ...

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, job: GenerationJob
    ) -> None: ...

    async def audit(self, event: GenerationAuditEvent) -> None: ...


class InMemoryGenerationStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, GenerationJob] = {}
        self._idempotency: dict[tuple[UUID, str], tuple[str, GenerationJob]] = {}
        self._audit_events: list[GenerationAuditEvent] = []
        self._lock = asyncio.Lock()

    async def get(self, job_id: UUID) -> GenerationJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list(self, workspace_id: UUID) -> tuple[GenerationJob, ...]:
        async with self._lock:
            jobs = [job for job in self._jobs.values() if job.workspace_id == workspace_id]
            jobs.sort(key=lambda job: job.created_at, reverse=True)
            return tuple(jobs)

    async def put(self, job: GenerationJob) -> None:
        async with self._lock:
            self._jobs[job.id] = job

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, GenerationJob] | None:
        async with self._lock:
            return self._idempotency.get((workspace_id, idempotency_key))

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, job: GenerationJob
    ) -> None:
        async with self._lock:
            self._idempotency[(workspace_id, idempotency_key)] = (fingerprint, job)

    async def audit(self, event: GenerationAuditEvent) -> None:
        async with self._lock:
            self._audit_events.append(event)

    async def audit_events(self) -> tuple[GenerationAuditEvent, ...]:
        async with self._lock:
            return tuple(self._audit_events)


class GenerationService:
    def __init__(
        self,
        store: GenerationStore,
        voices: VoiceLifecycleService,
        models: ModelRegistry,
    ) -> None:
        self._store = store
        self._voices = voices
        self._models = models
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        voice_profile_id: UUID,
        project_id: UUID | None,
        input_text: str,
        language_code: str,
        output_format: OutputFormat,
        speed: float,
        stability: float | None,
        style: float | None,
        seed: int | None,
        model_key: str,
        model_version: str,
        checkpoint_sha256: str,
        idempotency_key: str,
    ) -> GenerationJob:
        normalized = _validate_request(
            input_text,
            language_code,
            output_format,
            speed,
            stability,
            style,
            checkpoint_sha256,
            idempotency_key,
        )
        voice = await self._voices.get(voice_profile_id)
        if voice is None or voice.workspace_id != workspace_id:
            raise GenerationError("VOICE_NOT_FOUND", "Voice was not found.")
        if voice.status in {"revoked", "archived"} or voice.consent_status != "accepted":
            raise GenerationError(
                "VOICE_CONSENT_REVOKED", "Voice consent does not permit generation."
            )
        if voice.status != "ready":
            raise GenerationError("VOICE_NOT_READY", "Voice is not ready for generation.")
        if language_code != voice.language_code:
            raise GenerationError("LANGUAGE_UNSUPPORTED", "Voice does not support this language.")
        try:
            model = self._models.resolve(model_key, model_version, normalized[6])
        except ModelRegistryError as error:
            raise GenerationError(error.code, str(error)) from error
        if model.supported_languages and language_code not in model.supported_languages:
            raise GenerationError("LANGUAGE_UNSUPPORTED", "Model does not support this language.")
        fingerprint = _fingerprint(
            workspace_id,
            actor_id,
            voice_profile_id,
            project_id,
            normalized,
            model.identity(),
        )
        async with self._lock:
            existing = await self._store.get_idempotent(workspace_id, normalized[7])
            if existing is not None:
                previous_fingerprint, previous_job = existing
                if previous_fingerprint != fingerprint:
                    raise GenerationError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with different generation metadata.",
                    )
                return previous_job
            now = datetime.now(UTC)
            job = GenerationJob(
                id=uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                voice_profile_id=voice_profile_id,
                requested_by=actor_id,
                status="created",
                input_text=normalized[0],
                input_text_sha256=hashlib.sha256(normalized[0].encode()).hexdigest(),
                language_code=normalized[1],
                output_format=normalized[2],
                speed=normalized[3],
                stability=normalized[4],
                style=normalized[5],
                seed=seed,
                model_key=model.model_key,
                model_version=model.version,
                checkpoint_sha256=model.checkpoint_sha256,
                model_metadata=model.job_metadata(),
                idempotency_key=normalized[7],
                error_code=None,
                error_message_safe=None,
                retryable=False,
                queue_attempts=0,
                created_at=now,
            )
            await self._store.put(job)
            await self._store.put_idempotent(workspace_id, normalized[7], fingerprint, job)
            await self._record(job, actor_id, "generation.created", {"status": job.status})
            return job

    async def get(self, job_id: UUID) -> GenerationJob | None:
        return await self._store.get(job_id)

    async def list(
        self,
        workspace_id: UUID,
        *,
        status: GenerationStatus | None = None,
        limit: int = 50,
    ) -> tuple[GenerationJob, ...]:
        if not 1 <= limit <= 100:
            raise GenerationError("GENERATION_LIMIT_INVALID", "Limit must be between 1 and 100.")
        jobs = await self._store.list(workspace_id)
        if status is not None:
            jobs = tuple(job for job in jobs if job.status == status)
        return jobs[:limit]

    async def cancel(self, job_id: UUID, actor_id: UUID) -> GenerationJob:
        async with self._lock:
            job = await self._require(job_id)
            if job.status in {"cancel_requested", "canceled"}:
                return job
            if job.status not in {"created", "queued", "processing"}:
                raise GenerationError(
                    "GENERATION_STATE_CONFLICT",
                    "Generation cannot be canceled in its current state.",
                )
            updated = replace(job, status="cancel_requested")
            await self._store.put(updated)
            await self._record(updated, actor_id, "generation.cancel_requested", {})
            return updated

    async def retry(self, job_id: UUID, actor_id: UUID) -> GenerationJob:
        async with self._lock:
            job = await self._require(job_id)
            if job.status == "canceled":
                retryable = True
            elif job.status == "failed":
                retryable = job.retryable
            else:
                retryable = False
            if not retryable:
                raise GenerationError("GENERATION_NOT_RETRYABLE", "Generation is not retryable.")
            updated = replace(
                job,
                status="created",
                error_code=None,
                error_message_safe=None,
                retryable=False,
                queue_attempts=job.queue_attempts + 1,
                started_at=None,
                completed_at=None,
                canceled_at=None,
            )
            await self._store.put(updated)
            await self._record(
                updated,
                actor_id,
                "generation.retried",
                {"queue_attempts": updated.queue_attempts},
            )
            return updated

    async def transition(
        self,
        job_id: UUID,
        actor_id: UUID,
        target: GenerationStatus,
        *,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        retryable: bool = False,
    ) -> GenerationJob:
        async with self._lock:
            job = await self._require(job_id)
            if target == job.status:
                return job
            if target not in _TRANSITIONS[job.status]:
                raise GenerationError(
                    "GENERATION_STATE_CONFLICT",
                    f"Generation cannot transition from {job.status} to {target}.",
                )
            now = datetime.now(UTC)
            updated = replace(
                job,
                status=target,
                started_at=job.started_at
                or (now if target in {"processing", "cancel_requested"} else None),
                completed_at=(
                    now
                    if target in {"succeeded", "failed", "canceled"}
                    else job.completed_at
                ),
                canceled_at=now if target == "canceled" else job.canceled_at,
                error_code=error_code,
                error_message_safe=error_message_safe,
                retryable=retryable,
            )
            await self._store.put(updated)
            await self._record(updated, actor_id, "generation.status_changed", {"status": target})
            return updated

    async def _require(self, job_id: UUID) -> GenerationJob:
        job = await self._store.get(job_id)
        if job is None:
            raise GenerationError("GENERATION_NOT_FOUND", "Generation was not found.")
        return job

    async def _record(
        self,
        job: GenerationJob,
        actor_id: UUID,
        action: str,
        details: Mapping[str, object],
    ) -> None:
        await self._store.audit(
            GenerationAuditEvent(
                uuid4(),
                job.workspace_id,
                actor_id,
                action,
                job.id,
                datetime.now(UTC),
                details,
            )
        )


def _validate_request(
    input_text: str,
    language_code: str,
    output_format: str,
    speed: float,
    stability: float | None,
    style: float | None,
    checkpoint_sha256: str,
    idempotency_key: str,
) -> tuple[str, str, OutputFormat, float, float | None, float | None, str, str]:
    try:
        text = normalize_generation_text(input_text)
    except GenerationTextValidationError as error:
        raise GenerationError(
            "INPUT_TEXT_INVALID", "Text must be valid Unicode between 1 and 10,000 characters."
        ) from error
    if not _LANGUAGE_RE.fullmatch(language_code.strip()):
        raise GenerationError("LANGUAGE_INVALID", "Language code is invalid.")
    if output_format not in {"wav", "mp3"}:
        raise GenerationError("OUTPUT_FORMAT_INVALID", "Output format must be WAV or MP3.")
    if not 0.5 <= speed <= 2.0:
        raise GenerationError("SPEED_INVALID", "Speed must be between 0.5 and 2.0.")
    for name, value in (("stability", stability), ("style", style)):
        if value is not None and not 0 <= value <= 1:
            raise GenerationError(
                f"{name.upper()}_INVALID", f"{name.title()} must be between 0 and 1."
            )
    normalized_sha = checkpoint_sha256.strip().lower()
    if not _SHA256_RE.fullmatch(normalized_sha):
        raise GenerationError("MODEL_SHA_INVALID", "Model checkpoint SHA-256 is invalid.")
    if not 16 <= len(idempotency_key) <= 128 or not _VISIBLE_IDEMPOTENCY_RE.fullmatch(
        idempotency_key
    ):
        raise GenerationError(
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be 16–128 visible characters.",
        )
    return (
        text,
        language_code.strip(),
        cast(OutputFormat, output_format),
        speed,
        stability,
        style,
        normalized_sha,
        idempotency_key,
    )


def _fingerprint(*values: object) -> str:
    return hashlib.sha256(repr(values).encode()).hexdigest()
