"""`friday scout` and `friday scout-report`. Live Google when the key env var exists,
otherwise recorded fixtures (scout) / skip (scout-report). The key is never printed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from friday.scouting.categories import CATEGORIES, effective_radius_km, get_category
from friday.scouting.eligibility import _type_ok
from friday.scouting.models import ScoutRequest, ScoutResult
from friday.scouting.pipeline import scout
from friday.scouting.reviews import FixtureReviewFetcher, GoogleReviewFetcher
from friday.scouting.searcher import (
    FixturePlaceSearcher,
    GeocoderAreaResolver,
    GooglePlaceSearcher,
)

DEFAULT_AREAS = ["Sector 56 Gurgaon", "Indiranagar Bangalore"]


def _key(settings) -> str | None:
    k = getattr(settings, "google_places_api_key", None)
    return k.get_secret_value() if k else None


def format_result(res: ScoutResult) -> str:
    sl = res.shortlist
    lines = [
        f"Scout: {res.request.category} near {res.request.area} "
        f"[{res.search.source}] radius {sl.radius_km:g} km (default {sl.default_radius_km:g})"
        + (" WIDENED" if sl.widened else ""),
        f"  candidates {len(res.search.places)}, eligible {len(res.eligibility.eligible)}, "
        f"dropped {len(res.eligibility.dropped)}, reviews read for {res.reviews_fetched_for}",
    ]
    if not sl.items:
        lines.append("  No vendor passed the filters.")
    for it in sl.items:
        c = it.place.candidate
        far = "  [beyond default radius: ask the user first]" if it.beyond_default_radius else ""
        d = f"{it.distance_km:.1f} km" if it.distance_km is not None else "distance unknown"
        lines.append(f"  #{it.rank} {c.name} ({d}, score {it.score:.2f}){far}")
        for r in it.reasons:
            lines.append(f"      - {r}")
    if (
        sl.nearest_good
        and sl.best_in_range
        and (sl.nearest_good.place.candidate.place_id != sl.best_in_range.place.candidate.place_id)
    ):
        n = sl.nearest_good
        lines.append(
            f"  Nearest good: {n.place.candidate.name} ({n.distance_km:.1f} km); "
            f"best in range: {sl.best_in_range.place.candidate.name}"
        )
    for d in res.eligibility.dropped + sl.excluded:
        lines.append(f"  dropped {d.name}: {d.reason} {d.detail}".rstrip())
    return "\n".join(lines)


def run_scout(args, settings) -> int:
    try:
        cat = get_category(args.category)
    except KeyError as e:
        print(e)
        return 2
    services = [s.strip() for s in (args.services or "").split(",") if s.strip()]
    req = ScoutRequest(
        category=cat.key,
        area=args.area,
        services=services,
        radius_km=args.radius_km,
        top_n=args.top,
        gender_pref=args.gender,
        budget_inr=args.budget,
        home_visit=args.home_visit,
    )
    key = None if args.fixtures else _key(settings)

    async def go() -> ScoutResult:
        if not key:
            return await scout(req, FixturePlaceSearcher(), FixtureReviewFetcher())
        from friday.discovery.google_geocoder import GoogleGeocoder
        from friday.discovery.google_places import GooglePlacesDirectory

        d, g = GooglePlacesDirectory(key), GoogleGeocoder(key)
        try:
            return await scout(
                req, GooglePlaceSearcher(d, GeocoderAreaResolver(g)), GoogleReviewFetcher(d)
            )
        finally:
            await d.aclose()
            await g.aclose()

    if not key:
        print("(no Google key: using recorded fixtures; results are synthetic)")
    print(format_result(asyncio.run(go())))
    return 0


@dataclass
class CategoryStats:
    category: str
    total: int = 0
    phone: int = 0
    hours: int = 0
    typed: int = 0
    reviews: int = 0
    calls: int = 0
    error: str = field(default="")

    def pct(self, n: int) -> str:
        return f"{100 * n / self.total:.0f}%" if self.total else "-"

    def row(self) -> str:
        avg = f"{self.reviews / self.total:.0f}" if self.total else "-"
        return (
            f"{self.category:<20}{self.total:>6}{self.pct(self.phone):>8}"
            f"{self.pct(self.hours):>8}{self.pct(self.typed):>8}{avg:>9}{self.calls:>7}"
            + (f"  ERR {self.error}" if self.error else "")
        )


def run_scout_report(args, settings) -> int:
    key = _key(settings)
    if not key:
        print(
            "No Google Places key in the environment: skipping live measurement "
            "(nothing was called). Set GOOGLE_PLACES_API_KEY and run again."
        )
        return 0
    cats = (
        list(CATEGORIES)
        if args.categories == "all"
        else [c.strip() for c in args.categories.split(",") if c.strip()]
    )
    areas = [a.strip() for a in (args.areas or ";".join(DEFAULT_AREAS)).split(";") if a.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        print(f"unknown categories: {', '.join(unknown)}")
        return 2
    max_q = max(1, args.max_queries)

    async def go() -> list[CategoryStats]:
        from friday.discovery.google_geocoder import GoogleGeocoder
        from friday.discovery.google_places import GooglePlacesDirectory

        d, g = GooglePlacesDirectory(key), GoogleGeocoder(key)
        searcher = GooglePlaceSearcher(d, GeocoderAreaResolver(g), page_size=20)
        out = []
        try:
            for ck in cats:
                cat, st = CATEGORIES[ck], CategoryStats(ck)
                for area in areas:
                    req = ScoutRequest(
                        category=ck, area=area, radius_km=effective_radius_km(cat, None)
                    )
                    try:
                        res = await searcher.search(req, max_queries=max_q)
                    except Exception as e:  # report and keep going
                        st.error = type(e).__name__
                        continue
                    st.calls += len(res.queries)
                    for p in res.places:
                        c = p.candidate
                        st.total += 1
                        st.phone += bool(c.phone)
                        st.hours += bool(c.hours and c.hours.periods)
                        st.typed += _type_ok(p, cat) and bool(p.types or c.category)
                        st.reviews += c.review_count
                out.append(st)
        finally:
            await d.aclose()
            await g.aclose()
        return out

    stats = asyncio.run(go())
    print(f"Areas: {'; '.join(areas)} | up to {max_q} queries per category per area")
    print(
        f"{'category':<20}{'places':>6}{'phone':>8}{'hours':>8}{'type':>8}"
        f"{'avg rev':>9}{'calls':>7}"
    )
    for s in stats:
        print(s.row())
    return 0
