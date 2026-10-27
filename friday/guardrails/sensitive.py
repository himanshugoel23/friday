# ruff: noqa: E501
"""Sensitive codes typed in the chat (founder decision 2026-10-27, docs/HANDOFF.md).

* A LOGIN one-time code for a site Friday itself just started a login on (a *pending login* for that
  user) may be typed in the chat: 4-8 digits, single use, short TTL, handed straight to the browser
  worker through a sink (never to a model, never in a decision, never in the audit log).
* NEVER accepted, refused with a pointer to the secure page or the user's own app: bank / payment /
  transaction OTPs, UPI PIN, card number, CVV, Aadhaar OTP, and any password typed in chat.
* An unsolicited digit string is NOT an OTP: with no pending login a bare number is left alone, and a
  message that says "otp" plus digits is refused ("no login in progress").

Pure functions here; the engine (:mod:`friday.guardrails.engine`) decides what to do with the result.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from friday.guardrails.normalize import fold

LOGIN_OTP_TTL = timedelta(minutes=5)

_OTP_WORD = r"(?:otp|o\s?t\s?p|one\s*time\s*(?:pass\w*|code)|verification\s*code|code|ओटीपी|कोड)"
# the whole message is only a code, optionally framed by "otp hai" / "code is"
_CODE = r"(?P<code>\d(?:[\s\-]?\d){3,7})"
_BARE = re.compile(
    rf"^\W*(?:(?:the\s+|mera\s+|my\s+|yeh\s+|ye\s+|ye\s+hai\s+)?{_OTP_WORD}\s*(?:is|hai|h|he|है|:|=|-)?\s*)?"
    rf"{_CODE}\s*(?:hai|h|he|है|is|{_OTP_WORD})?\W*$"
)
_HAS_OTP_WORD = re.compile(rf"(?<![a-z]){_OTP_WORD}(?![a-z])")
_DIGITS = re.compile(r"\d")

_PAYMENT_CONTEXT = re.compile(
    r"\b(?:bank|banking|netbanking|net\s*banking|payment|pay|transaction|txn|upi|bhim|gpay|phonepe|"
    r"paytm|card|debit|credit|atm|neft|imps|rtgs|refund|wallet|emi|loan|mandate|autopay)\b|"
    r"बैंक|पेमेंट|यूपीआई|कार्ड"
)
_AADHAAR_CONTEXT = re.compile(r"\b(?:aadhaar|aadhar|adhar|uidai|आधार)\b|आधार")
_UPI_PIN = re.compile(
    r"\b(?:upi|atm|debit|bank|card|phonepe|gpay|paytm)\s*(?:m?pin|pin)\b|\b(?:m?pin)\b.{0,12}\d{4,6}|"
    r"पिन"
)
_CVV = re.compile(r"\b(?:cvv|cvc|cvv2|security\s*code)\b|सीवीवी")
_CARD_WORD = re.compile(r"\b(?:card|कार्ड)\b|कार्ड")
_PASSWORD = re.compile(
    r"\b(?:my\s+|mera\s+|apna\s+|the\s+|login\s+|account\s+|email\s+|gmail\s+)?(?:password|passwd|pwd|passcode|pass\s*word)\s*"
    r"(?:is|hai|h|he|:|=|-|->|are|rakha\s+hai|set\s+kiya)\s*\S+|"
    r"\b(?:password|passwd|pwd)\s+(?:\S+\s+)?(?:bhej\s+raha|bhej\s+rahi|bhej\s+diya|type\s+kar|likh\s+raha|likh\s+rahi|neeche)\b|"
    r"पासवर्ड\s*(?:है|:|=|-)\s*\S+"
)
_PASSWORD_QUESTION = re.compile(r"\b(?:forgot|bhool|reset|change|kya\s+hai|kaise|how|where|kahan|manager)\b|भूल")


@dataclass(frozen=True)
class SensitiveFinding:
    """``kind``: payment_code | aadhaar_otp | upi_pin | card_number | cvv | password |
    login_code (looks like a login OTP; usable only with a pending login) | unsolicited_code."""

    kind: str
    code: str | None = None  # only for login_code; stays inside the engine
    explicit: bool = False  # the message itself says "otp" / "code" (not just digits)

    def __repr__(self) -> str:
        return f"SensitiveFinding(kind={self.kind!r})"


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _card_number(t: str) -> bool:
    for m in re.finditer(r"(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)", t):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and (_luhn(digits) or _CARD_WORD.search(t)):
            return True
    return False


def find(text: str | None) -> SensitiveFinding | None:
    """What kind of secret, if any, the message carries. Cheap and total (never raises)."""
    t = fold(text)
    if not t or len(t) > 300:
        return None
    if re.search(r"(?<![a-z])c\s?v\s?[vc]\s?\d{3,4}(?!\d)", t):
        return SensitiveFinding("cvv")
    if _card_number(t):
        return SensitiveFinding("card_number")
    has_digits = bool(_DIGITS.search(t))
    if _CVV.search(t) and has_digits:
        return SensitiveFinding("cvv")
    if _PASSWORD.search(t) and not _PASSWORD_QUESTION.search(t):
        return SensitiveFinding("password")
    if _UPI_PIN.search(t) and has_digits:
        return SensitiveFinding("upi_pin")
    if not has_digits:
        return None
    if _AADHAAR_CONTEXT.search(t) and _HAS_OTP_WORD.search(t):
        return SensitiveFinding("aadhaar_otp")
    if _HAS_OTP_WORD.search(t) and _PAYMENT_CONTEXT.search(t):
        return SensitiveFinding("payment_code")
    m = _BARE.match(t)
    if m:
        code = re.sub(r"\D", "", m.group("code"))
        if 4 <= len(code) <= 8:
            return SensitiveFinding("login_code", code, bool(_HAS_OTP_WORD.search(t)))
    if _HAS_OTP_WORD.search(t) and re.search(r"(?<!\d)\d{4,8}(?!\d)", t):
        return SensitiveFinding("unsolicited_code")
    return None


def looks_sensitive(text: str | None) -> bool:
    """True when the stored copy of this message must be redacted (every kind but a bare number
    that is not a code, i.e. anything :func:`find` reports)."""
    return find(text) is not None


# --------------------------------------------------------------------------- pending logins
@dataclass
class PendingLogin:
    user_id: str
    site: str
    task_id: str
    expires_at: datetime


class PendingLogins:
    """Logins Friday itself started, waiting for a code. In memory (a restart forgets them, which
    only means the user is asked again). One per (user, site); a claim removes it."""

    def __init__(self, ttl: timedelta = LOGIN_OTP_TTL) -> None:
        self.ttl = ttl
        self._items: dict[str, dict[str, PendingLogin]] = {}

    def start(self, user_id: str, site: str, task_id: str, now: datetime) -> PendingLogin:
        p = PendingLogin(user_id, site.lower(), task_id, now + self.ttl)
        self._items.setdefault(user_id, {})[p.site] = p
        return p

    def claim(self, user_id: str, now: datetime) -> PendingLogin | None:
        """The newest live pending login for the user, removed (single use); None when none."""
        items = self._items.get(user_id) or {}
        for site in [s for s, p in items.items() if p.expires_at <= now]:
            del items[site]
        if not items:
            self._items.pop(user_id, None)
            return None
        newest = max(items.values(), key=lambda p: p.expires_at)
        del items[newest.site]
        if not items:
            self._items.pop(user_id, None)
        return newest

    def has_pending(self, user_id: str, now: datetime) -> bool:
        return any(p.expires_at > now for p in (self._items.get(user_id) or {}).values())

    def cancel(self, user_id: str, site: str | None = None) -> None:
        if site is None:
            self._items.pop(user_id, None)
        else:
            (self._items.get(user_id) or {}).pop(site.lower(), None)


# a sink receives (task_id, code) and hands it to the browser worker, e.g. OneTimeOtpChannel.submit
OtpSink = Callable[[str, str], None]
