# ruff: noqa: E501
"""`friday savings rules import|verify|list|export` - add and verify card-rule rows from a CSV.

    uv run friday savings rules import rules.csv --dry-run   # check only, store nothing
    uv run friday savings rules import rules.csv             # store the rows (as drafts until verified)
    uv run friday savings rules verify hdfc-bank/regalia --by "Asha Rao" --checked-on 2026-10-19
    uv run friday savings rules list [--unverified|--stale]
    uv run friday savings rules export out.csv

A row is only ever served to users when it has a public source link, a past check date and a
named person in ``verified_by`` (see friday/savings/rules.py). The CLI never invents a rule and
never marks a row verified on its own: ``verify`` needs ``--by`` with a person's name.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from friday.core.clock import SystemClock, ist_date
from friday.db.session import Database
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.rules import (
    CardRule,
    freshness,
    is_example,
    rules_from_csv,
    rules_to_csv,
    validate_rule,
)
from friday.savings.store import RulesRepo

Printer = Callable[[str], None]


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    sv = sub.add_parser("savings", help="savings engine tools (card rules table)")
    sv_sub = sv.add_subparsers(dest="savings_cmd", required=True)
    rules = sv_sub.add_parser("rules", help="the verified card rules table")
    rsub = rules.add_subparsers(dest="rules_cmd", required=True)
    imp = rsub.add_parser("import", help="load rows from a CSV (stored as drafts until verified)")
    imp.add_argument("file")
    imp.add_argument("--dry-run", action="store_true", help="validate only, store nothing")
    imp.add_argument("--allow-examples", action="store_true", help="dev only: accept EXAMPLE rows")
    ver = rsub.add_parser("verify", help="a person confirms a card's rows against the public page")
    ver.add_argument("card_key", help="e.g. hdfc-bank/regalia")
    ver.add_argument("--scope", default=None, help="one row, e.g. food_delivery (default: all rows)")
    ver.add_argument("--by", required=True, help="name of the person who checked the bank page")
    ver.add_argument("--checked-on", default=None, help="YYYY-MM-DD (default: today)")
    ver.add_argument("--source", default=None, help="public page the rule was read from")
    ls = rsub.add_parser("list", help="show the table with each row's status")
    ls.add_argument("--unverified", action="store_true")
    ls.add_argument("--stale", action="store_true")
    ex = rsub.add_parser("export", help="write the table to a CSV")
    ex.add_argument("file")


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def row_status(rule: CardRule, today: date, config: SavingsConfig = DEFAULT_CONFIG) -> str:
    """'served' | 'stale' | 'draft' (no verifier) | 'invalid' | 'example'."""
    if is_example(rule):
        return "example"
    issues = validate_rule(rule, today, config=config)
    if any(i.code == "unverified" for i in issues):
        return "draft"
    if issues:
        return "invalid"
    return "stale" if freshness(rule, today, config) != "fresh" else "served"


async def run_rules(
    args: argparse.Namespace,
    db: Database,
    *,
    today: date | None = None,
    out: Printer = print,
    config: SavingsConfig = DEFAULT_CONFIG,
) -> int:
    today = today or ist_date(SystemClock().now())
    repo = RulesRepo(db, SystemClock(), config)
    cmd = args.rules_cmd

    if cmd == "import":
        text = _read(args.file)
        stored = bad = 0
        for row in rules_from_csv(text):
            if row.rule is None:
                bad += 1
                out(f"line {row.line}: REJECTED  {row.error}")
                continue
            issues = [
                i
                for i in validate_rule(
                    row.rule, today, require_verified=False,
                    allow_examples=args.allow_examples, config=config,
                )
            ]
            if issues:
                bad += 1
                out(f"line {row.line}: REJECTED  " + "; ".join(f"{i.code}: {i.message}" for i in issues))
                continue
            if not args.dry_run:
                await repo.upsert(row.rule)
            stored += 1
            verified = "verified" if (row.rule.verified_by or "").strip() else "DRAFT (needs verify)"
            out(f"line {row.line}: ok  {row.rule.card_key} / {row.rule.scope}  [{verified}]")
        out(f"{'would store' if args.dry_run else 'stored'} {stored}, rejected {bad}")
        return 0 if bad == 0 else 1

    if cmd == "verify":
        by = args.by.strip()
        checked = date.fromisoformat(args.checked_on) if args.checked_on else today
        probe = [r for r in await repo.all() if r.card_key == args.card_key
                 and (not args.scope or r.scope == args.scope)]
        if not probe:
            out(f"no rows for {args.card_key}")
            return 1
        source = args.source or None
        for r in probe:
            candidate = r.model_copy(
                update={"verified_by": by, "checked_on": checked,
                        "source_url": source or r.source_url}
            )
            issues = validate_rule(candidate, today, config=config)
            if issues:
                out(f"{r.card_key} / {r.scope}: NOT verified  "
                    + "; ".join(f"{i.code}: {i.message}" for i in issues))
                return 1
        n = await repo.verify(args.card_key, args.scope, by=by, checked_on=checked, source_url=source)
        out(f"verified {n} row(s) of {args.card_key} by {by} on {checked}")
        return 0

    if cmd == "list":
        rows = await repo.all()
        shown = 0
        for r in rows:
            st = row_status(r, today, config)
            if args.unverified and st != "draft":
                continue
            if args.stale and st != "stale":
                continue
            age = "?" if r.checked_on is None else f"{(today - r.checked_on).days}d"
            out(f"{st:8s} {r.card_key:40s} {r.scope:28s} {r.rate_bp:5d}bp  checked {age:>5s}  by {r.verified_by or '-'}")
            shown += 1
        out(f"{shown} row(s)")
        return 0

    if cmd == "export":
        _write(args.file, rules_to_csv(await repo.all()))
        out(f"wrote {args.file}")
        return 0
    return 2


def run(args: argparse.Namespace, database_url: str) -> int:
    """Entry used by ``friday savings ...`` (friday/cli.py)."""
    import asyncio

    async def go() -> int:
        db = Database(database_url)
        try:
            return await run_rules(args, db)
        finally:
            await db.dispose()

    if args.savings_cmd != "rules":
        return 2
    return asyncio.run(go())


if __name__ == "__main__":  # pragma: no cover
    p = argparse.ArgumentParser(prog="friday")
    s = p.add_subparsers(dest="cmd", required=True)
    add_parser(s)
    ns = p.parse_args()
    from friday.core.config import Settings

    sys.exit(run(ns, Settings().database_url))
