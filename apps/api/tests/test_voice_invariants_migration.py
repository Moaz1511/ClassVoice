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


async def test_voice_readiness_and_consent_revocation_invariants(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace_slug = f"invariants-{str(user_id).replace('-', '')[:12]}"
    workspace = None
    approved_model_id = None
    pending_model_id = None
    asset_id = None
    pending_voice_id = None
    voice_id = None

    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic Invariant Tester"}',
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic Invariant Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )
        assert workspace is not None

        approved_model_id = await database.fetchval(
            """
            INSERT INTO public.model_versions (
                model_key, version, checkpoint_sha256, runtime,
                license_name, license_review_status, enabled
            )
            VALUES ('synthetic-invariant-model', '0.0.1', $1,
                    'cpu', 'Synthetic test license', 'approved', true)
            RETURNING id
            """,
            "a" * 64,
        )
        pending_model_id = await database.fetchval(
            """
            INSERT INTO public.model_versions (
                model_key, version, checkpoint_sha256, runtime,
                license_name, license_review_status, enabled
            )
            VALUES ('synthetic-invariant-model', '0.0.2', $1,
                    'cpu', 'Synthetic test license', 'pending', false)
            RETURNING id
            """,
            "b" * 64,
        )
        asset_id = await database.fetchval(
            """
            INSERT INTO public.audio_assets (
                workspace_id, owner_id, kind, status, object_key,
                mime_type, byte_size, duration_ms, sample_rate_hz,
                channels, sha256, storage_bucket
            )
            VALUES ($1, $2, 'voice_reference', 'available', $3, 'audio/wav',
                    1024, 6000, 24000, 1, $4, 'voice-inputs')
            RETURNING id
            """,
            workspace["id"],
            user_id,
            f"synthetic/{user_id}/invariant-reference.wav",
            "c" * 64,
        )
        pending_voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id
            )
            VALUES ($1, $2, 'Pending Model Voice', $3)
            RETURNING id
            """,
            workspace["id"],
            user_id,
            pending_model_id,
        )
        with pytest.raises(asyncpg.PostgresError):
            async with database.transaction():
                await database.execute(
                    "UPDATE public.voice_profiles SET status = 'ready' WHERE id = $1",
                    pending_voice_id,
                )

        voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (
                workspace_id, created_by, name, active_model_version_id
            )
            VALUES ($1, $2, 'Consent Controlled Voice', $3)
            RETURNING id
            """,
            workspace["id"],
            user_id,
            approved_model_id,
        )
        await database.execute(
            """
            INSERT INTO public.voice_samples (
                voice_profile_id, audio_asset_id, is_primary
            )
            VALUES ($1, $2, true)
            """,
            voice_id,
            asset_id,
        )
        with pytest.raises(asyncpg.PostgresError):
            async with database.transaction():
                await database.execute(
                    "UPDATE public.voice_profiles SET status = 'ready' WHERE id = $1",
                voice_id,
            )

        statement_hash = await database.fetchval(
            """
            SELECT statement_text_hash
            FROM public.consent_statements
            WHERE version = 'consent-v1'
            """
        )
        consent_id = await database.fetchval(
            """
            INSERT INTO public.voice_consent_records (
                voice_profile_id, workspace_id, subject_user_id,
                consent_statement_version, attestation_text_hash,
                evidence_asset_id
            )
            VALUES ($1, $2, $3, 'consent-v1', $4, $5)
            RETURNING id
            """,
            voice_id,
            workspace["id"],
            user_id,
            statement_hash,
            asset_id,
        )
        await database.execute(
            "UPDATE public.voice_profiles SET status = 'ready' WHERE id = $1",
            voice_id,
        )
        assert await database.fetchval(
            "SELECT status::text FROM public.voice_profiles WHERE id = $1", voice_id
        ) == "ready"

        await database.execute(
            """
            UPDATE public.voice_consent_records
            SET status = 'revoked', revoked_at = now()
            WHERE id = $1
            """,
            consent_id,
        )
        revoked_state = await database.fetchrow(
            """
            SELECT status::text, consent_status::text, revoked_at
            FROM public.voice_profiles
            WHERE id = $1
            """,
            voice_id,
        )
        assert revoked_state is not None
        assert revoked_state["status"] == "revoked"
        assert revoked_state["consent_status"] == "revoked"
        assert revoked_state["revoked_at"] is not None

        with pytest.raises(asyncpg.PostgresError):
            async with database.transaction():
                await database.execute(
                    """
                    INSERT INTO public.generation_jobs (
                        workspace_id, voice_profile_id, requested_by,
                        input_text, input_text_sha256, language_code,
                        model_version_id, idempotency_key
                    )
                    VALUES ($1, $2, $3, 'Blocked after revocation', $4,
                            'en-US', $5, $6)
                    """,
                    workspace["id"],
                    voice_id,
                    user_id,
                    "e" * 64,
                    approved_model_id,
                    f"revoked-{user_id}",
                )
    finally:
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        if approved_model_id is not None:
            await database.execute(
                "DELETE FROM public.model_versions WHERE id = $1", approved_model_id
            )
        if pending_model_id is not None:
            await database.execute(
                "DELETE FROM public.model_versions WHERE id = $1", pending_model_id
            )
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
