"""Workspace administrator webhook endpoint routes."""

from __future__ import annotations

from uuid import UUID

from app.core.authorization import (
    AuthorizationError,
    WorkspaceMembershipStore,
    require_authenticated,
    require_workspace_access,
)
from app.core.errors import APIError, envelope
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier
from app.domains.webhooks.service import WebhookError, WebhookService
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class CreateWebhookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    url: str = Field(min_length=1, max_length=2_048)
    events: list[str] = Field(min_length=1, max_length=20)


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return request.app.state.membership_store


def _service(request: Request) -> WebhookService:
    return request.app.state.webhook_service


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
async def create_webhook(
    body: CreateWebhookBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_admin(request, claims, body.workspace_id, scope="webhooks:write")
    try:
        issue = await _service(request).create(
            workspace_id=body.workspace_id,
            created_by=claims.subject,
            url=body.url,
            events=body.events,
        )
    except WebhookError as error:
        raise APIError(400, error.code, str(error)) from error
    return envelope(
        request,
        data={
            "webhook": issue.endpoint.as_dict(),
            "secret": issue.secret,
            "secret_warning": "Copy this secret now. It cannot be shown again.",
        },
    )


@router.get("")
async def list_webhooks(
    request: Request,
    workspace_id: UUID = Query(...),  # noqa: B008
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_admin(request, claims, workspace_id, scope="webhooks:read")
    endpoints = await _service(request).list(workspace_id)
    return envelope(request, data={"items": [endpoint.as_dict() for endpoint in endpoints]})


def configure_webhook_state(app: FastAPI) -> None:
    """Install local endpoint/delivery stores; production replaces them with SQL."""

    from app.domains.webhooks.service import (  # noqa: PLC0415
        InMemoryWebhookDeliveryStore,
        InMemoryWebhookEndpointStore,
    )

    app.state.webhook_endpoint_store = InMemoryWebhookEndpointStore()
    app.state.webhook_delivery_store = InMemoryWebhookDeliveryStore()
    app.state.webhook_service = WebhookService(
        app.state.webhook_endpoint_store,
        app.state.webhook_delivery_store,
    )
