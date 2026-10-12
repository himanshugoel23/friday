"""Agent 12: ranker. Pure maths; distance is a HARD filter (AGENT_ROSTER distance rule).

Quality = Bayesian-smoothed rating (so 5.0 from 3 votes loses to 4.6 from 800).
Final = weighted sum of quality, genuineness (blended to a neutral prior by confidence),
fit, distance and open-now. Rank 1.. come from inside the DEFAULT radius; widened-radius
places only fill leftover slots, flagged ``beyond_default_radius``.
"""

from __future__ import annotations

from dataclasses import dataclass

from friday.scouting.models import (
    AuthenticityReport,
    DropReason,
    FitScore,
    RankedItem,
    RankedShortlist,
    ScoutPlace,
)

PRIOR_MEAN = 4.2
PRIOR_COUNT = 50
WEIGHTS = {"quality": 0.30, "genuine": 0.25, "fit": 0.25, "distance": 0.15, "open": 0.05}
SUSPICIOUS_BELOW = 0.35  # genuine score under this with medium+ confidence: not shortlisted
_CONF_W = {"low": 0.4, "medium": 0.75, "high": 1.0}
GOOD_ENOUGH = 0.45  # minimum final score to count as "good" for nearest_good


@dataclass
class Scored:
    place: ScoutPlace
    auth: AuthenticityReport | None = None
    fit: FitScore | None = None


def smoothed_rating(rating: float | None, count: int) -> float:
    if rating is None or count <= 0:
        return PRIOR_MEAN - 0.4  # unknown: slightly below the prior
    return (count * rating + PRIOR_COUNT * PRIOR_MEAN) / (count + PRIOR_COUNT)


def _reasons(s: Scored, comps: dict[str, float], dist: float | None) -> list[str]:
    c = s.place.candidate
    out: list[str] = []
    if c.rating:
        out.append(f"{c.rating:g} rating from {c.review_count} reviews")
    if s.auth:
        if s.auth.flags and any(f.penalty > 0 for f in s.auth.flags):
            out.append("review concerns: " + "; ".join(f.detail for f in s.auth.flags if f.penalty))
        elif s.auth.reviews_seen:
            out.append(f"sampled reviews look genuine ({s.auth.confidence} confidence)")
    if s.fit:
        out.extend(s.fit.reasons[:2])
    if dist is not None:
        out.append(f"{dist:.1f} km away")
    if c.open_now is True:
        out.append("open now")
    elif c.open_now is False:
        out.append("closed right now")
    return out


def rank(
    scored: list[Scored],
    *,
    top_n: int,
    radius_km: float,
    default_radius_km: float,
) -> RankedShortlist:
    excluded: list[DropReason] = []
    rows: list[tuple[float, str, RankedItem]] = []
    for s in scored:
        c = s.place.candidate
        dist = c.distance_km
        if dist is not None and dist > radius_km:  # defensive: eligibility already did this
            excluded.append(
                DropReason(
                    place_id=c.place_id,
                    name=c.name,
                    reason="outside_radius",
                    detail=f"{dist:.1f} km > {radius_km:g} km",
                )
            )
            continue
        if s.auth and s.auth.confidence != "low" and s.auth.genuine_score < SUSPICIOUS_BELOW:
            excluded.append(
                DropReason(
                    place_id=c.place_id,
                    name=c.name,
                    reason="suspicious_reviews",
                    detail="; ".join(f.detail for f in s.auth.flags),
                )
            )
            continue
        quality = max(0.0, min(1.0, (smoothed_rating(c.rating, c.review_count) - 3.0) / 2.0))
        if s.auth:
            w = _CONF_W[s.auth.confidence]
            genuine = w * s.auth.genuine_score + (1 - w) * 0.7
        else:
            genuine = 0.7
        fit = s.fit.value if s.fit else 0.5
        distance = 0.5 if dist is None else max(0.0, 1.0 - dist / max(radius_km, 0.1))
        opn = 1.0 if c.open_now is True else (0.0 if c.open_now is False else 0.5)
        comps = {
            "quality": quality,
            "genuine": genuine,
            "fit": fit,
            "distance": distance,
            "open": opn,
        }
        score = sum(WEIGHTS[k] * v for k, v in comps.items())
        beyond = dist is not None and dist > default_radius_km
        flags = [f.code for f in (s.auth.flags if s.auth else []) if f.penalty > 0]
        if beyond:
            flags.append("BEYOND_DEFAULT_RADIUS")
        rows.append(
            (
                score,
                c.place_id,
                RankedItem(
                    rank=0,
                    place=s.place,
                    distance_km=dist,
                    beyond_default_radius=beyond,
                    score=round(score, 4),
                    components={k: round(v, 3) for k, v in comps.items()},
                    reasons=_reasons(s, comps, dist),
                    flags=flags,
                ),
            )
        )
    rows.sort(key=lambda r: (-r[0], r[1]))
    inside = [r[2] for r in rows if not r[2].beyond_default_radius]
    outside = [r[2] for r in rows if r[2].beyond_default_radius]
    chosen = (inside[:top_n] + outside)[:top_n]  # widened places only fill leftover slots
    items = [i.model_copy(update={"rank": n}) for n, i in enumerate(chosen, 1)]
    best_in_range = inside[0].model_copy(update={"rank": 1}) if inside else None
    good = [i for i in inside if i.score >= GOOD_ENOUGH and i.distance_km is not None]
    nearest = min(good, key=lambda i: (i.distance_km, -i.score), default=None)
    return RankedShortlist(
        items=items,
        best_in_range=best_in_range,
        nearest_good=nearest,
        excluded=excluded,
        radius_km=radius_km,
        default_radius_km=default_radius_km,
        widened=radius_km > default_radius_km,
    )
