"""Run the authenticated, consent-confirmed pilot generation smoke flow.

The script never accepts credentials on the command line, never prints signed
URLs or raw identifiers, and never writes generated audio to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

_SYNTHETIC_TEXT = (
    "This is a synthetic ClassVoice pilot lesson. Water changes between solid, "
    "liquid, and gas as thermal energy changes. This text contains no student data."
)
_TERMINAL_FAILURES = frozenset({"failed", "canceled"})


class SmokeFailure(RuntimeError):
    """A bounded pilot-smoke failure safe to print in operator evidence."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default=os.getenv("CLASSVOICE_PILOT_API_URL", ""))
    parser.add_argument("--workspace-id", default=os.getenv("CLASSVOICE_PILOT_WORKSPACE_ID", ""))
    parser.add_argument(
        "--voice-profile-id", default=os.getenv("CLASSVOICE_PILOT_VOICE_PROFILE_ID", "")
    )
    parser.add_argument("--model-key", default=os.getenv("CLASSVOICE_PILOT_MODEL_KEY", ""))
    parser.add_argument(
        "--model-version", default=os.getenv("CLASSVOICE_PILOT_MODEL_VERSION", "")
    )
    parser.add_argument(
        "--checkpoint-sha256", default=os.getenv("CLASSVOICE_PILOT_CHECKPOINT_SHA256", "")
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--confirm-consent",
        action="store_true",
        help="Confirm the selected synthetic/reference voice has active documented consent.",
    )
    return parser.parse_args()


def _credential_headers() -> dict[str, str]:
    bearer = os.getenv("CLASSVOICE_PILOT_BEARER_TOKEN", "").strip()
    api_key = os.getenv("CLASSVOICE_PILOT_API_KEY", "").strip()
    if bool(bearer) == bool(api_key):
        raise SmokeFailure(
            "Set exactly one of CLASSVOICE_PILOT_BEARER_TOKEN or CLASSVOICE_PILOT_API_KEY."
        )
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}
    return {"X-API-Key": api_key}


def _validate(arguments: argparse.Namespace) -> None:
    if not arguments.confirm_consent:
        raise SmokeFailure("--confirm-consent is required; the smoke flow cannot bypass consent.")
    if not arguments.api_base_url.startswith("https://"):
        raise SmokeFailure("Pilot API base URL must use HTTPS.")
    for name in ("workspace_id", "voice_profile_id"):
        try:
            UUID(getattr(arguments, name))
        except (TypeError, ValueError) as error:
            raise SmokeFailure(f"--{name.replace('_', '-')} must be a UUID.") from error
    if not arguments.model_key or not arguments.model_version:
        raise SmokeFailure("Model key and version are required.")
    sha = arguments.checkpoint_sha256.lower()
    if len(sha) != 64 or any(character not in "0123456789abcdef" for character in sha):
        raise SmokeFailure("Checkpoint SHA-256 must contain exactly 64 hexadecimal characters.")
    if not 30 <= arguments.timeout_seconds <= 600:
        raise SmokeFailure("Timeout must be between 30 and 600 seconds.")
    if not 0.5 <= arguments.poll_seconds <= 10:
        raise SmokeFailure("Poll interval must be between 0.5 and 10 seconds.")


