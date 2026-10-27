# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, FlightAdapter, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="goibibo", name="Goibibo",
    dialect=Dialect(sel=".gi-{d}", fld=".gi-{d}", attr="data-gi-{d}", case="dash"),
    overrides={"review_total": ".gi-grand-total", "reserve_button": "button.gi-book-room"},
    paths={
        "home": "/", "login": "/accounts/login",
        "search_hotel": "/hotels/results/?dest={destination}&ci={checkin}&co={checkout}&rms={rooms}&gst={guests}",
        "detail_hotel": "/hotels/property/{item_id}/?dest={destination}&ci={checkin}&co={checkout}&rms={rooms}&gst={guests}",
        "search_flight": "/flight/results/?src={origin}&dst={destination}&dep={depart}&ret={return_date}&type={trip}&adt={adults}",
        "detail_flight": "/flight/offer/{item_id}/?src={origin}&dst={destination}&dep={depart}&ret={return_date}&type={trip}&adt={adults}",
    })


class GoibiboHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "goibibo.hotel", "goibibo", "Goibibo"


class GoibiboFlight(FlightAdapter):
    cfg, key, site, site_name = CFG, "goibibo.flight", "goibibo", "Goibibo"
