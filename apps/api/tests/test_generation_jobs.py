from __future__ import annotations

from uuid import UUID

import pytest
from app.domains.generations.jobs import (
    GenerationError,
    GenerationService,
    InMemoryGenerationStore,
)
from app.domains.voices.lifecycle import (
    InMemoryVoiceStore,
    VoiceLifecycleService,
    VoiceReadiness,
)
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry

pytestmark = pytest.mark.asyncio

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
MODEL_SHA = "a" * 64


def model_registry(*, enabled: bool = True, status: str = "approved") -> ModelRegistry:
    entry = ModelManifestEntry(
        model_key="openvoice-v2",
        version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        checkpoint_path="checkpoint.bin",
        runtime="cpu",
        license_name="Reviewed license",
        license_url="https://example.test/license",
        license_review_status=status,  # type: ignore[arg-type]
        supported_languages=("en-US",),
        config={"sample_rate_hz": 24000},
        enabled=enabled,
    )
    return ModelRegistry(ModelManifest(1, (entry,)))


async def service_fixture() -> tuple[GenerationService, UUID]:
    voice_service = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await voice_service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="generation-voice-create-01",
    )
    await voice_service.transition(voice.id, ACTOR_ID, "validating")
    await voice_service.transition(voice.id, ACTOR_ID, "processing")
    await voice_service.transition(
        voice.id,
        ACTOR_ID,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    return (
        GenerationService(InMemoryGenerationStore(), voice_service, model_registry()),
        voice.id,
    )


async def create_job(
    service: GenerationService,
    voice_id: UUID,
    *,
    key: str = "generation-create-key-01",
):
    return await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        voice_profile_id=voice_id,
        project_id=None,
        input_text="A short lesson for students.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=0.5,
        style=0.2,
        seed=7,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key=key,
    )


async def test_generation_create_copies_model_provenance_and_is_idempotent() -> None:
    service, voice_id = await service_fixture()
    first = await create_job(service, voice_id)
    second = await create_job(service, voice_id)

    assert first.id == second.id
    assert first.status == "created"
    assert first.input_text_sha256 == first.input_text_sha256
    assert first.model_metadata["checkpoint_sha256"] == MODEL_SHA
    assert first.as_dict(include_text=False).get("input_text") is None


async def test_generation_rejects_voice_model_language_and_input_gates() -> None:
    service, voice_id = await service_fixture()
    with pytest.raises(GenerationError) as language_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            voice_profile_id=voice_id,
            project_id=None,
            input_text="Lesson",
            language_code="fr-FR",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            idempotency_key="generation-language-key-01",
        )
    assert language_error.value.code == "LANGUAGE_UNSUPPORTED"

    consent_service, consent_voice_id = await service_fixture()
    await consent_service._voices.revoke(consent_voice_id, ACTOR_ID)  # type: ignore[attr-defined]
    with pytest.raises(GenerationError) as consent_error:
        await create_job(consent_service, consent_voice_id, key="generation-consent-key-01")
    assert consent_error.value.code == "VOICE_CONSENT_REVOKED"

    with pytest.raises(GenerationError) as model_error:
        await GenerationService(
            service._store, service._voices, model_registry(status="pending", enabled=False)  # type: ignore[attr-defined]
        ).create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            voice_profile_id=voice_id,
            project_id=None,
            input_text="Lesson",
            language_code="en-US",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            idempotency_key="generation-model-key-01",
        )
    assert model_error.value.code == "MODEL_LICENSE_NOT_APPROVED"

    with pytest.raises(GenerationError) as speed_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            voice_profile_id=voice_id,
            project_id=None,
            input_text="Lesson",
            language_code="en-US",
            output_format="wav",
            speed=2.1,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            idempotency_key="generation-speed-key-01",
        )
    assert speed_error.value.code == "SPEED_INVALID"

    with pytest.raises(GenerationError) as text_error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            voice_profile_id=voice_id,
            project_id=None,
            input_text="x" * 10_001,
            language_code="en-US",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            idempotency_key="generation-text-key-01",
        )
    assert text_error.value.code == "INPUT_TEXT_INVALID"


async def test_cancel_retry_and_worker_transitions_are_bounded_and_audited() -> None:
    service, voice_id = await service_fixture()
    job = await create_job(service, voice_id)
    await service.transition(job.id, ACTOR_ID, "queued")
    await service.transition(job.id, ACTOR_ID, "processing")
    failed = await service.transition(
        job.id,
        ACTOR_ID,
        "failed",
        error_code="MODEL_RUNTIME_ERROR",
        error_message_safe="The model worker failed.",
        retryable=True,
    )
    retried = await service.retry(failed.id, ACTOR_ID)
    assert retried.status == "created"
    assert retried.queue_attempts == 1
    cancel_requested = await service.cancel(retried.id, ACTOR_ID)
    assert cancel_requested.status == "cancel_requested"
    canceled = await service.transition(retried.id, ACTOR_ID, "canceled")
    assert canceled.status == "canceled"

    store = service._store  # type: ignore[attr-defined]
    assert (await store.audit_events())[-1].action == "generation.status_changed"


async def test_duplicate_idempotency_metadata_is_rejected() -> None:
    service, voice_id = await service_fixture()
    await create_job(service, voice_id)
    with pytest.raises(GenerationError) as error:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            voice_profile_id=voice_id,
            project_id=None,
            input_text="Different lesson",
            language_code="en-US",
            output_format="wav",
            speed=1.0,
            stability=None,
            style=None,
            seed=None,
            model_key="openvoice-v2",
            model_version="2.0.0",
            checkpoint_sha256=MODEL_SHA,
            idempotency_key="generation-create-key-01",
        )
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
