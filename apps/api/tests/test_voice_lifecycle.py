from __future__ import annotations

from uuid import UUID

import pytest
from app.domains.voices.lifecycle import (
    InMemoryVoiceStore,
    VoiceLifecycleError,
    VoiceLifecycleService,
    VoiceReadiness,
)

pytestmark = pytest.mark.asyncio

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
HASH = "a" * 64


async def create_voice(service: VoiceLifecycleService, *, key: str = "voice-create-key-0001"):
    return await service.create(
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        name="Teacher voice",
        language_code="en-US",
        consent_statement_version="v1",
        consent_attestation_text_hash=HASH,
        reference_upload_id=UUID("00000000-0000-0000-0000-000000000003"),
        idempotency_key=key,
    )


async def test_create_is_idempotent_and_records_consent_metadata() -> None:
    store = InMemoryVoiceStore()
    service = VoiceLifecycleService(store)

    first = await create_voice(service)
    second = await create_voice(service)

    assert first.id == second.id
    assert first.status == "draft"
    assert first.consent_status == "accepted"
    assert first.consent_attestation_text_hash == HASH
    assert (await store.audit_events())[0].action == "voice.created"


async def test_idempotency_key_reuse_and_invalid_consent_are_rejected() -> None:
    service = VoiceLifecycleService(InMemoryVoiceStore())
    await create_voice(service)

    with pytest.raises(VoiceLifecycleError) as reused:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            name="Different voice",
            language_code="en-US",
            consent_statement_version="v1",
            consent_attestation_text_hash=HASH,
            reference_upload_id=None,
            idempotency_key="voice-create-key-0001",
        )
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

    with pytest.raises(VoiceLifecycleError) as invalid:
        await service.create(
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            name="Teacher voice",
            language_code="en-US",
            consent_statement_version="v1",
            consent_attestation_text_hash="bad",
            reference_upload_id=None,
            idempotency_key="voice-create-key-0002",
        )
    assert invalid.value.code == "CONSENT_ATTESTATION_INVALID"


async def test_archive_restore_update_and_revoke_follow_lifecycle_rules() -> None:
    service = VoiceLifecycleService(InMemoryVoiceStore())
    voice = await create_voice(service)

    archived = await service.update(voice.id, ACTOR_ID, status="archived", name="Archived voice")
    assert archived.status == "archived"
    restored = await service.update(voice.id, ACTOR_ID, status="draft")
    assert restored.status == "draft"
    revoked = await service.revoke(voice.id, ACTOR_ID, reason="consent withdrawn")
    assert revoked.status == "revoked"
    assert revoked.consent_status == "revoked"
    assert revoked.revoked_at is not None

    with pytest.raises(VoiceLifecycleError) as update_error:
        await service.update(voice.id, ACTOR_ID, name="No longer mutable")
    assert update_error.value.code == "VOICE_REVOKED"


async def test_ready_requires_all_prerequisites_and_delete_queues_cascade() -> None:
    store = InMemoryVoiceStore()
    service = VoiceLifecycleService(store)
    voice = await create_voice(service)

    await service.transition(voice.id, ACTOR_ID, "validating")
    await service.transition(voice.id, ACTOR_ID, "processing")
    with pytest.raises(VoiceLifecycleError) as not_ready:
        await service.transition(voice.id, ACTOR_ID, "ready")
    assert not_ready.value.code == "VOICE_NOT_READY"

    ready = await service.transition(
        voice.id,
        ACTOR_ID,
        "ready",
        readiness=VoiceReadiness(True, True, True, True),
    )
    assert ready.status == "ready"
    task = await service.delete(voice.id, ACTOR_ID)
    assert task.voice_id == voice.id
    assert await service.get(voice.id) is None
    assert (await store.cascade_tasks())[0].voice_id == voice.id
    assert (await store.audit_events())[-1].action == "voice.deleted"
