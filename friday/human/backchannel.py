"""Backchannels ("haan ji", "hmm", "achha") during the other side's LONG answers.

Rules (tests enforce them): only when Friday is silent AND the other person has been speaking for
at least ``MIN_SPEECH_S`` seconds AND they are in a short natural pause (250-450 ms), once per
pause; never over their speech; at least ``MIN_GAP_S`` between two; at most 2 per answer and 6 per
call; never the same one twice in a row; off for elders / officials. They are real words in the
same approved voice, not breaths, laughs or typing sounds, and never pretend to be a human.
"""

from __future__ import annotations

import hashlib

from friday.human.lines import VARIANTS

MIN_SPEECH_S = 4.0
MIN_GAP_S = 6.0
PAUSE_MIN_MS = 250
PAUSE_MAX_MS = 450
MAX_PER_ANSWER = 2
MAX_PER_CALL = 6


class BackchannelEngine:
    def __init__(self, seed: str, language: str = "hinglish", *, enabled: bool = True,
                 allowed: bool = True) -> None:
        self.seed = seed
        self.language = language if language in VARIANTS["bc.short"] else "hinglish"
        self.enabled = enabled and allowed
        self.count = 0
        self.last_t: float | None = None
        self.last_idx = -1
        self._per_answer = 0
        self._fired_this_pause = False
        self._answer_open = False

    def set_language(self, language: str) -> None:
        if language in VARIANTS["bc.short"]:
            self.language = language

    def consider(self, *, now_s: float, speech_s: float, silence_ms: int,
                 friday_speaking: bool = False, speech_active: bool = False) -> str | None:
        """The backchannel text to play now, or None. Call once per 20 ms frame (cheap)."""
        if speech_active or silence_ms < 20:
            self._fired_this_pause = False  # speech resumed: a new pause may get one
        if speech_s <= 0:
            self._per_answer = 0
        if not self.enabled or friday_speaking or speech_active:
            return None
        if self._fired_this_pause or speech_s < MIN_SPEECH_S:
            return None
        if not (PAUSE_MIN_MS <= silence_ms <= PAUSE_MAX_MS):
            return None
        if self._per_answer >= MAX_PER_ANSWER or self.count >= MAX_PER_CALL:
            return None
        if self.last_t is not None and now_s - self.last_t < MIN_GAP_S:
            return None
        opts = VARIANTS["bc.short"][self.language]
        h = int(hashlib.sha256(f"{self.seed}|bc|{self.count}".encode()).hexdigest()[:8], 16)
        idx = h % len(opts)
        if idx == self.last_idx:
            idx = (idx + 1) % len(opts)
        self.count += 1
        self._per_answer += 1
        self._fired_this_pause = True
        self.last_t = now_s
        self.last_idx = idx
        return opts[idx]

    def new_answer(self) -> None:
        self._per_answer = 0
