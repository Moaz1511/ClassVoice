"""Distributed request and generation-character rate limiting.

Local/test processes use the deterministic in-memory backend. Hosted profiles
must select Redis so limits are shared by every API replica. Subjects are
irreversibly hashed before they enter keys and are never logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import APIError, envelope


class RateLimitBackendError(RuntimeError):
    """Raised when the shared limiter cannot make an authoritative decision."""


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", self.name):
            raise ValueError("rate-limit policy name is invalid")
        if self.limit <= 0 or self.window_seconds <= 0:
            raise ValueError("rate-limit values must be positive")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter(Protocol):
    async def consume(
        self,
        policy: RateLimitPolicy,
        subject: str,
        *,
        cost: int = 1,
    ) -> RateLimitDecision: ...

    async def healthcheck(self) -> bool: ...

    async def close(self) -> None: ...


class InMemoryRateLimiter:
    """Process-local backend for deterministic development and unit tests."""

    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._counters: dict[tuple[str, str, int], int] = {}
        self._lock = asyncio.Lock()

    async def consume(
        self,
        policy: RateLimitPolicy,
        subject: str,
        *,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate_cost(cost)
        now = self._now()
        window = int(now // policy.window_seconds)
        reset = max(1, int(((window + 1) * policy.window_seconds) - now))
        key = (policy.name, _subject_digest(subject), window)
        async with self._lock:
            current = self._counters.get(key, 0) + cost
            self._counters[key] = current
            if len(self._counters) > 4096:
                self._counters = {
                    item_key: value
                    for item_key, value in self._counters.items()
                    if item_key[2] >= window - 1
                }
        return RateLimitDecision(
            allowed=current <= policy.limit,
            limit=policy.limit,
            remaining=max(0, policy.limit - current),
            reset_seconds=reset,
        )

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None


_REDIS_CONSUME_SCRIPT = """
local current = redis.call('INCRBY', KEYS[1], ARGV[1])
if current == tonumber(ARGV[1]) then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RedisRateLimiter:
    """Atomic fixed-window limiter shared by API replicas through Redis."""

    def __init__(
        self,
        redis_url: str,
        *,
        namespace: str = "classvoice",
        client: Redis | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", namespace):
            raise ValueError("rate-limit namespace is invalid")
        self._namespace = namespace
        self._client = client or Redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        self._now = now

    async def consume(
        self,
        policy: RateLimitPolicy,
        subject: str,
        *,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate_cost(cost)
        now = self._now()
        window = int(now // policy.window_seconds)
        reset = max(1, int(((window + 1) * policy.window_seconds) - now))
        key = (
            f"{self._namespace}:rate:{policy.name}:"
            f"{_subject_digest(subject)}:{window}"
        )
        try:
            result = await cast(
                Awaitable[object],
                self._client.eval(
                    _REDIS_CONSUME_SCRIPT,
                    1,
                    key,
                    str(cost),
                    str(policy.window_seconds + 1),
                ),
            )
        except RedisError as error:
            raise RateLimitBackendError("Redis rate limiter is unavailable") from error
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise RateLimitBackendError("Redis rate limiter returned an invalid response")
        current = int(result[0])
        ttl = int(result[1])
        return RateLimitDecision(
            allowed=current <= policy.limit,
            limit=policy.limit,
            remaining=max(0, policy.limit - current),
            reset_seconds=max(1, min(reset, ttl if ttl > 0 else reset)),
        )

    async def healthcheck(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        await self._client.aclose()


UPLOAD_POLICY = RateLimitPolicy("voice-upload", 20, 60)
GENERATION_REQUEST_POLICY = RateLimitPolicy("generation-create", 30, 60)
GENERATION_CHARACTER_POLICY = RateLimitPolicy("generation-characters", 50_000, 3600)
DOWNLOAD_POLICY = RateLimitPolicy("generation-download", 60, 60)
REPORT_POLICY = RateLimitPolicy("moderation-report", 10, 3600)
API_KEY_POLICY = RateLimitPolicy("api-key-admin", 10, 3600)
WEBHOOK_POLICY = RateLimitPolicy("webhook-admin", 30, 3600)
MUTATION_POLICY = RateLimitPolicy("v1-mutation", 120, 60)
READ_POLICY = RateLimitPolicy("v1-read", 600, 60)

_DOWNLOAD_PATH = re.compile(r"^/v1/generations/[0-9a-fA-F-]{36}/download$")
_API_KEY_PATH = re.compile(r"^/v1/api-keys(?:/[0-9a-fA-F-]{36})?(?:/revoke)?$")


def request_policy(method: str, path: str) -> RateLimitPolicy | None:
    """Return the bounded request policy for a concrete HTTP path."""

    if method == "OPTIONS" or not path.startswith("/v1/"):
        return None
    if method == "POST" and path == "/v1/voices/upload-url":
        return UPLOAD_POLICY
    if method == "POST" and path == "/v1/generations":
        return GENERATION_REQUEST_POLICY
    if method == "GET" and _DOWNLOAD_PATH.fullmatch(path):
        return DOWNLOAD_POLICY
    if method == "POST" and path == "/v1/reports":
        return REPORT_POLICY
    if _API_KEY_PATH.fullmatch(path) and method in {"POST", "DELETE"}:
        return API_KEY_POLICY
    if path.startswith("/v1/webhooks") and method in {"POST", "PATCH", "DELETE"}:
        return WEBHOOK_POLICY
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return MUTATION_POLICY
    return READ_POLICY


class RateLimitMiddleware:
    """Apply shared limits before an API request reaches expensive handlers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        fail_closed: bool,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.fail_closed = fail_closed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))
        policy = request_policy(method, path)
        if policy is None:
            await self.app(scope, receive, send)
            return
        subject = _request_subject(scope)
        try:
            decision = await self.limiter.consume(policy, subject)
        except RateLimitBackendError:
            if not self.fail_closed:
                await self.app(scope, receive, send)
                return
            await _error_response(
                scope,
                receive,
                send,
                status_code=503,
                code="RATE_LIMIT_UNAVAILABLE",
                message="Request protection is temporarily unavailable.",
            )
            return
        if not decision.allowed:
            await _error_response(
                scope,
                receive,
                send,
                status_code=429,
                code="RATE_LIMITED",
                message="Too many requests. Retry after the indicated delay.",
                decision=decision,
            )
            return

        async def send_with_limits(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _value in headers}
                if b"ratelimit-limit" not in existing:
                    headers.extend(_decision_headers(decision))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_limits)


async def enforce_rate_limit(
    limiter: RateLimiter,
    policy: RateLimitPolicy,
    subject: str,
    *,
    cost: int = 1,
) -> RateLimitDecision:
    """Enforce a domain quota after authorization resolves a stable subject."""

    try:
        decision = await limiter.consume(policy, subject, cost=cost)
    except RateLimitBackendError as error:
        raise APIError(
            503,
            "RATE_LIMIT_UNAVAILABLE",
            "Request protection is temporarily unavailable.",
        ) from error
    if not decision.allowed:
        headers = {
            "RateLimit-Limit": str(decision.limit),
            "RateLimit-Remaining": str(decision.remaining),
            "RateLimit-Reset": str(decision.reset_seconds),
            "Retry-After": str(decision.reset_seconds),
        }
        raise APIError(
            429,
            "RATE_LIMITED",
            "The generation character quota has been exceeded.",
            {"retry_after_seconds": decision.reset_seconds},
            headers,
        )
    return decision


def _request_subject(scope: Scope) -> str:
    headers = {
        key.lower(): value
        for key, value in scope.get("headers", [])
        if len(key) <= 64 and len(value) <= 4096
    }
    credential = headers.get(b"x-api-key") or headers.get(b"authorization")
    if credential:
        return f"credential:{credential.decode('utf-8', errors='ignore')}"
    client = scope.get("client")
    host = client[0] if isinstance(client, tuple) and client else "unknown"
    return f"client:{host}"


def _subject_digest(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _validate_cost(cost: int) -> None:
    if cost <= 0 or cost > 1_000_000:
        raise ValueError("rate-limit cost must be between 1 and 1,000,000")


def _decision_headers(decision: RateLimitDecision) -> list[tuple[bytes, bytes]]:
    return [
        (b"ratelimit-limit", str(decision.limit).encode("ascii")),
        (b"ratelimit-remaining", str(decision.remaining).encode("ascii")),
        (b"ratelimit-reset", str(decision.reset_seconds).encode("ascii")),
    ]


async def _error_response(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    decision: RateLimitDecision | None = None,
) -> None:
    request = Request(scope, receive=receive)
    response = JSONResponse(
        status_code=status_code,
        content=envelope(
            request,
            error={
                "code": code,
                "message": message,
                "details": (
                    {"retry_after_seconds": decision.reset_seconds}
                    if decision is not None
                    else None
                ),
            },
        ),
    )
    if decision is not None:
        for key, value in _decision_headers(decision):
            response.headers.append(key.decode("ascii"), value.decode("ascii"))
        response.headers["Retry-After"] = str(decision.reset_seconds)
    await response(scope, receive, send)
