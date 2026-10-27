"""Deterministic, in-memory auth provider for local development and CI.

This provider intentionally mirrors the security-relevant state transitions of
Supabase Auth without pretending to be a production identity service. It is only
selected by ``CLASSVOICE_AUTH_PROVIDER=local`` and keeps all state in process
memory, so local runs never need real email delivery or OAuth credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from .auth_config import AuthConfig


class AuthFlowError(RuntimeError):
    """A user-safe authentication flow error with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    email: str
    display_name: str | None
    email_verified: bool


@dataclass(frozen=True, slots=True)
class AuthSession:
    access_token: str
    user: AuthUser
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerificationChallenge:
    user: AuthUser
    token: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PasswordResetChallenge:
    email: str
    token: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class OAuthAuthorization:
    provider: str
    redirect_uri: str
    state: str
    expires_at: datetime


@dataclass(slots=True)
class _UserRecord:
    user: AuthUser
    password_hash: str


@dataclass(frozen=True, slots=True)
class _ExpiringToken:
    user_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _OAuthState:
    provider: str
    redirect_uri: str
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise AuthFlowError("AUTH_INVALID_EMAIL", "Enter a valid email address.")
    if len(normalized) > 320:
        raise AuthFlowError("AUTH_INVALID_EMAIL", "Enter a valid email address.")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 12 or any(character.isspace() for character in password):
        raise AuthFlowError(
            "AUTH_WEAK_PASSWORD",
            "Password must be at least 12 characters and contain no spaces.",
        )


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return hmac.compare_digest(actual, expected)


