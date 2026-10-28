from __future__ import annotations

import pytest
from app.core.settings import APISettings, SettingsError


def test_local_settings_have_safe_defaults_and_redacted_diagnostics() -> None:
    settings = APISettings.from_env({})

    assert settings.app_env == "local"
    assert settings.port == 8000
    assert settings.cors_origins == ("http://localhost:3000",)
    assert settings.redacted() == {
        "app_env": "local",
        "app_name": "ClassVoice API",
        "app_version": "0.1.0",
        "host": "0.0.0.0",
        "port": 8000,
        "database_configured": True,
        "redis_configured": True,
        "cors_origins": ("http://localhost:3000",),
        "storage_provider": "s3",
        "s3_endpoint": "http://localhost:4566",
        "s3_region": "us-east-1",
        "storage_buckets": {
            "voice_inputs": "voice-inputs",
            "voice_derived": "voice-derived",
            "generated_audio": "generated-audio",
            "exports": "exports",
        },
        "storage_signed_url_ttl_seconds": 600,
        "request_id_header": "X-Request-ID",
        "auth": {
            "provider": "local",
            "supabase_configured": False,
            "jwt_configured": False,
            "jwt_issuer": None,
            "jwt_audience": "authenticated",
            "jwt_clock_skew_seconds": 30,
            "redirect_allowlist": ("http://localhost:3000/auth/callback",),
            "email_confirmation_required": True,
            "verification_ttl_seconds": 86_400,
            "password_reset_ttl_seconds": 3_600,
            "session_ttl_seconds": 3_600,
        },
    }


def test_production_rejects_local_database_and_wildcard_cors() -> None:
    with pytest.raises(SettingsError, match="production DATABASE_URL"):
        APISettings.from_env({"APP_ENV": "production"})

    with pytest.raises(SettingsError, match="wildcard"):
        APISettings.from_env({"CORS_ORIGINS": "*"})


def test_invalid_runtime_urls_are_rejected() -> None:
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        APISettings.from_env({"DATABASE_URL": "sqlite:///classvoice.db"})

    with pytest.raises(SettingsError, match="S3_ENDPOINT"):
        APISettings.from_env({"S3_ENDPOINT": "not-a-url"})
