"""The four grocery adapters: base behaviour + a profile each (selectors and quirks: profiles.py).

Zepto, Blinkit, Instamart: instant delivery (about 10-15 minutes), the ETA is read from the page.
BigBasket: scheduled delivery, a slot is chosen after approval (slot fee included in the cap).
Zepto / Blinkit add a small-cart fee under the minimum; BigBasket / Instamart refuse a small cart.
Blinkit-style sites switch "replace if unavailable" on by themselves: the base turns it off.
"""

from __future__ import annotations

from friday.connectors.sites.grocery.base import GroceryAdapter
from friday.connectors.sites.grocery.profiles import PROFILES


def _make(site: str) -> type[GroceryAdapter]:
    prof = PROFILES[site]
    return type(f"{prof.name.replace(' ', '')}GroceryAdapter", (GroceryAdapter,), {
        "key": f"{site}.grocery", "site": site, "site_name": prof.name, "profile": prof})


ZeptoAdapter = _make("zepto")
BlinkitAdapter = _make("blinkit")
BigBasketAdapter = _make("bigbasket")
InstamartAdapter = _make("instamart")

ADAPTERS: dict[str, object] = {
    "zepto.grocery": ZeptoAdapter, "blinkit.grocery": BlinkitAdapter,
    "bigbasket.grocery": BigBasketAdapter, "instamart.grocery": InstamartAdapter,
}
