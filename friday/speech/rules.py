"""The deterministic floor: what the Speech Understander still does with NO model.

Used when the model is slow, fails, or returns something the grounding check rejects. Only changes that are
safe by construction: filler sounds, stutters, and the plainest self-corrections (a day, a part of the day or a
digit number replaced by another of the same kind: "kal nahi parso" -> "parso", "5 nahi 6 baje" -> "6 baje").
"""

from __future__ import annotations

import re

from friday.speech.schema import Repair

FILLER_SOUNDS = frozenset(
    {"um", "umm", "ummm", "uh", "uhh", "uhm", "er", "erm", "hmm", "hmmm", "hm", "mm", "mmm", "ah", "ahh", "aah"}
)
CORRECTION_MARKERS = frozenset({"nahi", "nahin", "nai", "no", "sorry", "matlab", "wait", "ruko"})
DAY_WORDS = frozenset(
    {
        "aaj", "kal", "parso", "narso", "today", "tomorrow", "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday", "somvar", "mangalvar", "budhvar", "guruvar", "shukravar",
        "shanivar", "ravivar",
    }
)
PERIOD_WORDS = frozenset(
    {"subah", "savere", "dopahar", "dupahar", "shaam", "sham", "raat", "morning", "afternoon", "evening", "night"}
)
_PUNCT = ".,!?;:-…\"'()"
_DIGITS = re.compile(r"^\d{1,4}$")


def bare(token: str) -> str:
    return token.strip(_PUNCT).lower()


def _kind(token: str) -> str | None:
    b = bare(token)
    if b in DAY_WORDS:
        return "day"
    if b in PERIOD_WORDS:
        return "period"
    if _DIGITS.match(b):
        return "num"
    return None


def clean_basic(text: str) -> tuple[str, list[Repair]]:
    """``(cleaned_text, repairs)``; the original comes back unchanged if the result would be empty."""
    toks = text.split()
    repairs: list[Repair] = []

    kept: list[str] = []
    for t in toks:
        if bare(t) in FILLER_SOUNDS:
            repairs.append(Repair(old=t, new="", kind="filler"))
        else:
            kept.append(t)
    toks = kept

    i = 1
    while i < len(toks) - 1:
        if bare(toks[i]) in CORRECTION_MARKERS:
            lk, rk = _kind(toks[i - 1]), _kind(toks[i + 1])
            if lk and lk == rk and bare(toks[i - 1]) != bare(toks[i + 1]):
                repairs.append(Repair(old=f"{toks[i - 1]} {toks[i]}", new="", kind="self_correction"))
                del toks[i - 1 : i + 1]
                i = max(1, i - 1)
                continue
        i += 1

    out: list[str] = []
    for t in toks:
        if out and len(bare(t)) >= 2 and bare(t) == bare(out[-1]):
            repairs.append(Repair(old=t, new="", kind="filler"))
            continue
        out.append(t)

    cleaned = " ".join(out).strip()
    if not cleaned:
        return text, []
    return cleaned, repairs
