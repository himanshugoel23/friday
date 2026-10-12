"""Agent 7: eligibility filter. Pure rules; every drop has a reason."""

from __future__ import annotations

import re

from friday.discovery.geo import haversine_km, is_toll_free, phone_key
from friday.scouting.categories import Category
from friday.scouting.models import DropReason, EligibilityResult, ScoutPlace, SearchResult

_DUP_DISTANCE_KM = 0.15
_GENERIC_NAME_WORDS = {
    "salon",
    "saloon",
    "unisex",
    "beauty",
    "parlour",
    "parlor",
    "studio",
    "spa",
    "hair",
    "and",
    "the",
    "for",
    "him",
    "her",
    "sector",
    "sec",
    "gurgaon",
    "gurugram",
    "bangalore",
    "bengaluru",
    "luxury",
    "family",
    "pvt",
    "ltd",
    "in",
    "at",
    "makeup",
    "clinic",
    "new",
}


def _name_core(name: str) -> set[str]:
    toks = re.findall(r"[a-z]+", name.lower())  # digits dropped: sector numbers are not identity
    return {t for t in toks if t not in _GENERIC_NAME_WORDS}


def _same_name(a: str, b: str) -> bool:
    ta, tb = _name_core(a), _name_core(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.6


def _type_ok(place: ScoutPlace, category: Category) -> bool:
    """True when type info is absent (cannot judge) or overlaps the expected types."""
    got = set(place.types)
    if place.candidate.category:
        got.add(place.candidate.category)
    if not got:
        return True
    if got & set(category.expected_types):
        return True
    name = place.candidate.name.lower()
    return any(k in f" {name} " for k in category.name_keywords)


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
    ordered = sorted(result.places, key=lambda p: (-p.candidate.review_count, p.candidate.place_id))
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
    if ca.location and cb.location and _same_name(ca.name, cb.name):
        return haversine_km(ca.location, cb.location) <= _DUP_DISTANCE_KM
    return False
