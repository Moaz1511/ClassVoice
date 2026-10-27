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


async def test_generation_idempotency_returns_one_durable_job(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace_slug = f"generation-{str(user_id).replace('-', '')[:12]}"
    workspace = None
    model_id = None
    asset_id = None
    voice_id = None
    project_id = None
    job_id = None

    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic Generation Tester"}',
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic Generation Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )
        assert workspace is not None

        model_id = await database.fetchval(
            """
            INSERT INTO public.model_versions (
                model_key, version, checkpoint_sha256, runtime,
                license_name, license_review_status, enabled
            )
            VALUES ('synthetic-generation-model', '0.0.1', $1,
                    'cpu', 'Synthetic test license', 'approved', true)
            RETURNING id
            """,
            "a" * 64,
        )
        asset_id = await database.fetchval(
            """
            INSERT INTO public.audio_assets (
                workspace_id, owner_id, kind, object_key, mime_type,
                byte_size, duration_ms, sample_rate_hz, channels,
                sha256, storage_bucket, status
            )
            VALUES ($1, $2, 'generated_audio', $3, 'audio/wav',
                    1024, 1000, 24000, 1, $4, 'voice-outputs', 'available')
            RETURNING id
            """,
            workspace["id"],
            user_id,
            f"synthetic/{user_id}/output.wav",
            "b" * 64,
        )
        voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id,
                reference_duration_ms
            )
            VALUES ($1, $2, 'Synthetic Generation Voice', $3, 6000)
            RETURNING id
            """,
            workspace["id"],
            user_id,
            model_id,
        )
        project_id = await database.fetchval(
            """
            INSERT INTO public.projects (workspace_id, created_by, name)
            VALUES ($1, $2, 'Synthetic Project')
            RETURNING id
            """,
            workspace["id"],
            user_id,
        )

        idempotency_key = f"synthetic-{user_id}"
        job_id = await database.fetchval(
            """
            INSERT INTO public.generation_jobs (
                workspace_id, project_id, voice_profile_id, requested_by,
                input_text, input_text_sha256, language_code,
                model_version_id, idempotency_key
            )
            VALUES ($1, $2, $3, $4, 'Hello from ClassVoice', $5,
                    'en-US', $6, $7)
            ON CONFLICT (workspace_id, idempotency_key)
            DO UPDATE SET id = public.generation_jobs.id
            RETURNING id
            """,
            workspace["id"],
            project_id,
            voice_id,
            user_id,
            "c" * 64,
            model_id,
            idempotency_key,
        )
        duplicate_id = await database.fetchval(
            """
            INSERT INTO public.generation_jobs (
                workspace_id, project_id, voice_profile_id, requested_by,
                input_text, input_text_sha256, language_code,
                model_version_id, idempotency_key
            )
            VALUES ($1, $2, $3, $4, 'Different retry payload', $5,
                    'en-US', $6, $7)
            ON CONFLICT (workspace_id, idempotency_key)
            DO UPDATE SET id = public.generation_jobs.id
            RETURNING id
            """,
            workspace["id"],
            project_id,
            voice_id,
            user_id,
            "d" * 64,
            model_id,
            idempotency_key,
        )

        assert duplicate_id == job_id
        assert (
            await database.fetchval(
                """
                SELECT count(*)
                FROM public.generation_jobs
                WHERE workspace_id = $1 AND idempotency_key = $2
                """,
                workspace["id"],
                idempotency_key,
            )
            == 1
        )

        output_id = await database.fetchval(
            """
            INSERT INTO public.generation_outputs (
                generation_job_id, audio_asset_id, output_format,
                duration_ms, checksum_sha256
            )
            VALUES ($1, $2, 'wav', 1000, $3)
            RETURNING id
            """,
            job_id,
            asset_id,
            "e" * 64,
        )
        assert output_id is not None

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                INSERT INTO public.generation_jobs (
                    workspace_id, voice_profile_id, requested_by,
                    input_text, input_text_sha256, language_code,
                    model_version_id, idempotency_key, speed
                )
                VALUES ($1, $2, $3, 'Invalid speed', $4, 'en-US', $5, $6, 2.01)
                """,
                workspace["id"],
                voice_id,
                user_id,
                "f" * 64,
                model_id,
                f"invalid-speed-{user_id}",
            )
    finally:
        if job_id is not None:
            await database.execute(
                "DELETE FROM public.generation_outputs WHERE generation_job_id = $1",
                job_id,
            )
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        if model_id is not None:
            await database.execute("DELETE FROM public.model_versions WHERE id = $1", model_id)
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
