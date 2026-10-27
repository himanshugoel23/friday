# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="booking", name="Booking.com",
    dialect=Dialect(sel="[data-ba={d}]", fld="[data-ba={d}]", attr="data-ba-{d}", case="camel"),
    overrides={"result_card": "[data-ba=propertyCard]", "guest_name_input": "input[name=booker_name]"},
    paths={
        "home": "/index.html", "login": "/signin.html",
        "search_hotel": "/searchresults.html?ss={destination}&checkin={checkin}&checkout={checkout}&no_rooms={rooms}&group_adults={guests}&selected_currency=INR",
        "detail_hotel": "/hotel/in/{item_id}.html?ss={destination}&checkin={checkin}&checkout={checkout}&no_rooms={rooms}&group_adults={guests}&selected_currency=INR",
    })


class BookingHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "booking.hotel", "booking", "Booking.com"
