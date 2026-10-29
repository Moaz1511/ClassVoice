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


async def test_projects_store_editor_settings_as_json_object(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace = None
    project_id = None
    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic Project Tester"}',
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic Project Workspace",
            f"project-{str(user_id).replace('-', '')[:12]}",
            "terms-v1",
            "safety-v1",
        )
        assert workspace is not None

        project_id = await database.fetchval(
            """
            INSERT INTO public.projects (workspace_id, created_by, name)
            VALUES ($1, $2, 'Synthetic Project')
            RETURNING id
            """,
            workspace["id"],
            user_id,
        )
        assert await database.fetchval(
            "SELECT editor_settings FROM public.projects WHERE id = $1",
            project_id,
        ) == {}

        await database.execute(
            """
            UPDATE public.projects
            SET editor_settings = '{"output_format":"mp3","speed":1.2}'::jsonb
            WHERE id = $1
            """,
            project_id,
        )
        stored = await database.fetchval(
            "SELECT editor_settings->>'output_format' FROM public.projects WHERE id = $1",
            project_id,
        )
        assert stored == "mp3"

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                UPDATE public.projects
                SET editor_settings = '[]'::jsonb
                WHERE id = $1
                """,
                project_id,
            )
    finally:
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
