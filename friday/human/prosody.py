"""Per-line prosody hints: pace multiplier and pauses (as commas) by the kind of line.

No new words. The pace multiplier is relative to the voice's own rate; pauses are plain commas
(the voice pauses at commas). UNVERIFIED until the founder hears ``friday voice human-preview``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = re.compile(r"\d|₹|\b(sau|hazaar|lakh|baje|rupaye|rupees)\b", re.I)
_BAD = re.compile(r"\b(sorry|maaf|nahi ho (paega|payega|paya)|unfortunately|afsos|dikkat|problem)\b|माफ़|खेद", re.I)
_THANKS = re.compile(r"\b(dhanyavaad|dhanyawad|shukriya|thank you|thanks)\b|धन्यवाद|शुक्रिया", re.I)
_GREET = re.compile(r"^\s*(hello|hi|namaste|namaskar|नमस्ते|हैलो)\b", re.I)


@dataclass(frozen=True)
class Prosody:
    kind: str
    rate_mult: float
    lead_pause: bool  # comma before the important fact


HINTS = {
    "number": Prosody("number", 0.92, True),   # slower and clearer, a beat before the fact
    "bad_news": Prosody("bad_news", 0.94, False),  # softer, slightly slower
    "question": Prosody("question", 1.0, False),
    "thanks": Prosody("thanks", 0.97, False),
    "greeting": Prosody("greeting", 0.98, False),
    "plain": Prosody("plain", 1.0, False),
}


def classify(text: str) -> str:
    t = text or ""
    if _NUM.search(t):
        return "number"
    if _BAD.search(t):
        return "bad_news"
    if t.rstrip().endswith("?"):
        return "question"
    if _THANKS.search(t):
        return "thanks"
    if _GREET.search(t):
        return "greeting"
    return "plain"


_LEAD = re.compile(r"(?<![,.;:?!\s])\s+((?:\d|₹|rs\b|\w+ sau\b|\w+ hazaar\b|\w+ lakh\b|(?:subah|dopahar|shaam|raat)\b))", re.I)


def apply(text: str) -> tuple[str, Prosody]:
    """(text with pauses, hint). Pause = one comma before the first number phrase."""
    kind = classify(text)
    hint = HINTS[kind]
    if hint.lead_pause:
        text = _LEAD.sub(r", \1", text, count=1)
    return text, hint
