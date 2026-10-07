import hashlib
from datetime import UTC, date, datetime

import httpx
import pytest

from friday.core.clock import FakeClock
from friday.core.interfaces import HotelProvider, ProviderError
from friday.core.models import GeoPoint, GuestDetails, HotelBookingMode, StayRequest
from friday.discovery.hotels.expedia import ExpediaRapid, rapid_auth_header, rapid_signature

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
STAY = StayRequest(
    destination="Udaipur",
    near=GeoPoint(lat=24.58, lng=73.71),
    check_in=date(2026, 2, 10),
    check_out=date(2026, 2, 12),
)
CONTENT = {
    "111": {
        "name": "Lakeview Homestay",
        "phone": "0294-4000010",
        "address": {"line_1": "Lake Pichola", "city": "Udaipur"},
        "location": {"coordinates": {"latitude": 24.5764, "longitude": 73.68}},
        "ratings": {"property": {"rating": "3.0"}, "guest": {"overall": "4.8", "count": 210}},
        "amenities": {"1": {"name": "Free WiFi"}},
    }
}
AVAIL = [
    {
        "property_id": "111",
        "rooms": [
            {
                "room_name": "Deluxe Lake View",
                "rates": [
                    {
                        "id": "rate-1",
                        "refundable": True,
                        "merchant_of_record": "property",
                        "amenities": {"2": {"name": "Breakfast"}},
                        "occupancy_pricing": {
                            "2": {
                                "totals": {
                                    "inclusive": {
                                        "request_currency": {"value": "9660.00", "currency": "INR"}
                                    }
                                }
                            }
                        },
                    }
                ],
            }
        ],
        "links": {
            "additional_rates": {
                "href": "https://test.ean.com/v3/properties/111/availability?token=x"
            }
        },
    }
]


def client(seen):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if path.endswith("/regions"):
            return httpx.Response(200, json=[{"id": "r1", "property_ids": ["111"]}])
        if path.endswith("/properties/availability"):
            return httpx.Response(200, json=AVAIL)
        if path.endswith("/properties/content"):
            return httpx.Response(200, json=CONTENT)
        return httpx.Response(500)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_signature():
    sig = rapid_signature("k", "s", 1700000000)
    assert sig == hashlib.sha512(b"ks1700000000").hexdigest()
    assert (
        rapid_auth_header("k", "s", 1700000000)
        == f"EAN APIKey=k,Signature={sig},timestamp=1700000000"
    )


async def test_search_and_details_wired():
    seen: list[httpx.Request] = []
    x = ExpediaRapid("k", "s", client=client(seen), clock=FakeClock(NOW))
    assert isinstance(x, HotelProvider)
    offers = await x.search(STAY)
    assert len(offers) == 1
    o = offers[0]
    assert o.total_inr == 9660 and o.rate_per_night_inr == 4830 and o.pay_at_hotel
    assert o.property.phone == "+9102944000010" or o.property.phone.endswith("2944000010")
    assert o.property.guest_rating == 4.8 and o.inclusions == ["Breakfast"]
    auth = seen[0].headers["Authorization"]
    assert (
        auth.startswith("EAN APIKey=k,Signature=") and f"timestamp={int(NOW.timestamp())}" in auth
    )
    avail = next(r for r in seen if r.url.path.endswith("availability"))
    assert avail.url.params["currency"] == "INR" and avail.url.params["property_id"] == "111"


async def test_search_requires_geocoded_destination_and_book_disabled():
    x = ExpediaRapid("k", "s", client=client([]), clock=FakeClock(NOW))
    with pytest.raises(ProviderError):
        await x.search(STAY.model_copy(update={"near": None}))
    offers = await x.search(STAY)
    for call in (
        x.book(offers[0], STAY, GuestDetails(name="A"), mode=HotelBookingMode.PAY_AT_HOTEL),
    ):
        with pytest.raises(ProviderError, match="not enabled"):
            await call
    assert await x.property_details("999") is None
