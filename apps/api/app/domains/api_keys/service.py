"""Hash-backed API-key lifecycle service.

The in-memory store is the local boundary used by the control-plane tests. A
database adapter can implement the same store protocol without changing the
HTTP contract. Plaintext secrets are returned only in ``ApiKeyIssue`` and are
never retained by the service or included in metadata responses.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.authorization import AuthPrincipal

ApiKeyStatus = Literal["active", "revoked", "expired"]

API_KEY_SCOPES = frozenset(
    {
        "voices:read",
        "voices:write",
        "projects:read",
        "projects:write",
        "generations:create",
        "generations:read",
        "api_keys:read",
        "api_keys:write",
        "webhooks:read",
        "webhooks:write",
    }
)
MAX_API_KEY_NAME = 100
MAX_API_KEY_SCOPES = 20
MAX_API_KEY_LIFETIME = timedelta(days=365)
API_KEY_PREFIX_LENGTH = 12


class ApiKeyError(ValueError):
    """A stable, user-safe API-key error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    key_prefix: str
    key_hash: str
    scopes: frozenset[str]
    status: ApiKeyStatus
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        """Serialize metadata without the hash or plaintext secret."""

        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "created_by": str(self.created_by),
            "name": self.name,
            "key_prefix": self.key_prefix,
            "scopes": sorted(self.scopes),
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ApiKeyIssue:
    """The one-time issuance result containing the only plaintext secret."""

    record: ApiKeyRecord
    secret: str


class ApiKeyStore(Protocol):
    async def get(self, key_id: UUID) -> ApiKeyRecord | None: ...

    async def get_by_prefix(self, key_prefix: str) -> ApiKeyRecord | None: ...

    async def list_workspace(self, workspace_id: UUID) -> tuple[ApiKeyRecord, ...]: ...

    async def put(self, record: ApiKeyRecord) -> None: ...


class InMemoryApiKeyStore:
    """Concurrency-safe local store used until SQL repository wiring."""

    def __init__(self) -> None:
        self._records: dict[UUID, ApiKeyRecord] = {}
        self._prefixes: dict[str, UUID] = {}
        self._lock = asyncio.Lock()

    async def get(self, key_id: UUID) -> ApiKeyRecord | None:
        async with self._lock:
            return self._records.get(key_id)

    async def get_by_prefix(self, key_prefix: str) -> ApiKeyRecord | None:
        async with self._lock:
            key_id = self._prefixes.get(key_prefix)
            return self._records.get(key_id) if key_id is not None else None

    async def list_workspace(self, workspace_id: UUID) -> tuple[ApiKeyRecord, ...]:
        async with self._lock:
            records = [
                record for record in self._records.values() if record.workspace_id == workspace_id
            ]
            records.sort(key=lambda record: record.created_at, reverse=True)
            return tuple(records)

    async def put(self, record: ApiKeyRecord) -> None:
        async with self._lock:
            previous = self._records.get(record.id)
            if previous is not None and previous.key_prefix != record.key_prefix:
                self._prefixes.pop(previous.key_prefix, None)
            self._records[record.id] = record
            self._prefixes[record.key_prefix] = record.id


