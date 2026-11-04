# ruff: noqa: E501
"""The CallGate in front of every Robin dial (friday.calls.gate.CallGate, unchanged).

A Robin call is an ordinary Friday call as far as the gate is concerned: callee kind FAMILY_FRIEND, the
number is a consenting family member's. What the gate contributes (kill switch, user standing, abuse
classifier, emergency numbers, the PILOT ALLOW-LIST, do-not-call, caps, calling window) is not
re-implemented here. In the pilot the parent's number must therefore be explicitly allow-listed
(``FRIDAY_PILOT_ALLOWED_NUMBERS``); otherwise nothing rings.

The per-call "approve this brief" step is replaced by the family's STANDING consent: the caller
(``context.Ctx.call``) has already checked consent, pause and quiet hours before asking here.
``outside_window`` (08:00 to 21:30 IST) is the one "ask" that an emergency or a HIGH-with-money alert may
override. Any other ask, and every deny, means no call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.calls.gate import CallGate, Verdict
from friday.calls.models import CallBrief, CalleeKind, CallRequest
from friday.calls.numbers import NumberHasher, canonical
from friday.core.models import User
from friday.urgent.gate import GateResult

PURPOSE = "family care call to a consenting family member"


class RobinGate:
    def __init__(self, gate: CallGate, hasher: NumberHasher, core_settings: Any = None) -> None:
        self.gate, self.hasher, self.core = gate, hasher, core_settings

    async def check(self, owner: User, number: str, *, override_window: bool, now: datetime) -> GateResult:
        e164 = canonical(number)
        if e164 is None:
            return GateResult(False, ("invalid_number",))
        if self.core is not None and self.core.pilot_dial_blocked(e164):
            return GateResult(False, ("test_allowlist",))  # belt and braces: the gate checks this too
        req = CallRequest(
            user_id=owner.id, callee_kind=CalleeKind.FAMILY_FRIEND, purpose=PURPOSE, callee_ref="family",
            callee_number=e164, number_confirmed=True, language="hinglish",
        )  # fmt: skip
        brief = CallBrief(
            request_id=req.id, user_id=owner.id, callee_kind=CalleeKind.FAMILY_FRIEND, goal=PURPOSE,
            callee_number_hash=self.hasher.hash(e164),
        )  # fmt: skip
        brief = brief.model_copy(update={"approved": True, "approval_hash": brief.content_hash(), "approved_at": now})
        d = await self.gate.decide(req, brief, owner, now)
        if d.verdict == Verdict.ALLOW:
            return GateResult(True, tuple(d.reasons))
        if d.verdict == Verdict.ASK and override_window and set(d.reasons) == {"outside_window"}:
            return GateResult(True, ("window_overridden",))
        return GateResult(False, tuple(d.reasons))


class AllowAllGate:
    """Tests that do not exercise the CallGate."""

    async def check(self, owner: User, number: str, *, override_window: bool, now: datetime) -> GateResult:  # noqa: ARG002
        return GateResult(True, ("fake",))
