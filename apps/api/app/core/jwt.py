"""Supabase-compatible HS256 access-token verification.

Supabase's default access tokens are signed JWTs. This module keeps verification
small and explicit: only HS256 is accepted, issuer/audience/signature/expiry are
mandatory, and the token subject must be a UUID that can map to ``auth.users``.
Asymmetric signing can be added later behind the same interface without weakening
the current allowlist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from .auth_config import AuthConfig, AuthConfigurationError


class JWTVerificationError(RuntimeError):
    """A user-safe token verification failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthClaims:
    """The minimum verified identity data used by API authorization."""

    subject: UUID
    issuer: str
    audience: tuple[str, ...]
    role: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    session_id: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _decode_segment(segment: str, claim_name: str) -> Mapping[str, Any]:
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        value = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JWTVerificationError(
            "AUTH_TOKEN_MALFORMED",
            f"JWT {claim_name} is malformed.",
        ) from error
    if not isinstance(value, dict):
        raise JWTVerificationError("AUTH_TOKEN_MALFORMED", f"JWT {claim_name} must be an object.")
    return value


def _numeric_timestamp(claims: Mapping[str, Any], name: str) -> datetime:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", f"JWT {name} is invalid.")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise JWTVerificationError(
            "AUTH_TOKEN_CLAIMS_INVALID",
            f"JWT {name} is invalid.",
        ) from error


def _audiences(claims: Mapping[str, Any]) -> tuple[str, ...]:
    value = claims.get("aud")
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT audience is invalid.")


def _scopes(claims: Mapping[str, Any]) -> frozenset[str]:
    values: list[str] = []
    for claim_name in ("scope", "scp"):
        value = claims.get(claim_name)
        if value is None:
            continue
        if isinstance(value, str):
            values.extend(value.split())
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values.extend(value)
        else:
            raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT scopes are invalid.")
    app_metadata = claims.get("app_metadata")
    if app_metadata is not None:
        if not isinstance(app_metadata, dict):
            raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT app metadata is invalid.")
        metadata_scopes = app_metadata.get("scopes")
        if metadata_scopes is not None:
            if not isinstance(metadata_scopes, list) or not all(
                isinstance(item, str) for item in metadata_scopes
            ):
                raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT scopes are invalid.")
            values.extend(metadata_scopes)
    return frozenset(value for value in values if value)


class JWTVerifier:
    """Verify one Supabase access token against a locked issuer and audience."""

    def __init__(
        self,
        secret: str,
        issuer: str,
        audience: str = "authenticated",
        expected_role: str = "authenticated",
        clock_skew_seconds: int = 30,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not secret.strip():
            raise JWTVerificationError(
                "AUTH_VERIFIER_MISCONFIGURED",
                "JWT secret is not configured.",
            )
        if not issuer.strip() or not audience.strip() or not expected_role.strip():
            raise JWTVerificationError(
                "AUTH_VERIFIER_MISCONFIGURED",
                "JWT claims are not configured.",
            )
        if clock_skew_seconds < 0:
            raise JWTVerificationError(
                "AUTH_VERIFIER_MISCONFIGURED",
                "JWT clock skew cannot be negative.",
            )
        self._secret = secret.encode()
        self._issuer = issuer
        self._audience = audience
        self._expected_role = expected_role
        self._clock_skew_seconds = clock_skew_seconds
        self._now = _utc_now if now is None else now

    @classmethod
    def from_config(cls, config: AuthConfig) -> JWTVerifier:
        if config.jwt_secret is None or config.jwt_issuer is None:
            raise AuthConfigurationError(
                "JWT verification requires SUPABASE_JWT_SECRET and SUPABASE_JWT_ISSUER"
            )
        return cls(
            secret=config.jwt_secret,
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            clock_skew_seconds=config.jwt_clock_skew_seconds,
        )

    def verify(self, token: str) -> AuthClaims:
        parts = token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise JWTVerificationError("AUTH_TOKEN_MALFORMED", "Bearer token is malformed.")
        header = _decode_segment(parts[0], "header")
        payload = _decode_segment(parts[1], "payload")
        if header.get("alg") != "HS256":
            raise JWTVerificationError(
                "AUTH_TOKEN_ALGORITHM",
                "Bearer token uses an unsupported algorithm.",
            )
        try:
            provided_signature = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        except (ValueError, UnicodeDecodeError) as error:
            raise JWTVerificationError(
                "AUTH_TOKEN_MALFORMED",
                "Bearer token signature is malformed.",
            ) from error
        signed_value = f"{parts[0]}.{parts[1]}".encode()
        expected_signature = hmac.new(self._secret, signed_value, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_signature, expected_signature):
            raise JWTVerificationError("AUTH_TOKEN_SIGNATURE", "Bearer token signature is invalid.")

        issuer = payload.get("iss")
        if issuer != self._issuer:
            raise JWTVerificationError("AUTH_TOKEN_ISSUER", "Bearer token issuer is invalid.")
        audiences = _audiences(payload)
        if self._audience not in audiences:
            raise JWTVerificationError("AUTH_TOKEN_AUDIENCE", "Bearer token audience is invalid.")
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT subject is invalid.")
        try:
            user_id = UUID(subject)
        except ValueError as error:
            raise JWTVerificationError(
                "AUTH_TOKEN_CLAIMS_INVALID",
                "JWT subject is invalid.",
            ) from error
        role = payload.get("role")
        if role != self._expected_role:
            raise JWTVerificationError("AUTH_TOKEN_ROLE_INVALID", "Bearer token role is invalid.")
        issued_at = _numeric_timestamp(payload, "iat")
        expires_at = _numeric_timestamp(payload, "exp")
        now = self._now()
        skew = self._clock_skew_seconds
        if expires_at <= now.replace(microsecond=0) - timedelta(seconds=skew):
            raise JWTVerificationError("AUTH_TOKEN_EXPIRED", "Bearer token has expired.")
        if issued_at > now.replace(microsecond=0) + timedelta(seconds=skew):
            raise JWTVerificationError("AUTH_TOKEN_NOT_YET_VALID", "Bearer token is not yet valid.")
        not_before = payload.get("nbf")
        if not_before is not None:
            not_before_at = _numeric_timestamp({"nbf": not_before}, "nbf")
            if not_before_at > now + timedelta(seconds=skew):
                raise JWTVerificationError(
                    "AUTH_TOKEN_NOT_YET_VALID",
                    "Bearer token is not yet valid.",
                )
        session_id = payload.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise JWTVerificationError("AUTH_TOKEN_CLAIMS_INVALID", "JWT session ID is invalid.")
        return AuthClaims(
            subject=user_id,
            issuer=issuer,
            audience=audiences,
            role=role,
            scopes=_scopes(payload),
            issued_at=issued_at,
            expires_at=expires_at,
            session_id=session_id,
        )
