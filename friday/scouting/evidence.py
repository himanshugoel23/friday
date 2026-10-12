"""Agent 10: service-evidence extractor.

The LLM sits behind ``EvidenceLLM`` and must answer a CLOSED JSON schema. Code then
verifies every claim: the review id must exist and the quote must literally appear in that
review's text; labels must come from closed vocabularies; a price amount must appear in
its quote. Anything else is dropped (and counted). Bad JSON: retry once, then "unsure".
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from friday.scouting.categories import Category, _has_term
from friday.scouting.models import (
    EvidenceClaim,
    EvidenceKind,
    PlaceReviews,
    Review,
    ServiceEvidence,
)

THEMES = (
    "cleanliness",
    "staff_behaviour",
    "skill",
    "value_for_money",
    "wait_time",
    "ambience",
)
_THEME_POS = {
    "cleanliness": ["clean", "hygien", "sanitis", "sanitiz"],
    "staff_behaviour": ["polite", "friendly", "courteous", "humble", "respectful"],
    "skill": ["skilled", "professional", "expert", "talented", "perfect cut", "great job"],
    "value_for_money": ["reasonable", "affordable", "value for money", "worth the price"],
    "wait_time": ["on time", "no waiting", "quick", "punctual"],
    "ambience": ["ambience", "ambiance", "cozy", "well maintained"],
}
_THEME_NEG = {
    "cleanliness": ["dirty", "unhygienic", "filthy", "not clean"],
    "staff_behaviour": ["rude", "arrogant", "misbehav", "unprofessional"],
    "skill": ["ruined", "bad haircut", "messed up", "botched", "worst cut"],
    "value_for_money": ["overpriced", "expensive", "rip off", "ripoff", "overcharg"],
    "wait_time": ["waited", "waiting for", "long wait", "delay", "late"],
    "ambience": ["cramped", "noisy", "stuffy"],
}
_PRICE = re.compile(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)|(\d[\d,]*)\s*(?:rs\b|rupees|/-)", re.I)


class RawClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    label: str
    quote: str
    review_id: str
    amount_inr: int | None = None


class RawEvidence(BaseModel):
    """The closed schema the LLM must produce."""

    model_config = ConfigDict(extra="forbid")

    claims: list[RawClaim]


class EvidenceLLM(Protocol):
    async def extract(
        self,
        place_name: str,
        reviews: list[Review],
        service_labels: list[str],
        theme_labels: list[str],
    ) -> Any:
        """Return a dict ``{"claims": [...]}`` (or JSON string) matching RawEvidence."""


def _squash(s: str) -> str:
    return " ".join(s.lower().split())


def verify_claims(
    place_id: str, raw: RawEvidence, reviews: list[Review], service_labels: list[str]
) -> ServiceEvidence:
    by_id = {r.review_id: _squash(r.text) for r in reviews}
    kept: list[EvidenceClaim] = []
    dropped = 0
    for c in raw.claims:
        text = by_id.get(c.review_id)
        quote = _squash(c.quote)
        ok = bool(text) and len(quote) >= 3 and quote in text
        if ok and c.kind == "service_offered":
            ok = c.label in service_labels
        elif ok and c.kind in ("theme_positive", "theme_negative"):
            ok = c.label in THEMES
        elif ok and c.kind == "price_hint":
            ok = c.amount_inr is not None and str(c.amount_inr) in quote.replace(",", "")
        if ok and c.kind != "price_hint":
            ok = c.amount_inr is None
        if not ok:
            dropped += 1
            continue
        if any(
            k.kind == c.kind and k.label == c.label and k.review_id == c.review_id for k in kept
        ):
            continue
        kept.append(EvidenceClaim(**c.model_dump()))
    return ServiceEvidence(place_id=place_id, claims=kept, dropped_claims=dropped)


async def extract_evidence(
    pr: PlaceReviews,
    category: Category,
    llm: EvidenceLLM,
    place_name: str = "",
    *,
    max_attempts: int = 2,
) -> ServiceEvidence:
    if not pr.reviews:
        return ServiceEvidence(place_id=pr.place_id)
    labels = list(category.services)
    for _ in range(max_attempts):
        try:
            payload = await llm.extract(place_name, pr.reviews, labels, list(THEMES))
            raw = (
                RawEvidence.model_validate_json(payload)
                if isinstance(payload, str)
                else RawEvidence.model_validate(payload)
            )
        except (ValidationError, ValueError, TypeError):
            continue
        except Exception:
            continue
        return verify_claims(pr.place_id, raw, pr.reviews, labels)
    return ServiceEvidence(place_id=pr.place_id, status="unsure")


class KeywordEvidenceLLM:
    """Deterministic stand-in behind the same interface (no LLM needed offline/for the CLI).

    Finds category service terms, theme words and rupee amounts, quoting a window of the
    real review text. A real LLM can replace it without touching the verifier.
    """

    def __init__(self, category: Category) -> None:
        self._cat = category

    async def extract(self, place_name, reviews, service_labels, theme_labels) -> dict:
        claims: list[dict] = []
        for r in reviews:
            low = r.text.lower()
            for label, terms in self._cat.services.items():
                for t in terms:
                    m = re.search(rf"(?<![a-z0-9]){re.escape(t)}", low)
                    if m:
                        claims.append(self._claim("service_offered", label, r, m.start(), len(t)))
                        break
            for kind, table in (("theme_positive", _THEME_POS), ("theme_negative", _THEME_NEG)):
                for theme, words in table.items():
                    for w in words:
                        i = low.find(w)
                        if i >= 0 and not _negated(low, i):
                            claims.append(self._claim(kind, theme, r, i, len(w)))
                            break
            for m in _PRICE.finditer(r.text):
                amt = int((m.group(1) or m.group(2)).replace(",", ""))
                c = self._claim("price_hint", "price", r, m.start(), len(m.group(0)))
                c["amount_inr"] = amt
                claims.append(c)
        return {"claims": claims}

    @staticmethod
    def _claim(kind: str, label: str, r: Review, start: int, length: int) -> dict:
        a = max(0, start - 25)
        b = min(len(r.text), start + length + 25)
        return {
            "kind": kind,
            "label": label,
            "quote": r.text[a:b].strip(),
            "review_id": r.review_id,
            "amount_inr": None,
        }


def _negated(low: str, i: int) -> bool:
    return bool(re.search(r"\b(not|never|no|nahi|nahin)\s+$", low[max(0, i - 8) : i]))


__all__ = [
    "THEMES",
    "EvidenceLLM",
    "KeywordEvidenceLLM",
    "RawEvidence",
    "extract_evidence",
    "verify_claims",
    "_has_term",
]
