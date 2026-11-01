from __future__ import annotations

import os
from typing import cast
from uuid import uuid4

import httpx
import pytest
from app.core.errors import APIError
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimitBackendError,
    RateLimitPolicy,
    RedisRateLimiter,
    enforce_rate_limit,
    request_policy,
)
from app.core.settings import APISettings
from app.main import create_app
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> list[int]:
        self.calls.append(args)
        if self.fail:
            raise RedisConnectionError("synthetic outage")
        return [int(args[-2]), 60]

    async def ping(self) -> bool:
        return not self.fail

    async def aclose(self) -> None:
        return None


class UnhealthyLimiter(InMemoryRateLimiter):
    async def healthcheck(self) -> bool:
        return False


async def test_in_memory_limiter_enforces_weighted_cost_and_resets() -> None:
    current = [120.0]
    limiter = InMemoryRateLimiter(now=lambda: current[0])
    policy = RateLimitPolicy("test-weighted", 5, 60)

    first = await limiter.consume(policy, "actor-1", cost=3)
    denied = await limiter.consume(policy, "actor-1", cost=3)
    other_actor = await limiter.consume(policy, "actor-2", cost=5)
    current[0] = 180.0
    reset = await limiter.consume(policy, "actor-1", cost=5)

    assert first.allowed and first.remaining == 2
    assert not denied.allowed and denied.remaining == 0
    assert other_actor.allowed
    assert reset.allowed and reset.remaining == 0


async def test_redis_limiter_uses_atomic_script_and_hides_subject() -> None:
    fake = FakeRedis()
    limiter = RedisRateLimiter(
        "redis://unused:6379/0",
        client=cast(Redis, fake),
        now=lambda: 120.0,
    )

    decision = await limiter.consume(
        RateLimitPolicy("test-redis", 10, 60),
        "Bearer private-test-credential",
        cost=2,
    )

    assert decision.allowed and decision.remaining == 8
    assert len(fake.calls) == 1
    redis_key = str(fake.calls[0][2])
    assert redis_key.startswith("classvoice:rate:test-redis:")
    assert "private-test-credential" not in redis_key


async def test_redis_failure_is_fail_closed_at_domain_boundary() -> None:
    limiter = RedisRateLimiter(
        "redis://unused:6379/0",
        client=cast(Redis, FakeRedis(fail=True)),
    )
    policy = RateLimitPolicy("test-failure", 10, 60)

    with pytest.raises(RateLimitBackendError):
        await limiter.consume(policy, "actor")

    with pytest.raises(APIError) as captured:
        await enforce_rate_limit(limiter, policy, "actor")
    assert captured.value.status_code == 503
    assert captured.value.code == "RATE_LIMIT_UNAVAILABLE"


async def test_weighted_domain_quota_exposes_retry_headers() -> None:
    limiter = InMemoryRateLimiter(now=lambda: 120.0)
    policy = RateLimitPolicy("test-domain-quota", 5, 60)
    await enforce_rate_limit(limiter, policy, "actor", cost=5)

    with pytest.raises(APIError) as captured:
        await enforce_rate_limit(limiter, policy, "actor", cost=1)

    assert captured.value.status_code == 429
    assert captured.value.headers == {
        "RateLimit-Limit": "5",
        "RateLimit-Remaining": "0",
        "RateLimit-Reset": "60",
        "Retry-After": "60",
    }


async def test_redis_limiter_is_shared_across_process_boundaries() -> None:
    redis_url = os.getenv("CLASSVOICE_INTEGRATION_REDIS_URL")
    if redis_url is None:
        pytest.skip("CLASSVOICE_INTEGRATION_REDIS_URL is not set")
    first_limiter = RedisRateLimiter(redis_url, namespace="classvoice-test")
    second_limiter = RedisRateLimiter(redis_url, namespace="classvoice-test")
    subject = f"integration:{uuid4()}"
    policy = RateLimitPolicy("integration-shared", 1, 60)
    try:
        first = await first_limiter.consume(policy, subject)
        second = await second_limiter.consume(policy, subject)
    finally:
        await first_limiter.close()
        await second_limiter.close()

    assert first.allowed
    assert not second.allowed


async def test_request_middleware_returns_stable_429_envelope_and_headers() -> None:
    app = create_app(APISettings.from_env({}))
    headers = {"Authorization": "Bearer synthetic-invalid-token"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        responses = [
            await client.post("/v1/generations", headers=headers, json={})
            for _ in range(31)
        ]

    assert all(response.status_code != 429 for response in responses[:30])
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.json()["request_id"] != "unknown"
    assert limited.headers["ratelimit-limit"] == "30"
    assert limited.headers["ratelimit-remaining"] == "0"
    assert int(limited.headers["retry-after"]) > 0


async def test_readiness_fails_when_rate_limit_backend_is_unavailable() -> None:
    app = create_app(APISettings.from_env({}))
    app.state.rate_limiter = UnhealthyLimiter()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "unavailable"
    assert response.json()["data"]["checks"]["rate_limit"] == "error"


async def test_route_policy_distinguishes_expensive_and_general_operations() -> None:
    assert request_policy("POST", "/v1/generations").name == "generation-create"
    assert request_policy("POST", "/v1/voices/upload-url").name == "voice-upload"
    assert (
        request_policy(
            "GET", "/v1/generations/00000000-0000-0000-0000-000000000001/download"
        ).name
        == "generation-download"
    )
    assert request_policy("GET", "/health/ready") is None
    assert request_policy("GET", "/v1/voices").name == "v1-read"
