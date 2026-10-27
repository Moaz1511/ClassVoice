"""Enforce voice readiness and consent-revocation invariants."""

from __future__ import annotations

from alembic import op

revision = "0007_voice_invariants"
down_revision = "0006_rls_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_voice_profile_state()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF NEW.consent_status = 'revoked' AND NEW.status <> 'revoked' THEN
                NEW.status = 'revoked';
                NEW.revoked_at = COALESCE(NEW.revoked_at, now());
            END IF;

            IF NEW.status <> 'ready' THEN
                RETURN NEW;
            END IF;

            IF NEW.consent_status <> 'accepted' THEN
                RAISE EXCEPTION 'voice cannot become ready without accepted consent'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.active_model_version_id IS NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM public.model_versions AS mv
                    WHERE mv.id = NEW.active_model_version_id
                      AND mv.enabled = true
                      AND mv.license_review_status = 'approved'
                ) THEN
                RAISE EXCEPTION 'voice cannot become ready without an approved model'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM public.voice_samples AS vs
                JOIN public.audio_assets AS aa ON aa.id = vs.audio_asset_id
                WHERE vs.voice_profile_id = NEW.id
                  AND vs.is_primary = true
                  AND aa.status = 'available'
            ) THEN
                RAISE EXCEPTION 'voice cannot become ready without an available primary sample'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM public.voice_consent_records AS vcr
                WHERE vcr.voice_profile_id = NEW.id
                  AND vcr.status = 'accepted'
                  AND vcr.revoked_at IS NULL
            ) THEN
                RAISE EXCEPTION 'voice cannot become ready without active consent'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER voice_profiles_validate_state
        BEFORE INSERT OR UPDATE OF status, consent_status, active_model_version_id
        ON public.voice_profiles
        FOR EACH ROW EXECUTE FUNCTION public.validate_voice_profile_state()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.sync_voice_revocation_from_consent()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF NEW.status = 'revoked' OR NEW.revoked_at IS NOT NULL THEN
                UPDATE public.voice_profiles
                SET consent_status = 'revoked',
                    status = 'revoked',
                    revoked_at = COALESCE(revoked_at, now()),
                    updated_at = now()
                WHERE id = NEW.voice_profile_id
                  AND (
                      consent_status <> 'revoked'
                      OR status <> 'revoked'
                      OR revoked_at IS NULL
                  );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER voice_consent_sync_revocation
        AFTER INSERT OR UPDATE OF status, revoked_at
        ON public.voice_consent_records
        FOR EACH ROW EXECUTE FUNCTION public.sync_voice_revocation_from_consent()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_generation_job_voice()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            selected_voice public.voice_profiles;
        BEGIN
            SELECT vp.*
            INTO selected_voice
            FROM public.voice_profiles AS vp
            WHERE vp.id = NEW.voice_profile_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'generation job voice does not exist'
                    USING ERRCODE = '23503';
            END IF;

            IF selected_voice.status IN ('revoked', 'archived')
                OR selected_voice.consent_status = 'revoked'
                OR NOT EXISTS (
                    SELECT 1
                    FROM public.voice_consent_records AS vcr
                    WHERE vcr.voice_profile_id = selected_voice.id
                      AND vcr.status = 'accepted'
                      AND vcr.revoked_at IS NULL
                ) THEN
                RAISE EXCEPTION 'generation is blocked for a revoked or consentless voice'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER generation_jobs_validate_voice
        BEFORE INSERT OR UPDATE OF voice_profile_id
        ON public.generation_jobs
        FOR EACH ROW EXECUTE FUNCTION public.validate_generation_job_voice()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS generation_jobs_validate_voice ON public.generation_jobs"
    )
    op.execute("DROP FUNCTION IF EXISTS public.validate_generation_job_voice()")
    op.execute(
        "DROP TRIGGER IF EXISTS voice_consent_sync_revocation ON public.voice_consent_records"
    )
    op.execute("DROP FUNCTION IF EXISTS public.sync_voice_revocation_from_consent()")
    op.execute(
        "DROP TRIGGER IF EXISTS voice_profiles_validate_state ON public.voice_profiles"
    )
    op.execute("DROP FUNCTION IF EXISTS public.validate_voice_profile_state()")
