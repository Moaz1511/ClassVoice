"""P4-06 control-plane load profile.

The harness exercises the real FastAPI route/dependency stack through HTTPX's
ASGI transport. It deliberately uses synthetic text and an in-memory private
storage adapter so no credential, source text, audio sample, or object key is
written to the report. Real OpenVoice/CUDA timing is handled by the separate
``p4_06_openvoice_gpu.py`` process.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import math
import platform
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from app.core.authorization import InMemoryMembershipStore, WorkspaceMembership
from app.core.settings import APISettings
from app.domains.generations.jobs import GenerationService
from app.domains.generations.outputs import PrivateGenerationOutputStore
from app.domains.voices.lifecycle import VoiceReadiness
from app.inference.adapter import (
    InferenceAdapter,
    InferenceRequest,
    InferenceResult,
    SmokeCpuAdapter,
)
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.main import create_app
from app.storage.ports import SignedObjectUrl
from app.storage.s3 import S3StorageAdapter
from app.workers.generation_queue import GenerationWorker, InMemoryGenerationQueue
from fastapi import FastAPI

JWT_SECRET = "p4-06-synthetic-jwt-secret"
JWT_ISSUER = "https://load-test.invalid/auth/v1"
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000601")
MODEL_SHA = "6" * 64
MAX_TEXT = "A" * 10_000


@dataclass(frozen=True, slots=True)
class LatencySummary:
    name: str
    requests: int
    failures: int
    elapsed_ms: float
    requests_per_second: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    threshold_ms: float
    status: str


@dataclass(frozen=True, slots=True)
class QueueSummary:
    jobs: int
    worker_concurrency: int
    observed_max_concurrency: int
    terminal_successes: int
    output_writes: int
    elapsed_ms: float
    jobs_per_second: float
    p95_queue_to_complete_ms: float
    threshold_ms: float
    status: str


class SyntheticPrivateStorage:
    """Private storage test double that never reports its object keys."""

    def __init__(self) -> None:
        self.output_writes = 0
        self.sign_calls = 0
        self._signer = S3StorageAdapter(APISettings.from_env({}))

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
    ) -> None:
        if bucket != "generated-audio" or not key or not body:
            raise AssertionError("synthetic private output was invalid")
        if content_type not in {"audio/wav", "audio/mpeg"}:
            raise AssertionError("synthetic output content type was invalid")
        self.output_writes += 1

    async def create_upload_url(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
    ) -> SignedObjectUrl:
        raise AssertionError("upload signing is outside the P4-06 profile")

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl:
        if bucket != "generated-audio" or not key:
            raise AssertionError("download signing target was invalid")
        self.sign_calls += 1
        return await self._signer.create_download_url(bucket, key)


class TrackingAdapter(InferenceAdapter):
    """Bounded async inference stand-in used only for queue pressure."""

    def __init__(self, result: InferenceResult, delay_seconds: float = 0.02) -> None:
        self._result = result
        self._delay_seconds = delay_seconds
        self._active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        if len(request.input_text) != 10_000:
            raise AssertionError("queue profile did not receive the maximum text boundary")
        async with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            await asyncio.sleep(self._delay_seconds)
            return self._result
        finally:
            async with self._lock:
                self._active -= 1


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return a nearest-rank percentile for a non-empty sample."""

    if not values:
        raise ValueError("percentile sample cannot be empty")
    if quantile <= 0 or quantile > 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _latency_summary(
    name: str,
    latencies_ms: Sequence[float],
    failures: int,
    elapsed_ms: float,
    threshold_ms: float,
) -> LatencySummary:
    samples = tuple(latencies_ms) or (elapsed_ms,)
    passed = failures == 0 and percentile(samples, 0.95) < threshold_ms
    return LatencySummary(
        name=name,
        requests=len(latencies_ms),
        failures=failures,
        elapsed_ms=round(elapsed_ms, 3),
        requests_per_second=round(len(latencies_ms) / max(elapsed_ms / 1000, 0.000_001), 3),
        p50_ms=round(percentile(samples, 0.50), 3),
        p95_ms=round(percentile(samples, 0.95), 3),
        p99_ms=round(percentile(samples, 0.99), 3),
        max_ms=round(max(samples), 3),
        threshold_ms=threshold_ms,
        status="pass" if passed else "fail",
    )


