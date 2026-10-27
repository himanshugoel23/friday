# ruff: noqa: E501
"""Item 11: reminder escalation, WhatsApp -> call, only to the user's OWN number.

Rules (all must hold for a call): the switch is on (default OFF); the user was already reminded on
WhatsApp and has not acknowledged within ``wait_s``; the call target equals the user's own number
(never anyone else's); and the CallGate allows it. This module only DECIDES; the caller places the
call through the normal call path. Nothing here dials.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DEFAULT_WAIT_S = 600


class Step(StrEnum):
    NONE = "none"  # nothing to do yet
    CALL = "call"  # place the reminder call to the user's own number
    SKIP_DISABLED = "skip_disabled"
    SKIP_ACKED = "skip_acked"
    SKIP_NOT_OWN_NUMBER = "skip_not_own_number"
    SKIP_GATE = "skip_gate"
    SKIP_ALREADY_CALLED = "skip_already_called"


@dataclass(frozen=True)
class Reminder:
    id: str
    user_id: str
    user_phone: str  # E.164, the user's own number
    call_target: str  # who the call would go to
    text: str
    whatsapp_sent_at: datetime | None = None
    acknowledged: bool = False
    called: bool = False


GateCheck = Callable[[Reminder], Awaitable[bool]]  # True when CallGate.decide allowed the call


async def decide(
    r: Reminder,
    now: datetime,
    *,
    enabled: bool,
    gate_allows: GateCheck,
    wait_s: int = DEFAULT_WAIT_S,
) -> Step:
    if not enabled:
        return Step.SKIP_DISABLED
    if r.acknowledged:
        return Step.SKIP_ACKED
    if r.called:
        return Step.SKIP_ALREADY_CALLED
    if r.whatsapp_sent_at is None or now < r.whatsapp_sent_at + timedelta(seconds=wait_s):
        return Step.NONE
    if r.call_target != r.user_phone:
        return Step.SKIP_NOT_OWN_NUMBER
    if not await gate_allows(r):
        return Step.SKIP_GATE
    return Step.CALL


def callgate_check(gate, build_request, build_brief, user, now_fn) -> GateCheck:
    """Adapt a ``friday.calls.gate.CallGate`` to ``GateCheck``.

    ``build_request(reminder)`` / ``build_brief(reminder, request)`` make the CallRequest/CallBrief
    (callee_kind FAMILY_FRIEND, the user's own number); the gate has the final say on kill switch,
    DNC, caps and the calling window.
    """

    async def check(r: Reminder) -> bool:
        req = build_request(r)
        decision = await gate.decide(req, build_brief(r, req), user, now_fn())
        return decision.allowed

    return check
