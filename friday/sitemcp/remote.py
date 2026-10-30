# ruff: noqa: E501
"""A MANAGED REMOTE browser (Browserbase / Steel / any Chrome DevTools Protocol websocket) with the same interface as
``SharedChromium`` (open / aclose / available), so the session pool, the live probe and the browser agent can use it unchanged.
See docs/REMOTE_BROWSER.md.

PRIVACY: the page content (including logged-in pages) passes through a THIRD PARTY. Switch FRIDAY_REMOTE_BROWSER_ENABLED is OFF.

FOUNDER'S HARD RULES (enforced here and asserted in tests/remotebrowser): we never ask a provider for a proxy, residential IP,
stealth, anti-detection, fingerprint, captcha solving or 'verified/advanced stealth', and never set a user agent or navigator
override. The create-session body below sends those features explicitly OFF (providers turn some of them on by default, e.g.
Browserbase ``solveCaptchas`` defaults to true) and nothing else beyond a time cap. Same NetworkPolicy default-deny guard,
same light resource blocking, one isolated context per user, the remote session is released as soon as the last context
closes (cost), a per-run time cap and a daily session + INR estimate cap.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from friday.connectors.browser.playwright_session import playwright_installed
from friday.connectors.browser.port import BrowserError
from friday.core.logging import get_logger
from friday.sitemcp.chromium import ContextSession, open_guarded
from friday.sitemcp.guard import PoolBusy

log = get_logger(__name__)

PROVIDERS = ("browserbase", "steel", "cdp")
BROWSERBASE_URL = "https://api.browserbase.com/v1/sessions"
STEEL_URL = "https://api.steel.dev/v1/sessions"  # UNVERIFIED: REST path from memory (docs show the SDK only)


class Http(Protocol):
    async def request(self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]: ...


class HttpxClient:
    async def request(self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.request(method, url, headers=headers, json=body)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data if isinstance(data, dict) else {}


class RemoteSession:
    def __init__(self, session_id: str, cdp_url: str) -> None:
        self.id, self.cdp_url = session_id, cdp_url


def _secret(v: Any) -> str:
    if v is None:
        return ""
    return str(v.get_secret_value() if hasattr(v, "get_secret_value") else v).strip()


class RemoteProvider(Protocol):
    name: str

    def configured(self) -> bool: ...
    async def create(self, http: Http, max_run_s: int) -> RemoteSession: ...
    async def release(self, http: Http, s: RemoteSession) -> None: ...


class BrowserbaseProvider:
    """POST https://api.browserbase.com/v1/sessions (header X-BB-API-Key); response ``id`` + ``connectUrl`` (a CDP websocket).
    Release: POST /v1/sessions/{id} with {"status": "REQUEST_RELEASE"}. Create and release were read from the official docs on
    2026-10-29; NEVER RUN against the real service."""

    name = "browserbase"

    def __init__(self, api_key: str, project_id: str = "") -> None:
        self.key, self.project_id = api_key, project_id

    def configured(self) -> bool:
        return bool(self.key)

    def _h(self) -> dict[str, str]:
        return {"X-BB-API-Key": self.key, "Content-Type": "application/json"}

    @staticmethod
    def body(project_id: str, max_run_s: int) -> dict[str, Any]:
        b: dict[str, Any] = {
            "timeout": max(60, int(max_run_s)),  # seconds; the provider ends the session by itself (cost backstop)
            "browserSettings": {"solveCaptchas": False,  # provider default is TRUE: switched off explicitly
                                "verified": False,  # no 'advanced stealth / verified' mode
                                "recordSession": False, "logSession": False,  # no recording of page content at the provider
                                "blockAds": False},
        }
        if project_id:
            b["projectId"] = project_id
        return b  # no proxies, no fingerprint, no os, no user agent

    async def create(self, http: Http, max_run_s: int) -> RemoteSession:
        code, data = await http.request("POST", BROWSERBASE_URL, self._h(), self.body(self.project_id, max_run_s))
        if code >= 300 or not data.get("connectUrl") or not data.get("id"):
            raise BrowserError(f"remote browser: create session failed (browserbase http {code})")
        return RemoteSession(str(data["id"]), str(data["connectUrl"]))

    async def release(self, http: Http, s: RemoteSession) -> None:
        await http.request("POST", f"{BROWSERBASE_URL}/{s.id}", self._h(), {"status": "REQUEST_RELEASE"})


class SteelProvider:
    """UNVERIFIED create/release REST calls: the Steel docs page we could read shows only the SDK (``sessions.create()``,
    ``websocketUrl`` + ``&apiKey=<key>`` for connect_over_cdp, ``sessions.release(id)``). Endpoint, header name
    (``steel-api-key``) and body field names are from memory; check before trusting."""

    name = "steel"

    def __init__(self, api_key: str) -> None:
        self.key = api_key

    def configured(self) -> bool:
        return bool(self.key)

    def _h(self) -> dict[str, str]:
        return {"steel-api-key": self.key, "Content-Type": "application/json"}

    @staticmethod
    def body(max_run_s: int) -> dict[str, Any]:
        return {"useProxy": False, "solveCaptcha": False, "timeout": max(1, int(max_run_s)) * 1000}  # timeout in ms (UNVERIFIED)

    async def create(self, http: Http, max_run_s: int) -> RemoteSession:
        code, data = await http.request("POST", STEEL_URL, self._h(), self.body(max_run_s))
        ws = str(data.get("websocketUrl") or "")
        if code >= 300 or not data.get("id") or not ws:
            raise BrowserError(f"remote browser: create session failed (steel http {code})")
        return RemoteSession(str(data["id"]), f"{ws}{'&' if '?' in ws else '?'}apiKey={self.key}")

    async def release(self, http: Http, s: RemoteSession) -> None:
        await http.request("POST", f"{STEEL_URL}/{s.id}/release", self._h(), None)


class CdpProvider:
    """Generic: the founder pastes a ready-made CDP websocket URL (may contain a token, so it is a secret). Nothing to create or
    release over HTTP; closing the connection ends our use. THE TESTED PATH."""

    name = "cdp"

    def __init__(self, url: str) -> None:
        self.url = url

    def configured(self) -> bool:
        return self.url.startswith(("ws://", "wss://"))

    async def create(self, http: Http, max_run_s: int) -> RemoteSession:
        return RemoteSession("cdp", self.url)

    async def release(self, http: Http, s: RemoteSession) -> None:
        return None


def provider_from_settings(settings: Any) -> RemoteProvider:
    name = str(getattr(settings, "remote_browser_provider", "browserbase") or "browserbase").lower()
    if name == "steel":
        return SteelProvider(_secret(getattr(settings, "steel_api_key", None)))
    if name == "cdp":
        return CdpProvider(_secret(getattr(settings, "remote_browser_cdp_url", None)))
    return BrowserbaseProvider(_secret(getattr(settings, "browserbase_api_key", None)), str(getattr(settings, "browserbase_project_id", "") or ""))


class RemoteBudget:
    """Daily cap on remote sessions and on the INR ESTIMATE (rate per minute is a setting, a GUESS to verify on the provider's
    pricing page). Persisted so a restart does not reset it; the day rolls over at UTC midnight."""

    def __init__(self, path: Path, *, max_sessions: int, max_inr: float, inr_per_min: float,
                 today: Callable[[], str] = lambda: datetime.now(UTC).date().isoformat()) -> None:
        self.path, self.max_sessions, self.max_inr, self.inr_per_min, self._today = Path(path), max_sessions, max_inr, inr_per_min, today

    def _load(self) -> dict[str, Any]:
        try:
            d = json.loads(self.path.read_text())
            if isinstance(d, dict) and d.get("date") == self._today():
                return {"date": d["date"], "sessions": int(d.get("sessions", 0)), "inr": float(d.get("inr", 0.0))}
        except (OSError, ValueError, TypeError):
            pass
        return {"date": self._today(), "sessions": 0, "inr": 0.0}

    def _save(self, d: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(d, f)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def usage(self) -> dict[str, Any]:
        return self._load()

    def allow(self) -> str:
        """'' when another session may start, else the reason."""
        d = self._load()
        if d["sessions"] >= self.max_sessions:
            return "remote_daily_session_cap"
        if d["inr"] + self.inr_per_min > self.max_inr:
            return "remote_daily_inr_cap"
        return ""

    def start(self) -> None:
        d = self._load()
        d["sessions"] += 1
        d["inr"] += self.inr_per_min  # a started session is billed at least one minute (assumption)
        self._save(d)

    def end(self, elapsed_s: float) -> None:
        extra = max(0, math.ceil(elapsed_s / 60.0) - 1)
        if extra:
            d = self._load()
            d["inr"] += extra * self.inr_per_min
            self._save(d)


class RemoteContextSession(ContextSession):
    """One user's context on the remote browser. Closing it tells the owner; the LAST one releases the remote session."""

    def __init__(self, pw: Any, browser: Any, context: Any, page: Any, timeout_ms: int, *, on_close: Callable[[], Any] | None = None) -> None:
        super().__init__(pw, browser, context, page, timeout_ms)
        self._on_close = on_close
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await super().close()
        if self._on_close is not None:
            with contextlib.suppress(Exception):
                await self._on_close()


