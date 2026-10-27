"""Item 12: OTP, date of birth, address and card details are never asked for in chat.

``ask_for(field, link, lang)`` is the ONLY way Friday words a request for one of these fields: it
always points to a secure-page link. ``scan(text)`` spots such a value pasted into the chat so the
reply can tell the user not to, and the raw text is never stored or echoed.
"""

from __future__ import annotations

import re

from friday.chatbot.parity import copy

FIELDS = ("otp", "dob", "address", "card")

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_OTP = re.compile(r"\b(?:otp|code|pin)\b\D{0,12}(\d{4,8})\b|\b(\d{4,8})\b\D{0,12}\b(?:is\s+(?:my|the)\s+)?otp\b", re.I)
_DOB = re.compile(
    r"\b(?:dob|date\s+of\s+birth|janm\s*tithi|born\s+on)\b.{0,12}\d|\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}\b", re.I
)
_ADDR = re.compile(r"\b(?:my\s+address\s+is|mera\s+(?:pata|address)\s+(?:hai)?|flat\s+no|house\s+no)\b", re.I)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def scan(text: str) -> str | None:
    """The sensitive field a message seems to contain ('card', 'otp', 'dob', 'address') or None."""
    t = text or ""
    for m in _CARD.finditer(t):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "card"
    if _OTP.search(t):
        return "otp"
    if _DOB.search(t):
        return "dob"
    if _ADDR.search(t):
        return "address"
    return None


def ask_for(field: str, link: str, lang: str = "hinglish") -> str:
    """The only wording for requesting a sensitive field: always a secure-page link."""
    if field not in FIELDS:
        raise ValueError(f"unknown sensitive field {field!r}")
    if not link.startswith("https://"):
        raise ValueError("the secure page link must be https")
    return copy.line("secure_page", lang, what=copy.line(f"field_{field}", lang), link=link)


def pasted_reply(field: str, link: str, lang: str = "hinglish") -> str:
    return copy.line("secure_pasted", lang, what=copy.line(f"field_{field}", lang), link=link)


_ASKS = re.compile(
    r"\b(?:send|share|enter|give|type|bhej\w*|bata\w*|de\s+do|batao|daalo)\b.{0,30}\b(?:otp|dob|date\s+of\s+birth|"
    r"address|card\s+(?:number|details)|cvv)\b",
    re.I,
)


def violates(outgoing: str) -> bool:
    """True if a draft reply asks for a sensitive field in chat (no https link in the same text)."""
    return bool(_ASKS.search(outgoing or "")) and "https://" not in (outgoing or "")
