"""ARQ task entrypoint for generation jobs.

The inference callback is intentionally injected through the ARQ context;
P2-10 supplies the deterministic CPU adapter while this step owns claiming,
lease cleanup, and retry semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import cast
from uuid import UUID, uuid4

from app.domains.generations.jobs import GenerationError
from app.workers.generation_queue import GenerationLease, GenerationWorker

GenerationRunner = Callable[[GenerationLease], Awaitable[None]]


async def process_generation(ctx: Mapping[str, object], job_id: str, attempt: int) -> None:
    worker = cast(GenerationWorker, ctx["generation_worker"])
    worker_id = cast(UUID, ctx.get("worker_id", uuid4()))
    lease = await worker.claim(UUID(job_id), attempt, worker_id)
    if lease is None:
        return
    runner = ctx.get("run_generation")
    if not callable(runner):
        await worker.fail(
            lease.lease_id,
            worker_id,
            error_code="WORKER_RUNNER_NOT_CONFIGURED",
            error_message_safe="The generation worker is not configured.",
            retryable=False,
        )
        return
    try:
        await cast(GenerationRunner, runner)(lease)
    except GenerationError:
        raise
