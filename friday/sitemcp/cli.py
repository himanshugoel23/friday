# ruff: noqa: E501
"""``friday sitemcp``: run on the SERVER where Playwright + Chromium exist (never in tests).

    friday sitemcp tools                          list the tool names every site server exposes (offline)
    friday sitemcp live  <site> [--query atta] [--pincode 131001]   anonymous run on the REAL public site, saves results + screenshot
    friday sitemcp probe <site>                   selector drift report on the public pages (counts only)
    friday sitemcp report                         the saved last results (what /ops-status/<token>/probe shows)
    friday sitemcp serve <site>                   MCP over stdio for ONE site (user id from FRIDAY_SITEMCP_USER, default 'local')

Does not read .env. Public pages only, robots.txt respected, no login, no captcha solving. Stops with status 'blocked' when a site blocks.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

DEFAULT_DIR = "var/sitemcp"
DEFAULT_PINCODE = "131001"


def add_parser(sub: Any) -> None:
    sp = sub.add_parser("sitemcp", help="browser-driven MCP servers for grocery apps: live run, drift probe, report")
    t = sp.add_subparsers(dest="sitemcp_cmd")
    t.add_parser("tools")
    t.add_parser("report").add_argument("--out", default=DEFAULT_DIR)
    for name in ("live", "probe", "serve"):
        p = t.add_parser(name)
        p.add_argument("site")
        if name != "serve":
            p.add_argument("--out", default=DEFAULT_DIR, help="results folder (var/ is not committed)")
        if name == "live":
            p.add_argument("--query", default="atta")
            p.add_argument("--pincode", default=DEFAULT_PINCODE)


def _kb(site: str) -> dict[str, Any] | None:
    from friday.sitemcp.knowledge import load_knowledge

    return load_knowledge().get(site)


def _prereq() -> str:
    from friday.sitemcp.chromium import SharedChromium
    from friday.sitemcp.doctor import INSTALL

    return "" if SharedChromium.available() else f"Playwright or Chromium is missing. {INSTALL}"


def run_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "sitemcp_cmd", None)
    if cmd == "tools":
        from friday.sitemcp.tools import TOOL_NAMES

        print("\n".join(TOOL_NAMES))
        return 0
    if cmd == "report":
        from friday.sitemcp.live import render_report
        from friday.sitemcp.probestore import ProbeStore

        print(render_report(ProbeStore(Path(args.out))), end="")
        return 0
    if cmd in ("live", "probe", "serve"):
        kb = _kb(args.site)
        if kb is None:
            from friday.sitemcp.knowledge import load_knowledge

            print(f"unknown site {args.site!r}; known: {', '.join(sorted(load_knowledge()))}")
            return 2
        problem = _prereq()
        if problem:
            print(problem)
            return 3
        return asyncio.run(_run(cmd, kb, args))
    print(__doc__)
    return 2


async def _run(cmd: str, kb: dict[str, Any], args: argparse.Namespace) -> int:
    from friday.sitemcp.chromium import SharedChromium
    from friday.sitemcp.guard import MemoryGuard, RobotsPolicy
    from friday.sitemcp.probestore import ProbeStore

    if cmd == "live":
        from friday.sitemcp.live import run_live

        store = ProbeStore(Path(args.out))
        r = await run_live(kb, SharedChromium(), store, query=args.query, pincode=args.pincode, robots=RobotsPolicy(), memory=MemoryGuard())
        print(f"{r['site']}: overall={r['overall']} items={r['items_found']} priced={r['priced']} screenshot={'saved' if r['screenshot'] else 'none'}")
        for s in r["steps"]:
            print(f"  {s['step']}: {s['status']} ({s['ms']} ms) {s['detail']}")
        return 0 if r["overall"] == "ok" else 1
    if cmd == "probe":
        from friday.sitemcp.probe import render, run_drift

        rep = await run_drift(kb, SharedChromium(), ProbeStore(Path(args.out)), robots=RobotsPolicy(), memory=MemoryGuard())
        print(render(rep))
        return 0 if rep["status"] == "ok" else 1
    # serve over stdio (the MCP stdio transport): one site, one local user; cookies would be encrypted under var/sitemcp/vault
    import os

    from friday.core.config import Settings
    from friday.sitemcp.protocol import serve_stdio
    from friday.sitemcp.wiring import build_hub

    s = Settings()
    s.site_mcp_sites = [kb["site"]]
    hub = build_hub(s)
    server = hub.servers[kb["site"]].mcp()
    user = os.environ.get("FRIDAY_SITEMCP_USER", "local")
    orig = server.handle

    async def with_user(msg: Any) -> Any:  # stdio clients do not send _meta.user_id; default it to the local user
        if isinstance(msg, dict) and msg.get("method") == "tools/call":
            msg.setdefault("params", {}).setdefault("_meta", {}).setdefault("user_id", user)
        return await orig(msg)

    server.handle = with_user  # type: ignore[method-assign]
    try:
        await serve_stdio(server)
    finally:
        await hub.aclose()
    return 0
