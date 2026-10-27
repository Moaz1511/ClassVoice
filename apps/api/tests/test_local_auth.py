from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.auth_config import AuthConfig
from app.core.local_auth import AuthFlowError, LocalAuthProvider


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 28, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def make_provider(clock: MutableClock | None = None) -> LocalAuthProvider:
    config = AuthConfig(
        verification_ttl_seconds=60,
        password_reset_ttl_seconds=60,
        session_ttl_seconds=60,
    )
    return LocalAuthProvider(config, now=clock)


def test_sign_up_verify_sign_in_and_sign_out() -> None:
    provider = make_provider()

    pending = provider.sign_up("Teacher@Example.com", "StrongPassword123!", "Teacher")
    with pytest.raises(AuthFlowError, match="Verify your email") as unverified:
        provider.sign_in("teacher@example.com", "StrongPassword123!")
    assert unverified.value.code == "AUTH_EMAIL_UNVERIFIED"

    assert pending.token is not None
    verified = provider.verify_email(pending.token)
    assert verified.email_verified is True
    session = provider.sign_in("teacher@example.com", "StrongPassword123!")
    assert provider.get_session(session.access_token).user.id == verified.id

    provider.sign_out(session.access_token)
    with pytest.raises(AuthFlowError) as signed_out:
        provider.get_session(session.access_token)
    assert signed_out.value.code == "AUTH_SESSION_INVALID"


def test_password_reset_invalidates_sessions_and_expired_sessions_are_rejected() -> None:
    clock = MutableClock()
    provider = make_provider(clock)
    pending = provider.sign_up("student@example.com", "StrongPassword123!")
    assert pending.token is not None
    provider.verify_email(pending.token)
    session = provider.sign_in("student@example.com", "StrongPassword123!")

    reset = provider.request_password_reset("student@example.com")
    assert reset.token is not None
    provider.reset_password(reset.token, "NewStrongPassword123!")
    with pytest.raises(AuthFlowError) as reset_session:
        provider.get_session(session.access_token)
    assert reset_session.value.code == "AUTH_SESSION_INVALID"
    fresh_session = provider.sign_in("student@example.com", "NewStrongPassword123!")

    clock.advance(seconds=61)
    with pytest.raises(AuthFlowError) as expired_session:
        provider.get_session(fresh_session.access_token)
    assert expired_session.value.code == "AUTH_SESSION_EXPIRED"

    # A reset token is single-use, even after the session expiry window.
    with pytest.raises(AuthFlowError) as expired_reset:
        provider.reset_password(reset.token, "AnotherStrongPassword123!")
    assert expired_reset.value.code == "AUTH_RESET_INVALID"


def test_oauth_callback_allowlist_and_state_expiry() -> None:
    clock = MutableClock()
    provider = make_provider(clock)
    authorization = provider.start_oauth("google", "http://localhost:3000/auth/callback")
    session = provider.complete_oauth(authorization.state, "oauth@example.com", "OAuth User")
    assert session.user.email_verified is True

    with pytest.raises(AuthFlowError) as replay:
        provider.complete_oauth(authorization.state, "oauth@example.com")
    assert replay.value.code == "AUTH_OAUTH_STATE_INVALID"

    with pytest.raises(AuthFlowError) as blocked:
        provider.start_oauth("google", "https://evil.example/callback")
    assert blocked.value.code == "AUTH_REDIRECT_NOT_ALLOWED"

    expired = provider.start_oauth("github", "http://localhost:3000/auth/callback")
    clock.advance(minutes=11)
    with pytest.raises(AuthFlowError) as expired_state:
        provider.complete_oauth(expired.state, "expired@example.com")
    assert expired_state.value.code == "AUTH_OAUTH_STATE_INVALID"


def test_password_reset_for_unknown_email_is_non_enumerating() -> None:
    challenge = make_provider().request_password_reset("missing@example.com")

    assert challenge.token is None
    assert challenge.expires_at is None
