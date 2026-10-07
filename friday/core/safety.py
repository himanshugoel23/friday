"""Sensitive-data guard for anything Friday speaks or keys on a call (C24).

Hard rules, enforced by the voice CallSessionRunner on EVERY SAY / HANGUP / ASK_USER
hold line / PRESS_KEYS action - in addition to the brain's own prompt rules:

1. Never speak or key an OTP, PIN, CVV, password or full card number - in digits,
   spoken number words (English / Hinglish / Devanagari), comma-separated digits, or
   with the keyword before OR after the digits (anywhere in the same sentence).
2. Long digit strings (>= 6 digits) may be spoken/keyed only if they are an
   identifier the user approved for this task, the call target's own number, the
   task's reference (ticket/order id), or an amount of money (<= 9 digits).
   A 13-19 digit run passing the Luhn check is always blocked (card number).
3. Keys: short menu choices (<= 2 digits, *, #) are fine; anything longer - including
   digits keyed in chunks within one IVR prompt (``check_key_sequence`` / ``KeyBuffer``)
   - must be an approved identifier or the task reference.
4. ``check_commit`` gates confirming a booking: approved terms, an approving answer,
   or an explicit delegation whose price / time window / scope covers the decision.

A blocked action is NOT executed; the runner appends a SYSTEM turn explaining why
and asks the policy again (which should then BRIDGE_USER or ASK_USER instead).

Owner: Engineering Manager (core). Pure functions - no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from friday.core.models import CallBrief, UserAnswer

_DEV = "ऀ-ॿ"  # Devanagari block
_WB_L = rf"(?<![\w{_DEV}])"
_WB_R = rf"(?![\w{_DEV}])"

# SECURITY-1: English + Hinglish + Devanagari secret wording.
_SECRET_WORDS = re.compile(
    _WB_L
    + r"(o[-. ]?t[-. ]?p|one[- ]?time[- ]?(pass(word|code)?)|cvv|cvc|m?pin|"
    r"pass(word|code)|card number|card no|"
    r"(verification|security|secret|auth(entication)?|otp|login|access)[- ]?code|"
    r"ओटीपी|ओ\.?टी\.?पी|पिन|पासवर्ड|पासकोड|सीवीवी|गुप्त\s?कोड)"
    + _WB_R,
    re.I,
)
# Postal "PIN code 560038" is an address, not a secret.
_POSTAL = re.compile(r"\bpin\s*-?\s*code\b(?=\W{0,5}[1-9]\d{2}\s?\d{3}(?!\d))", re.I)

# a "digit run": digits possibly separated by single spaces / hyphens / dots
_DIGIT_RUN = re.compile(r"\d(?:[ \-.]?\d)*")
# single digits separated by , / | ("4, 8, 2, 9")
_SEPARATED_SINGLES = re.compile(r"(?<!\d)\d(?:\s*[,/|]\s*\d(?!\d))+")
_MONEY_BEFORE = re.compile(r"(₹|rs\.?|inr|rupees?)\s*$", re.I)
_MONEY_AFTER = re.compile(r"^\s*(₹|rs\b|rupees?|/-|inr)", re.I)
_SENTENCE = re.compile(r"[!?।\n;]+|\.(?=\s+[A-Z])")
_LONG_RUN = 6
_MAX_MONEY_DIGITS = 9  # SECURITY-2: <= ₹99 crore

_NUMBER_WORDS: dict[str, str] = {
    # English
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Hinglish (romanised Hindi)
    "shunya": "0", "shoonya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4",
    "chaar": "4", "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "chah": "6",
    "saat": "7", "aath": "8", "nau": "9",
    # Devanagari
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "छः": "6", "छे": "6", "सात": "7", "आठ": "8", "नौ": "9",
}  # fmt: skip
_WORD_ALT = "|".join(sorted((re.escape(w) for w in _NUMBER_WORDS), key=len, reverse=True))
_REPEAT = re.compile(_WB_L + rf"(double|triple)\s+({_WORD_ALT}|\d)" + _WB_R, re.I)
_WORD = re.compile(_WB_L + rf"({_WORD_ALT})" + _WB_R, re.I)


class SafetyCheck(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ normalisation


def _ascii_digits(text: str) -> str:
    """Devanagari / other Unicode decimal digits -> ASCII."""
    return "".join(
        str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii() else ch
        for ch in text
    )


def _word_digit(word: str) -> str:
    return _NUMBER_WORDS.get(word.lower(), _NUMBER_WORDS.get(word, word))


def normalize_spoken_digits(text: str) -> str:
    """'four eight double two' -> '4 8 22'; 'char, aath' -> '48'; '४८' -> '48'."""
    text = _ascii_digits(text)
    text = _REPEAT.sub(
        lambda m: _word_digit(m.group(2)) * (2 if m.group(1).lower() == "double" else 3), text
    )
    text = _WORD.sub(lambda m: _word_digit(m.group(1)), text)
    return _SEPARATED_SINGLES.sub(lambda m: _digits(m.group()), text)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", _ascii_digits(s))


def luhn_valid(number: str) -> bool:
    digits = _digits(number)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _allowed_numbers(brief: CallBrief) -> set[str]:
    allowed = {_digits(i.value) for i in brief.approved_identifiers}
    allowed.add(_digits(brief.target.phone))
    if brief.reference:
        allowed.add(_digits(brief.reference))
    return {a for a in allowed if a}


def _matches_allowed(run: str, allowed: set[str]) -> bool:
    return any(run == a or (len(run) >= _LONG_RUN and run in a) for a in allowed) or any(
        a.endswith(run) and len(run) >= 10
        for a in allowed  # phone without country code
    )


# ------------------------------------------------------------------ speech


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text) if s and s.strip()]


def check_speech(text: str, brief: CallBrief) -> SafetyCheck:
    """May Friday say ``text`` on this call?"""
    reasons: list[str] = []
    allowed = _allowed_numbers(brief)
    for sentence in _sentences(_ascii_digits(text)):
        scrubbed = _POSTAL.sub("postcode", sentence)
        secret = bool(_SECRET_WORDS.search(scrubbed))
        norm = normalize_spoken_digits(scrubbed)
        for m in _DIGIT_RUN.finditer(norm):
            run = _digits(m.group())
            if secret and len(run) >= 3:
                reasons.append("digits in a sentence with OTP/PIN/CVV/password wording")
                continue
            if luhn_valid(run):
                reasons.append("looks like a card number")
                continue
            if len(run) < _LONG_RUN:
                continue
            money = _MONEY_BEFORE.search(norm[: m.start()]) or _MONEY_AFTER.search(
                norm[m.end() :]
            )
            if money and len(run) <= _MAX_MONEY_DIGITS:
                continue
            if not _matches_allowed(run, allowed):
                reasons.append(f"unapproved long number ending {run[-4:]}")
    return SafetyCheck(allowed=not reasons, reasons=reasons)


# ------------------------------------------------------------------ DTMF


def check_keys(digits: str, brief: CallBrief) -> SafetyCheck:
    """May Friday press these DTMF keys (one action, stateless)?"""
    stripped = digits.replace(" ", "")
    if not re.fullmatch(r"[0-9*#w]+", stripped):
        return SafetyCheck(allowed=False, reasons=["invalid DTMF characters"])
    run = _digits(stripped)
    if len(run) <= 2:
        return SafetyCheck(allowed=True)
    if luhn_valid(run):
        return SafetyCheck(allowed=False, reasons=["looks like a card number"])
    if _matches_allowed(run, _allowed_numbers(brief)):
        return SafetyCheck(allowed=True)
    return SafetyCheck(
        allowed=False, reasons=["keying a number that is not an approved identifier"]
    )


def check_key_sequence(history: Iterable[str], brief: CallBrief) -> SafetyCheck:
    """SECURITY-24: all keys pressed since the last IVR prompt, concatenated. Blocks a
    PIN keyed in small chunks ("48" + "21"). The runner resets the history on every
    new IVR prompt (``KeyBuffer.reset``)."""
    keys = list(history)
    for k in keys:
        single = check_keys(k, brief)
        if not single.allowed:
            return single
    run = _digits("".join(keys))
    if len(run) <= 2 or _matches_allowed(run, _allowed_numbers(brief)):
        return SafetyCheck(allowed=True)
    return SafetyCheck(
        allowed=False,
        reasons=["keys pressed in this prompt add up to an unapproved number"],
    )


class KeyBuffer:
    """Per-call helper for the runner: ``check(keys)`` before pressing, ``reset()`` on
    each new IVR prompt. Only allowed keys are remembered."""

    def __init__(self, brief: CallBrief) -> None:
        self.brief = brief
        self.pressed: list[str] = []

    def reset(self) -> None:
        self.pressed.clear()

    def check(self, keys: str) -> SafetyCheck:
        result = check_key_sequence([*self.pressed, keys], self.brief)
        if result.allowed:
            self.pressed.append(keys)
        return result


# ------------------------------------------------------------------ commitments


def check_commit(
    brief: CallBrief,
    answers: Sequence[UserAnswer],
    *,
    amount_inr: int | None = None,
    slot_at: datetime | None = None,
    decision: str | None = None,
) -> SafetyCheck:
    """SECURITY-27: may Friday confirm THIS booking on THIS call?

    Allowed with ``approved_terms`` (confirmation call-back) or an approving answer.
    Under a delegation only: price within ``max_price_inr`` (amount must be known when
    a ceiling is set), ``slot_at`` inside the window when one is set, and ``decision``
    inside ``scope`` when a scope is set.
    """
    if brief.approved_terms or any(a.approves for a in answers):
        return SafetyCheck(allowed=True)
    d = brief.delegation
    if not d.granted:
        return SafetyCheck(allowed=False, reasons=["no user approval and no delegation"])
    reasons: list[str] = []
    if d.max_price_inr is not None and not d.allows_price(amount_inr):
        reasons.append("price outside the delegated ceiling (or unknown)")
    if (d.window_start is not None or d.window_end is not None) and not d.allows_time(slot_at):
        reasons.append("slot outside the delegated time window (or unknown)")
    if d.scope and decision is not None and decision not in d.scope:
        reasons.append(f"decision '{decision}' not in the delegated scope")
    return SafetyCheck(allowed=not reasons, reasons=reasons)
