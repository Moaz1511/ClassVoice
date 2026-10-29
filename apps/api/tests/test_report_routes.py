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

SECRET = "test-report-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000021")


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID, *, moderator: bool = False) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "aud": "authenticated",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "iss": ISSUER,
        "role": "authenticated",
        "scope": "reports:write",
        "sub": str(user_id),
    }
    if moderator:
        payload["app_metadata"] = {"profile_role": "moderator"}
    header = _segment({"alg": "HS256", "typ": "JWT"})
    body = _segment(payload)
    signature = hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


async def test_member_report_is_audited_and_moderator_can_review_without_raw_audio() -> None:
    reporter = uuid4()
    moderator = uuid4()
    app = create_app(
        APISettings.from_env({"SUPABASE_JWT_SECRET": SECRET, "SUPABASE_JWT_ISSUER": ISSUER})
    )
    app.state.membership_store = InMemoryMembershipStore(
        (WorkspaceMembership(WORKSPACE_ID, reporter, "viewer"),)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/reports",
            headers={"Authorization": f"Bearer {_token(reporter)}"},
            json={
                "workspace_id": str(WORKSPACE_ID),
                "resource_type": "voice_profile",
                "resource_id": str(uuid4()),
                "reason_code": "impersonation",
                "description": "This report is safe for a moderator to read.",
            },
        )
        denied = await client.get(
            "/v1/reports",
            headers={"Authorization": f"Bearer {_token(reporter)}"},
        )
        reviewed = await client.get(
            "/v1/reports",
            headers={"Authorization": f"Bearer {_token(moderator, moderator=True)}"},
        )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "open"
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCESS_MODERATOR_REQUIRED"
    assert reviewed.status_code == 200
    assert len(reviewed.json()["data"]["items"]) == 1
    assert reviewed.json()["data"]["items"][0]["description"] == (
        "This report is safe for a moderator to read."
    )

    events = await app.state.audit_event_store.list_all()
    assert len(events) == 1
    assert events[0].action == "moderation.reported"
    assert events[0].request_id
