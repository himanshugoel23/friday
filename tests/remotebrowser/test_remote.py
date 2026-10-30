# ruff: noqa: E501
"""RemoteChromium on fakes only (no network, no Playwright launch): create-session bodies never ask for proxy / stealth /
fingerprint / captcha solving / user agent, the same default-deny guard, per-user contexts, release after use, time cap,
daily caps, labels in the probe report."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from friday.connectors.browser.port import BrowserError
from friday.core.config import Settings
from friday.sitemcp.guard import MemoryGuard, PoolBusy
from friday.sitemcp.live import render_report, run_control
from friday.sitemcp.probestore import ProbeStore
from friday.sitemcp.remote import (
    BrowserbaseProvider,
    CdpProvider,
    RemoteBudget,
    RemoteChromium,
    SteelProvider,
    is_remote,
    make_factory,
    make_factory_class_for_probe,
)
from friday.sitemcp.runtime import SessionPool
from friday.sitemcp.scheduler import ProbeJob

ROOT = Path(__file__).resolve().parents[2]
KB = {"site": "zepto", "domains": ["example.com"], "rate": {"min_interval_s": 0.0, "per_user_min_interval_s": 0.0, "max_wait_s": 1.0}, "blocked": {"selectors": [], "markers": []}, "checkout": {}, "version": 1, "status": "unverified"}
FORBIDDEN_KEYS = {"proxies", "proxy", "useproxy", "fingerprint", "useragent", "user_agent", "stealth", "advancedstealth", "os", "solvecaptcha", "solvecaptchas",
                  "verified", "captcha", "geolocation", "stealthconfig", "deviceconfig", "extensionid", "context", "locale"}
SECRET = "sk-test-SECRET-123"
RELEASE = {"status": "REQUEST_RELEASE"}


class FakeHttp:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def request(self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if self.fail:
            return 500, {}
        if url.endswith("/sessions") and method == "POST":
            if "browserbase" in url:
                return 201, {"id": "bb1", "connectUrl": "wss://connect.example/bb1"}
            return 200, {"id": "st1", "websocketUrl": "wss://connect.example/st1?sessionId=st1"}
        return 200, {}


class FakeRoute:
    def __init__(self, url: str, rtype: str = "document") -> None:
        self.request = SimpleNamespace(url=url, resource_type=rtype)
        self.verdict = ""

    async def abort(self) -> None:
        self.verdict = "abort"

    async def continue_(self) -> None:
        self.verdict = "continue"

    async def fallback(self) -> None:
        self.verdict = "fallback"


class FakePage:
    url = "https://example.com/"

    async def goto(self, url: str, wait_until: str = "") -> Any:
        return SimpleNamespace(status=200)

    async def inner_text(self, sel: str) -> str:
        return "Example Domain"

    async def screenshot(self, mask: Any = None) -> bytes:
        return b"\x89PNG"


class FakeContext:
    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts, self.routes, self.closed = opts, [], False

    def set_default_timeout(self, ms: int) -> None: ...

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append(handler)

    async def new_page(self) -> FakePage:
        return FakePage()

    async def close(self) -> None:
        self.closed = True

    async def fire(self, url: str, rtype: str = "document") -> str:
        """Playwright runs the most recently registered handler first; fallback() passes to the next one."""
        r = FakeRoute(url, rtype)
        for h in reversed(self.routes):
            await h(r)
            if r.verdict != "fallback":
                break
        return r.verdict


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def new_context(self, **opts: Any) -> FakeContext:
        c = FakeContext(opts)
        self.contexts.append(c)
        return c

    async def close(self) -> None:
        self.closed = True


async def _noop() -> None: ...


class Env:
    def __init__(self, tmp_path: Path, provider: Any, *, http: FakeHttp | None = None, max_run_s: float = 120, sessions: int = 20, inr: float = 50.0, today: str = "2026-10-29") -> None:
        self.http = http or FakeHttp()
        self.browsers: list[FakeBrowser] = []
        self.urls: list[str] = []
        self.day = [today]
        self.budget = RemoteBudget(tmp_path / "usage.json", max_sessions=sessions, max_inr=inr, inr_per_min=1.0, today=lambda: self.day[0])

        async def connect(url: str, timeout_ms: int) -> tuple[Any, Any]:
            self.urls.append(url)
            b = FakeBrowser()
            self.browsers.append(b)
            return SimpleNamespace(stop=_noop), b

        self.chrome = RemoteChromium(provider, budget=self.budget, http=self.http, max_run_s=max_run_s, connect=connect, needs_playwright=False)  # type: ignore[arg-type]


def _walk(d: Any):
    if isinstance(d, dict):
        for k, v in d.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(d, list):
        for v in d:
            yield from _walk(v)


def assert_no_evasion(body: dict[str, Any]) -> None:
    for k, v in _walk(body):
        if k.lower() in FORBIDDEN_KEYS:
            assert v is False, f"{k} must be absent or explicitly False, got {v!r}"
    flat = json.dumps(body).lower().replace("_", "")
    assert "proxies" not in body and "fingerprint" not in flat and "useragent" not in flat and "stealth" not in flat


# ------------------------------------------------------------------ hard rules
async def test_browserbase_create_body_asks_for_no_proxy_stealth_fingerprint_captcha_or_user_agent(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET, "proj1"))
    s = await e.chrome.open(KB, None)
    create = e.http.calls[0]
    assert create["method"] == "POST" and create["url"] == "https://api.browserbase.com/v1/sessions"
    assert create["headers"]["X-BB-API-Key"] == SECRET
    body = create["body"]
    assert_no_evasion(body)
    assert body["browserSettings"]["solveCaptchas"] is False and body["browserSettings"]["verified"] is False  # the provider default for captchas is ON
    assert body["browserSettings"]["recordSession"] is False
    assert body["projectId"] == "proj1" and body["timeout"] >= 60
    assert e.urls == ["wss://connect.example/bb1"]
    await s.close()


async def test_steel_create_body_asks_for_no_proxy_or_captcha_solving_and_key_goes_in_the_connect_url_only(tmp_path):
    e = Env(tmp_path, SteelProvider(SECRET))
    s = await e.chrome.open(KB, None)
    body = e.http.calls[0]["body"]
    assert_no_evasion(body)
    assert body["useProxy"] is False and body["solveCaptcha"] is False
    assert e.urls[0].endswith(f"&apiKey={SECRET}")
    await s.close()
    assert e.http.calls[-1]["url"].endswith("/st1/release")


def test_every_body_in_every_provider_is_clean_for_any_run_cap():
    for cap in (1, 60, 120, 900):
        assert_no_evasion(BrowserbaseProvider.body("p", cap))
        assert_no_evasion(BrowserbaseProvider.body("", cap))
        assert_no_evasion(SteelProvider.body(cap))


async def test_context_options_have_no_user_agent_locale_headers_or_other_overrides(tmp_path):
    e = Env(tmp_path, CdpProvider("wss://x.example/devtools"))
    await e.chrome.open(KB, None)
    opts = e.browsers[0].contexts[0].opts
    assert set(opts) == {"storage_state", "accept_downloads", "service_workers", "viewport", "permissions"}
    assert opts["accept_downloads"] is False and opts["permissions"] == []
    assert e.http.calls == []  # generic CDP path: no provider API call at all


# ------------------------------------------------------------------ same guard as the local browser
async def test_default_deny_guard_and_light_blocking_apply_to_the_remote_context(tmp_path):
    e = Env(tmp_path, CdpProvider("wss://x.example/devtools"))
    await e.chrome.open(KB, None)
    ctx = e.browsers[0].contexts[0]
    assert await ctx.fire("https://example.com/") == "continue"
    assert await ctx.fire("https://sub.example.com/a") == "continue"
    assert await ctx.fire("https://evil.example.net/") == "abort"
    assert await ctx.fire("http://169.254.169.254/latest/meta-data") == "abort"
    assert await ctx.fire("https://example.com/p.png", "image") == "abort"
    assert await ctx.fire("https://example.com/f.woff", "font") == "abort"


# ------------------------------------------------------------------ lifecycle, cost
async def test_one_remote_session_many_user_contexts_released_after_the_last_one_closes(tmp_path):
    http = FakeHttp()
    e = Env(tmp_path, BrowserbaseProvider(SECRET), http=http)
    a = await e.chrome.open(KB, None)
    b = await e.chrome.open(KB, {"cookies": [], "origins": []})
    assert len([c for c in http.calls if c["method"] == "POST" and c["url"].endswith("/sessions")]) == 1
    assert len(e.browsers[0].contexts) == 2 and e.browsers[0].contexts[0] is not e.browsers[0].contexts[1]
    await a.close()
    assert not e.browsers[0].closed and not any(c["body"] == RELEASE for c in http.calls)
    await b.close()
    assert e.browsers[0].closed
    last = http.calls[-1]
    assert last["url"] == "https://api.browserbase.com/v1/sessions/bb1" and last["body"] == RELEASE
    c = await e.chrome.open(KB, None)  # a later use creates a fresh session
    assert len(e.browsers) == 2
    await c.close()


async def test_aclose_releases_and_is_idempotent(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET))
    await e.chrome.open(KB, None)
    await e.chrome.aclose()
    await e.chrome.aclose()
    assert sum(1 for c in e.http.calls if c["body"] == RELEASE) == 1


async def test_per_run_time_cap_closes_and_releases_the_remote_session(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET), max_run_s=0.05)
    await e.chrome.open(KB, None)
    await asyncio.sleep(0.2)
    assert e.browsers[0].closed and e.chrome.ended_reason == "time_cap"
    assert any(c["body"] == RELEASE for c in e.http.calls)


async def test_connect_failure_releases_the_session_and_never_leaks_the_url_or_key(tmp_path):
    e = Env(tmp_path, SteelProvider(SECRET))

    async def bad(url: str, t: int) -> Any:
        raise RuntimeError(f"cannot reach {url}")

    e.chrome._connect = bad
    with pytest.raises(BrowserError) as ei:
        await e.chrome.open(KB, None)
    assert SECRET not in str(ei.value) and "wss" not in str(ei.value)
    assert e.http.calls[-1]["url"].endswith("/release")


async def test_create_failure_is_a_clean_error(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET), http=FakeHttp(fail=True))
    with pytest.raises(BrowserError) as ei:
        await e.chrome.open(KB, None)
    assert SECRET not in str(ei.value)


# ------------------------------------------------------------------ caps
async def test_daily_session_cap_blocks_the_next_session_and_survives_a_restart(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET), sessions=2)
    for _ in range(2):
        await (await e.chrome.open(KB, None)).close()
    with pytest.raises(PoolBusy) as ei:
        await e.chrome.open(KB, None)
    assert ei.value.reason == "remote_daily_session_cap"
    e2 = Env(tmp_path, BrowserbaseProvider(SECRET), sessions=2)  # new process, same file
    with pytest.raises(PoolBusy):
        await e2.chrome.open(KB, None)
    e.day[0] = "2026-10-30"  # next day resets
    await (await e.chrome.open(KB, None)).close()


async def test_daily_inr_estimate_cap(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET), inr=2.0)
    await (await e.chrome.open(KB, None)).close()
    await (await e.chrome.open(KB, None)).close()
    with pytest.raises(PoolBusy) as ei:
        await e.chrome.open(KB, None)
    assert ei.value.reason == "remote_daily_inr_cap"
    assert e.budget.usage()["inr"] == pytest.approx(2.0)


def test_budget_charges_extra_minutes_at_close(tmp_path):
    b = RemoteBudget(tmp_path / "u.json", max_sessions=9, max_inr=99, inr_per_min=2.0)
    b.start()
    b.end(125)  # 3 started minutes, one already charged
    assert b.usage()["inr"] == pytest.approx(6.0) and b.usage()["sessions"] == 1


# ------------------------------------------------------------------ config, wiring, label
def test_off_by_default_and_local_factory_is_used():
    s = Settings()
    assert s.remote_browser_enabled is False and not is_remote(s)
    f = make_factory(s)
    assert type(f).__name__ == "SharedChromium" and f.label == "local"


def test_not_configured_means_unavailable(tmp_path):
    s = Settings(remote_browser_enabled=True, remote_browser_provider="browserbase", site_mcp_dir=str(tmp_path), browserbase_api_key=None)
    f = make_factory(s)
    assert f.label == "remote:browserbase" and f.available() is False
    s2 = Settings(remote_browser_enabled=True, remote_browser_provider="cdp", remote_browser_cdp_url="wss://x.example/ws", site_mcp_dir=str(tmp_path))
    f2 = make_factory(s2)
    assert f2.provider.configured() and f2.label == "remote:cdp"
    s3 = Settings(remote_browser_enabled=True, remote_browser_provider="steel", steel_api_key="k", site_mcp_dir=str(tmp_path))
    assert make_factory(s3).provider.configured()


async def test_not_configured_open_raises_without_any_http(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(""))
    with pytest.raises(BrowserError):
        await e.chrome.open(KB, None)
    assert e.http.calls == []


async def test_session_pool_runs_on_the_remote_browser(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET))
    pool = SessionPool(e.chrome, memory=MemoryGuard(0.0))
    async with pool.session("u1", KB) as s:
        await s.safe.goto("https://example.com/")
    await pool.aclose()
    assert e.browsers[0].closed


async def test_control_run_labels_the_browser_and_releases_the_session(tmp_path):
    e = Env(tmp_path, BrowserbaseProvider(SECRET))
    store = ProbeStore(tmp_path / "p")
    r = await run_control(e.chrome, store)
    assert r["overall"] == "ok" and r["browser"] == "remote:browserbase"
    assert e.browsers[0].closed
    assert "browser=remote:browserbase" in render_report(store)


def test_probe_job_picks_the_remote_browser_when_switched_on(tmp_path):
    s = Settings(remote_browser_enabled=True, remote_browser_provider="cdp", remote_browser_cdp_url="wss://x.example/ws", site_mcp_dir=str(tmp_path))
    maker, _ = make_factory_class_for_probe(s)
    assert maker().label == "remote:cdp"
    job = ProbeJob(s, ProbeStore(tmp_path))
    assert job._maker().label == "remote:cdp" and job.memory.ok()  # the local RAM guard is off for a remote browser
    local = Settings(site_mcp_dir=str(tmp_path))
    assert ProbeJob(local, ProbeStore(tmp_path))._maker().label == "local"


# ------------------------------------------------------------------ deploy scripts: names only
def test_deploy_scripts_list_the_names_and_never_a_value():
    web = (ROOT / "deploy/enable-web-test.sh").read_text()
    assert web.index("ALWAYS_OFF = [") < web.index("FRIDAY_REMOTE_BROWSER_ENABLED") < web.index("CAPS = [")
    key = (ROOT / "deploy/set-key.sh").read_text()
    for n in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "STEEL_API_KEY", "FRIDAY_REMOTE_BROWSER_CDP_URL"):
        assert n in key
