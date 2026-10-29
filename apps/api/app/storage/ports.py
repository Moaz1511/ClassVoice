"""Storage contracts shared by S3-compatible and Supabase adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

SIGNED_URL_TTL_SECONDS = 600
ALLOWED_BUCKETS = frozenset({"voice-inputs", "voice-derived", "generated-audio", "exports"})


class StorageError(RuntimeError):
    """A safe, provider-neutral storage failure."""


def validate_object_key(key: str) -> str:
    """Reject path traversal and ambiguous object names before signing."""

    if not key or len(key) > 1024 or key.startswith("/") or "\\" in key:
        raise StorageError("object key is invalid")
    if any(ord(character) < 32 for character in key):
        raise StorageError("object key is invalid")
    if any(part in {"", ".", ".."} for part in key.split("/")):
        raise StorageError("object key is invalid")
    return key


@dataclass(frozen=True, slots=True)
class SignedObjectUrl:
    """A short-lived URL and the method/headers required to use it."""

    url: str
    bucket: str
    key: str
    method: str
    expires_at: datetime
    headers: Mapping[str, str]


class StorageAdapter(Protocol):
    """Provider-neutral private object storage operations."""

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
    ) -> None: ...

    async def create_upload_url(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
    ) -> SignedObjectUrl: ...

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl: ...
