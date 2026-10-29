"""Central, append-only audit event emission.

The application routes use this service as the boundary for the SQL
``public.audit_events`` table.  The in-memory store keeps local development
and route tests deterministic; the same event shape is used by the eventual
repository implementation.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from app.core.authorization import AuthenticatedPrincipal
from app.core.errors import request_id_for

AuditActorType = Literal["user", "api_key", "worker", "system", "moderator"]

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "password",
    "api_key",
    "apikey",
    "api_key_secret",
    "input_text",
    "audio",
    "embedding",
    "raw",
    "content",
    "body",
}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_token")


def redact_metadata(value: Mapping[str, object]) -> dict[str, object]:
    """Return bounded JSON-safe metadata with secret and payload fields removed."""

    def clean(item: object, depth: int = 0) -> object:
        if depth > 4:
            return _REDACTED
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            return item[:256]
        if isinstance(item, Mapping):
            output: dict[str, object] = {}
            for raw_key, raw_value in list(item.items())[:40]:
                key = str(raw_key)[:80]
                output[key] = _REDACTED if _is_sensitive_key(key) else clean(raw_value, depth + 1)
            return output
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray, str)):
            return [clean(child, depth + 1) for child in list(item)[:40]]
        return _REDACTED

    cleaned = clean(value)
    return cleaned if isinstance(cleaned, dict) else {}


def _digest(value: str | None) -> str | None:
    if value is None or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    workspace_id: UUID | None
    actor_type: AuditActorType
    actor_user_id: UUID | None
    actor_api_key_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: str | None
    ip_hash: str | None
    user_agent_hash: str | None
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["id"] = str(self.id)
        value["workspace_id"] = str(self.workspace_id) if self.workspace_id else None
        value["actor_user_id"] = str(self.actor_user_id) if self.actor_user_id else None
        value["actor_api_key_id"] = str(self.actor_api_key_id) if self.actor_api_key_id else None
        value["created_at"] = self.created_at.isoformat()
        value["metadata"] = dict(self.metadata)
        return value


class AuditEventStore(Protocol):
    async def append(self, event: AuditEvent) -> AuditEvent: ...

    async def list_workspace(
        self,
        workspace_id: UUID,
        limit: int = 100,
    ) -> tuple[AuditEvent, ...]: ...

    async def list_all(self, limit: int = 100) -> tuple[AuditEvent, ...]: ...


class InMemoryAuditEventStore:
    """Append-only local store; SQL persistence is the production boundary."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def append(self, event: AuditEvent) -> AuditEvent:
        async with self._lock:
            self._events.append(event)
        return event

    async def list_workspace(self, workspace_id: UUID, limit: int = 100) -> tuple[AuditEvent, ...]:
        async with self._lock:
            events = [event for event in self._events if event.workspace_id == workspace_id]
            return tuple(reversed(events[-max(1, limit) :]))

    async def list_all(self, limit: int = 100) -> tuple[AuditEvent, ...]:
        async with self._lock:
            return tuple(reversed(self._events[-max(1, limit) :]))

    async def events(self) -> tuple[AuditEvent, ...]:
        return await self.list_all(limit=max(1, len(self._events)))


class AuditService:
    def __init__(self, store: AuditEventStore) -> None:
        self._store = store

    async def emit(
        self,
        *,
        action: str,
        resource_type: str,
        workspace_id: UUID | None = None,
        resource_id: UUID | None = None,
        actor: AuthenticatedPrincipal | None = None,
        actor_type: AuditActorType | None = None,
        actor_user_id: UUID | None = None,
        actor_api_key_id: UUID | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        resolved_actor_type: AuditActorType = actor_type or (
            "api_key"
            if getattr(actor, "api_key_id", None) is not None
            else "moderator"
            if getattr(actor, "profile_role", None) == "moderator"
            else "user"
        )
        resolved_user_id = actor_user_id or getattr(actor, "subject", None)
        resolved_api_key_id = actor_api_key_id or getattr(actor, "api_key_id", None)
        if resolved_actor_type in ("worker", "system"):
            resolved_user_id = actor_user_id
            resolved_api_key_id = actor_api_key_id
        event = AuditEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            actor_type=resolved_actor_type,
            actor_user_id=resolved_user_id,
            actor_api_key_id=resolved_api_key_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            ip_hash=_digest(ip_address),
            user_agent_hash=_digest(user_agent),
            metadata=redact_metadata(metadata or {}),
        )
        return await self._store.append(event)

    async def emit_request(
        self,
        request: Any,
        *,
        action: str,
        resource_type: str,
        workspace_id: UUID | None = None,
        resource_id: UUID | None = None,
        actor: AuthenticatedPrincipal | None = None,
        actor_type: AuditActorType | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        client = getattr(request, "client", None)
        headers = getattr(request, "headers", {})
        return await self.emit(
            action=action,
            resource_type=resource_type,
            workspace_id=workspace_id,
            resource_id=resource_id,
            actor=actor,
            actor_type=actor_type,
            request_id=request_id_for(request),
            ip_address=getattr(client, "host", None),
            user_agent=headers.get("user-agent") if hasattr(headers, "get") else None,
            metadata=metadata,
        )
