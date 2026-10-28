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
from app.main import create_app

pytestmark = pytest.mark.asyncio

SECRET = "test-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def token(user_id: UUID, scopes: str = "voices:read voices:write") -> str:
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
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def make_app(role: str = "editor"):
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
        (WorkspaceMembership(WORKSPACE_ID, user_id, role),)
    )
    return app, user_id


async def test_voice_routes_require_workspace_role_and_cover_lifecycle() -> None:
    app, user_id = make_app("editor")
    headers = {
        "Authorization": f"Bearer {token(user_id)}",
        "Idempotency-Key": "voice-route-create-0001",
    }
    body = {
        "workspace_id": str(WORKSPACE_ID),
        "name": "Teacher voice",
        "language_code": "en-US",
        "consent_statement_version": "v1",
        "consent_attestation_text_hash": "a" * 64,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post("/v1/voices", headers=headers, json=body)
        voice_id = created.json()["data"]["id"]
        listed = await client.get(
            "/v1/voices",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers={"Authorization": headers["Authorization"]},
        )
        updated = await client.patch(
            f"/v1/voices/{voice_id}",
            headers={"Authorization": headers["Authorization"]},
            json={"name": "Updated teacher voice", "status": "archived"},
        )
        revoked = await client.post(
            f"/v1/voices/{voice_id}/revoke",
            headers={"Authorization": headers["Authorization"]},
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["id"] == voice_id
    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "archived"
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "revoked"


async def test_voice_delete_requires_admin_and_returns_queued_cascade() -> None:
    editor_app, editor_id = make_app("editor")
    editor_headers = {
        "Authorization": f"Bearer {token(editor_id)}",
        "Idempotency-Key": "voice-delete-create-0001",
    }
    body = {
        "workspace_id": str(WORKSPACE_ID),
        "name": "Delete me",
        "language_code": "en-US",
        "consent_statement_version": "v1",
        "consent_attestation_text_hash": "b" * 64,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=editor_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post("/v1/voices", headers=editor_headers, json=body)
        voice_id = created.json()["data"]["id"]
        forbidden = await client.delete(
            f"/v1/voices/{voice_id}",
            headers={"Authorization": editor_headers["Authorization"]},
        )

    assert forbidden.status_code == 403

    admin_app, admin_id = make_app("admin")
    voice = await admin_app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=admin_id,
        name="Delete me",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="c" * 64,
        reference_upload_id=None,
        idempotency_key="voice-delete-admin-0001",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        deleted = await client.delete(
            f"/v1/voices/{voice.id}",
            headers={"Authorization": f"Bearer {token(admin_id)}"},
        )

    assert deleted.status_code == 202
    assert deleted.json()["data"]["status"] == "deletion_queued"