class ApiKeyService:
    """Issue, authenticate, list, and revoke scoped workspace API keys."""

    _hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=2,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )

    def __init__(
        self,
        store: ApiKeyStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._now = _utc_now if now is None else now

    async def create(
        self,
        *,
        workspace_id: UUID,
        created_by: UUID,
        name: str,
        scopes: Sequence[str],
        expires_at: datetime | None,
    ) -> ApiKeyIssue:
        normalized_name = name.strip()
        if not 1 <= len(normalized_name) <= MAX_API_KEY_NAME:
            raise ApiKeyError("API_KEY_NAME_INVALID", "API key name must be 1–100 characters.")
        normalized_scopes = _normalize_scopes(scopes)
        now = _normalize_datetime(self._now())
        normalized_expiry = _normalize_expiry(expires_at, now)

        for _ in range(5):
            secret = f"cv_live_{secrets.token_urlsafe(32)}"
            key_prefix = secret[:API_KEY_PREFIX_LENGTH]
            if await self._store.get_by_prefix(key_prefix) is not None:
                continue
            record = ApiKeyRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=created_by,
                name=normalized_name,
                key_prefix=key_prefix,
                key_hash=self._hasher.hash(secret),
                scopes=frozenset(normalized_scopes),
                status="active",
                expires_at=normalized_expiry,
                last_used_at=None,
                revoked_at=None,
                created_at=now,
            )
            await self._store.put(record)
            return ApiKeyIssue(record=record, secret=secret)
        raise ApiKeyError("API_KEY_ISSUE_FAILED", "A unique API key could not be issued.")

    async def authenticate(self, secret: str) -> AuthPrincipal:
        if not secret or len(secret) > 256 or not secret.startswith("cv_live_"):
            raise ApiKeyError("API_KEY_INVALID", "API key is invalid.")
        key_prefix = secret[:API_KEY_PREFIX_LENGTH]
        record = await self._store.get_by_prefix(key_prefix)
        if record is None:
            raise ApiKeyError("API_KEY_INVALID", "API key is invalid.")
        now = _normalize_datetime(self._now())
        if record.status == "revoked":
            raise ApiKeyError("API_KEY_REVOKED", "API key has been revoked.")
        if record.expires_at is not None and record.expires_at <= now:
            if record.status != "expired":
                await self._store.put(replace(record, status="expired"))
            raise ApiKeyError("API_KEY_EXPIRED", "API key has expired.")
        try:
            self._hasher.verify(record.key_hash, secret)
        except (InvalidHashError, VerificationError):
            raise ApiKeyError("API_KEY_INVALID", "API key is invalid.") from None
        updated = replace(record, last_used_at=now)
        await self._store.put(updated)
        return AuthPrincipal(
            subject=record.created_by,
            scopes=record.scopes,
            workspace_id=record.workspace_id,
            api_key_id=record.id,
        )

    async def list(self, workspace_id: UUID) -> tuple[ApiKeyRecord, ...]:
        records = await self._store.list_workspace(workspace_id)
        now = _normalize_datetime(self._now())
        refreshed: list[ApiKeyRecord] = []
        for record in records:
            if (
                record.status == "active"
                and record.expires_at is not None
                and record.expires_at <= now
            ):
                record = replace(record, status="expired")
                await self._store.put(record)
            refreshed.append(record)
        return tuple(refreshed)

    async def get(self, key_id: UUID) -> ApiKeyRecord | None:
        record = await self._store.get(key_id)
        if (
            record is not None
            and record.status == "active"
            and record.expires_at is not None
            and record.expires_at <= _normalize_datetime(self._now())
        ):
            record = replace(record, status="expired")
            await self._store.put(record)
        return record

    async def revoke(self, key_id: UUID, workspace_id: UUID) -> ApiKeyRecord:
        record = await self._store.get(key_id)
        if record is None or record.workspace_id != workspace_id:
            raise ApiKeyError("API_KEY_NOT_FOUND", "API key was not found.")
        if record.status == "revoked":
            return record
        revoked = replace(record, status="revoked", revoked_at=_normalize_datetime(self._now()))
        await self._store.put(revoked)
        return revoked


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiKeyError("API_KEY_TIME_INVALID", "API key timestamps must include a timezone.")
    return value.astimezone(UTC)


def _normalize_expiry(value: datetime | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    expiry = _normalize_datetime(value)
    if expiry <= now:
        raise ApiKeyError("API_KEY_EXPIRY_INVALID", "API key expiry must be in the future.")
    if expiry > now + MAX_API_KEY_LIFETIME:
        raise ApiKeyError("API_KEY_EXPIRY_INVALID", "API key expiry cannot exceed 365 days.")
    return expiry


def _normalize_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))
    if not normalized:
        raise ApiKeyError("API_KEY_SCOPES_EMPTY", "At least one API key scope is required.")
    if len(normalized) > MAX_API_KEY_SCOPES:
        raise ApiKeyError("API_KEY_SCOPES_INVALID", "Too many API key scopes were requested.")
    unknown = sorted(set(normalized) - API_KEY_SCOPES)
    if unknown:
        raise ApiKeyError(
            "API_KEY_SCOPE_INVALID",
            "One or more requested API key scopes are not supported.",
        )
    return tuple(sorted(normalized))
