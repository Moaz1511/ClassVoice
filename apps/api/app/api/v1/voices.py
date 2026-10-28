"""Voice upload-intent HTTP endpoints."""

from __future__ import annotations

from uuid import UUID

from app.core.authorization import (
    AuthorizationError,
    InMemoryMembershipStore,
    WorkspaceMembershipStore,
    require_authenticated,
    require_workspace_access,
)
from app.core.errors import APIError, envelope
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier
from app.domains.voices.upload_intent import (
    InMemoryUploadIntentStore,
    UploadIntentError,
    UploadIntentRequest,
    UploadIntentService,
)
from fastapi import APIRouter, Depends, FastAPI, Header, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/voices", tags=["voices"])


class UploadIntentBody(BaseModel):
    workspace_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=25_000_000)


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return request.app.state.membership_store


async def _claims(request: Request, authorization: str | None = Header(default=None)) -> AuthClaims:
    verifier: JWTVerifier | None = request.app.state.jwt_verifier
    if verifier is None:
        raise APIError(503, "AUTH_NOT_CONFIGURED", "Authentication is not configured for this API.")
    try:
        return require_authenticated(authorization, verifier)
    except JWTVerificationError as error:
        raise APIError(401, error.code, str(error)) from error


@router.post("/upload-url", status_code=201)
async def create_upload_intent(
    body: UploadIntentBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
    membership_store: WorkspaceMembershipStore = Depends(_membership_store),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object]:
    try:
        await require_workspace_access(
            claims,
            body.workspace_id,
            membership_store,
            minimum_role="editor",
            required_scope="voices:write",
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    if idempotency_key is None:
        raise APIError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    service: UploadIntentService = request.app.state.upload_intent_service
    try:
        intent = await service.create(
            UploadIntentRequest(
                workspace_id=body.workspace_id,
                filename=body.filename,
                content_type=body.content_type,
                size_bytes=body.size_bytes,
            ),
            idempotency_key,
        )
    except UploadIntentError as error:
        status = 409 if error.code == "IDEMPOTENCY_KEY_REUSED" else 400
        raise APIError(status, error.code, str(error)) from error
    return envelope(request, data=intent.as_dict())


def configure_upload_state(app: FastAPI) -> None:
    """Install safe default state; production replaces the membership store with DB access."""

    app.state.membership_store = InMemoryMembershipStore()
    app.state.upload_intent_store = InMemoryUploadIntentStore()
    app.state.upload_intent_service = UploadIntentService(
        app.state.storage_adapter, app.state.upload_intent_store
    )
