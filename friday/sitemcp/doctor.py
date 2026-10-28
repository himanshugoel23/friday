# ruff: noqa: E501
"""`friday doctor` lines for the site MCP (added to the "private browser" section). Read-only: no browser is launched, no site
is contacted. Names, counts and statuses only."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from friday.connectors.browser.playwright_session import find_chromium, playwright_installed
from friday.sitemcp.guard import read_mem_available_mb
from friday.sitemcp.knowledge import load_knowledge
from friday.sitemcp.probestore import ProbeStore

INSTALL = (
    "run ONCE as root on the server: "
    "(1) apt-get install -y xvfb   "
    "(2) cd /opt/friday && sudo -u friday /home/friday/.local/bin/uv sync --extra browser   "
    "(3) cd /opt/friday && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers /home/friday/.local/bin/uv run playwright install chromium --with-deps "
    "&& chmod -R a+rX /opt/pw-browsers   then: systemctl restart friday"
)
BAD = {"blocked", "changed", "location_not_found", "browser_unavailable", "skipped_low_memory", "error", "unavailable", "rate_limited"}


def check(settings: Any, *, mem_reader: Any = read_mem_available_mb, now: datetime | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    on = bool(getattr(settings, "site_mcp_enabled", False))
    probe_on = bool(getattr(settings, "site_mcp_probe_enabled", False))
    out.append(("ok", f"site MCP: shopping switch {'ON' if on else 'off'} (FRIDAY_SITE_MCP_ENABLED), live probe {'ON' if probe_on else 'off'} (FRIDAY_SITE_MCP_PROBE_ENABLED); no pay / place-order tool exists"))
    need = on or probe_on
    lvl = "warn" if need else "ok"
    pw, exe, xvfb = playwright_installed(), find_chromium(), bool(shutil.which("Xvfb") or shutil.which("xvfb-run"))
    out.append((("ok" if pw else lvl), "site MCP: playwright python package " + ("present" if pw else "MISSING")))
    out.append((("ok" if exe else lvl), "site MCP: Chromium binary " + ("found" if exe else "MISSING (not in PLAYWRIGHT_CHROMIUM_PATH or /opt/pw-browsers)")))
    out.append((("ok" if xvfb else lvl), "site MCP: Xvfb " + ("present" if xvfb else "MISSING (only needed for headed mode; headless is the default)")))
    if not (pw and exe and xvfb):
        out.append((lvl, "site MCP install: " + INSTALL))
    mem = mem_reader()
    floor = float(getattr(settings, "site_mcp_min_free_mb", 250))
    if mem is None:
        out.append(("ok", "site MCP: free RAM unknown on this OS (the memory guard allows sessions)"))
    else:
        out.append((("ok" if mem >= floor else "warn"), f"site MCP: {mem:.0f} MB RAM available (new browser sessions are refused below {floor:.0f} MB; one Chromium needs about 300-500 MB)"))
    kbs = load_knowledge()
    unverified = sorted(s for s, k in kbs.items() if k["status"] != "verified")
    out.append(("ok", f"site MCP knowledge: {len(kbs)} sites, {len(unverified)} unverified (selectors are guesses until a live run confirms them)"))
    store = ProbeStore(Path(getattr(settings, "site_mcp_dir", "var/sitemcp")))
    live, drift = store.live_all(), store.drift_all()
    t = now or datetime.now(UTC)
    if not live:
        out.append((("warn" if probe_on else "ok"), "site MCP last live probe: none yet (friday sitemcp live <site>, or switch the scheduled probe on)"))
    for site, r in sorted(live.items()):
        age = ""
        try:
            h = (t - datetime.fromisoformat(r["finished_at"]).replace(tzinfo=UTC)).total_seconds() / 3600
            age = f", {h:.0f} h ago"
        except (KeyError, ValueError):
            pass
        out.append((("warn" if r["overall"] in BAD else "ok"), f"site MCP last live probe {site}: {r['overall']} (items {r['items_found']}, priced {r['priced']}{age})"))
    for site, d in sorted(drift.items()):
        out.append((("ok" if d["status"] == "ok" else "warn"), f"site MCP last drift probe {site}: {d['matched']}/{d['checked']} selectors matched ({d['status']})"))
    return out
