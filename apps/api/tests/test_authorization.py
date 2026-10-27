from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.authorization import (
    AuthorizationError,
    InMemoryMembershipStore,
    WorkspaceMembership,
    require_scope,
    require_workspace_access,
    require_workspace_role,
)
from app.core.jwt import AuthClaims

pytestmark = pytest.mark.asyncio


def make_claims(user_id: object, scopes: frozenset[str]) -> AuthClaims:
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    return AuthClaims(
        subject=user_id,
        issuer="https://project.supabase.co/auth/v1",
        audience=("authenticated",),
        role="authenticated",
        scopes=scopes,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


async def test_workspace_membership_role_and_scope_dependencies() -> None:
    user_id = uuid4()
    workspace_id = uuid4()
    membership = WorkspaceMembership(workspace_id, user_id, "editor")
    claims = make_claims(user_id, frozenset({"generations:create"}))
    store = InMemoryMembershipStore((membership,))

    authorized = await require_workspace_access(
        claims,
        str(workspace_id),
        store,
        minimum_role="editor",
        required_scope="generations:create",
    )

    assert authorized == membership
    require_scope(claims, "generations:create")
    require_workspace_role(membership, "viewer")


async def test_workspace_dependencies_deny_cross_workspace_missing_scope_and_disabled() -> None:
    user_id = uuid4()
    workspace_id = uuid4()
    claims = make_claims(user_id, frozenset())
    store = InMemoryMembershipStore(
        (WorkspaceMembership(workspace_id, user_id, "viewer"),)
    )

    with pytest.raises(AuthorizationError) as missing_scope:
        await require_workspace_access(
            claims,
            workspace_id,
            store,
            required_scope="voices:read",
        )
    assert missing_scope.value.code == "ACCESS_SCOPE_MISSING"

    with pytest.raises(AuthorizationError) as missing_membership:
        await require_workspace_access(claims, uuid4(), store)
    assert missing_membership.value.code == "ACCESS_WORKSPACE_FORBIDDEN"

    disabled_store = InMemoryMembershipStore(
        (WorkspaceMembership(workspace_id, user_id, "viewer", workspace_disabled=True),)
    )
    with pytest.raises(AuthorizationError) as disabled:
        await require_workspace_access(claims, workspace_id, disabled_store)
    assert disabled.value.code == "ACCESS_WORKSPACE_DISABLED"


async def test_role_dependency_rejects_viewer_write_and_invalid_workspace_id() -> None:
    user_id = uuid4()
    workspace_id = uuid4()
    claims = make_claims(user_id, frozenset({"voices:read"}))
    store = InMemoryMembershipStore((WorkspaceMembership(workspace_id, user_id, "viewer"),))

    with pytest.raises(AuthorizationError) as role_error:
        await require_workspace_access(claims, workspace_id, store, minimum_role="editor")
    assert role_error.value.code == "ACCESS_ROLE_INSUFFICIENT"

    with pytest.raises(AuthorizationError) as invalid_id:
        await require_workspace_access(claims, "not-a-uuid", store)
    assert invalid_id.value.code == "ACCESS_WORKSPACE_INVALID"
