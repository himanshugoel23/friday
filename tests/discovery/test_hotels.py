from datetime import date

import pytest

from friday.core.container import Container
from friday.core.interfaces import HotelProvider, ProviderError
from friday.core.models import GuestDetails, HotelBookingMode, HotelBookingStatus, StayRequest
from friday.discovery.hotels.simulator import SimulatedHotels

STAY = StayRequest(destination="Udaipur", check_in=date(2026, 2, 10), check_out=date(2026, 2, 12))


def test_factory_conformance(settings):
    h = Container(settings).hotels
    assert isinstance(h, HotelProvider) and h.name == "simulator"


async def test_search_online_rates_above_direct():
    h = SimulatedHotels()
    offers = await h.search(STAY)
    assert {o.property.name for o in offers} == {"Lakeview Homestay", "Old City Haveli Inn"}
    lake = next(o for o in offers if o.room_type == "deluxe lake view")
    assert lake.rate_per_night_inr == 4830 and lake.total_inr == 9660  # 4200 + 15%
    assert lake.pay_at_hotel and lake.property.phone == "+912940000010"
    assert offers == sorted(offers, key=lambda o: o.rate_per_night_inr)
    assert await h.search(STAY.model_copy(update={"destination": "Coorg"})) == []
    cheap = await h.search(STAY.model_copy(update={"max_rate_per_night_inr": 2000}))
    assert all(o.rate_per_night_inr <= 3000 for o in cheap)
    with pytest.raises(ProviderError):
        await h.search(STAY.model_copy(update={"check_out": date(2026, 2, 10)}))


async def test_book_modes_cancel_modify():
    h = SimulatedHotels()
    offers = await h.search(STAY)
    lake = next(o for o in offers if o.pay_at_hotel)
    haveli = next(o for o in offers if not o.pay_at_hotel)
    guest = GuestDetails(name="Suresh Verma")
    b = await h.book(lake, STAY, guest, mode=HotelBookingMode.PAY_AT_HOTEL)
    assert b.status == HotelBookingStatus.CONFIRMED and b.confirmation_ref
    link = await h.book(haveli, STAY, guest, mode=HotelBookingMode.BOOKING_LINK)
    assert link.status == HotelBookingStatus.LINK_SENT and link.booking_link
    with pytest.raises(ProviderError):
        await h.book(haveli, STAY, guest, mode=HotelBookingMode.PAY_AT_HOTEL)
    with pytest.raises(ProviderError):
        await h.book(lake, STAY, guest, mode=HotelBookingMode.DIRECT_HOLD)
    longer = STAY.model_copy(update={"check_out": date(2026, 2, 13)})
    m = await h.modify(b, longer)
    assert m.status == HotelBookingStatus.MODIFIED and m.total_inr == b.total_inr // 2 * 3
    c = await h.cancel(m)
    assert c.status == HotelBookingStatus.CANCELLED and (await h.cancel(c)) is c
    with pytest.raises(ProviderError):
        await h.modify(c, STAY)
    assert (await h.property_details("sim-lakeview-homestay")).name == "Lakeview Homestay"
    assert await h.property_details("sim-looks-salon") is None
