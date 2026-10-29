"""Workspace-scoped projects and explicitly saved editor settings."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.domains.voices.lifecycle import VoiceLifecycleService

ProjectOutputFormat = Literal["wav", "mp3"]
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2}|-[A-Z][a-z]{2,4})?$")
_VISIBLE_IDEMPOTENCY_RE = re.compile(r"^[^\x00-\x20\x7f]+$")


class ProjectError(ValueError):
    """A stable, user-safe project validation or lifecycle error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EditorSettings:
    """The server-persisted portion of the Studio editor state.

    Draft text is deliberately absent.  The web editor keeps unsaved text in
    a local project-keyed draft and sends text only when creating a generation.
    """

    voice_profile_id: UUID | None = None
    language_code: str = "en-US"
    output_format: ProjectOutputFormat = "wav"
    speed: float = 1.0
    stability: float | None = None
    style: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "voice_profile_id": str(self.voice_profile_id) if self.voice_profile_id else None,
            "language_code": self.language_code,
            "output_format": self.output_format,
            "speed": self.speed,
            "stability": self.stability,
            "style": self.style,
        }


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    description: str | None
    archived_at: datetime | None
    editor_settings: EditorSettings
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "created_by": str(self.created_by),
            "name": self.name,
            "description": self.description,
            "archived": self.archived_at is not None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "editor_settings": self.editor_settings.as_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ProjectAuditEvent:
    id: UUID
    workspace_id: UUID
    actor_id: UUID
    action: str
    project_id: UUID
    created_at: datetime
    details: Mapping[str, object]


class ProjectStore(Protocol):
    async def get(self, project_id: UUID) -> Project | None: ...

    async def list(self, workspace_id: UUID, *, include_archived: bool) -> tuple[Project, ...]: ...

    async def put(self, project: Project) -> None: ...

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, Project] | None: ...

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, project: Project
    ) -> None: ...

    async def audit(self, event: ProjectAuditEvent) -> None: ...


class InMemoryProjectStore:
    """Deterministic store used until the SQL project repository is wired."""

    def __init__(self) -> None:
        self._projects: dict[UUID, Project] = {}
        self._idempotency: dict[tuple[UUID, str], tuple[str, Project]] = {}
        self._audit_events: list[ProjectAuditEvent] = []
        self._lock = asyncio.Lock()

    async def get(self, project_id: UUID) -> Project | None:
        async with self._lock:
            return self._projects.get(project_id)

    async def list(self, workspace_id: UUID, *, include_archived: bool) -> tuple[Project, ...]:
        async with self._lock:
            projects = [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace_id
                and (include_archived or project.archived_at is None)
            ]
            projects.sort(key=lambda project: project.updated_at, reverse=True)
            return tuple(projects)

    async def put(self, project: Project) -> None:
        async with self._lock:
            self._projects[project.id] = project

    async def get_idempotent(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, Project] | None:
        async with self._lock:
            return self._idempotency.get((workspace_id, idempotency_key))

    async def put_idempotent(
        self, workspace_id: UUID, idempotency_key: str, fingerprint: str, project: Project
    ) -> None:
        async with self._lock:
            self._idempotency[(workspace_id, idempotency_key)] = (fingerprint, project)

    async def audit(self, event: ProjectAuditEvent) -> None:
        async with self._lock:
            self._audit_events.append(event)

    async def audit_events(self) -> tuple[ProjectAuditEvent, ...]:
        async with self._lock:
            return tuple(self._audit_events)


