"""Quotes-flow vendor finder backed by ``friday.scouting`` (best AND near, hard radius).

Same interface as ``VendorFinder`` (``find`` / ``candidate_for``), so the flow can swap it in with
``FRIDAY_QUOTES_USE_SCOUTING``. Items flagged ``beyond_default_radius`` are never shown here: the
user must be asked first and the flow cannot ask that yet. Vendors without a phone are dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import GeoPoint
from friday.quotes.finder import FindResult, VendorFinder
from friday.scouting.categories import get_category
from friday.scouting.models import ScoutRequest
from friday.scouting.pipeline import scout
from friday.scouting.reviews import GoogleReviewFetcher
from friday.scouting.searcher import GooglePlaceSearcher

log = get_logger(__name__)


class _NoResolver:
    async def resolve(self, area: str) -> GeoPoint | None:  # the pin is always known here
        return None


class ScoutingVendorFinder(VendorFinder):
    def __init__(
        self,
        directory: Any,
        *,
        category: str = "salon",
        services: list[str] | None = None,
        review_budget: int = 6,
        max_queries: int = 2,
        **kw: Any,
    ) -> None:
        super().__init__(directory, **kw)
        self.category = category
        self.review_budget = review_budget
        self.max_queries = max_queries
        self.services = services or []

    @staticmethod
    def usable(directory: Any) -> bool:
        return hasattr(directory, "_request")

    async def find(
        self,
        point: GeoPoint,
        *,
        where_text: str,
        when: datetime | None = None,
        exclude: set[str] | None = None,
        limit: int = 12,
        max_calls: int | None = None,
    ) -> FindResult:
        res = FindResult()
        cap = self.max_calls if max_calls is None else max_calls
        queries = min(self.max_queries, cap)
        reviews = max(0, min(self.review_budget, cap - queries))
        if queries <= 0:
            res.capped = True
            return res
        cat = get_category(self.category)
        req = ScoutRequest(
            category=cat.key,
            area=where_text,
            near=point,
            services=self.services,
            radius_km=self.radius_km,
            top_n=limit,
        )
        try:
            out = await scout(
                req,
                GooglePlaceSearcher(self.directory, _NoResolver()),
                GoogleReviewFetcher(self.directory),
                review_budget=reviews,
                max_queries=queries,
            )
        except Exception as e:  # noqa: BLE001 - never let discovery raise into the chat
            log.warning("scouting failed: %s", type(e).__name__)
            res.error = True
            res.calls_used = queries
            return res
        res.calls_used = len(out.search.queries) + out.reviews_fetched_for
        seen: set[str] = set()
        for item in out.shortlist.items:
            c = item.place.candidate
            if item.beyond_default_radius or not c.phone:
                continue
            if exclude and c.place_id in exclude:
                continue
            if self.pool is not None and await self.pool.is_blocked(c.phone):
                continue  # DNC: never even shown
            if c.place_id in seen:
                continue
            seen.add(c.place_id)
            res.vendors.append(self._vendor(c, when))
        return res



