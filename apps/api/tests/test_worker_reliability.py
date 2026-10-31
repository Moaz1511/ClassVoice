from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.domains.generations.jobs import (
    GenerationError,
    GenerationJob,
    GenerationService,
    InMemoryGenerationStore,
)
from app.domains.voices.lifecycle import (
    InMemoryVoiceStore,
    VoiceLifecycleService,
    VoiceReadiness,
)
from app.inference.adapter import (
    InferenceError,
    InferenceRequest,
    InferenceResult,
    SmokeCpuAdapter,
)
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.inference.openvoice import OpenVoiceV2Adapter
from app.workers.generation_queue import (
    GenerationWorker,
    InMemoryGenerationLeaseStore,
    InMemoryGenerationQueue,
)

pytestmark = pytest.mark.asyncio

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000102")
WORKER_A = UUID("00000000-0000-0000-0000-000000000103")
WORKER_B = UUID("00000000-0000-0000-0000-000000000104")
MODEL_SHA = "a" * 64
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})


class RecordingOutputSink:
    def __init__(self) -> None:
        self.put_calls = 0
        self.results: dict[UUID, InferenceResult] = {}

    async def put(self, job: GenerationJob, result: InferenceResult) -> object:
        self.put_calls += 1
        previous = self.results.get(job.id)
        if previous is not None and previous.sha256 != result.sha256:
            raise AssertionError("a worker attempted to replace a committed output")
        self.results[job.id] = result
        return result


class BlockingAdapter:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self._delegate = SmokeCpuAdapter()

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        self.started.set()
        await self.resume.wait()
        return await self._delegate.generate(request)


class RetryableFailureAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        self.calls += 1
        raise InferenceError(
            "INFERENCE_RUNTIME_ERROR",
            "The model runtime failed.",
            retryable=True,
        )


class BlockingOutputSink(RecordingOutputSink):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    async def put(self, job: GenerationJob, result: InferenceResult) -> object:
        self.started.set()
        await self.resume.wait()
        return await super().put(job, result)


async def _service_fixture() -> tuple[GenerationService, InMemoryGenerationStore, UUID]:
    voices = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await voices.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Reliability teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="reliability-voice-create-01",
    )
    await voices.transition(voice.id, ACTOR_ID, "validating")
    await voices.transition(voice.id, ACTOR_ID, "processing")
    await voices.transition(
        voice.id,
        ACTOR_ID,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    model = ModelManifestEntry(
        model_key="openvoice-v2",
        version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        checkpoint_path="checkpoint.bin",
        runtime="cpu",
        license_name="Reviewed license",
        license_url="https://example.test/license",
        license_review_status="approved",
        supported_languages=("en-US",),
        config={},
        enabled=True,
    )
    store = InMemoryGenerationStore()
    service = GenerationService(
        store,
        voices,
        ModelRegistry(ModelManifest(1, (model,))),
    )
    return service, store, voice.id


async def _create_job(service: GenerationService, voice_id: UUID, key: str) -> GenerationJob:
    return await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        voice_profile_id=voice_id,
        project_id=None,
        input_text="A deterministic worker reliability lesson.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        seed=7,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key=key,
    )


async def _terminal_statuses(
    store: InMemoryGenerationStore, job_id: UUID
) -> list[str]:
    events = await store.audit_events()
    return [
        status
        for event in events
        if event.job_id == job_id
        and isinstance((status := event.details.get("status")), str)
        and status in TERMINAL_STATUSES
    ]


async def test_duplicate_delivery_claims_once_and_commits_one_output() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-duplicate-01")
    queue = InMemoryGenerationQueue()
    leases = InMemoryGenerationLeaseStore()
    worker = GenerationWorker(service, queue, leases, lease_seconds=30)
    outputs = RecordingOutputSink()

    await worker.publish(job.id, ACTOR_ID)
    message = await queue.dequeue()
    assert message is not None
    claims = await asyncio.gather(
        worker.claim(job.id, message.attempt, WORKER_A),
        worker.claim(job.id, message.attempt, WORKER_B),
    )
    active = [lease for lease in claims if lease is not None]
    assert len(active) == 1
    assert await worker.claim(job.id, message.attempt, WORKER_B) is None

    completed, result = await worker.execute(
        active[0].lease_id,
        WORKER_A,
        SmokeCpuAdapter(),
        outputs,
    )

    assert completed.status == "succeeded"
    assert result is not None
    assert outputs.put_calls == 1
    assert await worker.claim(job.id, message.attempt, WORKER_B) is None
    assert await _terminal_statuses(store, job.id) == ["succeeded"]


