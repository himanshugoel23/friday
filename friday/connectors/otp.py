"""One-time channel for the LOGIN OTP: secure page (or WhatsApp chat) -> this object -> the worker.

The code is held in memory only, per task, single use, short TTL. ``take`` returns it once and
wipes it. It is never logged and never part of repr/str, never sent to a model. (Payment OTPs are
not handled at all: payment ends in a QR / UPI link the user pays in their own app.)

Login OTP typed in the WhatsApp chat (founder decision 2026-10-27)
------------------------------------------------------------------
A LOGIN code for a site the user asked Friday to use may be typed in chat, but ONLY while Friday
itself has just started a login for that user on that site (``PendingLoginRegistry``). It goes
straight into ``OneTimeOtpChannel`` (never the LLM, never a log, single use, short TTL) and the
stored chat text is redacted at once (the copy inside WhatsApp / Meta cannot be deleted by us).
Bank / payment / UPI PIN / card / CVV / Aadhaar codes and passwords are NEVER accepted:
``classify_chat_secret`` names them so the caller can refuse and point to the secure page or the
user's own app. Unsolicited 4-8 digit numbers are NOT codes.

``classify_chat_secret`` / ``chat_secret_kind`` are the small pure functions the guardrails module
may call as well (no state, no I/O, no logging).
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field


class OneTimeOtpChannel:
    __slots__ = ("_clock", "_ttl", "_codes")

    def __init__(self, ttl_seconds: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._codes: dict[str, tuple[str, float]] = {}

    def submit(self, task_id: str, code: str) -> None:
        code = code.strip().replace(" ", "")
        if not (code.isdigit() and 4 <= len(code) <= 8):
            raise ValueError("a login code is 4 to 8 digits")  # never echo the value
        self._codes[task_id] = (code, self._clock() + self._ttl)

    def take(self, task_id: str) -> str | None:
        """The code once, then it is gone. None when absent, expired or already taken."""
        entry = self._codes.pop(task_id, None)
        if entry is None:
            return None
        code, expires = entry
        return code if self._clock() < expires else None

    def has_pending(self, task_id: str) -> bool:
        entry = self._codes.get(task_id)
        if entry is not None and self._clock() >= entry[1]:
            self._codes.pop(task_id, None)
            return False
        return entry is not None

    def wipe(self, task_id: str) -> None:
        self._codes.pop(task_id, None)

    def __repr__(self) -> str:
        return f"OneTimeOtpChannel(pending={len(self._codes)})"

    __str__ = __repr__


# ---------------------------------------------------------------- login OTP typed in chat
CHAT_OTP_TTL_SECONDS = 300.0
MAX_CODE_MESSAGE_CHARS = 80

LOGIN_OTP = "login_otp"
REFUSE_PAYMENT_OTP = "refuse_payment_otp"
REFUSE_UPI_PIN = "refuse_upi_pin"
REFUSE_CARD = "refuse_card"
REFUSE_AADHAAR = "refuse_aadhaar"
REFUSE_PASSWORD = "refuse_password"
NONE = "none"
REFUSALS = frozenset({REFUSE_PAYMENT_OTP, REFUSE_UPI_PIN, REFUSE_CARD, REFUSE_AADHAAR,
                      REFUSE_PASSWORD})

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"), None)
_DIGIT_WORDS = {
    "zero": "0", "shunya": "0", "शून्य": "0", "one": "1", "ek": "1", "एक": "1", "two": "2",
    "do": "2", "दो": "2", "three": "3", "teen": "3", "तीन": "3", "four": "4", "char": "4",
    "chaar": "4", "चार": "4", "five": "5", "paanch": "5", "panch": "5", "पांच": "5", "पाँच": "5",
    "six": "6", "chhe": "6", "chhah": "6", "che": "6", "छह": "6", "छः": "6", "seven": "7",
    "saat": "7", "सात": "7", "eight": "8", "aath": "8", "आठ": "8", "nine": "9", "nau": "9",
    "नौ": "9",
}
_FILLERS = frozenset({
    "otp", "code", "codes", "hai", "hain", "he", "h", "is", "it", "its", "the", "my", "mera",
    "meri", "mere", "ye", "yeh", "yah", "ka", "ki", "ke", "ko", "login", "verification", "verify",
    "sms", "this", "number", "no", "digit", "digits", "karo", "kar", "dalo", "daalo", "dal", "daal",
    "enter", "please", "pls", "plz", "bhai", "ji", "sir", "madam", "here", "got", "received",
    "aaya", "aya", "wala", "ओटीपी", "कोड", "है", "हैं", "मेरा", "मेरी", "यह", "ये", "का", "की",
    "के", "लॉगिन", "नंबर",
})
_SPLIT = re.compile(r"[\s,;:.\-_/|()\[\]{}'\"!?=+*#<>~`]+")
_BOUNDARY = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")
_BANKISH = re.compile(
    r"(bank|payment|\bpay\b|transaction|\btxn\b|\bupi\b|card|debit|credit|netbanking|net banking|"
    r"paytm|phonepe|gpay|google pay|bhim|razorpay|wallet|\bneft\b|\brtgs\b|\bimps\b|\bloan\b|"
    r"\bemi\b|बैंक|पेमेंट|कार्ड|यूपीआई)")
_OTPISH = re.compile(r"(\botp\b|o\.t\.p|\bcode\b|verification|\bpin\b|ओटीपी|कोड|पिन)")
_AADHAAR = re.compile(r"(aadh?a+r|aadhar|adhaar|uidai|आधार)")
_UPI_PIN = re.compile(
    r"(upi\s*-?\s*pin|\bm-?pin\b|atm\s*pin|card\s*pin|debit\s*pin|bank\s*pin|"
    r"netbanking\s*(?:pin|password)|यूपीआई\s*पिन|एटीएम\s*पिन)")
_CVV = re.compile(r"(\bcvv2?\b|\bcvc2?\b|security\s*code|card\s*verification|सीवीवी)")
_CARD_WORD = re.compile(r"(card\s*(?:no|number|num|nbr)\b|कार्ड\s*नंबर)")
_PASSWORD = re.compile(r"(pass\s*word|passwd|passwrd|\bpwd\b|passcode|पासवर्ड)")
_PW_VALUE = re.compile(
    r"(?:pass\s*word|passwd|passwrd|\bpwd\b|passcode|पासवर्ड)\s*(?:is|hai|h|ye|yeh)?\s*[:=\-]?\s*(\S+)")
_PW_NONSECRET = frozenset({
    "is", "hai", "h", "ye", "yeh", "kya", "bhool", "bhul", "forgot", "forget", "reset", "change",
    "manager", "vault", "page", "link", "chahiye", "nahi", "not", "to", "for", "ka", "ki", "save",
    "delete", "mat", "never", "se", "mein", "me", "chat", "kyun", "why"})


def normalize_chat_text(text: str) -> str:
    """NFKC, no zero-width characters, every Unicode decimal digit (Devanagari, Arabic-Indic,
    full-width ...) turned into an ASCII digit, lower case."""
    t = unicodedata.normalize("NFKC", text or "").translate(_INVISIBLE)
    out = [str(unicodedata.decimal(ch)) if unicodedata.category(ch) == "Nd" else ch for ch in t]
    return "".join(out).lower().strip()


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


def _joined_digits(t: str) -> str:
    """'4111 1111-1111 1111' -> '4111111111111111' (separators between digit groups removed)."""
    return re.sub(r"(?<=\d)[ \-.]+(?=\d)", "", t)


def extract_login_code(text: str, *, site: str = "") -> str | None:
    """The 4-8 digit code if the WHOLE message is a code: bare digits, digits with spaces / dashes /
    Devanagari digits, digit words, optionally with filler words ('otp hai 4821'). Anything else
    (a question, a second number, a sentence) means it is not a code."""
    if not text or len(text) > MAX_CODE_MESSAGE_CHARS:
        return None
    t = _BOUNDARY.sub(" ", normalize_chat_text(text))
    extra = {site.lower()} if site else set()
    digits: list[str] = []
    for tok in _SPLIT.split(t):
        if not tok:
            continue
        if tok.isdigit():
            digits.append(tok)
        elif tok in _DIGIT_WORDS:
            digits.append(_DIGIT_WORDS[tok])
        elif tok in _FILLERS or tok in extra:
            continue
        else:
            return None
    code = "".join(digits)
    return code if 4 <= len(code) <= 8 else None


@dataclass(frozen=True)
class ChatSecretVerdict:
    """What a chat message is. ``code`` exists only for LOGIN_OTP and never prints."""

    kind: str = NONE
    code: str = field(default="", repr=False, compare=False)

    @property
    def refused(self) -> bool:
        return self.kind in REFUSALS

    def __repr__(self) -> str:
        return f"ChatSecretVerdict(kind={self.kind!r})"

    __str__ = __repr__

    def __reduce__(self) -> object:
        raise TypeError("a verdict cannot be serialised")


def classify_chat_secret(text: str, *, login_site: str | None = None) -> ChatSecretVerdict:
    """Say whether a chat message carries a secret Friday must never take, or a login code it may.

    ``login_site``: the site of a login Friday just started for this user (``""`` when the site
    is unknown), or ``None`` when no login is pending, in which case nothing is ever a login code.
    Refusals are decided first and need no pending login. Pure: no state, no logging, no I/O."""
    t = normalize_chat_text(text)
    if not t:
        return ChatSecretVerdict()
    runs = re.findall(r"\d+", _joined_digits(t))
    longest = max((len(r) for r in runs), default=0)
    if _AADHAAR.search(t) and (_OTPISH.search(t) or longest >= 4):
        return ChatSecretVerdict(REFUSE_AADHAAR)
    if _UPI_PIN.search(t):
        return ChatSecretVerdict(REFUSE_UPI_PIN)
    if _CVV.search(t) or (_CARD_WORD.search(t) and longest >= 8):
        return ChatSecretVerdict(REFUSE_CARD)
    if any(13 <= len(r) <= 19 and _luhn(r) for r in runs):
        return ChatSecretVerdict(REFUSE_CARD)
    if _PASSWORD.search(t):
        m = _PW_VALUE.search(t)
        value = (m.group(1) if m else "").strip(".,!?")
        if value and value not in _PW_NONSECRET:
            return ChatSecretVerdict(REFUSE_PASSWORD)
    bankish = bool(_BANKISH.search(t))
    if bankish and _OTPISH.search(t) and longest >= 4:
        return ChatSecretVerdict(REFUSE_PAYMENT_OTP)
    if login_site is None:
        return ChatSecretVerdict()
    if bankish and longest >= 4:
        return ChatSecretVerdict(REFUSE_PAYMENT_OTP)  # a login is pending: be strict
    code = extract_login_code(text, site=login_site)
    return ChatSecretVerdict(LOGIN_OTP, code) if code is not None else ChatSecretVerdict()


def chat_secret_kind(text: str, *, login_pending: bool = False) -> str:
    """Guardrails entry point: the kind only (never the code)."""
    return classify_chat_secret(text, login_site="" if login_pending else None).kind


@dataclass
class PendingLogin:
    user_id: str
    site: str
    task_id: str
    expires_at: float


class PendingLoginRegistry:
    """'Friday itself just started a login for this user on this site' (memory only, short TTL).

    A code typed in chat is accepted only while such an entry exists for that user; ``consume`` is
    single use. Stores no code: only who, which site, which task."""

    def __init__(self, ttl_seconds: float = CHAT_OTP_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl, self._clock = ttl_seconds, clock
        self._by_user: dict[str, PendingLogin] = {}

    def expect(self, user_id: str, site: str, task_id: str) -> None:
        self._by_user[user_id] = PendingLogin(user_id, site.lower(), task_id,
                                              self._clock() + self._ttl)

    def peek(self, user_id: str) -> PendingLogin | None:
        p = self._by_user.get(user_id)
        if p is not None and self._clock() >= p.expires_at:
            self._by_user.pop(user_id, None)
            return None
        return p

    def consume(self, user_id: str) -> PendingLogin | None:
        p = self.peek(user_id)
        self._by_user.pop(user_id, None)
        return p

    def clear_task(self, task_id: str) -> int:
        gone = [u for u, p in self._by_user.items() if p.task_id == task_id]
        for u in gone:
            self._by_user.pop(u, None)
        return len(gone)

    def clear_user(self, user_id: str) -> bool:
        return self._by_user.pop(user_id, None) is not None

    def __repr__(self) -> str:
        return f"PendingLoginRegistry(pending={len(self._by_user)})"

    __str__ = __repr__
