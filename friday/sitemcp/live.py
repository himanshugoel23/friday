# ruff: noqa: E501
"""Anonymous LIVE run on a real public site: open home, set the location, search, parse the first results. No login, no
personal data. Records per-step status (ok | blocked | location_not_found | changed | unavailable) with timings, saves one
screenshot of the PUBLIC page the run ended on, and CLOSES the browser right after (1 GB droplet: one page at a time).

Runs on the server (needs Playwright + Chromium); the test suite drives it only with fakes."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from friday.core.logging import get_logger
from friday.sitemcp.guard import MemoryGuard, RateLimiter, RobotsPolicy
from friday.sitemcp.hub import SiteMcpHub
from friday.sitemcp.probestore import ProbeStore
from friday.sitemcp.runtime import BrowserFactory, SessionPool
from friday.sitemcp.site import SiteServer

log = get_logger(__name__)
ANON_USER = "probe-anon"


def step_status(res: dict[str, Any]) -> str:
    st = res.get("status")
    if st in ("ok", "blocked", "location_not_found", "rate_limited"):
        return st
    if st == "unavailable" and res.get("reason") == "page_changed":
        return "changed"
    if st == "busy" and str(res.get("reason", "")).startswith("browser_unavailable"):
        return "browser_unavailable"
    return "unavailable" if st in ("busy", "unavailable", "needs_location") else "error"


async def run_live(kb: dict[str, Any], factory: BrowserFactory, store: ProbeStore | None, *, query: str, pincode: str,
                   robots: RobotsPolicy | None = None, memory: MemoryGuard | None = None, limiter: RateLimiter | None = None,
                   mono: Callable[[], float] = time.monotonic, now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    now = now or (lambda: datetime.now(UTC))
    site = kb["site"]
    result: dict[str, Any] = {"site": site, "kb_version": kb["version"], "kb_status": kb["status"], "query": query, "pincode": pincode,
                              "started_at": now().isoformat(timespec="seconds"), "steps": [], "overall": "ok", "items_found": 0, "priced": 0,
                              "sample": [], "screenshot": False, "browser": getattr(factory, "label", "local")}
    pool = SessionPool(factory, robots=robots, limiter=limiter, memory=memory or MemoryGuard(), max_sessions=1, max_pages=1)
    server = SiteServer(kb, pool)
    hub = SiteMcpHub({site: server}, pool)
    shot: bytes | None = None

    def add(name: str, status: str, t0: float, detail: str = "") -> None:
        result["steps"].append({"step": name, "status": status, "ms": int((mono() - t0) * 1000), "detail": detail[:120]})
        if status != "ok" and result["overall"] == "ok":
            result["overall"] = status

    try:
        t0 = mono()
        loc = await hub.call(site, "set_location", {"pincode": pincode}, user_id=ANON_USER)
        add("home+set_location", step_status(loc), t0, loc.get("reason", "") or loc.get("detail", ""))
        if result["overall"] == "ok":
            t0 = mono()
            res = await hub.call(site, "search_products", {"query": query}, user_id=ANON_USER)
            st = step_status(res)
            items = res.get("items", []) if st == "ok" else []
            result["items_found"] = len(items)
            result["priced"] = sum(1 for i in items if i.get("price_inr") is not None)
            result["sample"] = [{"title": i["title"][:60], "price_text": i["price_text"], "pack": i["pack"]} for i in items[:3]]
            if st == "ok" and not items:
                st = "changed"
            add("search", st, t0, "no items parsed (selectors changed or nothing found)" if st == "changed" and not items else res.get("reason", ""))
            if st == "ok":
                add("parse_prices", "ok" if result["priced"] else "changed", mono(), f"{result['priced']}/{len(items)} items with a price")
        shot = await server.snapshot(ANON_USER)
        result["screenshot"] = shot is not None
    except Exception as e:  # noqa: BLE001 - a probe never crashes the server
        log.exception("site mcp live run crashed")
        add("run", "error", mono(), type(e).__name__)
    finally:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(hub.aclose(), 20)  # the browser is closed right after the run
    result["finished_at"] = now().isoformat(timespec="seconds")
    if store is not None:
        store.save_live(result, shot)
    return result


CONTROL_URL = "https://example.com/"


async def run_control(factory: BrowserFactory, store: ProbeStore | None, *, now: Callable[[], datetime] | None = None,
                      mono: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Control run: open example.com (a page that blocks nobody). Loads => the browser works and a grocery site's
    refusal is about the site or our address; blank => our browser setup. Anonymous, one request, then closed."""
    now = now or (lambda: datetime.now(UTC))
    kb = {"site": "control", "version": 1, "status": "control", "domains": ["example.com"]}
    result: dict[str, Any] = {"site": "control", "kb_version": 1, "kb_status": "control", "started_at": now().isoformat(timespec="seconds"),
                              "steps": [], "overall": "ok", "items_found": 0, "priced": 0, "sample": [], "screenshot": False,
                              "browser": getattr(factory, "label", "local")}
    shot: bytes | None = None
    sess: Any = None
    t0 = mono()
    try:
        sess = await factory.open(kb, None)
        await sess.goto(CONTROL_URL)
        text = (await sess.text("body"))[:200]
        code = getattr(sess, "last_status", None)
        ok = "Example Domain" in text or "domain is for use in" in text
        result["steps"].append({"step": "open example.com", "status": "ok" if ok else "changed", "ms": int((mono() - t0) * 1000),
                                "detail": f"http={code} page_text={'Example Domain' if ok else 'not the expected page: ' + ' '.join(text.split())[:80]!r}"})
        if not ok:
            result["overall"] = "changed"
        shot = await sess.screenshot()
        result["screenshot"] = True
    except Exception as e:  # noqa: BLE001 - a probe never crashes the server
        result["overall"] = "error"
        result["steps"].append({"step": "open example.com", "status": "error", "ms": int((mono() - t0) * 1000), "detail": f"{type(e).__name__}: {str(e)[:100]}"})
    finally:
        if sess is not None:
            with contextlib.suppress(Exception):
                await sess.close()
        with contextlib.suppress(Exception):
            await factory.aclose()  # a remote session is paid for by the minute: release it right after the control run
    result["finished_at"] = now().isoformat(timespec="seconds")
    if store is not None:
        store.save_live(result, shot)
    return result


