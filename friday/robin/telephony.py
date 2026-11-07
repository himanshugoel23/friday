# ruff: noqa: E501
"""The REAL dial of Robin: ring a family member's number, speak fixed lines, listen for short answers.

Not exercised against a real phone (no real call without the founder's approval, CLAUDE.md rule 5); tests
use a fake provider leg. It REFUSES, by construction, while the spoken lines are PENDING:

    lines.LINE_STATUS != "APPROVED"  ->  CallOutcome(REFUSED, "line_pending")

so even with every switch on nothing can ring a phone until the founder has heard the audio and a
reviewed commit flips the constant. It also refuses on the kill switch and on a number outside the pilot
allow-list, independently of ``context.Ctx.call`` and the CallGate (defence in depth). Calls are never
recorded (``record=False``). Only the words the listener says are returned, as text; no audio is kept.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from friday.calls.numbers import is_emergency
from friday.core.logging import get_logger, mask_phone
from friday.core.models import DialStatus, Language, OutboundCallRequest
from friday.qa.override import note_pending_line, pending_lines_allowed
from friday.robin import answers as ans
from friday.robin import lines
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, Family, Member, Step

log = get_logger(__name__)

_STATUS = {
    DialStatus.ANSWERED: CallResult.ANSWERED,
    DialStatus.BUSY: CallResult.BUSY,
    DialStatus.NO_ANSWER: CallResult.NO_ANSWER,
    DialStatus.VOICEMAIL: CallResult.NO_ANSWER,
    DialStatus.FAILED: CallResult.FAILED,
}
_LANG = {"hinglish": Language.HINGLISH, "hi": Language.HI, "en": Language.EN}
LISTEN_S = 8.0


class TelephonyParentCaller:
    def __init__(
        self, telephony: Any, settings: Any, *, ring_timeout_s: int = 25, paused: Callable[[], bool] = lambda: False
    ) -> None:  # fmt: skip
        self._telephony, self.settings, self.ring_timeout_s, self.paused = telephony, settings, ring_timeout_s, paused

    def _tel(self) -> Any:
        return self._telephony() if callable(self._telephony) else self._telephony

    def _refusal(self, number: str | None, keys: list[str]) -> CallOutcome | None:
        if number and is_emergency(number):  # FIRST and unconditional: Robin never rings 112/100/101/102/108/1930 (any written form), whatever the switches or the QA override say
            log.error("robin: refused to dial an emergency/public-safety number (ROBIN_EMERGENCY_NUMBER_REFUSED)")
            return CallOutcome(result=CallResult.REFUSED, detail="emergency_number")
        qa_ok = pending_lines_allowed(self.settings) and number in set(self.settings.pilot_allowed_numbers)  # QA: founder's own number only
        if not lines.approved() and not qa_ok:
            return CallOutcome(result=CallResult.REFUSED, detail="line_pending")
        if self.paused():
            return CallOutcome(result=CallResult.REFUSED, detail="kill_switch")
        if not number or self.settings.pilot_dial_blocked(number):
            return CallOutcome(result=CallResult.REFUSED, detail="test_allowlist")
        if not lines.approved():
            for k in keys:
                note_pending_line("robin", f"robin.{k}")
        return None

    async def converse(
        self, *, member: Member, family: Family, purpose: str, steps: list[Step], dedupe_key: str, brand: str, max_seconds: int = 180
    ) -> CallOutcome:  # noqa: ARG002
        refusal = self._refusal(member.phone, [s.line for s in steps])
        if refusal is not None:
            return refusal
        lang = _LANG.get(member.language, Language.HINGLISH)
        req = OutboundCallRequest(
            to_phone=member.phone or "", task_id=dedupe_key, record=False, ring_timeout_s=self.ring_timeout_s,
            max_duration_s=max_seconds, language=lang, metadata={"call_id": dedupe_key, "kind": f"robin_{purpose}"},
        )  # fmt: skip
        try:
            leg = await self._tel().place_call(req)
        except Exception as e:  # noqa: BLE001 - provider error, kill-switch guard, anything
            log.warning("robin: call to %s not placed (%s)", mask_phone(member.phone), type(e).__name__)
            return CallOutcome(result=CallResult.FAILED, detail=type(e).__name__)
        answers: list[AnswerRaw] = []
        try:
            status = await leg.wait_for_answer(self.ring_timeout_s)
            if status != DialStatus.ANSWERED:
                return CallOutcome(result=_STATUS.get(status, CallResult.FAILED), detail=str(status))
            for step in steps:
                await leg.speak(lines.say(step.line, member.language, brand=brand, **step.slots), lang)
                if step.expect == "none":
                    continue
                heard = await leg.listen(LISTEN_S)
                said = (getattr(heard, "text", "") or "")[:200]
                answers.append(AnswerRaw(line=step.line, text=said))
                yes = True if ans.is_fine(said) else ans.yesno(said)
                reply = step.on_yes if yes is True else step.on_no if yes is False else None
                if reply and not ans.is_stop(said):
                    await leg.speak(lines.say(reply, member.language, brand=brand, **step.slots), lang)
                if ans.is_stop(said):  # the parent said 'stop': say the pause line and end the call
                    await leg.speak(lines.say("pause.ack", member.language, brand=brand, **steps[0].slots), lang)
                    return CallOutcome(result=CallResult.ANSWERED, detail="stop_requested", answers=answers)
            return CallOutcome(result=CallResult.ANSWERED, detail="spoken", answers=answers)
        except Exception as e:  # noqa: BLE001 - CallEnded (they hung up) and anything else
            early = type(e).__name__ == "CallEnded"
            log.info("robin: call to %s ended (%s)", mask_phone(member.phone), type(e).__name__)
            return CallOutcome(result=CallResult.ANSWERED if early else CallResult.FAILED, detail=type(e).__name__, answers=answers, hung_up_early=early)
        finally:
            with contextlib.suppress(Exception):
                await leg.hangup()

    async def bridge(self, *, child: Member, parent: Member, family: Family, dedupe_key: str, brand: str) -> CallOutcome:
        """Ring the child, and when they answer add the parent to the same call ('Robin joins the call').
        UNVERIFIED on a real provider: needs a supervised test (docs/ROBIN_FAMILY_CORE.md)."""
        for m in (child, parent):
            refusal = self._refusal(m.phone, ["bridge.child", "bridge.parent"])
            if refusal is not None:
                return refusal
        lang = _LANG.get(child.language, Language.HINGLISH)
        req = OutboundCallRequest(
            to_phone=child.phone or "", task_id=dedupe_key, record=False, ring_timeout_s=self.ring_timeout_s,
            max_duration_s=600, language=lang, metadata={"call_id": dedupe_key, "kind": "robin_bridge"},
        )  # fmt: skip
        try:
            leg = await self._tel().place_call(req)
        except Exception as e:  # noqa: BLE001
            return CallOutcome(result=CallResult.FAILED, detail=type(e).__name__)
        try:
            status = await leg.wait_for_answer(self.ring_timeout_s)
            if status != DialStatus.ANSWERED:
                return CallOutcome(result=_STATUS.get(status, CallResult.FAILED), detail=str(status))
            slots = {"parent": family.parent_label, "child": child.name or "ji"}
            await leg.speak(lines.say("bridge.child", child.language, brand=brand, **slots), lang)
            await leg.add_participant(parent.phone or "", announce=lines.say("bridge.parent", parent.language, brand=brand, **slots))
            await leg.leave()  # Robin drops out; the two stay connected
            return CallOutcome(result=CallResult.ANSWERED, detail="bridged")
        except Exception as e:  # noqa: BLE001
            with contextlib.suppress(Exception):
                await leg.hangup()
            return CallOutcome(result=CallResult.FAILED, detail=type(e).__name__)
