# ruff: noqa: E501
"""SITE: selectors and quirks only; the flow lives in stay/base.py. FAKE-site selectors, real site UNVERIFIED."""

from __future__ import annotations

from friday.connectors.sites.stay.base import Dialect, HotelAdapter, SiteConfig

CFG = SiteConfig(
    key="oyo", name="OYO",
    dialect=Dialect(sel="[class~=oyo-{d}]", fld="span.o-{d}", attr="data-oyo-{d}", case="dash"),
    overrides={"phone_input": "input#oyo-mobile", "send_otp_button": "button#oyo-get-otp"},
    paths={
        "home": "/", "login": "/login-oyo",
        "search_hotel": "/hotels-in-city/?location={destination}&checkin={checkin}&checkout={checkout}&roomConfig={rooms}&guests={guests}",
        "detail_hotel": "/rooms/{item_id}/?location={destination}&checkin={checkin}&checkout={checkout}&roomConfig={rooms}&guests={guests}",
    })


class OyoHotel(HotelAdapter):
    cfg, key, site, site_name = CFG, "oyo.hotel", "oyo", "OYO"
