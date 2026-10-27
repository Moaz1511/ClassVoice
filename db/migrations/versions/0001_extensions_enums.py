"""Create database extensions and the locked ClassVoice enum catalog."""

from __future__ import annotations

from alembic import op

revision = "0001_extensions_enums"
down_revision = None
branch_labels = None
depends_on = None

ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "workspace_role",
        ("owner", "admin", "editor", "viewer"),
    ),
    (
        "profile_role",
        ("student", "teacher", "agent_developer", "moderator"),
    ),
    (
        "workspace_plan",
        ("free", "pilot", "internal"),
    ),
    (
        "voice_status",
        ("draft", "validating", "processing", "ready", "rejected", "revoked", "archived"),
    ),
    (
        "consent_status",
        ("accepted", "revoked", "expired"),
    ),
    (
        "audio_kind",
        ("voice_reference", "voice_preview", "generated_audio", "export_archive"),
    ),
    (
        "audio_status",
        ("quarantined", "available", "deleted", "failed"),
    ),
    (
        "generation_status",
        ("created", "queued", "processing", "succeeded", "failed", "cancel_requested", "canceled"),
    ),
    (
        "output_format",
        ("wav", "mp3"),
    ),
    (
        "api_key_status",
        ("active", "revoked", "expired"),
    ),
    (
        "webhook_status",
        ("pending_verification", "active", "disabled"),
    ),
    (
        "delivery_status",
        ("pending", "delivered", "retrying", "failed", "abandoned"),
    ),
    (
        "audit_actor_type",
        ("user", "api_key", "worker", "system", "moderator"),
    ),
    (
        "moderation_status",
        ("open", "reviewing", "resolved", "dismissed"),
    ),
)


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    for enum_name, values in ENUMS:
        literals = ", ".join(_quote_literal(value) for value in values)
        op.execute(
            "DO $$ BEGIN "
            f"CREATE TYPE public.{enum_name} AS ENUM ({literals}); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )


def downgrade() -> None:
    for enum_name, _ in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS public.{enum_name}")

    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
