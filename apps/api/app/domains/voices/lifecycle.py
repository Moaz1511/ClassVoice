"""Voice profile lifecycle rules and the local persistence port.

The in-memory store keeps the API executable before the SQL repository is
wired.  The service owns state transitions, authorization-neutral validation,
idempotent creation, and audit/cascade intents so the later repository can
preserve the same contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

VoiceStatus = Literal[
    "draft", "validating", "processing", "ready", "rejected", "revoked", "archived"
]
ConsentStatus = Literal["accepted", "revoked", "expired"]
_VOICE_NAME_RE = re.compile(r"^\S(?:.{0,118}\S)?$", re.DOTALL)
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2}|-[A-Z][a-z]{2,4})?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VISIBLE_IDEMPOTENCY_RE = re.compile(r"^[^\x00-\x20\x7f]+$")

_TRANSITIONS: dict[VoiceStatus, frozenset[VoiceStatus]] = {
    "draft": frozenset({"validating", "archived"}),
    "validating": frozenset({"processing", "rejected", "draft"}),
    "processing": frozenset({"ready", "rejected"}),
    "ready": frozenset({"archived", "revoked"}),
    "rejected": frozenset({"draft", "archived"}),
    "archived": frozenset({"draft", "revoked"}),
    "revoked": frozenset(),
}


class VoiceLifecycleError(ValueError):
    """A stable, user-safe voice lifecycle error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VoiceReadiness:
    """Evidence required by the database invariant before a voice is ready."""

    accepted_consent: bool
    approved_model: bool
    available_primary_sample: bool
    active_consent_record: bool

    @property
    def complete(self) -> bool:
        return all(
            (
                self.accepted_consent,
                self.approved_model,
                self.available_primary_sample,
                self.active_consent_record,
            )
        )


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    language_code: str
    status: VoiceStatus
    consent_status: ConsentStatus
    consent_statement_version: str
    consent_attestation_text_hash: str
    reference_upload_id: UUID | None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None
    archived_at: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "created_by": str(self.created_by),
            "name": self.name,
            "language_code": self.language_code,
            "status": self.status,
            "consent_status": self.consent_status,
            "consent": {
                "statement_version": self.consent_statement_version,
                "attestation_text_hash": self.consent_attestation_text_hash,
            },
            "reference_upload_id": (
                str(self.reference_upload_id) if self.reference_upload_id is not None else None
            ),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


@dataclass(frozen=True, slots=True)
class VoiceAuditEvent:
    id: UUID
    workspace_id: UUID
    actor_id: UUID
    action: str
    voice_id: UUID
    created_at: datetime
    details: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class VoiceCascadeTask:
    voice_id: UUID
    workspace_id: UUID
    queued_at: datetime


class VoiceStore(Protocol):
    async def get(self, voice_id: UUID) -> VoiceProfile | None: ...

    async def list(self, workspace_id: UUID) -> tuple[VoiceProfile, ...]: ...

    async def put(self, voice: VoiceProfile) -> None: ...

    async def remove(self, voice_id: UUID) -> VoiceProfile | None: ...

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, VoiceProfile] | None: ...

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, voice: VoiceProfile
    ) -> None: ...

    async def audit(self, event: VoiceAuditEvent) -> None: ...

    async def enqueue_cascade(self, task: VoiceCascadeTask) -> None: ...


class InMemoryVoiceStore:
    """Concurrency-safe local store used until the SQL repository is connected."""

    def __init__(self) -> None:
        self._voices: dict[UUID, VoiceProfile] = {}
        self._idempotency: dict[tuple[UUID, str], tuple[str, VoiceProfile]] = {}
        self._audit_events: list[VoiceAuditEvent] = []
        self._cascade_tasks: list[VoiceCascadeTask] = []
        self._lock = asyncio.Lock()

    async def get(self, voice_id: UUID) -> VoiceProfile | None:
        async with self._lock:
            return self._voices.get(voice_id)

    async def list(self, workspace_id: UUID) -> tuple[VoiceProfile, ...]:
        async with self._lock:
            voices = [
                voice for voice in self._voices.values() if voice.workspace_id == workspace_id
            ]
            voices.sort(key=lambda voice: voice.updated_at, reverse=True)
            return tuple(voices)

    async def put(self, voice: VoiceProfile) -> None:
        async with self._lock:
            self._voices[voice.id] = voice

    async def remove(self, voice_id: UUID) -> VoiceProfile | None:
        async with self._lock:
            return self._voices.pop(voice_id, None)

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, VoiceProfile] | None:
        async with self._lock:
            return self._idempotency.get((workspace_id, idempotency_key))

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, voice: VoiceProfile
    ) -> None:
        async with self._lock:
            self._idempotency[(workspace_id, idempotency_key)] = (fingerprint, voice)

    async def audit(self, event: VoiceAuditEvent) -> None:
        async with self._lock:
            self._audit_events.append(event)

    async def enqueue_cascade(self, task: VoiceCascadeTask) -> None:
        async with self._lock:
            self._cascade_tasks.append(task)

    async def audit_events(self) -> tuple[VoiceAuditEvent, ...]:
        async with self._lock:
            return tuple(self._audit_events)

    async def cascade_tasks(self) -> tuple[VoiceCascadeTask, ...]:
        async with self._lock:
            return tuple(self._cascade_tasks)


