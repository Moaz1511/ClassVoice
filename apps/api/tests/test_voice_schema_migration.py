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


async def test_voice_schema_rejects_invalid_constraints(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace_slug = f"voice-{str(user_id).replace('-', '')[:12]}"
    model_id = None
    asset_id = None
    voice_id = None
    workspace = None

    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic Voice Tester"}',
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic Voice Workspace",
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
            VALUES ($1, $2, $3, $4, $5, $6, true)
            RETURNING id
            """,
            "synthetic-model",
            "0.0.1",
            "a" * 64,
            "cpu",
            "Synthetic test license",
            "approved",
        )
        asset_id = await database.fetchval(
            """
            INSERT INTO public.audio_assets (
                workspace_id, owner_id, kind, object_key, mime_type,
                byte_size, duration_ms, sample_rate_hz, channels,
                sha256, storage_bucket
            )
            VALUES ($1, $2, 'voice_reference', $3, 'audio/wav',
                    1024, 6000, 24000, 1, $4, 'voice-inputs')
            RETURNING id
            """,
            workspace["id"],
            user_id,
            f"synthetic/{user_id}/reference.wav",
            "b" * 64,
        )
        voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id,
                reference_duration_ms
            )
            VALUES ($1, $2, 'Synthetic Voice', $3, 6000)
            RETURNING id
            """,
            workspace["id"],
            user_id,
            model_id,
        )
        await database.execute(
            """
            INSERT INTO public.voice_consent_records (
                voice_profile_id, workspace_id, subject_user_id,
                consent_statement_version, attestation_text_hash,
                evidence_asset_id
            )
            VALUES ($1, $2, $3, 'consent-v1', $4, $5)
            """,
            voice_id,
            workspace["id"],
            user_id,
            "c" * 64,
            asset_id,
        )
        await database.execute(
            """
            INSERT INTO public.voice_samples (
                voice_profile_id, audio_asset_id, speaker_count,
                silence_ratio, clipping_ratio
            )
            VALUES ($1, $2, 1, 0.1, 0.01)
            """,
            voice_id,
            asset_id,
        )

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                INSERT INTO public.voice_profiles (
                    workspace_id, created_by, name, reference_duration_ms
                )
                VALUES ($1, $2, 'Invalid duration', 5999)
                """,
                workspace["id"],
                user_id,
            )

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                INSERT INTO public.model_versions (
                    model_key, version, checkpoint_sha256, runtime,
                    license_name, license_review_status
                )
                VALUES ('invalid-hash', '0.0.1', 'bad', 'cpu', 'test', 'approved')
                """
            )

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                INSERT INTO public.audio_assets (
                    workspace_id, owner_id, kind, object_key, mime_type,
                    byte_size, sha256, storage_bucket
                )
                VALUES ($1, $2, 'voice_reference', $3, 'audio/wav',
                        1024, 'bad', 'voice-inputs')
                """,
                workspace["id"],
                user_id,
                f"synthetic/{user_id}/invalid.wav",
            )

        with pytest.raises(asyncpg.InvalidTextRepresentationError):
            await database.execute(
                """
                INSERT INTO public.voice_profiles (
                    workspace_id, created_by, name, status
                )
                VALUES ($1, $2, 'Invalid status', 'not-a-status')
                """,
                workspace["id"],
                user_id,
            )

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await database.execute(
                """
                INSERT INTO public.voice_samples (voice_profile_id, audio_asset_id)
                VALUES ($1, $2)
                """,
                voice_id,
                uuid4(),
            )
    finally:
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        if model_id is not None:
            await database.execute("DELETE FROM public.model_versions WHERE id = $1", model_id)
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
