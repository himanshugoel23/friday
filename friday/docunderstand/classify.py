"""Document type: layout words in the read text first, then the model's own guess, else generic."""

from __future__ import annotations

import re

from friday.docunderstand.models import DocType

_WORDS: dict[DocType, tuple[str, ...]] = {
    DocType.FLIGHT: (
        r"boarding pass",
        r"e-?ticket",
        r"\bpnr\b",
        r"flight",
        r"\bgate\b",
        r"\bdeparture\b",
        r"indigo",
        r"air india",
        r"vistara",
        r"akasa",
        r"spicejet",
        r"उड़ान",
    ),
    DocType.TRAIN: (
        r"irctc",
        r"indian railways?",
        r"\btrain\b",
        r"\bcoach\b",
        r"\bberth\b",
        r"\bsleeper\b",
        r"\b[1-3]a\b",
        r"रेल",
        r"ट्रेन",
    ),
    DocType.HOTEL: (
        r"check-?in",
        r"check-?out",
        r"\bhotel\b",
        r"booking confirmation",
        r"\broom\b",
        r"reservation",
        r"guests?",
        r"होटल",
    ),
    DocType.PASSPORT: (
        r"passport",
        r"republic of india",
        r"p<ind",
        r"date of expiry",
        r"पासपोर्ट",
    ),
    DocType.BILL: (
        r"amount due",
        r"due date",
        r"bill date",
        r"\bbill\b",
        r"minimum (?:amount )?due",
        r"consumer no",
        r"statement",
        r"बिल",
        r"देय",
    ),
}
_FROM_MODEL = {t.value: t for t in DocType}


def classify(text: str, model_guess: str | None) -> DocType:
    """Highest layout-word score wins; a tie or no score falls back to the model's guess."""
    low = (text or "").lower()
    scores = {t: sum(1 for w in words if re.search(w, low)) for t, words in _WORDS.items()}
    best = max(scores.values(), default=0)
    leaders = [t for t, n in scores.items() if n == best]
    guess = _FROM_MODEL.get((model_guess or "").strip().lower())
    if best >= 2 and len(leaders) == 1:
        return leaders[0]
    if guess is not None:
        return guess
    if best >= 1 and len(leaders) == 1:
        return leaders[0]
    return DocType.GENERIC
