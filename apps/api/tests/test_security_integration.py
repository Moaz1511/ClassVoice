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
from app.workers.generation_queue import GenerationWorker, InMemoryGenerationQueue

pytestmark = pytest.mark.asyncio

SECRET = "security-integration-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_A = UUID("00000000-0000-0000-0000-000000000031")
WORKSPACE_B = UUID("00000000-0000-0000-0000-000000000032")
MODEL_SHA = "d" * 64


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID, scopes: str) -> str:
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
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


def _make_app(*memberships: WorkspaceMembership):
    app = create_app(
        APISettings.from_env(
            {
                "SUPABASE_JWT_SECRET": SECRET,
                "SUPABASE_JWT_ISSUER": ISSUER,
            }
        )
    )
    app.state.membership_store = InMemoryMembershipStore(tuple(memberships))
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
    app.state.generation_queue = InMemoryGenerationQueue()
    app.state.generation_worker = GenerationWorker(
        app.state.generation_service,
        app.state.generation_queue,
    )
    return app


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def _ready_voice(app, workspace_id: UUID, user_id: UUID, key: str):
    voice = await app.state.voice_service.create(
        workspace_id=workspace_id,
        actor_id=user_id,
        name="Private teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="e" * 64,
        reference_upload_id=None,
        idempotency_key=key,
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    return await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )


def _generation_body(workspace_id: UUID, voice_id: UUID) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "voice_profile_id": str(voice_id),
        "input_text": "A private lesson for enrolled students.",
        "language_code": "en-US",
        "output_format": "wav",
        "speed": 1.0,
        "model_key": "openvoice-v2",
        "model_version": "2.0.0",
        "checkpoint_sha256": MODEL_SHA,
    }


async def test_anonymous_and_cross_workspace_requests_cannot_read_private_voices() -> None:
    owner_a = uuid4()
    owner_b = uuid4()
    app = _make_app(
        WorkspaceMembership(WORKSPACE_A, owner_a, "editor"),
        WorkspaceMembership(WORKSPACE_B, owner_b, "editor"),
    )
    private_voice = await _ready_voice(app, WORKSPACE_B, owner_b, "security-cross-workspace-01")
    owner_a_headers = {
        "Authorization": f"Bearer {_token(owner_a, 'voices:read generations:read')}"
    }

    async with _client(app) as client:
        anonymous = await client.get(
            "/v1/voices", params={"workspace_id": str(WORKSPACE_A)}
        )
        cross_list = await client.get(
            "/v1/voices",
            params={"workspace_id": str(WORKSPACE_B)},
            headers=owner_a_headers,
        )
        cross_voice = await client.get(
            f"/v1/voices/{private_voice.id}", headers=owner_a_headers
        )
        cross_generations = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_B)},
            headers=owner_a_headers,
        )

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "AUTH_TOKEN_MISSING"
    assert cross_list.status_code == 403
    assert cross_list.json()["error"]["code"] == "ACCESS_WORKSPACE_FORBIDDEN"
    assert cross_voice.status_code == 403
    assert cross_voice.json()["error"]["code"] == "ACCESS_WORKSPACE_FORBIDDEN"
    assert cross_generations.status_code == 403
    assert cross_generations.json()["error"]["code"] == "ACCESS_WORKSPACE_FORBIDDEN"
    assert str(private_voice.id) not in cross_voice.text


async def test_viewer_cannot_mutate_voice_project_or_generation_resources() -> None:
    viewer = uuid4()
    app = _make_app(WorkspaceMembership(WORKSPACE_A, viewer, "viewer"))
    scopes = "voices:read voices:write projects:write generations:create"
    headers = {
        "Authorization": f"Bearer {_token(viewer, scopes)}",
        "Idempotency-Key": "security-viewer-write-01",
    }
    generation_body = _generation_body(WORKSPACE_A, uuid4())

    async with _client(app) as client:
        upload = await client.post(
            "/v1/voices/upload-url",
            headers=headers,
            json={
                "workspace_id": str(WORKSPACE_A),
                "filename": "teacher.wav",
                "content_type": "audio/wav",
                "size_bytes": 1024,
            },
        )
        project = await client.post(
            "/v1/projects",
            headers=headers,
            json={"workspace_id": str(WORKSPACE_A), "name": "Viewer project"},
        )
        generation = await client.post(
            "/v1/generations", headers=headers, json=generation_body
        )

    for response in (upload, project, generation):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCESS_ROLE_INSUFFICIENT"


