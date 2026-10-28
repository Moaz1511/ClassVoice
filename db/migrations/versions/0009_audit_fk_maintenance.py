"""Allow referential cleanup to maintain append-only audit foreign keys."""

from __future__ import annotations

from alembic import op

revision = "0009_audit_fk_maintenance"
down_revision = "0008_consent_statements_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            -- PostgreSQL's referential-action trigger may null out a foreign
            -- key when its parent workspace/user is deleted. That maintenance
            -- update is not an application mutation of the audit record.
            IF pg_trigger_depth() > 1 THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            RAISE EXCEPTION 'audit events are append-only'
                USING ERRCODE = '55000';
            RETURN NULL;
        END;
        $$
        """
    )


def downgrade() -> None:
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