def _data(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise SmokeFailure(f"{operation} returned non-JSON status {response.status_code}.") from error
    if response.is_error:
        error_code = "UNKNOWN"
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error_code = str(payload["error"].get("code", "UNKNOWN"))
        raise SmokeFailure(f"{operation} failed with status {response.status_code} ({error_code}).")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise SmokeFailure(f"{operation} returned an invalid API envelope.")
    return data


def run(arguments: argparse.Namespace) -> dict[str, object]:
    _validate(arguments)
    auth_headers = _credential_headers()
    api_url = arguments.api_base_url.rstrip("/")
    started = time.perf_counter()
    idempotency_key = f"pilot-smoke-{uuid4()}"
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        live = _data(client.get(f"{api_url}/health/live"), "liveness check")
        ready = _data(client.get(f"{api_url}/health/ready"), "readiness check")
        if live.get("status") != "ok" or ready.get("status") != "ready":
            raise SmokeFailure("Health endpoints did not report ok/ready.")

        body = {
            "workspace_id": arguments.workspace_id,
            "voice_profile_id": arguments.voice_profile_id,
            "input_text": _SYNTHETIC_TEXT,
            "language_code": "en-US",
            "output_format": "wav",
            "speed": 1.0,
            "stability": 0.5,
            "style": 0.0,
            "seed": 20261101,
            "model_key": arguments.model_key,
            "model_version": arguments.model_version,
            "checkpoint_sha256": arguments.checkpoint_sha256.lower(),
        }
        created = _data(
            client.post(
                f"{api_url}/v1/generations",
                headers={**auth_headers, "Idempotency-Key": idempotency_key},
                json=body,
            ),
            "generation create",
        )
        job_id = str(created.get("id", ""))
        try:
            UUID(job_id)
        except ValueError as error:
            raise SmokeFailure("Generation create did not return a valid job identifier.") from error

        deadline = time.monotonic() + arguments.timeout_seconds
        status = str(created.get("status", ""))
        job: dict[str, Any] = created
        while status not in {"succeeded", *_TERMINAL_FAILURES}:
            if time.monotonic() >= deadline:
                raise SmokeFailure("Generation did not reach a terminal state before timeout.")
            time.sleep(arguments.poll_seconds)
            job = _data(
                client.get(f"{api_url}/v1/generations/{job_id}", headers=auth_headers),
                "generation poll",
            )
            status = str(job.get("status", ""))
        if status != "succeeded":
            raise SmokeFailure(f"Generation reached terminal status {status!r}.")

        download_data = _data(
            client.get(f"{api_url}/v1/generations/{job_id}/download", headers=auth_headers),
            "signed download",
        )
        download = download_data.get("download")
        output = download_data.get("output")
        if not isinstance(download, dict) or not isinstance(output, dict):
            raise SmokeFailure("Signed download response is incomplete.")
        signed_url = download.get("url")
        method = download.get("method", "GET")
        signed_headers = download.get("headers", {})
        if not isinstance(signed_url, str) or not signed_url.startswith("https://"):
            raise SmokeFailure("Signed download URL is missing or does not use HTTPS.")
        if method != "GET" or not isinstance(signed_headers, dict):
            raise SmokeFailure("Signed download method or headers are invalid.")
        audio_response = client.get(
            signed_url,
            headers={str(key): str(value) for key, value in signed_headers.items()},
            timeout=60,
        )
        if audio_response.is_error:
            raise SmokeFailure(f"Private audio download failed with {audio_response.status_code}.")
        if not 44 <= len(audio_response.content) <= 25_000_000:
            raise SmokeFailure("Downloaded audio size is outside the accepted bounds.")
        checksum = hashlib.sha256(audio_response.content).hexdigest()
        if checksum != output.get("checksum_sha256"):
            raise SmokeFailure("Downloaded audio checksum does not match output provenance.")

    elapsed = round(time.perf_counter() - started, 3)
    return {
        "status": "pass",
        "completed_at": datetime.now(UTC).isoformat(),
        "consent_confirmed": True,
        "synthetic_text_sha256": hashlib.sha256(_SYNTHETIC_TEXT.encode()).hexdigest(),
        "generation_id_sha256": hashlib.sha256(job_id.encode()).hexdigest(),
        "output_sha256": checksum,
        "output_bytes": len(audio_response.content),
        "queue_to_download_seconds": elapsed,
        "model": {
            "key": arguments.model_key,
            "version": arguments.model_version,
            "checkpoint_sha256": arguments.checkpoint_sha256.lower(),
        },
    }


def main() -> int:
    try:
        result = run(_arguments())
    except (SmokeFailure, httpx.HTTPError) as error:
        print(json.dumps({"status": "fail", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
