from __future__ import annotations

import base64
import hashlib
import hmac
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.authorization import InMemoryMembershipStore, WorkspaceMembership
from app.core.settings import APISettings
from app.domains.generations.jobs import GenerationService
from app.domains.generations.outputs import PrivateGenerationOutputStore
from app.domains.voices.lifecycle import VoiceReadiness
from app.inference.adapter import InferenceRequest, SmokeCpuAdapter
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.inference.postprocess import AudioPostProcessor
from app.main import create_app
from app.storage.ports import SignedObjectUrl
from app.workers.generation_queue import GenerationWorker, InMemoryGenerationQueue

pytestmark = pytest.mark.asyncio

SECRET = "test-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
MODEL_SHA = "a" * 64


class FakePrivateStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.sign_calls: list[tuple[str, str]] = []

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
    ) -> None:
        assert content_type in {"audio/wav", "audio/mpeg"}
        self.objects[(bucket, key)] = body

    async def create_upload_url(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
    ) -> SignedObjectUrl:
        raise AssertionError("upload signing is not used by generated-output tests")

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl:
        self.sign_calls.append((bucket, key))
        return SignedObjectUrl(
            url="https://storage.example/signed-output",
            bucket=bucket,
            key=key,
            method="GET",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            headers={},
        )


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID, scopes: str = "generations:read generations:create") -> str:
    now = datetime.now(UTC)
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "aud": "authenticated",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": ISSUER,
            "role": "authenticated",
            "scope": scopes,
            "sub": str(user_id),
        }
    )
    signed = f"{header}.{payload}".encode()
    signature = hmac.new(SECRET.encode(), signed, hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _app() -> tuple[object, UUID, FakePrivateStorage]:
    user_id = uuid4()
    app = create_app(
        APISettings.from_env(
            {
                "SUPABASE_JWT_SECRET": SECRET,
                "SUPABASE_JWT_ISSUER": ISSUER,
            }
        )
    )
    app.state.membership_store = InMemoryMembershipStore(
        (WorkspaceMembership(WORKSPACE_ID, user_id, "editor"),)
    )
    entry = ModelManifestEntry(
        model_key="openvoice-v2",
        version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        checkpoint_path="checkpoint.bin",
        runtime="cpu",
        license_name="Reviewed license",
        license_url="https://example.test/license",
        license_review_status="approved",
        supported_languages=("en-US",),
        config={"sample_rate_hz": 24_000},
        enabled=True,
    )
    app.state.model_registry = ModelRegistry(ModelManifest(1, (entry,)))
    app.state.generation_service = GenerationService(
        app.state.generation_store,
        app.state.voice_service,
        app.state.model_registry,
    )
    app.state.generation_queue = InMemoryGenerationQueue()
    app.state.generation_worker = GenerationWorker(
        app.state.generation_service,
        app.state.generation_queue,
    )
    storage = FakePrivateStorage()
    app.state.storage_adapter = storage
    app.state.generation_outputs = PrivateGenerationOutputStore(storage)
    return app, user_id, storage


async def _ready_job(app: object, user_id: UUID, output_format: str = "wav") -> UUID:
    voice = await app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key=f"output-voice-{uuid4().hex[:16]}",
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    job = await app.state.generation_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        voice_profile_id=voice.id,
        project_id=None,
        input_text="A private output lesson.",
        language_code="en-US",
        output_format=output_format,
        speed=1.0,
        stability=0.5,
        style=0.2,
        seed=7,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key=f"output-job-{uuid4().hex[:16]}",
    )
    return job.id


async def test_postprocessor_creates_checksumed_mp3_result() -> None:
    request = await SmokeCpuAdapter().generate(
        InferenceRequest(
            job_id=UUID("00000000-0000-0000-0000-000000000010"),
            input_text="A lesson.",
            language_code="en-US",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            model_metadata={},
        )
    )
    converted = await AudioPostProcessor(converter=lambda _source: b"ID3\x04\x00\x00").normalize(
        request,
        "mp3",
    )
    assert converted.content_type == "audio/mpeg"
    assert converted.audio_bytes.startswith(b"ID3")
    assert converted.sha256 == hashlib.sha256(converted.audio_bytes).hexdigest()
    assert converted.metadata["postprocessing"]["converter"] == "injected"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_default_ffmpeg_postprocessor_emits_decodable_mp3() -> None:
    source = await SmokeCpuAdapter().generate(
        InferenceRequest(
            job_id=UUID("00000000-0000-0000-0000-000000000011"),
            input_text="A lesson.",
            language_code="en-US",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            model_metadata={},
        )
    )
    converted = await AudioPostProcessor().normalize(source, "mp3")
    decoded = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "null", "pipe:1"],
        input=converted.audio_bytes,
        capture_output=True,
        check=False,
    )
    assert decoded.returncode == 0


async def test_worker_persists_private_wav_and_mp3_assets() -> None:
    app, user_id, storage = _app()
    for output_format in ("wav", "mp3"):
        job_id = await _ready_job(app, user_id, output_format)
        await app.state.generation_worker.publish(job_id, user_id)
        lease = await app.state.generation_worker.claim_next(user_id)
        assert lease is not None
        completed, result = await app.state.generation_worker.execute(
            lease.lease_id,
            user_id,
            SmokeCpuAdapter(),
            app.state.generation_outputs,
            postprocessor=AudioPostProcessor(converter=lambda _source: b"ID3\x04\x00\x00"),
        )
        assert completed.status == "succeeded"
        assert result is not None
        output = await app.state.generation_outputs.get(job_id)
        assert output is not None
        assert output.output_format == output_format
        assert output.object_key.endswith(f".{output_format}")
        assert output.checksum_sha256 == hashlib.sha256(result.audio_bytes).hexdigest()
        assert (output.bucket, output.object_key) in storage.objects


async def test_download_rechecks_workspace_access_and_hides_object_key() -> None:
    app, user_id, storage = _app()
    job_id = await _ready_job(app, user_id, "wav")
    await app.state.generation_worker.publish(job_id, user_id)
    lease = await app.state.generation_worker.claim_next(user_id)
    assert lease is not None
    completed, _ = await app.state.generation_worker.execute(
        lease.lease_id,
        user_id,
        SmokeCpuAdapter(),
        app.state.generation_outputs,
    )
    assert completed.status == "succeeded"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        authorized = await client.get(
            f"/v1/generations/{job_id}/download",
            headers={"Authorization": f"Bearer {_token(user_id)}"},
        )
        forbidden = await client.get(
            f"/v1/generations/{job_id}/download",
            headers={"Authorization": f"Bearer {_token(uuid4())}"},
        )

    assert authorized.status_code == 200
    data = authorized.json()["data"]
    assert data["download"]["url"] == "https://storage.example/signed-output"
    assert "object_key" not in data["output"]
    assert len(storage.sign_calls) == 1
    assert forbidden.status_code == 403
