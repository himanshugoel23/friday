"""Item 1: the inbox + calendar digest sent after Gmail is connected, and its self-correction.

Pure functions over plain data (fake Gmail/Calendar fixtures in tests; the real connector maps its
rows into these dataclasses). Nothing here reads a mailbox, sends a message or stores anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from friday.chatbot.parity import copy

DIGEST_DEADLINE_S = 120  # send within 2 minutes of the connect
MAX_ITEMS = 3

_PHISH_ID = re.compile(r"\b(?:pan|kyc|aadhaar|aadhar)\b", re.I)
_PHISH_ACT = re.compile(
    r"\b(?:update|verify|blocked|block|suspend\w*|expire\w*|deactivat\w*|click|link|immediately|urgent)\b",
    re.I,
)


@dataclass(frozen=True)
class Mail:
    id: str
    sender: str
    subject: str
    snippet: str = ""
    needs_reply: bool = False


@dataclass(frozen=True)
class Renewal:
    name: str
    due: date


@dataclass(frozen=True)
class Inbox:
    mails: tuple[Mail, ...] = ()
    storage_pct: int | None = None
    renewals: tuple[Renewal, ...] = ()


@dataclass
class Digest:
    text: str
    claims: dict[str, str] = field(default_factory=dict)  # key -> value, kept to self-correct
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (old claim, new claim)
    phishing_ids: list[str] = field(default_factory=list)


def is_phishing(mail: Mail) -> bool:
    """A PAN/KYC/Aadhaar mention together with an urgency/action word: warn, never act."""
    blob = f"{mail.subject} {mail.snippet}"
    return bool(_PHISH_ID.search(blob) and _PHISH_ACT.search(blob))


def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


def build_claims(inbox: Inbox) -> dict[str, str]:
    claims: dict[str, str] = {}
    for m in inbox.mails:
        if is_phishing(m):
            claims[f"phish:{m.id}"] = m.subject
        elif m.needs_reply:
            claims[f"lead:{m.id}"] = m.subject
    if inbox.storage_pct is not None and inbox.storage_pct >= 90:
        claims["storage"] = str(inbox.storage_pct)
    for r in inbox.renewals:
        claims[f"renewal:{r.name}"] = r.due.isoformat()
    return claims


def _describe(key: str, value: str) -> str:
    kind, _, name = key.partition(":")
    if kind == "storage":
        return f"storage {value}%"
    if kind == "renewal":
        return f"{name} renewal {_fmt_date(date.fromisoformat(value))}"
    if kind == "phish":
        return f"'{value}' is a scam warning"
    return f"'{value}' needs a reply"


def corrections(prior: dict[str, str], now: dict[str, str]) -> list[tuple[str, str]]:
    """Claims that were made before and are now wrong: changed value, or no longer true."""
    out: list[tuple[str, str]] = []
    for key, old in prior.items():
        if key not in now:
            out.append((_describe(key, old), f"{_describe(key, old)}: no longer true"))
        elif now[key] != old:
            out.append((_describe(key, old), _describe(key, now[key])))
    return out


def build_digest(inbox: Inbox, lang: str = "hinglish", prior: dict[str, str] | None = None) -> Digest:
    claims = build_claims(inbox)
    fixes = corrections(prior or {}, claims)
    parts: list[str] = []
    phish = [m for m in inbox.mails if is_phishing(m)]
    leads = [m for m in inbox.mails if m.needs_reply and not is_phishing(m)]
    for old, new in fixes:
        parts.append(copy.line("digest_correction", lang, old=old, new=new))
    if phish or leads or "storage" in claims or inbox.renewals:
        parts.append(copy.line("digest_head", lang))
    if leads:
        items = "; ".join(f"{m.sender}: {m.subject}" for m in leads[:MAX_ITEMS])
        parts.append(copy.line("digest_leads", lang, items=items))
    for m in phish[:MAX_ITEMS]:
        parts.append(copy.line("digest_phishing", lang, subject=m.subject))
    if "storage" in claims:
        parts.append(copy.line("digest_storage", lang, pct=claims["storage"]))
    if inbox.renewals:
        rs = sorted(inbox.renewals, key=lambda r: r.due)[:MAX_ITEMS]
        parts.append(
            copy.line("digest_renewals", lang, items=", ".join(f"{r.name} {_fmt_date(r.due)}" for r in rs))
        )
    if not parts:
        parts.append(copy.line("digest_empty", lang))
    return Digest(
        text="\n".join(parts), claims=claims, corrections=fixes, phishing_ids=[m.id for m in phish]
    )


def due_for_digest(connected_at_s: float, now_s: float, already_sent: bool) -> bool:
    """True while the first digest is still owed (send at once; log a miss after 2 minutes)."""
    return not already_sent and now_s >= connected_at_s


def within_deadline(connected_at_s: float, sent_at_s: float) -> bool:
    return sent_at_s - connected_at_s <= DIGEST_DEADLINE_S
