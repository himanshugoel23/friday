"""Hostile-input and privacy rules for document text. Pure functions, no I/O.

* Document text is DATA. ``looks_like_injection`` finds instruction-like text so the value is
  dropped and the document flagged; nothing in this package can act on it anyway.
* Aadhaar and other government-ID numbers are never kept: ``scrub_gov_ids`` removes them from any
  value and ``is_gov_id_document`` makes the pipeline refuse the whole file.
* A passport number is masked at once (``mask_passport_number``); the full number never reaches a
  stored field, a reply or a log line.
"""

from __future__ import annotations

import re
import unicodedata

# zero-width, bidi override/isolate and other invisible characters used to hide instructions
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)"
    r"|disregard\s+(?:all\s+|the\s+|your\s+)?(?:previous|prior|above|instructions)"
    r"|forget\s+(?:everything|all|your|the\s+above)"
    r"|(?:system|developer)\s+(?:prompt|message|instruction)"
    r"|new\s+instructions?"
    r"|you\s+are\s+now\b|act\s+as\s+(?:a|an|the)\b|pretend\s+(?:to\s+be|you)"
    r"|(?:^|\n)\s*(?:assistant|system|user)\s*:"
    r"|<\|[a-z_]+\|>|\[/?inst\]|<<\s*sys\s*>>"
    r"|reveal\s+(?:your|the)\s+(?:prompt|instructions|secrets?)"
    r"|(?:pehle|upar)\s+(?:ke|wale)\s+(?:nirdesh|instructions?)"
    r"|instructions?\s+(?:ko\s+)?ignore"
    r"|निर्देशों?\s+को\s+(?:अनदेखा|नज़रअंदाज़)",
    re.IGNORECASE,
)

_GROUPED_AADHAAR = re.compile(r"(?<!\d)\d{4}[ \-]\d{4}[ \-]\d{4}(?!\d)")
_PLAIN_12 = re.compile(r"(?<!\d)\d{12}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_DL = re.compile(r"\b[A-Z]{2}[ \-]?\d{2}[ \-]?\d{11}\b")
_GOV_WORDS = re.compile(
    r"aadhaar|aadhar|adhaar|आधार|uidai|unique\s+identification\s+authority"
    r"|permanent\s+account\s+number|income\s+tax\s+department|आयकर\s+विभाग"
    r"|driving\s+licen[cs]e|voter\s+id|election\s+commission|मतदाता",
    re.IGNORECASE,
)
GOV_ID_TYPES = frozenset({"aadhaar", "pan", "driving_licence", "voter_id", "gov_id", "id_card"})
REMOVED = "[removed]"


def clean_text(value: object, limit: int = 200) -> str:
    """Normalise a model/user string: no control or invisible characters, one line, capped."""
    s = unicodedata.normalize("NFKC", str(value or ""))
    s = _INVISIBLE.sub("", s)
    s = _CTRL.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(unicodedata.normalize("NFKC", _INVISIBLE.sub("", text or ""))))


def has_gov_id_number(text: str) -> bool:
    return bool(_GROUPED_AADHAAR.search(text) or _PAN.search(text) or _DL.search(text))


def scrub_gov_ids(text: str, *, doc_mentions_gov_id: bool = False) -> str:
    """Remove Aadhaar-shaped (4-4-4), PAN-shaped and licence-shaped numbers. A bare 12-digit
    number is removed only when the document talks about Aadhaar / government IDs (otherwise it
    is likely a booking or phone number)."""
    out = _GROUPED_AADHAAR.sub(REMOVED, text)
    out = _PAN.sub(REMOVED, out)
    out = _DL.sub(REMOVED, out)
    if doc_mentions_gov_id:
        out = _PLAIN_12.sub(REMOVED, out)
    return out


def is_gov_id_document(declared_type: str | None, text: str) -> bool:
    """True when the file IS an Aadhaar / PAN / licence / voter card (not a ticket that merely
    says "carry Aadhaar"). The caller refuses these without extracting anything."""
    if (declared_type or "").strip().lower() in GOV_ID_TYPES:
        return True
    return bool(_GOV_WORDS.search(text or "") and has_gov_id_number(text or "")) or bool(
        _GOV_WORDS.search(text or "") and _PLAIN_12.search(text or "")
    )


def mentions_gov_id(text: str) -> bool:
    return bool(_GOV_WORDS.search(text or ""))


def mask_passport_number(raw: object) -> str:
    """'P1234567' -> '*****567'. Only the last 3 characters survive; anything shorter is fully
    masked. The full number is never returned."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    if len(alnum) < 6:
        return "***" if alnum else ""
    return "*" * (len(alnum) - 3) + alnum[-3:]
