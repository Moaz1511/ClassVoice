"""Voice upload-intent and voice-profile lifecycle HTTP endpoints."""

from __future__ import annotations

from typing import Literal
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
from app.domains.audit.service import AuditService
from app.domains.voices.lifecycle import (
    InMemoryVoiceStore,
    VoiceLifecycleError,
    VoiceLifecycleService,
    VoiceProfile,
)
from app.domains.voices.upload_intent import (
    InMemoryUploadIntentStore,
    UploadIntentError,
    UploadIntentRequest,
    UploadIntentService,
)
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/voices", tags=["voices"])


class UploadIntentBody(BaseModel):
    workspace_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=25_000_000)


class CreateVoiceBody(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=120)
    language_code: str = Field(min_length=2, max_length=10)
    consent_statement_version: str = Field(min_length=1, max_length=64)
    consent_attestation_text_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    reference_upload_id: UUID | None = None


class UpdateVoiceBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    language_code: str | None = Field(default=None, min_length=2, max_length=10)
    status: Literal["draft", "archived"] | None = None


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return request.app.state.membership_store


def _voice_service(request: Request) -> VoiceLifecycleService:
    return request.app.state.voice_service


def _audit(request: Request) -> AuditService:
    return request.app.state.audit_service


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
    await _audit(request).emit_request(
        request,
        action="voice.upload_intent.created",
        resource_type="audio_asset",
        workspace_id=body.workspace_id,
        resource_id=intent.upload_id,
        actor=claims,
        metadata={"content_type": body.content_type, "size_bytes": body.size_bytes},
    )
    return envelope(request, data=intent.as_dict())


async def _authorize_voice(
    request: Request,
    claims: AuthClaims,
    voice_id: UUID,
    *,
    minimum_role: Literal["viewer", "editor", "admin"],
) -> VoiceProfile:
    service = _voice_service(request)
    voice = await service.get(voice_id)
    if voice is None:
        raise APIError(404, "VOICE_NOT_FOUND", "Voice was not found.")
    try:
        await require_workspace_access(
            claims,
            voice.workspace_id,
            _membership_store(request),
            minimum_role=minimum_role,
            required_scope="voices:read" if minimum_role == "viewer" else "voices:write",
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    return voice


@router.get("")
async def list_voices(
    request: Request,
    workspace_id: UUID = Query(...),  # noqa: B008
    include_archived: bool = Query(default=False),
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    try:
        await require_workspace_access(
            claims,
            workspace_id,
            _membership_store(request),
            minimum_role="viewer",
            required_scope="voices:read",
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    voices = await _voice_service(request).list(workspace_id, include_archived=include_archived)
    return envelope(request, data={"items": [voice.as_dict() for voice in voices]})


@router.post("", status_code=201)
async def create_voice(
    body: CreateVoiceBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object]:
    try:
        await require_workspace_access(
            claims,
            body.workspace_id,
            _membership_store(request),
            minimum_role="editor",
            required_scope="voices:write",
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error
    if idempotency_key is None:
        raise APIError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        voice = await _voice_service(request).create(
            workspace_id=body.workspace_id,
            actor_id=claims.subject,
            name=body.name,
            language_code=body.language_code,
            consent_statement_version=body.consent_statement_version,
            consent_attestation_text_hash=body.consent_attestation_text_hash,
            reference_upload_id=body.reference_upload_id,
            idempotency_key=idempotency_key,
        )
    except VoiceLifecycleError as error:
        status = 409 if error.code == "IDEMPOTENCY_KEY_REUSED" else 400
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="voice.created",
        resource_type="voice_profile",
        workspace_id=voice.workspace_id,
        resource_id=voice.id,
        actor=claims,
        metadata={"language_code": voice.language_code},
    )
    return envelope(request, data=voice.as_dict())


@router.get("/{voice_id}")
async def get_voice(
    voice_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    voice = await _authorize_voice(request, claims, voice_id, minimum_role="viewer")
    return envelope(request, data=voice.as_dict())


@router.patch("/{voice_id}")
async def update_voice(
    voice_id: UUID,
    body: UpdateVoiceBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_voice(request, claims, voice_id, minimum_role="editor")
    if body.name is None and body.language_code is None and body.status is None:
        raise APIError(400, "VOICE_UPDATE_EMPTY", "At least one voice field must be provided.")
    try:
        voice = await _voice_service(request).update(
            voice_id,
            claims.subject,
            name=body.name,
            language_code=body.language_code,
            status=body.status,
        )
    except VoiceLifecycleError as error:
        status = 404 if error.code == "VOICE_NOT_FOUND" else 409
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="voice.updated",
        resource_type="voice_profile",
        workspace_id=voice.workspace_id,
        resource_id=voice.id,
        actor=claims,
        metadata={"fields": [key for key, value in body.model_dump().items() if value is not None]},
    )
    return envelope(request, data=voice.as_dict())


@router.post("/{voice_id}/revoke")
async def revoke_voice(
    voice_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_voice(request, claims, voice_id, minimum_role="editor")
    try:
        voice = await _voice_service(request).revoke(voice_id, claims.subject)
    except VoiceLifecycleError as error:
        status = 404 if error.code == "VOICE_NOT_FOUND" else 409
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="voice.consent_revoked",
        resource_type="voice_profile",
        workspace_id=voice.workspace_id,
        resource_id=voice.id,
        actor=claims,
    )
    return envelope(request, data=voice.as_dict())


@router.delete("/{voice_id}", status_code=202)
async def delete_voice(
    voice_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    voice = await _authorize_voice(request, claims, voice_id, minimum_role="admin")
    try:
        task = await _voice_service(request).delete(voice_id, claims.subject)
    except VoiceLifecycleError as error:
        status = 404 if error.code == "VOICE_NOT_FOUND" else 409
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="voice.deletion_queued",
        resource_type="voice_profile",
        workspace_id=voice.workspace_id,
        resource_id=task.voice_id,
        actor=claims,
    )
    return envelope(
        request,
        data={
            "voice_id": str(task.voice_id),
            "status": "deletion_queued",
            "queued_at": task.queued_at.isoformat(),
        },
    )


def configure_upload_state(app: FastAPI) -> None:
    """Install safe default state; production replaces the membership store with DB access."""

    app.state.membership_store = InMemoryMembershipStore()
    app.state.upload_intent_store = InMemoryUploadIntentStore()
    app.state.upload_intent_service = UploadIntentService(
        app.state.storage_adapter, app.state.upload_intent_store
    )
    app.state.voice_store = InMemoryVoiceStore()
    app.state.voice_service = VoiceLifecycleService(app.state.voice_store)
