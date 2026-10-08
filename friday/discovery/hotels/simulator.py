"""Hotel provider simulator over simworld businesses with a ``hotel`` block:

    "hotel": {"rooms": {"deluxe lake view": 4200}, "pay_at_hotel": true, "online_markup_pct": 15}

``rooms`` are the property's DIRECT rates (what the telephony simulator quotes);
online (API) rates are the direct rate + ``online_markup_pct`` so the direct-call
negotiation has something to beat. Deterministic.
"""

from __future__ import annotations

from friday.core.clock import Clock, SystemClock
from friday.core.interfaces import ProviderError
from friday.core.models import (
    GeoPoint,
    GuestDetails,
    HotelBooking,
    HotelBookingMode,
    HotelBookingStatus,
    HotelOffer,
    HotelProperty,
    StayRequest,
)
from friday.discovery.geo import haversine_km, tokens
from friday.simworld import SimBusiness, SimWorld, load_world

PROVIDER = "simulator"
LINK_BASE = "https://sim.friday.local/hotels/book"


class SimulatedHotels:
    name = PROVIDER

    def __init__(
        self,
        world: SimWorld | None = None,
        *,
        clock: Clock | None = None,
        mark_simulated: bool = False,
    ) -> None:
        # Live mode (pilot founder test): simulated rates/bookings say so in plain words.
        self.name_prefix = "[SIMULATED] " if mark_simulated else ""
        self.world = world or load_world()
        self.clock = clock or SystemClock()
        self._bookings: dict[str, HotelBooking] = {}
        self._seq = 0

    def _hotels(self) -> list[SimBusiness]:
        return [b for b in self.world.businesses if b.hotel]

    def _property(self, b: SimBusiness) -> HotelProperty:
        return HotelProperty(
            provider=PROVIDER,
            property_id=b.id,
            name=self.name_prefix + b.name,
            phone=b.phone,
            address=f"{b.area}, {b.city}",
            location=GeoPoint(lat=b.lat, lng=b.lng),
            guest_rating=b.rating,
            review_count=b.review_count,
            review_snippets=[r.text for r in b.reviews],
            amenities=list(b.persona.notes),
            maps_url=f"https://maps.google.com/?q={b.lat},{b.lng}",
        )

    # ------------------------------------------------------------------ protocol
    async def search(self, stay: StayRequest, *, limit: int = 20) -> list[HotelOffer]:
        if stay.nights <= 0:
            raise ProviderError(PROVIDER, "check_out must be after check_in")
        dest = tokens(stay.destination)
        offers: list[tuple[float, HotelOffer]] = []
        for b in self._hotels():
            point = GeoPoint(lat=b.lat, lng=b.lng)
            if stay.near is not None:
                if haversine_km(stay.near, point) > 15:
                    continue
            elif not (dest & tokens(f"{b.city} {b.area} {b.name}")):
                continue
            if stay.property_types and b.category not in stay.property_types:
                continue
            hotel = b.hotel or {}
            markup = 1 + hotel.get("online_markup_pct", 0) / 100
            for room, direct_rate in sorted(hotel.get("rooms", {}).items()):
                rate = int(round(direct_rate * markup))
                if stay.max_rate_per_night_inr and rate > stay.max_rate_per_night_inr * 1.5:
                    continue  # way over budget; direct calls may still find a deal
                pay_at_hotel = bool(hotel.get("pay_at_hotel", False))
                token = f"{b.id}|{room}|{stay.check_in}|{stay.check_out}"
                offers.append(
                    (
                        rate,
                        HotelOffer(
                            property=self._property(b),
                            room_type=room,
                            rate_per_night_inr=rate,
                            total_inr=rate * stay.nights * stay.rooms,
                            pay_at_hotel=pay_at_hotel,
                            refundable=pay_at_hotel,
                            inclusions=[n for n in b.persona.notes if "breakfast" in n.lower()],
                            cancellation_policy=(
                                "Free cancellation until 48h before check-in"
                                if pay_at_hotel
                                else "Non-refundable online rate"
                            ),
                            booking_link=f"{LINK_BASE}/{b.id}?room={room.replace(' ', '+')}"
                            f"&in={stay.check_in}&out={stay.check_out}",
                            offer_token=token,
                        ),
                    )
                )
        offers.sort(key=lambda x: x[0])
        return [o for _, o in offers[:limit]]

    async def property_details(self, property_id: str) -> HotelProperty | None:
        b = self.world.by_id(property_id)
        return self._property(b) if b and b.hotel else None

    async def book(
        self, offer: HotelOffer, stay: StayRequest, guest: GuestDetails, *, mode: HotelBookingMode
    ) -> HotelBooking:
        if mode == HotelBookingMode.DIRECT_HOLD:
            raise ProviderError(PROVIDER, "direct holds are made by phone, not via the API")
        base = dict(
            provider=PROVIDER,
            mode=mode,
            property=offer.property,
            room_type=offer.room_type,
            check_in=stay.check_in,
            check_out=stay.check_out,
            guests=stay.adults + stay.children,
            total_inr=offer.total_inr,
            guest_name=guest.name,
            created_at=self.clock.now(),
        )
        if mode == HotelBookingMode.BOOKING_LINK:
            booking = HotelBooking(
                status=HotelBookingStatus.LINK_SENT, booking_link=offer.booking_link, **base
            )
        else:  # PAY_AT_HOTEL
            if not offer.pay_at_hotel:
                raise ProviderError(PROVIDER, "rate is not pay-at-hotel; send the booking link")
            self._seq += 1
            booking = HotelBooking(
                status=HotelBookingStatus.CONFIRMED,
                confirmation_ref=f"SIMH{self._seq:05d}",
                **base,
            )
        self._bookings[booking.id] = booking
        return booking

    async def cancel(self, booking: HotelBooking) -> HotelBooking:
        if booking.status == HotelBookingStatus.CANCELLED:
            return booking
        out = booking.model_copy(update={"status": HotelBookingStatus.CANCELLED})
        self._bookings[out.id] = out
        return out

    async def modify(self, booking: HotelBooking, stay: StayRequest) -> HotelBooking:
        if booking.status in (HotelBookingStatus.CANCELLED, HotelBookingStatus.FAILED):
            raise ProviderError(PROVIDER, "cannot modify a cancelled booking")
        nightly = (
            booking.total_inr // max(1, (booking.check_out - booking.check_in).days)
            if booking.total_inr
            else None
        )
        out = booking.model_copy(
            update={
                "check_in": stay.check_in,
                "check_out": stay.check_out,
                "guests": stay.adults + stay.children,
                "total_inr": nightly * stay.nights * stay.rooms if nightly else None,
                "status": HotelBookingStatus.MODIFIED,
            }
        )
        self._bookings[out.id] = out
        return out


def build_simulated_hotels(c) -> SimulatedHotels:  # c: Container
    return SimulatedHotels(clock=c.clock, mark_simulated=c.settings.is_live)
