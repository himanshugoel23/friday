"""Voice worker role (S-9): claims ``call.place`` jobs when it has capacity and runs them
through the task engine (``c.task_engine.handle_job(job)``), which drives
``c.call_runner``.

* **Capacity** - claims at most ``worker_concurrency["voice"]`` live calls per process
  (minus what is already running and what a draining runner refuses).
* **Pinning** - a call lives in the process that claimed it: its legs, VAD buffers and
  media socket are in this worker's memory. ``worker_id`` is stamped into every media
  stream URL (``w=<id>``) so the load balancer can route the provider's WebSocket back
  here; a socket that lands on another replica is closed (``1013``) and re-dialled by the
  provider. The job lease is extended while the call is live, so a crash (not a slow
  call) is what frees the job for another worker.
* **Limiters** - the runner takes ``RateLimiter.acquire("telephony")`` and
  ``slot("telephony")`` + ``slot(<provider>)`` around each call (see ``session.py``).
* **Graceful drain** - ``stop(drain_s)`` stops claiming, lets live calls finish, then
  asks stragglers to wrap up politely.

Run with ``FRIDAY_ROLES=voice``: ``await build_voice_worker(c).start()`` (the API runtime
or ``friday worker --role voice`` owns the process).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.logging import get_logger
from friday.core.scale import Job, JobQueue, worker_id

log = get_logger(__name__)

JOB_CALL = "call.place"
Handler = Callable[[Job], Awaitable[None]]


class VoiceWorker:
    def __init__(
        self,
        *,
        queue: JobQueue,
        handler: Handler,
        settings: Settings,
        runner: Any = None,
        telephony: Any = None,
        clock: Clock | None = None,
        kinds: Sequence[str] = (JOB_CALL,),
        concurrency: int | None = None,
        poll_s: float | None = None,
        wid: str | None = None,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self.settings = settings
        self.runner = runner
        self.telephony = telephony
        self.kinds = tuple(kinds)
        self.concurrency = concurrency or settings.worker_concurrency.get("voice", 50)
        self.poll_s = poll_s if poll_s is not None else settings.queue_poll_interval_s
        self.lease_s = settings.queue_visibility_timeout_s
        self.worker_id = wid or worker_id("voice")
        self.running: dict[str, asyncio.Task] = {}  # job id -> task
        self.handled: list[str] = []  # job ids this worker completed (tests / metrics)
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._pin_providers()

    # ------------------------------------------------------------------ pinning
    def _pin_providers(self) -> None:
        tel = self.telephony
        if tel is None:
            return
        for p in getattr(tel, "providers", None) or [tel]:
            p.worker_id = self.worker_id

    # ------------------------------------------------------------------ capacity
    @property
    def free_slots(self) -> int:
        if self.runner is not None and getattr(self.runner, "draining", False):
            return 0
        return max(0, self.concurrency - len(self.running))

    async def run_once(self) -> int:
        """Claim up to ``free_slots`` due jobs and start them. Returns how many started."""
        free = self.free_slots
        if free <= 0 or self._stop.is_set():
            return 0
        jobs = await self.queue.claim(
            self.worker_id, kinds=list(self.kinds), limit=free, lease_s=self.lease_s
        )
        for job in jobs:
            self.running[job.id] = asyncio.create_task(self._handle(job), name=f"call-{job.id}")
        return len(jobs)

    async def _handle(self, job: Job) -> None:
        beat = asyncio.create_task(self._heartbeat(job.id))
        try:
            await self.handler(job)  # engine.handle_job acks / retries the job itself
            self.handled.append(job.id)
        except asyncio.CancelledError:
            raise  # shutting down hard: the lease expires and another worker re-claims
        except Exception:  # noqa: BLE001 - one bad call never kills the worker
            log.exception("voice job %s failed", job.id)
            with contextlib.suppress(Exception):
                await self.queue.retry(job.id, error="voice worker error", delay_s=30.0)
        finally:
            beat.cancel()
            self.running.pop(job.id, None)

    async def _heartbeat(self, job_id: str) -> None:
        """Keep the lease while the call is live (a long hold must not re-queue the job)."""
        interval = max(1.0, self.lease_s / 3)
        while True:
            await asyncio.sleep(interval)
            with contextlib.suppress(Exception):
                await self.queue.extend_lease(job_id, self.lease_s)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._stop.clear()
            self._loop_task = asyncio.create_task(self._loop(), name="voice-worker")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("voice worker claim failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_s)

    async def wait_idle(self, timeout_s: float | None = None) -> bool:
        tasks = list(self.running.values())
        if not tasks:
            return True
        _done, pending = await asyncio.wait(tasks, timeout=timeout_s)
        return not pending

    async def stop(self, drain_s: float = 30.0) -> bool:
        """Graceful drain: no new claims; live calls finish (or wrap up after ``drain_s``)."""
        self._stop.set()
        if self._loop_task is not None:
            await self._loop_task
        ok = True
        if self.runner is not None and hasattr(self.runner, "drain"):
            ok = bool(await self.runner.drain(timeout_s=drain_s))
        await self.wait_idle(timeout_s=drain_s)
        for task in list(self.running.values()):
            task.cancel()
        return ok


def build_voice_worker(c: Container) -> VoiceWorker:
    """The ``voice`` role worker: claims ``call.place`` jobs, runs them via the engine."""
    engine = c.task_engine
    return VoiceWorker(
        queue=c.get("job_queue"),
        handler=engine.handle_job,
        settings=c.settings,
        runner=c.call_runner,
        telephony=c.telephony,
        clock=c.clock,
    )
