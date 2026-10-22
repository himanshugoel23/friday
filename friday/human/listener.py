"""Match the listener: estimate how the other side talks and adapt our pace and line length.

Signals from the transcript and its audio duration: speech rate (words per second), answer length,
hesitation ("um", "matlab", "..."), and repeat requests ("kya?", "sorry?", "phir se"). Slow, hesitant
or repeating listeners get a slower pace (floor 0.8) and shorter, clearer lines; quick, curt shop
owners get a slightly quicker pace (cap 1.0). The approved base pace is 0.9; we never leave 0.8-1.0.
"""

from __future__ import annotations

import re

BASE_PACE = 0.9
MIN_PACE = 0.8
MAX_PACE = 1.0

_REPEAT = re.compile(
    r"^\s*(kya|kya\?|sorry\??|what\??|huh\??|pardon|haan\?|hm+\?|phir se|dobara|ek baar phir|"
    r"i beg your pardon|come again|kya kaha|kya bola|क्या\??)\s*[?.!]*\s*$|"
    r"\b(phir se (bolo|boliye|batao)|dobara (bolo|boliye|batao)|repeat (that|please)|say that again|"
    r"awaaz nahi aa rahi|samajh nahi aaya)\b",
    re.I,
)
_HESITATE = re.compile(r"\b(um+|uh+|hmm+|matlab|woh|wo|that is|you know|ek minute|ruko)\b|\.\.\.|…", re.I)
_PROTECT = re.compile(r"\b(ai|assistant|stop|do not call|dnd)\b|AI|असिस्टेंट", re.I)
_SENT = re.compile(r"(?<=[.?!।])\s+")
_KEEP = re.compile(r"\d|\?|₹|rupaye|baje|kal|aaj|parso")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


def shorten(text: str, max_words: int) -> str:
    """Drop trailing optional sentences (no question, no number/time) until it fits. Never touches
    a line that carries the AI disclosure or a stop request. The first sentence is always kept."""
    if max_words <= 0 or len(text.split()) <= max_words or _PROTECT.search(text):
        return text
    parts = split_sentences(text)
    if len(parts) < 2:
        return text
    keep = [True] * len(parts)
    total = len(text.split())
    for i in range(len(parts) - 1, 0, -1):  # from the end, never the first
        if total <= max_words:
            break
        if not _KEEP.search(parts[i]):
            keep[i] = False
            total -= len(parts[i].split())
    return " ".join(p for p, k in zip(parts, keep, strict=True) if k)


def is_repeat_request(text: str) -> bool:
    return bool(text and _REPEAT.search(text))


class ListenerModel:
    def __init__(self) -> None:
        self.rates: list[float] = []
        self.lengths: list[int] = []
        self.hesitations = 0
        self.repeats = 0
        self.turns = 0

    def observe(self, text: str, duration_s: float | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.turns += 1
        words = len(text.split())
        self.lengths.append(words)
        if duration_s and duration_s >= 1.0 and words >= 3:
            self.rates.append(words / duration_s)
        self.hesitations += len(_HESITATE.findall(text))
        if is_repeat_request(text):
            self.repeats += 1

    @property
    def rate(self) -> float | None:
        r = self.rates[-4:]
        return sum(r) / len(r) if r else None

    @property
    def avg_len(self) -> float:
        n = self.lengths[-4:]
        return sum(n) / len(n) if n else 0.0

    def style(self) -> str:
        """'slow' | 'busy' | 'normal'."""
        if self.turns == 0:
            return "normal"
        slow = (
            self.repeats >= 1
            or self.hesitations >= 2
            or (self.rate is not None and self.rate < 1.6)
        )
        if slow:
            return "slow"
        if self.turns >= 2 and self.avg_len <= 3 and self.rate is not None and self.rate > 3.2:
            return "busy"
        if self.turns >= 2 and self.avg_len <= 2:
            return "busy"
        return "normal"

    def pace(self) -> float:
        s = self.style()
        p = BASE_PACE
        if s == "slow":
            p = BASE_PACE - 0.05 - 0.025 * min(self.repeats + self.hesitations // 2, 2)
        elif s == "busy":
            p = BASE_PACE + 0.08
        return max(MIN_PACE, min(MAX_PACE, round(p, 3)))

    def max_words(self) -> int:
        """Longest line we will speak (0 = no limit)."""
        return {"slow": 16, "busy": 12}.get(self.style(), 0)

    def adapt(self, text: str) -> str:
        return shorten(text, self.max_words())
