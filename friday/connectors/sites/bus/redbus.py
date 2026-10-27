# ruff: noqa: E501
"""redBus: selectors and quirks only (FAKE site; real site UNVERIFIED)."""

from __future__ import annotations

from friday.connectors.sites.bus.base import BusAdapter, bus_config
from friday.connectors.sites.stay.base import Dialect

CFG = bus_config(
    key="redbus", name="redBus", hold_s=600,
    dialect=Dialect(sel="[data-rb={d}]", fld="[data-rb={d}]", attr="data-rb-{d}", case="snake"),
    overrides={"hold_button": "button#rb-block-seat", "review_total": "[data-rb=payable_amount]"},
    paths={"home": "/", "login": "/signin",
           "search": "/search?fromCityName={origin}&toCityName={destination}&onward={date}",
           "detail": "/bus-tickets/{item_id}?fromCityName={origin}&toCityName={destination}&onward={date}"})


class RedBusBus(BusAdapter):
    cfg, key, site, site_name = CFG, "redbus.bus", "redbus", "redBus"