class VoiceLifecycleService:
    def __init__(self, store: VoiceStore) -> None:
        self._store = store
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        name: str,
        language_code: str,
        consent_statement_version: str,
        consent_attestation_text_hash: str,
        reference_upload_id: UUID | None,
        idempotency_key: str,
    ) -> VoiceProfile:
        key = _validate_idempotency_key(idempotency_key)
        normalized = _validate_create_values(
            name,
            language_code,
            consent_statement_version,
            consent_attestation_text_hash,
        )
        fingerprint = _fingerprint(
            workspace_id,
            actor_id,
            normalized[0],
            normalized[1],
            normalized[2],
            normalized[3],
            reference_upload_id,
        )
        async with self._lock:
            existing = await self._store.get_idempotent(workspace_id, key)
            if existing is not None:
                previous_fingerprint, previous_voice = existing
                if previous_fingerprint != fingerprint:
                    raise VoiceLifecycleError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with different voice metadata.",
                    )
                return previous_voice
            now = datetime.now(UTC)
            voice = VoiceProfile(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=actor_id,
                name=normalized[0],
                language_code=normalized[1],
                status="draft",
                consent_status="accepted",
                consent_statement_version=normalized[2],
                consent_attestation_text_hash=normalized[3],
                reference_upload_id=reference_upload_id,
                created_at=now,
                updated_at=now,
            )
            await self._store.put(voice)
            await self._store.put_idempotent(workspace_id, key, fingerprint, voice)
            await self._record(voice, actor_id, "voice.created", {"status": voice.status})
            return voice

    async def get(self, voice_id: UUID) -> VoiceProfile | None:
        return await self._store.get(voice_id)

    async def list(
        self, workspace_id: UUID, *, include_archived: bool = False
    ) -> tuple[VoiceProfile, ...]:
        voices = await self._store.list(workspace_id)
        if include_archived:
            return voices
        return tuple(voice for voice in voices if voice.status != "archived")

    async def update(
        self,
        voice_id: UUID,
        actor_id: UUID,
        *,
        name: str | None = None,
        language_code: str | None = None,
        status: Literal["draft", "archived"] | None = None,
    ) -> VoiceProfile:
        async with self._lock:
            voice = await self._require(voice_id)
            if voice.status == "revoked":
                raise VoiceLifecycleError("VOICE_REVOKED", "A revoked voice cannot be updated.")
            next_name = voice.name if name is None else _validate_name(name)
            next_language = (
                voice.language_code
                if language_code is None
                else _validate_language(language_code)
            )
            next_status = voice.status
            if status is not None:
                if status == voice.status:
                    next_status = status
                elif status not in _TRANSITIONS[voice.status]:
                    raise VoiceLifecycleError(
                        "VOICE_STATE_CONFLICT",
                        f"Voice cannot transition from {voice.status} to {status}.",
                    )
                else:
                    next_status = status
            if (
                next_name == voice.name
                and next_language == voice.language_code
                and next_status == voice.status
            ):
                return voice
            now = datetime.now(UTC)
            updated = replace(
                voice,
                name=next_name,
                language_code=next_language,
                status=next_status,
                archived_at=now if next_status == "archived" else None,
                updated_at=now,
            )
            await self._store.put(updated)
            await self._record(
                updated,
                actor_id,
                "voice.updated",
                {"status": updated.status},
            )
            return updated

    async def revoke(
        self, voice_id: UUID, actor_id: UUID, *, reason: str | None = None
    ) -> VoiceProfile:
        async with self._lock:
            voice = await self._require(voice_id)
            if voice.status == "revoked":
                return voice
            if voice.status not in {
                "draft",
                "validating",
                "processing",
                "ready",
                "rejected",
                "archived",
            }:
                raise VoiceLifecycleError(
                    "VOICE_STATE_CONFLICT",
                    "Voice cannot be revoked in its current state.",
                )
            now = datetime.now(UTC)
            updated = replace(
                voice,
                status="revoked",
                consent_status="revoked",
                revoked_at=now,
                updated_at=now,
            )
            await self._store.put(updated)
            await self._record(
                updated,
                actor_id,
                "voice.revoked",
                {"reason": reason or "user_requested"},
            )
            return updated

    async def delete(self, voice_id: UUID, actor_id: UUID) -> VoiceCascadeTask:
        async with self._lock:
            voice = await self._require(voice_id)
            removed = await self._store.remove(voice.id)
            if removed is None:
                raise VoiceLifecycleError("VOICE_NOT_FOUND", "Voice was not found.")
            task = VoiceCascadeTask(voice.id, voice.workspace_id, datetime.now(UTC))
            await self._store.enqueue_cascade(task)
            await self._record(voice, actor_id, "voice.deleted", {"cascade": "queued"})
            return task

    async def transition(
        self,
        voice_id: UUID,
        actor_id: UUID,
        target: VoiceStatus,
        *,
        readiness: VoiceReadiness | None = None,
    ) -> VoiceProfile:
        async with self._lock:
            voice = await self._require(voice_id)
            if target == voice.status:
                return voice
            if target not in _TRANSITIONS[voice.status]:
                raise VoiceLifecycleError(
                    "VOICE_STATE_CONFLICT",
                    f"Voice cannot transition from {voice.status} to {target}.",
                )
            if target == "ready" and (readiness is None or not readiness.complete):
                raise VoiceLifecycleError(
                    "VOICE_NOT_READY",
                    "Voice requires accepted consent, an approved model, an available "
                    "primary sample, and active consent.",
                )
            now = datetime.now(UTC)
            updated = replace(
                voice,
                status=target,
                updated_at=now,
                archived_at=now if target == "archived" else None,
            )
            await self._store.put(updated)
            await self._record(updated, actor_id, "voice.status_changed", {"status": target})
            return updated

    async def _require(self, voice_id: UUID) -> VoiceProfile:
        voice = await self._store.get(voice_id)
        if voice is None:
            raise VoiceLifecycleError("VOICE_NOT_FOUND", "Voice was not found.")
        return voice

    async def _record(
        self,
        voice: VoiceProfile,
        actor_id: UUID,
        action: str,
        details: Mapping[str, object],
    ) -> None:
        await self._store.audit(
            VoiceAuditEvent(
                uuid4(),
                voice.workspace_id,
                actor_id,
                action,
                voice.id,
                datetime.now(UTC),
                details,
            )
        )


