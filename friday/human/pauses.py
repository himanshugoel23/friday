# ruff: noqa: E501
"""Right-sized silences: a short thoughtful pause (250-600 ms, varied, deterministic per call seed)
before a hard question or right after the other side gives a price. Never dead air: the pause plus
the reply gap stays under 1 s, and there is NO pause when the other side is waiting for our answer."""

from __future__ import annotations

import hashlib
import re

MIN_MS = 250
MAX_MS = 600
CEILING_MS = 1000  # pause + reply gap never goes over this

_PRICE_HEARD = re.compile(r"\d|₹|rupaye|rupees|\brs\b|sau\b|hazaar|hazar|lagega|lagenge|charge|rate|price|kharcha", re.I)
_HARD_Q = re.compile(r"(budget|discount|kam ho|thoda kam|final|best price|negotiat|kitna (final|kam)|cancel|guarantee|"
                     r"lowest|aakhri|bargain|extra charge)", re.I)
_WAITING = re.compile(r"\?\s*$|\b(kya|kaun|kab|kahan|kyun|kitna|kaise|hello|suniye|are you there|hai na)\s*\??\s*$", re.I)


def other_side_waiting(callee_text: str) -> bool:
    """They asked us something (or are calling out): answer at once."""
    return bool(callee_text and _WAITING.search(callee_text.strip()))


class PausePlanner:
    def __init__(self, seed: str) -> None:
        self.seed = seed
        self.n = 0
        self.log: list[int] = []

    def _vary(self) -> int:
        h = int(hashlib.sha256(f"{self.seed}|pause|{self.n}".encode()).hexdigest()[:8], 16)
        self.n += 1
        return MIN_MS + (h % (MAX_MS - MIN_MS + 1))

    def plan(self, *, our_line: str, callee_text: str, gap_so_far_ms: float = 0.0) -> int:
        if other_side_waiting(callee_text):
            return 0
        wanted = bool(_PRICE_HEARD.search(callee_text or "")) or bool(
            our_line.rstrip().endswith("?") and _HARD_Q.search(our_line)
        )
        if not wanted:
            return 0
        ms = self._vary()
        room = int(CEILING_MS - gap_so_far_ms)
        ms = min(ms, room)
        if ms < MIN_MS:
            return 0
        self.log.append(ms)
        return ms
