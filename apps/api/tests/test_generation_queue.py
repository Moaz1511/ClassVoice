from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from app.domains.generations.jobs import GenerationService, InMemoryGenerationStore
from app.domains.voices.lifecycle import InMemoryVoiceStore, VoiceLifecycleService, VoiceReadiness
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.workers.generation_queue import (
    GenerationWorker,
    InMemoryGenerationLeaseStore,
    InMemoryGenerationQueue,
)

pytestmark = pytest.mark.asyncio

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
MODEL_SHA = "a" * 64


async def service_fixture() -> tuple[GenerationService, UUID]:
    voices = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await voices.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="queue-voice-create-01",
    )
    await voices.transition(voice.id, ACTOR_ID, "validating")
    await voices.transition(voice.id, ACTOR_ID, "processing")
    await voices.transition(
        voice.id, ACTOR_ID, "ready", readiness=VoiceReadiness(True, True, True, True)
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
    service = GenerationService(
        InMemoryGenerationStore(),
        voices,
        ModelRegistry(ModelManifest(1, (model,))),
    )
    return service, voice.id


async def create_job(service: GenerationService, voice_id: UUID, key: str) -> UUID:
    job = await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        voice_profile_id=voice_id,
        project_id=None,
        input_text="A queue lesson.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        seed=None,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key=key,
    )
    return job.id


async def test_worker_claims_leases_and_bounds_retries() -> None:
    service, voice_id = await service_fixture()
    job_id = await create_job(service, voice_id, "queue-job-create-01")
    queue = InMemoryGenerationQueue()
    worker = GenerationWorker(service, queue, lease_seconds=5, max_attempts=2)

    queued = await worker.publish(job_id, ACTOR_ID)
    assert queued.status == "queued"
    lease = await worker.claim_next(ACTOR_ID)
    assert lease is not None
    assert (await service.get(job_id)).status == "processing"  # type: ignore[union-attr]
    renewed = await worker.heartbeat(lease.lease_id)
    assert renewed.expires_at > renewed.heartbeat_at

    retried = await worker.fail(
        lease.lease_id,
        ACTOR_ID,
        error_code="MODEL_RUNTIME_ERROR",
        error_message_safe="The model worker failed.",
        retryable=True,
    )
    assert retried.status == "queued"
    assert retried.queue_attempts == 1
    second_lease = await worker.claim_next(ACTOR_ID)
    assert second_lease is not None
    terminal = await worker.fail(
        second_lease.lease_id,
        ACTOR_ID,
        error_code="MODEL_RUNTIME_ERROR",
        error_message_safe="The model worker failed.",
        retryable=True,
    )
    assert terminal.status == "failed"
    assert terminal.retryable is False
    assert await queue.size() == 0


async def test_expired_lease_is_requeued_and_audit_is_recorded() -> None:
    service, voice_id = await service_fixture()
    job_id = await create_job(service, voice_id, "queue-expiry-create-01")
    queue = InMemoryGenerationQueue()
    leases = InMemoryGenerationLeaseStore()
    worker = GenerationWorker(service, queue, leases, lease_seconds=5, max_attempts=2)
    await worker.publish(job_id, ACTOR_ID)
    lease = await worker.claim_next(ACTOR_ID)
    assert lease is not None
    await leases.put(replace(lease, expires_at=lease.claimed_at))

    recovered = await worker.reap_expired(ACTOR_ID)
    assert recovered[0].status == "queued"
    assert recovered[0].error_code is None
    assert await queue.size() == 1
