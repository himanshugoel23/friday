# ruff: noqa: E501
"""``friday browser-sim``: run the browser flows against the FAKE sites. Offline, no real site.

Wiring (owner of friday/cli.py, 3 lines):
    from friday.connectors.sites.sim_cli import register as register_browser_sim   # in the parser setup
    register_browser_sim(sub)
    if args.cmd == "browser-sim": from friday.connectors.sites.sim_cli import run_command; return run_command(args)
Also runnable now: ``python -m friday.connectors.sites.sim_cli --scenario all``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from friday.connectors.sites.copy import COPY
from friday.connectors.sites.sim import BY_NAME, SCENARIOS, SimResult, run_scenario


def register(sub: Any) -> None:
    p = sub.add_parser("browser-sim", help="run browser order/booking scenarios on FAKE sites")
    add_arguments(p)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scenario", default="all", help="scenario name or 'all'")
    p.add_argument("--lang", choices=["en", "hi"], default="en")
    p.add_argument("--list", action="store_true", help="list scenarios")
    p.add_argument("--print-copy", action="store_true",
                   help="print every user-facing line (pending approval)")
    p.add_argument("--quiet", action="store_true", help="only the pass / fail table")


def _show(r: SimResult, quiet: bool) -> None:
    ok = r.ok()
    phase = r.task.phase.value if r.task else "-"
    print(f"{'PASS' if ok else 'FAIL'}  {r.scenario.name:<22} phase={phase:<14} {r.scenario.about}")
    if quiet:
        return
    for m in r.messages:
        btn = f"  [{' | '.join(t for _, t in m.buttons)}]" if m.buttons else ""
        img = "  <QR image>" if m.image_png else ""
        print(f"    {m.kind:<9}> {m.text.replace(chr(10), ' / ')}{btn}{img}")


def run_command(args: argparse.Namespace) -> int:
    if args.print_copy:
        for key, langs in COPY.items():
            for lang, text in langs.items():
                print(f"{key}.{lang}: {text}")
        return 0
    if args.list:
        for s in SCENARIOS:
            print(f"{s.name:<22} {s.about}")
        return 0
    names = [s.name for s in SCENARIOS] if args.scenario == "all" else [args.scenario]
    if any(n not in BY_NAME for n in names):
        print("unknown scenario; try --list", file=sys.stderr)
        return 2

    async def go() -> int:
        bad = 0
        for n in names:
            r = await run_scenario(BY_NAME[n], args.lang)
            _show(r, args.quiet)
            bad += 0 if r.ok() else 1
        return bad

    bad = asyncio.run(go())
    print(f"{len(names) - bad}/{len(names)} scenarios as expected (FAKE sites only)")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="friday browser-sim")
    add_arguments(p)
    return run_command(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
