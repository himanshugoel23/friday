from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.interfaces import BusinessDirectory, Geocoder
from friday.core.models import GeoPoint
from friday.discovery.simulator import SimulatedDirectory, SimulatedGeocoder

INDIRANAGAR = GeoPoint(lat=12.9719, lng=77.6412)


@pytest.fixture
def directory() -> SimulatedDirectory:
    return SimulatedDirectory(clock=FakeClock(datetime(2026, 1, 5, 11, 0, tzinfo=IST)))


def test_protocol_conformance(settings: Settings):
    c = Container(settings)
    assert isinstance(c.directory, BusinessDirectory)
    assert isinstance(c.geocoder, Geocoder)
    assert c.directory.name == "simulator"


async def test_search_near_point_sorted_by_distance(directory):
    res = await directory.search("AC repair guy", "Indiranagar", near=INDIRANAGAR)
    names = [r.name for r in res]
    assert names[0] == "CoolCare AC Services"
    assert set(names) == {"CoolCare AC Services", "Frosty Air Solutions", "Chill Point AC Repair"}
    assert all(r.phone is None and r.distance_km is not None for r in res)  # light records
    assert res == sorted(res, key=lambda r: r.distance_km)


async def test_search_by_location_text_and_synonyms(directory):
    res = await directory.search("chemist", "Kothrud, Pune")
    assert {r.name for r in res} == {"Wellness Pharmacy Kothrud", "City Chemist"}
    assert await directory.search("chemist", "Udaipur") == []


async def test_details_full_record_and_hours(directory):
    d = await directory.details("sim-looks-salon")
    assert d.phone == "+918040000001" and d.review_snippets and d.open_now is True
    hours = await directory.business_hours("sim-sharma-clinic")
    assert len(hours.periods) == 11  # mon-fri split + sat morning
    assert await directory.details("nope") is None
    assert await directory.business_hours("sim-cool-ac") is None


async def test_geocoder_forward_reverse_and_links():
    g = SimulatedGeocoder()
    r = await g.geocode("near Kothrud, Pune")
    assert r and r.city == "Pune"
    assert (await g.geocode("Domlur")).city == "Bengaluru"  # business-area fallback
    assert await g.geocode("Atlantis") is None
    rev = await g.reverse(GeoPoint(lat=12.972, lng=77.641))
    assert rev.city == "Bengaluru" and rev.location.lat == 12.972
    link = await g.resolve_maps_link("https://www.google.com/maps/place/Looks/@12.9719,77.6412,17z")
    assert link.city == "Bengaluru"
    q = await g.resolve_maps_link("https://www.google.com/maps/search/?api=1&query=udaipur")
    assert q.city == "Udaipur"
    assert await g.resolve_maps_link("https://maps.app.goo.gl/abc") is None
