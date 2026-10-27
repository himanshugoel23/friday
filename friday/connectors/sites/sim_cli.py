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

from friday.connectors.sites import categories, category_sim
from friday.connectors.sites.copy import COPY
from friday.connectors.sites.sim import BY_NAME, SCENARIOS, SimResult, run_scenario


def register(sub: Any) -> None:
    p = sub.add_parser("browser-sim", help="run browser order/booking scenarios on FAKE sites")
    add_arguments(p)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scenario", default="all", help="scenario name, a site key such as blinkit.grocery, 'sites', 'scenarios' or 'all'")
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


def _show_cat(r: category_sim.CatResult, quiet: bool) -> None:
    ok, bad = r.ok(), r.problems()
    print(f"{'PASS' if ok else 'FAIL'}  {r.case.key + ':' + r.mode:<30} phase={r.phase:<14} "
          f"{'; '.join(bad)}")
    if quiet and ok:
        return
    for m in r.messages:
        btn = f"  [{' | '.join(t for _, t in m.buttons)}]" if m.buttons else ""
        img = "  <QR image>" if m.image_png else ""
        print(f"    {m.kind:<9}> {m.text.replace(chr(10), ' / ')[:300]}{btn}{img}")


def run_command(args: argparse.Namespace) -> int:
    categories.all_adapters()  # loads the category packages (and their copy) first
    cases = category_sim.cases()
    if args.print_copy:
        for key, langs in COPY.items():
            for lang, text in langs.items():
                print(f"{key}.{lang}: {text}")
        return 0
    if args.list:
        for s in SCENARIOS:
            print(f"{s.name:<22} {s.about}")
        print(f"-- category cases (FAKE sites; modes happy, price_rise, cancel): {len(cases)} sites")
        for key, c in cases.items():
            print(f"{key:<22} {c.request!r}  modes={','.join(c.modes)}")
        miss = categories.missing_packages()
        if miss:
            print("-- category packages not present: " + ", ".join(miss))
        return 0
    names = [s.name for s in SCENARIOS] if args.scenario in {"all", "scenarios"} else []
    cat_names = list(cases) if args.scenario in {"all", "sites"} else []
    if args.scenario not in {"all", "scenarios", "sites"}:
        if args.scenario in BY_NAME:
            names = [args.scenario]
        elif args.scenario in cases:
            cat_names = [args.scenario]
        else:
            print("unknown scenario or site key; try --list", file=sys.stderr)
            return 2

    async def go() -> tuple[int, int]:
        bad = total = 0
        for n in names:
            r = await run_scenario(BY_NAME[n], args.lang)
            _show(r, args.quiet)
            bad += 0 if r.ok() else 1
            total += 1
        for k in cat_names:
            for mode in cases[k].modes:
                cr = await category_sim.run_case(cases[k], mode, args.lang)
                _show_cat(cr, args.quiet)
                bad += 0 if cr.ok() else 1
                total += 1
        return bad, total

    bad, total = asyncio.run(go())
    print(f"{total - bad}/{total} scenarios as expected (FAKE sites only)")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="friday browser-sim")
    add_arguments(p)
    return run_command(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
