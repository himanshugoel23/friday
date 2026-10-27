# ruff: noqa: E501
"""AbhiBus: selectors and quirks only (FAKE site; real site UNVERIFIED)."""

from __future__ import annotations

from friday.connectors.sites.bus.base import BusAdapter, bus_config
from friday.connectors.sites.stay.base import Dialect

CFG = bus_config(
    key="abhibus", name="AbhiBus", hold_s=480,
    dialect=Dialect(sel=".ab-{d}", fld="span.ab-{d}", attr="data-ab-{d}", case="dash"),
    overrides={"result_card": "li.ab-service-row", "review_total": ".ab-payable"},
    paths={"home": "/", "login": "/user/login",
           "search": "/booking/bus-search?src={origin}&dst={destination}&doj={date}",
           "detail": "/booking/seat-layout/{item_id}?src={origin}&dst={destination}&doj={date}"})


class AbhiBusBus(BusAdapter):
    cfg, key, site, site_name = CFG, "abhibus.bus", "abhibus", "AbhiBus"
