"""Scenario knobs on top of the existing fake food site (friday/connectors/fake_site).

Adds what the agents need to be tested: sold-out items, a price rise after the user approved,
a delivery-address line, a page banner (prompt injection), a block page, and renamed selectors
(layout change). The base class and its sim session stay untouched.
"""

from __future__ import annotations

from friday.connectors.fake_site.catalog import FakeSiteState, format_rupees
from friday.connectors.fake_site.sim_session import SimBrowserSession
from friday.connectors.food.zomato import SELECTORS as ZOMATO_SELECTORS

EXTRA_SELECTORS = {
    "page_body": "body",
    "sold_out": "[data-testid=sold-out]",
    "delivery_address": "[data-testid=delivery-address]",
}


class ScenarioFoodState(FakeSiteState):
    def __init__(self, *, sold_out: set[str] | None = None, price_bump_pct: int = 0,
                 address: str = "Flat 4, Sector 12", banner: str = "", **kw) -> None:  # noqa: ANN003
        super().__init__(**kw)
        self.sold_out, self.price_bump_pct = set(sold_out or ()), price_bump_pct
        self.address, self.banner = address, banner
        self._bumped = False

    def add(self, sid: str, rid: str, item_id: str, qty: int) -> None:
        if item_id in self.sold_out:
            return
        if self.price_bump_pct and not self._bumped:  # the price rises once the user has approved
            self._bumped = True
            for menu in self.menus.values():
                for m in menu:
                    m["price"] = m["price"] * (100 + self.price_bump_pct) // 100
        super().add(sid, rid, item_id, qty)


class ScenarioFoodSession(SimBrowserSession):
    """Sim session with the extras. ``renamed`` swaps selector strings (a changed layout)."""

    def __init__(self, state: ScenarioFoodState, renamed: dict[str, str] | None = None) -> None:
        sel = {**ZOMATO_SELECTORS, **EXTRA_SELECTORS, **(renamed or {})}
        super().__init__(state, selectors=sel)

    def _present(self, key: str) -> list[dict[str, str]]:
        st: ScenarioFoodState = self.state  # type: ignore[assignment]
        kind, arg = self.page
        if key == "page_body":
            if st.block == "captcha":
                return [{"text": "Please verify you are a human. Captcha"}]
            parts = [f"page {kind}", st.banner]
            return [{"text": "\n".join(p for p in parts if p)}]
        if key == "sold_out":
            if kind == "restaurant":
                return [{"item_id": i, "text": "Sold out"} for i in sorted(st.sold_out)]
            return []
        if key == "delivery_address":
            return [{"text": st.address}] if kind == "cart" and self._s.logged_in else []
        if key == "menu_item_add" and kind == "restaurant":
            pass
        return super()._present(key)

    def _key(self, selector: str) -> tuple[str, str]:
        key, arg = super()._key(selector)
        return key, arg


__all__ = ["ScenarioFoodSession", "ScenarioFoodState", "format_rupees", "EXTRA_SELECTORS"]
