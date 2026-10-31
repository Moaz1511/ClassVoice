"""Workspace administrator API-key management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from app.core.authorization import (
    AuthorizationError,
    WorkspaceMembershipStore,
    require_authenticated,
    require_workspace_access,
)
from app.core.errors import APIError, envelope
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier
from app.domains.api_keys.service import ApiKeyError, ApiKeyService
from app.domains.audit.service import AuditService
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_at: datetime | None = None


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return cast(WorkspaceMembershipStore, request.app.state.membership_store)


def _service(request: Request) -> ApiKeyService:
    return cast(ApiKeyService, request.app.state.api_key_service)


def _audit(request: Request) -> AuditService:
    return cast(AuditService, request.app.state.audit_service)


async def _claims(request: Request, authorization: str | None = Header(default=None)) -> AuthClaims:
    verifier: JWTVerifier | None = request.app.state.jwt_verifier
    if verifier is None:
        raise APIError(503, "AUTH_NOT_CONFIGURED", "Authentication is not configured for this API.")
    try:
        return require_authenticated(authorization, verifier)
    except JWTVerificationError as error:
        raise APIError(401, error.code, str(error)) from error


async def _authorize_admin(
    request: Request,
    claims: AuthClaims,
    workspace_id: UUID,
    *,
    scope: str,
) -> None:
    try:
        await require_workspace_access(
            claims,
            workspace_id,
            _membership_store(request),
            minimum_role="admin",
            required_scope=scope,
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error


@router.post("", status_code=201)
async def create_api_key(
    body: CreateApiKeyBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_admin(request, claims, body.workspace_id, scope="api_keys:write")
    try:
        issue = await _service(request).create(
            workspace_id=body.workspace_id,
            created_by=claims.subject,
            name=body.name,
            scopes=body.scopes,
            expires_at=body.expires_at,
        )
    except ApiKeyError as error:
        raise APIError(400, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="api_key.created",
        resource_type="api_key",
        workspace_id=issue.record.workspace_id,
        resource_id=issue.record.id,
        actor=claims,
        metadata={
            "scopes": body.scopes,
            "expires_at": body.expires_at.isoformat() if body.expires_at else None,
        },
    )
    return envelope(
        request,
        data={
            "api_key": issue.record.as_dict(),
            "secret": issue.secret,
            "secret_warning": "Copy this secret now. It cannot be shown again.",
        },
    )


@router.get("")
async def list_api_keys(
    request: Request,
    workspace_id: UUID = Query(...),  # noqa: B008
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_admin(request, claims, workspace_id, scope="api_keys:read")
    keys = await _service(request).list(workspace_id)
    return envelope(request, data={"items": [record.as_dict() for record in keys]})


@router.post("/{key_id}/revoke")
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    existing = await _service(request).get(key_id)
    if existing is None:
        raise APIError(404, "API_KEY_NOT_FOUND", "API key was not found.")
    await _authorize_admin(request, claims, existing.workspace_id, scope="api_keys:write")
    try:
        record = await _service(request).revoke(key_id, existing.workspace_id)
    except ApiKeyError as error:
        status = 404 if error.code == "API_KEY_NOT_FOUND" else 400
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="api_key.revoked",
        resource_type="api_key",
        workspace_id=record.workspace_id,
        resource_id=record.id,
        actor=claims,
    )
    return envelope(request, data={"api_key": record.as_dict()})


def configure_api_key_state(app: FastAPI) -> None:
    """Install the local API-key store; production replaces it with SQL."""

    from app.domains.api_keys.service import InMemoryApiKeyStore  # noqa: PLC0415

    app.state.api_key_store = InMemoryApiKeyStore()
    app.state.api_key_service = ApiKeyService(app.state.api_key_store)
