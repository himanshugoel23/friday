"""When a reply is spoken, when it is also text, when it is only text. Pure, no I/O.

The voice note always speaks the SAME text the chatbot would have sent (never different words), so
this module only decides ``speak`` (make a voice note) and ``send_text`` (the text goes out too).

Rules (docs/VOICE_NOTES_AND_DEVANAGARI.md):

* mode ``text`` never speaks; ``mirror`` speaks only when the user's last message was a voice note;
  ``voice`` and ``both`` speak (inside the other rules);
* a reply longer than ``max_chars`` (about 30 seconds) is text only;
* numbers, amounts, links and buttons ALSO go as text in the same turn (a voice note cannot carry
  buttons, and a number is read back from text, not from audio);
* the "maine suna: ... sahi hai?" check (buttons ``vn:``) is read, never spoken;
* an approval (call, booking: buttons ``callap:`` ``callact:`` ``a:`` ``q:`` or the words
  approve / confirm) is never spoken at all: the user acts on the text and its buttons;
* private details (card and bank names, bill amounts, the user's own events and medicine) are not
  read aloud unless the user asked by voice in the same turn;
* mode ``both`` always sends the text too.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from friday.core.models import ReplyButton

CHARS_PER_SECOND = 20  # a calm Hindi/Hinglish voice, rough
APPROVAL_PREFIXES = ("callap:", "callact:", "a:", "q:", "n:")
# the "maine suna ... sahi hai?" prompt shows the transcript for checking: read, not spoken
CONFIRM_PREFIXES = ("vn:",)
_APPROVAL_WORDS = re.compile(
    r"\b(?:approve|approval|confirm|haan\s+bolo|kya\s+main\s+call)\b", re.I
)
_DIGIT = re.compile(r"\d|[०-९]")
_LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|in|org|net|io|co)\b|@\w", re.I)
_MONEY = re.compile(r"₹|\brs\.?\b|\brupa\w*\b|\binr\b|\blakh\b|\bhazaar\b|\bcrore\b", re.I)
_BANKS = (
    r"hdfc|sbi|icici|axis|kotak|idfc|indusind|yes\s+bank|rbl|amex|american\s+express|hsbc|pnb|"
    r"bank\s+of\s+baroda|citi|standard\s+chartered|federal"
)
_PRIVATE = re.compile(
    rf"\b(?:{_BANKS}|card|cards|credit|debit|wallet|bill|bills|bijli|emi|premium|rent|kiraya|"
    r"interview|appointment|doctor|dentist|clinic|hospital|checkup|dawai|medicine|insulin|"
    r"therapy|salary|loan|yaad\s+hai|mera\s+din|aapka\s+din|calendar)\b",
    re.I,
)


@dataclass(frozen=True)
class Decision:
    speak: bool
    send_text: bool
    reason: str  # why, for logs and tests


def needs_text_too(text: str, buttons: Sequence[ReplyButton] = ()) -> bool:
    """Numbers, amounts, links and buttons are always also sent as text."""
    return bool(
        buttons or _DIGIT.search(text) or _LINK.search(text) or _MONEY.search(text)
    )


def is_approval(text: str, buttons: Sequence[ReplyButton] = ()) -> bool:
    return any(b.id.startswith(APPROVAL_PREFIXES) for b in buttons) or bool(
        buttons and _APPROVAL_WORDS.search(text)
    )


def is_private(text: str) -> bool:
    return bool(_PRIVATE.search(text))


def estimated_seconds(text: str) -> float:
    return len(text) / CHARS_PER_SECOND


def decide(
    text: str | None,
    buttons: Sequence[ReplyButton] = (),
    *,
    mode: str,
    user_spoke: bool,
    max_chars: int = 600,
) -> Decision:
    """-> Decision. ``user_spoke``: the user's last message was a voice note (this turn)."""
    body = (text or "").strip()
    if not body:
        return Decision(False, True, "no_text")
    if mode == "text":
        return Decision(False, True, "pref_text")
    if mode == "mirror" and not user_spoke:
        return Decision(False, True, "mirror_text_turn")
    if is_approval(body, buttons):
        return Decision(False, True, "approval_is_text")
    if any(b.id.startswith(CONFIRM_PREFIXES) for b in buttons):
        return Decision(False, True, "confirmation_is_text")
    if len(body) > max_chars:
        return Decision(False, True, "too_long")
    if is_private(body) and not user_spoke:
        return Decision(False, True, "private_not_read_aloud")
    if mode == "both":
        return Decision(True, True, "pref_both")
    if needs_text_too(body, buttons):
        return Decision(True, True, "numbers_links_or_buttons_also_as_text")
    return Decision(True, False, "voice_only")
