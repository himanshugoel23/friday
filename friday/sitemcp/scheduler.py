# ruff: noqa: E501
"""The anonymous live probe on a schedule: once shortly after `friday serve` starts, then every FRIDAY_SITE_MCP_PROBE_INTERVAL_H
(default 12 h). One site at a time, one page at a time, browser closed after each site, skipped when RAM is low. Results go to
var/sitemcp/ (read remotely through /ops-status/<token>/probe). OFF unless FRIDAY_SITE_MCP_PROBE_ENABLED."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from friday.core.logging import get_logger
from friday.sitemcp.chromium import SharedChromium
from friday.sitemcp.guard import MemoryGuard, RobotsPolicy
from friday.sitemcp.knowledge import load_knowledge
from friday.sitemcp.live import run_live
from friday.sitemcp.probestore import ProbeStore

log = get_logger(__name__)
START_DELAY_S = 90.0  # let the app finish booting first
BETWEEN_SITES_S = 30.0


class ProbeJob:
    def __init__(self, settings: Any, store: ProbeStore, *, factory_maker: Callable[[], Any] = SharedChromium,
                 available: Callable[[], bool] = SharedChromium.available, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 robots: RobotsPolicy | None = None, memory: MemoryGuard | None = None) -> None:
        self.s, self.store, self._maker, self._available, self._sleep = settings, store, factory_maker, available, sleep
        self.robots = robots if robots is not None else RobotsPolicy()
        self.memory = memory or MemoryGuard(float(settings.site_mcp_min_free_mb))

    def _unavailable(self, kb: dict[str, Any], overall: str, detail: str) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        r = {"site": kb["site"], "kb_version": kb["version"], "kb_status": kb["status"], "query": self.s.site_mcp_probe_query,
             "pincode": self.s.site_mcp_probe_pincode, "started_at": now, "finished_at": now, "overall": overall, "items_found": 0,
             "priced": 0, "sample": [], "screenshot": False,
             "steps": [{"step": "prerequisites", "status": overall, "ms": 0, "detail": detail}]}
        self.store.save_live(r, None)
        return r

    async def run_all(self) -> list[dict[str, Any]]:
        kbs = load_knowledge()
        out: list[dict[str, Any]] = []
        for i, site in enumerate(s for s in self.s.site_mcp_sites if s in kbs):
            kb = kbs[site]
            if i:
                await self._sleep(BETWEEN_SITES_S)
            if not self._available():
                out.append(self._unavailable(kb, "browser_unavailable", "Playwright or Chromium missing: see `friday doctor` for the install commands"))
            elif not self.memory.ok():
                out.append(self._unavailable(kb, "skipped_low_memory", "less free RAM than FRIDAY_SITE_MCP_MIN_FREE_MB"))
            else:
                out.append(await run_live(kb, self._maker(), self.store, query=self.s.site_mcp_probe_query, pincode=self.s.site_mcp_probe_pincode,
                                          robots=self.robots, memory=self.memory))
        log.info("site mcp probe: %s", {r["site"]: r["overall"] for r in out})  # statuses only
        return out

    def _recent(self) -> bool:
        """True when every site was probed less than one interval ago (a restart must not hit the sites again:
        several updates a day would look like hammering and got the droplet an HTTP 429 from one site)."""
        from datetime import UTC, datetime

        hours = max(1.0, float(self.s.site_mcp_probe_interval_h))
        done = self.store.live_all()
        if not done:
            return False
        for site in self.s.site_mcp_sites:
            fin = (done.get(site) or {}).get("finished_at")
            try:
                age_h = (datetime.now(UTC) - datetime.fromisoformat(str(fin))).total_seconds() / 3600
            except (TypeError, ValueError):
                return False
            if age_h >= hours:
                return False
        return True

    async def loop(self) -> None:
        await self._sleep(START_DELAY_S)
        while True:
            try:
                if self._recent():
                    log.info("site mcp probe: skipped at start, a recent result exists")
                else:
                    await self.run_all()
            except Exception:  # noqa: BLE001
                log.exception("site mcp probe tick failed")
            await self._sleep(max(1.0, float(self.s.site_mcp_probe_interval_h)) * 3600)
