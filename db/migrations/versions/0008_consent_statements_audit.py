"""Add canonical consent statements and auditable acceptance evidence."""

from __future__ import annotations

from alembic import op

revision = "0008_consent_statements_audit"
down_revision = "0007_voice_invariants"
branch_labels = None
depends_on = None


CONSENT_V1_TEXT = (
    "I confirm that I own this voice or have permission from the voice owner "
    "to create and use this ClassVoice voice profile for synthetic academic narration."
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.consent_statements (
            version text primary key
                CHECK (length(version) BETWEEN 1 AND 64),
            statement_text text not null
                CHECK (length(statement_text) BETWEEN 1 AND 10000),
            statement_text_hash text not null
                CHECK (
                    statement_text_hash = encode(digest(statement_text, 'sha256'), 'hex')
                ),
            published_at timestamptz not null default now(),
            retired_at timestamptz,
            created_at timestamptz not null default now(),
            CHECK (retired_at IS NULL OR retired_at >= published_at)
        )
        """
    )
    op.execute(
        """
        INSERT INTO public.consent_statements (
            version, statement_text, statement_text_hash
        )
        SELECT 'consent-v1', statement_text,
               encode(digest(statement_text, 'sha256'), 'hex')
        FROM (VALUES (
            'I confirm that I own this voice or have permission from the voice owner '
            'to create and use this ClassVoice voice profile for synthetic academic narration.'
        )) AS seed(statement_text)
        """
    )
    op.execute(
        """
        ALTER TABLE public.voice_consent_records
            ADD COLUMN accepted_by_user_id uuid
                REFERENCES auth.users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE public.voice_consent_records
            ADD CONSTRAINT voice_consent_statement_fk
            FOREIGN KEY (consent_statement_version)
            REFERENCES public.consent_statements(version)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX voice_consent_one_active_idx
            ON public.voice_consent_records(voice_profile_id)
            WHERE status = 'accepted' AND revoked_at IS NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_consent_acceptance()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, auth, pg_temp
        AS $$
        DECLARE
            canonical public.consent_statements;
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.status IN ('revoked', 'expired')
                AND NEW.status = 'accepted' THEN
                RAISE EXCEPTION 'revoked or expired consent cannot be reused'
                    USING ERRCODE = '23514';
            END IF;

            IF TG_OP = 'UPDATE' AND OLD.status = 'accepted' THEN
                IF NEW.consent_statement_version IS DISTINCT FROM OLD.consent_statement_version
                    OR NEW.attestation_text_hash IS DISTINCT FROM OLD.attestation_text_hash
                    OR NEW.accepted_at IS DISTINCT FROM OLD.accepted_at
                    OR NEW.accepted_by_user_id IS DISTINCT FROM OLD.accepted_by_user_id THEN
                    RAISE EXCEPTION 'accepted consent evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF NEW.status = 'accepted' THEN
                IF NEW.accepted_by_user_id IS NULL THEN
                    NEW.accepted_by_user_id = NEW.subject_user_id;
                END IF;
                IF NEW.accepted_by_user_id IS NULL THEN
                    RAISE EXCEPTION 'accepted consent requires an accepting actor'
                        USING ERRCODE = '23514';
                END IF;

                SELECT cs.*
                INTO canonical
                FROM public.consent_statements AS cs
                WHERE cs.version = NEW.consent_statement_version;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'consent statement version does not exist'
                        USING ERRCODE = '23503';
                END IF;
                IF canonical.retired_at IS NOT NULL THEN
                    RAISE EXCEPTION 'retired consent statement cannot be accepted'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.attestation_text_hash <> canonical.statement_text_hash THEN
                    RAISE EXCEPTION 'consent attestation hash does not match statement version'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.revoked_at IS NOT NULL THEN
                    RAISE EXCEPTION 'accepted consent cannot have revoked_at'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.status = 'revoked' THEN
                NEW.revoked_at = COALESCE(NEW.revoked_at, now());
            ELSIF NEW.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'only revoked consent may have revoked_at'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER voice_consent_validate_acceptance
        BEFORE INSERT OR UPDATE ON public.voice_consent_records
        FOR EACH ROW EXECUTE FUNCTION public.validate_consent_acceptance()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.audit_consent_acceptance()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, auth, pg_temp
        AS $$
        BEGIN
            IF NEW.status = 'accepted'
                AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'accepted') THEN
                INSERT INTO public.audit_events (
                    workspace_id,
                    actor_type,
                    actor_user_id,
                    action,
                    resource_type,
                    resource_id,
                    metadata
                )
                VALUES (
                    NEW.workspace_id,
                    'user',
                    NEW.accepted_by_user_id,
                    'consent.accepted',
                    'voice_consent_record',
                    NEW.id,
                    jsonb_build_object(
                        'statement_version', NEW.consent_statement_version,
                        'statement_text_hash', NEW.attestation_text_hash,
                        'accepted_at', NEW.accepted_at
                    )
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER voice_consent_acceptance_audit
        AFTER INSERT OR UPDATE OF status ON public.voice_consent_records
        FOR EACH ROW EXECUTE FUNCTION public.audit_consent_acceptance()
        """
    )
    op.execute("CREATE INDEX consent_statements_published_idx ON public.consent_statements(published_at DESC)")
    op.execute("ALTER TABLE public.consent_statements ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        GRANT SELECT ON TABLE public.consent_statements TO authenticated, service_role
        """
    )
    op.execute(
        """
        CREATE POLICY consent_statements_authenticated_select
        ON public.consent_statements FOR SELECT TO authenticated
        USING (true)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS voice_consent_acceptance_audit
            ON public.voice_consent_records
        """
    )
    op.execute("DROP FUNCTION IF EXISTS public.audit_consent_acceptance()")
    op.execute(
        """
        DROP TRIGGER IF EXISTS voice_consent_validate_acceptance
            ON public.voice_consent_records
        """
    )
    op.execute("DROP FUNCTION IF EXISTS public.validate_consent_acceptance()")
    op.execute("DROP INDEX IF EXISTS public.voice_consent_one_active_idx")
    op.execute("DROP POLICY IF EXISTS consent_statements_authenticated_select ON public.consent_statements")
    op.execute("ALTER TABLE public.consent_statements DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS public.consent_statements_published_idx")
    op.execute(
        "ALTER TABLE public.voice_consent_records DROP CONSTRAINT IF EXISTS voice_consent_statement_fk"
    )
    op.execute(
        "ALTER TABLE public.voice_consent_records DROP COLUMN IF EXISTS accepted_by_user_id"
    )
    op.execute("DROP TABLE IF EXISTS public.consent_statements")
