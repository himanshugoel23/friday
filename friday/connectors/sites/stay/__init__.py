"""STAY use cases (hotel + flight) on a scripted private browser, FAKE sites only.

``ADAPTERS`` is keyed ``"<catalog site key>.<use case>"`` (same protocol as FoodAdapter /
MovieAdapter). ``FAKE_SITES`` maps the same keys to fake-site factories for tests and the simulator:
``FAKE_SITES["agoda.hotel"](**knobs)`` returns a browser session on a fake Agoda (see
sites/fakes/stay_site.py for the knobs). Nothing here is cleared for a real site.
"""

from __future__ import annotations

from friday.connectors.sites.stay.agoda import AgodaHotel
from friday.connectors.sites.stay.booking import BookingHotel
from friday.connectors.sites.stay.cleartrip import CleartripFlight, CleartripHotel
from friday.connectors.sites.stay.goibibo import GoibiboFlight, GoibiboHotel
from friday.connectors.sites.stay.makemytrip import MakeMyTripFlight, MakeMyTripHotel
from friday.connectors.sites.stay.oyo import OyoHotel

ADAPTERS: dict[str, object] = {c.key: c for c in (
    MakeMyTripHotel, MakeMyTripFlight, GoibiboHotel, GoibiboFlight, BookingHotel, AgodaHotel,
    OyoHotel, CleartripFlight, CleartripHotel)}


def _factory(key: str):  # noqa: ANN202 - lazy, so production never imports the test fake
    def make(**knobs):  # noqa: ANN003, ANN202
        from friday.connectors.sites.fakes.stay_site import make_session

        return make_session(key, **knobs)

    return make


FAKE_SITES: dict[str, object] = {key: _factory(key) for key in ADAPTERS}
