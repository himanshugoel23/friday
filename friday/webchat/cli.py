# ruff: noqa: E501
"""``friday web``: invite, list and revoke testers, read feedback. Local files only (var/web/), no network.

    friday web invite --name "Asha" --phone +91...   prints her personal link ONCE
    friday web testers
    friday web revoke <id or name>
    friday web feedback [--tester <id or name>]
"""

from __future__ import annotations

import argparse
from typing import Any

from friday.core.config import Settings
from friday.webchat.app import link_for
from friday.webchat.config import WebConfig
from friday.webchat.registry import InviteRefused, Registry, allowed_numbers


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("web", help="Friday Web channel: testers, personal links, feedback")
    wsub = p.add_subparsers(dest="web_cmd", required=True)
    inv = wsub.add_parser("invite", help="create a tester's personal link (bound to their own phone)")
    inv.add_argument("--name", required=True)
    inv.add_argument("--phone", required=True, help="their own number; must be in FRIDAY_PILOT_ALLOWED_NUMBERS or FRIDAY_CHATBOT_TESTERS")
    inv.add_argument("--days", type=float, default=None, help="link life in days (default FRIDAY_WEB_INVITE_DAYS, 30)")
    wsub.add_parser("testers", help="list testers (numbers masked)")
    rev = wsub.add_parser("revoke", help="switch a tester's link off")
    rev.add_argument("tester", help="id or name")
    fb = wsub.add_parser("feedback", help="thumbs and 'mark wrong' notes from testers")
    fb.add_argument("--tester", default=None)


def run_command(args: argparse.Namespace, settings: Settings | None = None, out: Any = print) -> int:
    settings = settings or Settings()
    cfg = WebConfig()
    reg = Registry(cfg.path)
    cmd = args.web_cmd
    if cmd == "invite":
        try:
            tester, token = reg.invite(
                args.name, args.phone, allowed=allowed_numbers(settings),
                days=args.days or cfg.invite_days, default_cc=settings.default_country_code,
            )
        except InviteRefused as e:
            out(f"REFUSED: {e}")
            return 2
        out(f"Invited {tester.name} ({tester.id}), link valid until {tester.expires_at[:10]}.")
        out("Personal link (shown once; share it privately; anyone with it can chat as them):\n")
        out(f"  {link_for(settings, token)}\n")
        if not cfg.channel_enabled:
            out("NOTE: FRIDAY_WEB_CHANNEL_ENABLED is not true on the server yet; the link works once it is.")
        return 0
    if cmd == "testers":
        if not reg.all():
            out("no testers yet: friday web invite --name ... --phone ...")
        for t in reg.all():
            calls, spend = reg.usage(t.id)
            state = "active" if t.active() else ("revoked" if t.revoked_at else "expired")
            out(f"{t.id}  {t.name:<16} {t.public()['phone']:<16} {state:<8} consent={'yes' if t.consented_at else 'no'}  today: {calls} calls Rs {spend:.0f}  until {t.expires_at[:10]}")
        return 0
    if cmd == "revoke":
        t = reg.revoke(args.tester)
        out(f"revoked {t.name} ({t.id})" if t else "no such tester")
        return 0 if t else 1
    if cmd == "feedback":
        rows = reg.feedback(args.tester)
        if not rows:
            out("no feedback yet")
        for r in rows:
            out(f"{r['ts'][:16].replace('T', ' ')}  {r['tester']:<12} {r['kind']:<6} {r['text'][:100]!r}  {r['note']}")
        return 0
    return 2
