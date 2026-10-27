# ruff: noqa: E501
"""Swiggy food connector: the Zomato agent connector (sites/zomato_agent.py, untouched) plus the one
thing Swiggy needs that Zomato's did not: pre-selected extras (a membership trial, a tip) are
UNTICKED, and a ``AddOnStuck`` is raised when one cannot be removed.

!! Selectors are the Zomato fake's twin plus two add-on selectors. The real Swiggy is UNVERIFIED:
!! markup, login, challenge pages and checkout must be recorded and tuned first. Real tuning
!! touches the dicts of food/zomato.py (shared by design) and SWIGGY_EXTRA here.
"""

from __future__ import annotations

from typing import Any

from friday.connectors.browser.port import BrowserSession
from friday.connectors.contract import Cart, Menu, Restaurant
from friday.connectors.food.zomato import SELECTORS
from friday.connectors.sites.executor import AgentKit
from friday.connectors.sites.train.common import AddOnStuck, build_kit, clean, safe_id
from friday.connectors.sites.zomato_agent import (
    ALTERNATES,
    EXTRA,
    IRREVERSIBLE,
    AgentZomatoConnector,
)

SWIGGY_EXTRA = {
    "addon_row": "[data-testid=addon-row]",
    "addon_toggle": "[data-testid=addon-toggle-{addon_id}]",
}
ADDON_FIELDS = {"addon_id": "@data-addon-id", "label": "[data-testid=addon-label]",
                "amount": "[data-testid=addon-amount]", "checked": "@data-checked"}
ALL_SELECTORS = {**SELECTORS, **EXTRA, **SWIGGY_EXTRA}
EXPECT = {"checkout_button": ("pay_amount",), "send_otp_button": ("otp_input",)}


def make_kit(session: BrowserSession, *, task_id: str, repairer: Any = None) -> AgentKit:
    """Same guarded session as Zomato's, but the allow-list is Swiggy's own (from the catalog)."""
    return build_kit(session, site_key="swiggy", selectors=ALL_SELECTORS, alternates=ALTERNATES,
                     irreversible=IRREVERSIBLE, task_id=task_id, repairer=repairer, expect=EXPECT)


class SwiggyConnector(AgentZomatoConnector):
    site = "swiggy"

    def __init__(self, session: BrowserSession, **kw: Any) -> None:
        super().__init__(session, **kw)
        self.unticked: list[str] = []

    def __repr__(self) -> str:
        return f"SwiggyConnector(task_id={self._task_id!r})"

    async def _addons(self) -> list[dict[str, str]]:
        return await self._s.query_all(SWIGGY_EXTRA["addon_row"], ADDON_FIELDS)

    async def _untick_addons(self) -> list[str]:
        """Untick every pre-ticked extra on the cart page; return the labels that stayed ticked."""
        for r in await self._addons():
            if r.get("checked", "").lower() == "true":
                await self._s.click(SWIGGY_EXTRA["addon_toggle"].format(addon_id=safe_id(r.get("addon_id", ""), "extra")))
                self.unticked.append(clean(r.get("label", ""), 60))
        return [clean(r.get("label", ""), 60) for r in await self._addons() if r.get("checked", "").lower() == "true"]

    async def _read_cart(self, restaurant_id: str) -> Cart:
        stuck = await self._untick_addons()
        cart = await super()._read_cart(restaurant_id)
        cart = cart.model_copy(update={"lines": [ln.model_copy(update={"name": clean(ln.name, 80)})
                                                 for ln in cart.lines]})
        if stuck:
            raise AddOnStuck(stuck, 0, cart)
        return cart

    # Page text is untrusted data: names shown to the user pass the injection guard first.
    async def search_restaurants(self, query: str, area: str) -> list[Restaurant]:
        found = await super().search_restaurants(query, area)
        return [r.model_copy(update={"name": clean(r.name, 80) or "restaurant"}) for r in found]

    async def get_menu(self, restaurant_id: str) -> Menu:
        menu = await super().get_menu(restaurant_id)
        return menu.model_copy(update={"items": [i.model_copy(update={"name": clean(i.name, 80) or "item"})
                                                 for i in menu.items]})
