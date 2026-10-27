"""Grocery use case (Zepto, Blinkit, BigBasket, Instamart): scripted browser, FAKE sites only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from friday.connectors.sites.grocery.sites import ADAPTERS


def _fake(site: str) -> Callable[..., Any]:
    def factory(**knobs: Any) -> Any:
        from friday.connectors.sites.fakes.grocery_site import FakeGrocerySite  # no import cycle

        return FakeGrocerySite(site, **knobs)

    return factory


FAKE_SITES: dict[str, Callable[..., Any]] = {k: _fake(k.split(".")[0]) for k in ADAPTERS}

__all__ = ["ADAPTERS", "FAKE_SITES"]
