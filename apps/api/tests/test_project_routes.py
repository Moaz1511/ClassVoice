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
from app.domains.voices.lifecycle import VoiceReadiness
from app.main import create_app

pytestmark = pytest.mark.asyncio

SECRET = "test-project-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000011")


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID, scopes: str = "projects:read projects:write") -> str:
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


def _app() -> tuple[object, UUID]:
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
    return app, user_id


async def _ready_voice(app: object, user_id: UUID) -> UUID:
    voice = await app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        name="Project teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key=f"project-voice-{uuid4().hex[:16]}",
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    return voice.id


async def test_projects_are_idempotent_and_save_only_explicit_editor_settings() -> None:
    app, user_id = _app()
    voice_id = await _ready_voice(app, user_id)
    headers = {
        "Authorization": f"Bearer {_token(user_id)}",
        "Idempotency-Key": "project-create-idempotency-01",
    }
    body = {
        "workspace_id": str(WORKSPACE_ID),
        "name": "Algebra lesson",
        "description": "A saved Studio setup",
        "editor_settings": {
            "voice_profile_id": str(voice_id),
            "language_code": "en-US",
            "output_format": "mp3",
            "speed": 1.15,
            "stability": 0.6,
            "style": 0.2,
        },
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post("/v1/projects", headers=headers, json=body)
        repeated = await client.post("/v1/projects", headers=headers, json=body)
        settings = await client.get(
            f"/v1/projects/{created.json()['data']['id']}/editor-settings",
            headers={"Authorization": headers["Authorization"]},
        )
        draft_rejected = await client.post(
            "/v1/projects",
            headers={**headers, "Idempotency-Key": "project-draft-rejected-01"},
            json={
                "workspace_id": str(WORKSPACE_ID),
                "name": "Draft should stay local",
                "draft_text": "Do not persist this text",
            },
        )

    assert created.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["data"]["id"] == created.json()["data"]["id"]
    assert settings.status_code == 200
    assert settings.json()["data"]["settings"]["output_format"] == "mp3"
    assert settings.json()["data"]["settings"]["voice_profile_id"] == str(voice_id)
    assert draft_rejected.status_code == 422


async def test_projects_support_archive_restore_and_authorization() -> None:
    app, user_id = _app()
    headers = {
        "Authorization": f"Bearer {_token(user_id)}",
        "Idempotency-Key": "project-archive-create-01",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/projects",
            headers=headers,
            json={"workspace_id": str(WORKSPACE_ID), "name": "Archive me"},
        )
        project_id = created.json()["data"]["id"]
        archived = await client.patch(
            f"/v1/projects/{project_id}",
            headers={"Authorization": headers["Authorization"]},
            json={"archived": True},
        )
        active = await client.get(
            "/v1/projects",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers={"Authorization": headers["Authorization"]},
        )
        all_projects = await client.get(
            "/v1/projects",
            params={"workspace_id": str(WORKSPACE_ID), "include_archived": "true"},
            headers={"Authorization": headers["Authorization"]},
        )
        restored = await client.patch(
            f"/v1/projects/{project_id}",
            headers={"Authorization": headers["Authorization"]},
            json={"archived": False},
        )
        forbidden = await client.get(
            f"/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {_token(uuid4())}"},
        )

    assert created.status_code == 201
    assert archived.status_code == 200
    assert archived.json()["data"]["archived"] is True
    assert active.status_code == 200
    assert active.json()["data"]["items"] == []
    assert len(all_projects.json()["data"]["items"]) == 1
    assert restored.status_code == 200
    assert restored.json()["data"]["archived"] is False
    assert forbidden.status_code == 403
