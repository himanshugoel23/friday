"""Google Places API (New) directory: Text Search + Place Details. Read-only.

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
Auth: ``X-Goog-Api-Key``; field selection via ``X-Goog-FieldMask`` (billing tier).
Raw review text is only kept in memory for shortlisting (US-17.10 caching terms).
"""

from __future__ import annotations

from typing import Any

import httpx

from friday.core.clock import Clock, SystemClock
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.core.models import (
    BusinessCandidate,
    BusinessHours,
    GeoPoint,
    OpeningPeriod,
    normalize_phone,
)
from friday.discovery.geo import haversine_km

log = get_logger(__name__)

PROVIDER = "google_places"
BASE_URL = "https://places.googleapis.com/v1"

SEARCH_FIELDS = ",".join(
    f"places.{f}"
    for f in (
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "currentOpeningHours.openNow",
        "priceLevel",
        "primaryType",
        "businessStatus",
        "internationalPhoneNumber",
    )
)
DETAIL_FIELDS = ",".join(
    (
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "regularOpeningHours",
        "currentOpeningHours.openNow",
        "reviews",
        "priceLevel",
        "primaryType",
        "businessStatus",
    )
)
_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
MAX_REVIEWS = 10


class GooglePlacesDirectory:
    name = PROVIDER

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock | None = None,
        bias_radius_m: float = 3000.0,
        language: str = "en",
    ) -> None:
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self.clock = clock or SystemClock()
        self.bias_radius_m = bias_radius_m
        self.language = language
        self._details_cache: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ protocol
    async def search(
        self, query: str, location: str, *, near: GeoPoint | None = None, limit: int = 10
    ) -> list[BusinessCandidate]:
        text = f"{query} in {location}" if location else query
        body: dict[str, Any] = {
            "textQuery": text,
            "pageSize": max(1, min(limit, 20)),
            "regionCode": "IN",
            "languageCode": self.language,
        }
        if near:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": near.lat, "longitude": near.lng},
                    "radius": self.bias_radius_m,
                }
            }
        data = await self._request("POST", "/places:searchText", SEARCH_FIELDS, json=body)
        out: list[BusinessCandidate] = []
        for place in data.get("places", []):
            if place.get("businessStatus") == "CLOSED_PERMANENTLY":
                continue
            out.append(self._candidate(place, near=near))
        return out[:limit]

    async def details(self, place_id: str) -> BusinessCandidate | None:
        place = await self._details(place_id)
        return self._candidate(place) if place else None

    async def business_hours(self, place_id: str) -> BusinessHours | None:
        place = await self._details(place_id)
        return parse_opening_hours(place.get("regularOpeningHours")) if place else None

    # ------------------------------------------------------------------ internals
    async def _details(self, place_id: str) -> dict[str, Any] | None:
        if place_id in self._details_cache:
            return self._details_cache[place_id]
        try:
            data = await self._request(
                "GET", f"/places/{place_id}", DETAIL_FIELDS, params={"languageCode": self.language}
            )
        except ProviderError as e:
            if "404" in str(e):
                return None
            raise
        self._details_cache[place_id] = data
        return data

    async def _request(self, method: str, path: str, fields: str, **kw: Any) -> dict[str, Any]:
        headers = {
            "X-Goog-Api-Key": self._key,
            "X-Goog-FieldMask": fields,
            "Content-Type": "application/json",
        }
        try:
            resp = await self._client.request(method, BASE_URL + path, headers=headers, **kw)
        except httpx.HTTPError as e:
            raise ProviderError(
                PROVIDER, f"network error: {type(e).__name__}", retryable=True
            ) from e
        if resp.status_code >= 400:
            retryable = resp.status_code in (429, 500, 502, 503, 504)
            raise ProviderError(PROVIDER, f"HTTP {resp.status_code}", retryable=retryable)
        return resp.json()

    def _candidate(self, p: dict[str, Any], *, near: GeoPoint | None = None) -> BusinessCandidate:
        loc = p.get("location") or {}
        point = (
            GeoPoint(lat=loc["latitude"], lng=loc["longitude"])
            if "latitude" in loc and "longitude" in loc
            else None
        )
        phone = None
        raw_phone = p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber")
        if raw_phone:
            try:
                phone = normalize_phone(raw_phone)
            except ValueError:
                phone = None
        reviews = []
        for r in (p.get("reviews") or [])[:MAX_REVIEWS]:
            text = (r.get("text") or r.get("originalText") or {}).get("text")
            if text:
                reviews.append(text.strip())
        return BusinessCandidate(
            provider=PROVIDER,
            place_id=p.get("id", ""),
            name=(p.get("displayName") or {}).get("text") or p.get("id", "?"),
            phone=phone,
            category=p.get("primaryType"),
            address=p.get("formattedAddress"),
            location=point,
            distance_km=round(haversine_km(near, point), 2) if (near and point) else None,
            rating=p.get("rating"),
            review_count=int(p.get("userRatingCount") or 0),
            review_snippets=reviews,
            maps_url=p.get("googleMapsUri"),
            open_now=(p.get("currentOpeningHours") or {}).get("openNow"),
            price_level=_PRICE_LEVELS.get(p.get("priceLevel", "")),
            hours=parse_opening_hours(p.get("regularOpeningHours")),
        )


def parse_opening_hours(data: dict[str, Any] | None) -> BusinessHours | None:
    """Places ``regularOpeningHours`` -> BusinessHours. Google day 0 = Sunday."""
    if not data or not data.get("periods"):
        return None
    periods: list[OpeningPeriod] = []
    for p in data["periods"]:
        o, c = p.get("open"), p.get("close")
        if not o:
            continue
        weekday = (int(o.get("day", 0)) + 6) % 7
        start = f"{int(o.get('hour', 0)):02d}:{int(o.get('minute', 0)):02d}"
        if not c:  # open 24h
            periods.extend(OpeningPeriod(weekday=d, open="00:00", close="23:59") for d in range(7))
            continue
        end = f"{int(c.get('hour', 0)):02d}:{int(c.get('minute', 0)):02d}"
        if c.get("day", o.get("day")) != o.get("day") or end <= start:
            end = "23:59"  # crosses midnight: keep the same-day part
        if end > start:
            periods.append(OpeningPeriod(weekday=weekday, open=start, close=end))
    return BusinessHours(periods=periods, source=PROVIDER)


def build_google_places_directory(c) -> GooglePlacesDirectory:  # c: Container
    key = c.settings.google_places_api_key
    if not key:
        raise ProviderError(PROVIDER, "GOOGLE_PLACES_API_KEY not set")
    return GooglePlacesDirectory(key.get_secret_value(), clock=c.clock)
