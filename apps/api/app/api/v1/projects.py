"""Workspace-scoped project and saved Studio editor-settings endpoints."""

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
from app.domains.audit.service import AuditService
from app.domains.projects.service import (
    EditorSettings,
    Project,
    ProjectError,
    ProjectService,
)
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/projects", tags=["projects"])


class EditorSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_profile_id: UUID | None = None
    language_code: str = Field(default="en-US", min_length=2, max_length=10)
    output_format: Literal["wav", "mp3"] = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    style: float | None = Field(default=None, ge=0.0, le=1.0)

    def to_domain(self) -> EditorSettings:
        return EditorSettings(
            voice_profile_id=self.voice_profile_id,
            language_code=self.language_code,
            output_format=self.output_format,
            speed=self.speed,
            stability=self.stability,
            style=self.style,
        )


class CreateProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    editor_settings: EditorSettingsBody | None = None


class UpdateProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    archived: bool | None = None
    editor_settings: EditorSettingsBody | None = None


def _membership_store(request: Request) -> WorkspaceMembershipStore:
    return request.app.state.membership_store


def _project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


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


async def _authorize_project(
    request: Request,
    claims: AuthClaims,
    project_id: UUID,
    *,
    minimum_role: Literal["viewer", "editor"],
    scope: str,
) -> Project:
    project = await _project_service(request).get(project_id)
    if project is None:
        raise APIError(404, "PROJECT_NOT_FOUND", "Project was not found.")
    await _authorize_workspace(
        request,
        claims,
        project.workspace_id,
        minimum_role=minimum_role,
        scope=scope,
    )
    return project


@router.post("", status_code=201)
async def create_project(
    body: CreateProjectBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, object]:
    await _authorize_workspace(
        request,
        claims,
        body.workspace_id,
        minimum_role="editor",
        scope="projects:write",
    )
    if idempotency_key is None:
        raise APIError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        project = await _project_service(request).create(
            workspace_id=body.workspace_id,
            actor_id=claims.subject,
            name=body.name,
            description=body.description,
            editor_settings=body.editor_settings.to_domain()
            if body.editor_settings is not None
            else None,
            idempotency_key=idempotency_key,
        )
    except ProjectError as error:
        status = 409 if error.code == "IDEMPOTENCY_KEY_REUSED" else 400
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="project.created",
        resource_type="project",
        workspace_id=project.workspace_id,
        resource_id=project.id,
        actor=claims,
        metadata={"has_description": body.description is not None},
    )
    return envelope(request, data=project.as_dict())


@router.get("")
async def list_projects(
    request: Request,
    workspace_id: UUID = Query(...),  # noqa: B008
    include_archived: bool = Query(default=False),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_workspace(
        request,
        claims,
        workspace_id,
        minimum_role="viewer",
        scope="projects:read",
    )
    try:
        projects = await _project_service(request).list(
            workspace_id,
            include_archived=include_archived,
            limit=limit,
        )
    except ProjectError as error:
        raise APIError(400, error.code, str(error)) from error
    return envelope(request, data={"items": [project.as_dict() for project in projects]})


@router.get("/{project_id}/editor-settings")
async def get_editor_settings(
    project_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    project = await _authorize_project(
        request,
        claims,
        project_id,
        minimum_role="viewer",
        scope="projects:read",
    )
    return envelope(
        request,
        data={
            "project_id": str(project.id),
            "settings": project.editor_settings.as_dict(),
            "saved_at": project.updated_at.isoformat(),
        },
    )


@router.put("/{project_id}/editor-settings")
async def save_editor_settings(
    project_id: UUID,
    body: EditorSettingsBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_project(
        request,
        claims,
        project_id,
        minimum_role="editor",
        scope="projects:write",
    )
    try:
        project = await _project_service(request).save_editor_settings(
            project_id,
            claims.subject,
            body.to_domain(),
        )
    except ProjectError as error:
        status = 404 if error.code == "PROJECT_NOT_FOUND" else 400
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="project.editor_settings.updated",
        resource_type="project",
        workspace_id=project.workspace_id,
        resource_id=project.id,
        actor=claims,
        metadata={"output_format": body.output_format, "language_code": body.language_code},
    )
    return envelope(
        request,
        data={
            "project_id": str(project.id),
            "settings": project.editor_settings.as_dict(),
            "saved_at": project.updated_at.isoformat(),
        },
    )


@router.get("/{project_id}")
async def get_project(
    project_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    project = await _authorize_project(
        request,
        claims,
        project_id,
        minimum_role="viewer",
        scope="projects:read",
    )
    return envelope(request, data=project.as_dict())


@router.patch("/{project_id}")
async def update_project(
    project_id: UUID,
    body: UpdateProjectBody,
    request: Request,
    claims: AuthClaims = Depends(_claims),  # noqa: B008
) -> dict[str, object]:
    await _authorize_project(
        request,
        claims,
        project_id,
        minimum_role="editor",
        scope="projects:write",
    )
    try:
        project = await _project_service(request).update(
            project_id,
            claims.subject,
            name=body.name,
            description=body.description,
            description_provided="description" in body.model_fields_set,
            archived=body.archived,
            editor_settings=(
                body.editor_settings.to_domain()
                if body.editor_settings is not None
                else EditorSettings()
                if "editor_settings" in body.model_fields_set
                else None
            ),
        )
    except ProjectError as error:
        status = 404 if error.code == "PROJECT_NOT_FOUND" else 400
        raise APIError(status, error.code, str(error)) from error
    await _audit(request).emit_request(
        request,
        action="project.updated",
        resource_type="project",
        workspace_id=project.workspace_id,
        resource_id=project.id,
        actor=claims,
        metadata={"fields": sorted(body.model_fields_set)},
    )
    return envelope(request, data=project.as_dict())


def configure_project_state(app: FastAPI) -> None:
    """Install the local project store; production replaces it with SQL."""

    from app.domains.projects.service import InMemoryProjectStore  # noqa: PLC0415

    app.state.project_store = InMemoryProjectStore()
    app.state.project_service = ProjectService(app.state.project_store, app.state.voice_service)
