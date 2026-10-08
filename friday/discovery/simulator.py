"""Directory + geocoder simulators over the shared ``simworld`` (no network, no keys).

The number the directory returns is the number the telephony simulator answers,
so discovery -> shortlist -> call runs end to end offline.
"""

from __future__ import annotations

from friday.core.clock import Clock, SystemClock
from friday.core.models import (
    BusinessCandidate,
    BusinessHours,
    GeocodeResult,
    GeoPoint,
)
from friday.discovery.geo import haversine_km, hours_from_simworld, names_match, tokens
from friday.discovery.maps_links import parse_maps_link
from friday.simworld import SimBusiness, SimWorld, load_world

PROVIDER = "simulator"
DEFAULT_RADIUS_KM = 6.0

# a few everyday Indian-English synonyms so "chemist" finds pharmacies etc.
_SYNONYMS: dict[str, set[str]] = {
    "chemist": {"pharmacy"},
    "medical": {"pharmacy"},
    "medicine": {"pharmacy"},
    "doctor": {"clinic"},
    "dentist": {"clinic"},
    "hospital": {"clinic"},
    "parlour": {"salon"},
    "haircut": {"salon"},
    "barber": {"salon"},
    "hotel": {"homestay"},
    "homestay": {"hotel"},
    "stay": {"hotel", "homestay"},
    "plumbing": {"plumber"},
    "aircon": {"ac"},
}


class SimulatedDirectory:
    """``BusinessDirectory`` over simworld. ``search`` returns light records (no
    phone / reviews, like a real text search); ``details`` returns the full record."""

    name = PROVIDER

    def __init__(
        self, world: SimWorld | None = None, *, clock: Clock | None = None, radius_km: float = 6.0
    ) -> None:
        self.world = world or load_world()
        self.clock = clock or SystemClock()
        self.radius_km = radius_km

    # ------------------------------------------------------------------ protocol
    async def search(
        self, query: str, location: str, *, near: GeoPoint | None = None, limit: int = 10
    ) -> list[BusinessCandidate]:
        q = tokens(query)
        loc = tokens(location)
        scored: list[tuple[float, BusinessCandidate]] = []
        for b in self.world.businesses:
            if not self._matches_query(b, query, q):
                continue
            dist = haversine_km(near, GeoPoint(lat=b.lat, lng=b.lng)) if near else None
            if near is not None:
                if dist is None or dist > self.radius_km:
                    continue
            elif loc and not (loc & tokens(f"{b.city} {b.area}")):
                continue
            cand = self._candidate(b, full=False, distance_km=dist)
            sort_key = dist if dist is not None else -(b.rating or 0)
            scored.append((sort_key, cand))
        scored.sort(key=lambda x: x[0])
        return [c for _, c in scored[:limit]]

    async def details(self, place_id: str) -> BusinessCandidate | None:
        b = self.world.by_id(place_id)
        return self._candidate(b, full=True) if b else None

    # ------------------------------------------------------------------ extensions
    async def business_hours(self, place_id: str) -> BusinessHours | None:
        """Opening hours for a listing (B19). Not part of the core Protocol."""
        b = self.world.by_id(place_id)
        if not b or not b.hours:
            return None
        return hours_from_simworld(b.hours)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _matches_query(b: SimBusiness, raw: str, q: set[str]) -> bool:
        if not q:
            return False
        for word in list(q):
            q = q | _SYNONYMS.get(word, set())
        hay = tokens(f"{b.category} {b.name} {b.company or ''}")
        # "ac repair guy" should match category "ac repair"; "salon" matches "Looks Salon"
        if tokens(b.category) and tokens(b.category) <= q:
            return True
        if names_match(raw, b.name):
            return True
        return len(q & hay) >= max(1, min(2, len(q)))

    def _candidate(
        self, b: SimBusiness, *, full: bool, distance_km: float | None = None
    ) -> BusinessCandidate:
        hours = hours_from_simworld(b.hours) if b.hours else None
        open_now = hours.is_open(self.clock.now()) if hours else None
        return BusinessCandidate(
            provider=PROVIDER,
            place_id=b.id,
            name=b.name,
            phone=b.phone if full else None,
            category=b.category,
            address=f"{b.area}, {b.city}",
            location=GeoPoint(lat=b.lat, lng=b.lng),
            distance_km=round(distance_km, 2) if distance_km is not None else None,
            rating=b.rating,
            review_count=b.review_count,
            review_snippets=[r.text for r in b.reviews] if full else [],
            maps_url=f"https://maps.google.com/?q={b.lat},{b.lng}",
            open_now=open_now,
            hours=hours if full else None,
        )


class SimulatedGeocoder:
    """``Geocoder`` over simworld places (+ business areas as a fallback)."""

    name = PROVIDER

    def __init__(self, world: SimWorld | None = None) -> None:
        self.world = world or load_world()

    async def geocode(
        self, text: str, *, near: GeoPoint | None = None, region: str = "in"
    ) -> GeocodeResult | None:
        t = tokens(text)
        if not t:
            return None
        best: tuple[float, GeocodeResult] | None = None
        for p in self.world.places:
            pt = tokens(p.query)
            overlap = len(t & pt) / len(pt) if pt else 0
            if overlap >= 0.5 and (best is None or overlap > best[0]):
                best = (
                    overlap,
                    GeocodeResult(
                        location=GeoPoint(lat=p.lat, lng=p.lng),
                        formatted_address=p.formatted_address,
                        city=p.city,
                        provider_place_id=f"simplace:{p.query}",
                        confidence=round(min(1.0, overlap), 2),
                    ),
                )
        if best:
            return best[1]
        for b in self.world.businesses:  # "Kothrud", "Domlur" ... from business areas
            area = tokens(f"{b.area} {b.city}")
            if tokens(b.area) and tokens(b.area) <= t and area:
                return GeocodeResult(
                    location=GeoPoint(lat=b.lat, lng=b.lng),
                    formatted_address=f"{b.area}, {b.city}",
                    city=b.city,
                    confidence=0.6,
                )
        return None

    async def resolve_maps_link(self, url: str) -> GeocodeResult | None:
        parsed = parse_maps_link(url)
        if parsed is None or parsed.is_short:
            return None  # the simulator cannot expand short links (no network)
        if parsed.point:
            rev = await self.reverse(parsed.point)
            return GeocodeResult(
                location=parsed.point,
                formatted_address=(rev.formatted_address if rev else parsed.query)
                or f"{parsed.point.lat:.5f},{parsed.point.lng:.5f}",
                city=rev.city if rev else None,
                confidence=1.0,
            )
        return await self.geocode(parsed.query or "")

    async def reverse(self, point: GeoPoint) -> GeocodeResult | None:
        best: tuple[float, GeocodeResult] | None = None
        for p in self.world.places:
            d = haversine_km(point, GeoPoint(lat=p.lat, lng=p.lng))
            if d <= DEFAULT_RADIUS_KM and (best is None or d < best[0]):
                best = (
                    d,
                    GeocodeResult(
                        location=point,
                        formatted_address=p.formatted_address,
                        city=p.city,
                        provider_place_id=f"simplace:{p.query}",
                        confidence=round(max(0.3, 1 - d / DEFAULT_RADIUS_KM), 2),
                    ),
                )
        return best[1] if best else None


def build_simulated_directory(c) -> SimulatedDirectory:  # c: Container
    return SimulatedDirectory(clock=c.clock)


def build_simulated_geocoder(c) -> SimulatedGeocoder:  # c: Container
    return SimulatedGeocoder()
