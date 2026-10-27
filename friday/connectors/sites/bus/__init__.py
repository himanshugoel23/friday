"""BUS use case (redBus, AbhiBus) on a scripted private browser, FAKE sites only.

``ADAPTERS``: ``"redbus.bus"``, ``"abhibus.bus"`` (same protocol as FoodAdapter / MovieAdapter).
``FAKE_SITES["redbus.bus"](**knobs)`` returns a browser session on a fake redBus (knobs in
sites/fakes/bus_site.py). Nothing here is cleared for a real site.
"""

from __future__ import annotations

from friday.connectors.sites.bus.abhibus import AbhiBusBus
from friday.connectors.sites.bus.redbus import RedBusBus

ADAPTERS: dict[str, object] = {c.key: c for c in (RedBusBus, AbhiBusBus)}


def _factory(key: str):  # noqa: ANN202 - lazy, so production never imports the test fake
    def make(**knobs):  # noqa: ANN003, ANN202
        from friday.connectors.sites.fakes.bus_site import make_session

        return make_session(key, **knobs)

    return make


FAKE_SITES: dict[str, object] = {key: _factory(key) for key in ADAPTERS}
