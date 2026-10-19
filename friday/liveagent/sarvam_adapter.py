"""Thin adapter: an existing Sarvam/Vobiz call leg (``SarvamCallLeg``) as a ``TelephonyPort``.

The voice stack is not touched. The leg already speaks (Sarvam TTS), listens (Sarvam STT with
barge-in), sends DTMF and hangs up; this file only maps types and the "call ended" signal.
UNVERIFIED on a live call (no real call was placed by this workstream).
"""

from __future__ import annotations

from typing import Any

from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, HeardUtterance

_TO_CORE = {"hinglish": "hinglish", "hi": "hi", "en": "en"}


class SarvamLegPort:
    def __init__(self, leg: Any) -> None:
        self.leg = leg

    def _ended(self, exc: Exception) -> bool:
        return type(exc).__name__ == "CallEnded"

    async def speak(self, text: str, language: CallLanguage) -> None:
        from friday.core.models import Language

        try:
            await self.leg.speak(text, Language(_TO_CORE[language.value]))
        except Exception as exc:
            if self._ended(exc):
                raise CallDropped("call ended while speaking") from exc
            raise

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        try:
            tr = await self.leg.listen(timeout_s)
        except Exception as exc:
            if self._ended(exc):
                raise CallDropped("call ended while listening") from exc
            raise
        if tr is None:
            return None
        ac = getattr(getattr(tr, "audio_class", None), "value", getattr(tr, "audio_class", "human"))
        lang = getattr(getattr(tr, "language", None), "value", None)
        return HeardUtterance(
            text=tr.text or "",
            language=lang,
            confidence=tr.confidence,
            audio_class=str(ac or "human"),
            duration_s=float(getattr(tr, "duration_s", None) or 0.0),
        )

    async def send_dtmf(self, digits: str) -> None:
        await self.leg.send_dtmf(digits)

    async def hangup(self) -> None:
        await self.leg.hangup()
