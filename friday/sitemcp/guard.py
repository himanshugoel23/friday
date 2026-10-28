# ruff: noqa: E501
"""Safety wrappers around any BrowserSession: payment denylist, robots.txt, polite rate limits, block detection,
memory guard. No captcha solving, no fingerprint tricks, no proxies: when a site blocks, we stop (status 'blocked')."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from friday.connectors.browser.port import BrowserError, BrowserSession, ElementNotFound
from friday.sitemcp.knowledge import smells_like_payment_selector, smells_like_payment_url

USER_AGENT_NAME = "FridayBot"  # robots.txt token; we do NOT pretend to be anything else


class PaymentBlocked(BrowserError):
    """A click / fill / goto that looks like paying or placing an order was refused."""


class SiteBlocked(Exception):
    """The site showed a challenge / denial. Carries a short reason; the caller returns status 'blocked'."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RateLimited(Exception):
    pass


class PoolBusy(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ----------------------------------------------------------------------------- memory
def read_mem_available_mb(path: str = "/proc/meminfo") -> float | None:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


class MemoryGuard:
    """Refuses new browser sessions when available RAM is below ``min_free_mb``. Unknown reading = allow (not Linux)."""

    def __init__(self, min_free_mb: float = 250.0, reader: Callable[[], float | None] = read_mem_available_mb) -> None:
        self.min_free_mb, self._reader = min_free_mb, reader

    def ok(self) -> bool:
        v = self._reader()
        return v is None or v >= self.min_free_mb


# ----------------------------------------------------------------------------- rate limit
class RateLimiter:
    """Polite pacing: at least ``site_min_s`` between any two page loads on a site and ``user_min_s`` per (site, user)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._clock, self._sleep = clock, sleep
        self._site: dict[str, float] = {}
        self._user: dict[tuple[str, str], float] = {}

    async def wait(self, site: str, user: str, site_min_s: float, user_min_s: float, max_wait_s: float) -> None:
        now = self._clock()
        ready = max(self._site.get(site, -1e9) + site_min_s, self._user.get((site, user), -1e9) + user_min_s)
        delay = max(0.0, ready - now)
        if delay > max_wait_s:
            raise RateLimited(f"{delay:.0f}s")
        # reserve the slot first so concurrent callers queue behind each other
        self._site[site] = self._user[(site, user)] = now + delay
        if delay:
            await self._sleep(delay)


# ----------------------------------------------------------------------------- robots.txt
Fetcher = Callable[[str], Awaitable[tuple[int, str]]]  # url -> (status, text)


async def http_fetch(url: str) -> tuple[int, str]:  # pragma: no cover - real network, never used in tests
    import httpx

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, headers={"User-Agent": f"{USER_AGENT_NAME}/1 (personal assistant; respects robots.txt)"}) as c:
        r = await c.get(url)
        return r.status_code, r.text[:200_000]


class RobotsPolicy:
    """robots.txt for ANONYMOUS pages. Fetched once per host per ``ttl_s``. 404 = allowed; unreachable/5xx = NOT allowed (conservative)."""

    def __init__(self, fetch: Fetcher = http_fetch, clock: Callable[[], float] = time.monotonic, ttl_s: float = 3600.0) -> None:
        self._fetch, self._clock, self._ttl = fetch, clock, ttl_s
        self._cache: dict[str, tuple[float, RobotFileParser | None]] = {}

    async def allowed(self, url: str) -> bool:
        u = urlsplit(url)
        origin = f"{u.scheme}://{u.netloc}"
        hit = self._cache.get(origin)
        if hit is None or self._clock() - hit[0] > self._ttl:
            rp: RobotFileParser | None
            try:
                status, text = await self._fetch(origin + "/robots.txt")
            except Exception:  # noqa: BLE001
                status, text = 599, ""
            if status in (404, 410) or (status == 200 and not text.strip()):
                rp = None  # no rules
            elif status == 200:
                rp = RobotFileParser()
                rp.parse(text.splitlines())
            else:
                rp = RobotFileParser()
                rp.parse(["User-agent: *", "Disallow: /"])  # cannot read the rules: do not guess
            hit = (self._clock(), rp)
            self._cache[origin] = hit
        rp = hit[1]
        return True if rp is None else rp.can_fetch(USER_AGENT_NAME, url)


# ----------------------------------------------------------------------------- the safe session
class SafeSession:
    """Wraps a BrowserSession for one (user, site): payment denylist, domain check, robots (anonymous), pacing, block detection."""

    def __init__(self, inner: BrowserSession, kb: dict[str, Any], user_id: str, *, limiter: RateLimiter,
                 robots: RobotsPolicy | None, exempt_clicks: frozenset[str] = frozenset()) -> None:
        self.inner, self.kb, self.user_id = inner, kb, user_id
        self._limiter, self._robots = limiter, robots
        self._exempt = exempt_clicks  # exactly the knowledge 'checkout.proceed' selector, nothing else
        self.logged_in = False
        self.pages_loaded = 0
        self.clicked: list[str] = []  # selectors clicked (audit/tests; no page content)

    # ---- navigation
    async def goto(self, url: str) -> None:
        if smells_like_payment_url(url):
            raise PaymentBlocked("payment url refused")
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or (u.hostname or "") not in self.kb["domains"]:
            raise PaymentBlocked("host not in the site's domains")
        if not self.logged_in and self._robots is not None and not await self._robots.allowed(url):
            raise SiteBlocked("robots")
        rate = self.kb["rate"]
        try:
            await self._limiter.wait(self.kb["site"], self.user_id, rate["min_interval_s"], rate["per_user_min_interval_s"], rate["max_wait_s"])
        except RateLimited:
            raise
        await self.inner.goto(url)
        self.pages_loaded += 1
        await self.check_blocked()

    async def click(self, selector: str) -> None:
        if selector not in self._exempt and smells_like_payment_selector(selector):
            raise PaymentBlocked("payment control refused")
        self.clicked.append(selector)
        await self.inner.click(selector)
        await self.check_blocked()

    async def fill(self, selector: str, value: str) -> None:
        if smells_like_payment_selector(selector):
            raise PaymentBlocked("payment field refused")
        await self.inner.fill(selector, value)

    async def check_blocked(self) -> None:
        st = getattr(self.inner, "last_status", None)
        if st in (401, 403, 429):
            raise SiteBlocked(f"http_{st}")
        b = self.kb["blocked"]
        for sel in b.get("selectors", []):
            if await self.inner.query_all(sel):
                raise SiteBlocked("challenge")
        try:
            body = (await self.inner.text("body")).lower()
        except ElementNotFound:
            return
        for m in b.get("markers", []):
            if m in body:
                raise SiteBlocked("challenge")

    # ---- reads / pass-through
    async def text(self, selector: str) -> str:
        return await self.inner.text(selector)

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None) -> list[dict[str, str]]:
        return await self.inner.query_all(selector, fields)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        await self.inner.wait_for(selector, timeout_ms)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return await self.inner.screenshot(mask_selectors)

    async def storage_state(self) -> dict:
        return await self.inner.storage_state()  # type: ignore[attr-defined]

    def current_url(self) -> str:
        return self.inner.current_url()  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self.inner.close()

    async def exists(self, selector: str) -> bool:
        return bool(selector) and bool(await self.inner.query_all(selector))
