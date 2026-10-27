from __future__ import annotations

import pytest
from app.core.auth_config import AuthConfig, AuthConfigurationError


def test_local_defaults_are_safe_and_redacted() -> None:
    config = AuthConfig.from_env({})

    assert config.provider == "local"
    assert config.email_confirmation_required is True
    assert config.assert_redirect_allowed("http://localhost:3000/auth/callback") == (
        "http://localhost:3000/auth/callback"
    )
    assert config.redacted() == {
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
    }


def test_supabase_profile_requires_real_server_values() -> None:
    with pytest.raises(AuthConfigurationError, match="SUPABASE_SERVICE_ROLE_KEY"):
        AuthConfig.from_env(
            {
                "CLASSVOICE_AUTH_PROVIDER": "supabase",
                "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
                "NEXT_PUBLIC_SUPABASE_ANON_KEY": "replace-with-anon-key",
                "SUPABASE_SERVICE_ROLE_KEY": "replace-with-server-only-key",
            }
        )


def test_supabase_profile_accepts_real_values_without_exposing_secrets() -> None:
    config = AuthConfig.from_env(
        {
            "CLASSVOICE_AUTH_PROVIDER": "supabase",
            "NEXT_PUBLIC_SUPABASE_URL": "https://project.supabase.co",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon-key-from-secret-store",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-from-secret-store",
            "SUPABASE_JWT_SECRET": "jwt-secret-from-secret-store",
            "CLASSVOICE_AUTH_REDIRECT_ALLOWLIST": "https://app.example.com/auth/callback",
        }
    )

    assert config.redacted() == {
        "provider": "supabase",
        "supabase_configured": True,
        "jwt_configured": True,
        "jwt_issuer": "https://project.supabase.co/auth/v1",
        "jwt_audience": "authenticated",
        "jwt_clock_skew_seconds": 30,
        "redirect_allowlist": ("https://app.example.com/auth/callback",),
        "email_confirmation_required": True,
        "verification_ttl_seconds": 86_400,
        "password_reset_ttl_seconds": 3_600,
        "session_ttl_seconds": 3_600,
    }
    assert "service-role-from-secret-store" not in str(config.redacted())


def test_redirect_allowlist_is_exact_and_local_http_only() -> None:
    config = AuthConfig.from_env(
        {
            "CLASSVOICE_AUTH_REDIRECT_ALLOWLIST": (
                "http://localhost:3000/auth/callback,https://app.example.com/auth/callback"
            )
        }
    )

    assert config.assert_redirect_allowed("https://app.example.com/auth/callback")
    with pytest.raises(AuthConfigurationError, match="without query"):
        config.assert_redirect_allowed("https://app.example.com/auth/callback?next=/dashboard")
    with pytest.raises(AuthConfigurationError, match="must use https"):
        AuthConfig.from_env({"CLASSVOICE_AUTH_REDIRECT_ALLOWLIST": "http://app.example.com/callback"})
