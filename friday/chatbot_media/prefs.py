"""Per-user voice preference and the state of the current turn.

* preference: ``mirror`` (default: voice reply to a voice note, text reply to text), ``text``,
  ``voice`` or ``both``. Changed by a short message such as "text mein reply karo".
* turn state: did the user's LAST message arrive as a voice note, and in which script. The outbound
  hook reads it, so a reply to a typed message is never spoken by accident.

Both live in the shared cache (``friday.core.scale.Cache``: Redis in production, memory in
tests). They hold no message text. The preference has a long TTL; a dedicated column is the
durable home and a decision for the founder (docs/VOICE_NOTES_AND_DEVANAGARI.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from friday.core.scale import Cache
from friday.lang_dev.normalise import normalise_text

Mode = Literal["mirror", "text", "voice", "both"]
MODES: tuple[Mode, ...] = ("mirror", "text", "voice", "both")
DEFAULT_MODE: Mode = "mirror"
PREF_TTL_S = 400 * 86400
TURN_TTL_S = 15 * 60
VOICE_TURN_WINDOW = timedelta(minutes=10)

_VOICE_WORD = r"(?:voice(?:\s*-?\s*note)?s?|vn|bol\s*ke|bolkar|awaaz(?:\s*mein)?|audio)"
_TEXT_WORD = r"(?:text|likh\s*ke|likhkar|message|msg|chat)"
# "reply" as people type it, incl. what the Devanagari normaliser makes of रिप्लाई / जवाब
_REPLY = r"(?:reply|replay|ripla+(?:ee|i|e)|jawa+b|javaa?b|bhejo|bhejna|batao|bolo|do)"
_MIRROR = re.compile(
    r"\b(?:mirror|auto|jaisa\s+main\s+(?:bhejun|bhejoon|bhejta|bhejti)\s+waisa|"
    r"jaise\s+main\s+(?:bhejun|bhejoon|bhejta|bhejti)\s+waise|default)\b",
    re.I,
)
_BOTH = re.compile(
    rf"\b(?:dono|both|{_VOICE_WORD}\s+(?:aur|and|\+)\s+{_TEXT_WORD}|"
    rf"{_TEXT_WORD}\s+(?:aur|and|\+)\s+{_VOICE_WORD})\b",
    re.I,
)
_TEXT_ONLY = re.compile(
    rf"\b(?:sirf\s+{_TEXT_WORD}|{_TEXT_WORD}\s+(?:only|hi)|"
    rf"{_TEXT_WORD}\s+(?:mein|me|par|pe)\s+(?:hi\s+)?{_REPLY}|"
    rf"{_VOICE_WORD}\s+(?:mat|nahi|band|off)|(?:mat|nahi)\s+{_VOICE_WORD}|{_VOICE_WORD}\s+band)\b",
    re.I,
)
_VOICE_ONLY = re.compile(
    rf"\b(?:sirf\s+{_VOICE_WORD}|{_VOICE_WORD}\s+(?:only|hi)|"
    rf"{_VOICE_WORD}\s+(?:mein|me|par|pe)\s+(?:hi\s+)?{_REPLY}|"
    rf"{_VOICE_WORD}\s+(?:bhejo|bhejna|karo|on|chalu)|reply\s+{_VOICE_WORD})\b",
    re.I,
)
_MAX_WORDS = 8


def parse_pref_command(text: str) -> Mode | None:
    """The mode a short message asks for, or None. Devanagari is read through the normaliser."""
    t = normalise_text(text or "").text.strip().lower()
    if not t or len(t.split()) > _MAX_WORDS:
        return None
    # a topic-bound request ("interview ke baad voice note bhejo") belongs to the follow-up
    # settings, not to this preference
    from friday.lifestate.followups import parse_mute_command

    if parse_mute_command(t) is not None:
        return None
    if _BOTH.search(t):
        return "both"
    if _TEXT_ONLY.search(t):
        return "text"
    if _VOICE_ONLY.search(t):
        return "voice"
    if _MIRROR.search(t) and re.search(rf"\b(?:{_REPLY}|mode|voice|text)\b", t):
        return "mirror"
    return None


@dataclass(frozen=True)
class TurnState:
    voice: bool  # the last inbound message was a voice note
    script: Literal["roman", "devanagari"]
    language: str | None  # detected spoken language (STT) when voice
    at: datetime

    def dump(self) -> dict:
        return {
            "voice": self.voice,
            "script": self.script,
            "language": self.language,
            "at": self.at.isoformat(),
        }

    @classmethod
    def load(cls, raw: dict) -> TurnState:
        return cls(
            voice=bool(raw.get("voice")),
            script="devanagari" if raw.get("script") == "devanagari" else "roman",
            language=raw.get("language"),
            at=datetime.fromisoformat(raw["at"]),
        )


class VoiceState:
    """Preference + turn state over a ``Cache``."""

    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    async def mode(self, user_id: str) -> Mode:
        raw = await self.cache.get(f"vn:pref:{user_id}")
        return raw if raw in MODES else DEFAULT_MODE  # type: ignore[return-value]

    async def set_mode(self, user_id: str, mode: Mode) -> None:
        await self.cache.set(f"vn:pref:{user_id}", mode, ttl_s=PREF_TTL_S)

    async def set_turn(self, user_id: str, turn: TurnState) -> None:
        await self.cache.set(f"vn:turn:{user_id}", turn.dump(), ttl_s=TURN_TTL_S)

    async def turn(self, user_id: str) -> TurnState | None:
        raw = await self.cache.get(f"vn:turn:{user_id}")
        if not isinstance(raw, dict):
            return None
        try:
            return TurnState.load(raw)
        except (KeyError, ValueError):
            return None

    async def clear(self, user_id: str) -> None:
        for key in ("pref", "turn", "pend"):
            await self.cache.delete(f"vn:{key}:{user_id}")