def _jwt(user_id: UUID) -> str:
    now = datetime.now(UTC)

    def segment(value: object) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()

    header = segment({"alg": "HS256", "typ": "JWT"})
    payload = segment(
        {
            "aud": "authenticated",
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": JWT_ISSUER,
            "role": "authenticated",
            "scope": "generations:read generations:create",
            "sub": str(user_id),
        }
    )
    signed = f"{header}.{payload}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signed, hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _app() -> tuple[FastAPI, UUID, SyntheticPrivateStorage]:
    user_id = uuid4()
    app = create_app(
        APISettings.from_env(
            {
                "SUPABASE_JWT_SECRET": JWT_SECRET,
                "SUPABASE_JWT_ISSUER": JWT_ISSUER,
            }
        )
    )
    app.state.membership_store = InMemoryMembershipStore(
        (WorkspaceMembership(WORKSPACE_ID, user_id, "editor"),)
    )
    entry = ModelManifestEntry(
        model_key="openvoice-v2",
        version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        checkpoint_path="synthetic-checkpoint.bin",
        runtime="load-test",
        license_name="Synthetic fixture",
        license_url=None,
        license_review_status="approved",
        supported_languages=("en-US",),
        config={"sample_rate_hz": 24_000},
        enabled=True,
    )
    app.state.model_registry = ModelRegistry(ModelManifest(1, (entry,)))
    app.state.generation_service = GenerationService(
        app.state.generation_store,
        app.state.voice_service,
        app.state.model_registry,
    )
    app.state.generation_queue = InMemoryGenerationQueue()
    app.state.generation_worker = GenerationWorker(
        app.state.generation_service,
        app.state.generation_queue,
    )
    storage = SyntheticPrivateStorage()
    app.state.storage_adapter = storage
    app.state.generation_outputs = PrivateGenerationOutputStore(storage)
    return app, user_id, storage


async def _ready_voice(app: FastAPI, user_id: UUID) -> UUID:
    voice = await app.state.voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        name="Synthetic benchmark voice",
        language_code="en-US",
        consent_statement_version="p4-06",
        consent_attestation_text_hash="6" * 64,
        reference_upload_id=None,
        idempotency_key=f"p4-06-voice-{uuid4().hex}",
    )
    await app.state.voice_service.transition(voice.id, user_id, "validating")
    await app.state.voice_service.transition(voice.id, user_id, "processing")
    await app.state.voice_service.transition(
        voice.id,
        user_id,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    return voice.id


def _generation_body(voice_id: UUID, input_text: str) -> dict[str, object]:
    return {
        "workspace_id": str(WORKSPACE_ID),
        "voice_profile_id": str(voice_id),
        "input_text": input_text,
        "language_code": "en-US",
        "output_format": "wav",
        "speed": 1.0,
        "stability": 0.5,
        "style": 0.2,
        "seed": 606,
        "model_key": "openvoice-v2",
        "model_version": "2.0.0",
        "checkpoint_sha256": MODEL_SHA,
    }


async def _complete_fixture_job(app: FastAPI, user_id: UUID, voice_id: UUID) -> UUID:
    job = await app.state.generation_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=user_id,
        voice_profile_id=voice_id,
        project_id=None,
        input_text="Synthetic load fixture.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=0.5,
        style=0.2,
        seed=606,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key=f"p4-06-fixture-{uuid4().hex}",
    )
    await app.state.generation_worker.publish(job.id, user_id)
    lease = await app.state.generation_worker.claim_next(user_id)
    if lease is None:
        raise RuntimeError("fixture generation could not be claimed")
    completed, _ = await app.state.generation_worker.execute(
        lease.lease_id,
        user_id,
        SmokeCpuAdapter(),
        app.state.generation_outputs,
    )
    if completed.status != "succeeded":
        raise RuntimeError("fixture generation did not succeed")
    return job.id


