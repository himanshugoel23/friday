# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="agoda", name="Agoda",
    dialect=Dialect(sel="[data-selenium={d}]", fld="[data-selenium={d}]", attr="data-ag-{d}", case="snake"),
    overrides={"account_name": "#ag_user_name", "review_total": "[data-selenium=grand_total_amount]"},
    paths={
        "home": "/", "login": "/account/signin.html",
        "search_hotel": "/search?textToSearch={destination}&checkIn={checkin}&checkOut={checkout}&rooms={rooms}&adults={guests}",
        "detail_hotel": "/hotel-room/{item_id}?textToSearch={destination}&checkIn={checkin}&checkOut={checkout}&rooms={rooms}&adults={guests}",
    })


class AgodaHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "agoda.hotel", "agoda", "Agoda"
