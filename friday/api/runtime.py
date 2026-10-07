"""Process runtime shared by the API server and the simulator chat CLI.

* builds the inbound pipeline and the call-back service (bus subscriptions);
* serialises inbound messages per sender phone (ordering, no races);
* starts/stops the task engine queue workers and the proactive loop if those
  components exist (duck-typed: ``start()``/``stop()``, or ``run()`` as a task);
* re-checks the ops cost alert after every finished call.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections import defaultdict
from typing import Any

from friday.api.callbacks import CallbackService
from friday.api.inbound import InboundPipeline
from friday.core.container import ComponentNotAvailable, Container
from friday.core.events import CallFinished
from friday.core.logging import get_logger
from friday.core.models import InboundMessage

log = get_logger(__name__)

BACKGROUND_COMPONENTS = ("task_engine", "proactive")


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Runtime:
    def __init__(self, c: Container, *, fast_pin_hash: bool = False) -> None:
        self.c = c
        self.pipeline = InboundPipeline(c, fast_pin_hash=fast_pin_hash)
        self.callbacks: CallbackService = self.pipeline.callbacks
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: list[asyncio.Task[Any]] = []
        self._started: list[Any] = []
        self.running = False

    async def start(self, *, background: bool = True) -> None:
        await self.c.startup()
        self.callbacks.subscribe()
        self.c.bus.subscribe(CallFinished, self._on_call_finished)
        if background:
            for name in BACKGROUND_COMPONENTS:
                await self._start_component(name)
        self.running = True

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

    async def handle(self, msg: InboundMessage) -> None:
        async with self._locks[msg.from_phone]:
            try:
                await self.pipeline.handle(msg)
            except Exception:  # noqa: BLE001 - a bad message never kills the webhook
                log.exception("inbound message %s failed", msg.id)

    async def _on_call_finished(self, event: CallFinished) -> None:
        task = await self.c.repos.tasks.get(event.task_id)
        if task is not None:
            await self.pipeline.costs.check(task.requester_user_id)
