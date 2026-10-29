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
from app.domains.api_keys.service import ApiKeyError, ApiKeyService, InMemoryApiKeyStore
from app.main import create_app

pytestmark = pytest.mark.asyncio

SECRET = "test-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID, scopes: str = "api_keys:read api_keys:write") -> str:
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


async def test_api_key_service_returns_secret_once_and_tracks_last_use() -> None:
    now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    store = InMemoryApiKeyStore()
    service = ApiKeyService(store, now=lambda: now)
    user_id = uuid4()

    issue = await service.create(
        workspace_id=WORKSPACE_ID,
        created_by=user_id,
        name="CLI generation",
        scopes=["generations:read", "generations:create"],
        expires_at=None,
    )

    assert issue.secret.startswith("cv_live_")
    assert issue.record.key_hash not in issue.secret
    assert "key_hash" not in issue.record.as_dict()
    principal = await service.authenticate(issue.secret)
    stored = await store.get(issue.record.id)

    assert principal.subject == user_id
    assert principal.workspace_id == WORKSPACE_ID
    assert principal.api_key_id == issue.record.id
    assert principal.scopes == frozenset({"generations:create", "generations:read"})
    assert stored is not None
    assert stored.last_used_at == now


async def test_api_key_service_rejects_unknown_scope_and_expiry() -> None:
    service = ApiKeyService(InMemoryApiKeyStore())
    with pytest.raises(ApiKeyError) as scope_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=uuid4(),
            name="bad",
            scopes=["admin:root"],
            expires_at=None,
        )
    assert scope_error.value.code == "API_KEY_SCOPE_INVALID"

    with pytest.raises(ApiKeyError) as expiry_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=uuid4(),
            name="bad expiry",
            scopes=["generations:read"],
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    assert expiry_error.value.code == "API_KEY_EXPIRY_INVALID"


async def test_api_key_service_expires_and_revokes_keys() -> None:
    current = [datetime(2026, 10, 29, 12, 0, tzinfo=UTC)]
    store = InMemoryApiKeyStore()
    service = ApiKeyService(store, now=lambda: current[0])
    issue = await service.create(
        workspace_id=WORKSPACE_ID,
        created_by=uuid4(),
        name="short lived",
        scopes=["generations:read"],
        expires_at=current[0] + timedelta(minutes=1),
    )
    current[0] += timedelta(minutes=2)
    with pytest.raises(ApiKeyError) as expired:
        await service.authenticate(issue.secret)
    assert expired.value.code == "API_KEY_EXPIRED"

    revoked = await service.revoke(issue.record.id, WORKSPACE_ID)
    assert revoked.status == "revoked"
    assert await service.revoke(issue.record.id, WORKSPACE_ID) == revoked


def _make_app(user_id: UUID):
    app = create_app(
        APISettings.from_env(
            {
                "SUPABASE_JWT_SECRET": SECRET,
                "SUPABASE_JWT_ISSUER": ISSUER,
            }
        )
    )
    app.state.membership_store = InMemoryMembershipStore(
        (WorkspaceMembership(WORKSPACE_ID, user_id, "admin"),)
    )
    return app


async def test_api_key_routes_issue_list_revoke_and_authenticate_generation_read() -> None:
    user_id = uuid4()
    app = _make_app(user_id)
    jwt_headers = {"Authorization": f"Bearer {_token(user_id)}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/api-keys",
            headers=jwt_headers,
            json={
                "workspace_id": str(WORKSPACE_ID),
                "name": "Generation reader",
                "scopes": ["generations:read"],
            },
        )
        secret = created.json()["data"]["secret"]
        listed = await client.get(
            "/v1/api-keys",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers=jwt_headers,
        )
        generation_list = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers={"X-API-Key": secret},
        )
        revoked = await client.post(
            f"/v1/api-keys/{created.json()['data']['api_key']['id']}/revoke",
            headers=jwt_headers,
        )
        after_revoke = await client.get(
            "/v1/generations",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers={"X-API-Key": secret},
        )

    assert created.status_code == 201
    assert created.json()["data"]["api_key"]["key_prefix"] == secret[:12]
    assert "key_hash" not in created.json()["data"]["api_key"]
    assert secret not in listed.text
    assert listed.status_code == 200
    assert generation_list.status_code == 200
    assert generation_list.json()["data"]["items"] == []
    assert revoked.status_code == 200
    assert after_revoke.status_code == 401
    assert after_revoke.json()["error"]["code"] == "API_KEY_REVOKED"
