"""Typed hand-off objects between the scouting agents. Pure data, no I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from friday.core.models import BusinessCandidate, GeoPoint


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutRequest(_M):
    category: str  # key in categories.CATEGORIES
    area: str  # free text, e.g. "Sector 56 Gurgaon"
    services: list[str] = Field(default_factory=list)  # what the user wants, free text
    near: GeoPoint | None = None  # skip geocoding when the pin is known
    radius_km: float | None = None  # None = category default; widening is capped at its max
    budget_inr: int | None = None
    gender_pref: Literal["men", "women", "unisex"] | None = None
    home_visit: bool = False
    top_n: int = 3


class ScoutPlace(_M):
    """A raw candidate from the place searcher (agent 6)."""

    candidate: BusinessCandidate
    types: list[str] = Field(default_factory=list)
    business_status: str | None = None


class SearchResult(_M):
    places: list[ScoutPlace]
    near: GeoPoint | None = None
    queries: list[str] = Field(default_factory=list)
    source: Literal["google", "fixtures"] = "google"


class DropReason(_M):
    place_id: str
    name: str
    reason: Literal[
        "closed",
        "no_phone",
        "wrong_type",
        "outside_radius",
        "duplicate",
        "toll_free_number",
        "suspicious_reviews",
    ]
    detail: str = ""


class EligibilityResult(_M):
    eligible: list[ScoutPlace]
    dropped: list[DropReason]


class Review(_M):
    review_id: str
    text: str
    rating: int | None = None  # 1-5
    published_at: datetime | None = None
    author: str | None = None
    author_review_count: int | None = None  # Places API does not give this; None = unknown


class PlaceReviews(_M):
    place_id: str
    reviews: list[Review] = Field(default_factory=list)


class AuthFlag(_M):
    code: Literal[
        "NO_REVIEWS",
        "REVIEW_BURST",
        "DUPLICATE_TEXT",
        "SHORT_GENERIC_PRAISE",
        "LOW_HISTORY_REVIEWERS",
        "RATING_ODDITY",
        "LLM_TEMPLATE_TEXT",
        "LLM_KEYWORD_STUFFING",
        "LLM_UNRELATED",
        "LLM_PROMOTIONAL",
    ]
    detail: str
    penalty: float
    review_ids: list[str] = Field(default_factory=list)


class AuthenticityReport(_M):
    place_id: str
    genuine_score: float  # 0-1, higher = more genuine
    confidence: Literal["low", "medium", "high"]
    flags: list[AuthFlag] = Field(default_factory=list)
    reviews_seen: int = 0
    llm_used: bool = False


EvidenceKind = Literal["service_offered", "theme_positive", "theme_negative", "price_hint"]


class EvidenceClaim(_M):
    """One claim. Only exists if code verified quote is inside the named review."""

    kind: EvidenceKind
    label: str  # closed vocabulary: service key or theme key
    quote: str
    review_id: str
    amount_inr: int | None = None  # price_hint only; digits must appear in the quote


class ServiceEvidence(_M):
    place_id: str
    claims: list[EvidenceClaim] = Field(default_factory=list)
    dropped_claims: int = 0  # claims rejected by the verifier
    status: Literal["ok", "unsure"] = "ok"  # unsure = LLM output unusable after retry

    def services(self) -> set[str]:
        return {c.label for c in self.claims if c.kind == "service_offered"}


class FitScore(_M):
    place_id: str
    value: float  # 0-1
    reasons: list[str] = Field(default_factory=list)
    services_confirmed: list[str] = Field(default_factory=list)
    services_missing: list[str] = Field(default_factory=list)


class RankedItem(_M):
    rank: int
    place: ScoutPlace
    distance_km: float | None = None
    beyond_default_radius: bool = False  # user must be asked before showing/choosing these
    score: float
    components: dict[str, float]
    reasons: list[str]
    flags: list[str] = Field(default_factory=list)


class RankedShortlist(_M):
    items: list[RankedItem]
    best_in_range: RankedItem | None = None  # best inside the DEFAULT radius
    nearest_good: RankedItem | None = None  # nearest acceptable; differs from best sometimes
    radius_km: float = 0.0  # effective radius used
    default_radius_km: float = 0.0
    widened: bool = False
    excluded: list[DropReason] = Field(default_factory=list)


class ScoutResult(_M):
    request: ScoutRequest
    search: SearchResult
    eligibility: EligibilityResult
    shortlist: RankedShortlist
    reviews_fetched_for: int = 0
