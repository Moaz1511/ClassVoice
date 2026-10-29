"""SSRF-safe webhook endpoints, signing, replay protection, and retries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv6Address
from typing import Literal, Protocol
from urllib.parse import SplitResult, urlsplit
from uuid import UUID, uuid4

WebhookStatus = Literal["pending_verification", "active", "disabled"]
DeliveryStatus = Literal["pending", "delivered", "retrying", "failed", "abandoned"]

WEBHOOK_EVENTS = frozenset(
    {
        "generation.created",
        "generation.succeeded",
        "generation.failed",
        "generation.canceled",
        "voice.ready",
        "voice.revoked",
        "project.updated",
    }
)
WEBHOOK_SECRET_PREFIX_LENGTH = 12
MAX_WEBHOOK_EVENTS = 20
MAX_WEBHOOK_PAYLOAD_BYTES = 256_000
REPLAY_WINDOW_SECONDS = 300
DEFAULT_DISABLE_FAILURE_THRESHOLD = 5
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAYS_SECONDS = (60, 300, 900, 3_600)


class WebhookError(ValueError):
    """A stable, user-safe webhook error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WebhookEndpoint:
    id: UUID
    workspace_id: UUID
    created_by: UUID
    url: str
    secret_hash: str
    secret_prefix: str
    events: frozenset[str]
    status: WebhookStatus
    failure_count: int
    last_delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        """Serialize metadata without the secret digest or plaintext secret."""

        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "created_by": str(self.created_by),
            "url": self.url,
            "secret_prefix": self.secret_prefix,
            "events": sorted(self.events),
            "status": self.status,
            "failure_count": self.failure_count,
            "last_delivered_at": (
                self.last_delivered_at.isoformat() if self.last_delivered_at else None
            ),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WebhookSecretIssue:
    endpoint: WebhookEndpoint
    secret: str


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    id: UUID
    endpoint_id: UUID
    event_type: str
    event_id: UUID
    payload: Mapping[str, object]
    status: DeliveryStatus
    attempt_count: int
    next_attempt_at: datetime | None
    response_status: int | None
    response_body_hash: str | None
    delivered_at: datetime | None
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "endpoint_id": str(self.endpoint_id),
            "event_type": self.event_type,
            "event_id": str(self.event_id),
            "status": self.status,
            "attempt_count": self.attempt_count,
            "next_attempt_at": (
                self.next_attempt_at.isoformat() if self.next_attempt_at else None
            ),
            "response_status": self.response_status,
            "response_body_hash": self.response_body_hash,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    status_code: int
    body: bytes = b""