async def test_api_key_is_workspace_bound_and_revocation_is_immediate() -> None:
    owner = uuid4()
    app = _make_app(
        WorkspaceMembership(WORKSPACE_A, owner, "admin"),
        WorkspaceMembership(WORKSPACE_B, owner, "admin"),
    )
    issue = await app.state.api_key_service.create(
        workspace_id=WORKSPACE_A,
        created_by=owner,
        name="Security integration reader",
        scopes=["generations:read"],
        expires_at=None,
    )

    async with _client(app) as client:
        allowed = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_A)},
            headers={"X-API-Key": issue.secret},
        )
        cross_workspace = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_B)},
            headers={"X-API-Key": issue.secret},
        )
        missing_scope = await client.post(
            "/v1/generations",
            headers={"X-API-Key": issue.secret, "Idempotency-Key": "security-key-write-01"},
            json=_generation_body(WORKSPACE_A, uuid4()),
        )
        await app.state.api_key_service.revoke(issue.record.id, WORKSPACE_A)
        revoked = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_A)},
            headers={"X-API-Key": issue.secret},
        )

    assert allowed.status_code == 200
    assert cross_workspace.status_code == 403
    assert cross_workspace.json()["error"]["code"] == "ACCESS_WORKSPACE_FORBIDDEN"
    assert missing_scope.status_code == 403
    assert missing_scope.json()["error"]["code"] == "ACCESS_SCOPE_MISSING"
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "API_KEY_REVOKED"


async def test_revoked_consent_blocks_generation_at_the_http_boundary() -> None:
    owner = uuid4()
    app = _make_app(WorkspaceMembership(WORKSPACE_A, owner, "editor"))
    voice = await _ready_voice(app, WORKSPACE_A, owner, "security-revoked-consent-01")
    headers = {
        "Authorization": (
            f"Bearer {_token(owner, 'voices:write generations:create') }"
        )
    }

    async with _client(app) as client:
        revoked = await client.post(f"/v1/voices/{voice.id}/revoke", headers=headers)
        generation = await client.post(
            "/v1/generations",
            headers={**headers, "Idempotency-Key": "security-revoked-generation-01"},
            json=_generation_body(WORKSPACE_A, voice.id),
        )

    assert revoked.status_code == 200
    assert revoked.json()["data"]["consent_status"] == "revoked"
    assert generation.status_code == 400
    assert generation.json()["error"]["code"] == "VOICE_CONSENT_REVOKED"


async def test_disabled_workspace_denies_reads_and_writes_before_resource_access() -> None:
    owner = uuid4()
    app = _make_app(WorkspaceMembership(WORKSPACE_A, owner, "admin", workspace_disabled=True))
    headers = {
        "Authorization": (
            f"Bearer {_token(owner, 'voices:read voices:write generations:read') }"
        ),
        "Idempotency-Key": "security-disabled-workspace-01",
    }

    async with _client(app) as client:
        read = await client.get(
            "/v1/voices", params={"workspace_id": str(WORKSPACE_A)}, headers=headers
        )
        write = await client.post(
            "/v1/voices/upload-url",
            headers=headers,
            json={
                "workspace_id": str(WORKSPACE_A),
                "filename": "teacher.wav",
                "content_type": "audio/wav",
                "size_bytes": 1024,
            },
        )

    assert read.status_code == 403
    assert read.json()["error"]["code"] == "ACCESS_WORKSPACE_DISABLED"
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "ACCESS_WORKSPACE_DISABLED"
