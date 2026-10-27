"""Create projects, generation jobs, and generation outputs."""

from __future__ import annotations

from alembic import op

revision = "0004_generation"
down_revision = "0003_voice_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.projects (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            created_by uuid not null references auth.users(id) on delete restrict,
            name text not null check (length(name) between 1 and 160),
            description text,
            archived_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.generation_jobs (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            project_id uuid references public.projects(id) on delete set null,
            voice_profile_id uuid not null references public.voice_profiles(id) on delete restrict,
            requested_by uuid not null references auth.users(id) on delete restrict,
            api_key_id uuid,
            status public.generation_status not null default 'created',
            input_text text not null check (length(input_text) between 1 and 10000),
            input_text_sha256 text not null check (length(input_text_sha256) = 64),
            language_code text not null,
            output_format public.output_format not null default 'wav',
            speed numeric(4,2) not null default 1.00 check (speed between 0.5 and 2.0),
            stability numeric(4,3) check (stability is null or stability between 0 and 1),
            style numeric(4,3) check (style is null or style between 0 and 1),
            seed integer,
            model_version_id uuid not null references public.model_versions(id) on delete restrict,
            idempotency_key text not null,
            error_code text,
            error_message_safe text,
            retryable boolean not null default false,
            queue_attempts smallint not null default 0 check (queue_attempts >= 0),
            created_at timestamptz not null default now(),
            started_at timestamptz,
            completed_at timestamptz,
            canceled_at timestamptz,
            unique (workspace_id, idempotency_key)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.generation_outputs (
            id uuid primary key default gen_random_uuid(),
            generation_job_id uuid not null references public.generation_jobs(id) on delete cascade,
            audio_asset_id uuid not null references public.audio_assets(id) on delete restrict,
            output_format public.output_format not null,
            duration_ms integer not null check (duration_ms > 0),
            checksum_sha256 text not null check (length(checksum_sha256) = 64),
            provenance jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique (generation_job_id, audio_asset_id)
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER projects_set_updated_at
        BEFORE UPDATE ON public.projects
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """
    )

    op.execute(
        """
        CREATE INDEX projects_workspace_updated_idx
            ON public.projects(workspace_id, updated_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX generation_jobs_workspace_created_idx
            ON public.generation_jobs(workspace_id, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX generation_jobs_status_idx
            ON public.generation_jobs(status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX generation_jobs_voice_idx
            ON public.generation_jobs(voice_profile_id, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX generation_jobs_project_idx
            ON public.generation_jobs(project_id, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX generation_outputs_job_idx
            ON public.generation_outputs(generation_job_id, created_at desc)
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS projects_set_updated_at ON public.projects")
    op.execute("DROP TABLE IF EXISTS public.generation_outputs")
    op.execute("DROP TABLE IF EXISTS public.generation_jobs")
    op.execute("DROP TABLE IF EXISTS public.projects")
