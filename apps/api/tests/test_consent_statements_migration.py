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


async def test_consent_statement_hash_actor_and_acceptance_audit(
    database: asyncpg.Connection,
) -> None:
    subject_id = uuid4()
    actor_id = uuid4()
    workspace_slug = f"consent-{str(subject_id).replace('-', '')[:12]}"
    workspace = None
    voice_id = None
    consent_id = None

    try:
        await database.executemany(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            [
                (subject_id, '{"display_name":"Synthetic Consent Subject"}'),
                (actor_id, '{"display_name":"Synthetic Consent Actor"}'),
            ],
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            subject_id,
            "Synthetic Consent Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )
        assert workspace is not None
        await database.execute(
            """
            INSERT INTO public.workspace_members (workspace_id, user_id, role, invited_by)
            VALUES ($1, $2, 'admin', $3)
            """,
            workspace["id"],
            actor_id,
            subject_id,
        )
        voice_id = await database.fetchval(
            """
            INSERT INTO public.voice_profiles (workspace_id, created_by, name)
            VALUES ($1, $2, 'Synthetic Consent Voice')
            RETURNING id
            """,
            workspace["id"],
            subject_id,
        )
        statement = await database.fetchrow(
            """
            SELECT version, statement_text, statement_text_hash
            FROM public.consent_statements
            WHERE version = 'consent-v1'
            """
        )
        assert statement is not None
        assert len(statement["statement_text_hash"]) == 64

        consent_id = await database.fetchval(
            """
            INSERT INTO public.voice_consent_records (
                voice_profile_id, workspace_id, subject_user_id,
                accepted_by_user_id, consent_statement_version,
                attestation_text_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            voice_id,
            workspace["id"],
            subject_id,
            actor_id,
            statement["version"],
            statement["statement_text_hash"],
        )
        stored = await database.fetchrow(
            """
            SELECT accepted_by_user_id, accepted_at, attestation_text_hash
            FROM public.voice_consent_records
            WHERE id = $1
            """,
            consent_id,
        )
        assert stored is not None
        assert stored["accepted_by_user_id"] == actor_id
        assert stored["accepted_at"] is not None
        assert stored["attestation_text_hash"] == statement["statement_text_hash"]

        audit = await database.fetchrow(
            """
            SELECT actor_type::text, actor_user_id, action, resource_type, resource_id,
                   metadata->>'statement_version' AS statement_version,
                   metadata->>'statement_text_hash' AS statement_text_hash
            FROM public.audit_events
            WHERE resource_id = $1 AND action = 'consent.accepted'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            consent_id,
        )
        assert audit is not None
        assert audit["actor_type"] == "user"
        assert audit["actor_user_id"] == actor_id
        assert audit["resource_type"] == "voice_consent_record"
        assert audit["statement_version"] == "consent-v1"
        assert audit["statement_text_hash"] == statement["statement_text_hash"]

        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                INSERT INTO public.voice_consent_records (
                    voice_profile_id, workspace_id, subject_user_id,
                    accepted_by_user_id, consent_statement_version,
                    attestation_text_hash
                )
                VALUES ($1, $2, $3, $4, 'consent-v1', $5)
                """,
                voice_id,
                workspace["id"],
                subject_id,
                actor_id,
                "0" * 64,
            )

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await database.execute(
                """
                INSERT INTO public.voice_consent_records (
                    voice_profile_id, workspace_id, subject_user_id,
                    accepted_by_user_id, consent_statement_version,
                    attestation_text_hash
                )
                VALUES ($1, $2, $3, $4, 'missing-v99', $5)
                """,
                voice_id,
                workspace["id"],
                subject_id,
                actor_id,
                statement["statement_text_hash"],
            )

        await database.execute(
            """
            UPDATE public.voice_consent_records
            SET status = 'revoked'
            WHERE id = $1
            """,
            consent_id,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await database.execute(
                """
                UPDATE public.voice_consent_records
                SET status = 'accepted'
                WHERE id = $1
                """,
                consent_id,
            )
    finally:
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        await database.execute("DELETE FROM public.profiles WHERE id = $1", subject_id)
        await database.execute("DELETE FROM public.profiles WHERE id = $1", actor_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", subject_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", actor_id)
