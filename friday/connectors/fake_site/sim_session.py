"""SimBrowserSession: an in-process BrowserSession over FakeSiteState (no Chromium, no sockets).

It answers the same selectors as the real fake-site HTML, so connectors run unchanged. Used by the
always-on unit tests and by ``friday connectors demo-pizza --fake --engine sim``.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.fake_site.catalog import FAKE_QR_PNG, FakeSiteState, format_rupees

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class SimBrowserSession:
    def __init__(self, state: FakeSiteState, selectors: Mapping[str, str] | None = None) -> None:
        from friday.connectors.food.zomato import SELECTORS

        self.state = state
        self.sid = state.new_session()
        self._sel = dict(selectors or SELECTORS)
        self.page = ("home", "")
        self.fills: dict[str, str] = {}
        self.calls: list[str] = []  # action log (selectors only, never values)
        self.closed = False

    # ---- selector resolution
    def _key(self, selector: str) -> tuple[str, str]:
        for key, sel in self._sel.items():
            if "{item_id}" in sel:
                for rid in {r for r in self.state.menus}:
                    for m in self.state.menus[rid]:
                        if sel.format(item_id=m["id"]) == selector:
                            return key, m["id"]
            elif sel == selector:
                return key, ""
        raise ElementNotFound(f"unknown selector: {selector}")

    @property
    def _s(self):  # noqa: ANN202
        return self.state.sessions[self.sid]

    # ---- BrowserSession
    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        u = urlsplit(url)
        parts = [unquote(p) for p in u.path.strip("/").split("/")]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        head = parts[0] if parts[0] else "home"
        arg = parts[1] if len(parts) > 1 else ""
        if head == "search":
            self.page = ("search", q.get("q", ""))
        elif head == "cart" and not self._s.logged_in:
            self.page = ("login", "")
        else:
            self.page = (head, arg)

    async def fill(self, selector: str, value: str) -> None:
        key, arg = self._key(selector)
        self._require(key)
        self.calls.append(f"fill:{key}")
        self.fills[key + arg] = value

    async def click(self, selector: str) -> None:
        key, arg = self._key(selector)
        self._require(key)
        self.calls.append(f"click:{key}")
        st, s = self.state, self._s
        if key == "send_otp_button":
            st.send_otp(self.sid, self.fills.get("phone_input", ""))
            self.page = ("otp", "")
        elif key == "submit_otp_button":
            self.page = ("home", "") if st.check_otp(self.sid, self.fills.pop("otp_input", "")) \
                else ("otp_error", "")
        elif key == "menu_item_add":
            try:
                qty = int(self.fills.get("menu_item_qty" + arg, "1"))
            except ValueError:
                qty = 0
            st.add(self.sid, self.page[1], arg, qty)
        elif key == "clear_cart":
            st.clear(self.sid)
        elif key == "checkout_button":
            ref = st.checkout(self.sid)
            self.page = ("pay", ref) if ref else ("cart", "")
        _ = s

    def _present(self, key: str) -> list[dict[str, str]]:
        """Rows that exist on the current page for a selector key."""
        st, kind, arg = self.state, *self.page
        logged = self._s.logged_in
        if key == "account_name":
            return [{"text": "Test User"}] if logged else []
        if kind == "login" and key == "phone_input" or kind == "otp" and key == "otp_input":
            return [{"text": ""}]
        if kind == "otp" and key == "submit_otp_button" or kind == "login" and \
                key == "send_otp_button":
            return [{"text": ""}]
        if kind == "otp_error" and key in {"login_error", "otp_input", "submit_otp_button"}:
            return [{"text": "That code did not work"}]
        if kind == "search" and key == "restaurant_card":
            return [{"restaurant_id": r["id"], "name": r["name"], "area": r["area"],
                     "rating": r["rating"], "text": r["name"]} for r in st.search(arg)]
        if kind == "restaurant" and st.restaurant(arg):
            menu = st.menus[arg]
            if key == "menu_item":
                return [{"item_id": m["id"], "name": m["name"], "price": format_rupees(m["price"]),
                         "veg": "true" if m["veg"] else "false", "text": m["name"]} for m in menu]
            if key in {"menu_item_qty", "menu_item_add"}:
                return [{"text": ""}]
        if kind == "cart" and logged:
            v = st.cart_view(self.sid)
            if key == "cart_line":
                return [{"item_id": line["item_id"], "name": line["name"], "qty": str(line["qty"]),
                         "total": format_rupees(line["line_total_paise"]), "text": line["name"]}
                        for line in v.lines]
            if key in {"cart_fee_row", "cart_tax_row"}:
                rows = v.fees if key == "cart_fee_row" else v.taxes
                return [{"name": n, "amount": format_rupees(a), "text": n} for n, a in rows]
            if key == "cart_subtotal":
                return [{"text": format_rupees(v.subtotal_paise)}]
            if key == "cart_grand_total":
                return [{"text": format_rupees(v.grand_total_paise)}]
            if key == "cart_discount":
                return [{"text": "-" + format_rupees(v.discount_paise)}] if v.discount_paise else []
            if key in {"clear_cart", "checkout_button"}:
                return [{"text": ""}]
        if kind == "pay" and arg in st.orders:
            o = st.orders[arg]
            amount = format_rupees(o["amount"])
            link = f"upi://pay?pa=fakemerchant@fakebank&pn=FakeEats&am={o['amount'] / 100:.2f}" \
                   f"&cu=INR&tr={arg}"
            table = {
                "pay_amount": {"text": amount}, "pay_merchant": {"text": "FakeEats Pvt Ltd"},
                "pay_order_ref": {"text": arg},
                "pay_qr": {"text": "", "src": "data:image/png;base64,"
                           + base64.b64encode(FAKE_QR_PNG).decode()},
                "pay_upi_link": {"text": "Pay", "href": link},
            }
            return [table[key]] if key in table else []
        if kind == "order" and arg in st.orders:
            o = st.orders[arg]
            table = {"order_state": {"text": o["state"]}, "order_eta": {"text": f"{o['eta']} min"}}
            return [table[key]] if key in table else []
        return []

    def _require(self, key: str) -> list[dict[str, str]]:
        rows = self._present(key)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    async def text(self, selector: str) -> str:
        key, _ = self._key(selector)
        return self._require(key)[0]["text"]

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]:
        try:
            key, _ = self._key(selector)
        except ElementNotFound:
            return []  # like a real browser: no match is an empty list
        return self._present(key)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        key, _ = self._key(selector)
        self._require(key)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return _PNG_1X1  # placeholder pixel: the real run uses Chromium screenshots

    async def close(self) -> None:
        self.closed = True