async def test_crashed_worker_cannot_commit_after_expired_lease_recovery() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-crash-01")
    queue = InMemoryGenerationQueue()
    leases = InMemoryGenerationLeaseStore()
    worker = GenerationWorker(service, queue, leases, lease_seconds=5, max_attempts=2)
    outputs = RecordingOutputSink()
    crashed_adapter = BlockingAdapter()

    await worker.publish(job.id, ACTOR_ID)
    crashed_lease = await worker.claim_next(WORKER_A)
    assert crashed_lease is not None
    crashed_execution = asyncio.create_task(
        worker.execute(crashed_lease.lease_id, WORKER_A, crashed_adapter, outputs)
    )
    await crashed_adapter.started.wait()
    await leases.put(
        replace(crashed_lease, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    recovered = await worker.reap_expired(ACTOR_ID)
    assert recovered[0].status == "queued"
    replacement_lease = await worker.claim_next(WORKER_B)
    assert replacement_lease is not None
    replacement, replacement_result = await worker.execute(
        replacement_lease.lease_id,
        WORKER_B,
        SmokeCpuAdapter(),
        outputs,
    )
    assert replacement.status == "succeeded"
    assert replacement_result is not None

    crashed_adapter.resume.set()
    with pytest.raises(GenerationError) as stale_completion:
        await crashed_execution
    assert stale_completion.value.code == "WORKER_LEASE_NOT_FOUND"
    assert outputs.put_calls == 1
    assert (await service.get(job.id)).status == "succeeded"  # type: ignore[union-attr]
    assert await _terminal_statuses(store, job.id) == ["succeeded"]


async def test_expired_final_lease_reaches_one_failed_terminal_state() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-expiry-01")
    queue = InMemoryGenerationQueue()
    leases = InMemoryGenerationLeaseStore()
    worker = GenerationWorker(service, queue, leases, lease_seconds=5, max_attempts=1)

    await worker.publish(job.id, ACTOR_ID)
    lease = await worker.claim_next(WORKER_A)
    assert lease is not None
    await leases.put(replace(lease, expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    recovered = await worker.reap_expired(ACTOR_ID)

    assert len(recovered) == 1
    assert recovered[0].status == "failed"
    assert recovered[0].error_code == "WORKER_LEASE_EXPIRED"
    assert await queue.size() == 0
    assert await _terminal_statuses(store, job.id) == ["failed"]


async def test_cancel_wins_during_inference_and_prevents_output() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-cancel-inference-01")
    queue = InMemoryGenerationQueue()
    worker = GenerationWorker(service, queue, lease_seconds=30)
    outputs = RecordingOutputSink()
    adapter = BlockingAdapter()

    await worker.publish(job.id, ACTOR_ID)
    lease = await worker.claim_next(WORKER_A)
    assert lease is not None
    execution = asyncio.create_task(worker.execute(lease.lease_id, WORKER_A, adapter, outputs))
    await adapter.started.wait()
    requested = await service.cancel(job.id, ACTOR_ID)
    assert requested.status == "cancel_requested"
    adapter.resume.set()

    completed, result = await execution

    assert completed.status == "canceled"
    assert result is None
    assert outputs.put_calls == 0
    assert await _terminal_statuses(store, job.id) == ["canceled"]


async def test_output_commit_wins_cancel_race_without_duplicate_terminal() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-cancel-commit-01")
    queue = InMemoryGenerationQueue()
    worker = GenerationWorker(service, queue, lease_seconds=30)
    outputs = BlockingOutputSink()

    await worker.publish(job.id, ACTOR_ID)
    lease = await worker.claim_next(WORKER_A)
    assert lease is not None
    execution = asyncio.create_task(
        worker.execute(lease.lease_id, WORKER_A, SmokeCpuAdapter(), outputs)
    )
    await outputs.started.wait()
    cancellation = asyncio.create_task(service.cancel(job.id, ACTOR_ID))
    await asyncio.sleep(0)
    outputs.resume.set()

    completed, result = await execution
    with pytest.raises(GenerationError) as cancel_conflict:
        await cancellation

    assert cancel_conflict.value.code == "GENERATION_STATE_CONFLICT"
    assert completed.status == "succeeded"
    assert result is not None
    assert outputs.put_calls == 1
    assert await _terminal_statuses(store, job.id) == ["succeeded"]


async def test_retry_exhaustion_never_exposes_an_intermediate_terminal_state() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-retry-01")
    queue = InMemoryGenerationQueue()
    worker = GenerationWorker(service, queue, lease_seconds=30, max_attempts=2)
    outputs = RecordingOutputSink()
    adapter = RetryableFailureAdapter()

    await worker.publish(job.id, ACTOR_ID)
    first_lease = await worker.claim_next(WORKER_A)
    assert first_lease is not None
    first, first_result = await worker.execute(
        first_lease.lease_id,
        WORKER_A,
        adapter,
        outputs,
    )
    assert first.status == "queued"
    assert first_result is None
    assert await _terminal_statuses(store, job.id) == []

    final_lease = await worker.claim_next(WORKER_B)
    assert final_lease is not None
    final, final_result = await worker.execute(
        final_lease.lease_id,
        WORKER_B,
        adapter,
        outputs,
    )

    assert final.status == "failed"
    assert final.error_code == "INFERENCE_RUNTIME_ERROR"
    assert final.retryable is False
    assert final_result is None
    assert adapter.calls == 2
    assert outputs.put_calls == 0
    assert await queue.size() == 0
    assert await _terminal_statuses(store, job.id) == ["failed"]


async def test_stale_model_manifest_fails_closed_without_loading_or_output() -> None:
    service, store, voice_id = await _service_fixture()
    job = await _create_job(service, voice_id, "reliability-stale-model-01")
    queue = InMemoryGenerationQueue()
    worker = GenerationWorker(service, queue, lease_seconds=30)
    outputs = RecordingOutputSink()
    runtime_called = False

    async def forbidden_runtime_factory(
        _entry: ModelManifestEntry, _device: str
    ) -> object:
        nonlocal runtime_called
        runtime_called = True
        raise AssertionError("a stale manifest must fail before runtime loading")

    adapter = OpenVoiceV2Adapter(
        ModelRegistry.empty(),
        forbidden_runtime_factory,  # type: ignore[arg-type]
    )
    await worker.publish(job.id, ACTOR_ID)
    lease = await worker.claim_next(WORKER_A)
    assert lease is not None

    completed, result = await worker.execute(lease.lease_id, WORKER_A, adapter, outputs)

    assert completed.status == "failed"
    assert completed.error_code == "MODEL_NOT_ALLOWLISTED"
    assert completed.retryable is False
    assert result is None
    assert runtime_called is False
    assert outputs.put_calls == 0
    assert await _terminal_statuses(store, job.id) == ["failed"]
