# ruff: noqa: E501
"""Understanding the request and finding vendors (no chat, no calls)."""

from __future__ import annotations

from datetime import datetime

from friday.core.clock import IST
from friday.core.models import GeoPoint
from friday.quotes import parse as P
from friday.quotes.finder import VendorFinder, score
from tests.quotes.conftest import FakeDirectory, cand

NOW = datetime(2026, 10, 12, 11, 0, tzinfo=IST)
POINT = GeoPoint(lat=28.4244, lng=77.1068)


def test_hinglish_request_is_understood():
    p = P.parse_request("kal shaam parlour mein haircut karwana hai, quotes chahiye", NOW)
    assert p.services == ["haircut"] and p.when_text == "kal shaam" and not p.exact_time
    assert p.lang == "hinglish" and p.for_name is None and p.location_text is None


def test_english_request_with_everything():
    p = P.parse_request(
        "Need a haircut and beard trim tomorrow 6pm near Sector 56 Gurgaon under 600", NOW
    )
    assert p.services == ["haircut", "beard trim"] and p.exact_time
    assert p.when_text == "kal shaam 6 baje" and p.budget_inr == 600
    assert p.location_text == "Sector 56 Gurgaon" and p.city == "gurgaon" and p.lang == "en"


def test_for_someone_else_and_devanagari():
    assert P.parse_request("Rahul ke liye haircut kal 5 baje", NOW).for_name == "Rahul"
    assert P.parse_request("kisi aur ke liye haircut chahiye", NOW).for_other_unnamed
    p = P.parse_request("कल शाम पार्लर में हेयरकट चाहिए", NOW)
    assert p.lang == "hi" and p.services == ["haircut"]


def test_other_city_and_named_business_are_not_taken():
    assert P.parse_request("haircut in Pune tomorrow", NOW).other_city
    assert not P.looks_like_request("Looks Unisex Salon mein haircut book karo kal shaam")
    assert not P.looks_like_request("call +919876543210 for a haircut")
    assert P.looks_like_request("Parlour mein haircut chahiye")


def test_explicit_book_needs_the_word_not_the_quote_ask():
    assert P.parse_request("book kar do haircut kal 6 baje 500 tak", NOW).book_intent
    assert not P.parse_request("book a parlour, give me quotes for haircut", NOW).book_intent


def test_city_only_is_too_wide():
    assert P.city_only("Gurgaon") and not P.city_only("Sector 56 Gurgaon")


async def test_finder_filters_ranks_dedupes_and_skips_dnc():
    items = [
        cand(1, "Glow", rating=4.5, reviews=640, dist=0.8),
        cand(2, "Low Rated", rating=3.2, reviews=900, dist=0.5),
        cand(3, "Far Away", rating=4.9, reviews=900, dist=9.0),
        cand(4, "No Phone", phone=False),
        cand(5, "Glow", rating=4.5, reviews=640, dist=0.8),
        cand(6, "Unrated New", rating=None, reviews=0, dist=1.0),
        cand(7, "Blocked", rating=4.8, reviews=500, dist=1.0),
        cand(8, "Same Phone", rating=4.4, reviews=100, dist=1.0),
    ]
    # a second listing of the same shop: same name, same spot, other id and number
    items[4] = items[0].model_copy(update={"place_id": "dup", "phone": "+911245009999"})
    items[7] = items[7].model_copy(update={"phone": items[0].phone})

    class Pool:
        async def is_blocked(self, phone):
            return phone == items[6].phone

    d = FakeDirectory(items)
    res = await VendorFinder(d, pool=Pool()).find(POINT, where_text="x")
    names = [v.name for v in res.vendors]
    assert names == ["Glow", "Unrated New"]
    assert "Low Rated" not in names and "Far Away" not in names and "Blocked" not in names


def test_ranking_uses_rating_reviews_and_distance_and_open_time():
    near_ok = cand(1, "A", rating=4.4, reviews=300, dist=0.5)
    far_ok = cand(2, "B", rating=4.4, reviews=300, dist=4.5)
    many = cand(3, "C", rating=4.4, reviews=3000, dist=0.5)
    assert score(many, None) > score(near_ok, None) > score(far_ok, None)
    closed = near_ok.model_copy(update={"open_now": False})
    assert score(closed, None) < score(near_ok, None)


async def test_finder_looks_up_missing_phones_and_caps_directory_calls():
    items = [cand(i, f"S{i}", phone=False, reviews=100 + i) for i in range(1, 7)]
    items = [c.model_copy() for c in items]
    d = FakeDirectory(items)
    # details() returns the same record without a phone: nobody qualifies, and the spend stops
    res = await VendorFinder(d, max_calls=4).find(POINT, where_text="x")
    assert res.vendors == [] and res.capped
    assert d.searches + d.details_calls <= 4


async def test_finder_cache_avoids_second_search():
    from friday.core.scale import MemoryCache

    d = FakeDirectory([cand(1, "Glow")])
    f = VendorFinder(d, cache=MemoryCache())
    await f.find(POINT, where_text="x")
    n = d.searches
    again = await f.find(POINT, where_text="x")
    assert d.searches == n and [v.name for v in again.vendors] == ["Glow"]
