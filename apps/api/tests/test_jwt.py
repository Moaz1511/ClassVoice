from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.auth_config import AuthConfig, AuthConfigurationError
from app.core.authorization import extract_bearer_token, require_authenticated
from app.core.jwt import AuthClaims, JWTVerificationError, JWTVerifier


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()


def make_token(secret: str, claims: dict[str, object], algorithm: str = "HS256") -> str:
    header = _segment({"alg": algorithm, "typ": "JWT"})
    payload = _segment(claims)
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def base_claims(clock: MutableClock) -> dict[str, object]:
    return {
        "iss": "https://project.supabase.co/auth/v1",
        "aud": "authenticated",
        "sub": str(uuid4()),
        "role": "authenticated",
        "iat": int(clock().timestamp()),
        "exp": int((clock() + timedelta(minutes=5)).timestamp()),
        "session_id": "session-123",
        "scope": "voices:read generations:create",
        "app_metadata": {"scopes": ["generations:read"]},
    }


def make_verifier(clock: MutableClock) -> JWTVerifier:
    return JWTVerifier(
        secret="test-jwt-secret",
        issuer="https://project.supabase.co/auth/v1",
        now=clock,
    )


def test_verifier_accepts_valid_supabase_claims_and_scopes() -> None:
    clock = MutableClock()
    token = make_token("test-jwt-secret", base_claims(clock))

    claims = make_verifier(clock).verify(token)

    assert isinstance(claims, AuthClaims)
    assert claims.audience == ("authenticated",)
    assert claims.scopes == frozenset({"voices:read", "generations:create", "generations:read"})
    assert claims.session_id == "session-123"


@pytest.mark.parametrize(
    ("claim", "value", "error_code"),
    [
        ("aud", "other-audience", "AUTH_TOKEN_AUDIENCE"),
        ("iss", "https://evil.example/auth/v1", "AUTH_TOKEN_ISSUER"),
        ("role", "service_role", "AUTH_TOKEN_ROLE_INVALID"),
    ],
)
def test_verifier_rejects_wrong_security_claims(
    claim: str,
    value: object,
    error_code: str,
) -> None:
    clock = MutableClock()
    claims = base_claims(clock)
    claims[claim] = value

    with pytest.raises(JWTVerificationError) as error:
        make_verifier(clock).verify(make_token("test-jwt-secret", claims))
    assert error.value.code == error_code


def test_verifier_rejects_expired_signature_algorithm_and_malformed_token() -> None:
    clock = MutableClock()
    expired = base_claims(clock)
    expired["exp"] = int((clock() - timedelta(minutes=5)).timestamp())
    with pytest.raises(JWTVerificationError) as expired_error:
        make_verifier(clock).verify(make_token("test-jwt-secret", expired))
    assert expired_error.value.code == "AUTH_TOKEN_EXPIRED"

    with pytest.raises(JWTVerificationError) as signature_error:
        make_verifier(clock).verify(make_token("wrong-secret", base_claims(clock)))
    assert signature_error.value.code == "AUTH_TOKEN_SIGNATURE"

    with pytest.raises(JWTVerificationError) as algorithm_error:
        make_verifier(clock).verify(make_token("test-jwt-secret", base_claims(clock), "none"))
    assert algorithm_error.value.code == "AUTH_TOKEN_ALGORITHM"

    with pytest.raises(JWTVerificationError) as malformed_error:
        make_verifier(clock).verify("not-a-jwt")
    assert malformed_error.value.code == "AUTH_TOKEN_MALFORMED"


def test_auth_header_and_config_dependency_reject_missing_or_misconfigured_tokens() -> None:
    with pytest.raises(JWTVerificationError) as missing:
        extract_bearer_token(None)
    assert missing.value.code == "AUTH_TOKEN_MISSING"
    with pytest.raises(JWTVerificationError) as invalid:
        extract_bearer_token("Basic abc")
    assert invalid.value.code == "AUTH_TOKEN_INVALID"

    clock = MutableClock()
    token = make_token("test-jwt-secret", base_claims(clock))
    claims = require_authenticated(f"Bearer {token}", make_verifier(clock))
    assert claims.subject

    with pytest.raises(AuthConfigurationError):
        JWTVerifier.from_config(AuthConfig())
