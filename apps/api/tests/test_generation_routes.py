from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.authorization import InMemoryMembershipStore, WorkspaceMembership
from app.core.settings import APISettings
from app.domains.generations.jobs import GenerationService
from app.domains.voices.lifecycle import VoiceReadiness
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.main import create_app

pytestmark = pytest.mark.asyncio

SECRET = "test-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
MODEL_SHA = "a" * 64


def segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def token(user_id: UUID, scopes: str = "generations:create generations:read") -> str:
    now = datetime.now(UTC)
    header = segment({"alg": "HS256", "typ": "JWT"})
    payload = segment(
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
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


def make_app() -> tuple[object, UUID]:
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
        config={"sample_rate_hz": 24000},
        enabled=True,
    )
    app.state.model_registry = ModelRegistry(ModelManifest(1, (entry,)))
    app.state.generation_service = GenerationService(
        app.state.generation_store,
        app.state.voice_service,
        app.state.model_registry,
    )
    return app, user_id


async def test_generation_routes_are_idempotent_and_support_cancel_retry() -> None:
    app, user_id = make_app()
    voice = await app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="generation-route-voice-01",
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    headers = {
        "Authorization": f"Bearer {token(user_id)}",
        "Idempotency-Key": "generation-route-create-01",
    }
    body = {
        "workspace_id": str(WORKSPACE_ID),
        "voice_profile_id": str(voice.id),
        "input_text": "A short lesson for students.",
        "language_code": "en-US",
        "output_format": "wav",
        "speed": 1.0,
        "stability": 0.5,
        "style": 0.2,
        "seed": 7,
        "model_key": "openvoice-v2",
        "model_version": "2.0.0",
        "checkpoint_sha256": MODEL_SHA,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post("/v1/generations", headers=headers, json=body)
        repeated = await client.post("/v1/generations", headers=headers, json=body)
        job_id = created.json()["data"]["id"]
        listed = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers={"Authorization": headers["Authorization"]},
        )
        fetched = await client.get(
            f"/v1/generations/{job_id}",
            headers={"Authorization": headers["Authorization"]},
        )
        canceled = await client.post(
            f"/v1/generations/{job_id}/cancel",
            headers={"Authorization": headers["Authorization"]},
        )
        await app.state.generation_service.transition(UUID(job_id), user_id, "canceled")
        retried = await client.post(
            f"/v1/generations/{job_id}/retry",
            headers={"Authorization": headers["Authorization"]},
        )

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["data"]["id"] == job_id
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0].get("input_text") is None
    assert fetched.status_code == 200
    assert fetched.json()["data"]["input_text"] == body["input_text"]
    assert canceled.status_code == 200
    assert canceled.json()["data"]["status"] == "cancel_requested"
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "created"
    assert retried.json()["data"]["queue_attempts"] == 1


async def test_generation_route_requires_idempotency_and_reports_model_gate() -> None:
    app, user_id = make_app()
    voice = await app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="c" * 64,
        reference_upload_id=None,
        idempotency_key="generation-route-voice-02",
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    headers = {"Authorization": f"Bearer {token(user_id)}"}
    body = {
        "workspace_id": str(WORKSPACE_ID),
        "voice_profile_id": str(voice.id),
        "input_text": "Lesson",
        "language_code": "en-US",
        "model_key": "missing-model",
        "model_version": "1.0.0",
        "checkpoint_sha256": MODEL_SHA,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        missing_key = await client.post("/v1/generations", headers=headers, json=body)
        gated = await client.post(
            "/v1/generations",
            headers={**headers, "Idempotency-Key": "generation-route-model-01"},
            json=body,
        )

    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert gated.status_code == 400
    assert gated.json()["error"]["code"] == "MODEL_NOT_ALLOWLISTED"
