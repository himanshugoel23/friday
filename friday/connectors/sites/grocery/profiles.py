# ruff: noqa: E501
"""Per-site data for the grocery adapters: selectors, alternates, paths and fee rules.

!! Every selector targets the FAKE grocery site (sites/fakes/grocery_site.py). Real Zepto, Blinkit,
!! BigBasket and Instamart markup is UNVERIFIED: record the real pages first; real tuning touches
!! only this file. The selector maps differ per site on purpose, so a mix-up between sites fails.
Fee numbers are placeholders the fake also uses; the adapter always trusts the cart page, never
these, for the final total (they only size the approval cap).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.connectors.catalog import policy_hosts

KEYS = (
    "account_name", "store_closed", "address_badge", "eta_badge", "product_card", "add_button",
    "subs_toggle", "cart_line", "fee_row", "tax_row", "cart_total", "cart_address", "cart_eta",
    "slot_option", "slot_pick", "checkout_button", "pay_amount", "pay_merchant", "pay_order_ref",
    "pay_qr", "pay_upi_link", "order_state", "banner",
)
IRREVERSIBLE = frozenset({"checkout_button"})  # "place order": armed only after approval


@dataclass(frozen=True)
class SiteProfile:
    key: str
    name: str
    kind: str  # "instant" (10-minute) | "scheduled" (delivery slots)
    selectors: dict[str, str]
    fields: dict[str, dict[str, str]]
    alternates: dict[str, list[str]]
    paths: dict[str, str]
    min_cart_paise: int
    hard_min: bool  # True: the site refuses a cart below the minimum; False: it adds a small-cart fee
    delivery_fee_paise: int
    free_delivery_above_paise: int
    handling_fee_paise: int = 0
    small_cart_fee_paise: int = 0
    default_eta: str = ""
    subs_default_on: bool = False  # quirk: the site turns "replace if unavailable" on by itself
    extra_hosts: frozenset[str] = field(default_factory=lambda: frozenset(
        {"fake.invalid", "127.0.0.1", "localhost"}))

    def hosts(self) -> frozenset[str]:
        real = {h.removeprefix("*.") for h in policy_hosts(self.key)}
        return frozenset(real) | self.extra_hosts

    def fees_for(self, subtotal: int, slot_fee: int = 0) -> int:
        """Fees the site is expected to charge for a cart of this size (sizes the approval cap)."""
        fee = 0 if subtotal >= self.free_delivery_above_paise else self.delivery_fee_paise
        fee += self.handling_fee_paise + slot_fee
        if not self.hard_min and subtotal < self.min_cart_paise:
            fee += self.small_cart_fee_paise
        return fee


def _maps(style: str, attr_id: str, attr_slot: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    def s(name: str) -> str:
        return style.format(n=name.replace("_", "-"))

    sel = {k: s(k) for k in KEYS}
    sel["add_button"] = s("add") + f"[{attr_id}='{{item_id}}']"
    sel["slot_pick"] = s("slot-pick") + f"[{attr_slot}='{{slot_id}}']"
    sel["checkout_button"] = s("checkout")
    sel["subs_toggle"] = s("subs-toggle")
    fields = {
        "product_card": {"item_id": "@" + attr_id, "name": s("name"), "brand": s("brand"),
                         "size": s("size"), "price": s("price"), "stock": "@data-stock"},
        "cart_line": {"item_id": "@" + attr_id, "name": s("line-name"), "qty": s("line-qty"),
                      "unit": s("line-unit"), "total": s("line-total")},
        "charge_row": {"name": s("charge-name"), "amount": s("charge-amount")},
        "slot_option": {"slot_id": "@" + attr_slot, "label": s("slot-label"),
                        "fee": s("slot-fee"), "available": "@data-available"},
        "subs_toggle": {"on": "@data-on"},
    }
    return sel, fields


_ZEPTO = _maps("[data-testid=zp-{n}]", "data-sku", "data-slot")
_BLINKIT = _maps("[data-blk='{n}']", "data-pid", "data-window")
_BIGBASKET = _maps(".bb-{n}", "data-skuid", "data-slotid")
_INSTAMART = _maps("[data-im={n}]", "data-spin", "data-when")

_PATHS = {"home": "/", "search": "/search?q={q}", "item": "/p/{item_id}", "cart": "/cart",
          "slots": "/slots", "order": "/order/{ref}"}

PROFILES: dict[str, SiteProfile] = {
    "zepto": SiteProfile(
        "zepto", "Zepto", "instant", *_ZEPTO,
        alternates={"checkout_button": ["[data-testid=zp-go-pay]"], "subs_toggle": ["[data-testid=zp-replace]"]},
        paths=_PATHS, min_cart_paise=9900, hard_min=False, delivery_fee_paise=2500,
        free_delivery_above_paise=19900, handling_fee_paise=400, small_cart_fee_paise=2000,
        default_eta="10 mins"),
    "blinkit": SiteProfile(
        "blinkit", "Blinkit", "instant", *_BLINKIT,
        alternates={"checkout_button": ["[data-blk='proceed']"]},
        paths={**_PATHS, "item": "/prn/{item_id}"}, min_cart_paise=9900, hard_min=False,
        delivery_fee_paise=3000, free_delivery_above_paise=19900, handling_fee_paise=200,
        small_cart_fee_paise=1500, default_eta="10 minutes", subs_default_on=True),
    "bigbasket": SiteProfile(
        "bigbasket", "BigBasket", "scheduled", *_BIGBASKET,
        alternates={"checkout_button": [".bb-continue-order"]},
        paths={**_PATHS, "search": "/ps/?q={q}", "item": "/pd/{item_id}"}, min_cart_paise=20000,
        hard_min=True, delivery_fee_paise=3000, free_delivery_above_paise=50000),
    "instamart": SiteProfile(
        "instamart", "Swiggy Instamart", "instant", *_INSTAMART,
        alternates={"checkout_button": ["[data-im=pay-step]"]},
        paths={**_PATHS, "search": "/instamart/search?q={q}", "item": "/instamart/item/{item_id}"},
        min_cart_paise=9900, hard_min=True, delivery_fee_paise=2900,
        free_delivery_above_paise=29900, handling_fee_paise=500, default_eta="15 mins"),
}
