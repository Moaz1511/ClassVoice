"""Fail-closed static and evidence checks before a pilot tag may be created."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "private" / "pilot-release" / "evidence.json"
CHECKPOINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
sys.path.insert(0, str(ROOT / "apps" / "api"))


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--candidate", default="v0.1.0-pilot.1")
    return parser.parse_args()


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


def _nested(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _evidence_checks(evidence: dict[str, Any], head: str) -> list[Check]:
    required_values = {
        "release.commit_sha": lambda value: isinstance(value, str)
        and COMMIT_PATTERN.fullmatch(value) is not None
        and value == head,
        "release.ci_conclusion": lambda value: value == "success",
        "release.ci_run_url": lambda value: isinstance(value, str)
        and value.startswith("https://github.com/")
        and "/actions/runs/" in value,
        "deployment.environment": lambda value: value in {"staging", "production"},
        "deployment.provider": lambda value: isinstance(value, str) and len(value.strip()) >= 2,
        "deployment.api_image_digest": lambda value: isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71,
        "deployment.web_image_digest": lambda value: isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71,
        "deployment.worker_image_digest": lambda value: isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71,
        "backup.achieved_rpo_minutes": lambda value: isinstance(value, (int, float))
        and 0 <= value <= 15,
        "backup.achieved_rto_minutes": lambda value: isinstance(value, (int, float))
        and 0 < value <= 240,
        "smoke.status": lambda value: value == "pass",
        "smoke.consent_confirmed": lambda value: value is True,
        "smoke.output_sha256": lambda value: isinstance(value, str)
        and CHECKPOINT_PATTERN.fullmatch(value) is not None,
        "metrics.api_read_p95_ms": lambda value: isinstance(value, (int, float))
        and 0 <= value < 400,
        "metrics.platform_failure_rate": lambda value: isinstance(value, (int, float))
        and 0 <= value <= 0.05,
        "metrics.signed_url_ttl_seconds": lambda value: value == 600,
        "rollback.status": lambda value: value == "pass",
        "rollback.previous_release_ref": lambda value: isinstance(value, str)
        and bool(value.strip()),
        "approvals.release_owner": lambda value: isinstance(value, str)
        and value not in {"", "UNASSIGNED"},
        "approvals.security_reviewer": lambda value: isinstance(value, str)
        and value not in {"", "UNASSIGNED"},
        "approvals.privacy_reviewer": lambda value: isinstance(value, str)
        and value not in {"", "UNASSIGNED"},
    }
    checks: list[Check] = []
    for path, validator in required_values.items():
        value = _nested(evidence, path)
        checks.append(Check(f"evidence:{path}", bool(validator(value)), "present and valid"))
    return checks


def run(evidence_path: Path, candidate: str) -> dict[str, object]:
    checks: list[Check] = []
    head = ""
    try:
        head = _git("rev-parse", "HEAD")
        dirty = _git("status", "--porcelain")
        checks.append(Check("git:clean", not dirty, "working tree must be clean"))
        tag_match = _git("tag", "--list", candidate)
        checks.append(Check("git:tag-absent", not tag_match, f"candidate {candidate} must not exist"))
    except subprocess.CalledProcessError:
        checks.append(Check("git:repository", False, "Git repository check failed"))

    manifest = _load_json(ROOT / "infra" / "model-registry" / "manifest.json")
    entries = manifest.get("models", manifest.get("entries", []))
    approved_enabled = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("license_review_status") == "approved"
        and entry.get("enabled") is True
        and isinstance(entry.get("checkpoint_sha256"), str)
        and CHECKPOINT_PATTERN.fullmatch(str(entry["checkpoint_sha256"]).lower())
    ]
    checks.append(
        Check(
            "model:approved-enabled",
            bool(approved_enabled),
            "an approved checksum-pinned model must be enabled",
        )
    )

    incident_text = (ROOT / "docs" / "security" / "INCIDENT_RESPONSE.md").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "operations:incident-contacts",
            "UNASSIGNED" not in incident_text,
            "incident, privacy, provider, and communication owners must be assigned",
        )
    )
    checks.append(
        Check(
            "decision:hosting",
            (ROOT / "docs" / "decisions" / "ADR-002_Pilot_Hosting.md").is_file(),
            "pilot hosting/provider/network decision is required",
        )
    )
    checks.append(
        Check(
            "decision:long-text",
            (ROOT / "docs" / "decisions" / "ADR-003_Long_Text_Inference.md").is_file(),
            "the P4-06 long-text GPU gap requires an accepted decision",
        )
    )

    from app.core.settings import APISettings, SettingsError

    hosted = APISettings(
        app_env="staging",
        database_url="postgresql+asyncpg://classvoice:placeholder@db.internal/classvoice",
        redis_url="rediss://redis.internal:6379/0",
        rate_limit_backend="redis",
        s3_endpoint="https://storage.example.edu",
        s3_access_key_id="placeholder-hosted-access",
        s3_secret_access_key="placeholder-hosted-secret",
        cors_origins=("https://classvoice.example.edu",),
    )
    try:
        hosted.validate()
    except SettingsError as error:
        checks.append(Check("runtime:hosted-startup", False, str(error)))
    else:
        checks.append(Check("runtime:hosted-startup", True, "hosted settings validate"))

    if evidence_path.is_file():
        try:
            evidence = _load_json(evidence_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            checks.append(Check("evidence:file", False, f"invalid evidence file: {error}"))
        else:
            checks.append(Check("evidence:file", True, "operator evidence loaded"))
            checks.extend(_evidence_checks(evidence, head))
    else:
        checks.append(Check("evidence:file", False, f"missing {evidence_path}"))

    passed = all(check.passed for check in checks)
    return {
        "status": "pass" if passed else "blocked",
        "candidate": candidate,
        "head": head,
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    arguments = _arguments()
    try:
        result = run(arguments.evidence.resolve(), arguments.candidate)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result = {"status": "blocked", "error": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