RequestOperation = Callable[[httpx.AsyncClient, int], Awaitable[bool]]


async def _measure_http(
    *,
    client: httpx.AsyncClient,
    name: str,
    requests: int,
    concurrency: int,
    threshold_ms: float,
    operation: RequestOperation,
) -> LatencySummary:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures = 0

    async def one(index: int) -> None:
        nonlocal failures
        async with semaphore:
            started = time.perf_counter()
            try:
                if not await operation(client, index):
                    failures += 1
            except Exception:
                failures += 1
            finally:
                latencies.append((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    await asyncio.gather(*(one(index) for index in range(requests)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return _latency_summary(name, latencies, failures, elapsed_ms, threshold_ms)


async def _api_scenarios(
    read_requests: int,
    signed_url_requests: int,
    concurrency: int,
) -> tuple[LatencySummary, LatencySummary]:
    app, user_id, storage = _app()
    voice_id = await _ready_voice(app, user_id)
    job_id = await _complete_fixture_job(app, user_id, voice_id)
    headers = {"Authorization": f"Bearer {_jwt(user_id)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://p4-06.invalid",
    ) as client:

        async def read_operation(http_client: httpx.AsyncClient, index: int) -> bool:
            if index % 2 == 0:
                response = await http_client.get(
                    "/v1/generations",
                    params={"workspace_id": str(WORKSPACE_ID)},
                    headers=headers,
                )
                payload = response.json()
                items = payload.get("data", {}).get("items", [])
                return response.status_code == 200 and bool(items) and "input_text" not in items[0]
            response = await http_client.get(f"/v1/generations/{job_id}", headers=headers)
            return response.status_code == 200 and response.json().get("data", {}).get("id") == str(
                job_id
            )

        async def signed_operation(http_client: httpx.AsyncClient, _index: int) -> bool:
            response = await http_client.get(
                f"/v1/generations/{job_id}/download",
                headers=headers,
            )
            payload = response.json().get("data", {})
            output = payload.get("output", {})
            download = payload.get("download", {})
            return (
                response.status_code == 200
                and "object_key" not in output
                and download.get("method") == "GET"
                and "X-Amz-Signature=" in str(download.get("url", ""))
            )

        reads = await _measure_http(
            client=client,
            name="authenticated_api_reads",
            requests=read_requests,
            concurrency=concurrency,
            threshold_ms=400,
            operation=read_operation,
        )
        signed = await _measure_http(
            client=client,
            name="authorized_signed_url_reads",
            requests=signed_url_requests,
            concurrency=concurrency,
            threshold_ms=400,
            operation=signed_operation,
        )
    if storage.sign_calls != signed_url_requests:
        raise RuntimeError("signed URL call count did not match successful requests")
    return reads, signed


async def _max_text_and_queue_scenarios(
    jobs: int,
    worker_concurrency: int,
) -> tuple[LatencySummary, QueueSummary]:
    app, user_id, storage = _app()
    voice_id = await _ready_voice(app, user_id)
    headers = {"Authorization": f"Bearer {_jwt(user_id)}"}
    body = _generation_body(voice_id, MAX_TEXT)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://p4-06.invalid",
    ) as client:

        async def create_operation(http_client: httpx.AsyncClient, index: int) -> bool:
            response = await http_client.post(
                "/v1/generations",
                headers={**headers, "Idempotency-Key": f"p4-06-max-{index:06d}"},
                json=body,
            )
            data = response.json().get("data", {})
            return response.status_code == 202 and data.get("status") == "queued"

        creates = await _measure_http(
            client=client,
            name="maximum_text_generation_acceptance",
            requests=jobs,
            concurrency=worker_concurrency,
            threshold_ms=400,
            operation=create_operation,
        )

    template_request = InferenceRequest(
        job_id=uuid4(),
        input_text=MAX_TEXT,
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=0.5,
        style=0.2,
        seed=606,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        model_metadata={},
    )
    template_result = await SmokeCpuAdapter().generate(template_request)
    adapter = TrackingAdapter(template_result)
    terminal_jobs: list[UUID] = []
    queue_latencies_ms: list[float] = []

    async def consume() -> None:
        while True:
            lease = await app.state.generation_worker.claim_next(user_id)
            if lease is None:
                return
            completed, result = await app.state.generation_worker.execute(
                lease.lease_id,
                user_id,
                adapter,
                app.state.generation_outputs,
            )
            if completed.status == "succeeded" and result is not None:
                terminal_jobs.append(completed.id)
                if completed.completed_at is not None:
                    queue_latencies_ms.append(
                        (completed.completed_at - completed.created_at).total_seconds() * 1000
                    )

    started = time.perf_counter()
    await asyncio.gather(*(consume() for _ in range(worker_concurrency)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    queue_p95 = percentile(queue_latencies_ms, 0.95) if queue_latencies_ms else elapsed_ms
    queue_passed = (
        creates.failures == 0
        and len(set(terminal_jobs)) == jobs
        and storage.output_writes == jobs
        and adapter.max_active <= worker_concurrency
        and adapter.max_active == min(worker_concurrency, jobs)
        and queue_p95 < 90_000
    )
    queue = QueueSummary(
        jobs=jobs,
        worker_concurrency=worker_concurrency,
        observed_max_concurrency=adapter.max_active,
        terminal_successes=len(set(terminal_jobs)),
        output_writes=storage.output_writes,
        elapsed_ms=round(elapsed_ms, 3),
        jobs_per_second=round(jobs / max(elapsed_ms / 1000, 0.000_001), 3),
        p95_queue_to_complete_ms=round(queue_p95, 3),
        threshold_ms=90_000,
        status="pass" if queue_passed else "fail",
    )
    return creates, queue


async def run_profile(
    *,
    read_requests: int = 200,
    signed_url_requests: int = 100,
    queue_jobs: int = 24,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Run the synthetic control-plane profile and return redacted metrics."""

    if min(read_requests, signed_url_requests, queue_jobs, concurrency) < 1:
        raise ValueError("load profile counts and concurrency must be positive")
    reads, signed = await _api_scenarios(read_requests, signed_url_requests, concurrency)
    maximum_text, queue = await _max_text_and_queue_scenarios(queue_jobs, concurrency)
    control_plane_status = (
        "pass"
        if all(
            summary.status == "pass"
            for summary in (reads, signed, maximum_text, queue)
        )
        else "fail"
    )
    return {
        "schema_version": 1,
        "profile": "p4-06-control-plane-asgi",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "transport": "httpx-asgi",
            "storage": "boto3-sigv4-local-signing-with-synthetic-private-writes",
            "inference": "bounded-smoke-adapter",
        },
        "workload": {
            "read_requests": read_requests,
            "signed_url_requests": signed_url_requests,
            "maximum_text_characters": 10_000,
            "queue_jobs": queue_jobs,
            "worker_concurrency": concurrency,
        },
        "targets": {
            "api_read_p95_ms": 400,
            "queue_to_complete_proxy_p95_ms": 90_000,
        },
        "results": {
            "api_reads": asdict(reads),
            "signed_urls": asdict(signed),
            "maximum_text_acceptance": asdict(maximum_text),
            "queue_concurrency": asdict(queue),
        },
        "control_plane_status": control_plane_status,
        "gpu_status": "requires-separate-reference-gpu-run",
        "limitations": [
            "ASGI measurements exclude network and reverse-proxy latency.",
            "Queue timing uses a bounded synthetic adapter and is not an OpenVoice GPU result.",
            "No source text, audio bytes, credentials, signed URL, or object key is reported.",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the P4-06 control-plane load profile.")
    parser.add_argument("--read-requests", type=int, default=200)
    parser.add_argument("--signed-url-requests", type=int, default=100)
    parser.add_argument("--queue-jobs", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = asyncio.run(
        run_profile(
            read_requests=args.read_requests,
            signed_url_requests=args.signed_url_requests,
            queue_jobs=args.queue_jobs,
            concurrency=args.concurrency,
        )
    )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["control_plane_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
