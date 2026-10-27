"""Create API keys, webhooks, usage, audit, moderation, and export tables."""

from __future__ import annotations

from alembic import op

revision = "0005_integrations_audit"
down_revision = "0004_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.api_keys (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            created_by uuid not null references auth.users(id) on delete restrict,
            name text not null check (length(name) between 1 and 100),
            key_prefix text not null check (length(key_prefix) between 6 and 16),
            key_hash text not null unique,
            scopes text[] not null check (cardinality(scopes) > 0),
            status public.api_key_status not null default 'active',
            expires_at timestamptz,
            last_used_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz not null default now(),
            check (expires_at is null or expires_at > created_at)
        )
        """
    )

    op.execute(
        """
        ALTER TABLE public.generation_jobs
            ADD CONSTRAINT generation_jobs_api_key_fk
            FOREIGN KEY (api_key_id)
            REFERENCES public.api_keys(id) ON DELETE SET NULL
        """
    )

    op.execute(
        """
        CREATE TABLE public.webhook_endpoints (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            created_by uuid not null references auth.users(id) on delete restrict,
            url text not null,
            secret_hash text not null,
            secret_prefix text not null,
            events text[] not null check (cardinality(events) > 0),
            status public.webhook_status not null default 'pending_verification',
            failure_count integer not null default 0 check (failure_count >= 0),
            last_delivered_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.webhook_deliveries (
            id uuid primary key default gen_random_uuid(),
            webhook_endpoint_id uuid not null references public.webhook_endpoints(id) on delete cascade,
            event_type text not null,
            event_id uuid not null,
            payload jsonb not null,
            status public.delivery_status not null default 'pending',
            attempt_count integer not null default 0,
            next_attempt_at timestamptz,
            response_status integer,
            response_body_hash text,
            delivered_at timestamptz,
            created_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.usage_events (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            user_id uuid references auth.users(id) on delete set null,
            api_key_id uuid references public.api_keys(id) on delete set null,
            generation_job_id uuid references public.generation_jobs(id) on delete set null,
            event_type text not null,
            units numeric(12,3) not null check (units >= 0),
            metadata jsonb not null default '{}'::jsonb,
            occurred_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.audit_events (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid references public.workspaces(id) on delete set null,
            actor_type public.audit_actor_type not null,
            actor_user_id uuid references auth.users(id) on delete set null,
            actor_api_key_id uuid references public.api_keys(id) on delete set null,
            action text not null,
            resource_type text not null,
            resource_id uuid,
            request_id text,
            ip_hash text,
            user_agent_hash text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.moderation_flags (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            reporter_user_id uuid references auth.users(id) on delete set null,
            resource_type text not null,
            resource_id uuid not null,
            reason_code text not null,
            description text,
            status public.moderation_status not null default 'open',
            reviewer_user_id uuid references auth.users(id) on delete set null,
            resolution_note text,
            created_at timestamptz not null default now(),
            resolved_at timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.data_exports (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            requested_by uuid not null references auth.users(id) on delete restrict,
            status text not null default 'queued'
                check (status in ('queued', 'processing', 'ready', 'failed', 'expired')),
            audio_included boolean not null default true,
            object_key text,
            expires_at timestamptz,
            error_code text,
            created_at timestamptz not null default now(),
            completed_at timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER webhook_endpoints_set_updated_at
        BEFORE UPDATE ON public.webhook_endpoints
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit events are append-only'
                USING ERRCODE = '55000';
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON public.audit_events
        FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_event_mutation()
        """
    )

    op.execute(
        """
        CREATE INDEX api_keys_workspace_status_idx
            ON public.api_keys(workspace_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX webhook_endpoints_workspace_idx
            ON public.webhook_endpoints(workspace_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX webhook_deliveries_retry_idx
            ON public.webhook_deliveries(status, next_attempt_at)
        """
    )
    op.execute(
        """
        CREATE INDEX usage_events_workspace_time_idx
            ON public.usage_events(workspace_id, occurred_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_workspace_time_idx
            ON public.audit_events(workspace_id, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_resource_idx
            ON public.audit_events(resource_type, resource_id, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX moderation_flags_status_idx
            ON public.moderation_flags(status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX data_exports_requester_idx
            ON public.data_exports(requested_by, created_at desc)
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON public.audit_events")
    op.execute("DROP FUNCTION IF EXISTS public.prevent_audit_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS webhook_endpoints_set_updated_at ON public.webhook_endpoints")
    op.execute("ALTER TABLE public.generation_jobs DROP CONSTRAINT IF EXISTS generation_jobs_api_key_fk")
    op.execute("DROP TABLE IF EXISTS public.data_exports")
    op.execute("DROP TABLE IF EXISTS public.moderation_flags")
    op.execute("DROP TABLE IF EXISTS public.audit_events")
    op.execute("DROP TABLE IF EXISTS public.usage_events")
    op.execute("DROP TABLE IF EXISTS public.webhook_deliveries")
    op.execute("DROP TABLE IF EXISTS public.webhook_endpoints")
    op.execute("DROP TABLE IF EXISTS public.api_keys")
