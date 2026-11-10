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

import asyncio
import contextlib
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from friday.calls.numbers import is_emergency
from friday.core.logging import get_logger, mask_phone
from friday.core.models import AudioClass, DialStatus, Language, OutboundCallRequest
from friday.qa.override import note_pending_line, pending_lines_allowed
from friday.robin import answers as ans
from friday.robin import lines
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, Family, Member, Step, StepTiming

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
_MACHINE = (AudioClass.VOICEMAIL, AudioClass.IVR_PROMPT)  # far end is a machine: not a reached person
_IST = ZoneInfo("Asia/Kolkata")


class CallCostLedger:
    """Estimated call cost (rupees, ``friday.pilot.estimate_cost_inr``) per family per IST day, in memory, and one PII-free log line per call
    (family id, day, call and day totals; never a number or a word). Connected seconds only; an unanswered ring costs nothing here."""

    def __init__(self, today: Callable[[], date] | None = None) -> None:
        self._today = today or (lambda: datetime.now(UTC).astimezone(_IST).date())
        self.totals: dict[tuple[str, str], float] = {}

    def add(self, family_id: str, seconds: float) -> float:
        from friday.pilot import estimate_cost_inr

        cost = float(estimate_cost_inr(seconds))
        key = (family_id, self._today().isoformat())
        self.totals[key] = round(self.totals.get(key, 0.0) + cost, 1)
        log.info("robin: call cost estimate family=%s day=%s call_inr=%.1f day_inr=%.1f seconds=%.0f", family_id, key[1], cost, self.totals[key], seconds)
        return cost

    def per_family_day(self) -> dict[tuple[str, str], float]:
        return dict(self.totals)


class TelephonyParentCaller:
    def __init__(
        self, telephony: Any, settings: Any, *, ring_timeout_s: int = 25, paused: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic, costs: CallCostLedger | None = None,
    ) -> None:  # fmt: skip
        self._telephony, self.settings, self.ring_timeout_s, self.paused = telephony, settings, ring_timeout_s, paused
        self._clock, self.costs = clock, costs or CallCostLedger()

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
    ) -> CallOutcome:
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
        timings: list[StepTiming] = []
        t_answer: float | None = None

        def finish(result: CallResult, detail: str, *, early: bool = False) -> CallOutcome:
            secs = round(max(0.0, self._clock() - t_answer), 1) if t_answer is not None else 0.0
            cost = self.costs.add(family.id, secs) if t_answer is not None else 0.0
            return CallOutcome(result=result, detail=detail, answers=answers, hung_up_early=early, steps=timings, duration_s=secs, cost_inr=cost)

        async def say(key: str, step_slots: dict[str, str]) -> Any:
            return await leg.speak(lines.say(key, member.language, brand=brand, **step_slots), lang)

        try:
            try:
                status = await asyncio.wait_for(leg.wait_for_answer(self.ring_timeout_s), self.ring_timeout_s + 5)
            except TimeoutError:  # the provider never reported: the phone did not pick up in time
                return finish(CallResult.NO_ANSWER, "ring_timeout")
            if status != DialStatus.ANSWERED:  # VOICEMAIL is an answering machine: NOT reached (no ack, no check-in done, retry / ladder go on)
                return finish(_STATUS.get(status, CallResult.FAILED), "voicemail" if status == DialStatus.VOICEMAIL else str(status))
            t_answer = self._clock()
            silent_in_a_row = 0
            for step in steps:
                if self._clock() - t_answer > max_seconds:
                    return finish(CallResult.ANSWERED, "max_duration")
                t0 = self._clock()
                barge = await say(step.line, step.slots)  # a leg may return what the listener said OVER Robin (barge-in); real legs that cannot return None
                timing = StepTiming(line=step.line, speak_ms=int((self._clock() - t0) * 1000))
                timings.append(timing)
                barge_text = (getattr(barge, "text", "") or "").strip() if isinstance(getattr(barge, "text", None), str) else ""
                if barge_text:
                    timing.barge_in = True
                if step.expect == "none":
                    if barge_text and (ans.is_help(barge_text) or ans.is_threat(barge_text) or ans.is_stop(barge_text)):  # safety words are honoured even over the greeting
                        said, conf = barge_text[:200], getattr(barge, "confidence", None)
                    else:
                        continue
                else:
                    said, conf = barge_text[:200], getattr(barge, "confidence", None)
                    repeated = False
                    while True:
                        if not said:  # nothing said over Robin: listen
                            t1 = self._clock()
                            try:
                                heard = await asyncio.wait_for(leg.listen(LISTEN_S), LISTEN_S + 5)
                            except TimeoutError:
                                heard = None
                            timing.listen_ms += int((self._clock() - t1) * 1000)
                            if heard is not None and getattr(heard, "audio_class", None) in _MACHINE and not answers:  # a greeting / IVR, not a person
                                return finish(CallResult.NO_ANSWER, "voicemail")
                            said, conf = (getattr(heard, "text", "") or "").strip()[:200], getattr(heard, "confidence", None)
                        kind = ans.classify(said, conf)
                        unclear = kind == "silence" or (kind == "unclear" and step.expect == "yesno")
                        if not unclear or repeated:
                            break
                        repeated = True  # one gentle 'say it again', never more
                        timing.repeated = True
                        await say("call.repeat", step.slots)
                        said, conf = "", None
                    if kind == "silence":
                        timing.heard = "silence"
                        silent_in_a_row += 1
                        answers.append(AnswerRaw(line=step.line, text=""))
                        if silent_in_a_row >= 2:  # picked up but nobody speaks (pocket, hold): hang up; with no word at all this is NOT a reached parent
                            return finish(CallResult.ANSWERED if any(a.text for a in answers) else CallResult.NO_ANSWER, "silence")
                        continue
                    silent_in_a_row = 0
                kind = ans.classify(said, conf)
                timing.confidence = conf
                timing.heard = kind if step.expect == "yesno" or kind in ("help", "stop", "silence") else "text"
                answers.append(AnswerRaw(line=step.line, text=said))
                if ans.is_help(said) or ans.is_threat(said):  # 'madad' / 'help' / 'bachao': tell them the child is told; the caller raises the SOS
                    await say("sos.parent", steps[0].slots)
                    return finish(CallResult.ANSWERED, "help_requested")
                if ans.is_stop(said):  # the parent said 'stop': say the pause line and end the call
                    await say("pause.ack", steps[0].slots)
                    return finish(CallResult.ANSWERED, "stop_requested")
                yes = True if ans.is_fine(said) else ans.yesno(said)
                reply = step.on_yes if yes is True else step.on_no if yes is False else None
                if reply:
                    await say(reply, step.slots)
            return finish(CallResult.ANSWERED, "spoken")
        except Exception as e:  # noqa: BLE001 - CallEnded (they hung up) and anything else
            early = type(e).__name__ == "CallEnded"
            log.info("robin: call to %s ended (%s)", mask_phone(member.phone), type(e).__name__)
            return finish(CallResult.ANSWERED if early else CallResult.FAILED, type(e).__name__, early=early)
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