def _validate_create_values(
    name: str,
    language_code: str,
    consent_statement_version: str,
    consent_attestation_text_hash: str,
) -> tuple[str, str, str, str]:
    return (
        _validate_name(name),
        _validate_language(language_code),
        _validate_consent_version(consent_statement_version),
        _validate_hash(consent_attestation_text_hash),
    )


def _validate_name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 120 or not _VOICE_NAME_RE.fullmatch(normalized):
        raise VoiceLifecycleError(
            "VOICE_NAME_INVALID", "Voice name must be 1–120 visible characters."
        )
    return normalized


def _validate_language(value: str) -> str:
    normalized = value.strip()
    if not _LANGUAGE_RE.fullmatch(normalized):
        raise VoiceLifecycleError("VOICE_LANGUAGE_INVALID", "Language code is invalid.")
    return normalized


def _validate_consent_version(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 64 or any(ord(character) < 33 for character in normalized):
        raise VoiceLifecycleError(
            "CONSENT_VERSION_INVALID", "Consent statement version is invalid."
        )
    return normalized


def _validate_hash(value: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise VoiceLifecycleError(
            "CONSENT_ATTESTATION_INVALID", "Consent attestation hash must be SHA-256."
        )
    return normalized


def _validate_idempotency_key(value: str) -> str:
    if not 16 <= len(value) <= 128 or not _VISIBLE_IDEMPOTENCY_RE.fullmatch(value):
        raise VoiceLifecycleError(
            "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 16–128 visible characters."
        )
    return value


def _fingerprint(*values: object) -> str:
    payload = [str(value) if isinstance(value, UUID) else value for value in values]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
