# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, FlightAdapter, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="makemytrip", name="MakeMyTrip",
    dialect=Dialect(sel="[data-testid={d}]", fld="[data-testid={d}]", attr="data-{d}", case="dash"),
    overrides={"result_card": "[data-testid=listing-card]", "reserve_button": "[data-testid=book-room-cta]"},
    paths={
        "home": "/", "login": "/login",
        "search_hotel": "/hotels/search?city={destination}&checkin={checkin}&checkout={checkout}&roomCount={rooms}&guests={guests}",
        "detail_hotel": "/hotels/detail/{item_id}?city={destination}&checkin={checkin}&checkout={checkout}&roomCount={rooms}&guests={guests}",
        "search_flight": "/flights/search?from={origin}&to={destination}&depart={depart}&return={return_date}&tripType={trip}&pax={adults}",
        "detail_flight": "/flights/fare/{item_id}?from={origin}&to={destination}&depart={depart}&return={return_date}&tripType={trip}&pax={adults}",
    })


class MakeMyTripHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "makemytrip.hotel", "makemytrip", "MakeMyTrip"


class MakeMyTripFlight(FlightAdapter):
    cfg, key, site, site_name = CFG, "makemytrip.flight", "makemytrip", "MakeMyTrip"
