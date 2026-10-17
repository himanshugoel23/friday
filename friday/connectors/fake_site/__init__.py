"""A FAKE food-delivery site for tests and offline demos. It imitates page structure only (stable
data-testid attributes); every name, price, phone and code in it is invented. It is not Zomato."""

from __future__ import annotations

from friday.connectors.fake_site.catalog import FakeSiteState
from friday.connectors.fake_site.server import FakeSiteServer
from friday.connectors.fake_site.sim_session import SimBrowserSession

__all__ = ["FakeSiteServer", "FakeSiteState", "SimBrowserSession"]
