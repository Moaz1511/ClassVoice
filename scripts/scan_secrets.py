"""Fail CI when tracked content or Git history contains likely credentials.

The scanner deliberately reports only rule, path, line, and commit. It never
prints the suspected value. High-confidence provider formats are complemented
by a conservative assigned-secret rule with explicit placeholder handling.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2_000_000

HIGH_CONFIDENCE_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
)

SECRET_NAME = (
    r"(?:[A-Z0-9_]*(?:_SECRET|_PASSWORD|_PASSWD|_TOKEN|_API_KEY|_ACCESS_KEY)"
    r"|SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|ACCESS_KEY)"
)
ASSIGNED_SECRET_RULES = (
    re.compile(rf"(?i)(['\"]){SECRET_NAME}\1\s*[:=]\s*(['\"])([^'\"]{{8,}})\2"),
    re.compile(rf"(?i)\b{SECRET_NAME}\b\s*=\s*(['\"])([^'\"]{{8,}})\1"),
)
ENV_SECRET = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|ACCESS_KEY)"
    r"[A-Z0-9_]*\s*=\s*([^\s#]{8,})"
)
URL_CREDENTIAL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]+)@")

SAFE_VALUE_MARKERS = (
    "replace-with-",
    "change-me",
    "local-only",
    "minioadmin",
    "test-",
    "test_",
    "synthetic",
    "example",
    "do-not-store",
    "jwt-secret-from-secret-store",
    "security-integration-jwt-secret",
    "redacted",
    "placeholder",
    "your-",
    "${",
    "{{",
    "<",
)


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    path: str
    line: int
    commit: str | None = None


def _git(*args: str) -> bytes:
    process = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def _safe_value(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return normalized in {"test", "none", "null", "false"} or any(
        marker in normalized for marker in SAFE_VALUE_MARKERS
    )


def _scan_line(path: str, line_number: int, line: str, commit: str | None) -> list[Finding]:
    findings: list[Finding] = []
    for rule, pattern in HIGH_CONFIDENCE_RULES:
        if pattern.search(line):
            findings.append(Finding(rule, path, line_number, commit))

    for assigned_pattern in ASSIGNED_SECRET_RULES:
        assigned = assigned_pattern.search(line)
        if assigned and not _safe_value(assigned.groups()[-1]):
            findings.append(Finding("assigned-secret", path, line_number, commit))
            break

    if Path(path).name.startswith(".env"):
        env_value = ENV_SECRET.search(line)
        if env_value and not _safe_value(env_value.group(1)):
            findings.append(Finding("environment-secret", path, line_number, commit))

    url_value = URL_CREDENTIAL.search(line)
    if url_value and not _safe_value(url_value.group(1)):
        findings.append(Finding("url-credential", path, line_number, commit))
    return findings


def scan_worktree() -> list[Finding]:
    findings: list[Finding] = []
    for raw_path in _git("ls-files", "-z").split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="strict")
        path = ROOT / relative
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        if len(data) > MAX_TEXT_BYTES or b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            findings.extend(_scan_line(relative, number, line, None))
    return findings


def scan_history() -> list[Finding]:
    patch = _git(
        "log",
        "--all",
        "--no-ext-diff",
        "--no-renames",
        "--unified=0",
        "--format=commit:%H",
        "--",
        ".",
        ":(exclude)package-lock.json",
        ":(exclude)packages/api-client/openapi.json",
    ).decode("utf-8", errors="replace")
    findings: list[Finding] = []
    commit: str | None = None
    path = "unknown"
    new_line = 0
    for line in patch.splitlines():
        if line.startswith("commit:"):
            commit = line.removeprefix("commit:")[:12]
        elif line.startswith("+++ b/"):
            path = line.removeprefix("+++ b/")
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            findings.extend(_scan_line(path, new_line, line[1:], commit))
            new_line += 1
        elif not line.startswith("-"):
            new_line += 1
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan tracked files for likely secrets.")
    parser.add_argument("--history", action="store_true", help="also scan lines added in Git history")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    findings = scan_worktree()
    if args.history:
        findings.extend(scan_history())
    unique = sorted(
        set(findings),
        key=lambda item: (item.path, item.line, item.rule, item.commit or ""),
    )

    if args.json:
        print(json.dumps({"status": "fail" if unique else "pass", "findings": [asdict(item) for item in unique]}))
    elif unique:
        print(f"Secret scan failed with {len(unique)} redacted finding(s):")
        for item in unique:
            location = f"{item.path}:{item.line}"
            if item.commit:
                location = f"{location} (commit {item.commit})"
            print(f"- {item.rule}: {location}")
    else:
        scope = "tracked files and Git history" if args.history else "tracked files"
        print(f"Secret scan passed: no likely credentials in {scope}.")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
