"""Ride use case (Uber, Ola, Rapido): scripted browser, FAKE sites only. No payment, ever."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from friday.connectors.sites.ride.reveal import DEFAULT_REVEAL, OneTimeReveal
from friday.connectors.sites.ride.sites import ADAPTERS


def _fake(site: str) -> Callable[..., Any]:
    def factory(**knobs: Any) -> Any:
        from friday.connectors.sites.fakes.ride_site import FakeRideSite  # no import cycle

        return FakeRideSite(site, **knobs)

    return factory


FAKE_SITES: dict[str, Callable[..., Any]] = {k: _fake(k.split(".")[0]) for k in ADAPTERS}

__all__ = ["ADAPTERS", "DEFAULT_REVEAL", "FAKE_SITES", "OneTimeReveal"]
