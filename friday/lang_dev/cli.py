"""``friday chatbot devanagari-eval``: offline accuracy report (no network, never reads .env)."""

from __future__ import annotations

import argparse

CMD = "devanagari-eval"


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """Register ``chatbot devanagari-eval``; reuses an existing ``chatbot`` parser if another
    module registered one first."""
    chatbot = sub.choices.get("chatbot") if hasattr(sub, "choices") else None
    if chatbot is None:
        chatbot = sub.add_parser("chatbot", help="chatbot tools (offline)")
    inner = next(
        (a for a in chatbot._actions if isinstance(a, argparse._SubParsersAction)),  # noqa: SLF001
        None,
    )
    if inner is None:
        inner = chatbot.add_subparsers(dest="chatbot_cmd")
    if CMD in inner.choices:
        return
    ev = inner.add_parser(CMD, help="accuracy of the rule banks on Devanagari / mixed messages")
    ev.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    ev.add_argument("--baseline", action="store_true", help="also run without the normaliser")
    ev.add_argument("--no-failures", action="store_true", help="do not list the failures")


def handles(args: argparse.Namespace) -> bool:
    return getattr(args, "cmd", None) == "chatbot" and getattr(args, "chatbot_cmd", None) == CMD


def run(args: argparse.Namespace) -> int:
    from friday.lang_dev.evaluate import run_cli

    return run_cli(args.split, baseline=args.baseline, failures=not args.no_failures)
