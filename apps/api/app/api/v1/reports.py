"""Member abuse-report submission and moderator-only review endpoints."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.core.authorization import (
    AuthorizationError,
    WorkspaceMembershipStore,
    require_authenticated,
    require_moderator,
    require_workspace_access,
)
from app.core.errors import APIError, envelope
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier
from app.domains.audit.service import AuditService
from app.domains.moderation.service import (
    InMemoryModerationReportStore,
    ModerationReportError,
    ModerationReportService,
    ModerationStatus,
)
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/reports", tags=["moderation"])


class CreateReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: UUID
    reason_code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2_000)


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return cast(WorkspaceMembershipStore, request.app.state.membership_store)


def _service(request: Request) -> ModerationReportService:
    return cast(ModerationReportService, request.app.state.moderation_report_service)


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


@router.post("", status_code=201)
async def create_report(
    body: CreateReportBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    try:
        await require_workspace_access(
            claims,
            body.workspace_id,
            _membership_store(request),
            minimum_role="viewer",
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    try:
        report = await _service(request).create(
            workspace_id=body.workspace_id,
            reporter_user_id=claims.subject,
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            reason_code=body.reason_code,
            description=body.description,
        )
    except ModerationReportError as error:
        raise APIError(400, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="moderation.reported",
        resource_type="moderation_flag",
        workspace_id=body.workspace_id,
        resource_id=report.id,
        actor=claims,
        metadata={"reported_resource_type": body.resource_type, "reason_code": body.reason_code},
    )
    return envelope(request, data=report.as_dict())


@router.get("")
async def list_reports(
    request: Request,
    status: ModerationStatus | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    try:
        require_moderator(claims)
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    reports = await _service(request).list(status=status, limit=limit)
    return envelope(request, data={"items": [report.as_dict() for report in reports]})


def configure_moderation_state(app: FastAPI) -> None:
    store = InMemoryModerationReportStore()
    app.state.moderation_report_store = store
    app.state.moderation_report_service = ModerationReportService(store)
