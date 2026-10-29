from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.authorization import InMemoryMembershipStore, WorkspaceMembership
from app.core.settings import APISettings
from app.domains.webhooks.service import (
    InMemoryWebhookDeliveryStore,
    InMemoryWebhookEndpointStore,
    WebhookError,
    WebhookResponse,
    WebhookService,
    verify_webhook_signature,
)
from app.main import create_app

pytestmark = pytest.mark.asyncio

SECRET = "test-jwt-secret"
ISSUER = "https://project.supabase.co/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeSender:
    def __init__(self, responses: list[WebhookResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    async def send(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookResponse:
        self.calls.append((url, body, dict(headers)))
        return self.responses.pop(0)


def _service(
    *,
    now: list[datetime] | None = None,
    threshold: int = 5,
    max_attempts: int = 5,
) -> WebhookService:
    clock = now or [datetime(2026, 10, 29, 12, 0, tzinfo=UTC)]
    return WebhookService(
        InMemoryWebhookEndpointStore(),
        InMemoryWebhookDeliveryStore(),
        now=lambda: clock[0],
        resolve_host=lambda hostname: ("93.184.216.34",) if hostname == "example.test" else (),
        disable_failure_threshold=threshold,
        max_attempts=max_attempts,
        retry_delays_seconds=(1,),
    )


async def test_webhook_url_validation_rejects_http_and_private_dns() -> None:
    service = _service()
    with pytest.raises(WebhookError) as http_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=uuid4(),
            url="http://example.test/hook",
            events=["generation.succeeded"],
        )
    assert http_error.value.code == "WEBHOOK_URL_HTTPS_REQUIRED"

    with pytest.raises(WebhookError) as ip_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=uuid4(),
            url="https://127.0.0.1/hook",
            events=["generation.succeeded"],
        )
    assert ip_error.value.code == "WEBHOOK_PRIVATE_ADDRESS"

    private_service = WebhookService(
        InMemoryWebhookEndpointStore(),
        InMemoryWebhookDeliveryStore(),
        resolve_host=lambda _hostname: ("10.0.0.10",),
    )
    with pytest.raises(WebhookError) as dns_error:
        await private_service.create(
            workspace_id=WORKSPACE_ID,
            created_by=uuid4(),
            url="https://private.test/hook",
            events=["generation.succeeded"],
        )
    assert dns_error.value.code == "WEBHOOK_PRIVATE_ADDRESS"


async def test_webhook_delivery_is_signed_and_event_id_is_idempotent() -> None:
    service = _service()
    issue = await service.create(
        workspace_id=WORKSPACE_ID,
        created_by=uuid4(),
        url="https://example.test/hook",
        events=["generation.succeeded"],
    )
    event_id = uuid4()
    first = await service.enqueue(
        issue.endpoint.id,
        event_type="generation.succeeded",
        event_id=event_id,
        payload={"generation_id": str(uuid4()), "status": "succeeded"},
    )
    duplicate = await service.enqueue(
        issue.endpoint.id,
        event_type="generation.succeeded",
        event_id=event_id,
        payload={"ignored": True},
    )
    sender = FakeSender([WebhookResponse(204)])
    delivered = await service.deliver(first.id, sender)
    url, body, headers = sender.calls[0]

    assert duplicate == first
    assert delivered.status == "delivered"
    assert url == "https://example.test/hook"
    assert headers["X-ClassVoice-Event-Id"] == str(event_id)
    assert headers["X-ClassVoice-Event-Type"] == "generation.succeeded"
    assert verify_webhook_signature(
        issue.secret,
        body,
        headers,
        now=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
    )

    with pytest.raises(WebhookError) as replay:
        verify_webhook_signature(
            issue.secret,
            body,
            headers,
            now=datetime.now(UTC) + timedelta(minutes=10),
        )
    assert replay.value.code == "WEBHOOK_SIGNATURE_REPLAY"


async def test_webhook_failures_retry_and_disable_endpoint() -> None:
    clock = [datetime(2026, 10, 29, 12, 0, tzinfo=UTC)]
    service = _service(now=clock, threshold=3)
    issue = await service.create(
        workspace_id=WORKSPACE_ID,
        created_by=uuid4(),
        url="https://example.test/hook",
        events=["generation.failed"],
    )
    delivery = await service.enqueue(
        issue.endpoint.id,
        event_type="generation.failed",
        payload={"error_code": "MODEL_FAILED"},
    )
    sender = FakeSender(
        [WebhookResponse(500, b"one"), WebhookResponse(503, b"two"), WebhookResponse(410, b"three")]
    )

    first = await service.deliver(delivery.id, sender)
    clock[0] += timedelta(seconds=2)
    second = await service.deliver(delivery.id, sender)
    clock[0] += timedelta(seconds=2)
    third = await service.deliver(delivery.id, sender)
    endpoint = await service.get(issue.endpoint.id)

    assert first.status == "retrying"
    assert second.status == "retrying"
    assert third.status == "abandoned"
    assert endpoint is not None
    assert endpoint.status == "disabled"
    assert endpoint.failure_count == 3
    with pytest.raises(WebhookError) as inactive:
        await service.enqueue(
            issue.endpoint.id,
            event_type="generation.failed",
            payload={"error_code": "NEW"},
        )
    assert inactive.value.code == "WEBHOOK_NOT_ACTIVE"


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def _token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "aud": "authenticated",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": ISSUER,
            "role": "authenticated",
            "scope": "webhooks:read webhooks:write",
            "sub": str(user_id),
        }
    )
    signed = f"{header}.{payload}".encode()
    signature = hmac.new(SECRET.encode(), signed, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


async def test_webhook_routes_issue_and_list_metadata_without_secret_hash() -> None:
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
        (WorkspaceMembership(WORKSPACE_ID, user_id, "admin"),)
    )
    app.state.webhook_service = _service()
    headers = {"Authorization": f"Bearer {_token(user_id)}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/webhooks",
            headers=headers,
            json={
                "workspace_id": str(WORKSPACE_ID),
                "url": "https://example.test/hook",
                "events": ["generation.succeeded"],
            },
        )
        listed = await client.get(
            "/v1/webhooks",
            params={"workspace_id": str(WORKSPACE_ID)},
            headers=headers,
        )

    secret = created.json()["data"]["secret"]
    assert created.status_code == 201
    assert secret.startswith("whsec_")
    assert "secret_hash" not in created.json()["data"]["webhook"]
    assert secret not in listed.text
    assert listed.status_code == 200
