"""Create voice, consent, model, and audio asset tables."""

from __future__ import annotations

from alembic import op

revision = "0003_voice_assets"
down_revision = "0002_identity_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.model_versions (
            id uuid primary key default gen_random_uuid(),
            model_key text not null,
            version text not null,
            checkpoint_sha256 text not null check (length(checkpoint_sha256) = 64),
            runtime text not null,
            license_name text not null,
            license_url text,
            license_review_status text not null
                check (license_review_status in ('pending', 'approved', 'rejected')),
            supported_languages text[] not null default '{}',
            config jsonb not null default '{}'::jsonb,
            enabled boolean not null default false,
            created_at timestamptz not null default now(),
            unique (model_key, version, checkpoint_sha256)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.voice_profiles (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            created_by uuid not null references auth.users(id) on delete restrict,
            name text not null check (length(name) between 1 and 120),
            language_code text not null default 'en-US'
                check (language_code ~ '^[a-z]{2,3}(-[A-Z]{2}|-[A-Z][a-z]{2,4})?$'),
            status public.voice_status not null default 'draft',
            consent_status public.consent_status not null default 'accepted',
            active_model_version_id uuid,
            reference_duration_ms integer check (reference_duration_ms between 6000 and 180000),
            quality_score numeric(5,4) check (quality_score between 0 and 1),
            rejection_code text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            revoked_at timestamptz,
            archived_at timestamptz
        )
        """
    )

    op.execute(
        """
        ALTER TABLE public.voice_profiles
            ADD CONSTRAINT voice_profiles_model_fk
            FOREIGN KEY (active_model_version_id)
            REFERENCES public.model_versions(id) ON DELETE RESTRICT
        """
    )

    op.execute(
        """
        CREATE TABLE public.audio_assets (
            id uuid primary key default gen_random_uuid(),
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            owner_id uuid not null references auth.users(id) on delete restrict,
            kind public.audio_kind not null,
            status public.audio_status not null default 'quarantined',
            object_key text not null unique,
            mime_type text not null,
            byte_size bigint not null check (byte_size between 1 and 268435456),
            duration_ms integer check (duration_ms >= 0),
            sample_rate_hz integer check (sample_rate_hz between 8000 and 192000),
            channels smallint check (channels between 1 and 8),
            sha256 text check (sha256 is null or length(sha256) = 64),
            storage_bucket text not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            deleted_at timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE public.voice_consent_records (
            id uuid primary key default gen_random_uuid(),
            voice_profile_id uuid not null references public.voice_profiles(id) on delete cascade,
            workspace_id uuid not null references public.workspaces(id) on delete cascade,
            subject_user_id uuid references auth.users(id) on delete set null,
            consent_statement_version text not null,
            status public.consent_status not null default 'accepted',
            attestation_text_hash text not null check (length(attestation_text_hash) = 64),
            evidence_asset_id uuid,
            accepted_at timestamptz not null default now(),
            accepted_ip_hash text,
            accepted_user_agent_hash text,
            revoked_at timestamptz,
            revoke_reason text,
            created_at timestamptz not null default now()
        )
        """
    )

    op.execute(
        """
        ALTER TABLE public.voice_consent_records
            ADD CONSTRAINT voice_consent_evidence_fk
            FOREIGN KEY (evidence_asset_id)
            REFERENCES public.audio_assets(id) ON DELETE SET NULL
        """
    )

    op.execute(
        """
        CREATE TABLE public.voice_samples (
            id uuid primary key default gen_random_uuid(),
            voice_profile_id uuid not null references public.voice_profiles(id) on delete cascade,
            audio_asset_id uuid not null references public.audio_assets(id) on delete restrict,
            transcript text,
            speaker_count smallint check (speaker_count is null or speaker_count >= 1),
            silence_ratio numeric(5,4)
                check (silence_ratio is null or silence_ratio between 0 and 1),
            clipping_ratio numeric(5,4)
                check (clipping_ratio is null or clipping_ratio between 0 and 1),
            quality_report jsonb not null default '{}'::jsonb,
            is_primary boolean not null default true,
            created_at timestamptz not null default now(),
            unique (voice_profile_id, audio_asset_id)
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER voice_profiles_set_updated_at
        BEFORE UPDATE ON public.voice_profiles
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """
    )

    op.execute(
        """
        CREATE INDEX voice_profiles_workspace_status_idx
            ON public.voice_profiles(workspace_id, status, updated_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX voice_profiles_creator_idx
            ON public.voice_profiles(created_by, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX voice_consent_voice_status_idx
            ON public.voice_consent_records(voice_profile_id, status, accepted_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX audio_assets_workspace_kind_idx
            ON public.audio_assets(workspace_id, kind, created_at desc)
        """
    )
    op.execute(
        """
        CREATE INDEX voice_samples_voice_idx
            ON public.voice_samples(voice_profile_id, is_primary desc)
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS voice_profiles_set_updated_at ON public.voice_profiles")
    op.execute("DROP TABLE IF EXISTS public.voice_samples")
    op.execute("DROP TABLE IF EXISTS public.voice_consent_records")
    op.execute("DROP TABLE IF EXISTS public.voice_profiles")
    op.execute("DROP TABLE IF EXISTS public.audio_assets")
    op.execute("DROP TABLE IF EXISTS public.model_versions")
