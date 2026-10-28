"""Validated, idempotent upload-intent service for quarantined voice samples."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.storage.ports import SignedObjectUrl, StorageAdapter, StorageError

MAX_UPLOAD_BYTES = 25_000_000
QUARANTINE_BUCKET = "voice-inputs"
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$")
_CONTENT_TYPES: dict[str, frozenset[str]] = {
    ".wav": frozenset({"audio/wav", "audio/x-wav"}),
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a"}),
}


class UploadIntentError(ValueError):
    """A user-safe upload-intent validation or idempotency error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class UploadIntentRequest:
    workspace_id: UUID
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class UploadIntent:
    upload_id: UUID
    workspace_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    object_key: str
    signed_url: SignedObjectUrl

    def as_dict(self) -> dict[str, object]:
        return {
            "upload_id": str(self.upload_id),
            "workspace_id": str(self.workspace_id),
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "bucket": self.signed_url.bucket,
            "object_key": self.object_key,
            "upload": {
                "url": self.signed_url.url,
                "method": self.signed_url.method,
                "headers": dict(self.signed_url.headers),
                "expires_at": self.signed_url.expires_at.isoformat(),
            },
        }


class UploadIntentStore(Protocol):
    async def get(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, UploadIntent] | None: ...

    async def put(
        self,
        workspace_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        intent: UploadIntent,
    ) -> None: ...


class InMemoryUploadIntentStore:
    """Deterministic local store; production persistence is added with the upload table."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, str], tuple[str, UploadIntent]] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, workspace_id: UUID, idempotency_key: str
    ) -> tuple[str, UploadIntent] | None:
        async with self._lock:
            return self._records.get((workspace_id, idempotency_key))

    async def put(
        self,
        workspace_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        intent: UploadIntent,
    ) -> None:
        async with self._lock:
            self._records[(workspace_id, idempotency_key)] = (fingerprint, intent)


class UploadIntentService:
    def __init__(self, storage: StorageAdapter, store: UploadIntentStore) -> None:
        self._storage = storage
        self._store = store
        self._lock = asyncio.Lock()

    async def create(self, request: UploadIntentRequest, idempotency_key: str) -> UploadIntent:
        normalized_key = self._validate_idempotency_key(idempotency_key)
        normalized_request = validate_upload_request(request)
        fingerprint = _fingerprint(normalized_request)
        async with self._lock:
            existing = await self._store.get(request.workspace_id, normalized_key)
            if existing is not None:
                previous_fingerprint, previous_intent = existing
                if previous_fingerprint != fingerprint:
                    raise UploadIntentError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with different upload metadata.",
                    )
                return previous_intent
            object_key = _quarantine_key(request.workspace_id, normalized_request.filename)
            try:
                signed_url = await self._storage.create_upload_url(
                    QUARANTINE_BUCKET,
                    object_key,
                    content_type=normalized_request.content_type,
                )
            except StorageError as error:
                raise UploadIntentError(
                    "STORAGE_SIGNING_FAILED", "Upload URL could not be created."
                ) from error
            intent = UploadIntent(
                upload_id=uuid4(),
                workspace_id=request.workspace_id,
                filename=normalized_request.filename,
                content_type=normalized_request.content_type,
                size_bytes=normalized_request.size_bytes,
                object_key=object_key,
                signed_url=signed_url,
            )
            await self._store.put(request.workspace_id, normalized_key, fingerprint, intent)
            return intent

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if not 16 <= len(value) <= 128 or any(ord(character) < 33 for character in value):
            raise UploadIntentError(
                "IDEMPOTENCY_KEY_INVALID",
                "Idempotency-Key must be 16–128 visible characters.",
            )
        return value


def validate_upload_request(request: UploadIntentRequest) -> UploadIntentRequest:
    filename = request.filename.strip()
    content_type = request.content_type.strip().lower()
    if (
        not _FILENAME_RE.fullmatch(filename)
        or "/" in filename
        or "\\" in filename
        or "://" in filename
    ):
        raise UploadIntentError(
            "UPLOAD_FILENAME_INVALID", "Filename must be a local audio filename."
        )
    suffix = filename.lower()[filename.rfind(".") :]
    allowed_types = _CONTENT_TYPES.get(suffix)
    if allowed_types is None or content_type not in allowed_types:
        raise UploadIntentError(
            "UPLOAD_TYPE_INVALID", "Only WAV, MP3, and M4A audio types are accepted."
        )
    if request.size_bytes <= 0 or request.size_bytes > MAX_UPLOAD_BYTES:
        raise UploadIntentError(
            "UPLOAD_SIZE_INVALID", "Audio upload must be between 1 byte and 25 MB."
        )
    return UploadIntentRequest(request.workspace_id, filename, content_type, request.size_bytes)


def _fingerprint(request: UploadIntentRequest) -> str:
    payload = {
        "workspace_id": str(request.workspace_id),
        "filename": request.filename,
        "content_type": request.content_type,
        "size_bytes": request.size_bytes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _quarantine_key(workspace_id: UUID, filename: str) -> str:
    return f"quarantine/{workspace_id}/{uuid4().hex}/{filename}"
