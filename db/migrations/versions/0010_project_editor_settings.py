"""Persist the non-draft Studio editor settings on projects."""

from __future__ import annotations

from alembic import op

revision = "0010_project_editor_settings"
down_revision = "0009_audit_fk_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.projects
            ADD COLUMN editor_settings jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT projects_editor_settings_object_check
                CHECK (jsonb_typeof(editor_settings) = 'object')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.projects
            DROP CONSTRAINT IF EXISTS projects_editor_settings_object_check,
            DROP COLUMN IF EXISTS editor_settings
        """
    )
