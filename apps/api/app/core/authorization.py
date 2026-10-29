"""HTTP-agnostic identity, workspace membership, role, and scope dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from .jwt import AuthClaims, JWTVerificationError, JWTVerifier

WorkspaceRole = Literal["owner", "admin", "editor", "viewer"]
_ROLE_RANK: dict[WorkspaceRole, int] = {"viewer": 10, "editor": 20, "admin": 30, "owner": 40}


class AuthorizationError(RuntimeError):
    """A user-safe authorization failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkspaceMembership:
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceRole
    workspace_disabled: bool = False


class WorkspaceMembershipStore(Protocol):
    async def get_membership(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None: ...


class AuthenticatedPrincipal(Protocol):
    """Identity fields shared by verified JWTs and scoped API keys."""

    @property
    def subject(self) -> UUID: ...

    @property
    def scopes(self) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Request identity after either JWT or API-key authentication."""

    subject: UUID
    scopes: frozenset[str]
    workspace_id: UUID | None = None
    api_key_id: UUID | None = None
    profile_role: str | None = None


def extract_bearer_token(authorization_header: str | None) -> str:
    if authorization_header is None:
        raise JWTVerificationError("AUTH_TOKEN_MISSING", "Authentication is required.")
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise JWTVerificationError("AUTH_TOKEN_INVALID", "Use an Authorization Bearer token.")
    return parts[1]


def require_authenticated(
    authorization_header: str | None,
    verifier: JWTVerifier,
) -> AuthClaims:
    return verifier.verify(extract_bearer_token(authorization_header))


def require_scope(claims: AuthenticatedPrincipal, scope: str) -> None:
    normalized_scope = scope.strip()
    if not normalized_scope:
        raise AuthorizationError("ACCESS_SCOPE_INVALID", "Required scope is not configured.")
    if normalized_scope not in claims.scopes:
        raise AuthorizationError("ACCESS_SCOPE_MISSING", "The token does not grant this scope.")


def require_moderator(claims: AuthenticatedPrincipal) -> None:
    if getattr(claims, "profile_role", None) != "moderator":
        raise AuthorizationError("ACCESS_MODERATOR_REQUIRED", "Moderator access is required.")


def require_workspace_role(
    membership: WorkspaceMembership,
    minimum_role: WorkspaceRole,
) -> None:
    if _ROLE_RANK[membership.role] < _ROLE_RANK[minimum_role]:
        raise AuthorizationError("ACCESS_ROLE_INSUFFICIENT", "Workspace role is insufficient.")


async def require_workspace_access(
    claims: AuthenticatedPrincipal,
    workspace_id: UUID | str,
    membership_store: WorkspaceMembershipStore,
    minimum_role: WorkspaceRole = "viewer",
    required_scope: str | None = None,
) -> WorkspaceMembership:
    try:
        requested_workspace = UUID(str(workspace_id))
    except ValueError as error:
        raise AuthorizationError("ACCESS_WORKSPACE_INVALID", "Workspace ID is invalid.") from error
    if required_scope is not None:
        require_scope(claims, required_scope)
    membership = await membership_store.get_membership(claims.subject, requested_workspace)
    if membership is None or membership.user_id != claims.subject:
        raise AuthorizationError("ACCESS_WORKSPACE_FORBIDDEN", "Workspace access is not permitted.")
    if membership.workspace_id != requested_workspace:
        raise AuthorizationError("ACCESS_WORKSPACE_FORBIDDEN", "Workspace access is not permitted.")
    if membership.workspace_disabled:
        raise AuthorizationError("ACCESS_WORKSPACE_DISABLED", "This workspace is disabled.")
    require_workspace_role(membership, minimum_role)
    return membership


class InMemoryMembershipStore:
    """Small deterministic store used by unit tests before the DB repository exists."""

    def __init__(self, memberships: tuple[WorkspaceMembership, ...] = ()) -> None:
        self._memberships = {(item.user_id, item.workspace_id): item for item in memberships}

    async def get_membership(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None:
        return self._memberships.get((user_id, workspace_id))
