"""At-least-once generation dispatch, leases, and bounded retries.

The queue and lease stores are deliberately small ports.  Local tests use the
in-memory implementations; production wires :class:`ArqGenerationPublisher`
to Redis/ARQ while the generation service remains the source of truth for
job state and terminal outcomes.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.domains.generations.jobs import GenerationError, GenerationJob, GenerationService
from app.inference.adapter import (
    InferenceAdapter,
    InferenceError,
    InferenceRequest,
    InferenceResult,
)


@dataclass(frozen=True, slots=True)
class GenerationQueueMessage:
    job_id: UUID
    attempt: int
    enqueued_at: datetime


@dataclass(frozen=True, slots=True)
class GenerationLease:
    lease_id: UUID
    job_id: UUID
    attempt: int
    claimed_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


class GenerationPublisher(Protocol):
    async def enqueue(self, job_id: UUID, attempt: int) -> None: ...


class GenerationLeaseStore(Protocol):
    async def get(self, job_id: UUID) -> GenerationLease | None: ...

    async def put(self, lease: GenerationLease) -> None: ...

    async def remove(self, job_id: UUID) -> GenerationLease | None: ...

    async def list(self) -> tuple[GenerationLease, ...]: ...


class GenerationOutputStore(Protocol):
    async def put(self, job: GenerationJob, result: InferenceResult) -> None: ...

    async def get(self, job_id: UUID) -> InferenceResult | None: ...


class InMemoryGenerationOutputStore(GenerationOutputStore):
    def __init__(self) -> None:
        self._outputs: dict[UUID, InferenceResult] = {}
        self._lock = asyncio.Lock()

    async def put(self, job: GenerationJob, result: InferenceResult) -> None:
        async with self._lock:
            self._outputs[job.id] = result

    async def get(self, job_id: UUID) -> InferenceResult | None:
        async with self._lock:
            return self._outputs.get(job_id)


class InMemoryGenerationQueue(GenerationPublisher):
    """Deterministic at-least-once queue used by local API/tests."""

    def __init__(self) -> None:
        self._items: deque[GenerationQueueMessage] = deque()
        self._keys: set[tuple[UUID, int]] = set()
        self._lock = asyncio.Lock()

    async def enqueue(self, job_id: UUID, attempt: int) -> None:
        if attempt < 1:
            raise GenerationError("QUEUE_ATTEMPT_INVALID", "Queue attempt must be positive.")
        async with self._lock:
            key = (job_id, attempt)
            if key in self._keys:
                return
            self._keys.add(key)
            self._items.append(GenerationQueueMessage(job_id, attempt, datetime.now(UTC)))

    async def dequeue(self) -> GenerationQueueMessage | None:
        async with self._lock:
            if not self._items:
                return None
            message = self._items.popleft()
            self._keys.discard((message.job_id, message.attempt))
            return message

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)


class InMemoryGenerationLeaseStore(GenerationLeaseStore):
    def __init__(self) -> None:
        self._leases: dict[UUID, GenerationLease] = {}
        self._lock = asyncio.Lock()

    async def get(self, job_id: UUID) -> GenerationLease | None:
        async with self._lock:
            return self._leases.get(job_id)

    async def put(self, lease: GenerationLease) -> None:
        async with self._lock:
            self._leases[lease.job_id] = lease

    async def remove(self, job_id: UUID) -> GenerationLease | None:
        async with self._lock:
            return self._leases.pop(job_id, None)

    async def list(self) -> tuple[GenerationLease, ...]:
        async with self._lock:
            return tuple(self._leases.values())


class GenerationWorker:
    """Claim jobs, renew leases, and persist bounded terminal/retry states."""

    def __init__(
        self,
        service: GenerationService,
        publisher: InMemoryGenerationQueue,
        leases: GenerationLeaseStore | None = None,
        *,
        lease_seconds: int = 60,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds < 5:
            raise ValueError("lease_seconds must be at least 5")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._service = service
        self._publisher = publisher
        self._leases = leases or InMemoryGenerationLeaseStore()
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def publish(self, job_id: UUID, actor_id: UUID) -> GenerationJob:
        job = await self._require(job_id)
        if job.status == "created":
            job = await self._service.transition(job.id, actor_id, "queued")
        elif job.status not in {"queued"}:
            return job
        await self._publisher.enqueue(job.id, job.queue_attempts + 1)
        return job

    async def claim_next(self, worker_id: UUID) -> GenerationLease | None:
        message = await self._publisher.dequeue()
        if message is None:
            return None
        return await self.claim(message.job_id, message.attempt, worker_id)

    async def claim(self, job_id: UUID, attempt: int, worker_id: UUID) -> GenerationLease | None:
        """Claim a specific ARQ delivery or an in-memory queue delivery."""

        job = await self._service.get(job_id)
        if job is None or job.status not in {"queued"}:
            return None
        existing = await self._leases.get(job.id)
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        lease = GenerationLease(
            lease_id=uuid4(),
            job_id=job.id,
            attempt=attempt,
            claimed_at=now,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        await self._service.transition(job.id, worker_id, "processing")
        await self._leases.put(lease)
        return lease

    async def heartbeat(self, lease_id: UUID) -> GenerationLease:
        lease = await self._find_lease(lease_id)
        now = datetime.now(UTC)
        updated = GenerationLease(
            lease.lease_id,
            lease.job_id,
            lease.attempt,
            lease.claimed_at,
            now,
            now + timedelta(seconds=self._lease_seconds),
        )
        await self._leases.put(updated)
        return updated

    async def succeed(self, lease_id: UUID, actor_id: UUID) -> GenerationJob:
        lease = await self._find_lease(lease_id)
        job = await self._service.transition(lease.job_id, actor_id, "succeeded")
        await self._leases.remove(lease.job_id)
        return job

    async def execute(
        self,
        lease_id: UUID,
        actor_id: UUID,
        adapter: InferenceAdapter,
        outputs: GenerationOutputStore,
    ) -> tuple[GenerationJob, InferenceResult | None]:
        lease = await self._find_lease(lease_id)
        job = await self._service.get(lease.job_id)
        if job is None:
            await self._leases.remove(lease.job_id)
            raise GenerationError("GENERATION_NOT_FOUND", "Generation was not found.")
        try:
            result = await adapter.generate(InferenceRequest.from_job(job))
            await outputs.put(job, result)
        except InferenceError as error:
            failed = await self.fail(
                lease.lease_id,
                actor_id,
                error_code=error.code,
                error_message_safe=str(error),
                retryable=error.retryable,
            )
            return failed, None
        completed = await self.succeed(lease.lease_id, actor_id)
        return completed, result

    async def fail(
        self,
        lease_id: UUID,
        actor_id: UUID,
        *,
        error_code: str,
        error_message_safe: str,
        retryable: bool,
    ) -> GenerationJob:
        lease = await self._find_lease(lease_id)
        job = await self._service.transition(
            lease.job_id,
            actor_id,
            "failed",
            error_code=error_code,
            error_message_safe=error_message_safe,
            retryable=retryable and lease.attempt < self._max_attempts,
        )
        await self._leases.remove(lease.job_id)
        if job.retryable:
            retried = await self._service.retry(job.id, actor_id)
            return await self.publish(retried.id, actor_id)
        return job

    async def reap_expired(self, actor_id: UUID) -> tuple[GenerationJob, ...]:
        now = datetime.now(UTC)
        recovered: list[GenerationJob] = []
        for lease in await self._leases.list():
            if lease.expires_at > now:
                continue
            current = await self._service.get(lease.job_id)
            await self._leases.remove(lease.job_id)
            if current is None or current.status != "processing":
                continue
            recovered.append(
                await self._recover_expired(lease, actor_id, current)
            )
        return tuple(recovered)

    async def _recover_expired(
        self, lease: GenerationLease, actor_id: UUID, current: GenerationJob
    ) -> GenerationJob:
        failed = await self._service.transition(
            current.id,
            actor_id,
            "failed",
            error_code="WORKER_LEASE_EXPIRED",
            error_message_safe="The worker lease expired before completion.",
            retryable=lease.attempt < self._max_attempts,
        )
        if not failed.retryable:
            return failed
        retried = await self._service.retry(failed.id, actor_id)
        return await self.publish(retried.id, actor_id)

    async def _find_lease(self, lease_id: UUID) -> GenerationLease:
        for lease in await self._leases.list():
            if lease.lease_id == lease_id:
                return lease
        raise GenerationError("WORKER_LEASE_NOT_FOUND", "Worker lease was not found.")

    async def _require(self, job_id: UUID) -> GenerationJob:
        job = await self._service.get(job_id)
        if job is None:
            raise GenerationError("GENERATION_NOT_FOUND", "Generation was not found.")
        return job


class ArqGenerationPublisher:
    """Redis/ARQ publisher; imports ARQ lazily so local unit tests stay offline."""

    def __init__(self, redis_url: str, *, queue_name: str = "classvoice") -> None:
        self._redis_url = redis_url
        self._queue_name = queue_name

    async def enqueue(self, job_id: UUID, attempt: int) -> None:
        from arq import create_pool  # type: ignore[import-not-found]
        from arq.connections import RedisSettings  # type: ignore[import-not-found]

        pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        try:
            await pool.enqueue_job(
                "process_generation",
                str(job_id),
                attempt,
                _job_id=f"generation:{job_id}:{attempt}",
                _queue_name=self._queue_name,
            )
        finally:
            await pool.close()
