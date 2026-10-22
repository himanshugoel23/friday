"""`friday chatbot ...`: the founder's tools for the WhatsApp chatbot pilot.

    friday chatbot wishlist [--support] [--limit N]    what testers asked that Friday does not do
    friday chatbot templates check                     verify the template drafts against the code
    friday chatbot templates render                    print docs/WHATSAPP_TEMPLATES.md
    friday chatbot status                              first-run steps, waitlist size

`templates` never reads .env and never touches the network. `wishlist` and `status` read the
database named by FRIDAY_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Callable

Printer = Callable[[str], None]


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    cb = sub.add_parser("chatbot", help="WhatsApp chatbot pilot tools (wishlist, templates)")
    csub = cb.add_subparsers(dest="chatbot_cmd", required=True)
    wl = csub.add_parser("wishlist", help="print what testers asked that Friday does not do")
    wl.add_argument("--support", action="store_true", help="print support requests instead")
    wl.add_argument("--limit", type=int, default=200)
    csub.add_parser("status", help="first-run steps reached and the waitlist size")
    tpl = csub.add_parser("templates", help="the WhatsApp template drafts")
    tsub = tpl.add_subparsers(dest="templates_cmd", required=True)
    tsub.add_parser("check", help="verify placeholders, buttons, names and senders")
    tsub.add_parser("render", help="print docs/WHATSAPP_TEMPLATES.md from the YAML")


def run_offline(args: argparse.Namespace, out: Printer = print) -> int:
    """`friday chatbot templates ...`: no database, no .env."""
    from friday.chatbot import templates

    if args.templates_cmd == "render":
        out(templates.render())
        return 0
    report = templates.check()
    for p in report.problems:
        out(f"FAIL {p}")
    out(
        f"{report.drafts} template drafts, {report.registrations} registrations, "
        f"{report.call_sites} sender call sites: "
        + ("OK" if report.ok else f"{len(report.problems)} problem(s)")
    )
    return 0 if report.ok else 1


async def _wishlist(db_url: str, support: bool, limit: int, out: Printer) -> int:
    from friday.db.repositories.chatbot import ChatbotRepo
    from friday.db.session import Database

    db = Database(db_url)
    try:
        repo = ChatbotRepo(db)
        kind = "support" if support else "wishlist"
        items = await repo.inbox_list(kind, limit=limit)
        if not items:
            out(f"no {kind} entries yet")
            return 0
        counts = Counter(i.text.lower() for i in items)
        out(f"{len(items)} {kind} entries ({len(counts)} different), newest first")
        for i in items:
            when = i.created_at.strftime("%Y-%m-%d %H:%M")
            out(f"{when}  [{i.lang}]  {i.text}")
        repeated = [(t, n) for t, n in counts.most_common() if n > 1]
        if repeated:
            out("asked more than once:")
            for t, n in repeated:
                out(f"  {n}x  {t}")
        return 0
    finally:
        await db.dispose()


async def _status(db_url: str, out: Printer) -> int:
    from friday.db.repositories.chatbot import ChatbotRepo
    from friday.db.session import Database

    db = Database(db_url)
    try:
        repo = ChatbotRepo(db)
        steps = await repo.count_sessions()
        out(
            "first-run steps (people per step): "
            + (", ".join(f"{k}={v}" for k, v in sorted(steps.items())) or "none")
        )
        out(f"waitlist (numbers, hash only): {await repo.waitlist_count()}")
        return 0
    finally:
        await db.dispose()


def run(args: argparse.Namespace, db_url: str, out: Printer = print) -> int:
    if args.chatbot_cmd == "wishlist":
        return asyncio.run(_wishlist(db_url, args.support, args.limit, out))
    if args.chatbot_cmd == "status":
        return asyncio.run(_status(db_url, out))
    return run_offline(args, out)
