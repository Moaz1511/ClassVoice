from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.core.settings import APISettings, SettingsError
from app.storage.ports import StorageError, validate_object_key
from app.storage.s3 import S3StorageAdapter
from app.storage.supabase import SupabaseStorageAdapter


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        self.calls.append((operation, kwargs))
        return f"http://storage.test/{operation}?X-Amz-Expires={kwargs['ExpiresIn']}"

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(("put_object", kwargs))


@pytest.mark.asyncio
async def test_s3_adapter_only_signs_allowlisted_private_objects() -> None:
    client = FakeS3Client()
    adapter = S3StorageAdapter(APISettings.from_env({}), client=client)

    upload = await adapter.create_upload_url(
        "voice-inputs", "workspace/voice.wav", content_type="audio/wav"
    )
    download = await adapter.create_download_url("voice-inputs", "workspace/voice.wav")

    assert upload.method == "PUT"
    assert upload.headers == {"Content-Type": "audio/wav"}
    assert upload.expires_at > datetime.now(UTC)
    assert download.method == "GET"
    assert [call[0] for call in client.calls] == ["put_object", "get_object"]
    assert client.calls[0][1]["ExpiresIn"] == 600
    assert client.calls[0][1]["Params"]["Bucket"] == "voice-inputs"


@pytest.mark.asyncio
async def test_s3_adapter_uploads_private_generated_bytes() -> None:
    client = FakeS3Client()
    adapter = S3StorageAdapter(APISettings.from_env({}), client=client)

    await adapter.put_object(
        "generated-audio",
        "workspace/job/output.wav",
        b"RIFFgenerated",
        content_type="audio/wav",
    )

    operation, params = client.calls[0]
    assert operation == "put_object"
    assert params["Bucket"] == "generated-audio"
    assert params["Key"] == "workspace/job/output.wav"
    assert params["Body"] == b"RIFFgenerated"
    assert params["ContentType"] == "audio/wav"


@pytest.mark.asyncio
async def test_object_key_and_bucket_traversal_are_rejected() -> None:
    for key in ("../secret", "workspace/../secret", "/absolute", "workspace\\secret", ""):
        with pytest.raises(StorageError):
            validate_object_key(key)
    with pytest.raises(StorageError, match="allowlisted"):
        await S3StorageAdapter(APISettings.from_env({}), client=FakeS3Client()).create_download_url(
            "public", "safe.wav"
        )


@pytest.mark.asyncio
async def test_supabase_adapter_uses_server_only_signed_endpoints() -> None:
    settings = APISettings.from_env(
        {
            "STORAGE_PROVIDER": "supabase",
            "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
        }
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/upload/sign/" in str(request.url):
            return httpx.Response(
                200,
                json={"url": "/object/upload/sign/voice-inputs/a.wav?token=x"},
            )
        return httpx.Response(200, json={"signedURL": "/object/sign/voice-inputs/a.wav?token=y"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SupabaseStorageAdapter(settings, client=client)
        upload = await adapter.create_upload_url(
            "voice-inputs", "a.wav", content_type="audio/wav"
        )
        download = await adapter.create_download_url("voice-inputs", "a.wav")
    assert upload.url.startswith("https://example.supabase.co/storage/v1/")
    assert download.url.startswith("https://example.supabase.co/storage/v1/")
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == "Bearer server-secret"
    assert requests[0].headers["apikey"] == "server-secret"
    assert "/object/upload/sign/voice-inputs/a.wav" in str(requests[0].url)
    assert "/object/sign/voice-inputs/a.wav" in str(requests[1].url)


def test_supabase_provider_requires_https_and_server_key() -> None:
    with pytest.raises(SettingsError, match="HTTPS"):
        APISettings.from_env(
            {
                "STORAGE_PROVIDER": "supabase",
                "NEXT_PUBLIC_SUPABASE_URL": "http://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
            }
        )


@pytest.mark.asyncio
async def test_supabase_adapter_uploads_private_generated_bytes() -> None:
    settings = APISettings.from_env(
        {
            "STORAGE_PROVIDER": "supabase",
            "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
        }
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"Key": "workspace/job/output.mp3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SupabaseStorageAdapter(settings, client=client)
        await adapter.put_object(
            "generated-audio",
            "workspace/job/output.mp3",
            b"ID3generated",
            content_type="audio/mpeg",
        )

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert "/object/generated-audio/workspace/job/output.mp3" in str(requests[0].url)
    assert requests[0].headers["x-upsert"] == "true"
    assert requests[0].content == b"ID3generated"
