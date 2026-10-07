"""Sensitive-data guard for anything Friday speaks or keys on a call (C24).

Hard rules, enforced by the voice CallSessionRunner on EVERY SAY / HANGUP / ASK_USER
hold line / PRESS_KEYS action - in addition to the brain's own prompt rules:

1. Never speak or key an OTP, PIN, CVV, password or full card number.
2. Long digit strings (>= 6 digits) may be spoken/keyed only if they are an
   identifier the user approved for this task, the call target's own number, the
   task's reference (ticket/order id), or an amount of money.
3. Keys: short menu choices (<= 2 digits, *, #) are always fine; anything longer
   must be an approved identifier or the task reference.

A blocked action is NOT executed; the runner appends a SYSTEM turn explaining why
and asks the policy again (which should then BRIDGE_USER or ASK_USER instead).

Owner: Engineering Manager (core). Pure functions - no I/O.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from friday.core.models import CallBrief

_SECRET_WORDS = re.compile(
    r"\b(otp|o\.t\.p|one[- ]?time[- ]?(pass(word|code)?)|cvv|cvc|m?pin|pass(word|code)|"
    r"card number|card no)\b",
    re.I,
)
# a "digit run": digits possibly separated by single spaces / hyphens / dots
_DIGIT_RUN = re.compile(r"\d(?:[ \-.]?\d)*")
_MONEY_BEFORE = re.compile(r"(₹|rs\.?|inr|rupees?)\s*$", re.I)
_MONEY_AFTER = re.compile(r"^\s*(₹|rs\b|rupees?|/-|inr)", re.I)
_LONG_RUN = 6


class SafetyCheck(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


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


def check_speech(text: str, brief: CallBrief) -> SafetyCheck:
    """May Friday say ``text`` on this call?"""
    reasons: list[str] = []
    allowed = _allowed_numbers(brief)
    for m in _DIGIT_RUN.finditer(text):
        run = _digits(m.group())
        window_before = text[max(0, m.start() - 40) : m.start()]
        if _SECRET_WORDS.search(window_before) and len(run) >= 3:
            reasons.append("digits next to OTP/PIN/CVV/password wording")
            continue
        if len(run) < _LONG_RUN:
            continue
        if _MONEY_BEFORE.search(text[: m.start()]) or _MONEY_AFTER.search(text[m.end() :]):
            continue
        if not _matches_allowed(run, allowed):
            reasons.append(f"unapproved long number ending {run[-4:]}")
    return SafetyCheck(allowed=not reasons, reasons=reasons)


def check_keys(digits: str, brief: CallBrief) -> SafetyCheck:
    """May Friday press these DTMF keys?"""
    stripped = digits.replace(" ", "")
    if not re.fullmatch(r"[0-9*#w]+", stripped):
        return SafetyCheck(allowed=False, reasons=["invalid DTMF characters"])
    run = _digits(stripped)
    if len(run) <= 2:
        return SafetyCheck(allowed=True)
    if _matches_allowed(run, _allowed_numbers(brief)):
        return SafetyCheck(allowed=True)
    return SafetyCheck(
        allowed=False, reasons=["keying a number that is not an approved identifier"]
    )
