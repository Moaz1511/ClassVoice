"""Create identity profiles, workspaces, and onboarding primitives."""

from __future__ import annotations

from alembic import op

revision = "0002_identity_workspace"
down_revision = "0001_extensions_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Supabase owns auth.users in hosted environments. The guarded local stub
    # keeps bare PostgreSQL development/CI migrations reproducible without
    # replacing a real Supabase auth schema.
    op.execute(
        """
        DO $$
        DECLARE
            auth_schema_created boolean := false;
        BEGIN
            IF to_regnamespace('auth') IS NULL THEN
                CREATE SCHEMA auth;
                auth_schema_created := true;
            END IF;

            IF to_regclass('auth.users') IS NULL THEN
                CREATE TABLE auth.users (
                    id uuid primary key default gen_random_uuid(),
                    raw_user_meta_data jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null default now()
                );

                CREATE TABLE IF NOT EXISTS auth._classvoice_local_bootstrap (
                    created_schema boolean not null
                );
                INSERT INTO auth._classvoice_local_bootstrap (created_schema)
                VALUES (auth_schema_created)
                ON CONFLICT DO NOTHING;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE public.profiles (
            id uuid primary key references auth.users(id) on delete cascade,
            display_name text not null check (length(display_name) between 1 and 120),
            role public.profile_role not null default 'student',
            locale text not null default 'en-US',
            timezone text not null default 'UTC',
            terms_version text not null,
            safety_ack_version text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.workspaces (
            id uuid primary key default gen_random_uuid(),
            name text not null check (length(name) between 1 and 120),
            slug citext not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{2,63}$'),
            owner_id uuid not null references auth.users(id) on delete restrict,
            plan public.workspace_plan not null default 'free',
            retention_days integer not null default 0 check (retention_days >= 0),
            disabled_at timestamptz,
            disabled_reason text,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.workspace_members (
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            user_id uuid not null references auth.users(id) on delete cascade,
            role public.workspace_role not null default 'viewer',
            invited_by uuid references auth.users(id) on delete set null,
            joined_at timestamptz not null default now(),
            primary key (workspace_id, user_id)
        )
        """
    )

    op.execute(
        """
        CREATE INDEX workspace_members_user_idx
            ON public.workspace_members(user_id, workspace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX workspaces_owner_idx
            ON public.workspaces(owner_id)
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER profiles_set_updated_at
        BEFORE UPDATE ON public.profiles
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER workspaces_set_updated_at
        BEFORE UPDATE ON public.workspaces
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            INSERT INTO public.profiles (
                id,
                display_name,
                role,
                terms_version,
                safety_ack_version
            )
            VALUES (
                NEW.id,
                COALESCE(NULLIF(NEW.raw_user_meta_data ->> 'display_name', ''), 'Student'),
                'student',
                'pending',
                'pending'
            )
            ON CONFLICT (id) DO NOTHING;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS classvoice_on_auth_user_created ON auth.users
        """
    )
    op.execute(
        """
        CREATE TRIGGER classvoice_on_auth_user_created
        AFTER INSERT ON auth.users
        FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.create_personal_workspace(
            p_user_id uuid,
            p_workspace_name text,
            p_workspace_slug text,
            p_terms_version text,
            p_safety_ack_version text
        )
        RETURNS public.workspaces
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, auth, pg_temp
        AS $$
        DECLARE
            existing_workspace public.workspaces;
            created_workspace public.workspaces;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = p_user_id) THEN
                RAISE EXCEPTION 'auth user does not exist'
                    USING ERRCODE = '23503';
            END IF;

            IF p_workspace_name IS NULL OR length(p_workspace_name) NOT BETWEEN 1 AND 120 THEN
                RAISE EXCEPTION 'workspace name must be between 1 and 120 characters'
                    USING ERRCODE = '22023';
            END IF;

            IF p_workspace_slug IS NULL OR p_workspace_slug !~ '^[a-z0-9][a-z0-9-]{2,63}$' THEN
                RAISE EXCEPTION 'workspace slug is invalid'
                    USING ERRCODE = '22023';
            END IF;

            IF p_terms_version IS NULL OR length(p_terms_version) = 0
                OR p_safety_ack_version IS NULL OR length(p_safety_ack_version) = 0 THEN
                RAISE EXCEPTION 'terms and safety acknowledgement versions are required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT w.*
            INTO existing_workspace
            FROM public.workspaces AS w
            WHERE w.owner_id = p_user_id
            ORDER BY w.created_at
            LIMIT 1;

            IF FOUND THEN
                IF existing_workspace.slug = p_workspace_slug THEN
                    RETURN existing_workspace;
                END IF;

                RAISE EXCEPTION 'personal workspace already exists for user'
                    USING ERRCODE = '23505';
            END IF;

            INSERT INTO public.profiles (
                id,
                display_name,
                role,
                terms_version,
                safety_ack_version
            )
            SELECT
                u.id,
                COALESCE(NULLIF(u.raw_user_meta_data ->> 'display_name', ''), 'Student'),
                'student',
                p_terms_version,
                p_safety_ack_version
            FROM auth.users AS u
            WHERE u.id = p_user_id
            ON CONFLICT (id) DO UPDATE
            SET terms_version = EXCLUDED.terms_version,
                safety_ack_version = EXCLUDED.safety_ack_version,
                updated_at = now();

            INSERT INTO public.workspaces (name, slug, owner_id)
            VALUES (p_workspace_name, p_workspace_slug, p_user_id)
            RETURNING * INTO created_workspace;

            INSERT INTO public.workspace_members (workspace_id, user_id, role)
            VALUES (created_workspace.id, p_user_id, 'owner');

            RETURN created_workspace;
        END;
        $$
        """
    )

    op.execute(
        """
        REVOKE ALL ON FUNCTION public.create_personal_workspace(
            uuid, text, text, text, text
        ) FROM PUBLIC
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.create_personal_workspace(
            uuid, text, text, text, text
        )
        """
    )
    op.execute("DROP TRIGGER IF EXISTS classvoice_on_auth_user_created ON auth.users")
    op.execute("DROP FUNCTION IF EXISTS public.handle_new_auth_user()")
    op.execute("DROP TRIGGER IF EXISTS workspaces_set_updated_at ON public.workspaces")
    op.execute("DROP TRIGGER IF EXISTS profiles_set_updated_at ON public.profiles")
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at()")
    op.execute("DROP TABLE IF EXISTS public.workspace_members")
    op.execute("DROP TABLE IF EXISTS public.workspaces")
    op.execute("DROP TABLE IF EXISTS public.profiles")

    # Never remove a hosted Supabase auth schema. Only the guarded local stub
    # created by this migration is eligible for cleanup.
    op.execute(
        """
        DO $$
        DECLARE
            created_schema boolean;
        BEGIN
            IF to_regclass('auth._classvoice_local_bootstrap') IS NOT NULL THEN
                SELECT b.created_schema
                INTO created_schema
                FROM auth._classvoice_local_bootstrap AS b
                LIMIT 1;
                DROP TABLE IF EXISTS auth.users;
                DROP TABLE IF EXISTS auth._classvoice_local_bootstrap;
                IF created_schema AND to_regnamespace('auth') IS NOT NULL THEN
                    DROP SCHEMA auth;
                END IF;
            END IF;
        END $$;
        """
    )
