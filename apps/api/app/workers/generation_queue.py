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
from app.domains.generations.outputs import GenerationOutputError, GenerationOutputSink
from app.inference.adapter import (
    InferenceAdapter,
    InferenceError,
    InferenceRequest,
    InferenceResult,
)
from app.inference.postprocess import AudioPostProcessor


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

    async def acquire(self, lease: GenerationLease) -> bool: ...

    async def renew(
        self, lease_id: UUID, heartbeat_at: datetime, expires_at: datetime
    ) -> GenerationLease | None: ...

    async def release(self, job_id: UUID, lease_id: UUID) -> GenerationLease | None: ...

    async def pop_expired(self, now: datetime) -> tuple[GenerationLease, ...]: ...

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
            existing = self._outputs.get(job.id)
            if existing is not None:
                if (
                    existing.sha256 == result.sha256
                    and existing.content_type == result.content_type
                ):
                    return
                raise GenerationOutputError(
                    "OUTPUT_ALREADY_COMMITTED",
                    "A different generated output is already committed for this job.",
                    retryable=False,
                )
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

    async def acquire(self, lease: GenerationLease) -> bool:
        async with self._lock:
            if lease.job_id in self._leases:
                return False
            self._leases[lease.job_id] = lease
            return True

    async def renew(
        self, lease_id: UUID, heartbeat_at: datetime, expires_at: datetime
    ) -> GenerationLease | None:
        async with self._lock:
            for job_id, lease in self._leases.items():
                if lease.lease_id != lease_id:
                    continue
                if lease.expires_at <= heartbeat_at:
                    return None
                updated = GenerationLease(
                    lease.lease_id,
                    lease.job_id,
                    lease.attempt,
                    lease.claimed_at,
                    heartbeat_at,
                    expires_at,
                )
                self._leases[job_id] = updated
                return updated
            return None

    async def release(self, job_id: UUID, lease_id: UUID) -> GenerationLease | None:
        async with self._lock:
            current = self._leases.get(job_id)
            if current is None or current.lease_id != lease_id:
                return None
            return self._leases.pop(job_id)

    async def pop_expired(self, now: datetime) -> tuple[GenerationLease, ...]:
        async with self._lock:
            expired = tuple(lease for lease in self._leases.values() if lease.expires_at <= now)
            for lease in expired:
                self._leases.pop(lease.job_id, None)
            return expired

    # Deterministic tests may move a lease's clock without sleeping. Runtime
    # code uses acquire/renew/release/pop_expired instead of this replacement.
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
        if job is None:
            return None
        if job.status == "cancel_requested":
            await self._service.transition(job.id, worker_id, "canceled")
            return None
        if job.status != "queued":
            return None
        now = datetime.now(UTC)
        lease = GenerationLease(
            lease_id=uuid4(),
            job_id=job.id,
            attempt=attempt,
            claimed_at=now,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        if not await self._leases.acquire(lease):
            return None
        claimed = False
        try:
            current = await self._service.get(job.id)
            if current is None:
                return None
            if current.status == "cancel_requested":
                await self._service.transition(job.id, worker_id, "canceled")
                return None
            if current.status != "queued":
                return None
            await self._service.transition(job.id, worker_id, "processing")
            claimed = True
            return lease
        except GenerationError as error:
            current = await self._service.get(job.id)
            if (
                error.code == "GENERATION_STATE_CONFLICT"
                and current is not None
                and current.status == "cancel_requested"
            ):
                await self._service.transition(job.id, worker_id, "canceled")
                return None
            raise
        finally:
            if not claimed:
                await self._leases.release(lease.job_id, lease.lease_id)

    async def heartbeat(self, lease_id: UUID) -> GenerationLease:
        lease = await self._find_lease(lease_id)
        now = datetime.now(UTC)
        if lease.expires_at <= now:
            raise GenerationError("WORKER_LEASE_EXPIRED", "Worker lease has expired.")
        updated = await self._leases.renew(
            lease.lease_id,
            now,
            now + timedelta(seconds=self._lease_seconds),
        )
        if updated is None:
            raise GenerationError("WORKER_LEASE_NOT_FOUND", "Worker lease was not found.")
        return updated

    async def execute(
        self,
        lease_id: UUID,
        actor_id: UUID,
        adapter: InferenceAdapter,
        outputs: GenerationOutputSink,
        *,
        postprocessor: AudioPostProcessor | None = None,
    ) -> tuple[GenerationJob, InferenceResult | None]:
        lease = await self._require_active_lease(lease_id)
        job = await self._service.get(lease.job_id)
        if job is None:
            await self._leases.release(lease.job_id, lease.lease_id)
            raise GenerationError("GENERATION_NOT_FOUND", "Generation was not found.")
        if job.status == "cancel_requested":
            canceled = await self._service.transition(job.id, actor_id, "canceled")
            await self._leases.release(lease.job_id, lease.lease_id)
            return canceled, None
        if job.status != "processing":
            await self._leases.release(lease.job_id, lease.lease_id)
            return job, None
        try:
            request = InferenceRequest.from_job(job)
            # Model adapters normalize their native output as WAV.  MP3 is a
            # worker concern, so never ask a runtime to implement encoding.
            if request.output_format == "mp3":
                request = InferenceRequest(
                    job_id=request.job_id,
                    input_text=request.input_text,
                    language_code=request.language_code,
                    output_format="wav",
                    speed=request.speed,
                    stability=request.stability,
                    style=request.style,
                    seed=request.seed,
                    model_key=request.model_key,
                    model_version=request.model_version,
                    checkpoint_sha256=request.checkpoint_sha256,
                    model_metadata=request.model_metadata,
                )
            result = await adapter.generate(request)
            result = await (postprocessor or AudioPostProcessor()).normalize(
                result, job.output_format
            )
            await self._require_active_lease(lease.lease_id)

            async def persist_output(current: GenerationJob) -> object:
                return await outputs.put(current, result)

            completed, committed = await self._service.commit_success(
                lease.job_id,
                actor_id,
                persist_output,
            )
        except InferenceError as error:
            failed = await self.fail(
                lease.lease_id,
                actor_id,
                error_code=error.code,
                error_message_safe=str(error),
                retryable=error.retryable,
            )
            return failed, None
        except GenerationOutputError as error:
            failed = await self.fail(
                lease.lease_id,
                actor_id,
                error_code=error.code,
                error_message_safe=str(error),
                retryable=error.retryable,
            )
            return failed, None
        await self._leases.release(lease.job_id, lease.lease_id)
        return completed, result if committed else None

    async def fail(
        self,
        lease_id: UUID,
        actor_id: UUID,
        *,
        error_code: str,
        error_message_safe: str,
        retryable: bool,
    ) -> GenerationJob:
        lease = await self._require_active_lease(lease_id)
        should_retry = retryable and lease.attempt < self._max_attempts
        if should_retry:
            job = await self._service.requeue_after_worker_failure(
                lease.job_id,
                actor_id,
                error_code=error_code,
            )
        else:
            try:
                job = await self._service.transition(
                    lease.job_id,
                    actor_id,
                    "failed",
                    error_code=error_code,
                    error_message_safe=error_message_safe,
                    retryable=False,
                )
            except GenerationError as error:
                current = await self._service.get(lease.job_id)
                if (
                    error.code == "GENERATION_STATE_CONFLICT"
                    and current is not None
                    and current.status == "cancel_requested"
                ):
                    job = await self._service.transition(lease.job_id, actor_id, "canceled")
                else:
                    raise
        await self._leases.release(lease.job_id, lease.lease_id)
        if job.status == "queued":
            return await self.publish(job.id, actor_id)
        return job

    async def reap_expired(self, actor_id: UUID) -> tuple[GenerationJob, ...]:
        now = datetime.now(UTC)
        recovered: list[GenerationJob] = []
        for lease in await self._leases.pop_expired(now):
            current = await self._service.get(lease.job_id)
            if current is None:
                continue
            if current.status == "cancel_requested":
                recovered.append(
                    await self._service.transition(current.id, actor_id, "canceled")
                )
            elif current.status == "processing":
                recovered.append(await self._recover_expired(lease, actor_id, current))
        return tuple(recovered)

    async def _recover_expired(
        self, lease: GenerationLease, actor_id: UUID, current: GenerationJob
    ) -> GenerationJob:
        if lease.attempt < self._max_attempts:
            requeued = await self._service.requeue_after_worker_failure(
                current.id,
                actor_id,
                error_code="WORKER_LEASE_EXPIRED",
            )
            if requeued.status == "queued":
                return await self.publish(requeued.id, actor_id)
            return requeued
        try:
            failed = await self._service.transition(
                current.id,
                actor_id,
                "failed",
                error_code="WORKER_LEASE_EXPIRED",
                error_message_safe="The worker lease expired before completion.",
                retryable=False,
            )
        except GenerationError as error:
            latest = await self._service.get(current.id)
            if (
                error.code == "GENERATION_STATE_CONFLICT"
                and latest is not None
                and latest.status == "cancel_requested"
            ):
                return await self._service.transition(current.id, actor_id, "canceled")
            raise
        return failed

    async def _find_lease(self, lease_id: UUID) -> GenerationLease:
        for lease in await self._leases.list():
            if lease.lease_id == lease_id:
                return lease
        raise GenerationError("WORKER_LEASE_NOT_FOUND", "Worker lease was not found.")

    async def _require_active_lease(self, lease_id: UUID) -> GenerationLease:
        lease = await self._find_lease(lease_id)
        if lease.expires_at <= datetime.now(UTC):
            raise GenerationError("WORKER_LEASE_EXPIRED", "Worker lease has expired.")
        return lease

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
        from arq import create_pool
        from arq.connections import RedisSettings

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
