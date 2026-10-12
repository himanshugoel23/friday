"""Agent 11: fit scorer. Rules over the evidence from agent 10; no LLM."""

from __future__ import annotations

from friday.scouting.categories import Category, match_services
from friday.scouting.models import FitScore, ScoutPlace, ScoutRequest, ServiceEvidence

_MEN_ONLY = ("gents", "men's", "mens", "barber")
_WOMEN_ONLY = ("ladies", "women", "bridal", "beauty parlour", "beauty parlor")
_UNISEX = ("unisex",)


def score_fit(
    place: ScoutPlace, evidence: ServiceEvidence, req: ScoutRequest, category: Category
) -> FitScore:
    c = place.candidate
    wanted = match_services(category, req.services)
    confirmed_set = evidence.services()
    confirmed = [w for w in wanted if w in confirmed_set]
    missing = [w for w in wanted if w not in confirmed_set]
    reasons: list[str] = []
    parts: list[tuple[float, float]] = []  # (weight, value)

    if wanted:
        # confirmed by a verified review quote = 1; unknown = 0.4 (absence of evidence is
        # weak because only <=5 reviews are visible)
        cov = (len(confirmed) + 0.4 * len(missing)) / len(wanted)
        parts.append((0.6, cov))
        if confirmed:
            reasons.append("reviews mention " + ", ".join(w.replace("_", " ") for w in confirmed))
        if missing:
            reasons.append(
                "no review evidence for " + ", ".join(w.replace("_", " ") for w in missing)
            )
    neg = sum(1 for k in evidence.claims if k.kind == "theme_negative")
    pos = sum(1 for k in evidence.claims if k.kind == "theme_positive")
    parts.append((0.2, max(0.0, min(1.0, 0.6 + 0.1 * (pos - 2 * neg)))))
    if neg:
        reasons.append(f"{neg} complaint theme(s) in reviews")

    name = c.name.lower()
    if req.gender_pref:
        if req.gender_pref == "women" and any(t in name for t in _MEN_ONLY):
            g, note = 0.0, "name suggests men-only"
        elif req.gender_pref == "men" and any(t in name for t in _WOMEN_ONLY):
            g, note = 0.0, "name suggests women-only"
        elif any(t in name for t in _UNISEX):
            g, note = 1.0, "unisex"
        else:
            g, note = 0.6, ""
        parts.append((0.1, g))
        if note:
            reasons.append(note)
    if req.budget_inr is not None and c.price_level is not None:
        v = 1.0 if c.price_level <= 2 else 0.4
        parts.append((0.1, v))
        if v < 1:
            reasons.append("listed as higher priced")
    if req.home_visit:
        home = any("home" in k.quote.lower() or "ghar" in k.quote.lower() for k in evidence.claims)
        parts.append((0.1, 1.0 if home else 0.3))
        reasons.append("home service mentioned" if home else "home service not confirmed")

    total_w = sum(w for w, _ in parts)
    value = sum(w * v for w, v in parts) / total_w if total_w else 0.5
    return FitScore(
        place_id=c.place_id,
        value=round(value, 3),
        reasons=reasons,
        services_confirmed=confirmed,
        services_missing=missing,
    )
