"""Agent 6: place searcher. Wraps the Google Places directory + geocoder (not edited).

``PlaceSearcher`` is the interface; ``GooglePlaceSearcher`` runs live Places text search with
a wider field mask (types, opening hours) and parses through the directory's own mapper;
``FixturePlaceSearcher`` replays a recorded response through the SAME parser.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from friday.core.models import GeoPoint
from friday.discovery.geo import haversine_km
from friday.discovery.google_geocoder import GoogleGeocoder
from friday.discovery.google_places import SEARCH_FIELDS, GooglePlacesDirectory
from friday.scouting.categories import build_queries, get_category
from friday.scouting.models import ScoutPlace, ScoutRequest, SearchResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"
# Same Enterprise SKU as SEARCH_FIELDS (phone + rating already in it): adds types and hours.
WIDE_SEARCH_FIELDS = (
    SEARCH_FIELDS + ",places.types,places.regularOpeningHours,places.nationalPhoneNumber"
)
_PARSER: GooglePlacesDirectory | None = None


def parse_places(raw: dict[str, Any], near: GeoPoint | None) -> list[ScoutPlace]:
    """Raw Places searchText JSON -> ScoutPlace (shared by live and fixture paths)."""
    global _PARSER
    if _PARSER is None:  # _candidate is a pure mapper; no request is ever made with this key
        _PARSER = GooglePlacesDirectory("parser-only")
    out = []
    for p in raw.get("places", []):
        if not p.get("id"):
            continue
        out.append(
            ScoutPlace(
                candidate=_PARSER._candidate(p, near=near),
                types=list(p.get("types") or []),
                business_status=p.get("businessStatus"),
            )
        )
    return out


class AreaResolver(Protocol):
    async def resolve(self, area: str) -> GeoPoint | None: ...


class PlaceSearcher(Protocol):
    async def search(self, req: ScoutRequest, *, max_queries: int = 3) -> SearchResult: ...


class GeocoderAreaResolver:
    def __init__(self, geocoder: GoogleGeocoder) -> None:
        self._g = geocoder

    async def resolve(self, area: str) -> GeoPoint | None:
        res = await self._g.geocode(area)
        return res.location if res else None


class GooglePlaceSearcher:
    def __init__(
        self,
        directory: GooglePlacesDirectory,
        resolver: AreaResolver,
        *,
        page_size: int = 20,
    ) -> None:
        self._dir = directory
        self._resolver = resolver
        self._page = page_size

    async def search(self, req: ScoutRequest, *, max_queries: int = 3) -> SearchResult:
        near = req.near or await self._resolver.resolve(req.area)
        queries = build_queries(get_category(req.category), req.area, max_queries=max_queries)
        seen: dict[str, ScoutPlace] = {}
        for q in queries:
            body: dict[str, Any] = {
                "textQuery": f"{q} in {req.area}",
                "pageSize": self._page,
                "regionCode": "IN",
                "languageCode": "en",
            }
            if near:
                body["locationBias"] = {
                    "circle": {
                        "center": {"latitude": near.lat, "longitude": near.lng},
                        "radius": min(req.radius_km * 1000.0, 50000.0),
                    }
                }
            raw = await self._dir._request("POST", "/places:searchText", WIDE_SEARCH_FIELDS, json=body)
            for sp in parse_places(raw, near):
                seen.setdefault(sp.candidate.place_id, sp)
        return SearchResult(places=list(seen.values()), near=near, queries=queries, source="google")


class FixturePlaceSearcher:
    """Replays a recorded searchText response; distance is recomputed from ``near``."""

    def __init__(self, path: Path | None = None, near: GeoPoint | None = None) -> None:
        self._raw = json.loads((path or FIXTURE_DIR / "salon_search.json").read_text())
        meta = self._raw.get("_fixture", {})
        c = meta.get("center")
        self._near = near or (GeoPoint(lat=c["lat"], lng=c["lng"]) if c else None)

    async def search(self, req: ScoutRequest, *, max_queries: int = 3) -> SearchResult:
        near = req.near or self._near
        queries = build_queries(get_category(req.category), req.area, max_queries=max_queries)
        places = parse_places(self._raw, near)
        for sp in places:  # parse_places already sets distance when near is known
            c = sp.candidate
            if near and c.location and c.distance_km is None:
                c.distance_km = round(haversine_km(near, c.location), 2)
        return SearchResult(places=places, near=near, queries=queries, source="fixtures")
