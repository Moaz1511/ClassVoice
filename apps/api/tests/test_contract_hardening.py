from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.api.v1.api_keys import CreateApiKeyBody
from app.api.v1.generations import CreateGenerationBody
from app.api.v1.reports import CreateReportBody
from app.api.v1.voices import UploadIntentBody
from app.domains.api_keys.service import ApiKeyError, ApiKeyService, InMemoryApiKeyStore
from app.domains.generations.jobs import (
    GenerationError,
    GenerationService,
    InMemoryGenerationStore,
    _validate_request,
)
from app.domains.projects.service import (
    EditorSettings,
    InMemoryProjectStore,
    ProjectError,
    ProjectService,
)
from app.domains.voices.lifecycle import (
    InMemoryVoiceStore,
    VoiceLifecycleError,
    VoiceLifecycleService,
    VoiceReadiness,
)
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from pydantic import ValidationError

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000102")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000103")
MODEL_SHA = "a" * 64


def _generation_body() -> dict[str, object]:
    return {
        "workspace_id": str(WORKSPACE_ID),
        "voice_profile_id": str(uuid4()),
        "input_text": "A short lesson.",
        "language_code": "en-US",
        "output_format": "wav",
        "speed": 1.0,
        "stability": 0.5,
        "style": 0.2,
        "model_key": "openvoice-v2",
        "model_version": "2.0.0",
        "checkpoint_sha256": MODEL_SHA,
    }


def _model_registry() -> ModelRegistry:
    return ModelRegistry(
        ModelManifest(
            schema_version=1,
            models=(
                ModelManifestEntry(
                    model_key="openvoice-v2",
                    version="2.0.0",
                    checkpoint_sha256=MODEL_SHA,
                    checkpoint_path="checkpoint.bin",
                    runtime="cpu",
                    license_name="Reviewed license",
                    license_url="https://example.test/license",
                    license_review_status="approved",
                    supported_languages=("en-US",),
                    config={"sample_rate_hz": 24000},
                    enabled=True,
                ),
            ),
        )
    )


async def _ready_voice(service: VoiceLifecycleService, *, workspace_id: UUID = WORKSPACE_ID):
    voice = await service.create(
        workspace_id=workspace_id,
        actor_id=ACTOR_ID,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key=f"contract-voice-{uuid4().hex[:20]}",
    )
    await service.transition(voice.id, ACTOR_ID, "validating")
    await service.transition(voice.id, ACTOR_ID, "processing")
    return await service.transition(
        voice.id,
        ACTOR_ID,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"input_text": ""}, "INPUT_TEXT_INVALID"),
        ({"input_text": "x" * 10_001}, "INPUT_TEXT_INVALID"),
        ({"language_code": "EN-us"}, "LANGUAGE_INVALID"),
        ({"output_format": "ogg"}, "OUTPUT_FORMAT_INVALID"),
        ({"speed": 0.49}, "SPEED_INVALID"),
        ({"speed": 2.01}, "SPEED_INVALID"),
        ({"stability": -0.01}, "STABILITY_INVALID"),
        ({"style": 1.01}, "STYLE_INVALID"),
        ({"checkpoint_sha256": "not-a-sha"}, "MODEL_SHA_INVALID"),
        ({"idempotency_key": "too-short"}, "IDEMPOTENCY_KEY_INVALID"),
        ({"idempotency_key": "contract-key-\x00-invalid"}, "IDEMPOTENCY_KEY_INVALID"),
    ],
)
def test_generation_input_boundaries_have_stable_error_codes(
    changes: dict[str, object], code: str
) -> None:
    values: dict[str, object] = {
        "input_text": "A short lesson.",
        "language_code": "en-US",
        "output_format": "wav",
        "speed": 1.0,
        "stability": 0.5,
        "style": 0.2,
        "checkpoint_sha256": MODEL_SHA,
        "idempotency_key": "contract-generation-key-01",
    }
    values.update(changes)
    with pytest.raises(GenerationError) as error:
        _validate_request(**values)  # type: ignore[arg-type]
    assert error.value.code == code


