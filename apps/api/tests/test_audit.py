from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.core.authorization import AuthPrincipal
from app.domains.audit.service import AuditService, InMemoryAuditEventStore

pytestmark = pytest.mark.asyncio


async def test_audit_emission_maps_actor_and_redacts_payload_fields() -> None:
    store = InMemoryAuditEventStore()
    service = AuditService(store)
    user_id = uuid4()
    api_key_id = uuid4()
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")

    event = await service.emit(
        action="generation.created",
        resource_type="generation_job",
        workspace_id=workspace_id,
        resource_id=uuid4(),
        actor=AuthPrincipal(user_id, frozenset(), workspace_id, api_key_id),
        request_id="req-audit-01",
        ip_address="192.0.2.10",
        user_agent="test-agent",
        metadata={
            "model_key": "openvoice-v2",
            "input_text": "a private lesson transcript",
            "secret": "do-not-store",
            "nested": {"content": "private"},
        },
    )

    assert event.actor_type == "api_key"
    assert event.actor_user_id == user_id
    assert event.actor_api_key_id == api_key_id
    assert event.request_id == "req-audit-01"
    assert event.ip_hash is not None and event.ip_hash != "192.0.2.10"
    assert event.user_agent_hash is not None
    assert event.metadata["input_text"] == "[REDACTED]"
    assert event.metadata["secret"] == "[REDACTED]"
    assert event.metadata["nested"] == {"content": "[REDACTED]"}

    stored = await store.list_workspace(workspace_id)
    assert stored == (event,)
