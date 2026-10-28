# ruff: noqa: E501
"""The REAL dial of the escalation: ring the user's own number and speak one fixed line.

Not exercised against a real phone (no real call without the founder's approval, CLAUDE.md rule 5);
tests use a fake provider leg. It REFUSES, by construction, while the spoken line is PENDING:

    lines.LINE_STATUS != "APPROVED"  ->  RingOutcome(REFUSED, "line_pending")

so even with every switch on nothing can ring a phone until the founder has heard the audio and a
reviewed commit flips the constant. It also refuses on the kill switch and on a number outside the
pilot allow-list, independently of ``service.py`` and the CallGate (defence in depth).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from friday.core.logging import get_logger, mask_phone
from friday.core.models import DialStatus, Language, OutboundCallRequest
from friday.qa.override import note_pending_line, pending_lines_allowed
from friday.urgent import lines
from friday.urgent.models import RingOutcome, RingResult

log = get_logger(__name__)

_STATUS = {
    DialStatus.ANSWERED: RingResult.ANSWERED,
    DialStatus.BUSY: RingResult.BUSY,
    DialStatus.NO_ANSWER: RingResult.NO_ANSWER,
    DialStatus.VOICEMAIL: RingResult.VOICEMAIL,
    DialStatus.FAILED: RingResult.FAILED,
}
_LANG = {"hinglish": Language.HINGLISH, "hi": Language.HI, "en": Language.EN}


class TelephonyOwnNumberCaller:
    def __init__(
        self, telephony: Any, settings: Any, *, ring_timeout_s: int = 25, max_seconds: int = 45,
        paused: Callable[[], bool] = lambda: False,
    ) -> None:  # fmt: skip
        self._telephony, self.settings = telephony, settings
        self.ring_timeout_s, self.max_seconds, self.paused = ring_timeout_s, max_seconds, paused

    def _tel(self) -> Any:
        return self._telephony() if callable(self._telephony) else self._telephony

    async def ring(
        self, *, user_id: str, number: str, line_key: str, lang: str, user_name: str, dedupe_key: str
    ) -> RingOutcome:
        # QA override: pending lines play only on a QA call to the founder's own allow-listed number
        qa_ok = pending_lines_allowed(self.settings) and number in set(self.settings.pilot_allowed_numbers)
        if not lines.approved() and not qa_ok:
            return RingOutcome(result=RingResult.REFUSED, detail="line_pending")
        if self.paused():
            return RingOutcome(result=RingResult.REFUSED, detail="kill_switch")
        if self.settings.pilot_dial_blocked(number):
            return RingOutcome(result=RingResult.REFUSED, detail="test_allowlist")
        name = (user_name or "").strip() or ("there" if lang == "en" else "ji")
        text = lines.say(line_key, lang, user=name)
        if not lines.approved():
            note_pending_line("urgent", f"urg.{line_key}.{lang if lang in lines.LANGS else 'hinglish'}")
        req = OutboundCallRequest(
            to_phone=number, task_id=dedupe_key, record=False, ring_timeout_s=self.ring_timeout_s,
            max_duration_s=self.max_seconds, language=_LANG.get(lang, Language.HINGLISH),
            metadata={"call_id": dedupe_key, "kind": "urgent_escalation"},
        )  # fmt: skip
        try:
            leg = await self._tel().place_call(req)
        except Exception as e:  # noqa: BLE001 - provider error, kill-switch guard, anything
            log.warning("urgent escalation: call to %s not placed (%s)", mask_phone(number), type(e).__name__)
            return RingOutcome(result=RingResult.FAILED, detail=type(e).__name__)
        try:
            status = await leg.wait_for_answer(self.ring_timeout_s)
            if status != DialStatus.ANSWERED:
                return RingOutcome(result=_STATUS.get(status, RingResult.FAILED), detail=str(status))
            await leg.speak(text, _LANG.get(lang, Language.HINGLISH))
            return RingOutcome(result=RingResult.ANSWERED, detail="spoken")
        except Exception as e:  # noqa: BLE001
            log.warning("urgent escalation: call to %s failed (%s)", mask_phone(number), type(e).__name__)
            return RingOutcome(result=RingResult.FAILED, detail=type(e).__name__)
        finally:
            with contextlib.suppress(Exception):
                await leg.hangup()
