# ruff: noqa: E501
"""Selector drift probe (`friday sitemcp probe <site>`): open the site's PUBLIC pages (robots.txt respected, rate limited,
no login), check that each selector in the knowledge file still matches, print/save COUNTS only. Runs on the server where
Playwright exists; never in tests except with fakes."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from friday.sitemcp.guard import MemoryGuard, RateLimiter, RobotsPolicy, SafeSession, SiteBlocked
from friday.sitemcp.probestore import ProbeStore
from friday.sitemcp.runtime import BrowserFactory


def public_selectors(kb: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """[(path, [selectors that should exist on that PUBLIC page])] from the knowledge file."""
    loc = kb["location"]
    pages = [(p["path"], list(p["selectors"])) for p in kb["probe"]["public_pages"]]
    extra = [x for x in (loc.get("open"), loc.get("input"), loc.get("current"), kb["login"].get("open")) if x]
    return [(path, sels + [x for x in extra if x not in sels] if i == 0 else sels) for i, (path, sels) in enumerate(pages)]


async def run_drift(kb: dict[str, Any], factory: BrowserFactory, store: ProbeStore | None, *, robots: RobotsPolicy | None = None,
                    memory: MemoryGuard | None = None, limiter: RateLimiter | None = None,
                    now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    now = now or (lambda: datetime.now(UTC))
    rep: dict[str, Any] = {"site": kb["site"], "kb_version": kb["version"], "checked": 0, "matched": 0, "missing": 0, "pages": [],
                           "status": "ok", "started_at": now().isoformat(timespec="seconds")}
    if memory is not None and not memory.ok():
        rep["status"] = "skipped_low_memory"
    else:
        safe = None
        try:
            inner = await factory.open(kb, None)
            safe = SafeSession(inner, kb, "probe-anon", limiter=limiter or RateLimiter(), robots=robots)
            for path, sels in public_selectors(kb):
                page = {"path": path, "checked": 0, "matched": 0}
                await safe.goto(kb["base_url"].rstrip("/") + path)
                for sel in sels:
                    page["checked"] += 1
                    page["matched"] += 1 if await safe.exists(sel) else 0
                rep["pages"].append(page)
                rep["checked"] += page["checked"]
                rep["matched"] += page["matched"]
            rep["missing"] = rep["checked"] - rep["matched"]
            rep["status"] = "ok" if rep["missing"] == 0 else "drift"
        except SiteBlocked as e:
            rep["status"] = "blocked"
            rep["reason"] = e.reason
        except Exception as e:  # noqa: BLE001
            rep["status"] = "unavailable"
            rep["reason"] = type(e).__name__
        finally:
            if safe is not None:
                with contextlib.suppress(Exception):
                    await safe.close()
            with contextlib.suppress(Exception):
                await factory.aclose()
    rep["finished_at"] = now().isoformat(timespec="seconds")
    if store is not None:
        store.save_drift(rep)
    return rep


def render(rep: dict[str, Any]) -> str:
    lines = [f"{rep['site']} (knowledge v{rep['kb_version']}, selectors UNVERIFIED until this says ok): status={rep['status']}"
             + (f" ({rep['reason']})" if rep.get("reason") else "")]
    for p in rep["pages"]:
        lines.append(f"  page {p['path']}: {p['matched']}/{p['checked']} selectors matched")
    if rep["checked"]:
        lines.append(f"  total: {rep['matched']}/{rep['checked']} matched, {rep['missing']} missing")
    return "\n".join(lines)

