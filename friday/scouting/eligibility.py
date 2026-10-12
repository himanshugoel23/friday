"""Agent 7: eligibility filter. Pure rules; every drop has a reason."""

from __future__ import annotations

from friday.discovery.geo import haversine_km, is_toll_free, names_match, phone_key
from friday.scouting.categories import Category
from friday.scouting.models import DropReason, EligibilityResult, ScoutPlace, SearchResult

_DUP_DISTANCE_KM = 0.15


def _type_ok(place: ScoutPlace, category: Category) -> bool:
    """True when type info is absent (cannot judge) or overlaps the expected types."""
    got = set(place.types)
    if place.candidate.category:
        got.add(place.candidate.category)
    if not got:
        return True
    return bool(got & set(category.expected_types))


def filter_eligible(
    result: SearchResult,
    category: Category,
    *,
    radius_km: float,
    require_phone: bool = True,
    require_expected_type: bool = True,
) -> EligibilityResult:
    eligible: list[ScoutPlace] = []
    dropped: list[DropReason] = []

    def drop(p: ScoutPlace, reason, detail: str = "") -> None:
        dropped.append(
            DropReason(
                place_id=p.candidate.place_id, name=p.candidate.name, reason=reason, detail=detail
            )
        )

    # strongest listing first, so a duplicate drops the weaker one
    ordered = sorted(
        result.places, key=lambda p: (-p.candidate.review_count, p.candidate.place_id)
    )
    for p in ordered:
        c = p.candidate
        if p.business_status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            drop(p, "closed", p.business_status)
            continue
        if require_phone and not c.phone:
            drop(p, "no_phone")
            continue
        if c.phone and is_toll_free(c.phone):
            drop(p, "toll_free_number", "central call-centre line, not the outlet")
            continue
        if require_expected_type and not _type_ok(p, category):
            drop(p, "wrong_type", ",".join(p.types[:4]) or str(c.category))
            continue
        dist = c.distance_km
        if dist is None and result.near and c.location:
            dist = haversine_km(result.near, c.location)
        if dist is not None and dist > radius_km:
            drop(p, "outside_radius", f"{dist:.1f} km > {radius_km:g} km")
            continue
        dup = next((e for e in eligible if _is_duplicate(e, p)), None)
        if dup:
            drop(p, "duplicate", f"same as {dup.candidate.name}")
            continue
        eligible.append(p)
    return EligibilityResult(eligible=eligible, dropped=dropped)


def _is_duplicate(a: ScoutPlace, b: ScoutPlace) -> bool:
    ca, cb = a.candidate, b.candidate
    if ca.phone and cb.phone and phone_key(ca.phone) == phone_key(cb.phone):
        return True
    if ca.location and cb.location and names_match(ca.name, cb.name):
        return haversine_km(ca.location, cb.location) <= _DUP_DISTANCE_KM
    return False
