# ruff: noqa: E501
"""`friday robin pause-all`: the founder's one kill switch for everything Robin does (T19). It is the existing global kill switch
(``friday pause``: flag file ``FRIDAY_PAUSE_FILE``, no restart, takes effect in about a second in every container) with Robin-specific words.

While it is ON:
* no call of any kind is placed by Robin (check-in, medicine, alert, intro, SOS ring): ``Ctx.call`` refuses with ``kill_switch``;
* the Robin scheduler runs ONLY the alert ladder for incidents that are already open (``RobinHub.tick``): no check-in plan, no digest, no medicine
  reminder, no greeting, no monthly reminder, no outbox drain, no device sweep, no authority step. Nothing new is started.
* an SOS from the parent's phone still WhatsApps the child (and the second contact); the rings are refused. That is deliberate: the switch must be able to
  stop calls to every phone, and a message to the child is the minimum that stays. [U: founder to confirm; see docs/ROBIN_PILOT_CHECKLIST.md]
Undo with ``friday robin pause-all --resume``. Per-family pause (the child's chat word "pause") is separate and untouched.
"""

from __future__ import annotations

import argparse
from typing import Any

PAUSED_WORDS = "no Robin call is placed, no check-in/digest/reminder/greeting starts; open alerts still message the child"


def add_subparser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("pause-all", help="KILL SWITCH for all of Robin: no calls, nothing new starts (undo with --resume)")
    p.add_argument("--resume", action="store_true", help="switch the kill switch OFF")
    p.add_argument("--status", action="store_true", help="only show whether Robin is paused")


def run(settings: Any, *, resume: bool, status_only: bool, out: Any = print) -> int:
    """0 = done / running, 3 = (status) paused, 1 = cannot resume because FRIDAY_PAUSED=true is set in the environment."""
    from friday.pause import is_paused, pause_status, set_paused

    if not status_only:
        set_paused(settings, on=not resume)
    out(f"Robin kill switch: {pause_status(settings)}")
    if status_only:
        out(f"Robin is {'PAUSED: ' + PAUSED_WORDS if is_paused(settings) else 'running'}.")
        return 3 if is_paused(settings) else 0
    if resume:
        if settings.paused:
            out("FRIDAY_PAUSED=true is still set in the environment: change it and restart.")
            return 1
        out("Resumed: Robin check-ins, reminders and calls continue at their next scheduled time.")
        return 0
    out(f"Paused: {PAUSED_WORDS}.")
    out("Calls already in progress finish normally. Undo with: friday robin pause-all --resume")
    return 0


def run_command(args: argparse.Namespace) -> int:
    from friday.core.config import Settings

    return run(Settings(), resume=args.resume, status_only=args.status)