class ProjectService:
    def __init__(self, store: ProjectStore, voices: VoiceLifecycleService) -> None:
        self._store = store
        self._voices = voices
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        name: str,
        description: str | None,
        editor_settings: EditorSettings | None,
        idempotency_key: str,
    ) -> Project:
        normalized_name = _validate_name(name)
        normalized_description = _validate_description(description)
        normalized_key = _validate_idempotency_key(idempotency_key)
        settings = await self._validate_settings(
            workspace_id, editor_settings or EditorSettings()
        )
        fingerprint = _fingerprint(
            workspace_id,
            actor_id,
            normalized_name,
            normalized_description,
            settings.as_dict(),
        )
        async with self._lock:
            existing = await self._store.get_idempotent(workspace_id, normalized_key)
            if existing is not None:
                previous_fingerprint, previous_project = existing
                if previous_fingerprint != fingerprint:
                    raise ProjectError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with different project metadata.",
                    )
                return previous_project
            now = datetime.now(UTC)
            project = Project(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=actor_id,
                name=normalized_name,
                description=normalized_description,
                archived_at=None,
                editor_settings=settings,
                created_at=now,
                updated_at=now,
            )
            await self._store.put(project)
            await self._store.put_idempotent(workspace_id, normalized_key, fingerprint, project)
            await self._record(project, actor_id, "project.created", {})
            return project

    async def get(self, project_id: UUID) -> Project | None:
        return await self._store.get(project_id)

    async def list(
        self,
        workspace_id: UUID,
        *,
        include_archived: bool = False,
        limit: int = 50,
    ) -> tuple[Project, ...]:
        if not 1 <= limit <= 100:
            raise ProjectError("PROJECT_LIMIT_INVALID", "Limit must be between 1 and 100.")
        projects = await self._store.list(workspace_id, include_archived=include_archived)
        return projects[:limit]

    async def update(
        self,
        project_id: UUID,
        actor_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        description_provided: bool = False,
        archived: bool | None = None,
        editor_settings: EditorSettings | None = None,
    ) -> Project:
        if (
            name is None
            and not description_provided
            and archived is None
            and editor_settings is None
        ):
            raise ProjectError("PROJECT_UPDATE_EMPTY", "At least one project field is required.")
        async with self._lock:
            project = await self._require(project_id)
            updated = project
            if name is not None:
                updated = replace(updated, name=_validate_name(name))
            if description_provided:
                updated = replace(updated, description=_validate_description(description))
            if archived is not None:
                updated = replace(
                    updated,
                    archived_at=datetime.now(UTC) if archived else None,
                )
            if editor_settings is not None:
                settings = await self._validate_settings(project.workspace_id, editor_settings)
                updated = replace(updated, editor_settings=settings)
            updated = replace(updated, updated_at=datetime.now(UTC))
            await self._store.put(updated)
            details: dict[str, object] = {}
            if archived is not None:
                details["archived"] = archived
            if editor_settings is not None:
                details["editor_settings_saved"] = True
            await self._record(updated, actor_id, "project.updated", details)
            return updated

    async def save_editor_settings(
        self,
        project_id: UUID,
        actor_id: UUID,
        settings: EditorSettings,
    ) -> Project:
        return await self.update(
            project_id,
            actor_id,
            editor_settings=settings,
        )

    async def _validate_settings(
        self,
        workspace_id: UUID,
        settings: EditorSettings,
    ) -> EditorSettings:
        language_code = settings.language_code.strip()
        if not _LANGUAGE_RE.fullmatch(language_code):
            raise ProjectError("LANGUAGE_INVALID", "Language code is invalid.")
        if settings.output_format not in {"wav", "mp3"}:
            raise ProjectError("OUTPUT_FORMAT_INVALID", "Output format must be WAV or MP3.")
        if not 0.5 <= settings.speed <= 2.0:
            raise ProjectError("SPEED_INVALID", "Speed must be between 0.5 and 2.0.")
        for name, value in (("stability", settings.stability), ("style", settings.style)):
            if value is not None and not 0 <= value <= 1:
                raise ProjectError(
                    f"{name.upper()}_INVALID", f"{name.title()} must be between 0 and 1."
                )
        if settings.voice_profile_id is not None:
            voice = await self._voices.get(settings.voice_profile_id)
            if voice is None or voice.workspace_id != workspace_id:
                raise ProjectError("VOICE_NOT_FOUND", "Voice was not found.")
            if voice.status in {"revoked", "archived"} or voice.consent_status != "accepted":
                raise ProjectError(
                    "VOICE_CONSENT_REVOKED", "Voice consent does not permit generation."
                )
            if voice.status != "ready":
                raise ProjectError("VOICE_NOT_READY", "Voice is not ready for generation.")
            if voice.language_code != language_code:
                raise ProjectError(
                    "LANGUAGE_UNSUPPORTED", "Voice does not support this language."
                )
        return replace(settings, language_code=language_code)

    async def _require(self, project_id: UUID) -> Project:
        project = await self._store.get(project_id)
        if project is None:
            raise ProjectError("PROJECT_NOT_FOUND", "Project was not found.")
        return project

    async def _record(
        self,
        project: Project,
        actor_id: UUID,
        action: str,
        details: Mapping[str, object],
    ) -> None:
        await self._store.audit(
            ProjectAuditEvent(
                uuid4(),
                project.workspace_id,
                actor_id,
                action,
                project.id,
                datetime.now(UTC),
                details,
            )
        )


def _validate_name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 160:
        raise ProjectError("PROJECT_NAME_INVALID", "Project name must be 1–160 characters.")
    return normalized


def _validate_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 2_000:
        raise ProjectError(
            "PROJECT_DESCRIPTION_INVALID", "Project description cannot exceed 2,000 characters."
        )
    return normalized or None


def _validate_idempotency_key(value: str) -> str:
    if not 16 <= len(value) <= 128 or not _VISIBLE_IDEMPOTENCY_RE.fullmatch(value):
        raise ProjectError(
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be 16–128 visible characters.",
        )
    return value


def _fingerprint(*values: object) -> str:
    return hashlib.sha256(repr(values).encode()).hexdigest()