def render_report(store: ProbeStore, kbs: dict[str, dict[str, Any]] | None = None) -> str:
    """Plain text for GET /ops-status/<token>/probe: statuses, counts, timings. No personal data."""
    live, drift = store.live_all(), store.drift_all()
    if not live and not drift:
        return "no site MCP probe has run yet\n"
    out = ["Site MCP probe report (anonymous public pages only; selectors are unverified guesses until these say ok)", ""]
    for site in sorted(live):
        r = live[site]
        out.append(f"{site}: overall={r['overall']}  kb v{r['kb_version']} {r['kb_status']}  finished {r.get('finished_at', '?')}Z  items={r['items_found']} priced={r['priced']}  screenshot={'yes' if r.get('screenshot') else 'no'}  browser={r.get('browser', 'local')}")
        for s in r["steps"]:
            out.append(f"  - {s['step']}: {s['status']} ({s['ms']} ms){' ' + s['detail'] if s['detail'] else ''}")
        for it in r.get("sample", []):
            out.append(f"  sample: {it['title']} | {it['price_text']} | {it['pack']}")
        if r.get("screenshot"):
            out.append(f"  screenshot: /ops-status/<token>/shot/{site}")
    if drift:
        out += ["", "Selector drift (friday sitemcp probe):"]
        for site in sorted(drift):
            d = drift[site]
            out.append(f"{site}: {d['matched']}/{d['checked']} selectors matched, {d['missing']} missing, status={d['status']} at {d.get('finished_at', '?')}Z")
    return "\n".join(out) + "\n"
