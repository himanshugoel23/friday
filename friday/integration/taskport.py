"""``TaskPort`` for W1 over the task engine's durable job queue, and the periodic call jobs.

One dial path: the engine's scheduled job ``consumer.call`` runs ``CallOrchestrator.execute``
(gate again, attempt saved before the dial, W2 engine, report, retry). Nothing here dials.

* Idempotency: the job's ``dedupe_key`` is the orchestrator's task key (``callreq:<id>:<attempt>``),
  so the same attempt never gets two live jobs, and a re-delivered job finds the request no longer
  SCHEDULED and does nothing.
* Retry delays: the orchestrator computes them with the existing ``TaskPolicy`` (+1 h, +3 h,
  max 3), moves them into the callee's calling window and creates the next attempt through this
  port with that ``run_at``; the final "could not reach" report comes from W1's report builder.
* Periodic jobs (``ConsumerJobs.tick``): ``run_due`` (safety net for a job that was lost),
  ``recover_stale`` (a call stuck in CALLING after a crash is closed, never redialled) and
  ``purge_expired`` (recordings past retention).

Job payloads hold ids only (request id, attempt), never a number or a name.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Protocol

from friday.calls.models import CallRequest
from friday.calls.orchestrator import CallOrchestrator
from friday.calls.recordings import RecordingService
from friday.core.clock import Clock
from friday.core.logging import get_logger
from friday.core.scale import Job, JobPriority

log = get_logger(__name__)

JOB_CONSUMER_CALL = "consumer.call"


class _Queue(Protocol):
    async def enqueue(self, job: Job, *, session: Any = None) -> Job: ...


class QueueTaskPort:
    """``friday.calls.interfaces.TaskPort`` backed by the container's JobQueue.

    No wake-up is sent after an enqueue: the orchestrator saves the request as SCHEDULED only
    AFTER ``create`` returns, so an instant claim would find it not yet scheduled and lose the
    attempt. The engine's own poll (``TaskEngine.tick`` every few seconds) claims the due job."""

    def __init__(self, queue: _Queue, clock: Clock) -> None:
        self.queue, self.clock = queue, clock
        self.cancelled: set[str] = set()

    async def create(
        self,
        *,
        key: str,
        request: CallRequest,
        run_at: datetime,
        parent_task_id: str | None = None,
    ) -> str:
        job = await self.queue.enqueue(
            Job(
                kind=JOB_CONSUMER_CALL,
                payload={"request_id": request.id, "key": key},
                priority=JobPriority.TASK,
                due_at=run_at,
                dedupe_key=key,
                partition_key=request.user_id,
                max_attempts=3,
                created_at=self.clock.now(),
            )
        )
        return job.id

    async def cancel(self, task_id: str) -> None:
        """Best effort: the job still fires, finds the request CANCELLED and does nothing."""
        self.cancelled.add(task_id)


def job_handler(orchestrator: CallOrchestrator, locks: Any = None):  # noqa: ANN201
    """The function registered on the task engine for ``consumer.call`` jobs. ``locks`` is the
    container's DistributedLock (optional): one worker at a time per request."""

    async def handle(job: Job) -> None:
        request_id = str(job.payload.get("request_id") or "")
        if not request_id:
            return
        if locks is None:
            await orchestrator.execute(request_id)  # the single dial path
            return
        async with locks.hold(f"consumer.call:{request_id}", timeout_s=30):
            await orchestrator.execute(request_id)

    return handle


class ConsumerJobs:
    """The periodic jobs W1 listed as unwired. ``tick`` is cheap and idempotent; ``loop`` runs it
    beside the app's other loops (friday/api/runtime.py)."""

    def __init__(
        self,
        orchestrator: CallOrchestrator,
        clock: Clock,
        *,
        recordings: RecordingService | None = None,
        interval_s: float = 30.0,
        purge_every: timedelta = timedelta(hours=6),
        grace: timedelta = timedelta(minutes=2),
    ) -> None:
        self.orch, self.clock, self.recordings = orchestrator, clock, recordings
        self.interval_s, self.purge_every, self.grace = interval_s, purge_every, grace
        self._last_purge: datetime | None = None

    async def tick(self) -> dict[str, int]:
        now = self.clock.now()
        done = {
            # only calls the engine's own job missed by more than the grace period
            "run_due": await self.orch.run_due(now - self.grace),
            "recover_stale": await self.orch.recover_stale(now),
            "purge_expired": 0,
        }
        if self.recordings is not None and (
            self._last_purge is None or now - self._last_purge >= self.purge_every
        ):
            done["purge_expired"] = await self.recordings.purge_expired(now)
            self._last_purge = now
        return done

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - a bad tick never kills the loop
                log.exception("consumer jobs tick failed")
            await asyncio.sleep(self.interval_s)