class LocalAuthProvider:
    """An in-memory provider implementing the P1-11 auth state machine."""

    def __init__(
        self,
        config: AuthConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if config.provider != "local":
            raise AuthFlowError(
                "AUTH_PROVIDER_MISCONFIGURED",
                "The local provider requires CLASSVOICE_AUTH_PROVIDER=local.",
            )
        config.validate()
        self.config = config
        self._now = _utc_now if now is None else now
        self._users_by_email: dict[str, _UserRecord] = {}
        self._users_by_id: dict[UUID, _UserRecord] = {}
        self._verification_tokens: dict[str, _ExpiringToken] = {}
        self._password_reset_tokens: dict[str, _ExpiringToken] = {}
        self._sessions: dict[str, AuthSession] = {}
        self._oauth_states: dict[str, _OAuthState] = {}

    def sign_up(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> VerificationChallenge:
        normalized_email = _normalize_email(email)
        _validate_password(password)
        if normalized_email in self._users_by_email:
            raise AuthFlowError(
                "AUTH_EMAIL_EXISTS",
                "An account already exists. Sign in or reset your password.",
            )
        user = AuthUser(
            uuid4(),
            normalized_email,
            display_name.strip() if display_name else None,
            False,
        )
        record = _UserRecord(user, _hash_password(password))
        self._users_by_email[normalized_email] = record
        self._users_by_id[user.id] = record
        if not self.config.email_confirmation_required:
            verified_user = replace(user, email_verified=True)
            record.user = verified_user
            return VerificationChallenge(verified_user, None, None)
        token = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(seconds=self.config.verification_ttl_seconds)
        self._verification_tokens[token] = _ExpiringToken(user.id, expires_at)
        return VerificationChallenge(user, token, expires_at)

    def verify_email(self, token: str) -> AuthUser:
        challenge = self._verification_tokens.pop(token, None)
        if challenge is None:
            raise AuthFlowError("AUTH_VERIFICATION_INVALID", "This verification link is invalid.")
        if challenge.expires_at <= self._now():
            raise AuthFlowError("AUTH_VERIFICATION_EXPIRED", "This verification link has expired.")
        record = self._users_by_id.get(challenge.user_id)
        if record is None:
            raise AuthFlowError("AUTH_VERIFICATION_INVALID", "This verification link is invalid.")
        record.user = replace(record.user, email_verified=True)
        return record.user

    def sign_in(self, email: str, password: str) -> AuthSession:
        normalized_email = _normalize_email(email)
        record = self._users_by_email.get(normalized_email)
        if record is None or not _verify_password(password, record.password_hash):
            raise AuthFlowError("AUTH_INVALID_CREDENTIALS", "Email or password is incorrect.")
        if self.config.email_confirmation_required and not record.user.email_verified:
            raise AuthFlowError("AUTH_EMAIL_UNVERIFIED", "Verify your email before signing in.")
        return self._create_session(record.user)

    def sign_out(self, access_token: str) -> None:
        self._sessions.pop(access_token, None)

    def get_session(self, access_token: str) -> AuthSession:
        session = self._sessions.get(access_token)
        if session is None:
            raise AuthFlowError("AUTH_SESSION_INVALID", "Your session is no longer valid.")
        if session.expires_at <= self._now():
            del self._sessions[access_token]
            raise AuthFlowError("AUTH_SESSION_EXPIRED", "Your session has expired.")
        current_record = self._users_by_id.get(session.user.id)
        if current_record is None:
            del self._sessions[access_token]
            raise AuthFlowError("AUTH_SESSION_INVALID", "Your session is no longer valid.")
        return replace(session, user=current_record.user)

    def request_password_reset(self, email: str) -> PasswordResetChallenge:
        normalized_email = _normalize_email(email)
        record = self._users_by_email.get(normalized_email)
        if record is None:
            # The caller can always show the same response, preventing enumeration.
            return PasswordResetChallenge(normalized_email, None, None)
        token = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(seconds=self.config.password_reset_ttl_seconds)
        self._password_reset_tokens[token] = _ExpiringToken(record.user.id, expires_at)
        return PasswordResetChallenge(normalized_email, token, expires_at)

    def reset_password(self, token: str, new_password: str) -> AuthUser:
        _validate_password(new_password)
        challenge = self._password_reset_tokens.pop(token, None)
        if challenge is None:
            raise AuthFlowError("AUTH_RESET_INVALID", "This password reset link is invalid.")
        if challenge.expires_at <= self._now():
            raise AuthFlowError("AUTH_RESET_EXPIRED", "This password reset link has expired.")
        record = self._users_by_id.get(challenge.user_id)
        if record is None:
            raise AuthFlowError("AUTH_RESET_INVALID", "This password reset link is invalid.")
        record.password_hash = _hash_password(new_password)
        record.user = replace(record.user, email_verified=True)
        self._invalidate_sessions(record.user.id)
        return record.user

    def start_oauth(self, provider: str, redirect_uri: str) -> OAuthAuthorization:
        normalized_provider = provider.strip().lower()
        if not self.config.is_oauth_provider_supported(normalized_provider):
            raise AuthFlowError(
                "AUTH_OAUTH_PROVIDER_UNSUPPORTED",
                "This sign-in provider is unavailable.",
            )
        try:
            normalized_redirect = self.config.assert_redirect_allowed(redirect_uri)
        except ValueError as error:
            raise AuthFlowError(
                "AUTH_REDIRECT_NOT_ALLOWED",
                "This callback URL is not allowed.",
            ) from error
        state = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(minutes=10)
        self._oauth_states[state] = _OAuthState(
            normalized_provider,
            normalized_redirect,
            expires_at,
        )
        return OAuthAuthorization(normalized_provider, normalized_redirect, state, expires_at)

    def complete_oauth(
        self,
        state: str,
        email: str,
        display_name: str | None = None,
    ) -> AuthSession:
        oauth_state = self._oauth_states.pop(state, None)
        if oauth_state is None or oauth_state.expires_at <= self._now():
            raise AuthFlowError("AUTH_OAUTH_STATE_INVALID", "The sign-in request has expired.")
        normalized_email = _normalize_email(email)
        record = self._users_by_email.get(normalized_email)
        if record is None:
            user = AuthUser(uuid4(), normalized_email, display_name, True)
            record = _UserRecord(user, _hash_password(secrets.token_urlsafe(32)))
            self._users_by_email[normalized_email] = record
            self._users_by_id[user.id] = record
        elif not record.user.email_verified:
            record.user = replace(record.user, email_verified=True)
        return self._create_session(record.user)

    def _create_session(self, user: AuthUser) -> AuthSession:
        token = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(seconds=self.config.session_ttl_seconds)
        session = AuthSession(token, user, expires_at)
        self._sessions[token] = session
        return session

    def _invalidate_sessions(self, user_id: UUID) -> None:
        expired_tokens = [
            token for token, session in self._sessions.items() if session.user.id == user_id
        ]
        for token in expired_tokens:
            del self._sessions[token]
