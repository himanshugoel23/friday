# ruff: noqa: E501
"""``friday replylog``: the tester training-data log. Local files only; nothing is ever uploaded.

    friday replylog stats
    friday replylog export --approved-only [--out FILE]     fine-tuning JSONL, written locally
    friday replylog delete --all                            hard delete of every record
    friday replylog delete --user <user id>                 erase one tester
    friday replylog prune                                   apply retention and the size cap now
"""

from __future__ import annotations

import argparse
from typing import Any

from friday.core.config import Settings
from friday.replywriter.log import ReplyLog


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("replylog", help="reply writer training-data log (testers only, local, never uploaded)")
    rsub = p.add_subparsers(dest="replylog_cmd", required=True)
    rsub.add_parser("stats", help="counts by writer / intent / status, size, age")
    ex = rsub.add_parser("export", help="write approved examples as fine-tuning JSONL (local file; uploads nothing)")
    ex.add_argument("--approved-only", action="store_true", required=True, help="required: only approved or founder-edited examples are exported")
    ex.add_argument("--out", default=None, help="output file (default var/replylog/export-<time>.jsonl, mode 0600)")
    dl = rsub.add_parser("delete", help="hard delete")
    g = dl.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="delete every record and every export")
    g.add_argument("--user", default=None, help="erase one tester by user id")
    rsub.add_parser("prune", help="apply retention and the size cap now")


def run_command(args: argparse.Namespace, settings: Settings | None = None, out: Any = print) -> int:
    settings = settings or Settings()
    rl = ReplyLog.open(settings)
    cmd = args.replylog_cmd
    if cmd == "stats":
        s = rl.stats()
        out(f"records: {s['records']}  (retention {s['retention_days']} days, {s['bytes']} bytes)")
        out(f"by writer: {s['by_writer']}")
        out(f"by intent: {s['by_intent']}")
        out(f"by status: {s['by_status']}")
        out(f"fact check rejected an LLM reply: {s['fact_check_rejected']}   reactions: {s['reactions']}")
        out(f"approved examples: {s['approved_examples']} of about {s['fine_tune_target']} wanted before a fine-tune is worth trying")
        if s["unreadable_lines"]:
            out(f"unreadable lines (wrong key or damaged): {s['unreadable_lines']}")
        return 0
    if cmd == "export":
        path, n = rl.export_approved(args.out)
        out(f"wrote {n} approved example(s) to {path} (local file, mode 0600). Nothing was uploaded.")
        return 0 if n else 1
    if cmd == "delete":
        if args.all:
            n = rl.delete_all()
            out(f"deleted the whole reply log ({n} record(s)) and all exports")
        else:
            n = rl.erase_user(args.user)
            out(f"erased {n} record(s) of that tester")
        return 0
    if cmd == "prune":
        out(f"pruned {rl.prune()} record(s)")
        return 0
    return 2
