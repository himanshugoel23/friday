"""Scouting package tests: recorded fixtures and fakes only, no network."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from friday.core.models import BusinessCandidate, GeoPoint
from friday.scouting import cli as scout_cli
from friday.scouting.authenticity import TextFlag, judge_authenticity, judge_rules
from friday.scouting.categories import (
    CATEGORIES,
    build_queries,
    effective_radius_km,
    match_services,
)
from friday.scouting.eligibility import filter_eligible
from friday.scouting.evidence import KeywordEvidenceLLM, extract_evidence
from friday.scouting.fit import score_fit
from friday.scouting.models import (
    PlaceReviews,
    Review,
    ScoutPlace,
    ScoutRequest,
    SearchResult,
    ServiceEvidence,
)
from friday.scouting.pipeline import scout
from friday.scouting.ranker import Scored, rank, smoothed_rating
from friday.scouting.reviews import FixtureReviewFetcher, parse_reviews
from friday.scouting.searcher import FixturePlaceSearcher

SALON = CATEGORIES["salon"]
T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)


def rv(i, text, rating=5, days=0, hours=0, count=None):
    return Review(
        review_id=i,
        text=text,
        rating=rating,
        published_at=T0 - timedelta(days=days) + timedelta(hours=hours),
        author_review_count=count,
    )


def place(
    pid="p1",
    name="Test Salon",
    km=1.0,
    rating=4.5,
    n=200,
    phone="+919810012345",
    types=("beauty_salon",),
    open_now=True,
    lat=28.42,
    status=None,
):
    return ScoutPlace(
        candidate=BusinessCandidate(
            provider="google_places",
            place_id=pid,
            name=name,
            phone=phone,
            rating=rating,
            review_count=n,
            distance_km=km,
            open_now=open_now,
            location=GeoPoint(lat=lat, lng=77.1),
        ),
        types=list(types),
        business_status=status,
    )


# ------------------------------------------------------------------ categories
def test_category_table_complete():
    assert len(CATEGORIES) == 20
    for c in CATEGORIES.values():
        assert c.queries and c.expected_types and c.services
        assert 0 < c.default_radius_km <= c.max_radius_km


def test_radii_from_doc():
    assert (CATEGORIES["salon"].default_radius_km, CATEGORIES["salon"].max_radius_km) == (5, 10)
    assert CATEGORIES["clinic"].max_radius_km == 15
    assert CATEGORIES["packers_movers"].default_radius_km == 20
    assert CATEGORIES["pest_control"].max_radius_km == 20


def test_match_services_prefers_specific_term():
    assert match_services(SALON, ["beard trim", "haircut", "head massage", "zzz"]) == [
        "beard",
        "haircut",
        "massage",
        "zzz",
    ]
    assert build_queries(SALON, "x", max_queries=2) == SALON.queries[:2]


def test_effective_radius_capped():
    assert effective_radius_km(SALON, None) == 5
    assert effective_radius_km(SALON, 8) == 8
    assert effective_radius_km(SALON, 100) == 10


# ------------------------------------------------------------------ searcher + eligibility
async def test_fixture_searcher_parses_google_shape():
    res = await FixturePlaceSearcher().search(ScoutRequest(category="salon", area="x"))
    assert len(res.places) == 10 and res.source == "fixtures"
    good = next(p for p in res.places if p.candidate.place_id == "pGood1")
    assert good.candidate.phone == "+919810011111" and "hair_salon" in good.types
    assert good.candidate.hours is not None and 0.5 < good.candidate.distance_km < 1.2


async def test_eligibility_reasons():
    res = await FixturePlaceSearcher().search(ScoutRequest(category="salon", area="x"))
    el = filter_eligible(res, SALON, radius_km=5)
    reasons = {d.place_id: d.reason for d in el.dropped}
    assert reasons == {
        "pFar": "outside_radius",
        "pWrong": "wrong_type",
        "pClosed": "closed",
        "pMid": "outside_radius",
        "pNoPhone": "no_phone",
        "pDup": "duplicate",
    }
    assert {p.candidate.place_id for p in el.eligible} == {"pGood1", "pGood2", "pFake", "pFew"}


async def test_widening_within_max_only():
    res = await FixturePlaceSearcher().search(ScoutRequest(category="salon", area="x"))

    def ids(r):
        return {p.candidate.place_id for p in filter_eligible(res, SALON, radius_km=r).eligible}

    assert "pMid" not in ids(5)
    assert "pMid" in ids(effective_radius_km(SALON, 8))
    wide = ids(effective_radius_km(SALON, 500))  # capped at 10
    assert "pMid" in wide and "pFar" not in wide


def test_unrelated_names_not_duplicates():
    a = place("a", "Kashish Luxury Unisex Salon", km=0.5)
    b = place("b", "The Kaaya Unisex Salon", km=0.5, phone="+919810099999")
    el = filter_eligible(SearchResult(places=[a, b]), SALON, radius_km=5)
    assert len(el.eligible) == 2


# ------------------------------------------------------------------ reviews
def test_parse_reviews_google_shape():
    raw = {
        "reviews": [
            {
                "name": "places/x/reviews/abc",
                "rating": 4,
                "text": {"text": " Nice haircut "},
                "publishTime": "2026-09-02T10:00:00Z",
                "authorAttribution": {"displayName": "R"},
            },
            {"name": "n", "text": {}},
        ]
    }
    pr = parse_reviews("x", raw)
    assert [r.review_id for r in pr.reviews] == ["abc"] and pr.reviews[0].text == "Nice haircut"
    assert pr.reviews[0].author_review_count is None


# ------------------------------------------------------------------ authenticity
async def test_fake_vs_genuine_fixture_sets():
    f = FixtureReviewFetcher()
    genuine = judge_rules(await f.fetch("pGood1"), rating=4.6, review_count=812)
    fake = judge_rules(await f.fetch("pFake"), rating=5.0, review_count=42)
    assert genuine.genuine_score >= 0.9 and not genuine.flags
    assert fake.genuine_score <= 0.35
    assert {"REVIEW_BURST", "SHORT_GENERIC_PRAISE", "RATING_ODDITY"} <= {x.code for x in fake.flags}


def test_duplicate_text_detected():
    revs = [
        rv("a", "Amazing bridal makeup and hair, best parlour in gurgaon go now"),
        rv("b", "Amazing bridal makeup and hair, best parlour in gurgaon go now!"),
        rv("c", "Quite fine haircut, price was ok and parking was hard to find", days=40),
    ]
    r = judge_rules(PlaceReviews(place_id="p", reviews=revs))
    assert any(f.code == "DUPLICATE_TEXT" and set(f.review_ids) == {"a", "b"} for f in r.flags)


def test_burst_needs_dates_and_density():
    spread = [
        rv(str(i), f"Visit number {i} was decent with a proper haircut", days=30 * i)
        for i in range(5)
    ]
    assert not [
        f
        for f in judge_rules(PlaceReviews(place_id="p", reviews=spread)).flags
        if f.code == "REVIEW_BURST"
    ]
    burst = [
        rv(str(i), f"Visit number {i} was decent with a proper haircut", hours=i) for i in range(5)
    ]
    assert any(
        f.code == "REVIEW_BURST"
        for f in judge_rules(PlaceReviews(place_id="p", reviews=burst)).flags
    )


def test_low_history_reviewers_only_when_known():
    revs = [
        rv(
            str(i),
            [
                "Stylist trimmed evenly and the bill matched the quote",
                "Parking was awful but the facial itself felt relaxing",
                "Waited twenty minutes yet the colour came out lovely",
                "Clean chairs, polite staff, wax done quickly",
            ][i],
            days=20 * i,
            count=1,
        )
        for i in range(4)
    ]
    assert any(
        f.code == "LOW_HISTORY_REVIEWERS"
        for f in judge_rules(PlaceReviews(place_id="p", reviews=revs)).flags
    )
    unknown = [r.model_copy(update={"author_review_count": None}) for r in revs]
    assert not judge_rules(PlaceReviews(place_id="p", reviews=unknown)).flags


def test_no_reviews_is_neutral_low_confidence():
    r = judge_rules(PlaceReviews(place_id="p"))
    assert r.genuine_score == 0.5 and r.confidence == "low" and r.flags[0].code == "NO_REVIEWS"


class FakeTextJudge:
    def __init__(self, flags):
        self.flags = flags

    async def judge(self, place_name, reviews):
        return self.flags


async def test_llm_hook_flags_verified_ids_only():
    pr = PlaceReviews(place_id="p", reviews=[rv("a", "Long honest review about the haircut I got")])
    base = await judge_authenticity(pr)
    out = await judge_authenticity(
        pr,
        text_judge=FakeTextJudge(
            [
                TextFlag(code="TEMPLATE_TEXT", review_ids=["a"], detail="template"),
                TextFlag(code="PROMOTIONAL", review_ids=["ghost"]),
            ]
        ),
    )
    assert out.llm_used and [f.code for f in out.flags] == ["LLM_TEMPLATE_TEXT"]
    assert out.genuine_score < base.genuine_score


async def test_llm_failure_keeps_rules_verdict():
    class Boom:
        async def judge(self, *a):
            raise RuntimeError("down")

    pr = PlaceReviews(place_id="p", reviews=[rv("a", "Long honest review about the haircut I got")])
    assert not (await judge_authenticity(pr, text_judge=Boom())).llm_used


# ------------------------------------------------------------------ evidence
class FakeLLM:
    def __init__(self, payloads):
        self.payloads, self.calls = list(payloads), 0

    async def extract(self, *a):
        self.calls += 1
        return self.payloads.pop(0)


def _claim(**kw):
    base = {
        "kind": "service_offered",
        "label": "haircut",
        "quote": "great haircut",
        "review_id": "a",
        "amount_inr": None,
    }
    return {**base, **kw}


PR = PlaceReviews(place_id="p", reviews=[rv("a", "Got a Great  haircut here, paid Rs 450 only")])


async def test_every_claim_needs_real_quote_and_id():
    llm = FakeLLM(
        [
            {
                "claims": [
                    _claim(),  # ok (case and whitespace squashed)
                    _claim(quote="amazing beard work"),  # quote not in review
                    _claim(review_id="zzz"),  # unknown review id
                    _claim(label="teleportation"),  # outside closed vocabulary
                    _claim(kind="price_hint", label="price", quote="paid Rs 450", amount_inr=450),
                    _claim(kind="price_hint", label="price", quote="paid Rs 450", amount_inr=999),
                ]
            }
        ]
    )
    ev = await extract_evidence(PR, SALON, llm)
    assert [(c.kind, c.label) for c in ev.claims] == [
        ("service_offered", "haircut"),
        ("price_hint", "price"),
    ]
    assert ev.dropped_claims == 4 and ev.services() == {"haircut"}


async def test_bad_json_retries_once_then_unsure():
    llm = FakeLLM(["not json", {"claims": [{"kind": "bogus"}]}])
    ev = await extract_evidence(PR, SALON, llm)
    assert ev.status == "unsure" and llm.calls == 2 and not ev.claims
    llm2 = FakeLLM(["garbage", '{"claims": []}'])
    assert (await extract_evidence(PR, SALON, llm2)).status == "ok"


async def test_extra_fields_rejected_by_closed_schema():
    llm = FakeLLM([{"claims": [], "note": "hi"}, {"claims": [], "note": "hi"}])
    assert (await extract_evidence(PR, SALON, llm)).status == "unsure"


async def test_keyword_extractor_quotes_are_verified():
    pr = await FixtureReviewFetcher().fetch("pGood1")
    ev = await extract_evidence(pr, SALON, KeywordEvidenceLLM(SALON))
    assert ev.dropped_claims == 0 and {"haircut", "beard", "facial"} <= ev.services()
    assert any(c.kind == "price_hint" and c.amount_inr == 450 for c in ev.claims)
    assert any(c.kind == "theme_positive" and c.label == "cleanliness" for c in ev.claims)


# ------------------------------------------------------------------ fit
async def test_fit_prefers_confirmed_services():
    pr = await FixtureReviewFetcher().fetch("pGood1")
    ev = await extract_evidence(pr, SALON, KeywordEvidenceLLM(SALON))
    req = ScoutRequest(category="salon", area="x", services=["haircut", "keratin"])
    fit = score_fit(place("pGood1"), ev, req, SALON)
    assert fit.services_confirmed == ["haircut"] and fit.services_missing == ["hair_treatment"]
    none = score_fit(place("q"), ServiceEvidence(place_id="q"), req, SALON)
    assert none.value < fit.value


def test_fit_gender_mismatch():
    req = ScoutRequest(category="salon", area="x", gender_pref="women")
    ev = ServiceEvidence(place_id="q")
    assert (
        score_fit(place(name="Gents Salon"), ev, req, SALON).value
        < score_fit(place(name="Unisex Salon"), ev, req, SALON).value
    )


# ------------------------------------------------------------------ ranker
def test_bayesian_smoothing_penalises_tiny_samples():
    assert smoothed_rating(5.0, 3) < smoothed_rating(4.6, 800)
    out = rank(
        [Scored(place("a", rating=5.0, n=3)), Scored(place("b", rating=4.6, n=800))],
        top_n=2,
        radius_km=5,
        default_radius_km=5,
    )
    assert [i.place.candidate.place_id for i in out.items] == ["b", "a"]


def test_far_five_star_never_ranks():
    out = rank(
        [Scored(place("far", km=100, rating=5.0, n=5000)), Scored(place("near", rating=3.8))],
        top_n=3,
        radius_km=10,
        default_radius_km=5,
    )
    assert [i.place.candidate.place_id for i in out.items] == ["near"]
    assert out.excluded[0].reason == "outside_radius"


def test_widened_places_never_beat_in_range_and_are_flagged():
    out = rank(
        [
            Scored(place("in", km=3, rating=3.9, n=60)),
            Scored(place("wide", km=8, rating=4.9, n=3000)),
        ],
        top_n=2,
        radius_km=10,
        default_radius_km=5,
    )
    assert [i.place.candidate.place_id for i in out.items] == ["in", "wide"]
    assert out.items[1].beyond_default_radius and "BEYOND_DEFAULT_RADIUS" in out.items[1].flags
    assert out.widened and out.best_in_range.place.candidate.place_id == "in"
    assert out.items[0].distance_km == 3 and not out.items[0].beyond_default_radius


def test_nearest_good_differs_from_best():
    out = rank(
        [
            Scored(place("close", km=0.4, rating=4.1, n=80)),
            Scored(place("best", km=4.0, rating=4.9, n=1500)),
        ],
        top_n=2,
        radius_km=5,
        default_radius_km=5,
    )
    assert out.best_in_range.place.candidate.place_id == "best"
    assert out.nearest_good.place.candidate.place_id == "close"


async def test_pipeline_end_to_end_fixtures():
    req = ScoutRequest(category="salon", area="Sector 56 Gurgaon", services=["haircut"], top_n=3)
    res = await scout(req, FixturePlaceSearcher(), FixtureReviewFetcher())
    names = [i.place.candidate.name for i in res.shortlist.items]
    assert names[0] == "Looks Unisex Salon" and "Glow Queen Parlour" not in names
    assert any(
        d.place_id == "pFake" and d.reason == "suspicious_reviews" for d in res.shortlist.excluded
    )
    assert all(i.distance_km is not None for i in res.shortlist.items)
    assert "pFar" not in {i.place.candidate.place_id for i in res.shortlist.items}


async def test_pipeline_widening_capped():
    base = dict(category="salon", area="x", services=["haircut"], top_n=5)
    wide = await scout(
        ScoutRequest(**base, radius_km=8), FixturePlaceSearcher(), FixtureReviewFetcher()
    )
    ids = [i.place.candidate.place_id for i in wide.shortlist.items]
    assert "pMid" in ids and ids[-1] == "pMid" and wide.shortlist.widened
    huge = await scout(
        ScoutRequest(**base, radius_km=1000), FixturePlaceSearcher(), FixtureReviewFetcher()
    )
    assert huge.shortlist.radius_km == 10
    assert "pFar" not in {i.place.candidate.place_id for i in huge.shortlist.items}


# ------------------------------------------------------------------ CLI
def test_scout_cli_fixtures(capsys):
    args = argparse.Namespace(
        category="salon",
        area="Sector 56 Gurgaon",
        services="haircut",
        top=3,
        radius_km=None,
        gender=None,
        budget=None,
        home_visit=False,
        fixtures=True,
    )
    assert scout_cli.run_scout(args, SimpleNamespace(google_places_api_key=None)) == 0
    out = capsys.readouterr().out
    assert "Looks Unisex Salon" in out and "km away" in out and "suspicious_reviews" in out


def test_scout_report_skips_without_key(capsys):
    args = argparse.Namespace(categories="all", areas=None, max_queries=2)
    assert scout_cli.run_scout_report(args, SimpleNamespace(google_places_api_key=None)) == 0
    assert "skipping" in capsys.readouterr().out


def test_unknown_category_refused(capsys):
    args = argparse.Namespace(
        category="nope",
        area="x",
        services="",
        top=3,
        radius_km=None,
        gender=None,
        budget=None,
        home_visit=False,
        fixtures=True,
    )
    assert scout_cli.run_scout(args, SimpleNamespace(google_places_api_key=None)) == 2


@pytest.mark.parametrize("cat", list(CATEGORIES))
def test_every_category_has_service_terms_lowercase(cat):
    for syn in CATEGORIES[cat].services.values():
        assert all(s == s.lower() for s in syn)
