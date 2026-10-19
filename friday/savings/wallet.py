"""The user's wallet: which cards they hold, by bank and card NAME only.

Never stored: card number, CVV, expiry, OTP, PIN, bank login. A message or a field that looks like
one is refused (``looks_sensitive``), and the user is told why. Stored per user, encrypted at rest
(friday/savings/dbmodel.py): bank, card name and the optional figures below.

    parse_wallet_message("mere paas HDFC Regalia aur SBI Cashback hai")
        -> WalletIntent(kind="add", cards=[ParsedCard("HDFC Bank", "Regalia"), ...])
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from friday.core.models import new_id
from friday.savings.rules import make_card_key, slug

Network = Literal["visa", "mastercard", "rupay", "amex", "diners"]

# canonical bank names; the first alias token(s) of a message chunk are matched longest-first
BANKS: dict[str, tuple[str, ...]] = {
    "HDFC Bank": ("hdfc bank", "hdfc"),
    "SBI Card": ("sbi card", "sbi"),
    "ICICI Bank": ("icici bank", "icici"),
    "Axis Bank": ("axis bank", "axis"),
    "Kotak Mahindra Bank": ("kotak mahindra", "kotak"),
    "IDFC FIRST Bank": ("idfc first bank", "idfc first", "idfc"),
    "IndusInd Bank": ("indusind bank", "indusind"),
    "Yes Bank": ("yes bank", "yes"),
    "RBL Bank": ("rbl bank", "rbl"),
    "AU Small Finance Bank": ("au small finance bank", "au bank", "au"),
    "American Express": ("american express", "amex"),
    "Standard Chartered": ("standard chartered", "stanchart", "scb"),
    "HSBC": ("hsbc",),
    "Bank of Baroda": ("bank of baroda", "bob"),
    "Punjab National Bank": ("punjab national bank", "pnb"),
    "Federal Bank": ("federal bank", "federal"),
    "Citi": ("citibank", "citi"),
    "Example Bank": ("example bank",),  # fake bank used by the EXAMPLE rows and the tests
}
_BANK_ALIASES = sorted(
    ((alias, canon) for canon, aliases in BANKS.items() for alias in aliases),
    key=lambda t: len(t[0]),
    reverse=True,
)
_NETWORKS = {
    "visa": "visa", "mastercard": "mastercard", "master card": "mastercard", "rupay": "rupay",
    "amex": "amex", "diners": "diners",
}
_GENERIC = {"card", "cards", "credit", "debit", "cc", "wala", "wali", "ka", "ki", "ke"}

_DIGITS_RUN = re.compile(r"\d(?:[\s\-]?\d){11,}")  # 12+ digits, with spaces or dashes allowed
_SENSITIVE_WORD = re.compile(
    r"\b(?:cvv|cvc|otp|password|passcode|(?:upi|atm|card|debit|credit|my|mera|meri)\s+pin|"
    r"pin\s*(?:is|hai))\b|\bpin\s*:",
    re.I,
)
_EXPIRY = re.compile(r"(?<![\d/])(?:0?[1-9]|1[0-2])\s*[/\-]\s*\d{2}(?!\d)")


def looks_sensitive(text: str) -> str | None:
    """A reason code when ``text`` looks like card data or a secret, else None.
    Deliberately strict: a false alarm only asks the user to rephrase."""
    if _DIGITS_RUN.search(text):
        return "card_number"
    if re.search(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b", text):
        return "card_number"
    if _SENSITIVE_WORD.search(text) and re.search(r"\d", text):
        return "secret_word"
    if re.search(r"\b(expiry|exp\.?\s*date|valid\s*thru)\b", text, re.I) and _EXPIRY.search(text):
        return "expiry"
    return None


class SensitiveDataError(ValueError):
    """Raised when a wallet field looks like a card number or a secret."""


def ensure_not_sensitive(value: str, field_name: str = "value") -> str:
    """Raise SensitiveDataError for text that looks like card data (many digits, a secret word)."""
    if sum(ch.isdigit() for ch in value) > 4 or looks_sensitive(value):
        raise SensitiveDataError(f"{field_name} looks like card data")
    return value


def _clean_name(value: str, field_name: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise ValueError(f"{field_name} is empty")
    if len(value) > 60:
        raise ValueError(f"{field_name} is too long")
    return ensure_not_sensitive(value, field_name)


class UserCard(BaseModel):
    """One card in a user's wallet. All money in paise."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str = ""
    bank: str
    card_name: str
    network: Network | None = None
    billing_day: int | None = Field(default=None, ge=1, le=31)
    monthly_spend_so_far_paise: int = Field(default=0, ge=0)
    caps_used: dict[str, int] = Field(default_factory=dict)  # rule cap key -> reward used
    caps_month: str | None = None  # "2026-10": the month the caps_used figures belong to
    points_balance: int | None = Field(default=None, ge=0)
    usual: bool = False  # the card the user normally pays with (the ledger's baseline)
    added_at: datetime | None = None

    @field_validator("bank")
    @classmethod
    def _bank(cls, v: str) -> str:
        return _clean_name(v, "bank")

    @field_validator("card_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean_name(v, "card_name")

    @model_validator(mode="after")
    def _caps_non_negative(self) -> UserCard:
        if any(v < 0 for v in self.caps_used.values()):
            raise ValueError("caps_used must be >= 0")
        return self

    @property
    def card_key(self) -> str:
        return make_card_key(self.bank, self.card_name)

    @property
    def display(self) -> str:
        return f"{self.bank} {self.card_name}"

    def caps_used_on(self, today: date) -> dict[str, int]:
        """Caps used this month; a new month starts again from zero."""
        return dict(self.caps_used) if self.caps_month == f"{today:%Y-%m}" else {}

    def with_cap_used(self, cap_key: str, reward_paise: int, today: date) -> UserCard:
        used = self.caps_used_on(today)
        used[cap_key] = used.get(cap_key, 0) + max(0, reward_paise)
        return self.model_copy(update={"caps_used": used, "caps_month": f"{today:%Y-%m}"})


# ------------------------------------------------------------------ message parsing


@dataclass(frozen=True)
class ParsedCard:
    bank: str
    card_name: str
    network: str | None = None
    bank_known: bool = True


@dataclass
class WalletIntent:
    kind: Literal["add", "remove", "list", "none"]
    cards: list[ParsedCard] = field(default_factory=list)
    unclear: list[str] = field(default_factory=list)  # chunks where the card name is missing
    sensitive: str | None = None  # reason code: nothing was parsed


_LEAD_ADD = re.compile(
    r"^\s*(?:mere\s+pa+s|meri\s+pa+s|mere\s+paas|mujhe|i\s+(?:have|use|hold)|i'?ve\s+got|"
    r"my\s+cards?\s+(?:are|is)|mere\s+cards?(?:\s+hain|\s+hai)?|add\s+cards?|card\s+add\s+(?:karo|kar)?|"
    r"wallet\s+me[ie]n?|ye\s+cards?\s+hain)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_TAIL = re.compile(
    r"\s*(?:hai+n?|he|hain|are|is|use\s+karta\s+hoon|use\s+karti\s+hoon|add\s+(?:karo|kar\s+do)|"
    r"hain\s+mere\s+paas)\s*[.!]*\s*$",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*(?:,|&|\+|\band\b|\baur\b|\bor\b|\btatha\b|\bevam\b)\s*", re.IGNORECASE)
_REMOVE = re.compile(
    r"\b(hata\s*do|hatao|hata\s*de|hata|remove|delete|nikal\s*do|nikaal\s*do|nikal\s*de|"
    r"band\s*kar\s*do)\b",
    re.IGNORECASE,
)
_ADD_HINT = re.compile(
    r"(mere\s+pa+s|meri\s+pa+s|\bi\s+(have|use|hold)\b|i'?ve\s+got|my\s+cards?\s+(are|is)|"
    r"\badd\s+cards?\b|\bcard\s+add\b|\bmere\s+cards?\b|\bwallet\s+me)",
    re.IGNORECASE,
)
_LIST = re.compile(
    r"^\s*(?:mere\s+cards?(?:\s+(?:dikhao|batao|list))?|my\s+cards?(?:\s+list)?|cards?\s+list|"
    r"wallet\s+(?:dikhao|dikha|show|batao)|show\s+(?:my\s+)?(?:wallet|cards?)|"
    r"kaun\s*(?:se|sa)\s+cards?\s+hain\s+mere\s+paas)\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def parse_card_chunk(chunk: str) -> ParsedCard | None | str:
    """One chunk like 'HDFC Regalia' -> ParsedCard. Returns the chunk text when the card name is
    missing ('HDFC credit card'), None when it is empty."""
    text = re.sub(r"\s+", " ", chunk.strip(" .!?:;-'\""))
    if not text:
        return None
    network: str | None = None
    low = text.lower()
    for alias, net in _NETWORKS.items():
        if re.search(rf"\b{alias}\b", low):
            network = net
            text = re.sub(rf"\b{alias}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    low = text.lower()
    bank = canon = None
    rest = text
    for alias, c in _BANK_ALIASES:
        if low == alias or low.startswith(alias + " "):
            canon, rest = c, text[len(alias) :].strip()
            bank = canon
            break
    bank_known = bank is not None
    if bank is None:
        words = text.split(" ")
        if len(words) < 2:
            return text
        bank, rest = words[0].title() if words[0].islower() else words[0], " ".join(words[1:])
    name_words = [w for w in rest.split(" ") if w and w.lower() not in _GENERIC]
    if not name_words:
        return text
    return ParsedCard(bank=bank, card_name=" ".join(name_words), network=network,
                      bank_known=bank_known)


def parse_wallet_message(text: str) -> WalletIntent:
    """Understand 'mere paas HDFC Regalia aur SBI Cashback hai' / 'SBI Cashback hata do' /
    'mere cards'. Anything that looks like card data stops everything (nothing is stored)."""
    reason = looks_sensitive(text)
    if reason:
        return WalletIntent(kind="none", sensitive=reason)
    if _LIST.match(text):
        return WalletIntent(kind="list")
    is_remove = bool(_REMOVE.search(text))
    if is_remove:
        body = _REMOVE.sub(" ", text)
        body = re.sub(r"\b(card|cards|mere|meri|se|ko|wallet|from|my|the)\b", " ", body, flags=re.I)
        kind: Literal["add", "remove"] = "remove"
    elif _ADD_HINT.search(text):
        body = _TAIL.sub("", _LEAD_ADD.sub("", text.strip()))
        kind = "add"
    else:
        return WalletIntent(kind="none")
    intent = WalletIntent(kind=kind)
    for chunk in _SPLIT.split(body):
        parsed = parse_card_chunk(chunk)
        if parsed is None:
            continue
        if isinstance(parsed, str):
            intent.unclear.append(parsed)
        else:
            intent.cards.append(parsed)
    if not intent.cards and not intent.unclear:
        return WalletIntent(kind="none")
    return intent


def match_cards(cards: list[UserCard], query: str) -> list[UserCard]:
    """Wallet cards matching a user's words ('sbi cashback', 'regalia'): every query token must
    appear in the bank + card name (case-insensitive)."""
    tokens = [t for t in slug(query).split("-") if t and t not in _GENERIC]
    if not tokens:
        return []
    out = []
    for c in cards:
        hay = slug(f"{c.bank} {c.card_name}")
        if all(t in hay for t in tokens):
            out.append(c)
    return out
