"""Validated runtime settings for the FastAPI control plane."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .auth_config import AuthConfig, AuthConfigurationError


class SettingsError(ValueError):
    """Raised when API settings are unsafe or incomplete."""


_APP_ENVS = frozenset({"local", "test", "staging", "production"})
_STORAGE_PROVIDERS = frozenset({"s3", "supabase"})


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise SettingsError(f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise SettingsError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True, slots=True)
class APISettings:
    """Application settings with safe local defaults and redacted diagnostics."""

    app_env: str = "local"
    app_name: str = "ClassVoice API"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "postgresql+asyncpg://classvoice:change-me-local-only@localhost:5432/classvoice"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    storage_provider: str = "s3"
    s3_endpoint: str = "http://localhost:4566"
    request_id_header: str = "X-Request-ID"
    auth: AuthConfig = AuthConfig()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> APISettings:
        values = os.environ if environ is None else environ
        auth = AuthConfig.from_env(values)
        config = cls(
            app_env=values.get("APP_ENV", "local").strip().lower(),
            app_name=values.get("APP_NAME", "ClassVoice API").strip(),
            app_version=values.get("APP_VERSION", "0.1.0").strip(),
            host=values.get("API_HOST", "0.0.0.0").strip(),
            port=_positive_int(values.get("API_PORT", "8000"), "API_PORT"),
            database_url=values.get(
                "DATABASE_URL",
                "postgresql+asyncpg://classvoice:change-me-local-only@localhost:5432/classvoice",
            ).strip(),
            redis_url=values.get("REDIS_URL", "redis://localhost:6379/0").strip(),
            cors_origins=_split_csv(
                values.get("CORS_ORIGINS", "http://localhost:3000")
            ),
            storage_provider=values.get("STORAGE_PROVIDER", "s3").strip().lower(),
            s3_endpoint=values.get("S3_ENDPOINT", "http://localhost:4566").strip(),
            request_id_header=values.get("REQUEST_ID_HEADER", "X-Request-ID").strip(),
            auth=auth,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.app_env not in _APP_ENVS:
            raise SettingsError(f"APP_ENV must be one of {sorted(_APP_ENVS)}")
        if not self.app_name or not self.app_version:
            raise SettingsError("APP_NAME and APP_VERSION cannot be empty")
        if not self.host or self.port not in range(1, 65_536):
            raise SettingsError("API_HOST and API_PORT are invalid")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise SettingsError("DATABASE_URL must use the postgresql+asyncpg scheme")
        if not self.redis_url.startswith("redis://"):
            raise SettingsError("REDIS_URL must use the redis scheme")
        if self.storage_provider not in _STORAGE_PROVIDERS:
            raise SettingsError(f"STORAGE_PROVIDER must be one of {sorted(_STORAGE_PROVIDERS)}")
        parsed_s3 = urlsplit(self.s3_endpoint)
        if parsed_s3.scheme not in {"http", "https"} or not parsed_s3.netloc:
            raise SettingsError("S3_ENDPOINT must be an absolute HTTP(S) URL")
        if not self.cors_origins:
            raise SettingsError("CORS_ORIGINS cannot be empty")
        if any(origin == "*" for origin in self.cors_origins):
            raise SettingsError("CORS_ORIGINS cannot contain a wildcard")
        if not self.request_id_header:
            raise SettingsError("REQUEST_ID_HEADER cannot be empty")
        try:
            self.auth.validate()
        except AuthConfigurationError as error:
            raise SettingsError(str(error)) from error
        if self.app_env == "production" and "localhost" in self.database_url:
            raise SettingsError("production DATABASE_URL cannot target localhost")

    def redacted(self) -> dict[str, object]:
        """Return startup diagnostics without credentials or connection secrets."""

        return {
            "app_env": self.app_env,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "host": self.host,
            "port": self.port,
            "database_configured": bool(self.database_url),
            "redis_configured": bool(self.redis_url),
            "cors_origins": self.cors_origins,
            "storage_provider": self.storage_provider,
            "s3_endpoint": self.s3_endpoint,
            "request_id_header": self.request_id_header,
            "auth": self.auth.redacted(),
        }
