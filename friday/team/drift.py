# ruff: noqa: E501
"""Scheduled self-check of each site agent's knowledge (low frequency, public pages only, no login).

For every probe in the knowledge file: robots.txt is read first (disallowed -> skipped), requests are rate
limited per host, a bot challenge / 403 / 429 / timeout makes the site ``unverified`` (we NEVER try to get
around it and the last good version stays). Observed changes become PROPOSALS (new versions with a diff):

* a probe URL that now redirects (HTTP 200 at a new place on the same site) -> proposal changing only URL
  fields; auto-applied when it validates and the new URL itself answered correctly;
* expected markers missing / page gone -> a proposal that adds a quirk note: always queued for founder review.

The agent never edits code, prompts or safety rules: ``knowledge.validate`` refuses any proposal that touches
them, and only URL/observed paths can ever be auto-applied.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from friday.core.logging import get_logger
from friday.team.knowledge import KnowledgeStore, Proposal

log = get_logger(__name__)
USER_AGENT = "FridayProbe/1 (personal assistant; public pages only; respects robots.txt)"
MAX_PROBES_PER_SITE = 4
BLOCK_STATUSES = frozenset({401, 403, 429, 503})


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status: int
    text: str = ""
    error: str | None = None


class PageFetcher(Protocol):
    async def get(self, url: str) -> FetchedPage: ...


class FakePages:
    """Tests: ``pages`` maps url -> FetchedPage | Exception. Unknown url -> 404. Records every call."""

    def __init__(self, pages: dict[str, FetchedPage | Exception] | None = None) -> None:
        self.pages: dict[str, FetchedPage | Exception] = dict(pages or {})
        self.calls: list[str] = []

    async def get(self, url: str) -> FetchedPage:
        self.calls.append(url)
        item = self.pages.get(url)
        if isinstance(item, Exception):
            raise item
        return item or FetchedPage(url, url, 404, "")


class HttpxFetcher:
    """The real fetcher. NOT used by any test. No cookies, no login, <= 3 redirects, text capped at 200 KB."""

    def __init__(self, timeout_s: float = 8.0) -> None:
        self.timeout_s = timeout_s

    async def get(self, url: str) -> FetchedPage:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True, max_redirects=3,
                                     headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"}) as c:
            try:
                r = await c.get(url)
            except httpx.HTTPError as e:
                return FetchedPage(url, url, 0, "", type(e).__name__)
            return FetchedPage(url, str(r.url), r.status_code, r.text[:200_000])


@dataclass
class ProbeResult:
    probe_id: str
    url: str
    outcome: str  # ok | moved | marker_missing | gone | blocked | skipped_robots | error
    status: int = 0
    new_url: str | None = None
    detail: str = ""


@dataclass
class DriftReport:
    site: str
    version: int
    status: str  # verified | drift | unverified
    probes: list[ProbeResult] = field(default_factory=list)
    action: str = "none"  # none | auto_applied | queued
    applied_version: int | None = None
    review_id: str | None = None
    diff: list[str] = field(default_factory=list)
    note: str = ""

    def line(self) -> str:
        return f"{self.site} v{self.version}: {self.status}; {self.action}" + (f" -> v{self.applied_version}" if self.applied_version else "")


class RateLimiter:
    def __init__(self, min_interval_s: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.min_interval_s, self._clock, self._sleep = min_interval_s, clock, sleep
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = self.min_interval_s - (self._clock() - last)
            if gap > 0:
                await self._sleep(gap)
        self._last[host] = self._clock()


class DriftJob:
    def __init__(self, store: KnowledgeStore, fetcher: PageFetcher, *, min_interval_s: float = 6.0,
                 interval_h: float = 24.0, clock: Callable[[], float] = time.time,
                 limiter: RateLimiter | None = None) -> None:
        self.store, self.fetcher, self.interval_h, self._clock = store, fetcher, interval_h, clock
        self.limiter = limiter or RateLimiter(min_interval_s)
        self._robots: dict[str, RobotFileParser | None] = {}

    # ------------------------------------------------------------------ robots.txt
    async def _allowed(self, url: str) -> bool:
        host = urlsplit(url).hostname or ""
        if host not in self._robots:
            await self.limiter.wait(host)
            try:
                page = await self.fetcher.get(f"https://{host}/robots.txt")
            except Exception:  # noqa: BLE001
                page = FetchedPage("", "", 0, "", "error")
            rp: RobotFileParser | None = RobotFileParser()
            if page.status == 200:
                rp.parse(page.text.splitlines())
            elif page.status in (404, 410):
                rp.parse([])  # no robots file: allowed
            else:
                rp = None  # cannot read it: do not fetch (conservative)
            self._robots[host] = rp
        rp = self._robots[host]
        return bool(rp and rp.can_fetch(USER_AGENT, url))

    # ------------------------------------------------------------------ one probe
    async def _probe(self, doc: dict[str, Any], probe: dict[str, Any]) -> ProbeResult:
        pid, url = str(probe.get("id", "?")), str(probe["url"])
        res = ProbeResult(pid, url, "error")
        if not await self._allowed(url):
            res.outcome, res.detail = "skipped_robots", "robots.txt does not allow it (or could not be read)"
            return res
        host = urlsplit(url).hostname or ""
        await self.limiter.wait(host)
        try:
            page = await self.fetcher.get(url)
        except Exception as e:  # noqa: BLE001
            res.detail = type(e).__name__
            return res
        res.status = page.status
        low = (page.text or "").lower()
        markers = [m.lower() for m in doc.get("anti_bot", {}).get("markers", [])]
        if page.error or page.status == 0:
            res.detail = page.error or "no response"
        elif page.status in BLOCK_STATUSES or any(m in low for m in markers):
            res.outcome, res.detail = "blocked", "bot challenge or refusal; not bypassed"
        elif page.status in (404, 410):
            res.outcome, res.detail = "gone", f"HTTP {page.status}"
        elif page.status in probe.get("expect_status", [200]):
            if not all(str(m).lower() in low for m in probe.get("expect_markers", [])):
                res.outcome, res.detail = "marker_missing", "expected text not on the page"
            else:
                moved = page.final_url.rstrip("/") != url.rstrip("/")
                res.outcome = "moved" if moved else "ok"
                res.new_url = page.final_url if moved else None
        else:
            res.outcome, res.detail = "marker_missing", f"unexpected HTTP {page.status}"
        return res

    # ------------------------------------------------------------------ one site
    async def run_site(self, site: str) -> DriftReport:
        doc = self.store.get(site)
        report = DriftReport(site, int(doc["version"]), "unverified")
        for probe in doc["probes"][:MAX_PROBES_PER_SITE]:
            report.probes.append(await self._probe(doc, probe))
        outcomes = {p.outcome for p in report.probes}
        if outcomes & {"moved", "marker_missing", "gone"}:
            report.status = "drift"
        elif "ok" in outcomes and outcomes <= {"ok", "skipped_robots", "blocked", "error"}:
            report.status = "verified" if outcomes == {"ok"} else "unverified"
        else:
            report.status = "unverified"
        if report.status == "unverified":
            report.note = "could not verify from this server (bot challenge, refusal, robots or network); last good version kept"
            self.store.mark_status(site, "unverified", report.note)
        elif report.status == "verified":
            self.store.mark_status(site, "verified")
        else:
            self._propose(site, doc, report)
        self._record(report)
        return report

    def _propose(self, site: str, doc: dict[str, Any], report: DriftReport) -> None:
        moved = {p.probe_id: p for p in report.probes if p.outcome == "moved" and p.new_url}
        problems = [p for p in report.probes if p.outcome in ("marker_missing", "gone")]
        mutate: dict[str, Any] = {}
        verified_values: set[str] = {p.new_url for p in report.probes if p.outcome == "moved" and p.new_url}
        if moved:
            patterns = dict(doc["url_patterns"])
            probes = json.loads(json.dumps(doc["probes"]))
            for pr in probes:
                m = moved.get(pr.get("id"))
                if m:
                    name = pr.get("pattern")
                    if name in patterns:  # re-template the new URL with the probe's own variable values
                        tmpl = m.new_url
                        for var, val in (pr.get("vars") or {}).items():
                            tmpl = tmpl.replace("/" + str(val), "/{" + str(var) + "}")
                        patterns[name] = tmpl
                        verified_values.add(tmpl)  # derived from a URL we fetched ourselves in this run
                    else:
                        for k, v in patterns.items():
                            if v == pr["url"]:
                                patterns[k] = m.new_url
                    pr["url"] = m.new_url
            mutate["url_patterns"], mutate["probes"] = patterns, probes
        if problems:
            note = "; ".join(f"probe {p.probe_id}: {p.outcome} ({p.detail})" for p in problems)
            mutate["quirks"] = [*doc["quirks"], f"DRIFT NOTICE {time.strftime('%Y-%m-%d', time.gmtime(self._clock()))}: {note}"]
        reason = "drift: " + ", ".join(f"{p.probe_id}={p.outcome}" for p in report.probes if p.outcome not in ("ok",))
        prop: Proposal = self.store.make_proposal(site, mutate, reason)
        report.diff = [c.line() for c in prop.changes if c.path not in ("version", "updated")]
        evidence = {"probes": [vars(p) for p in report.probes]}
        # sanity: every NEW url must be one we actually fetched and that answered correctly in this run
        new_urls = {c.new for c in prop.changes
                    if isinstance(c.new, str) and c.new.startswith("https://") and c.new != c.old
                    and (c.path.startswith("url_patterns.") or c.path.endswith(".url"))}
        sanity_ok = new_urls <= verified_values
        if prop.auto_ok and sanity_ok:
            report.applied_version = self.store.apply(prop, how="auto")
            report.action = "auto_applied"
        else:
            report.review_id = self.store.queue(prop, evidence=evidence)
            report.action = "queued"

    def _record(self, report: DriftReport) -> None:
        d = self.store.root / report.site
        d.mkdir(parents=True, exist_ok=True)
        rec = {"ts": int(self._clock()), "status": report.status, "action": report.action, "version": report.version,
               "applied": report.applied_version, "review": report.review_id, "diff": report.diff,
               "probes": [{"id": p.probe_id, "outcome": p.outcome, "status": p.status} for p in report.probes]}
        with (d / "drift.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        log.info("team drift %s", report.line())

    # ------------------------------------------------------------------ schedule
    def _state_file(self) -> Path:
        return self.store.root / "drift_state.json"

    def due(self) -> bool:
        try:
            last = float(json.loads(self._state_file().read_text())["last_run"])
        except (OSError, ValueError, KeyError):
            return True
        return self._clock() - last >= self.interval_h * 3600

    async def run_all(self) -> list[DriftReport]:
        self._robots.clear()
        out = []
        for site in self.store.sites():
            try:
                out.append(await self.run_site(site))
            except Exception:  # noqa: BLE001 - one site must not stop the others
                log.exception("team drift: %s failed", site)
        self.store.root.mkdir(parents=True, exist_ok=True)
        self._state_file().write_text(json.dumps({"last_run": self._clock()}))
        return out

    async def tick(self) -> list[DriftReport]:
        """Called by the runtime loop every few minutes; does real work at most once per interval."""
        return await self.run_all() if self.due() else []
