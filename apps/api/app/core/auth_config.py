"""Validated authentication configuration shared by local and hosted profiles.

The API deliberately owns the configuration contract even though Supabase issues
the production session.  This keeps redirect validation and security defaults the
same in the web app, local test provider, and future FastAPI dependencies.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class AuthConfigurationError(ValueError):
    """Raised when authentication configuration is unsafe or incomplete."""


_SUPPORTED_PROVIDERS = frozenset({"local", "supabase"})
_SUPPORTED_OAUTH_PROVIDERS = frozenset({"google", "github"})
_PLACEHOLDER_VALUES = frozenset(
    {
        "replace-with-anon-key",
        "replace-with-server-only-key",
        "replace-with-jwt-secret",
        "https://your-project.supabase.co",
    }
)


def _parse_bool(raw_value: str, name: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AuthConfigurationError(f"{name} must be a boolean")


def _parse_positive_int(raw_value: str, name: str) -> int:
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise AuthConfigurationError(f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise AuthConfigurationError(f"{name} must be a positive integer")
    return parsed


def _validate_redirect_uri(uri: str) -> str:
    normalized = uri.strip()
    parsed = urlsplit(normalized)
    if not parsed.scheme or not parsed.netloc or parsed.query or parsed.fragment:
        raise AuthConfigurationError(
            "OAuth redirect URIs must be absolute URLs without query strings or fragments"
        )
    if parsed.scheme not in {"https", "http"}:
        raise AuthConfigurationError("OAuth redirect URIs must use http or https")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AuthConfigurationError("Non-local OAuth redirect URIs must use https")
    return normalized.rstrip("/")


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Runtime authentication settings with safe local defaults."""

    provider: str = "local"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str = "authenticated"
    jwt_clock_skew_seconds: int = 30
    redirect_allowlist: tuple[str, ...] = ("http://localhost:3000/auth/callback",)
    email_confirmation_required: bool = True
    verification_ttl_seconds: int = 86_400
    password_reset_ttl_seconds: int = 3_600
    session_ttl_seconds: int = 3_600

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AuthConfig:
        """Build and validate configuration from a mapping or process environment."""

        values = os.environ if environ is None else environ
        raw_redirects = values.get(
            "CLASSVOICE_AUTH_REDIRECT_ALLOWLIST",
            "http://localhost:3000/auth/callback",
        )
        redirects = tuple(
            _validate_redirect_uri(value)
            for value in raw_redirects.split(",")
            if value.strip()
        )
        config = cls(
            provider=values.get("CLASSVOICE_AUTH_PROVIDER", "local").strip().lower(),
            supabase_url=values.get("NEXT_PUBLIC_SUPABASE_URL"),
            supabase_anon_key=values.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
            jwt_secret=values.get("SUPABASE_JWT_SECRET"),
            jwt_issuer=values.get("SUPABASE_JWT_ISSUER")
            or _default_jwt_issuer(values.get("NEXT_PUBLIC_SUPABASE_URL")),
            jwt_audience=values.get("SUPABASE_JWT_AUDIENCE", "authenticated").strip(),
            jwt_clock_skew_seconds=_parse_positive_int(
                values.get("SUPABASE_JWT_CLOCK_SKEW_SECONDS", "30"),
                "SUPABASE_JWT_CLOCK_SKEW_SECONDS",
            ),
            redirect_allowlist=redirects,
            email_confirmation_required=_parse_bool(
                values.get("CLASSVOICE_AUTH_EMAIL_CONFIRMATION", "true"),
                "CLASSVOICE_AUTH_EMAIL_CONFIRMATION",
            ),
            verification_ttl_seconds=_parse_positive_int(
                values.get("CLASSVOICE_AUTH_VERIFICATION_TTL_SECONDS", "86400"),
                "CLASSVOICE_AUTH_VERIFICATION_TTL_SECONDS",
            ),
            password_reset_ttl_seconds=_parse_positive_int(
                values.get("CLASSVOICE_AUTH_PASSWORD_RESET_TTL_SECONDS", "3600"),
                "CLASSVOICE_AUTH_PASSWORD_RESET_TTL_SECONDS",
            ),
            session_ttl_seconds=_parse_positive_int(
                values.get("CLASSVOICE_AUTH_SESSION_TTL_SECONDS", "3600"),
                "CLASSVOICE_AUTH_SESSION_TTL_SECONDS",
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Reject insecure or incomplete settings before the app starts."""

        if self.provider not in _SUPPORTED_PROVIDERS:
            raise AuthConfigurationError(
                f"CLASSVOICE_AUTH_PROVIDER must be one of {sorted(_SUPPORTED_PROVIDERS)}"
            )
        if not self.redirect_allowlist:
            raise AuthConfigurationError("OAuth redirect allowlist cannot be empty")
        normalized_redirects = tuple(_validate_redirect_uri(uri) for uri in self.redirect_allowlist)
        if normalized_redirects != self.redirect_allowlist:
            raise AuthConfigurationError("OAuth redirect allowlist contains duplicate slashes")
        for name, value in (
            ("jwt_clock_skew_seconds", self.jwt_clock_skew_seconds),
            ("verification_ttl_seconds", self.verification_ttl_seconds),
            ("password_reset_ttl_seconds", self.password_reset_ttl_seconds),
            ("session_ttl_seconds", self.session_ttl_seconds),
        ):
            if value <= 0:
                raise AuthConfigurationError(f"{name} must be a positive integer")
        if not self.jwt_audience.strip():
            raise AuthConfigurationError("SUPABASE_JWT_AUDIENCE cannot be empty")
        if self.provider == "supabase":
            required_values = {
                "NEXT_PUBLIC_SUPABASE_URL": self.supabase_url,
                "NEXT_PUBLIC_SUPABASE_ANON_KEY": self.supabase_anon_key,
                "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
                "SUPABASE_JWT_SECRET": self.jwt_secret,
            }
            missing = [
                name
                for name, value in required_values.items()
                if value is None or not value.strip() or value in _PLACEHOLDER_VALUES
            ]
            if missing:
                raise AuthConfigurationError(
                    f"Supabase auth requires non-placeholder values for: {', '.join(missing)}"
                )
            assert self.supabase_url is not None
            parsed_url = urlsplit(self.supabase_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise AuthConfigurationError("NEXT_PUBLIC_SUPABASE_URL must be an https URL")
            if self.jwt_issuer is None or not self.jwt_issuer.strip():
                raise AuthConfigurationError("SUPABASE_JWT_ISSUER is required")
            parsed_issuer = urlsplit(self.jwt_issuer)
            if parsed_issuer.scheme != "https" or not parsed_issuer.netloc:
                raise AuthConfigurationError("SUPABASE_JWT_ISSUER must be an https URL")

    def assert_redirect_allowed(self, redirect_uri: str) -> str:
        """Return a normalized callback URI only when it is explicitly allowlisted."""

        normalized = _validate_redirect_uri(redirect_uri)
        if normalized not in self.redirect_allowlist:
            raise AuthConfigurationError("OAuth callback URI is not allowlisted")
        return normalized

    def is_oauth_provider_supported(self, provider: str) -> bool:
        """Return whether a provider is supported by the MVP OAuth contract."""

        return provider.strip().lower() in _SUPPORTED_OAUTH_PROVIDERS

    def redacted(self) -> dict[str, object]:
        """Return diagnostics safe to include in startup logs."""

        return {
            "provider": self.provider,
            "supabase_configured": self.provider == "supabase",
            "jwt_configured": self.jwt_secret is not None and self.jwt_issuer is not None,
            "jwt_issuer": self.jwt_issuer,
            "jwt_audience": self.jwt_audience,
            "jwt_clock_skew_seconds": self.jwt_clock_skew_seconds,
            "redirect_allowlist": self.redirect_allowlist,
            "email_confirmation_required": self.email_confirmation_required,
            "verification_ttl_seconds": self.verification_ttl_seconds,
            "password_reset_ttl_seconds": self.password_reset_ttl_seconds,
            "session_ttl_seconds": self.session_ttl_seconds,
        }


def _default_jwt_issuer(supabase_url: str | None) -> str | None:
    if supabase_url is None or supabase_url in _PLACEHOLDER_VALUES:
        return None
    return f"{supabase_url.rstrip('/')}/auth/v1"
