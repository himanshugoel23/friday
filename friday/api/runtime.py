"""Process runtime shared by the API server and the simulator chat CLI.

* builds the inbound pipeline and the call-back service (bus subscriptions);
* serialises inbound messages per sender phone (ordering, no races);
* starts the background loops of the process ROLES (``Settings.roles``; one codebase,
  several deployments - ARCHITECTURE §10.3):

  =========  ==========================================================================
  api        webhooks + callbacks (always wired); no loops of its own
  task       inbound.message / message.send worker loop + the task engine (step /
             scheduled jobs, exactly-once timers)
  voice      ``friday.voice.worker.build_voice_worker(c)``: claims ``call.place`` and runs
             it through ``task_engine.handle_job`` (the engine does NOT claim calls when a
             voice worker owns them: ``engine.claim_calls = False``)
  proactive  the proactive engine (its tick runs the daily retention job) plus a
             retention loop so ``repos.retention.run`` also runs when proactive is off
  batch      reserved: no ``batch.*`` consumers exist yet (logged)
  =========  ==========================================================================

* re-checks the ops cost alert after every finished call.

Inbound-call bus events (InboundCallReceived / MissedCallReceived) are published in the
process that hosts the provider webhook (role api) and consumed there; cross-process
delivery would need the ``call.inbound`` job kind (not implemented - see CORE_CHANGES).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from typing import Any

from friday.api.callbacks import CallbackService
from friday.api.inbound import InboundPipeline
from friday.core.container import ComponentNotAvailable, Container
from friday.core.events import CallFinished
from friday.core.logging import get_logger
from friday.core.models import InboundMessage
from friday.core.scale import (
    DistributedLock,
    Job,
    JobPriority,
    LockTimeout,
    MemoryLock,
    worker_id,
)
from friday.db.repositories._base import phone_index

log = get_logger(__name__)

CONSUMED_KINDS = ("inbound.message", "message.send")
RETENTION_POLL_S = 900.0  # real-time cadence; the job itself runs once per IST day


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Runtime:
    def __init__(self, c: Container, *, fast_pin_hash: bool = False) -> None:
        self.c = c
        self.pipeline = InboundPipeline(c, fast_pin_hash=fast_pin_hash)
        self.callbacks: CallbackService = self.pipeline.callbacks
        # SECURITY-34 / S-3: per-sender serialisation through the shared DistributedLock
        # (ref-counted memory lock in dev; Postgres advisory / Redis lock across replicas).
        try:
            self.lock: DistributedLock = c.get("lock")
        except ComponentNotAvailable:
            self.lock = MemoryLock()
        self._tasks: list[asyncio.Task[Any]] = []
        self._started: list[Any] = []
        self.running = False
        self.worker = worker_id("task")

    async def start(self, *, background: bool = True) -> None:
        await self.c.startup()
        self.callbacks.subscribe()
        self.c.bus.subscribe(CallFinished, self._on_call_finished)
        if background:
            await self._start_roles()
        self.running = True

    async def _start_roles(self) -> None:
        s = self.c.settings
        voice_worker = self._build_voice_worker() if s.has_role("voice") else None
        if s.has_role("task"):
            self._tasks.append(asyncio.create_task(self.worker_loop(), name="friday-worker"))
            await self._start_component("task_engine")
        if voice_worker is not None:
            await voice_worker.start()
            self._started.append(voice_worker)
        if s.has_role("proactive"):
            await self._start_component("proactive")
            self._tasks.append(asyncio.create_task(self.retention_loop(), name="friday-retention"))
        if s.has_role("batch"):
            log.info("role batch: no batch.* job consumers are registered yet")
        log.info("runtime started for roles %s", ",".join(s.roles))

    def _build_voice_worker(self) -> Any | None:
        """The voice role owns ``call.place``: the engine in this process stops claiming it."""
        engine = self._component("task_engine")
        try:
            from friday.voice.worker import build_voice_worker

            worker = build_voice_worker(self.c)
        except Exception:  # noqa: BLE001 - fall back to the engine claiming calls itself
            log.exception("voice worker not available; the task engine will place calls")
            return None
        if engine is not None:
            engine.claim_calls = False
        return worker

    async def retention_loop(self) -> None:
        """SECURITY-32: ``repos.retention.run`` once per IST day (exactly once across
        replicas via the idempotency store inside ``RetentionJob.run_daily``)."""
        from friday.proactive.retention import RetentionJob

        job = RetentionJob(self.c)
        while True:
            try:
                await job.run_daily(self.c.clock.now())
            except Exception:  # noqa: BLE001
                log.exception("retention run failed")
            await asyncio.sleep(RETENTION_POLL_S)

    async def _start_component(self, name: str) -> None:
        try:
            comp = self.c.get(name)
        except ComponentNotAvailable:
            log.info("%s not available; not started", name)
            return
        except Exception:  # noqa: BLE001 - one broken component must not stop the app
            log.exception("could not build %s", name)
            return
        if callable(getattr(comp, "start", None)):
            await _maybe_await(comp.start())
            self._started.append(comp)
        elif callable(getattr(comp, "run", None)):
            self._tasks.append(asyncio.create_task(_maybe_await(comp.run()), name=f"friday-{name}"))

    async def stop(self) -> None:
        self.callbacks.unsubscribe()
        self.c.bus.unsubscribe(CallFinished, self._on_call_finished)
        for comp in reversed(self._started):
            if callable(getattr(comp, "stop", None)):
                try:
                    await _maybe_await(comp.stop())
                except Exception:  # noqa: BLE001
                    log.exception("error stopping %s", type(comp).__name__)
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()
        self._started.clear()
        self.running = False

    # ------------------------------------------------------------------ durable inbound (S-1)
    def _component(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except ComponentNotAvailable:
            return None

    async def accept_inbound(self, msg: InboundMessage) -> bool:
        """Webhook path: idempotency check -> durable enqueue. False = duplicate.
        No per-user in-memory state here; processing happens in a worker."""
        idem = self._component("idempotency")
        key = f"wa:{msg.provider_message_id}" if msg.provider_message_id else None
        ttl = self.c.settings.webhook_idempotency_ttl_h * 3600
        if key and idem is not None and not await idem.first_seen(key, ttl_s=ttl):
            return False
        queue = self._component("job_queue")
        if queue is None:  # no queue available: process in-line (degraded)
            await self.handle(msg)
            return True
        await queue.enqueue(
            Job(
                kind="inbound.message",
                payload={"message": msg.model_dump(mode="json")},
                priority=JobPriority.LIVE,
                dedupe_key=key,
                partition_key=phone_index(msg.from_phone),
            )
        )
        return True

    async def drain(self, kinds: tuple[str, ...] = CONSUMED_KINDS, *, limit: int = 20) -> int:
        """Claim and process due jobs of ``kinds``; returns how many were processed."""
        queue = self._component("job_queue")
        if queue is None:
            return 0
        done = 0
        while True:
            jobs = await queue.claim(self.worker, kinds=list(kinds), limit=limit)
            if not jobs:
                return done
            for job in jobs:
                try:
                    await self._run_job(job)
                    await queue.ack(job.id)
                except Exception as e:  # noqa: BLE001 - retry with backoff, dead-letter at max
                    log.warning("job %s (%s) failed: %s", job.id, job.kind, type(e).__name__)
                    await queue.retry(
                        job.id, error=type(e).__name__, delay_s=min(300, 5 * 2**job.attempts)
                    )
                done += 1

    async def _run_job(self, job: Job) -> None:
        if job.kind == "inbound.message":
            msg = InboundMessage.model_validate(job.payload["message"])
            await self.handle(msg, raise_errors=True)
        elif job.kind == "message.send":
            await self.c.notifier.handle_job(job)

    async def worker_loop(self) -> None:
        queue = self._component("job_queue")
        wait = getattr(queue, "wait_for_work", None)
        while True:
            try:
                n = await self.drain()
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                n = 0
            if n == 0:
                if wait is not None:
                    await wait(self.c.settings.queue_poll_interval_s)
                else:
                    await self.c.clock.sleep(self.c.settings.queue_poll_interval_s)

    async def handle(self, msg: InboundMessage, *, raise_errors: bool = False) -> None:
        try:
            async with self.lock.hold(f"sender:{msg.from_phone}", timeout_s=30.0):
                await self.pipeline.handle(msg)
        except LockTimeout:
            log.warning("inbound message %s: sender busy, lock timeout", msg.id)
            raise
        except Exception:  # noqa: BLE001 - a bad message never kills the webhook
            log.exception("inbound message %s failed", msg.id)
            if raise_errors:
                raise

    async def _on_call_finished(self, event: CallFinished) -> None:
        task = await self.c.repos.tasks.get(event.task_id)
        if task is not None:
            await self.pipeline.costs.check(task.requester_user_id)
