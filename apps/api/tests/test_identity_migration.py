from __future__ import annotations

import os
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def database() -> asyncpg.Connection:
    database_url = os.getenv("CLASSVOICE_INTEGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip("CLASSVOICE_INTEGRATION_DATABASE_URL is not set")

    connection = await asyncpg.connect(database_url)
    try:
        yield connection
    finally:
        await connection.close()


async def test_personal_workspace_onboarding_is_idempotent(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace_slug = f"synthetic-{str(user_id).replace('-', '')[:12]}"

    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic CI User"}',
        )

        first = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic CI Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )
        second = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic CI Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )

        assert first is not None
        assert second is not None
        assert first["id"] == second["id"]
        assert await database.fetchval(
            "SELECT count(*) FROM public.workspaces WHERE owner_id = $1",
            user_id,
        ) == 1
        assert await database.fetchval(
            """
            SELECT role::text
            FROM public.workspace_members
            WHERE user_id = $1 AND workspace_id = $2
            """,
            user_id,
            first["id"],
        ) == "owner"
    finally:
        await database.execute("DELETE FROM public.workspaces WHERE owner_id = $1", user_id)
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
