# ruff: noqa: E501
"""``friday robin call-test``: ONE supervised check-in call to the allow-listed founder number, nothing else.

    friday robin call-test --plan-only      show what would be spoken; dials nothing
    friday robin call-test                  type the approval phrase, then ONE call is placed

Every guard is the QA one (``friday.qa.safety.QaGuard``): FRIDAY_QA_LIVE=true, FRIDAY_MODE=live, FRIDAY_PROFILE=pilot, exactly one number in
FRIDAY_PILOT_ALLOWED_NUMBERS (the founder's), kill switch, the QA daily call and spend caps. ``--to`` may only repeat that number; any other is refused
before anything is dialled. While the call runs, the QA override lets the PENDING lines be spoken to that number only, and each pending line id spoken is
logged so the founder can approve or reject it by id (``friday qa report``). The call is never recorded. The printed result holds NO words the listener
said and no phone number (only its last two digits): outcome, detail, per-step timings in milliseconds, STT confidence, a class per answer, an estimated cost.

Tested with fake telephony only (tests/robin/test_telephony_live_fake.py). The real run is a founder-supervised step (T19), founder present.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from collections.abc import Callable
from typing import Any

from friday.integration.telephony import mask2
from friday.qa.config import APPROVAL_PHRASE, QaConfig
from friday.qa.override import pending_lines_allowed
from friday.qa.safety import QaGuard, QaRefused
from friday.qa.store import QaStore
from friday.robin import lines
from friday.robin.checkin import base_steps
from friday.robin.models import CallOutcome, CallResult, Family, Member, Role
from friday.robin.telephony import TelephonyParentCaller
from friday.robindevice.brand import brand_name

SCENARIO = "robin_call_test"


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("robin", help="Robin tools (supervised live-test commands)")
    r = p.add_subparsers(dest="robin_cmd", required=True)
    ct = r.add_parser("call-test", help="ONE check-in call to the allow-listed founder number (QA guards; asks for the approval phrase)")
    ct.add_argument("--to", default=None, help="must equal the allow-listed founder number (default); any other number is refused")
    ct.add_argument("--language", choices=["hinglish", "hi", "en"], default="hinglish")
    ct.add_argument("--parent", default="Papa", help="how the check-in addresses the parent (a label, not a name from any family)")
    ct.add_argument("--child", default="Asha", help="the child's name said on the call (invented)")
    ct.add_argument("--seconds", type=int, default=None, help="call length cap (QA maximum applies)")
    ct.add_argument("--plan-only", action="store_true", help="print the plan, dial nothing")


def result_lines(out: CallOutcome) -> list[str]:
    """The PII-free report: no transcript, no number. Safe to paste into chat or git."""
    rows = [
        f"Outcome: {out.result.value} ({out.detail or '-'})",
        f"Reached: {'yes' if out.result == CallResult.ANSWERED else 'no'}",
        f"Connected: {out.duration_s:.1f} s, estimated cost Rs {out.cost_inr:.1f}",
    ]
    for i, t in enumerate(out.steps, 1):
        conf = "-" if t.confidence is None else f"{t.confidence:.2f}"
        flags = ("barge-in " if t.barge_in else "") + ("repeated" if t.repeated else "")
        rows.append(f"  {i:>2}. {t.line:<20} speak {t.speak_ms:>5} ms  listen {t.listen_ms:>5} ms  stt {conf:>4}  heard {t.heard:<8} {flags}".rstrip())
    return rows


async def run_call_test(
    args: argparse.Namespace, settings: Any, qa: QaConfig, store: QaStore, telephony: Any, *,
    input_fn: Callable[[str], str] = input, out: Callable[[str], None] = print, clock: Callable[[], float] | None = None,
) -> int:  # fmt: skip
    guard = QaGuard(settings, qa, store)
    try:
        number, secs, est = guard.check_call(args.to or guard.target, args.seconds)  # only the allow-listed founder number passes
    except QaRefused as e:
        out(f"REFUSED: {e}")
        return 2
    steps = base_steps({"parent": args.parent, "child": args.child})
    out(f"Plan: one check-in call to {mask2(number)} ({args.language}), at most {secs} s, estimated cost Rs {est:.1f}. Not recorded.")
    for s in steps:
        out(f"  - {s.line}" + (f"  (listens: {s.expect})" if s.expect != "none" else ""))
    if not lines.approved():
        out("The Robin lines are PENDING_FOUNDER_APPROVAL: they play on this call only because of the founder-number QA override.")
    if args.plan_only:
        out("Plan only: nothing was dialled.")
        return 0
    if input_fn(f"\nType exactly  {APPROVAL_PHRASE}  to place the call (anything else cancels): ").strip() != APPROVAL_PHRASE:
        out("Cancelled: nothing was dialled.")
        return 1
    member = Member(family_id="calltest", role=Role.PARENT, phone=number, language=args.language)
    family = Family(owner_user_id="calltest", parent_label=args.parent)
    caller = TelephonyParentCaller(telephony, settings, paused=guard._paused, **({"clock": clock} if clock else {}))  # noqa: SLF001
    with guard.session(SCENARIO):
        if not pending_lines_allowed(settings):
            out("REFUSED: the QA override is not active (check FRIDAY_MODE / FRIDAY_PROFILE / the allow-list).")
            return 2
        res = await caller.converse(member=member, family=family, purpose="calltest", steps=steps, dedupe_key=f"calltest:{secrets.token_hex(4)}", brand=brand_name(settings), max_seconds=secs)
    if res.result != CallResult.REFUSED:
        guard.record_call(SCENARIO, res.duration_s, res.cost_inr)
    out("")
    for row in result_lines(res):
        out(row)
    if res.result == CallResult.REFUSED:
        out("Nothing was dialled.")
    out("\nNow hear the pending lines and decide:  friday qa report  /  friday qa line <id> approve|reject")
    return 0 if res.result == CallResult.ANSWERED else 1


def run_command(args: argparse.Namespace) -> int:
    from friday.core.config import Settings

    settings, qa = Settings(), QaConfig()
    store = QaStore(qa.path)
    if args.robin_cmd != "call-test":
        return 2
    if args.plan_only:
        return asyncio.run(run_call_test(args, settings, qa, store, None))

    async def go() -> int:
        from friday.qa.live import LiveBackend

        guard = QaGuard(settings, qa, store)
        try:
            guard.require_startable()
        except QaRefused as e:
            print(f"REFUSED: {e}")
            return 2
        async with LiveBackend(settings, qa).serving(lambda line: print(line, flush=True)) as c:  # the real adapter: UNEXERCISED here, founder-supervised in T19
            return await run_call_test(args, settings, qa, store, c.get("telephony"))

    try:
        return asyncio.run(go())
    except KeyboardInterrupt:
        print("\nStopped by you.")
        return 130
