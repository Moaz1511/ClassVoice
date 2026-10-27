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


async def test_integrations_store_only_secret_material_and_audit_is_append_only(
    database: asyncpg.Connection,
) -> None:
    user_id = uuid4()
    workspace_slug = f"integrations-{str(user_id).replace('-', '')[:12]}"
    workspace = None
    api_key_id = None
    webhook_id = None

    try:
        await database.execute(
            """
            INSERT INTO auth.users (id, raw_user_meta_data)
            VALUES ($1, $2::jsonb)
            """,
            user_id,
            '{"display_name":"Synthetic Integrations Tester"}',
        )
        workspace = await database.fetchrow(
            """
            SELECT * FROM public.create_personal_workspace(
                $1, $2, $3, $4, $5
            )
            """,
            user_id,
            "Synthetic Integrations Workspace",
            workspace_slug,
            "terms-v1",
            "safety-v1",
        )
        assert workspace is not None

        api_key_id = await database.fetchval(
            """
            INSERT INTO public.api_keys (
                workspace_id, created_by, name, key_prefix, key_hash, scopes
            )
            VALUES ($1, $2, 'Synthetic key', 'cv_test', $3, ARRAY['generation:write'])
            RETURNING id
            """,
            workspace["id"],
            user_id,
            "a" * 64,
        )
        webhook_id = await database.fetchval(
            """
            INSERT INTO public.webhook_endpoints (
                workspace_id, created_by, url, secret_hash, secret_prefix, events
            )
            VALUES ($1, $2, 'https://example.invalid/classvoice', $3, 'wh_test',
                    ARRAY['generation.succeeded'])
            RETURNING id
            """,
            workspace["id"],
            user_id,
            "b" * 64,
        )
        await database.execute(
            """
            INSERT INTO public.webhook_deliveries (
                webhook_endpoint_id, event_type, event_id, payload
            )
            VALUES ($1, 'generation.succeeded', $2, '{"synthetic":true}'::jsonb)
            """,
            webhook_id,
            uuid4(),
        )
        await database.execute(
            """
            INSERT INTO public.usage_events (
                workspace_id, user_id, api_key_id, event_type, units
            )
            VALUES ($1, $2, $3, 'characters.generated', 21.000)
            """,
            workspace["id"],
            user_id,
            api_key_id,
        )
        await database.execute(
            """
            INSERT INTO public.moderation_flags (
                workspace_id, reporter_user_id, resource_type, resource_id,
                reason_code, description
            )
            VALUES ($1, $2, 'voice_profile', $3, 'synthetic_test', 'test only')
            """,
            workspace["id"],
            user_id,
            uuid4(),
        )
        await database.execute(
            """
            INSERT INTO public.data_exports (workspace_id, requested_by)
            VALUES ($1, $2)
            """,
            workspace["id"],
            user_id,
        )

        columns = await database.fetch(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('api_keys', 'webhook_endpoints')
            """
        )
        column_names = {row["column_name"] for row in columns}
        assert {"key_prefix", "key_hash", "secret_prefix", "secret_hash"} <= column_names
        assert "key_secret" not in column_names
        assert "secret" not in column_names

        class _RollbackAuditProbe(Exception):
            pass

        try:
            async with database.transaction():
                audit_id = await database.fetchval(
                    """
                    INSERT INTO public.audit_events (
                        workspace_id, actor_type, actor_user_id,
                        action, resource_type, resource_id
                    )
                    VALUES ($1, 'user', $2, 'synthetic.test', 'api_key', $3)
                    RETURNING id
                    """,
                    workspace["id"],
                    user_id,
                    api_key_id,
                )
                with pytest.raises(asyncpg.PostgresError):
                    async with database.transaction():
                        await database.execute(
                            "UPDATE public.audit_events SET action = 'mutated' WHERE id = $1",
                            audit_id,
                        )
                with pytest.raises(asyncpg.PostgresError):
                    async with database.transaction():
                        await database.execute(
                            "DELETE FROM public.audit_events WHERE id = $1", audit_id
                        )
                raise _RollbackAuditProbe
        except _RollbackAuditProbe:
            pass
    finally:
        if workspace is not None:
            await database.execute(
                "DELETE FROM public.workspaces WHERE id = $1", workspace["id"]
            )
        await database.execute("DELETE FROM public.profiles WHERE id = $1", user_id)
        await database.execute("DELETE FROM auth.users WHERE id = $1", user_id)