class WebhookHttpSender(Protocol):
    async def send(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookResponse: ...


class WebhookEndpointStore(Protocol):
    async def get(self, endpoint_id: UUID) -> WebhookEndpoint | None: ...

    async def list_workspace(self, workspace_id: UUID) -> tuple[WebhookEndpoint, ...]: ...

    async def put(self, endpoint: WebhookEndpoint) -> None: ...


class WebhookDeliveryStore(Protocol):
    async def get(self, delivery_id: UUID) -> WebhookDelivery | None: ...

    async def get_by_event(self, endpoint_id: UUID, event_id: UUID) -> WebhookDelivery | None: ...

    async def list_due(self, now: datetime) -> tuple[WebhookDelivery, ...]: ...

    async def put(self, delivery: WebhookDelivery) -> None: ...


class InMemoryWebhookEndpointStore:
    def __init__(self) -> None:
        self._endpoints: dict[UUID, WebhookEndpoint] = {}
        self._lock = asyncio.Lock()

    async def get(self, endpoint_id: UUID) -> WebhookEndpoint | None:
        async with self._lock:
            return self._endpoints.get(endpoint_id)

    async def list_workspace(self, workspace_id: UUID) -> tuple[WebhookEndpoint, ...]:
        async with self._lock:
            endpoints = [
                endpoint
                for endpoint in self._endpoints.values()
                if endpoint.workspace_id == workspace_id
            ]
            endpoints.sort(key=lambda endpoint: endpoint.created_at, reverse=True)
            return tuple(endpoints)

    async def put(self, endpoint: WebhookEndpoint) -> None:
        async with self._lock:
            self._endpoints[endpoint.id] = endpoint


class InMemoryWebhookDeliveryStore:
    def __init__(self) -> None:
        self._deliveries: dict[UUID, WebhookDelivery] = {}
        self._events: dict[tuple[UUID, UUID], UUID] = {}
        self._lock = asyncio.Lock()

    async def get(self, delivery_id: UUID) -> WebhookDelivery | None:
        async with self._lock:
            return self._deliveries.get(delivery_id)

    async def get_by_event(self, endpoint_id: UUID, event_id: UUID) -> WebhookDelivery | None:
        async with self._lock:
            delivery_id = self._events.get((endpoint_id, event_id))
            return self._deliveries.get(delivery_id) if delivery_id is not None else None

    async def list_due(self, now: datetime) -> tuple[WebhookDelivery, ...]:
        async with self._lock:
            due = [
                delivery
                for delivery in self._deliveries.values()
                if delivery.status in {"pending", "retrying"}
                and (delivery.next_attempt_at is None or delivery.next_attempt_at <= now)
            ]
            due.sort(key=lambda delivery: delivery.created_at)
            return tuple(due)

    async def put(self, delivery: WebhookDelivery) -> None:
        async with self._lock:
            previous = self._deliveries.get(delivery.id)
            if previous is not None and previous.event_id != delivery.event_id:
                self._events.pop((previous.endpoint_id, previous.event_id), None)
            self._deliveries[delivery.id] = delivery
            self._events[(delivery.endpoint_id, delivery.event_id)] = delivery.id


class WebhookService:
    """Manage endpoints and perform bounded at-least-once delivery."""

    def __init__(
        self,
        endpoints: WebhookEndpointStore,
        deliveries: WebhookDeliveryStore,
        *,
        now: Callable[[], datetime] | None = None,
        resolve_host: Callable[[str], Sequence[str]] | None = None,
        disable_failure_threshold: int = DEFAULT_DISABLE_FAILURE_THRESHOLD,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delays_seconds: Sequence[int] = DEFAULT_RETRY_DELAYS_SECONDS,
    ) -> None:
        if disable_failure_threshold < 1:
            raise ValueError("disable_failure_threshold must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not retry_delays_seconds:
            raise ValueError("retry_delays_seconds cannot be empty")
        if any(delay < 1 for delay in retry_delays_seconds):
            raise ValueError("retry delays must be positive")
        self._endpoints = endpoints
        self._deliveries = deliveries
        self._now = _utc_now if now is None else now
        self._resolve_host = _resolve_host if resolve_host is None else resolve_host
        self._disable_failure_threshold = disable_failure_threshold
        self._max_attempts = max_attempts
        self._retry_delays = tuple(retry_delays_seconds)
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        workspace_id: UUID,
        created_by: UUID,
        url: str,
        events: Sequence[str],
    ) -> WebhookSecretIssue:
        normalized_url = validate_webhook_url(url, resolve_host=self._resolve_host)
        normalized_events = _normalize_events(events)
        now = _normalize_datetime(self._now())
        secret = f"whsec_{secrets.token_urlsafe(32)}"
        secret_hash = _secret_digest(secret)
        endpoint = WebhookEndpoint(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=created_by,
            url=normalized_url,
            secret_hash=secret_hash,
            secret_prefix=secret[:WEBHOOK_SECRET_PREFIX_LENGTH],
            events=frozenset(normalized_events),
            status="active",
            failure_count=0,
            last_delivered_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._endpoints.put(endpoint)
        return WebhookSecretIssue(endpoint=endpoint, secret=secret)

    async def list(self, workspace_id: UUID) -> tuple[WebhookEndpoint, ...]:
        return await self._endpoints.list_workspace(workspace_id)

    async def get(self, endpoint_id: UUID) -> WebhookEndpoint | None:
        return await self._endpoints.get(endpoint_id)

    async def enqueue(
        self,
        endpoint_id: UUID,
        *,
        event_type: str,
        payload: Mapping[str, object],
        event_id: UUID | None = None,
    ) -> WebhookDelivery:
        endpoint = await self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise WebhookError("WEBHOOK_NOT_FOUND", "Webhook endpoint was not found.")
        normalized_event = event_type.strip()
        if normalized_event not in WEBHOOK_EVENTS:
            raise WebhookError("WEBHOOK_EVENT_INVALID", "Webhook event type is not supported.")
        if normalized_event not in endpoint.events:
            raise WebhookError(
                "WEBHOOK_EVENT_NOT_SUBSCRIBED",
                "Endpoint is not subscribed to this event.",
            )
        if endpoint.status != "active":
            raise WebhookError("WEBHOOK_NOT_ACTIVE", "Webhook endpoint is not active.")
        serialized = _serialize_payload(payload)
        delivery_event_id = event_id or uuid4()
        existing = await self._deliveries.get_by_event(endpoint_id, delivery_event_id)
        if existing is not None:
            return existing
        delivery = WebhookDelivery(
            id=uuid4(),
            endpoint_id=endpoint_id,
            event_type=normalized_event,
            event_id=delivery_event_id,
            payload=dict(payload),
            status="pending",
            attempt_count=0,
            next_attempt_at=None,
            response_status=None,
            response_body_hash=None,
            delivered_at=None,
            created_at=_normalize_datetime(self._now()),
        )
        if len(serialized) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise WebhookError("WEBHOOK_PAYLOAD_TOO_LARGE", "Webhook payload is too large.")
        await self._deliveries.put(delivery)
        return delivery

    async def enqueue_for_workspace(
        self,
        workspace_id: UUID,
        *,
        event_type: str,
        payload: Mapping[str, object],
        event_id: UUID | None = None,
    ) -> tuple[WebhookDelivery, ...]:
        endpoints = await self._endpoints.list_workspace(workspace_id)
        deliveries: list[WebhookDelivery] = []
        for endpoint in endpoints:
            if endpoint.status != "active" or event_type not in endpoint.events:
                continue
            deliveries.append(
                await self.enqueue(
                    endpoint.id,
                    event_type=event_type,
                    payload=payload,
                    event_id=event_id,
                )
            )
        return tuple(deliveries)

    async def deliver(
        self,
        delivery_id: UUID,
        sender: WebhookHttpSender,
    ) -> WebhookDelivery:
        now = _normalize_datetime(self._now())
        async with self._lock:
            delivery = await self._deliveries.get(delivery_id)
            if delivery is None:
                raise WebhookError("WEBHOOK_DELIVERY_NOT_FOUND", "Webhook delivery was not found.")
            if delivery.status in {"delivered", "failed", "abandoned"}:
                return delivery
            if delivery.next_attempt_at is not None and delivery.next_attempt_at > now:
                return delivery
            endpoint = await self._endpoints.get(delivery.endpoint_id)
            if endpoint is None:
                abandoned = replace(delivery, status="abandoned", next_attempt_at=None)
                await self._deliveries.put(abandoned)
                return abandoned
            if endpoint.status != "active":
                abandoned = replace(delivery, status="abandoned", next_attempt_at=None)
                await self._deliveries.put(abandoned)
                return abandoned
            attempt = delivery.attempt_count + 1
            if attempt > self._max_attempts:
                abandoned = replace(delivery, status="abandoned", next_attempt_at=None)
                await self._deliveries.put(abandoned)
                return abandoned
            in_flight = replace(delivery, attempt_count=attempt, next_attempt_at=None)
            await self._deliveries.put(in_flight)

        try:
            validate_webhook_url(endpoint.url, resolve_host=self._resolve_host)
            body = _delivery_body(in_flight)
            headers = signed_webhook_headers(
                endpoint,
                body,
                timestamp=int(now.timestamp()),
                event_id=in_flight.event_id,
                event_type=in_flight.event_type,
            )
            response = await sender.send(endpoint.url, body, headers)
        except Exception:
            return await self._record_failure(in_flight, endpoint, None, now)
        if 200 <= response.status_code < 300:
            return await self._record_success(in_flight, endpoint, response, now)
        return await self._record_failure(in_flight, endpoint, response, now)

    async def deliver_due(
        self,
        sender: WebhookHttpSender,
    ) -> tuple[WebhookDelivery, ...]:
        now = _normalize_datetime(self._now())
        due = await self._deliveries.list_due(now)
        results: list[WebhookDelivery] = []
        for delivery in due:
            results.append(await self.deliver(delivery.id, sender))
        return tuple(results)

    async def _record_success(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookEndpoint,
        response: WebhookResponse,
        now: datetime,
    ) -> WebhookDelivery:
        async with self._lock:
            updated_delivery = replace(
                delivery,
                status="delivered",
                response_status=response.status_code,
                response_body_hash=_body_hash(response.body),
                delivered_at=now,
                next_attempt_at=None,
            )
            updated_endpoint = replace(
                endpoint,
                failure_count=0,
                last_delivered_at=now,
                updated_at=now,
            )
            await self._deliveries.put(updated_delivery)
            await self._endpoints.put(updated_endpoint)
            return updated_delivery

    async def _record_failure(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookEndpoint,
        response: WebhookResponse | None,
        now: datetime,
    ) -> WebhookDelivery:
        async with self._lock:
            failure_count = endpoint.failure_count + 1
            disabled = failure_count >= self._disable_failure_threshold
            terminal = delivery.attempt_count >= self._max_attempts
            status: DeliveryStatus
            next_attempt: datetime | None
            if disabled:
                status, next_attempt = "abandoned", None
            elif terminal:
                status, next_attempt = "failed", None
            else:
                status = "retrying"
                delay_index = min(delivery.attempt_count - 1, len(self._retry_delays) - 1)
                next_attempt = now + timedelta(seconds=self._retry_delays[delay_index])
            updated_delivery = replace(
                delivery,
                status=status,
                next_attempt_at=next_attempt,
                response_status=response.status_code if response else None,
                response_body_hash=_body_hash(response.body) if response else None,
            )
            updated_endpoint = replace(
                endpoint,
                failure_count=failure_count,
                status="disabled" if disabled else endpoint.status,
                updated_at=now,
            )
            await self._deliveries.put(updated_delivery)
            await self._endpoints.put(updated_endpoint)
            return updated_delivery


class HttpxWebhookSender:
    """Default sender with bounded timeout and redirect disabled."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    async def send(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookResponse:
        import httpx

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.post(url, content=body, headers=dict(headers))
        return WebhookResponse(response.status_code, response.content)


def validate_webhook_url(
    value: str,
    *,
    resolve_host: Callable[[str], Sequence[str]] | None = None,
) -> str:
    """Validate HTTPS and reject literal or DNS-resolved private addresses."""

    url = value.strip()
    if not url or len(url) > 2_048:
        raise WebhookError("WEBHOOK_URL_INVALID", "Webhook URL is invalid.")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise WebhookError("WEBHOOK_URL_INVALID", "Webhook URL is invalid.") from error
    if parsed.scheme.lower() != "https":
        raise WebhookError("WEBHOOK_URL_HTTPS_REQUIRED", "Webhook URL must use HTTPS.")
    if hostname is None or parsed.username is not None or parsed.password is not None:
        raise WebhookError(
            "WEBHOOK_URL_INVALID",
            "Webhook URL must include a hostname without credentials.",
        )
    if parsed.fragment:
        raise WebhookError("WEBHOOK_URL_INVALID", "Webhook URL cannot contain a fragment.")
    normalized_host = hostname.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise WebhookError("WEBHOOK_PRIVATE_ADDRESS", "Webhook URL cannot target localhost.")
    if normalized_host.endswith(".local"):
        raise WebhookError("WEBHOOK_PRIVATE_ADDRESS", "Webhook URL cannot target a local hostname.")
    addresses: tuple[str, ...]
    try:
        ipaddress.ip_address(normalized_host)
        addresses = (normalized_host,)
    except ValueError:
        resolver = _resolve_host if resolve_host is None else resolve_host
        try:
            addresses = tuple(resolver(normalized_host))
        except OSError as error:
            raise WebhookError(
                "WEBHOOK_DNS_FAILED",
                "Webhook hostname could not be resolved.",
            ) from error
        if not addresses:
            raise WebhookError(
                "WEBHOOK_DNS_FAILED",
                "Webhook hostname could not be resolved.",
            ) from None
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as error:
            raise WebhookError(
                "WEBHOOK_DNS_FAILED",
                "Webhook hostname resolved to an invalid address.",
            ) from error
        if _is_private_address(parsed_address):
            raise WebhookError(
                "WEBHOOK_PRIVATE_ADDRESS",
                "Webhook URL cannot target a private address.",
            )
    return _normalized_url(parsed)


def signed_webhook_headers(
    endpoint: WebhookEndpoint,
    body: bytes,
    *,
    timestamp: int,
    event_id: UUID | None = None,
    event_type: str | None = None,
) -> dict[str, str]:
    if timestamp <= 0:
        raise WebhookError("WEBHOOK_TIMESTAMP_INVALID", "Webhook timestamp is invalid.")
    signature = _signature(endpoint.secret_hash, timestamp, body)
    return {
        "Content-Type": "application/json",
        "User-Agent": "ClassVoice-Webhooks/1",
        "X-ClassVoice-Event-Id": str(event_id) if event_id else "",
        "X-ClassVoice-Event-Type": event_type or "",
        "X-ClassVoice-Timestamp": str(timestamp),
        "X-ClassVoice-Signature": f"t={timestamp},v1={signature}",
    }


def verify_webhook_signature(
    secret: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    now: datetime | None = None,
    tolerance_seconds: int = REPLAY_WINDOW_SECONDS,
) -> bool:
    """Verify a signed delivery and reject stale timestamps as replays."""

    if tolerance_seconds < 1:
        raise WebhookError("WEBHOOK_REPLAY_WINDOW_INVALID", "Replay window is invalid.")
    timestamp_value = _header(headers, "X-ClassVoice-Timestamp")
    signature_value = _header(headers, "X-ClassVoice-Signature")
    if timestamp_value is None or signature_value is None:
        raise WebhookError("WEBHOOK_SIGNATURE_INVALID", "Webhook signature headers are missing.")
    try:
        timestamp = int(timestamp_value)
    except ValueError as error:
        raise WebhookError("WEBHOOK_SIGNATURE_INVALID", "Webhook timestamp is invalid.") from error
    current = int((_normalize_datetime(now or _utc_now())).timestamp())
    if abs(current - timestamp) > tolerance_seconds:
        raise WebhookError(
            "WEBHOOK_SIGNATURE_REPLAY",
            "Webhook signature is outside the replay window.",
        )
    provided = _signature_from_header(signature_value, timestamp)
    expected = _signature(_secret_digest(secret), timestamp, body)
    if not hmac.compare_digest(provided, expected):
        raise WebhookError("WEBHOOK_SIGNATURE_INVALID", "Webhook signature is invalid.")
    return True


def _normalize_events(events: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(event.strip() for event in events if event.strip()))
    if not normalized:
        raise WebhookError("WEBHOOK_EVENTS_EMPTY", "At least one webhook event is required.")
    if len(normalized) > MAX_WEBHOOK_EVENTS or set(normalized) - WEBHOOK_EVENTS:
        raise WebhookError("WEBHOOK_EVENT_INVALID", "One or more webhook events are unsupported.")
    return tuple(sorted(normalized))


def _serialize_payload(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise WebhookError(
            "WEBHOOK_PAYLOAD_INVALID",
            "Webhook payload must be JSON serializable.",
        ) from error


def _delivery_body(delivery: WebhookDelivery) -> bytes:
    return _serialize_payload(
        {
            "id": str(delivery.event_id),
            "type": delivery.event_type,
            "created_at": delivery.created_at.isoformat(),
            "data": delivery.payload,
        }
    )


def _secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _signature(secret_digest: str, timestamp: int, body: bytes) -> str:
    signed = f"{timestamp}.".encode() + body
    return hmac.new(secret_digest.encode(), signed, hashlib.sha256).hexdigest()


def _signature_from_header(value: str, timestamp: int) -> str:
    header_timestamp: int | None = None
    candidate_signature: str | None = None
    for part in value.split(","):
        if part.startswith("t="):
            try:
                header_timestamp = int(part[2:])
            except ValueError as error:
                raise WebhookError(
                    "WEBHOOK_SIGNATURE_INVALID",
                    "Webhook signature is invalid.",
                ) from error
        if part.startswith("v1="):
            candidate = part[3:]
            if len(candidate) == 64 and all(
                character in "0123456789abcdef" for character in candidate
            ):
                candidate_signature = candidate
    if header_timestamp is not None and header_timestamp != timestamp:
        raise WebhookError("WEBHOOK_SIGNATURE_INVALID", "Webhook signature is invalid.")
    if candidate_signature is not None:
        return candidate_signature
    raise WebhookError("WEBHOOK_SIGNATURE_INVALID", "Webhook signature is invalid.")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    normalized_name = name.lower()
    for key, value in headers.items():
        if key.lower() == normalized_name:
            return value
    return None


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _resolve_host(hostname: str) -> tuple[str, ...]:
    addresses: set[str] = set()
    for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM):
        address = str(item[4][0])
        addresses.add(address)
    return tuple(sorted(addresses))


def _is_private_address(address: IPv4Address | IPv6Address) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_unspecified,
            address.is_reserved,
            not address.is_global,
        )
    )


def _normalized_url(parsed: SplitResult) -> str:
    return parsed.geturl()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WebhookError("WEBHOOK_TIME_INVALID", "Webhook timestamps must include a timezone.")
    return value.astimezone(UTC)
