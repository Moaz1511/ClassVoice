"""Workspace abuse-report service backed by ``public.moderation_flags``."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

ModerationStatus = Literal["open", "reviewing", "resolved", "dismissed"]


@dataclass(frozen=True, slots=True)
class ModerationReport:
    id: UUID
    workspace_id: UUID
    reporter_user_id: UUID | None
    resource_type: str
    resource_id: UUID
    reason_code: str
    description: str | None
    status: ModerationStatus = "open"
    reviewer_user_id: UUID | None = None
    resolution_note: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "reporter_user_id": str(self.reporter_user_id) if self.reporter_user_id else None,
            "resource_type": self.resource_type,
            "resource_id": str(self.resource_id),
            "reason_code": self.reason_code,
            "description": self.description,
            "status": self.status,
            "reviewer_user_id": str(self.reviewer_user_id) if self.reviewer_user_id else None,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ModerationReportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InMemoryModerationReportStore:
    def __init__(self) -> None:
        self._reports: list[ModerationReport] = []
        self._lock = asyncio.Lock()

    async def insert(self, report: ModerationReport) -> ModerationReport:
        async with self._lock:
            self._reports.append(report)
        return report

    async def list(
        self,
        *,
        status: ModerationStatus | None = None,
        limit: int = 100,
    ) -> tuple[ModerationReport, ...]:
        async with self._lock:
            reports = [item for item in self._reports if status is None or item.status == status]
            return tuple(reversed(reports[-max(1, limit) :]))


class ModerationReportService:
    def __init__(self, store: InMemoryModerationReportStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        workspace_id: UUID,
        reporter_user_id: UUID,
        resource_type: str,
        resource_id: UUID,
        reason_code: str,
        description: str | None,
    ) -> ModerationReport:
        if not resource_type.strip() or len(resource_type) > 64:
            raise ModerationReportError("REPORT_RESOURCE_INVALID", "Resource type is invalid.")
        if not reason_code.strip() or len(reason_code) > 64:
            raise ModerationReportError("REPORT_REASON_INVALID", "Report reason is invalid.")
        return await self._store.insert(
            ModerationReport(
                id=uuid4(),
                workspace_id=workspace_id,
                reporter_user_id=reporter_user_id,
                resource_type=resource_type.strip(),
                resource_id=resource_id,
                reason_code=reason_code.strip(),
                description=description,
            )
        )

    async def list(
        self,
        *,
        status: ModerationStatus | None = None,
        limit: int = 100,
    ) -> tuple[ModerationReport, ...]:
        return await self._store.list(status=status, limit=limit)
