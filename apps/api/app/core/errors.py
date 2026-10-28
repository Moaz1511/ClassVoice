"""Stable API error types and the JSON envelope contract."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """An expected API failure that is safe to expose to the caller."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details) if details is not None else None


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else "unknown"


def envelope(
    request: Request,
    *,
    data: Any = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {"data": data, "error": error, "request_id": request_id_for(request)}


async def api_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, APIError):
        return await unexpected_error_handler(request, error)
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            error={"code": error.code, "message": error.message, "details": error.details},
        ),
    )


async def validation_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        return await unexpected_error_handler(request, error)
    return JSONResponse(
        status_code=422,
        content=envelope(
            request,
            error={
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {"fields": error.errors()},
            },
        ),
    )


async def http_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, StarletteHTTPException):
        return await unexpected_error_handler(request, error)
    try:
        default_message = HTTPStatus(error.status_code).phrase
    except ValueError:
        default_message = "Request failed."
    details: Mapping[str, Any] | None = None
    message = default_message
    if isinstance(error.detail, str):
        message = error.detail
    elif isinstance(error.detail, Mapping):
        message = str(error.detail.get("message", default_message))
        raw_details = error.detail.get("details")
        if isinstance(raw_details, Mapping):
            details = raw_details
    return JSONResponse(
        status_code=error.status_code,
        content=envelope(
            request,
            error={
                "code": f"HTTP_{error.status_code}",
                "message": message,
                "details": details,
            },
        ),
    )


async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=envelope(
            request,
            error={
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "details": None,
            },
        ),
    )
