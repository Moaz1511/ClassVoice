from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.domains.voices.upload_intent import (
    InMemoryUploadIntentStore,
    UploadIntentError,
    UploadIntentRequest,
    UploadIntentService,
    validate_upload_request,
)
from app.storage.ports import SignedObjectUrl


class FakeStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def create_upload_url(
        self, bucket: str, key: str, *, content_type: str
    ) -> SignedObjectUrl:
        self.calls.append((bucket, key, content_type))
        return SignedObjectUrl(
            url="https://storage.test/signed",
            bucket=bucket,
            key=key,
            method="PUT",
            expires_at=datetime.now(UTC) + timedelta(seconds=600),
            headers={"Content-Type": content_type},
        )

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl:
        raise AssertionError("download URL should not be requested")


def request(**overrides: object) -> UploadIntentRequest:
    values: dict[str, object] = {
        "workspace_id": UUID("00000000-0000-0000-0000-000000000001"),
        "filename": "lecture.wav",
        "content_type": "audio/wav",
        "size_bytes": 1024,
    }
    values.update(overrides)
    return UploadIntentRequest(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upload_intent_is_quarantined_and_idempotent() -> None:
    storage = FakeStorage()
    service = UploadIntentService(storage, InMemoryUploadIntentStore())

    first = await service.create(request(), "idempotency-key-0001")
    second = await service.create(request(), "idempotency-key-0001")

    assert first.upload_id == second.upload_id
    assert first.object_key.startswith("quarantine/00000000-0000-0000-0000-000000000001/")
    assert first.object_key.endswith("/lecture.wav")
    assert len(storage.calls) == 1


@pytest.mark.asyncio
async def test_reusing_idempotency_key_with_different_metadata_is_rejected() -> None:
    service = UploadIntentService(FakeStorage(), InMemoryUploadIntentStore())
    await service.create(request(), "idempotency-key-0002")

    with pytest.raises(UploadIntentError, match="different upload metadata"):
        await service.create(request(filename="other.wav"), "idempotency-key-0002")


@pytest.mark.parametrize(
    ("filename", "content_type", "size_bytes", "code"),
    [
        ("lecture.wav", "audio/mpeg", 1024, "UPLOAD_TYPE_INVALID"),
        ("../lecture.wav", "audio/wav", 1024, "UPLOAD_FILENAME_INVALID"),
        ("lecture.wav", "audio/wav", 25_000_001, "UPLOAD_SIZE_INVALID"),
        ("https://example.test/a.wav", "audio/wav", 1024, "UPLOAD_FILENAME_INVALID"),
    ],
)
def test_upload_metadata_rejects_spoofed_or_unsafe_inputs(
    filename: str, content_type: str, size_bytes: int, code: str
) -> None:
    with pytest.raises(UploadIntentError) as error:
        validate_upload_request(
            request(filename=filename, content_type=content_type, size_bytes=size_bytes)
        )
    assert error.value.code == code


@pytest.mark.asyncio
async def test_idempotency_key_must_be_present_and_bounded() -> None:
    service = UploadIntentService(FakeStorage(), InMemoryUploadIntentStore())
    for key in ("short", "a" * 129):
        with pytest.raises(UploadIntentError, match="Idempotency-Key"):
            await service.create(request(), key)
