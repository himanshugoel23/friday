"""Google Geocoding API + Google Maps link resolution (incl. maps.app.goo.gl).

Docs: https://developers.google.com/maps/documentation/geocoding/requests-geocoding
"""

from __future__ import annotations

from typing import Any

import httpx

from friday.core.interfaces import ProviderError
from friday.core.models import GeocodeResult, GeoPoint
from friday.discovery.maps_links import parse_maps_link

PROVIDER = "google"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_CONFIDENCE = {
    "ROOFTOP": 1.0,
    "RANGE_INTERPOLATED": 0.8,
    "GEOMETRIC_CENTER": 0.6,
    "APPROXIMATE": 0.4,
}
_MAX_REDIRECTS = 5


class GoogleGeocoder:
    name = PROVIDER

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def geocode(
        self, text: str, *, near: GeoPoint | None = None, region: str = "in"
    ) -> GeocodeResult | None:
        if not text.strip():
            return None
        params: dict[str, Any] = {"address": text, "region": region}
        if near:  # bias to ~10 km box around the anchor
            d = 0.09
            params["bounds"] = f"{near.lat - d},{near.lng - d}|{near.lat + d},{near.lng + d}"
        return await self._query(params)

    async def reverse(self, point: GeoPoint) -> GeocodeResult | None:
        res = await self._query({"latlng": f"{point.lat},{point.lng}"})
        if res:  # keep the exact pin the user shared
            res = res.model_copy(update={"location": point})
        return res

    async def resolve_maps_link(self, url: str) -> GeocodeResult | None:
        parsed = parse_maps_link(url)
        if parsed is not None and parsed.is_short:
            expanded = await self._expand(url)
            parsed = parse_maps_link(expanded) if expanded else None
        if parsed is None:
            return None
        if parsed.point:
            rev = await self.reverse(parsed.point)
            if rev:
                return rev
            return GeocodeResult(
                location=parsed.point,
                formatted_address=parsed.query or f"{parsed.point.lat:.5f},{parsed.point.lng:.5f}",
                confidence=0.9,
            )
        return await self.geocode(parsed.query or "")

    # ------------------------------------------------------------------ internals
    async def _expand(self, url: str) -> str | None:
        current = url
        for _ in range(_MAX_REDIRECTS):
            try:
                resp = await self._client.get(current, follow_redirects=False)
            except httpx.HTTPError as e:
                raise ProviderError(
                    PROVIDER, f"short link: {type(e).__name__}", retryable=True
                ) from e
            location = resp.headers.get("location")
            if resp.status_code not in (301, 302, 303, 307, 308) or not location:
                return current if current != url else None
            current = location
            parsed = parse_maps_link(current)
            if parsed and not parsed.is_short:
                return current
        return current

    async def _query(self, params: dict[str, Any]) -> GeocodeResult | None:
        try:
            resp = await self._client.get(GEOCODE_URL, params={**params, "key": self._key})
        except httpx.HTTPError as e:
            raise ProviderError(
                PROVIDER, f"network error: {type(e).__name__}", retryable=True
            ) from e
        if resp.status_code >= 400:
            raise ProviderError(
                PROVIDER, f"HTTP {resp.status_code}", retryable=resp.status_code >= 500
            )
        data = resp.json()
        status = data.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            raise ProviderError(
                PROVIDER,
                f"status {status}",
                retryable=status in ("OVER_QUERY_LIMIT", "UNKNOWN_ERROR"),
            )
        return _result(data["results"][0])


def _result(r: dict[str, Any]) -> GeocodeResult:
    geom = r.get("geometry") or {}
    loc = geom.get("location") or {}
    city = None
    for comp in r.get("address_components", []):
        types = comp.get("types", [])
        if "locality" in types:
            city = comp.get("long_name")
            break
        if city is None and "administrative_area_level_2" in types:
            city = comp.get("long_name")
    return GeocodeResult(
        location=GeoPoint(lat=loc["lat"], lng=loc["lng"]),
        formatted_address=r.get("formatted_address", ""),
        city=city,
        provider_place_id=r.get("place_id"),
        confidence=_CONFIDENCE.get(geom.get("location_type", ""), 0.5),
    )


def build_google_geocoder(c) -> GoogleGeocoder:  # c: Container
    key = c.settings.google_places_api_key
    if not key:
        raise ProviderError(PROVIDER, "GOOGLE_PLACES_API_KEY not set")
    return GoogleGeocoder(key.get_secret_value())
