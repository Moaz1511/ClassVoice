from __future__ import annotations

import httpx
import pytest
from app.core.errors import APIError
from app.core.settings import APISettings
from app.main import create_app
from fastapi import Query

pytestmark = pytest.mark.asyncio


def make_app():
    return create_app(APISettings.from_env({}))


async def test_live_health_uses_envelope_and_correlation_header() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "test:req-01"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test:req-01"
    assert response.json() == {
        "data": {"status": "ok", "service": "ClassVoice API", "version": "0.1.0"},
        "error": None,
        "request_id": "test:req-01",
    }


async def test_invalid_request_id_is_replaced_and_cors_is_explicit() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "X-Request-ID": "bad request id",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["x-request-id"] != "bad request id"


async def test_validation_errors_use_safe_envelope() -> None:
    app = make_app()

    @app.get("/test-validation")
    async def validation(value: int = Query(...)) -> dict[str, int]:
        return {"value": value}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(
            "/test-validation?value=not-an-int",
            headers={"X-Request-ID": "validation-01"},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["request_id"] == "validation-01"
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed."


async def test_expected_and_unexpected_errors_are_redacted() -> None:
    app = make_app()

    @app.get("/test-api-error")
    async def expected_error() -> None:
        raise APIError(409, "SYNTHETIC_CONFLICT", "Synthetic conflict.")

    @app.get("/test-unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("secret database password")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        expected = await client.get("/test-api-error")
        unexpected = await client.get("/test-unexpected-error")

    assert expected.status_code == 409
    assert expected.json()["error"]["code"] == "SYNTHETIC_CONFLICT"
    assert unexpected.status_code == 500
    assert unexpected.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
        "details": None,
    }
    assert "secret database password" not in unexpected.text


async def test_framework_http_errors_use_the_same_envelope() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "HTTP_404",
        "message": "Not Found",
        "details": None,
    }