def test_http_body_models_enforce_boundary_shapes() -> None:
    with pytest.raises(ValidationError):
        CreateGenerationBody(**{**_generation_body(), "input_text": ""})
    with pytest.raises(ValidationError):
        CreateGenerationBody(**{**_generation_body(), "speed": 2.1})
    with pytest.raises(ValidationError):
        CreateGenerationBody(**{**_generation_body(), "checkpoint_sha256": "bad"})
    with pytest.raises(ValidationError):
        UploadIntentBody(
            workspace_id=WORKSPACE_ID,
            filename="lesson.wav",
            content_type="audio/wav",
            size_bytes=25_000_001,
        )
    with pytest.raises(ValidationError):
        CreateReportBody(
            workspace_id=WORKSPACE_ID,
            resource_type="voice_profile",
            resource_id=uuid4(),
            reason_code="privacy",
            description="x" * 2_001,
        )
    with pytest.raises(ValidationError):
        CreateApiKeyBody(
            workspace_id=WORKSPACE_ID,
            name="agent",
            scopes=[],
        )


@pytest.mark.asyncio
async def test_voice_policy_matrix_blocks_invalid_transitions_and_reuse() -> None:
    service = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="  Teacher voice  ",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="contract-voice-idempotency-01",
    )
    repeated = await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash="b" * 64,
        reference_upload_id=None,
        idempotency_key="contract-voice-idempotency-01",
    )
    assert repeated.id == voice.id

    await service.transition(voice.id, ACTOR_ID, "validating")
    await service.transition(voice.id, ACTOR_ID, "processing")
    with pytest.raises(VoiceLifecycleError) as not_ready:
        await service.transition(voice.id, ACTOR_ID, "ready")
    assert not_ready.value.code == "VOICE_NOT_READY"

    with pytest.raises(VoiceLifecycleError) as invalid_transition:
        await service.transition(voice.id, ACTOR_ID, "draft")
    assert invalid_transition.value.code == "VOICE_STATE_CONFLICT"

    ready = await _ready_voice(service)
    revoked = await service.revoke(ready.id, ACTOR_ID)
    assert revoked.status == "revoked"
    with pytest.raises(VoiceLifecycleError) as revoked_update:
        await service.update(revoked.id, ACTOR_ID, name="Blocked update")
    assert revoked_update.value.code == "VOICE_REVOKED"
    with pytest.raises(VoiceLifecycleError) as reused:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            name="Different voice",
            language_code="en-US",
            consent_statement_version="v1",
            consent_attestation_text_hash="b" * 64,
            reference_upload_id=None,
            idempotency_key="contract-voice-idempotency-01",
        )
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_generation_terminal_states_and_retry_policy_are_bounded() -> None:
    voices = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await _ready_voice(voices)
    service = GenerationService(InMemoryGenerationStore(), voices, _model_registry())
    job = await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        voice_profile_id=voice.id,
        project_id=None,
        input_text="A short lesson.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        seed=None,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key="contract-generation-lifecycle-01",
    )
    await service.transition(job.id, ACTOR_ID, "queued")
    await service.transition(job.id, ACTOR_ID, "processing")
    succeeded = await service.transition(job.id, ACTOR_ID, "succeeded")
    assert succeeded.completed_at is not None
    with pytest.raises(GenerationError) as cancel_terminal:
        await service.cancel(job.id, ACTOR_ID)
    assert cancel_terminal.value.code == "GENERATION_STATE_CONFLICT"
    with pytest.raises(GenerationError) as retry_terminal:
        await service.retry(job.id, ACTOR_ID)
    assert retry_terminal.value.code == "GENERATION_NOT_RETRYABLE"

    failed_job = await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        voice_profile_id=voice.id,
        project_id=None,
        input_text="Retry this lesson.",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        seed=None,
        model_key="openvoice-v2",
        model_version="2.0.0",
        checkpoint_sha256=MODEL_SHA,
        idempotency_key="contract-generation-lifecycle-02",
    )
    await service.transition(failed_job.id, ACTOR_ID, "queued")
    failed = await service.transition(
        failed_job.id,
        ACTOR_ID,
        "failed",
        error_code="MODEL_RUNTIME_ERROR",
        error_message_safe="Worker failed safely.",
        retryable=True,
    )
    retried = await service.retry(failed.id, ACTOR_ID)
    assert retried.status == "created"
    assert retried.queue_attempts == 1