async def _connect_playwright(cdp_url: str, timeout_ms: int) -> tuple[Any, Any]:
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=timeout_ms)
    except Exception:
        await pw.stop()
        raise
    return pw, browser


class RemoteChromium:
    """Same surface as ``SharedChromium``. ONE remote session at a time, created lazily on the first ``open``."""

    def __init__(self, provider: RemoteProvider, *, budget: RemoteBudget, http: Http | None = None, max_run_s: int = 120,
                 timeout_ms: int = 15000, connect: Callable[[str, int], Any] = _connect_playwright,
                 clock: Callable[[], float] = time.monotonic, needs_playwright: bool = True) -> None:
        self.provider, self.budget, self.http = provider, budget, http or HttpxClient()
        self.max_run_s, self.timeout_ms, self._connect, self._clock = int(max_run_s), timeout_ms, connect, clock
        self._needs_pw = needs_playwright
        self._pw: Any = None
        self._browser: Any = None
        self._remote: RemoteSession | None = None
        self._started = 0.0
        self._open = 0
        self._watchdog: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.ended_reason = ""

    @property
    def label(self) -> str:
        return f"remote:{self.provider.name}"

    def available(self) -> bool:
        return (playwright_installed() or not self._needs_pw) and self.provider.configured()

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if not self.provider.configured():
                raise BrowserError(f"remote browser ({self.provider.name}) is not configured: key or URL missing")
            why = self.budget.allow()
            if why:
                raise PoolBusy(why)
            self.budget.start()  # counted when we ask, even if the connect then fails (we may still be billed)
            remote = await self.provider.create(self.http, self.max_run_s)
            try:
                self._pw, self._browser = await self._connect(remote.cdp_url, self.timeout_ms)
            except Exception:
                with contextlib.suppress(Exception):
                    await self.provider.release(self.http, remote)
                raise BrowserError("remote browser: could not connect over CDP") from None  # message never carries the URL (token)
            self._remote, self._started, self.ended_reason = remote, self._clock(), ""
            self._watchdog = asyncio.ensure_future(self._cap_watch())
            return self._browser

    async def _cap_watch(self) -> None:
        await asyncio.sleep(self.max_run_s)
        log.info("remote browser: per-run time cap reached, closing the remote session")
        await self._end("time_cap", from_watchdog=True)

    async def open(self, kb: dict[str, Any], storage_state: dict[str, Any] | None) -> RemoteContextSession:
        browser = await self._ensure()
        self._open += 1
        try:
            # no locale / user agent override: the provider's default browser, as is
            return await open_guarded(browser, self._pw, kb, storage_state, self.timeout_ms, RemoteContextSession,
                                      locale=None, on_close=self._context_closed)
        except Exception:
            self._open -= 1
            raise

    async def _context_closed(self) -> None:
        self._open = max(0, self._open - 1)
        if self._open == 0:
            await self._end("done")  # release the paid session as soon as nobody uses it

    async def _end(self, reason: str, *, from_watchdog: bool = False) -> None:
        remote, browser, pw = self._remote, self._browser, self._pw
        if remote is None and browser is None:
            return
        self._remote = self._browser = self._pw = None
        self.ended_reason = reason
        if self._watchdog is not None and not from_watchdog:
            self._watchdog.cancel()
        self._watchdog = None
        self._open = 0
        for closer in (browser.close if browser is not None else None, pw.stop if pw is not None else None):
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer()
        if remote is not None:
            with contextlib.suppress(Exception):
                await self.provider.release(self.http, remote)
            self.budget.end(self._clock() - self._started)

    async def aclose(self) -> None:
        await self._end("closed")


