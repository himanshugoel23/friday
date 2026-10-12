"""Wiring: agents 6-12 in order. Fetches reviews only for the best pre-ranked few (cost)."""

from __future__ import annotations

import asyncio

from friday.scouting.authenticity import TextPatternJudge, judge_authenticity
from friday.scouting.categories import effective_radius_km, get_category
from friday.scouting.eligibility import filter_eligible
from friday.scouting.evidence import EvidenceLLM, KeywordEvidenceLLM, extract_evidence
from friday.scouting.fit import score_fit
from friday.scouting.models import ScoutRequest, ScoutResult
from friday.scouting.ranker import Scored, rank
from friday.scouting.reviews import ReviewFetcher
from friday.scouting.searcher import PlaceSearcher


async def scout(
    req: ScoutRequest,
    searcher: PlaceSearcher,
    fetcher: ReviewFetcher,
    *,
    evidence_llm: EvidenceLLM | None = None,
    text_judge: TextPatternJudge | None = None,
    review_budget: int = 8,
    max_queries: int = 3,
) -> ScoutResult:
    cat = get_category(req.category)
    radius = effective_radius_km(cat, req.radius_km)  # caller may widen, capped at hard max
    search = await searcher.search(req, max_queries=max_queries)
    elig = filter_eligible(search, cat, radius_km=radius)
    # cheap pre-rank (no reviews) to choose who is worth a review fetch
    pre = rank(
        [Scored(p) for p in elig.eligible],
        top_n=review_budget,
        radius_km=radius,
        default_radius_km=cat.default_radius_km,
    ).items
    # keep widened-radius candidates reachable but spend the budget on the best first
    ids = {i.place.candidate.place_id for i in pre}
    chosen = [p for p in elig.eligible if p.candidate.place_id in ids]
    llm = evidence_llm or KeywordEvidenceLLM(cat)

    async def one(p):
        c = p.candidate
        pr = await fetcher.fetch(c.place_id)
        auth = await judge_authenticity(
            pr, c.name, rating=c.rating, review_count=c.review_count, text_judge=text_judge
        )
        ev = await extract_evidence(pr, cat, llm, c.name)
        return Scored(p, auth, score_fit(p, ev, req, cat))

    scored = list(await asyncio.gather(*(one(p) for p in chosen)))
    shortlist = rank(
        scored, top_n=req.top_n, radius_km=radius, default_radius_km=cat.default_radius_km
    )
    return ScoutResult(
        request=req,
        search=search,
        eligibility=elig,
        shortlist=shortlist,
        reviews_fetched_for=len(chosen),
    )
