"""ZomatoFoodConnector: the food contract on a scripted browser (backend kind scripted_browser).

!! The selectors below target the FAKE test site (friday/connectors/fake_site). Real Zomato
!! pages are UNVERIFIED: markup, login modal, anti-bot checks and the checkout flow must be
!! recorded as fixtures and tuned before this connector is switched to ``live`` for real users.
!! Real-site tuning touches ONLY the three dicts right here (PATHS, SELECTORS, FIELDS).

Rules this file keeps: the connector stops at the payment page and returns a ``PaymentHandoff``
(QR / UPI link) - there is no pay call; the login OTP comes only from ``OneTimeOtpChannel`` and
is typed into the page, never stored or logged; errors never include page text; everything read
from the page is parsed into typed models and re-validated (totals must add up).
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.contract import (
    Cart,
    CartLine,
    CartMismatch,
    Charge,
    ConnectorError,
    ItemQty,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    Menu,
    MenuItem,
    OrderStatus,
    PaymentHandoff,
    Restaurant,
    TotalsMismatch,
    rupees_to_paise,
)
from friday.connectors.otp import OneTimeOtpChannel

# ---------------------------------------------------------------- TUNE HERE (fake-site values)
PATHS = {
    "home": "/",
    "login": "/login",
    "search": "/search?q={q}&area={area}",
    "restaurant": "/restaurant/{restaurant_id}",
    "cart": "/cart",
    "order": "/order/{order_ref}",
}
SELECTORS = {
    "account_name": "[data-testid=account-name]",
    "phone_input": "[data-testid=phone-input]",
    "send_otp_button": "[data-testid=send-otp-button]",
    "otp_input": "[data-testid=otp-input]",
    "submit_otp_button": "[data-testid=submit-otp-button]",
    "login_error": "[data-testid=login-error]",
    "restaurant_card": "[data-testid=restaurant-card]",
    "menu_item": "[data-testid=menu-item]",
    "menu_item_qty": "[data-testid=menu-item][data-item-id='{item_id}'] [data-testid=qty-input]",
    "menu_item_add": "[data-testid=menu-item][data-item-id='{item_id}'] [data-testid=add-button]",
    "clear_cart": "[data-testid=clear-cart]",
    "cart_line": "[data-testid=cart-line]",
    "cart_subtotal": "[data-testid=cart-subtotal]",
    "cart_fee_row": "[data-testid=fee-row]",
    "cart_tax_row": "[data-testid=tax-row]",
    "cart_discount": "[data-testid=cart-discount]",
    "cart_grand_total": "[data-testid=cart-grand-total]",
    "checkout_button": "[data-testid=checkout-button]",
    "pay_amount": "[data-testid=pay-amount]",
    "pay_merchant": "[data-testid=pay-merchant]",
    "pay_order_ref": "[data-testid=pay-order-ref]",
    "pay_qr": "[data-testid=pay-qr]",
    "pay_upi_link": "[data-testid=pay-upi-link]",
    "order_state": "[data-testid=order-state]",
    "order_eta": "[data-testid=order-eta]",
}
FIELDS = {  # per-row sub-selectors; "@attr" reads an attribute
    "restaurant_card": {
        "restaurant_id": "@data-restaurant-id",
        "name": "[data-testid=restaurant-name]",
        "area": "[data-testid=restaurant-area]",
        "rating": "[data-testid=restaurant-rating]",
    },
    "menu_item": {
        "item_id": "@data-item-id",
        "name": "[data-testid=item-name]",
        "price": "[data-testid=item-price]",
        "veg": "@data-veg",
    },
    "cart_line": {
        "item_id": "@data-item-id",
        "name": "[data-testid=line-name]",
        "qty": "[data-testid=line-qty]",
        "total": "[data-testid=line-total]",
    },
    "charge_row": {"name": "[data-testid=charge-name]", "amount": "[data-testid=charge-amount]"},
}
# ---------------------------------------------------------------- end of tunable part

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")  # ids come from the page: never trust them
Sleep = Callable[[float], Awaitable[None]]


def _safe_id(value: str, what: str) -> str:
    if not _SAFE_ID.match(value or ""):
        raise CartMismatch(f"unexpected {what} format")
    return value


class ZomatoFoodConnector:
    site = "zomato"
    use_case = "food"
    backend = "scripted_browser"

    def __init__(
        self,
        session: BrowserSession,
        *,
        base_url: str,
        task_id: str,
        otp_channel: OneTimeOtpChannel | None = None,
        phone: str | None = None,
        reuse_session: bool = True,
        otp_wait_s: float = 120.0,
        poll_s: float = 0.5,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._s = session
        self._base = base_url.rstrip("/")
        self._task_id = task_id
        self._otp = otp_channel
        self._phone = phone  # held in memory for login only; never logged or returned
        self._reuse = reuse_session
        self._otp_wait_s = otp_wait_s
        self._poll_s = poll_s
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"ZomatoFoodConnector(task_id={self._task_id!r})"

    # ------------------------------------------------------------ helpers
    async def _goto(self, key: str, **params: str) -> None:
        quoted = {k: quote(v, safe="") for k, v in params.items()}
        await self._s.goto(self._base + PATHS[key].format(**quoted))

    async def _rows(self, key: str, fields: str | None = None) -> list[dict[str, str]]:
        return await self._s.query_all(SELECTORS[key], FIELDS.get(fields or key))

    async def _wait(self, key: str, timeout_ms: int = 5000) -> None:
        try:
            await self._s.wait_for(SELECTORS[key], timeout_ms)
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _text(self, key: str) -> str:
        try:
            return await self._s.text(SELECTORS[key])
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _money(self, key: str) -> int:
        try:
            return rupees_to_paise(await self._text(key))
        except ValueError:
            raise LayoutChanged(f"'{key}' is not a money amount") from None

    async def _logged_in(self) -> bool:
        return bool(await self._s.query_all(SELECTORS["account_name"]))

    # ------------------------------------------------------------ login
    async def ensure_logged_in(self) -> str:
        """'reused' if a saved session still works, else logs in with the one-time channel."""
        await self._goto("home")
        if self._reuse and await self._logged_in():
            return "reused"
        if not self._phone or self._otp is None:
            raise LoginRequired("not logged in and no phone / OTP channel available")
        await self._goto("login")
        await self._s.fill(SELECTORS["phone_input"], self._phone)
        await self._s.click(SELECTORS["send_otp_button"])
        await self._wait("otp_input")
        code = await self._wait_for_code()
        try:
            await self._s.fill(SELECTORS["otp_input"], code)
            await self._s.click(SELECTORS["submit_otp_button"])
        finally:
            code = ""  # noqa: F841 - drop our reference; the channel already wiped its copy
        try:
            await self._s.wait_for(SELECTORS["account_name"], 4000)
        except ElementNotFound:
            raise LoginFailed("the site did not accept the login code") from None
        return "logged_in"

    async def _wait_for_code(self) -> str:
        assert self._otp is not None
        deadline = time.monotonic() + self._otp_wait_s
        while True:
            code = self._otp.take(self._task_id)
            if code:
                return code
            if time.monotonic() >= deadline:
                raise LoginRequired("login code not received in time")
            await self._sleep(self._poll_s)

    # ------------------------------------------------------------ the contract
    async def search_restaurants(self, query: str, area: str) -> list[Restaurant]:
        await self._goto("search", q=query, area=area)
        out: list[Restaurant] = []
        for row in await self._rows("restaurant_card"):
            rid = row.get("restaurant_id", "")
            if not _SAFE_ID.match(rid) or not row.get("name"):
                continue
            try:
                rating = float(row["rating"]) if row.get("rating") else None
            except ValueError:
                rating = None
            out.append(Restaurant(
                restaurant_id=rid, name=row["name"], area=row.get("area", ""), rating=rating))
        return out

    async def get_menu(self, restaurant_id: str) -> Menu:
        await self._goto("restaurant", restaurant_id=_safe_id(restaurant_id, "restaurant id"))
        items: list[MenuItem] = []
        for row in await self._rows("menu_item"):
            try:
                items.append(MenuItem(
                    item_id=_safe_id(row.get("item_id", ""), "item id"),
                    name=row.get("name", ""),
                    price_paise=rupees_to_paise(row.get("price", "")),
                    veg=row.get("veg", "").lower() == "true",
                ))
            except (ValueError, ValidationError, ConnectorError):
                continue  # skip a malformed row rather than guess
        if not items:
            raise LayoutChanged("no menu items found")
        return Menu(restaurant_id=restaurant_id, items=items)

    async def build_cart(self, restaurant_id: str, items: list[ItemQty]) -> Cart:
        await self.ensure_logged_in()
        await self._goto("restaurant", restaurant_id=_safe_id(restaurant_id, "restaurant id"))
        await self._goto("cart")
        if await self._s.query_all(SELECTORS["clear_cart"]):
            await self._s.click(SELECTORS["clear_cart"])  # start from an empty cart
        await self._goto("restaurant", restaurant_id=restaurant_id)
        for it in items:
            iid = _safe_id(it.item_id, "item id")
            await self._s.fill(SELECTORS["menu_item_qty"].format(item_id=iid), str(it.qty))
            await self._s.click(SELECTORS["menu_item_add"].format(item_id=iid))
        await self._goto("cart")
        cart = await self._read_cart(restaurant_id)
        want = {i.item_id: i.qty for i in items}
        got = {line.item_id: line.qty for line in cart.lines}
        if want != got:
            raise CartMismatch("cart contents differ from the request")
        return cart

    async def _read_cart(self, restaurant_id: str) -> Cart:
        await self._wait("cart_grand_total")
        lines: list[CartLine] = []
        for row in await self._rows("cart_line"):
            try:
                qty = int(row["qty"])
                total = rupees_to_paise(row["total"])
                if qty < 1 or total % qty:
                    raise TotalsMismatch("line total not divisible by quantity")
                lines.append(CartLine(
                    item_id=_safe_id(row["item_id"], "item id"), name=row["name"], qty=qty,
                    unit_price_paise=total // qty, line_total_paise=total))
            except (KeyError, ValueError):
                raise LayoutChanged("cart line could not be read") from None
        if not lines:
            raise CartMismatch("cart is empty")
        fees, taxes = await self._charges("cart_fee_row"), await self._charges("cart_tax_row")
        discount = 0
        if await self._s.query_all(SELECTORS["cart_discount"]):
            discount = await self._money("cart_discount")
        try:
            return Cart(
                restaurant_id=restaurant_id, lines=lines,
                subtotal_paise=await self._money("cart_subtotal"),
                fees=fees, taxes=taxes, discount_paise=discount,
                grand_total_paise=await self._money("cart_grand_total"),
            )
        except ValidationError:
            raise TotalsMismatch("cart totals on the page do not add up") from None

    async def _charges(self, key: str) -> list[Charge]:
        out: list[Charge] = []
        for row in await self._rows(key, "charge_row"):
            try:
                out.append(Charge(name=row["name"], amount_paise=rupees_to_paise(row["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged(f"'{key}' row could not be read") from None
        return out

    async def get_payment_handoff(self, cart: Cart) -> PaymentHandoff:
        """Go to the pay page and STOP: read the QR / UPI link for the user. Nothing is paid."""
        await self._goto("cart")
        again = await self._read_cart(cart.restaurant_id)
        if again.grand_total_paise != cart.grand_total_paise:
            raise TotalsMismatch("the total changed since the cart was approved")
        await self._s.click(SELECTORS["checkout_button"])
        await self._wait("pay_amount")
        amount = await self._money("pay_amount")
        if amount != cart.grand_total_paise:
            raise TotalsMismatch("payment page amount differs from the approved cart")
        merchant = await self._text("pay_merchant")
        ref = await self._s.query_all(SELECTORS["pay_order_ref"])
        qr_png = await self._qr_bytes()
        link = await self._upi_link(amount)
        if qr_png is None and link is None:
            raise LayoutChanged("no QR or UPI link on the payment page")
        try:
            return PaymentHandoff(
                kind="qr" if qr_png else "upi_intent", amount_paise=amount, merchant=merchant,
                order_ref=(ref[0]["text"] if ref else None), qr_png=qr_png, upi_link=link)
        except ValidationError:
            raise LayoutChanged("payment page data failed validation") from None

    async def _qr_bytes(self) -> bytes | None:
        for row in await self._s.query_all(SELECTORS["pay_qr"], {"src": "@src"}):
            src = row.get("src", "")
            if src.startswith("data:image/png;base64,"):
                try:
                    return base64.b64decode(src.split(",", 1)[1], validate=True)
                except ValueError:
                    return None
        return None

    async def _upi_link(self, amount_paise: int) -> str | None:
        for row in await self._s.query_all(SELECTORS["pay_upi_link"], {"href": "@href"}):
            href = row.get("href", "")
            if not href.startswith("upi://pay"):
                continue
            am = parse_qs(urlsplit(href).query).get("am")
            if am and rupees_to_paise(am[0]) != amount_paise:
                raise TotalsMismatch("UPI link amount differs from the approved cart")
            return href
        return None

    async def track_order(self, order_ref: str) -> OrderStatus:
        await self._goto("order", order_ref=_safe_id(order_ref, "order ref"))
        state = await self._text("order_state")
        eta = None
        if await self._s.query_all(SELECTORS["order_eta"]):
            digits = "".join(c for c in await self._text("order_eta") if c.isdigit())
            eta = int(digits) if digits else None
        return OrderStatus(order_ref=order_ref, state=state, eta_minutes=eta)
