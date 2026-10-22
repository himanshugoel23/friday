# ruff: noqa: E501
"""Deterministic phrasing variety and light language mirroring from the PENDING table.

Selection depends only on (call seed, line key, how many times the key was used before), so a call
never contradicts itself and never repeats a variant back to back; no free generation.
"""

from __future__ import annotations

import hashlib
import re

from friday.human.lines import VARIANTS

_DEVA = re.compile(r"[ऀ-ॿ]")
_HINDI_ROMAN = {
    "hai", "hain", "ji", "haan", "nahi", "nahin", "kya", "aap", "main", "mujhe", "hoon", "tha", "thi",
    "karo", "kar", "karna", "kijiye", "bataiye", "batao", "chahiye", "kitna", "kitne", "kal", "aaj",
    "abhi", "theek", "achha", "accha", "bhi", "toh", "se", "ko", "ka", "ki", "ke", "mein", "par", "pe",
    "bol", "bolo", "boliye", "rahi", "raha", "kaun", "kab", "kahan", "kyun", "lagega", "lagenge", "wala",
    "dijiye", "dena", "sir", "madam",
}
_EN_WORDS = {
    "the", "is", "are", "and", "you", "your", "i", "we", "can", "could", "would", "please", "what",
    "how", "when", "where", "yes", "no", "okay", "ok", "thanks", "thank", "price", "cost", "time",
    "tomorrow", "today", "available", "need", "want", "will", "this", "that", "it", "for", "with",
}


def detect_style(text: str) -> str:
    """'hi' (Devanagari Hindi), 'en' (plain English), else 'hinglish'. Unsure -> hinglish."""
    if not text or len(text.split()) < 3:
        return "hinglish"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "hinglish"
    deva = sum(1 for c in letters if _DEVA.match(c))
    if deva / len(letters) > 0.6:
        return "hi"
    words = re.findall(r"[a-zA-Z']+", text.lower())
    hi_n = sum(w in _HINDI_ROMAN for w in words)
    en_n = sum(w in _EN_WORDS for w in words)
    if hi_n == 0 and en_n >= 2 and en_n / max(len(words), 1) >= 0.3:
        return "en"
    return "hinglish"


def _h(seed: str, key: str, n: int) -> int:
    return int(hashlib.sha256(f"{seed}|{key}|{n}".encode()).hexdigest()[:8], 16)


class VariantPicker:
    def __init__(self, seed: str, *, mirror: bool = False, enabled: bool = True) -> None:
        self.seed = seed
        self.mirror = mirror
        self.enabled = enabled
        self.style = "hinglish"
        self._used: dict[str, int] = {}
        self._last: dict[str, int] = {}

    def observe_callee(self, text: str) -> None:
        if self.mirror:
            s = detect_style(text)
            if s != "hinglish" or len(text.split()) >= 3:
                self.style = s

    def pick(self, key: str, language: str = "hinglish", **slots: str) -> str:
        """The line for ``key``. Variants off -> the first (default) wording; mirror off -> ``language``."""
        by = VARIANTS[key]
        lang = self.style if self.mirror else language
        if lang not in by:
            lang = "hinglish"
        options = by[lang]
        n = self._used.get(key, 0)
        idx = 0
        if self.enabled and len(options) > 1:
            idx = _h(self.seed, key, n) % len(options)
            if idx == self._last.get(key) and n:
                idx = (idx + 1) % len(options)
        self._used[key] = n + 1
        self._last[key] = idx
        return options[idx].format(**slots) if slots else options[idx]

    def replacement_for(self, text: str, name: str) -> str | None:
        """If ``text`` is one of the existing fixed lines we have variants for, a chosen variant."""
        for key in ("hold.waiting", "cancel.sorry"):
            for lang, opts in VARIANTS[key].items():
                for o in opts[:1]:
                    if text.strip() == o.format(name=name):
                        return self.pick(key, lang, name=name) if "{name}" in o else self.pick(key, lang)
        return None
