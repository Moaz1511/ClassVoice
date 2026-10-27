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


async def test_rls_blocks_cross_workspace_and_unauthorized_writes(
    database: asyncpg.Connection,
) -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    owner_slug = f"rls-owner-{str(owner_id).replace('-', '')[:10]}"
    viewer_slug = f"rls-viewer-{str(viewer_id).replace('-', '')[:10]}"
    owner_workspace = None
    viewer_workspace = None
    enabled_model_id = None
    disabled_model_id = None

    try:
        await database.executemany(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            [
                (owner_id, '{"display_name":"Synthetic RLS Owner"}'),
                (viewer_id, '{"display_name":"Synthetic RLS Viewer"}'),
            ],
        )
        owner_workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            owner_id,
            "Synthetic RLS Owner Workspace",
            owner_slug,
            "terms-v1",
            "safety-v1",
        )
        viewer_workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            viewer_id,
            "Synthetic RLS Viewer Workspace",
            viewer_slug,
            "terms-v1",
            "safety-v1",
        )
        assert owner_workspace is not None
        assert viewer_workspace is not None

        await database.execute(
            """
            UPDATE public.workspace_members
            SET role = 'viewer'
            WHERE workspace_id = $1 AND user_id = $2
            """,
            viewer_workspace["id"],
            viewer_id,
        )
        enabled_model_id = await database.fetchval(
            """
            INSERT INTO public.model_versions (
                model_key, version, checkpoint_sha256, runtime,
                license_name, license_review_status, enabled
            )
            VALUES ('synthetic-rls-model', '0.0.1', $1,
                    'cpu', 'Synthetic test license', 'approved', true)
            RETURNING id
            """,
            "a" * 64,
        )
        disabled_model_id = await database.fetchval(
            """
            INSERT INTO public.model_versions (
                model_key, version, checkpoint_sha256, runtime,
                license_name, license_review_status, enabled
            )
            VALUES ('synthetic-rls-model', '0.0.2', $1,
                    'cpu', 'Synthetic test license', 'pending', false)
            RETURNING id
            """,
            "b" * 64,
        )
        await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id
            )
            VALUES ($1, $2, 'Owner Voice', $3)
            RETURNING id
            """,
            owner_workspace["id"],
            owner_id,
            enabled_model_id,
        )
        revoked_voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, status, active_model_version_id
            )
            VALUES ($1, $2, 'Revoked Voice', 'revoked', $3)
            RETURNING id
            """,
            owner_workspace["id"],
            owner_id,
            enabled_model_id,
        )
        await database.execute(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id
            )
            VALUES ($1, $2, 'Viewer Workspace Voice', $3)
            """,
            viewer_workspace["id"],
            viewer_id,
            enabled_model_id,
        )

        async with database.transaction():
            await database.execute("SET LOCAL ROLE authenticated")
            await database.fetchval(
                "SELECT set_config('request.jwt.claim.sub', $1, true)",
                str(owner_id),
            )
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM public.voice_profiles WHERE workspace_id = $1",
                    owner_workspace["id"],
                )
                == 2
            )
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM public.model_versions"
                )
                == 1
            )
            with pytest.raises(asyncpg.PostgresError):
                async with database.transaction():
                    await database.execute(
                        """
                        INSERT INTO public.generation_jobs (
                            workspace_id, voice_profile_id, requested_by,
                            input_text, input_text_sha256, language_code,
                            model_version_id, idempotency_key
                        )
                        VALUES ($1, $2, $3, 'Revoked voice request', $4,
                                'en-US', $5, $6)
                        """,
                        owner_workspace["id"],
                        revoked_voice_id,
                        owner_id,
                        "c" * 64,
                        enabled_model_id,
                        f"revoked-{owner_id}",
                    )

            await database.execute("SET LOCAL ROLE anon")
            await database.fetchval(
                "SELECT set_config('request.jwt.claim.sub', $1, true)",
                str(owner_id),
            )
            assert await database.fetchval("SELECT count(*) FROM public.voice_profiles") == 0

            await database.execute("SET LOCAL ROLE authenticated")
            await database.fetchval(
                "SELECT set_config('request.jwt.claim.sub', $1, true)",
                str(viewer_id),
            )
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM public.voice_profiles WHERE workspace_id = $1",
                    viewer_workspace["id"],
                )
                == 1
            )
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM public.voice_profiles WHERE workspace_id = $1",
                    owner_workspace["id"],
                )
                == 0
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with database.transaction():
                    await database.execute(
                        """
                        INSERT INTO public.projects (workspace_id, created_by, name)
                        VALUES ($1, $2, 'Viewer must not write')
                        """,
                        viewer_workspace["id"],
                        viewer_id,
                    )
    finally:
        if owner_workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", owner_workspace["id"]
            )
        if viewer_workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", viewer_workspace["id"]
            )
        if enabled_model_id is not None:
            await database.execute(
                "DELETE FROM public.model_versions WHERE id = $1", enabled_model_id
            )
        if disabled_model_id is not None:
            await database.execute(
                "DELETE FROM public.model_versions WHERE id = $1", disabled_model_id
            )
        await database.execute("DELETE FROM public.profiles WHERE id = $1", owner_id)
        await database.execute("DELETE FROM public.profiles WHERE id = $1", viewer_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", owner_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", viewer_id)
