"""The three ride adapters: base behaviour + a profile each (selectors and quirks: profiles.py).

Uber (auto / bike / cab / premium), Ola (the same four, its own names), Rapido (auto / bike / cab,
no premium: asking for one is a clean 'no match'). Web booking on the real sites is UNVERIFIED.
"""

from __future__ import annotations

from friday.connectors.sites.ride.base import RideAdapter
from friday.connectors.sites.ride.profiles import PROFILES


def _make(site: str) -> type[RideAdapter]:
    prof = PROFILES[site]
    return type(f"{prof.name}RideAdapter", (RideAdapter,), {
        "key": f"{site}.ride", "site": site, "site_name": prof.name, "profile": prof})


UberAdapter = _make("uber")
OlaAdapter = _make("ola")
RapidoAdapter = _make("rapido")

ADAPTERS: dict[str, object] = {"uber.ride": UberAdapter, "ola.ride": OlaAdapter,
                               "rapido.ride": RapidoAdapter}
