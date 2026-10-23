"""SessionManager: one fresh, isolated browser context per task.

* Isolation: a new context per task (never reused); saved logins come only from the vault slot of
  THAT user and site.
* Default-deny network: a ``NetworkPolicy`` per connector, checked on goto here and on every request
  inside the backend.
* Limits: per-action timeout, whole-task deadline, max pages, max downloads; hitting one closes it.
* Concurrency: ``max_per_user`` and ``max_global`` are enforced when a slot is reserved (before any
  await), so racing opens cannot exceed the caps.
* Cleanup: deadline timer, ``close`` in a finally, ``kill_*`` for the kill switch. Closing always
  tears the browser down; the vault is written only on a clean close.
* Takeover: while the user drives, Friday's calls wait; recording and audit see event counts only.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from friday.connectors.browser.backend import BrowserBackend, SessionSpec
from friday.connectors.browser.policy import LimitCounter, NetworkPolicy, ResourceLimits
from friday.connectors.browser.port import (
    BrowserError,
    BrowserSession,
    LimitExceeded,
    LiveBrowserSession,
    NetworkBlocked,
)
from friday.connectors.recorder import MASK_SELECTORS, RecordingSession, StepRecorder
from friday.connectors.session.audit import AuditLog
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.session.vault import StorageVault

ALLOWED_KEYS = frozenset({
    "Enter", "Tab", "Backspace", "Delete", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft",
    "ArrowRight", "Home", "End", "Space",
})
MAX_TYPE_CHARS = 200


class SessionRefused(BrowserError):
    """Not allowed to start (switch off, user not enabled, paused, or at a concurrency cap)."""


class SessionClosed(BrowserError):
    """The session was closed (done, expired, limit, or killed)."""


class TakeoverError(BrowserError):
    """Takeover misuse (not active, bad input event)."""


@dataclass
class SessionInfo:
    task_id: str
    user_id: str
    site: str
    started_at: float
    mode: str  # "agent" | "takeover"


class TaskSession:
    """The BrowserSession a connector gets. Enforces policy, limits and takeover pauses."""

    def __init__(self, mgr: SessionManager, info: SessionInfo, inner: LiveBrowserSession,
                 policy: NetworkPolicy, counter: LimitCounter, recorder: StepRecorder | None):
        self._mgr, self.info, self._raw = mgr, info, inner
        self._policy, self._counter = policy, counter
        self._front: BrowserSession = RecordingSession(inner, recorder) if recorder else inner
        self._agent_turn = asyncio.Event()
        self._agent_turn.set()
        self.closed = False
        self.close_reason = ""
        self._takeover_timer: asyncio.Task[None] | None = None
        self._deadline_timer: asyncio.Task[None] | None = None
        self.input_events = 0

    # ---- state
    @property
    def takeover_active(self) -> bool:
        return self.info.mode == "takeover"

    async def _gate(self, action: str) -> None:
        while True:
            if self.closed:
                raise SessionClosed(self.close_reason or "closed")
            if self._counter.tripped:
                reason = self._counter.tripped
                await self._mgr.close(self.info.task_id, persist=False, reason=f"limit:{reason}")
                raise LimitExceeded(reason)
            if self._agent_turn.is_set():
                return
            await self._agent_turn.wait()  # Friday waits while the user drives

    # ---- BrowserSession surface (Friday / connector side)
    async def goto(self, url: str) -> None:
        await self._gate("goto")
        reason = self._policy.check(url)
        if reason:
            self._counter.blocked(url, reason)
            raise NetworkBlocked(reason)
        self._mgr.audit.record("step", task_id=self.info.task_id, user_id=self.info.user_id,
                               site=self.info.site, action="goto", host=_host(url))
        await self._front.goto(url)

    async def fill(self, selector: str, value: str) -> None:
        await self._gate("fill")
        self._step("fill", selector)  # the value is never logged
        await self._front.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._gate("click")
        self._step("click", selector)
        await self._front.click(selector)

    async def text(self, selector: str) -> str:
        await self._gate("text")
        return await self._front.text(selector)

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]:
        await self._gate("query_all")
        return await self._front.query_all(selector, fields)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        await self._gate("wait_for")
        await self._front.wait_for(selector, timeout_ms)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        await self._gate("screenshot")
        return await self._front.screenshot(tuple(mask_selectors) or MASK_SELECTORS)

    async def close(self) -> None:
        await self._mgr.close(self.info.task_id)

    def _step(self, action: str, selector: str) -> None:
        self._mgr.audit.record("step", task_id=self.info.task_id, user_id=self.info.user_id,
                               site=self.info.site, action=action, selector=selector)

    # ---- live view side (used by LiveViewService; works even while the agent is paused)
    async def frame(self) -> bytes:
        """Masked PNG for the live view. Password / OTP / phone fields are always painted over."""
        if self.closed:
            raise SessionClosed(self.close_reason or "closed")
        return await self._raw.screenshot(MASK_SELECTORS)

    def begin_takeover(self) -> None:
        if self.closed:
            raise SessionClosed(self.close_reason or "closed")
        if self.takeover_active:
            return
        self.info.mode = "takeover"
        self._agent_turn.clear()
        self.input_events = 0
        self._mgr.audit.record("takeover_start", task_id=self.info.task_id,
                               user_id=self.info.user_id, site=self.info.site)
        loop = asyncio.get_running_loop()
        self._takeover_timer = loop.create_task(
            self._takeover_timeout(self._mgr.settings.takeover_max_seconds))

    def give_back(self) -> None:
        if not self.takeover_active:
            raise TakeoverError("takeover is not active")
        self._end_takeover()
        self._mgr.audit.record("takeover_end", task_id=self.info.task_id,
                               user_id=self.info.user_id, site=self.info.site,
                               input_events=self.input_events)

    def _end_takeover(self) -> None:
        self.info.mode = "agent"
        self._agent_turn.set()
        t, self._takeover_timer = self._takeover_timer, None
        if t and t is not asyncio.current_task():
            t.cancel()

    async def _takeover_timeout(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        await self._mgr.close(self.info.task_id, persist=False, reason="takeover_timeout")

    async def takeover_input(self, event: Mapping[str, Any]) -> None:
        """Forward ONE validated user input to the page. Content is not logged or recorded; only a
        count is kept. Refused unless takeover is active."""
        if not self.takeover_active or self.closed:
            raise TakeoverError("takeover is not active")
        kind = event.get("kind")
        if kind == "click":
            w, h = self._raw.viewport()
            x, y = event.get("x"), event.get("y")
            if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < w and 0 <= y < h):
                raise TakeoverError("click outside the page")
            await self._raw.pointer_click(x, y)
        elif kind == "type":
            text = event.get("text")
            if not isinstance(text, str) or not (0 < len(text) <= MAX_TYPE_CHARS):
                raise TakeoverError("bad text input")
            await self._raw.type_text(text)
        elif kind == "key":
            key = event.get("key")
            if key not in ALLOWED_KEYS:
                raise TakeoverError("key not allowed")
            await self._raw.press_key("Space" if key == "Space" else str(key))
        elif kind == "scroll":
            dy = event.get("dy")
            if not isinstance(dy, int):
                raise TakeoverError("bad scroll")
            await self._raw.scroll(max(-2000, min(2000, dy)))
        else:
            raise TakeoverError("unknown input")
        self.input_events += 1

    def current_host(self) -> str:
        return _host(self._raw.current_url())


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


@dataclass
class _Entry:
    session: TaskSession | None = None
    info: SessionInfo | None = None
    persist_ok: bool = True
    closing: bool = False
    raw: LiveBrowserSession | None = field(default=None, repr=False)


class SessionManager:
    def __init__(
        self,
        backend: BrowserBackend,
        vault: StorageVault | None,
        settings: BrowserSettings | None = None,
        *,
        audit: AuditLog | None = None,
        paused: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.backend, self.vault = backend, vault
        self.settings = settings or BrowserSettings()
        self.audit = audit or AuditLog()
        self._paused = paused or (lambda: False)
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._close_listeners: list[Callable[[str], None]] = []

    # ---- queries
    def get(self, task_id: str) -> TaskSession | None:
        e = self._entries.get(task_id)
        return e.session if e else None

    def active(self) -> list[SessionInfo]:
        return [e.info for e in self._entries.values() if e.info]

    def on_close(self, listener: Callable[[str], None]) -> None:
        self._close_listeners.append(listener)

    # ---- open
    async def open(
        self,
        user_id: str,
        site: str,
        task_id: str,
        *,
        policy: NetworkPolicy,
        limits: ResourceLimits | None = None,
        recorder: StepRecorder | None = None,
        use_vault: bool = True,
    ) -> TaskSession:
        def refuse(why: str) -> SessionRefused:
            self.audit.record("refused", task_id=task_id, user_id=user_id, site=site, reason=why)
            return SessionRefused(why)

        s = self.settings
        if not s.user_allowed(user_id):
            raise refuse("browser is off for this user")
        if self._paused():
            raise refuse("paused by the kill switch")
        if task_id in self._entries:
            raise refuse("task already has a session")
        if len(self._entries) >= s.max_global:
            raise refuse("global browser limit reached")
        if sum(1 for e in self._entries.values() if e.info and e.info.user_id == user_id) \
                >= s.max_per_user:
            raise refuse("per-user browser limit reached")
        limits = limits or ResourceLimits(
            s.timeout_ms, s.task_max_seconds, s.max_pages, s.max_downloads)
        info = SessionInfo(task_id, user_id, site, self._clock(), "agent")
        entry = _Entry(info=info)
        self._entries[task_id] = entry  # reserve the slot BEFORE any await
        counter = LimitCounter(limits)
        counter.on_violation = lambda kind, detail: self.audit.record(
            kind, task_id=task_id, user_id=user_id, site=site, detail=detail)
        try:
            state = self.vault.load(user_id, site) if (self.vault and use_vault) else None
            raw = await self.backend.open(SessionSpec(
                user_id, site, task_id, policy, limits, counter, state))
            entry.raw = raw
            sess = TaskSession(self, info, raw, policy, counter, recorder)
            entry.session = sess
            sess._deadline_timer = asyncio.get_running_loop().create_task(
                self._deadline(task_id, limits.max_seconds))
        except BaseException:
            self._entries.pop(task_id, None)
            raise
        self.audit.record("session_open", task_id=task_id, user_id=user_id, site=site,
                          backend=self.backend.name, restored_login=state is not None,
                          hosts=len(policy.allowed_hosts))
        return sess

    async def _deadline(self, task_id: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        await self.close(task_id, persist=False, reason="deadline")

    async def reap_expired(self) -> int:
        """Close sessions older than their deadline (belt and braces next to the timers)."""
        now = self._clock()
        n = 0
        for e in list(self._entries.values()):
            if e.info and e.session and now - e.info.started_at >= \
                    e.session._counter.limits.max_seconds:
                await self.close(e.info.task_id, persist=False, reason="deadline")
                n += 1
        return n

    # ---- close / kill
    async def close(self, task_id: str, *, persist: bool = True, reason: str = "done") -> bool:
        entry = self._entries.get(task_id)
        if entry is None or entry.closing:
            return False
        entry.closing = True
        sess, info = entry.session, entry.info
        try:
            if sess is not None:
                sess.closed = True
                sess.close_reason = reason
                for t in (sess._takeover_timer, sess._deadline_timer):
                    if t and t is not asyncio.current_task():
                        t.cancel()
                sess._agent_turn.set()  # wake any waiting call so it sees "closed"
                clean = sess.info.mode == "agent" and not sess._counter.tripped
                if persist and self.vault and clean:
                    with contextlib.suppress(Exception):
                        state = await sess._raw.storage_state()
                        self.vault.save(info.user_id, info.site, state)  # type: ignore[union-attr]
                with contextlib.suppress(Exception):
                    await sess._raw.close()
        finally:
            self._entries.pop(task_id, None)
            if info:
                self.audit.record("session_close", task_id=task_id, user_id=info.user_id,
                                  site=info.site, reason=reason,
                                  seconds=round(self._clock() - info.started_at, 1))
            for cb in self._close_listeners:
                with contextlib.suppress(Exception):
                    cb(task_id)
        return True

    async def kill_task(self, task_id: str, reason: str = "abort") -> bool:
        return await self.close(task_id, persist=False, reason=f"killed:{reason}")

    async def kill_user(self, user_id: str, reason: str = "user") -> int:
        ids = [t for t, e in self._entries.items() if e.info and e.info.user_id == user_id]
        await asyncio.gather(*(self.kill_task(t, reason) for t in ids))
        return len(ids)

    async def kill_all(self, reason: str = "kill_switch") -> int:
        """Kill switch: close every session now, no vault writes, tokens revoked via listeners."""
        ids = list(self._entries)
        await asyncio.gather(*(self.kill_task(t, reason) for t in ids))
        if ids:
            self.audit.record("kill_all", reason=reason, count=len(ids))
        return len(ids)

    @contextlib.asynccontextmanager
    async def session(self, *args: Any, **kw: Any):  # type: ignore[no-untyped-def]
        sess = await self.open(*args, **kw)
        try:
            yield sess
        except BaseException:
            await self.close(sess.info.task_id, persist=False, reason="error")
            raise
        else:
            await self.close(sess.info.task_id)


