from __future__ import annotations

from argparse import Namespace

import httpx
import pytest
from scripts.pilot_release_preflight import _evidence_checks
from scripts.pilot_smoke import SmokeFailure, _credential_headers, _data, _validate


def valid_evidence(head: str) -> dict[str, object]:
    digest = "a" * 64
    return {
        "release": {
            "commit_sha": head,
            "ci_conclusion": "success",
            "ci_run_url": "https://github.com/example/project/actions/runs/123",
        },
        "deployment": {
            "environment": "staging",
            "provider": "provider",
            "api_image_digest": f"sha256:{digest}",
            "web_image_digest": f"sha256:{digest}",
            "worker_image_digest": f"sha256:{digest}",
        },
        "backup": {"achieved_rpo_minutes": 10, "achieved_rto_minutes": 120},
        "smoke": {
            "status": "pass",
            "consent_confirmed": True,
            "output_sha256": digest,
        },
        "metrics": {
            "api_read_p95_ms": 100,
            "platform_failure_rate": 0.01,
            "signed_url_ttl_seconds": 600,
        },
        "rollback": {"status": "pass", "previous_release_ref": "v0.0.1"},
        "approvals": {
            "release_owner": "owner",
            "security_reviewer": "security",
            "privacy_reviewer": "privacy",
        },
    }


def test_pilot_evidence_requires_every_release_gate() -> None:
    head = "b" * 40
    checks = _evidence_checks(valid_evidence(head), head)
    assert checks
    assert all(check.passed for check in checks)

    evidence = valid_evidence(head)
    evidence["smoke"] = {"status": "blocked", "consent_confirmed": False}
    failed = _evidence_checks(evidence, head)
    assert {check.name for check in failed if not check.passed} == {
        "evidence:smoke.status",
        "evidence:smoke.consent_confirmed",
        "evidence:smoke.output_sha256",
    }


def test_smoke_requires_explicit_consent_and_https() -> None:
    arguments = Namespace(
        confirm_consent=False,
        api_base_url="https://api.example.test",
        workspace_id="00000000-0000-0000-0000-000000000001",
        voice_profile_id="00000000-0000-0000-0000-000000000002",
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256="a" * 64,
        timeout_seconds=180,
        poll_seconds=2.0,
    )
    with pytest.raises(SmokeFailure, match="confirm-consent"):
        _validate(arguments)

    arguments.confirm_consent = True
    arguments.api_base_url = "http://api.example.test"
    with pytest.raises(SmokeFailure, match="HTTPS"):
        _validate(arguments)


def test_smoke_credentials_are_environment_only_and_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLASSVOICE_PILOT_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("CLASSVOICE_PILOT_API_KEY", raising=False)
    with pytest.raises(SmokeFailure, match="exactly one"):
        _credential_headers()

    monkeypatch.setenv("CLASSVOICE_PILOT_BEARER_TOKEN", "test-bearer")
    monkeypatch.setenv("CLASSVOICE_PILOT_API_KEY", "test-api-key")
    with pytest.raises(SmokeFailure, match="exactly one"):
        _credential_headers()


def test_smoke_error_does_not_echo_remote_message_or_payload() -> None:
    response = httpx.Response(
        401,
        json={"error": {"code": "AUTH_FAILED", "message": "private remote detail"}},
    )
    with pytest.raises(SmokeFailure) as captured:
        _data(response, "generation create")
    assert "AUTH_FAILED" in str(captured.value)
    assert "private remote detail" not in str(captured.value)
