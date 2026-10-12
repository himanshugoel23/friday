"""Agent 8: review fetcher. Places Details reviews, IN MEMORY ONLY (never persisted)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.discovery.google_places import GooglePlacesDirectory
from friday.scouting.models import PlaceReviews, Review
from friday.scouting.searcher import FIXTURE_DIR

log = get_logger(__name__)
REVIEW_FIELDS = "id,reviews"  # Places returns at most 5 reviews per place


class ReviewFetcher(Protocol):
    async def fetch(self, place_id: str) -> PlaceReviews: ...


def parse_reviews(place_id: str, raw: dict[str, Any], limit: int = 5) -> PlaceReviews:
    out: list[Review] = []
    for i, r in enumerate((raw.get("reviews") or [])[:limit]):
        text = ((r.get("text") or r.get("originalText") or {}).get("text") or "").strip()
        if not text:
            continue
        published = None
        if r.get("publishTime"):
            try:
                published = datetime.fromisoformat(str(r["publishTime"]).replace("Z", "+00:00"))
            except ValueError:
                published = None
        rid = str(r.get("name") or f"r{i + 1}").rsplit("/", 1)[-1]
        out.append(
            Review(
                review_id=rid,
                text=text,
                rating=int(r["rating"]) if r.get("rating") else None,
                published_at=published,
                author=(r.get("authorAttribution") or {}).get("displayName"),
                author_review_count=r.get("_author_review_count"),  # not provided by Google
            )
        )
    return PlaceReviews(place_id=place_id, reviews=out)


class GoogleReviewFetcher:
    def __init__(self, directory: GooglePlacesDirectory) -> None:
        self._dir = directory

    async def fetch(self, place_id: str) -> PlaceReviews:
        try:
            raw = await self._dir._request(
                "GET", f"/places/{place_id}", REVIEW_FIELDS, params={"languageCode": "en"}
            )
        except ProviderError as e:
            log.warning("review fetch failed", extra={"place_id": place_id, "err": str(e)})
            return PlaceReviews(place_id=place_id)
        return parse_reviews(place_id, raw)


class FixtureReviewFetcher:
    def __init__(self, path: Path | None = None) -> None:
        self._by_place = json.loads((path or FIXTURE_DIR / "salon_reviews.json").read_text())

    async def fetch(self, place_id: str) -> PlaceReviews:
        return parse_reviews(place_id, self._by_place.get(place_id, {}))
