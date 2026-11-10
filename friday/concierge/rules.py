# ruff: noqa: E501
"""The concierge's hard rules, enforced in code (docs/ROBIN_CONCIERGE_DESK.md section 3).

* never pays: a request carries NO payment fields; a field with a payment name is refused; the UPI link is generated for the USER to tap
* no OTP / password / PIN / card / CVV / Aadhaar / bank login is accepted, in a field or in free text
* no bank access: nothing here logs in anywhere; the categories have no bank-account action
* a spend above the ceiling needs the child's yes
* only the parent or a child admin may ask
* distress and safety text is not an errand: it goes to the AI emergency path (and is never stored as a request)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from friday.care.detect import is_distress


class RuleViolation(ValueError):
    """A hard rule refused the input. ``code`` is a fixed word; the message never contains the offending value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# fields a request may carry. Anything else is refused (extra=forbid), which also blocks every payment/credential field by construction.
ALLOWED_FIELDS = frozenset({"category", "summary", "estimated_paise", "child_approved"})
FORBIDDEN_FIELD_HINTS = (
    "pay", "card", "cvv", "pin", "otp", "password", "passwd", "pwd", "secret", "token", "account", "ifsc", "upi_pin", "netbanking",
    "bank", "aadhaar", "aadhar", "pan", "credential", "wallet", "amount_paid", "vpa_pin",
)

_OTP = re.compile(r"\b(?:otp|one[\s-]?time|verification\s+code|code)\b[^\d]{0,25}\d{4,8}\b|\b\d{4,8}\b[^\d]{0,12}\b(?:is\s+(?:my|the)\s+)?otp\b", re.I)
_SECRET_WORDS = re.compile(
    r"\b(?:password|passwd|pwd|passcode|upi\s*pin|atm\s*pin|mpin|m-pin|cvv|cvc|net\s*banking|netbanking|login\s+id|card\s+number|secret\s+answer)\b"
    r"|\bpin\b[^\d]{0,12}\d{4,6}\b|पासवर्ड|पिन\s*\d",
    re.I,
)
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
        alt = not alt
    return total % 10 == 0


def secret_in(text: str) -> str | None:
    """A fixed code if the text holds (or asks to hold) an OTP, password, PIN, card or Aadhaar number; else None."""
    t = text or ""
    if _OTP.search(t):
        return "otp_refused"
    if _SECRET_WORDS.search(t):
        return "credential_refused"
    for m in _CARD_CANDIDATE.finditer(t):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "card_refused"
    if _AADHAAR.search(t):
        return "aadhaar_refused"
    return None


_SAFETY = re.compile(
    r"\b(?:sos|bachao|bachaao|help\s+me|chest\s+pain|heart\s+attack|can'?t\s+breathe|cannot\s+breathe|fell\s+down|has\s+fallen|have\s+fallen|gir\s+(?:gay(?:a|e|i|ee)|pad(?:a|e|i))|behosh|unconscious|bleeding|ambulance|"
    r"threat(?:en(?:ing|ed)?)?|dhamki|kidnap|someone\s+is\s+(?:in\s+the\s+house|following)|scam\s+(?:in\s+progress|right\s+now)|just\s+sent\s+money\s+to|hurt\s+myself|want\s+to\s+die|mar\s+jaana)\b"
    r"|बचाओ|एम्बुलेंस|सीने\s+में\s+दर्द|धमकी",
    re.I,
)


def is_safety_text(text: str) -> bool:
    """Distress or emergency words. Such text is never an errand: it is rerouted to the AI emergency path."""
    return bool(text) and (bool(_SAFETY.search(text)) or is_distress(text))


def check_fields(payload: Mapping[str, Any]) -> None:
    """Refuse any field that is not on the allow-list; name the fields that look like payment or credentials with a fixed code."""
    for key in payload:
        k = str(key).lower()
        if k in ALLOWED_FIELDS:
            continue
        if any(h in k for h in FORBIDDEN_FIELD_HINTS):
            raise RuleViolation("payment_or_credential_field_refused")
        raise RuleViolation("unknown_field")


def spend_needs_child(estimated_paise: int | None, ceiling_paise: int) -> bool:
    return estimated_paise is not None and estimated_paise > ceiling_paise


def make_upi_link(payee_vpa: str, payee_name: str, amount_paise: int, note: str = "") -> str:
    """A UPI deep link for the USER to tap and pay in their own app. Pure string building; nothing is sent and no money moves.
    The payee is the biller or shop named in the request, never a staff account."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,64}@[A-Za-z0-9]{2,32}", payee_vpa or ""):
        raise RuleViolation("bad_payee")
    if not (0 < int(amount_paise) <= 10_000_000):
        raise RuleViolation("bad_amount")
    params = {"pa": payee_vpa, "pn": payee_name[:40], "am": f"{int(amount_paise) // 100}.{int(amount_paise) % 100:02d}", "cu": "INR", "tn": note[:40]}
    return "upi://pay?" + urlencode(params, quote_via=quote)
