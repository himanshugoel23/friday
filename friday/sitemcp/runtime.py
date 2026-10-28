# ruff: noqa: E501
"""Session pool: ONE shared browser process (see chromium.py), one context per (user, site), hard caps, idle timeout,
memory guard. Sized for a 1 GB droplet: defaults are 2 sessions open, 1 page working at a time."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from friday.connectors.browser.port import BrowserSession
from friday.sitemcp.guard import MemoryGuard, PoolBusy, RateLimiter, RobotsPolicy, SafeSession


class BrowserFactory(Protocol):
    async def open(self, kb: dict[str, Any], storage_state: dict[str, Any] | None) -> BrowserSession: ...

    async def aclose(self) -> None: ...


class SessionVault(Protocol):
    def load(self, user_id: str, site: str) -> dict[str, Any] | None: ...

    def save(self, user_id: str, site: str, state: dict[str, Any]) -> None: ...

    def disconnect(self, user_id: str, site: str) -> None: ...

    def disconnect_user(self, user_id: str) -> int: ...


@dataclass
class SiteSession:
    user_id: str
    site: str
    safe: SafeSession
    created: float
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    location: str = ""
    otp_task_id: str = ""
    cooldown_until: float = 0.0  # after 'blocked': no more page loads until then (no retry loops)
    block_reason: str = ""


class SessionPool:
    def __init__(self, factory: BrowserFactory, *, vault: SessionVault | None = None, robots: RobotsPolicy | None = None,
                 limiter: RateLimiter | None = None, memory: MemoryGuard | None = None, max_sessions: int = 2,
                 max_pages: int = 1, idle_s: float = 240.0, page_wait_s: float = 15.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.factory, self.vault, self.robots = factory, vault, robots
        self.limiter = limiter or RateLimiter()
        self.memory = memory or MemoryGuard()
        self.max_sessions, self.idle_s, self.page_wait_s, self._clock = max_sessions, idle_s, page_wait_s, clock
        self._pages = asyncio.Semaphore(max_pages)
        self._sessions: dict[tuple[str, str], SiteSession] = {}
        self._create_lock = asyncio.Lock()

    # ---- introspection
    def open_count(self) -> int:
        return len(self._sessions)

    def users(self) -> set[str]:
        return {u for u, _ in self._sessions}

    # ---- lifecycle
    async def reap(self) -> int:
        """Close sessions idle longer than ``idle_s`` (and not in use). Returns how many."""
        now, n = self._clock(), 0
        for key, s in list(self._sessions.items()):
            if now - s.last_used > self.idle_s and not s.lock.locked():
                await self._close(key)
                n += 1
        return n

    async def _close(self, key: tuple[str, str]) -> None:
        s = self._sessions.pop(key, None)
        if s is not None:
            with contextlib.suppress(Exception):
                await s.safe.close()

    async def _make_room(self) -> None:
        await self.reap()
        if len(self._sessions) < self.max_sessions:
            return
        idle = sorted((s for s in self._sessions.values() if not s.lock.locked()), key=lambda s: s.last_used)
        if idle:
            await self._close((idle[0].user_id, idle[0].site))  # evict the least recently used idle session
        if len(self._sessions) >= self.max_sessions:
            raise PoolBusy("capacity")

    async def _get(self, user_id: str, site: str, kb: dict[str, Any], exempt: frozenset[str]) -> SiteSession:
        key = (user_id, site)
        s = self._sessions.get(key)
        if s is not None:
            return s
        async with self._create_lock:
            s = self._sessions.get(key)
            if s is not None:
                return s
            await self._make_room()
            if not self.memory.ok():
                raise PoolBusy("low_memory")
            state = self.vault.load(user_id, site) if self.vault else None
            try:
                inner = await self.factory.open(kb, state)
            except PoolBusy:
                raise
            except Exception as e:  # noqa: BLE001
                raise PoolBusy(f"browser_unavailable:{type(e).__name__}") from None
            safe = SafeSession(inner, kb, user_id, limiter=self.limiter, robots=self.robots, exempt_clicks=exempt)
            safe.logged_in = state is not None
            now = self._clock()
            s = SiteSession(user_id, site, safe, now, now)
            self._sessions[key] = s
            return s

    @contextlib.asynccontextmanager
    async def session(self, user_id: str, kb: dict[str, Any]) -> AsyncIterator[SiteSession]:
        site = kb["site"]
        proceed = (kb.get("checkout") or {}).get("proceed") or ""
        exempt = frozenset({proceed}) if proceed and (kb["checkout"].get("proceed_verified")) else frozenset()
        s = await self._get(user_id, site, kb, exempt)
        try:
            await asyncio.wait_for(self._pages.acquire(), self.page_wait_s)
        except TimeoutError:
            raise PoolBusy("page_cap") from None
        try:
            async with s.lock:
                try:
                    yield s
                finally:
                    s.last_used = self._clock()
        finally:
            self._pages.release()

    async def forget_user(self, user_id: str) -> int:
        """'Forget my logins': close this user's contexts and erase their stored cookies. Returns erased vault slots."""
        for key in [k for k in self._sessions if k[0] == user_id]:
            await self._close(key)
        return self.vault.disconnect_user(user_id) if self.vault else 0

    async def close_site(self, user_id: str, site: str) -> None:
        await self._close((user_id, site))

    async def aclose(self) -> None:
        for key in list(self._sessions):
            await self._close(key)
        await self.factory.aclose()
