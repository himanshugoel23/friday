# ruff: noqa: E501
"""The CallGate in front of the escalation dial (friday.calls.gate.CallGate, unchanged).

The escalation call is an ordinary Friday call as far as the gate is concerned: callee kind
FAMILY_FRIEND, the number is the USER'S OWN. What the gate contributes (kill switch, pilot allow-list,
do-not-call, per-user and per-number caps, emergency numbers, the abuse classifier) is not
re-implemented here.

Two points of design:

* The per-call "approve this brief" step is replaced by the user's STANDING opt-in: the brief is marked
  approved with its own hash only because ``UserEscalationConfig.opted_in`` is true and the opt-in was
  made from that very number. The caller checks the opt-in first (``policy.decide``).
* ``outside_window`` (the family calling window 08:00 to 21:30 IST) is the one "ask" that a TRUE
  emergency may override. Any other ask, and every deny, means no call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from friday.calls.gate import CallGate, Verdict
from friday.calls.models import CallBrief, CalleeKind, CallRequest
from friday.calls.numbers import NumberHasher, canonical
from friday.core.models import User

PURPOSE = "own-number notification of an urgent WhatsApp message"


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reasons: tuple[str, ...] = ()


class OwnNumberGate:
    def __init__(self, gate: CallGate, hasher: NumberHasher, core_settings: Any = None) -> None:
        self.gate, self.hasher, self.core = gate, hasher, core_settings

    async def check(self, user: User, number: str, *, emergency: bool, now: datetime) -> GateResult:
        e164 = canonical(number)
        if e164 is None or e164 != canonical(user.phone):
            return GateResult(False, ("not_own_number",))  # belt and braces: the gate is not the only wall
        if self.core is not None and self.core.pilot_dial_blocked(e164):
            return GateResult(False, ("test_allowlist",))
        req = CallRequest(
            user_id=user.id, callee_kind=CalleeKind.FAMILY_FRIEND, purpose=PURPOSE, callee_ref="self",
            callee_number=e164, number_confirmed=True, language="hinglish",
        )  # fmt: skip
        brief = CallBrief(
            request_id=req.id, user_id=user.id, callee_kind=CalleeKind.FAMILY_FRIEND, goal=PURPOSE,
            callee_number_hash=self.hasher.hash(e164),
        )  # fmt: skip
        brief = brief.model_copy(
            update={"approved": True, "approval_hash": brief.content_hash(), "approved_at": now}
        )  # the standing opt-in is the approval
        d = await self.gate.decide(req, brief, user, now)
        if d.verdict == Verdict.ALLOW:
            return GateResult(True, tuple(d.reasons))
        if d.verdict == Verdict.ASK and emergency and set(d.reasons) == {"outside_window"}:
            return GateResult(True, ("emergency_overrides_window",))
        return GateResult(False, tuple(d.reasons))
