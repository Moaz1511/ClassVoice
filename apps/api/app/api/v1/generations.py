"""Generation job HTTP endpoints."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.core.authorization import (
    AuthorizationError,
    WorkspaceMembershipStore,
    require_authenticated,
    require_workspace_access,
)
from app.core.errors import APIError, envelope
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier
from app.domains.generations.jobs import (
    GenerationError,
    GenerationJob,
    GenerationService,
    GenerationStatus,
)
from app.domains.generations.outputs import PrivateGenerationOutputStore
from app.storage.ports import StorageError
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/generations", tags=["generations"])


class CreateGenerationBody(BaseModel):
    workspace_id: UUID
    voice_profile_id: UUID
    project_id: UUID | None = None
    input_text: str = Field(min_length=1, max_length=10_000)
    language_code: str = Field(min_length=2, max_length=10)
    output_format: Literal["wav", "mp3"] = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    style: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int | None = None
    model_key: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return request.app.state.membership_store


def _generation_service(request: Request) -> GenerationService:
    return request.app.state.generation_service


def _generation_worker(request: Request):
    return request.app.state.generation_worker


def _generation_outputs(request: Request) -> PrivateGenerationOutputStore:
    return request.app.state.generation_outputs


async def _claims(request: Request, authorization: str | None = Header(default=None)) -> AuthClaims:
    verifier: JWTVerifier | None = request.app.state.jwt_verifier
    if verifier is None:
        raise APIError(503, "AUTH_NOT_CONFIGURED", "Authentication is not configured for this API.")
    try:
        return require_authenticated(authorization, verifier)
    except JWTVerificationError as error:
        raise APIError(401, error.code, str(error)) from error


async def _authorize_workspace(
    request: Request,
    claims: AuthClaims,
    workspace_id: UUID,
    *,
    minimum_role: Literal["viewer", "editor"],
    scope: str,
) -> None:
    try:
        await require_workspace_access(
            claims,
            workspace_id,
            _membership_store(request),
            minimum_role=minimum_role,
            required_scope=scope,
        )
    except AuthorizationError as error:
        raise APIError(403, error.code, str(error)) from error


async def _authorize_job(
    request: Request,
    claims: AuthClaims,
    job_id: UUID,
    *,
    minimum_role: Literal["viewer", "editor"],
    scope: str,
) -> GenerationJob:
    job = await _generation_service(request).get(job_id)
    if job is None:
        raise APIError(404, "GENERATION_NOT_FOUND", "Generation was not found.")
    await _authorize_workspace(
        request,
        claims,
        job.workspace_id,
        minimum_role=minimum_role,
        scope=scope,
    )
    return job


@router.post("", status_code=202)
async def create_generation(
    body: CreateGenerationBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object]:
    await _authorize_workspace(
        request,
        claims,
        body.workspace_id,
        minimum_role="editor",
        scope="generations:create",
    )
    if idempotency_key is None:
        raise APIError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        job = await _generation_service(request).create(
            workspace_id=body.workspace_id,
            actor_id=claims.subject,
            voice_profile_id=body.voice_profile_id,
            project_id=body.project_id,
            input_text=body.input_text,
            language_code=body.language_code,
            output_format=body.output_format,
            speed=body.speed,
            stability=body.stability,
            style=body.style,
            seed=body.seed,
            model_key=body.model_key,
            model_version=body.model_version,
            checkpoint_sha256=body.checkpoint_sha256,
            idempotency_key=idempotency_key,
        )
    except GenerationError as error:
        status = 409 if error.code == "IDEMPOTENCY_KEY_REUSED" else 400
        raise APIError(status, error.code, str(error)) from error
    job = await _generation_worker(request).publish(job.id, claims.subject)
    return envelope(request, data=job.as_dict())


@router.get("")
async def list_generations(
    request: Request,
    workspace_id: UUID = Query(...),  # noqa: B008
    status: GenerationStatus | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_workspace(
        request,
        claims,
        workspace_id,
        minimum_role="viewer",
        scope="generations:read",
    )
    jobs = await _generation_service(request).list(workspace_id, status=status, limit=limit)
    return envelope(request, data={"items": [job.as_dict(include_text=False) for job in jobs]})


@router.get("/{job_id}/download")
async def download_generation(
    job_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    job = await _authorize_job(
        request,
        claims,
        job_id,
        minimum_role="viewer",
        scope="generations:read",
    )
    if job.status != "succeeded":
        raise APIError(
            409,
            "GENERATION_OUTPUT_NOT_READY",
            "The generation output is not ready for download.",
        )
    output = await _generation_outputs(request).get(job.id)
    if output is None:
        raise APIError(
            409,
            "GENERATION_OUTPUT_NOT_READY",
            "The generation output is not ready for download.",
        )
    try:
        signed = await request.app.state.storage_adapter.create_download_url(
            output.bucket,
            output.object_key,
        )
    except StorageError as error:
        raise APIError(
            503,
            "STORAGE_SIGN_FAILED",
            "A private download URL could not be created.",
        ) from error
    return envelope(
        request,
        data={
            "output": output.as_dict(),
            "download": {
                "url": signed.url,
                "method": signed.method,
                "expires_at": signed.expires_at.isoformat(),
                "headers": dict(signed.headers),
            },
        },
    )


@router.get("/{job_id}")
async def get_generation(
    job_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    job = await _authorize_job(
        request,
        claims,
        job_id,
        minimum_role="viewer",
        scope="generations:read",
    )
    return envelope(request, data=job.as_dict())


@router.post("/{job_id}/cancel")
async def cancel_generation(
    job_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_job(
        request,
        claims,
        job_id,
        minimum_role="editor",
        scope="generations:create",
    )
    try:
        job = await _generation_service(request).cancel(job_id, claims.subject)
    except GenerationError as error:
        status = 404 if error.code == "GENERATION_NOT_FOUND" else 409
        raise APIError(status, error.code, str(error)) from error
    return envelope(request, data=job.as_dict())


@router.post("/{job_id}/retry")
async def retry_generation(
    job_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_job(
        request,
        claims,
        job_id,
        minimum_role="editor",
        scope="generations:create",
    )
    try:
        job = await _generation_service(request).retry(job_id, claims.subject)
        job = await _generation_worker(request).publish(job.id, claims.subject)
    except GenerationError as error:
        status = 404 if error.code == "GENERATION_NOT_FOUND" else 409
        raise APIError(status, error.code, str(error)) from error
    return envelope(request, data=job.as_dict())
