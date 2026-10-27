# ruff: noqa: E501
"""``friday guardrails eval | policy | copy`` (offline: never reads .env, no network)."""

from __future__ import annotations

import argparse

CMDS = {"guardrails"}


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    g = sub.add_parser("guardrails", help="guardrails tools (offline)")
    gs = g.add_subparsers(dest="guardrails_cmd", required=True)
    gs.add_parser("eval", help="run the red-team corpus and the regression gate")
    gs.add_parser("policy", help="print the category -> action table and which switch enables it")
    gs.add_parser("copy", help="list every new wording id awaiting founder approval")


def handles(args: argparse.Namespace) -> bool:
    return getattr(args, "cmd", None) in CMDS


def run(args: argparse.Namespace) -> int:
    from friday.guardrails import copy
    from friday.guardrails.eval import run_cli
    from friday.guardrails.policy import POLICY

    if args.guardrails_cmd == "eval":
        return run_cli()
    if args.guardrails_cmd == "policy":
        for cat, p in POLICY.items():
            switch = "FRIDAY_GUARDRAILS_ENABLED" if p.legacy else "FRIDAY_GUARDRAILS_NEW_CATEGORIES (OFF)"
            print(f"{cat.value:18s} {p.action.value:22s} {p.phase:5s} {switch}")
        return 0
    for i in copy.all_ids():
        print(i)
    return 0