@pytest.mark.asyncio
async def test_project_policy_rejects_empty_updates_cross_workspace_voices_and_bad_limits() -> None:
    voices = VoiceLifecycleService(InMemoryVoiceStore())
    ready = await _ready_voice(voices)
    projects = ProjectService(InMemoryProjectStore(), voices)
    project = await projects.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="  Algebra lesson ",
        description=None,
        editor_settings=EditorSettings(voice_profile_id=ready.id),
        idempotency_key="contract-project-idempotency-01",
    )
    repeated = await projects.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Algebra lesson",
        description=None,
        editor_settings=EditorSettings(voice_profile_id=ready.id),
        idempotency_key="contract-project-idempotency-01",
    )
    assert repeated.id == project.id

    with pytest.raises(ProjectError) as empty:
        await projects.update(project.id, ACTOR_ID)
    assert empty.value.code == "PROJECT_UPDATE_EMPTY"
    with pytest.raises(ProjectError) as limit:
        await projects.list(WORKSPACE_ID, limit=101)
    assert limit.value.code == "PROJECT_LIMIT_INVALID"
    other_workspace_voice = await _ready_voice(voices, workspace_id=OTHER_WORKSPACE_ID)
    with pytest.raises(ProjectError) as cross_workspace:
        await projects.update(
            project.id,
            ACTOR_ID,
            editor_settings=EditorSettings(voice_profile_id=other_workspace_voice.id),
        )
    assert cross_workspace.value.code == "VOICE_NOT_FOUND"

    with pytest.raises(ProjectError) as mismatch:
        await projects.update(
            project.id,
            ACTOR_ID,
            editor_settings=EditorSettings(
                voice_profile_id=ready.id,
                language_code="fr-FR",
            ),
        )
    assert mismatch.value.code == "LANGUAGE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_api_key_policy_matrix_has_stable_codes_and_workspace_binding() -> None:
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    service = ApiKeyService(InMemoryApiKeyStore(), now=lambda: now)

    with pytest.raises(ApiKeyError) as empty_name:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=ACTOR_ID,
            name=" ",
            scopes=["generations:read"],
            expires_at=None,
        )
    assert empty_name.value.code == "API_KEY_NAME_INVALID"

    with pytest.raises(ApiKeyError) as timezone:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=ACTOR_ID,
            name="Agent",
            scopes=["generations:read"],
            expires_at=datetime(2027, 1, 1),
        )
    assert timezone.value.code == "API_KEY_TIME_INVALID"

    with pytest.raises(ApiKeyError) as lifetime:
        await service.create(
            workspace_id=WORKSPACE_ID,
            created_by=ACTOR_ID,
            name="Agent",
            scopes=["generations:read"],
            expires_at=now + timedelta(days=366),
        )
    assert lifetime.value.code == "API_KEY_EXPIRY_INVALID"

    issue = await service.create(
        workspace_id=WORKSPACE_ID,
        created_by=ACTOR_ID,
        name="Agent",
        scopes=["generations:read", "generations:read"],
        expires_at=now + timedelta(days=1),
    )
    assert issue.record.scopes == frozenset({"generations:read"})
    with pytest.raises(ApiKeyError) as wrong_workspace:
        await service.revoke(issue.record.id, OTHER_WORKSPACE_ID)
    assert wrong_workspace.value.code == "API_KEY_NOT_FOUND"
