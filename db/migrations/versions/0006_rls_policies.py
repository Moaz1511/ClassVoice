"""Enable RLS and add explicit workspace authorization policies."""

from __future__ import annotations

from alembic import op

revision = "0006_rls_policies"
down_revision = "0005_integrations_audit"
branch_labels = None
depends_on = None


PUBLIC_TABLES = (
    "profiles",
    "workspaces",
    "workspace_members",
    "model_versions",
    "voice_profiles",
    "voice_consent_records",
    "audio_assets",
    "voice_samples",
    "projects",
    "generation_jobs",
    "generation_outputs",
    "api_keys",
    "webhook_endpoints",
    "webhook_deliveries",
    "usage_events",
    "audit_events",
    "moderation_flags",
    "data_exports",
)


def upgrade() -> None:
    # The hosted Supabase roles already exist. These guarded local roles make
    # policy behavior testable against the bare PostgreSQL development stack.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                CREATE ROLE anon NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                CREATE ROLE authenticated NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                CREATE ROLE service_role NOLOGIN BYPASSRLS;
            END IF;
        END
        $$
        """
    )

    # Supabase provides auth.uid(). The guarded local implementation reads the
    # same request claim used by the integration tests and never replaces a
    # hosted implementation.
    op.execute(
        """
        DO $do$
        DECLARE
            created_local_uid boolean := false;
        BEGIN
            IF to_regprocedure('auth.uid()') IS NULL THEN
                CREATE FUNCTION auth.uid()
                RETURNS uuid
                LANGUAGE sql
                STABLE
                SET search_path = auth, pg_temp
                AS $function$
                    SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
                $function$;
                created_local_uid := true;
            END IF;
            IF created_local_uid THEN
                CREATE TABLE IF NOT EXISTS auth._classvoice_local_rls_bootstrap (
                    uid_function_created boolean not null
                );
                INSERT INTO auth._classvoice_local_rls_bootstrap (uid_function_created)
                VALUES (true);
            END IF;
        END
        $do$
        """
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_member(target_workspace uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.workspace_members AS wm
                WHERE wm.workspace_id = target_workspace
                  AND wm.user_id = auth.uid()
            )
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.has_workspace_role(
            target_workspace uuid,
            allowed public.workspace_role[]
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.workspace_members AS wm
                WHERE wm.workspace_id = target_workspace
                  AND wm.user_id = auth.uid()
                  AND wm.role = ANY (allowed)
            )
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.is_moderator()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.profiles AS p
                WHERE p.id = auth.uid()
                  AND p.role = 'moderator'
            )
        $$
        """
    )
    op.execute("REVOKE ALL ON SCHEMA app FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app TO authenticated, service_role")
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.is_member(uuid) FROM PUBLIC
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.has_workspace_role(uuid, public.workspace_role[]) FROM PUBLIC
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.is_moderator() FROM PUBLIC")
    op.execute(
        """
        GRANT EXECUTE ON FUNCTION app.is_member(uuid),
            app.has_workspace_role(uuid, public.workspace_role[]),
            app.is_moderator()
        TO authenticated, service_role
        """
    )
    op.execute("GRANT USAGE ON SCHEMA auth TO authenticated, service_role")
    op.execute("GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated, service_role")

    for table in PUBLIC_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} "
            "TO authenticated, anon, service_role"
        )

    op.execute(
        """
        CREATE POLICY profiles_self_select
        ON public.profiles FOR SELECT TO authenticated
        USING (id = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY profiles_self_update
        ON public.profiles FOR UPDATE TO authenticated
        USING (id = auth.uid())
        WITH CHECK (id = auth.uid())
        """
    )

    op.execute(
        """
        CREATE POLICY workspaces_member_select
        ON public.workspaces FOR SELECT TO authenticated
        USING (app.is_member(id))
        """
    )
    op.execute(
        """
        CREATE POLICY workspaces_admin_update
        ON public.workspaces FOR UPDATE TO authenticated
        USING (app.has_workspace_role(id, ARRAY['owner', 'admin']::public.workspace_role[]))
        WITH CHECK (app.has_workspace_role(id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )
    op.execute(
        """
        CREATE POLICY workspaces_admin_delete
        ON public.workspaces FOR DELETE TO authenticated
        USING (app.has_workspace_role(id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY members_read
        ON public.workspace_members FOR SELECT TO authenticated
        USING (app.is_member(workspace_id))
        """
    )
    op.execute(
        """
        CREATE POLICY members_admin_write
        ON public.workspace_members FOR ALL TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        WITH CHECK (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY model_versions_enabled_select
        ON public.model_versions FOR SELECT TO authenticated
        USING (enabled = true)
        """
    )

    op.execute(
        """
        CREATE POLICY voice_profiles_member_select
        ON public.voice_profiles FOR SELECT TO authenticated
        USING (app.is_member(workspace_id))
        """
    )
    op.execute(
        """
        CREATE POLICY voice_profiles_editor_insert
        ON public.voice_profiles FOR INSERT TO authenticated
        WITH CHECK (
            created_by = auth.uid()
            AND app.has_workspace_role(
                workspace_id,
                ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY voice_profiles_editor_update
        ON public.voice_profiles FOR UPDATE TO authenticated
        USING (
            app.has_workspace_role(
                workspace_id,
                ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
            )
        )
        WITH CHECK (
            app.has_workspace_role(
                workspace_id,
                ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY voice_profiles_admin_delete
        ON public.voice_profiles FOR DELETE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY consent_member_select
        ON public.voice_consent_records FOR SELECT TO authenticated
        USING (app.is_member(workspace_id) OR subject_user_id = auth.uid())
        """
    )

    op.execute(
        """
        CREATE POLICY audio_assets_member_select
        ON public.audio_assets FOR SELECT TO authenticated
        USING (app.is_member(workspace_id))
        """
    )

    op.execute(
        """
        CREATE POLICY voice_samples_member_select
        ON public.voice_samples FOR SELECT TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND app.is_member(vp.workspace_id)
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY voice_samples_editor_write
        ON public.voice_samples FOR INSERT TO authenticated
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND app.has_workspace_role(
                      vp.workspace_id,
                      ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
                  )
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY voice_samples_editor_update
        ON public.voice_samples FOR UPDATE TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND app.has_workspace_role(
                      vp.workspace_id,
                      ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
                  )
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND app.has_workspace_role(
                      vp.workspace_id,
                      ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
                  )
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY voice_samples_admin_delete
        ON public.voice_samples FOR DELETE TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND app.has_workspace_role(
                      vp.workspace_id,
                      ARRAY['owner', 'admin']::public.workspace_role[]
                  )
            )
        )
        """
    )

    op.execute(
        """
        CREATE POLICY projects_member_select
        ON public.projects FOR SELECT TO authenticated
        USING (app.is_member(workspace_id))
        """
    )
    op.execute(
        """
        CREATE POLICY projects_editor_insert
        ON public.projects FOR INSERT TO authenticated
        WITH CHECK (
            created_by = auth.uid()
            AND app.has_workspace_role(
                workspace_id,
                ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY projects_editor_update
        ON public.projects FOR UPDATE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin', 'editor']::public.workspace_role[]))
        WITH CHECK (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin', 'editor']::public.workspace_role[]))
        """
    )
    op.execute(
        """
        CREATE POLICY projects_admin_delete
        ON public.projects FOR DELETE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY generation_jobs_member_select
        ON public.generation_jobs FOR SELECT TO authenticated
        USING (app.is_member(workspace_id))
        """
    )
    op.execute(
        """
        CREATE POLICY generation_jobs_editor_insert
        ON public.generation_jobs FOR INSERT TO authenticated
        WITH CHECK (
            requested_by = auth.uid()
            AND app.has_workspace_role(
                workspace_id,
                ARRAY['owner', 'admin', 'editor']::public.workspace_role[]
            )
            AND EXISTS (
                SELECT 1
                FROM public.voice_profiles AS vp
                WHERE vp.id = voice_profile_id
                  AND vp.workspace_id = generation_jobs.workspace_id
                  AND vp.status <> 'revoked'
                  AND vp.consent_status <> 'revoked'
            )
            AND EXISTS (
                SELECT 1
                FROM public.model_versions AS mv
                WHERE mv.id = model_version_id
                  AND mv.enabled = true
                  AND mv.license_review_status = 'approved'
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY generation_jobs_editor_update
        ON public.generation_jobs FOR UPDATE TO authenticated
        USING (
            app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
            OR (
                requested_by = auth.uid()
                AND app.has_workspace_role(
                    workspace_id,
                    ARRAY['editor']::public.workspace_role[]
                )
            )
        )
        WITH CHECK (
            app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
            OR (
                requested_by = auth.uid()
                AND app.has_workspace_role(
                    workspace_id,
                    ARRAY['editor']::public.workspace_role[]
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY generation_jobs_admin_delete
        ON public.generation_jobs FOR DELETE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY generation_outputs_member_select
        ON public.generation_outputs FOR SELECT TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM public.generation_jobs AS gj
                WHERE gj.id = generation_job_id
                  AND app.is_member(gj.workspace_id)
            )
        )
        """
    )

    op.execute(
        """
        CREATE POLICY api_keys_admin_select
        ON public.api_keys FOR SELECT TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )
    op.execute(
        """
        CREATE POLICY api_keys_admin_insert
        ON public.api_keys FOR INSERT TO authenticated
        WITH CHECK (
            created_by = auth.uid()
            AND app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY api_keys_admin_update
        ON public.api_keys FOR UPDATE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        WITH CHECK (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )
    op.execute(
        """
        CREATE POLICY api_keys_admin_delete
        ON public.api_keys FOR DELETE TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY webhook_endpoints_admin_all
        ON public.webhook_endpoints FOR ALL TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        WITH CHECK (
            created_by = auth.uid()
            AND app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY webhook_deliveries_admin_select
        ON public.webhook_deliveries FOR SELECT TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM public.webhook_endpoints AS we
                WHERE we.id = webhook_endpoint_id
                  AND app.has_workspace_role(we.workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
            )
        )
        """
    )

    op.execute(
        """
        CREATE POLICY usage_events_admin_select
        ON public.usage_events FOR SELECT TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY audit_events_admin_select
        ON public.audit_events FOR SELECT TO authenticated
        USING (app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]))
        """
    )

    op.execute(
        """
        CREATE POLICY moderation_flags_report
        ON public.moderation_flags FOR INSERT TO authenticated
        WITH CHECK (
            reporter_user_id = auth.uid()
            AND app.is_member(workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY moderation_flags_read
        ON public.moderation_flags FOR SELECT TO authenticated
        USING (
            reporter_user_id = auth.uid()
            OR app.is_moderator()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY moderation_flags_moderator_update
        ON public.moderation_flags FOR UPDATE TO authenticated
        USING (app.is_moderator())
        WITH CHECK (app.is_moderator())
        """
    )
    op.execute(
        """
        CREATE POLICY moderation_flags_moderator_delete
        ON public.moderation_flags FOR DELETE TO authenticated
        USING (app.is_moderator())
        """
    )

    op.execute(
        """
        CREATE POLICY data_exports_requester_select
        ON public.data_exports FOR SELECT TO authenticated
        USING (
            requested_by = auth.uid()
            OR app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY data_exports_requester_insert
        ON public.data_exports FOR INSERT TO authenticated
        WITH CHECK (
            requested_by = auth.uid()
            AND app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
        )
        """
    )
    op.execute(
        """
        CREATE POLICY data_exports_requester_delete
        ON public.data_exports FOR DELETE TO authenticated
        USING (
            requested_by = auth.uid()
            OR app.has_workspace_role(workspace_id, ARRAY['owner', 'admin']::public.workspace_role[])
        )
        """
    )


def downgrade() -> None:
    for table in reversed(PUBLIC_TABLES):
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS data_exports_requester_delete ON public.data_exports")
    op.execute("DROP POLICY IF EXISTS data_exports_requester_insert ON public.data_exports")
    op.execute("DROP POLICY IF EXISTS data_exports_requester_select ON public.data_exports")
    op.execute("DROP POLICY IF EXISTS moderation_flags_moderator_delete ON public.moderation_flags")
    op.execute("DROP POLICY IF EXISTS moderation_flags_moderator_update ON public.moderation_flags")
    op.execute("DROP POLICY IF EXISTS moderation_flags_read ON public.moderation_flags")
    op.execute("DROP POLICY IF EXISTS moderation_flags_report ON public.moderation_flags")
    op.execute("DROP POLICY IF EXISTS audit_events_admin_select ON public.audit_events")
    op.execute("DROP POLICY IF EXISTS usage_events_admin_select ON public.usage_events")
    op.execute("DROP POLICY IF EXISTS webhook_deliveries_admin_select ON public.webhook_deliveries")
    op.execute("DROP POLICY IF EXISTS webhook_endpoints_admin_all ON public.webhook_endpoints")
    op.execute("DROP POLICY IF EXISTS api_keys_admin_delete ON public.api_keys")
    op.execute("DROP POLICY IF EXISTS api_keys_admin_update ON public.api_keys")
    op.execute("DROP POLICY IF EXISTS api_keys_admin_insert ON public.api_keys")
    op.execute("DROP POLICY IF EXISTS api_keys_admin_select ON public.api_keys")
    op.execute("DROP POLICY IF EXISTS generation_outputs_member_select ON public.generation_outputs")
    op.execute("DROP POLICY IF EXISTS generation_jobs_admin_delete ON public.generation_jobs")
    op.execute("DROP POLICY IF EXISTS generation_jobs_editor_update ON public.generation_jobs")
    op.execute("DROP POLICY IF EXISTS generation_jobs_editor_insert ON public.generation_jobs")
    op.execute("DROP POLICY IF EXISTS generation_jobs_member_select ON public.generation_jobs")
    op.execute("DROP POLICY IF EXISTS projects_admin_delete ON public.projects")
    op.execute("DROP POLICY IF EXISTS projects_editor_update ON public.projects")
    op.execute("DROP POLICY IF EXISTS projects_editor_insert ON public.projects")
    op.execute("DROP POLICY IF EXISTS projects_member_select ON public.projects")
    op.execute("DROP POLICY IF EXISTS voice_samples_admin_delete ON public.voice_samples")
    op.execute("DROP POLICY IF EXISTS voice_samples_editor_update ON public.voice_samples")
    op.execute("DROP POLICY IF EXISTS voice_samples_editor_write ON public.voice_samples")
    op.execute("DROP POLICY IF EXISTS voice_samples_member_select ON public.voice_samples")
    op.execute("DROP POLICY IF EXISTS audio_assets_member_select ON public.audio_assets")
    op.execute("DROP POLICY IF EXISTS consent_member_select ON public.voice_consent_records")
    op.execute("DROP POLICY IF EXISTS voice_profiles_admin_delete ON public.voice_profiles")
    op.execute("DROP POLICY IF EXISTS voice_profiles_editor_update ON public.voice_profiles")
    op.execute("DROP POLICY IF EXISTS voice_profiles_editor_insert ON public.voice_profiles")
    op.execute("DROP POLICY IF EXISTS voice_profiles_member_select ON public.voice_profiles")
    op.execute("DROP POLICY IF EXISTS model_versions_enabled_select ON public.model_versions")
    op.execute("DROP POLICY IF EXISTS members_admin_write ON public.workspace_members")
    op.execute("DROP POLICY IF EXISTS members_read ON public.workspace_members")
    op.execute("DROP POLICY IF EXISTS workspaces_admin_delete ON public.workspaces")
    op.execute("DROP POLICY IF EXISTS workspaces_admin_update ON public.workspaces")
    op.execute("DROP POLICY IF EXISTS workspaces_member_select ON public.workspaces")
    op.execute("DROP POLICY IF EXISTS profiles_self_update ON public.profiles")
    op.execute("DROP POLICY IF EXISTS profiles_self_select ON public.profiles")

    op.execute("DROP FUNCTION IF EXISTS app.is_moderator()")
    op.execute("DROP FUNCTION IF EXISTS app.has_workspace_role(uuid, public.workspace_role[])")
    op.execute("DROP FUNCTION IF EXISTS app.is_member(uuid)")
    op.execute("DROP SCHEMA IF EXISTS app")
    op.execute(
        """
        DO $do$
        BEGIN
            IF to_regclass('auth._classvoice_local_rls_bootstrap') IS NOT NULL THEN
                DROP FUNCTION IF EXISTS auth.uid();
                DROP TABLE auth._classvoice_local_rls_bootstrap;
            END IF;
        END
        $do$
        """
    )
