"""``friday bench run [--scenario ID] [--fake] [--judge]``: the Instinct parity benchmark."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("bench", help="Instinct parity benchmark: scripted chat scenarios with a deterministic rubric")
    bsub = p.add_subparsers(dest="bench_cmd", required=True)
    r = bsub.add_parser("run", help="run the scenarios through the real in-process pipeline and write var/bench/")
    r.add_argument("--scenario", action="append", default=None, metavar="ID", help="run only this scenario (repeatable)")
    r.add_argument("--fake", action="store_true", help="fake LLM and fake providers only (CI/unit tests); no key is read")
    r.add_argument("--judge", action="store_true", help="also ask the LLM for a one-line verdict (needs a key; never required)")
    r.add_argument("--file", default=None, help="scenario file (default data/benchmarks/instinct_parity.yaml)")
    r.add_argument("--out", default=None, help="output directory (default var/bench)")
    bsub.add_parser("list", help="list the scenario ids")


def run_command(args: argparse.Namespace, *, world_factory: Any = None) -> int:
    from friday.bench import runner, scenarios

    try:
        scs = scenarios.load(getattr(args, "file", None))
    except scenarios.ScenarioError as e:
        print(f"bench: {e}", file=sys.stderr)
        return 2
    if args.bench_cmd == "list":
        for s in scs:
            print(f"{s.id:<28} {s.category:<10} {s.capability:<10} {s.expected_today}")
        return 0
    wanted = args.scenario
    if wanted:
        known = {s.id for s in scs}
        missing = [w for w in wanted if w not in known]
        if missing:
            print("bench: unknown scenario id(s): " + ", ".join(missing), file=sys.stderr)
            return 2
        scs = [s for s in scs if s.id in wanted]
    env = None
    if not args.fake:
        from friday.core.config import Settings

        env = Settings()  # server .env is read by the settings loader only to see whether an LLM key exists
    report = asyncio.run(runner.run(scs, fake=args.fake, judge=args.judge, env=env, world_factory=world_factory))
    js, txt = runner.write(report, args.out)
    print(runner.render(report))
    print(f"\nwritten: {js} and {txt}")
    return 0  # a measurement, not a gate: failures are in the report