def is_remote(settings: Any) -> bool:
    return bool(getattr(settings, "remote_browser_enabled", False))


def make_factory(settings: Any, *, http: Http | None = None, connect: Callable[[str, int], Any] | None = None) -> Any:
    """The browser every caller should use: remote when FRIDAY_REMOTE_BROWSER_ENABLED, else the local shared Chromium."""
    if not is_remote(settings):
        from friday.sitemcp.chromium import SharedChromium

        return SharedChromium()
    budget = RemoteBudget(Path(getattr(settings, "site_mcp_dir", "var/sitemcp")) / "remote_usage.json",
                          max_sessions=int(getattr(settings, "remote_browser_daily_sessions", 20)),
                          max_inr=float(getattr(settings, "remote_browser_daily_inr", 50.0)),
                          inr_per_min=float(getattr(settings, "remote_browser_inr_per_min", 1.0)))
    kw: dict[str, Any] = {"connect": connect} if connect is not None else {}
    return RemoteChromium(provider_from_settings(settings), budget=budget, http=http, max_run_s=int(getattr(settings, "remote_browser_max_run_s", 120)), **kw)


def make_factory_class_for_probe(settings: Any) -> tuple[Callable[[], Any], Callable[[], bool]]:
    """(maker, available) pair for ProbeJob."""
    from friday.sitemcp.chromium import SharedChromium

    if not is_remote(settings):
        return SharedChromium, SharedChromium.available
    return (lambda: make_factory(settings)), (lambda: make_factory(settings).available())
