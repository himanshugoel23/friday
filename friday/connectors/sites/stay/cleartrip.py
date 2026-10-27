# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, FlightAdapter, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="cleartrip", name="Cleartrip",
    dialect=Dialect(sel="[data-cy=ct-{d}]", fld="[data-cy=ct-f-{d}]", attr="data-ct-{d}", case="dash"),
    overrides={"pay_qr": "img[data-cy=ct-upi-qr]"},
    paths={
        "home": "/", "login": "/signin",
        "search_hotel": "/hotels/results?q={destination}&from={checkin}&to={checkout}&rooms={rooms}&adults={guests}",
        "detail_hotel": "/hotels/info/{item_id}?q={destination}&from={checkin}&to={checkout}&rooms={rooms}&adults={guests}",
        "search_flight": "/flights/results?origin={origin}&destination={destination}&depart_date={depart}&return_date={return_date}&trip={trip}&adults={adults}",
        "detail_flight": "/flights/itinerary/{item_id}?origin={origin}&destination={destination}&depart_date={depart}&return_date={return_date}&trip={trip}&adults={adults}",
    })


class CleartripFlight(FlightAdapter):
    cfg, key, site, site_name = CFG, "cleartrip.flight", "cleartrip", "Cleartrip"


class CleartripHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "cleartrip.hotel", "cleartrip", "Cleartrip"
