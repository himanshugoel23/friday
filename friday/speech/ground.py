"""Grounding: the rules the model's answer must obey, checked in CODE.

The model may clean and fix, but it may not INVENT. ``violations`` returns a list of reasons; an empty list
means the corrected text can be used. Protected classes: numbers (amounts, times, quantities), day and
part-of-day words, names, and the script/language of the user.
"""

from __future__ import annotations

import contextlib
import re
from difflib import SequenceMatcher

from friday.playbooks.slots import words_to_numbers
from friday.speech.rules import DAY_WORDS, PERIOD_WORDS

_TOKEN = re.compile(r"[\wऀ-ॿ']+", re.U)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_NUM = re.compile(r"\d[\d,]*")
SIM_MIN = 0.55  # a memory name may replace a heard word only if they sound/spell alike


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def numbers_in(text: str) -> set[int]:
    """Every number said: digit runs and Hindi/Hinglish number words ("paanch sau" -> 500)."""
    out: set[int] = set()
    for m in _NUM.finditer(text or ""):
        digits = m.group().replace(",", "")
        if digits.isdigit():
            out.add(int(digits))
    # a number parser problem must not break grounding
    with contextlib.suppress(Exception):
        out |= {v for v, _s, _e in words_to_numbers(text or "")}
    return out


def _proper(original_case_tokens: list[str], i: int) -> bool:
    t = original_case_tokens[i]
    return len(t) > 1 and t[0].isupper() and t.lower() != "i"


def violations(original: str, corrected: str, vocab: set[str] | frozenset[str] = frozenset()) -> list[str]:
    o_tokens, c_tokens = tokens(original), tokens(corrected)
    if not c_tokens:
        return ["empty"]
    o_set = set(o_tokens)
    out: list[str] = []

    if len(c_tokens) > len(o_tokens) * 1.6 + 2:
        out.append("too_long")
    if len(o_tokens) >= 8 and len(c_tokens) < len(o_tokens) * 0.25:
        out.append("too_short")

    extra_numbers = numbers_in(corrected) - numbers_in(original)
    if extra_numbers:
        out.append(f"invented_number:{sorted(extra_numbers)[0]}")

    for words, label in ((DAY_WORDS, "day"), (PERIOD_WORDS, "period")):
        added = (set(c_tokens) & words) - o_set
        if added:
            out.append(f"invented_{label}:{sorted(added)[0]}")

    if _DEVANAGARI.search(corrected) and not _DEVANAGARI.search(original):
        out.append("script_changed")

    removed = [t for t in o_tokens if t not in set(c_tokens)]
    case_tokens = _TOKEN.findall(corrected)
    for i, t in enumerate(c_tokens):
        if t in o_set:
            continue
        if t in vocab:
            if not any(SequenceMatcher(None, t, r).ratio() >= SIM_MIN for r in removed):
                out.append(f"ungrounded_name:{t}")
        elif i < len(case_tokens) and _proper(case_tokens, i):
            out.append(f"invented_name:{t}")

    shared = sum(1 for t in c_tokens if t in o_set)
    if len(c_tokens) >= 4 and shared / len(c_tokens) < 0.5:
        out.append("rewritten")
    return out
