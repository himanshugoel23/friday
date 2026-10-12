"""ScoutingVendorFinder: the quotes flow can use friday.scouting (fake Places, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import friday.scouting as scouting_pkg
from friday.core.models import GeoPoint
from friday.quotes.scout_finder import ScoutingVendorFinder

FIX = Path(scouting_pkg.__file__).parent / "fixtures"
POINT = GeoPoint(lat=28.4217, lng=77.1064)


class FakePlaces:
    name = "fake"

    def __init__(self) -> None:
        self.search_raw = json.loads((FIX / "salon_search.json").read_text())
        self.reviews = json.loads((FIX / "salon_reviews.json").read_text())
        self.calls: list[str] = []

    async def _request(self, method, path, fields, *, json=None, params=None):
        self.calls.append(path)
        if path.endswith(":searchText"):
            return self.search_raw
        pid = path.rsplit("/", 1)[-1]
        return self.reviews.get(pid, self.reviews.get("places/" + pid, {"reviews": []}))


class Pool:
    def __init__(self, blocked: set[str]) -> None:
        self.blocked = blocked

    async def is_blocked(self, phone: str) -> bool:
        return phone in self.blocked


async def test_scouting_finder_returns_vendors_within_budget():
    d = FakePlaces()
    f = ScoutingVendorFinder(d, radius_km=5.0, max_calls=8)
    res = await f.find(POINT, where_text="Sector 56 Gurgaon", limit=5)
    assert not res.error and res.vendors
    assert all(v.phone for v in res.vendors)
    assert len({v.place_id for v in res.vendors}) == len(res.vendors)
    assert all((v.distance_km or 0) <= 5.0 for v in res.vendors)
    assert res.calls_used == len(d.calls) <= 8


async def test_scouting_finder_honours_exclude_dnc_and_cap():
    d = FakePlaces()
    first = await ScoutingVendorFinder(d, radius_km=5.0).find(POINT, where_text="x", limit=5)
    top = first.vendors[0]
    f = ScoutingVendorFinder(FakePlaces(), radius_km=5.0, pool=Pool({top.phone}))
    again = await f.find(POINT, where_text="x", limit=5, exclude={first.vendors[1].place_id})
    ids = {v.place_id for v in again.vendors}
    assert top.place_id not in ids and first.vendors[1].place_id not in ids
    capped = await ScoutingVendorFinder(FakePlaces()).find(POINT, where_text="x", max_calls=0)
    assert capped.capped and not capped.vendors


async def test_scouting_failure_is_an_error_not_a_crash():
    class Boom(FakePlaces):
        async def _request(self, *a, **k):
            raise RuntimeError("down")

    res = await ScoutingVendorFinder(Boom()).find(POINT, where_text="x")
    assert res.error and not res.vendors


def test_usable_needs_the_real_directory():
    assert ScoutingVendorFinder.usable(FakePlaces())
    assert not ScoutingVendorFinder.usable(object())
