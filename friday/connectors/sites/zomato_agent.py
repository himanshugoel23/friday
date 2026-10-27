# ruff: noqa: E501
"""Zomato food connector for the agent flow: the existing connector plus what the flow needs.

Subclass only (food/zomato.py and its tests are untouched). Adds: sold-out check before anything is
added, the delivery address shown on the cart, a callback when the site is waiting for the login
code (so the flow can send the secure-page link), selector alternates and the safety wiring.
All selectors target the FAKE site; real Zomato is UNVERIFIED.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from friday.connectors.browser.port import BrowserSession
from friday.connectors.contract import Cart, ItemQty
from friday.connectors.fake_site.catalog import format_rupees  # noqa: F401
from friday.connectors.food.zomato import FIELDS, SELECTORS, ZomatoFoodConnector, _safe_id
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import SiteSafety
from friday.connectors.sites.verifier import Expect, Verifier

ALLOWED_HOSTS = frozenset({"zomato.com", "fake.invalid", "127.0.0.1", "localhost"})
EXTRA = {
    "sold_out": "[data-testid=sold-out]",
    "delivery_address": "[data-testid=delivery-address]",
}
# Fallbacks tried when the primary selector finds nothing (cheap, reviewed, no model involved).
ALTERNATES = {
    "checkout_button": ["[data-testid=go-to-pay]", "button.checkout"],
    "send_otp_button": ["[data-testid=get-otp]"],
    "clear_cart": ["[data-testid=empty-cart]"],
}
IRREVERSIBLE = frozenset({"checkout_button"})


def build_kit(inner: BrowserSession, *, task_id: str, repairer: SelectorRepairer | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    safety = SiteSafety(ALLOWED_HOSTS | extra_hosts, IRREVERSIBLE)
    log = RepairLog()
    locator = ElementLocator({**SELECTORS, **EXTRA}, ALTERNATES, repairer=repairer, log=log,
                             task_id=task_id, irreversible=IRREVERSIBLE)
    verifier = Verifier({
        SELECTORS["checkout_button"]: Expect(present=(SELECTORS["pay_amount"],)),
        SELECTORS["send_otp_button"]: Expect(present=(SELECTORS["otp_input"],)),
    })
    for alt in ALTERNATES["checkout_button"]:
        verifier.expectations[alt] = Expect(present=(SELECTORS["pay_amount"],))
    gs = GuardedSession(inner, safety, locator, PageReader(), verifier)
    return AgentKit(gs, safety, locator, log)


class AgentZomatoConnector(ZomatoFoodConnector):
    def __init__(self, session: BrowserSession, *, on_code_wait: Callable[[], Awaitable[None]]
                 | None = None, **kw) -> None:  # noqa: ANN003
        super().__init__(session, **kw)
        self._on_code_wait = on_code_wait
        self._announced = False

    async def _wait_for_code(self) -> str:
        if self._on_code_wait and not self._announced:
            self._announced = True
            await self._on_code_wait()
        return await super()._wait_for_code()

    async def sold_out_ids(self, restaurant_id: str) -> set[str]:
        await self._goto("restaurant", restaurant_id=_safe_id(restaurant_id, "restaurant id"))
        rows = await self._s.query_all(EXTRA["sold_out"], {"item_id": "@data-item-id"})
        return {r.get("item_id", "") for r in rows}

    async def build_cart(self, restaurant_id: str, items: list[ItemQty]) -> Cart:
        await self.ensure_logged_in()
        gone = await self.sold_out_ids(restaurant_id)
        hit = [i.item_id for i in items if i.item_id in gone]
        if hit:
            raise OutOfStock("an item is sold out", hit)
        return await super().build_cart(restaurant_id, items)

    async def delivery_address(self) -> str | None:
        await self._goto("cart")
        rows = await self._s.query_all(EXTRA["delivery_address"])
        return rows[0]["text"] if rows else None


__all__ = ["AgentZomatoConnector", "AgentKit", "build_kit", "FIELDS", "format_rupees"]
