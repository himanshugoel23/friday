# ruff: noqa: E501
"""Friday's own outbound call queue: pace calls so Vobiz's account-side queue never has to.

A call waits here until (a) fewer than ``max_concurrent`` calls are in flight, (b) the start-rate
gap since the last start has passed, (c) no other call to the same destination is live, and (d) it
is the first eligible waiter (urgent before normal, then oldest). The slot is released when the
call ends, is hung up or cancelled, fails to place, or its deadline passes (stale slots are
reclaimed, also after a restart). Unanswered calls are cancelled (Vobiz ``DELETE /Call/{uuid}``,
which is what ``leg.hangup()`` does) after the ring timeout plus a grace.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from friday.callqueue import metrics
from friday.callqueue.limits import Limits
from friday.callqueue.limits import resolve as resolve_limits
from friday.callqueue.store import NORMAL, URGENT, Entry, QueueStore
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.core.models import DialStatus

log = get_logger(__name__)

MAX_POLL_S = 1.0


class QueueRefused(ProviderError):
    def __init__(self, code: str) -> None:
        super().__init__("callqueue", code)
        self.code = code


def priority_of(request: Any) -> int:
    md = getattr(request, "metadata", None) or {}
    if md.get("priority") == "urgent" or md.get("kind") == "urgent_escalation":
        return URGENT
    return NORMAL


def key_of(request: Any) -> str:
    md = getattr(request, "metadata", None) or {}
    return str(md.get("idempotency_key") or f"{request.task_id}:{request.to_phone[-4:]}")


class CallQueue:
    def __init__(
        self,
        store: QueueStore,
        *,
        limits: Callable[[], Limits] | Limits = Limits(),
        grace_s: float = 10,
        max_wait_s: float = 900,
        poll_s: float = 2.0,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.store, self.grace_s, self.max_wait_s, self.poll_s = store, grace_s, max_wait_s, poll_s
        self._limits = limits if callable(limits) else (lambda: limits)
        self.clock, self.sleep = clock or store.clock, sleep
        self._tasks: set[asyncio.Task] = set()

    @property
    def limits(self) -> Limits:
        return self._limits()

    # ---------------------------------------------------------------- slots
    async def acquire(
        self, *, key: str, number: str, priority: int, ring_s: float, max_s: float,
        should_stop: Callable[[], Exception | None] = lambda: None,
    ) -> Entry:  # fmt: skip
        entry, created = self.store.enqueue(
            key=key, number=number, priority=priority, ring_s=ring_s, max_s=max_s
        )
        if not created:
            metrics.inc("duplicate")
            log.info("call queue: duplicate enqueue ignored (to ...%s)", entry.tail)
            raise QueueRefused("duplicate_call")
        metrics.inc("enqueued")
        log.info("call queue: enqueued #%s prio=%s to ...%s", entry.id, entry.priority, entry.tail)
        try:
            while True:
                stop = should_stop()
                if stop is not None:
                    self.store.finish(entry.id, "cancelled", "stopped")
                    metrics.inc("cancelled")
                    raise stop
                lim = self.limits
                ok, retry, rec = self.store.try_grant(entry.id, lim, self.grace_s)
                if rec:
                    metrics.inc("reclaimed_stale", rec)
                    log.warning("call queue: reclaimed %d stale slot(s)", rec)
                if ok:
                    waited = self.clock() - entry.enqueued_at
                    metrics.inc("started")
                    log.info(
                        "call queue: start #%s to ...%s after %.1fs wait",
                        entry.id,
                        entry.tail,
                        waited,
                    )
                    return self.store.get(entry.id) or entry
                if self.clock() - entry.enqueued_at > self.max_wait_s:
                    self.store.finish(entry.id, "expired", "wait_timeout")
                    metrics.inc("expired")
                    log.warning(
                        "call queue: #%s to ...%s gave up after %.0fs",
                        entry.id,
                        entry.tail,
                        self.max_wait_s,
                    )
                    raise QueueRefused("queue_wait_timeout")
                await self.sleep(max(0.05, min(retry, MAX_POLL_S)))
        except asyncio.CancelledError:
            self.store.finish(entry.id, "cancelled", "task_cancelled")
            metrics.inc("cancelled")
            raise

    def release(self, entry_id: int, outcome: str) -> bool:
        done = self.store.finish(entry_id, "done", outcome)
        if done:
            metrics.inc(f"released_{outcome}")
            log.info("call queue: slot #%s released (%s)", entry_id, outcome)
        return done

    # ---------------------------------------------------------------- watching a live leg
    def watch(self, entry: Entry, leg: QueuedLeg) -> None:
        task = asyncio.ensure_future(self._watch(entry, leg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _watch(self, entry: Entry, leg: QueuedLeg) -> None:
        start = entry.started_at or self.clock()
        ring_deadline = start + entry.ring_s + self.grace_s
        hard_deadline = entry.deadline_at or (start + entry.ring_s + entry.max_s + self.grace_s)
        while not leg.released:
            await self.sleep(self.poll_s)
            if leg.released:
                return
            now = self.clock()
            if getattr(leg.inner, "ended", False):
                await leg.finish("ended")
            elif not leg.is_answered() and now >= ring_deadline:
                metrics.inc("ring_cancelled")
                log.warning(
                    "call queue: #%s unanswered after ring timeout + grace; cancelling", entry.id
                )
                await leg.finish("ring_timeout", cancel=True)
            elif now >= hard_deadline:
                metrics.inc("max_duration_cancelled")
                log.warning("call queue: #%s past max duration; cancelling", entry.id)
                await leg.finish("max_duration", cancel=True)


class QueuedLeg:
    """Proxy for the provider leg: same behaviour, plus releasing the queue slot on its end."""

    _OWN = ("inner", "_queue", "_entry", "released", "answered")

    def __init__(self, inner: Any, queue: CallQueue, entry: Entry) -> None:
        object.__setattr__(self, "inner", inner)
        object.__setattr__(self, "_queue", queue)
        object.__setattr__(self, "_entry", entry)
        object.__setattr__(self, "released", False)
        object.__setattr__(self, "answered", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)

    def is_answered(self) -> bool:
        return self.answered or getattr(self.inner, "status", None) == DialStatus.ANSWERED

    async def finish(self, outcome: str, *, cancel: bool = False) -> None:
        """Release the slot (once). ``cancel`` also hangs the provider call up (Vobiz DELETE)."""
        if self.released:
            return
        object.__setattr__(self, "released", True)
        if cancel:
            with contextlib.suppress(Exception):
                await self.inner.hangup()
        self._queue.release(self._entry.id, outcome)

    async def wait_for_answer(self, timeout_s: float) -> Any:
        try:
            status = await self.inner.wait_for_answer(timeout_s)
        except BaseException:
            await self.finish("wait_failed", cancel=True)
            raise
        if status == DialStatus.ANSWERED:
            object.__setattr__(self, "answered", True)
        else:  # nobody to talk to: the slot is free, and the provider call must not linger
            await self.finish("not_answered", cancel=True)
        return status

    async def hangup(self) -> None:
        try:
            await self.inner.hangup()
        finally:
            await self.finish("hangup")


class GuardedDialer:
    """Wraps ``telephony.place_call`` with the queue. Keeps the pilot allow-list and the kill switch."""

    def __init__(
        self, inner_place_call: Callable[..., Awaitable[Any]], queue: CallQueue, settings: Any
    ) -> None:
        self._place, self.queue, self.settings = inner_place_call, queue, settings

    def _stop(self) -> Exception | None:
        from friday.pause import PausedError, is_paused

        return PausedError() if is_paused(self.settings) else None

    async def place_call(self, request: Any, *a: Any, **k: Any) -> Any:
        if self.settings.pilot_dial_blocked(request.to_phone):  # real calls only to the allow-list
            metrics.inc("refused_allowlist")
            raise QueueRefused("test_allowlist")
        entry = await self.queue.acquire(
            key=key_of(request), number=request.to_phone, priority=priority_of(request),
            ring_s=float(request.ring_timeout_s), max_s=float(request.max_duration_s),
            should_stop=self._stop,
        )  # fmt: skip
        try:
            leg = await self._place(request, *a, **k)
        except BaseException:
            self.queue.release(entry.id, "place_failed")
            raise
        cid = getattr(leg, "provider_call_id", None)
        if cid:
            self.queue.store.set_call_id(entry.id, str(cid))
        qleg = QueuedLeg(leg, self.queue, entry)
        self.queue.watch(entry, qleg)
        return qleg


def build_queue(settings: Any, **kw: Any) -> CallQueue:
    store = QueueStore(settings.call_queue_db)
    return CallQueue(
        store, limits=lambda: resolve_limits(settings), grace_s=settings.call_queue_grace_s,
        max_wait_s=settings.call_queue_max_wait_s, **kw,
    )  # fmt: skip


def install_call_queue(c: Any) -> list[str]:
    """Put the queue in front of ``telephony.place_call``. A no-op unless the switch is on."""
    settings = c.settings
    if not getattr(settings, "call_queue_enabled", False):
        return []
    if "telephony" not in set(c.role_components()):
        return []
    try:
        tel = c.get("telephony")
    except Exception:  # noqa: BLE001 - a role without telephony simply has no queue
        return []
    if getattr(tel, "_friday_call_queue", None) is not None:
        return ["telephony.place_call"]
    dialer = GuardedDialer(tel.place_call, build_queue(settings), settings)
    try:
        tel.place_call = dialer.place_call
        tel._friday_call_queue = dialer.queue
    except (AttributeError, TypeError):
        return []
    log.info("call queue ON: %s", dialer.queue.limits)
    return ["telephony.place_call"]
