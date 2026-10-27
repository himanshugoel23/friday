# ruff: noqa: E501
"""Shopping connector on a scripted browser: Amazon India and Flipkart.

!! Every selector below targets the FAKE shop (sites/fakes/shopping_site.py). The real Amazon and
!! Flipkart are UNVERIFIED: markup, login, add-ons, checkout, cancel flow and payment screen must be
!! recorded and tuned first. Real tuning touches only PATHS / SELECTORS / FIELDS / ALTERNATES.
Rules: add-ons / subscriptions / trials are UNTICKED (or the run reports it cannot); the cart must
hold exactly the approved item (anything else stops); the order-confirm click and the cancel click
are armed by the adapter only after approval; the connector ends at the QR / UPI link, never pays.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession
from friday.connectors.contract import (
    CartMismatch,
    Charge,
    LayoutChanged,
    PaymentHandoff,
    TotalsMismatch,
    rupees_to_paise,
)
from friday.connectors.sites.errors import VerifyFailed
from friday.connectors.sites.shopping.contract import (
    OrderRow,
    Product,
    ProductPage,
    Quote,
    QuoteLine,
    Variant,
)
from friday.connectors.sites.train.common import (
    AddOnStuck,
    ScriptedConnector,
    build_kit,
    clean,
    safe_id,
)
from friday.connectors.sites.train.contract import AddOn

PATHS = {
    "home": "/", "login": "/login", "search": "/search?q={q}", "product": "/product/{product_id}",
    "cart": "/cart", "checkout": "/checkout", "orders": "/orders", "order": "/order/{order_id}",
}
AMAZON_SELECTORS = {
    "account_name": "[data-testid=account-name]",
    "phone_input": "[data-testid=phone-input]",
    "send_otp_button": "[data-testid=send-otp-button]",
    "otp_input": "[data-testid=otp-input]",
    "submit_otp_button": "[data-testid=submit-otp-button]",
    "login_error": "[data-testid=login-error]",
    "product_card": "[data-testid=product-card]",
    "product_title": "[data-testid=product-title]",
    "product_price": "[data-testid=product-price]",
    "product_stock": "[data-testid=product-stock]",
    "variant_option": "[data-testid=variant-option]",
    "variant_pick": "[data-testid=variant-option][data-variant-id='{variant_id}']",
    "return_policy": "[data-testid=return-policy]",
    "delivery_fee": "[data-testid=delivery-fee]",
    "delivery_estimate": "[data-testid=delivery-estimate]",
    "qty_input": "[data-testid=qty-input]",
    "add_to_cart": "[data-testid=add-to-cart]",
    "line": "[data-testid=line]",
    "fee_row": "[data-testid=fee-row]",
    "addon_row": "[data-testid=addon-row]",
    "addon_toggle": "[data-testid=addon-toggle-{addon_id}]",
    "total": "[data-testid=total]",
    "checkout_button": "[data-testid=go-checkout]",
    "delivery_address": "[data-testid=delivery-address]",
    "order_confirm_button": "[data-testid=order-confirm]",
    "pay_amount": "[data-testid=pay-amount]",
    "pay_merchant": "[data-testid=pay-merchant]",
    "pay_order_ref": "[data-testid=pay-order-ref]",
    "pay_qr": "[data-testid=pay-qr]",
    "pay_upi_link": "[data-testid=pay-upi-link]",
    "order_row": "[data-testid=order-row]",
    "order_status": "[data-testid=order-status]",
    "cancel_open": "[data-testid=cancel-open]",
    "cancel_confirm_button": "[data-testid=cancel-confirm]",
}
FLIPKART_SELECTORS = {**AMAZON_SELECTORS,
                      "add_to_cart": "[data-testid=add-to-bag]",
                      "checkout_button": "[data-testid=place-checkout]",
                      "order_confirm_button": "[data-testid=finish-order]",
                      "product_card": "[data-testid=item-card]"}
SELECTORS = {"amazon": AMAZON_SELECTORS, "flipkart": FLIPKART_SELECTORS}
FIELDS = {
    "product_card": {"product_id": "@data-product-id", "title": "[data-testid=card-title]",
                     "price": "[data-testid=card-price]", "rating": "[data-testid=card-rating]",
                     "rating_count": "[data-testid=card-rating-count]", "seller": "[data-testid=card-seller]",
                     "fulfilment": "[data-testid=card-fulfilment]"},
    "variant_option": {"variant_id": "@data-variant-id", "label": "[data-testid=variant-label]",
                       "available": "@data-available", "price": "[data-testid=variant-price]"},
    "line": {"product_id": "@data-product-id", "variant_id": "@data-variant-id",
             "title": "[data-testid=line-title]", "qty": "[data-testid=line-qty]",
             "unit": "[data-testid=line-unit]", "total": "[data-testid=line-total]"},
    "charge_row": {"name": "[data-testid=charge-name]", "amount": "[data-testid=charge-amount]"},
    "addon_row": {"addon_id": "@data-addon-id", "label": "[data-testid=addon-label]",
                  "amount": "[data-testid=addon-amount]", "checked": "@data-checked"},
    "order_row": {"order_id": "@data-order-id", "title": "[data-testid=order-title]",
                  "status": "[data-testid=order-state]", "amount": "[data-testid=order-amount]",
                  "cancellable": "@data-cancellable"},
}
ALTERNATES: dict[str, list[str]] = {}
IRREVERSIBLE = frozenset({"order_confirm_button", "cancel_confirm_button"})
EXPECT = {"order_confirm_button": ("pay_amount",)}


def make_kit(session: BrowserSession, site_key: str, *, task_id: str, repairer: Any = None):  # noqa: ANN201
    return build_kit(session, site_key=site_key, selectors=SELECTORS[site_key], alternates=ALTERNATES,
                     irreversible=IRREVERSIBLE, task_id=task_id, repairer=repairer, expect=EXPECT)


def _int(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


class ShopConnector(ScriptedConnector):
    use_case = "shopping"
    P, F = PATHS, FIELDS

    def __init__(self, session: BrowserSession, *, site: str, **kw: Any) -> None:
        super().__init__(session, **kw)
        self.site, self.S = site, SELECTORS[site]

    # ---- login: code only through the one-time channel
    async def ensure_logged_in(self) -> str:
        await self._goto("home")
        if await self._present("account_name"):
            return "reused"
        await self._phone_login()
        return "logged_in"

    async def _no_login_form(self) -> None:
        from friday.connectors.contract import LoginRequired

        if await self._present("phone_input"):
            raise LoginRequired("the site logged the session out")

    # ---- read-only browsing
    async def search(self, query: str) -> list[Product]:
        await self._goto("search", q=query)
        out = []
        for r in await self._rows("product_card"):
            try:
                rating = float(r["rating"]) if r.get("rating") else None
                out.append(Product(product_id=safe_id(r["product_id"], "product id"), title=clean(r["title"], 80),
                                   price_paise=rupees_to_paise(r["price"]), rating=rating,
                                   rating_count=_int(r.get("rating_count", "")), seller=clean(r.get("seller", ""), 40),
                                   fulfilment=clean(r.get("fulfilment", ""), 40)))
            except (KeyError, ValueError, ValidationError):
                continue
        return out

    async def product(self, product_id: str) -> ProductPage:
        await self._goto("product", product_id=safe_id(product_id, "product id"))
        try:
            title, price = clean(await self._text("product_title"), 80), await self._money("product_price")
        except LayoutChanged:
            raise
        stock = (await self._text("product_stock")).strip().lower() if await self._present("product_stock") else "in stock"
        variants = []
        for r in await self._rows("variant_option"):
            try:
                variants.append(Variant(variant_id=safe_id(r["variant_id"], "variant id"), label=clean(r["label"], 40),
                                        available=r.get("available", "").lower() == "true",
                                        price_paise=rupees_to_paise(r["price"]) if r.get("price") else price))
            except (KeyError, ValueError, ValidationError):
                continue
        fee = await self._money("delivery_fee") if await self._present("delivery_fee") else 0
        return ProductPage(
            product_id=product_id, title=title, price_paise=price, in_stock=not stock.startswith(("out", "sold", "currently unavailable")),
            variants=variants, delivery_fee_paise=fee,
            return_policy=clean(await self._text("return_policy"), 160) if await self._present("return_policy") else "",
            delivery_estimate=clean(await self._text("delivery_estimate"), 40) if await self._present("delivery_estimate") else "")

    # ---- cart and checkout (after approval)
    async def add_to_cart(self, product_id: str, variant_id: str, qty: int) -> None:
        await self.ensure_logged_in()
        await self._goto("product", product_id=safe_id(product_id, "product id"))
        if variant_id:
            await self._s.click(self.S["variant_pick"].format(variant_id=safe_id(variant_id, "variant id")))
        await self._s.fill(self.S["qty_input"], str(qty))
        await self._s.click(self.S["add_to_cart"])

    async def read_quote(self) -> Quote:
        """The cart or checkout page as the site shows it (same keys on both)."""
        await self._no_login_form()
        await self._wait("total")
        lines = []
        for r in await self._rows("line"):
            try:
                lines.append(QuoteLine(product_id=safe_id(r["product_id"], "product id"), variant_id=r.get("variant_id", ""),
                                       title=clean(r["title"], 80), qty=int(r["qty"]), unit_paise=rupees_to_paise(r["unit"]),
                                       total_paise=rupees_to_paise(r["total"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("a cart line could not be read") from None
        if not lines:
            raise CartMismatch("the cart is empty")
        fees = []
        for r in await self._rows("fee_row", "charge_row"):
            try:
                fees.append(Charge(name=clean(r["name"], 60), amount_paise=rupees_to_paise(r["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("a fee row could not be read") from None
        addons = []
        for r in await self._rows("addon_row"):
            try:
                addons.append(AddOn(addon_id=safe_id(r["addon_id"], "extra"), label=clean(r["label"], 60),
                                    amount_paise=rupees_to_paise(r["amount"]), checked=r.get("checked", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("an extra could not be read") from None
        try:
            return Quote(lines=lines, fees=fees, addons=addons, total_paise=await self._money("total"))
        except ValidationError:
            raise TotalsMismatch("totals on the page do not add up") from None

    async def cart(self) -> Quote:
        await self._goto("cart")
        return await self.read_quote()

    async def untick_addons(self) -> Quote:
        """Untick every pre-ticked extra (protection plan, trial, subscription). ``AddOnStuck`` if one stays."""
        q = await self.read_quote()
        for a in q.ticked():
            await self._s.click(self.S["addon_toggle"].format(addon_id=a.addon_id))
        fresh = await self.read_quote()
        stuck = fresh.ticked()
        if stuck:
            raise AddOnStuck([a.label for a in stuck], sum(a.amount_paise for a in stuck), fresh)
        return fresh

    async def go_checkout(self) -> str:
        await self._s.click(self.S["checkout_button"])
        await self._no_login_form()
        return clean(await self._text("delivery_address"), 160)

    async def confirm_order(self, total_paise: int) -> PaymentHandoff:
        """The ONE irreversible click of a purchase (armed after approval); ends at the pay page."""
        await self._s.click(self.S["order_confirm_button"])
        return await self._read_payment(total_paise)

    # ---- orders: track (read-only) and cancel (irreversible)
    async def orders(self) -> list[OrderRow]:
        await self._goto("orders")
        out = []
        for r in await self._rows("order_row"):
            try:
                out.append(OrderRow(order_id=safe_id(r["order_id"], "order id"), title=clean(r["title"], 80),
                                    status=clean(r["status"], 40), amount_paise=rupees_to_paise(r["amount"]) if r.get("amount") else 0,
                                    cancellable=r.get("cancellable", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError):
                continue
        return out

    async def order_status(self, order_id: str) -> str:
        await self._goto("order", order_id=safe_id(order_id, "order id"))
        return clean(await self._text("order_status"), 60)

    async def cancel_order(self, order_id: str) -> str:
        """Open the cancel page (reversible), then the armed confirm click. Verified afterwards."""
        await self._goto("order", order_id=safe_id(order_id, "order id"))
        await self._s.click(self.S["cancel_open"])
        await self._s.click(self.S["cancel_confirm_button"])
        state = await self.order_status(order_id)
        if "cancel" not in state.lower():
            raise VerifyFailed("the order does not show as cancelled")
        return state
