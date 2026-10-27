# ruff: noqa: E501
"""FAKE grocery site (one class, parametrised by site key). Invented products, prices and codes.

The page markup is addressed through each site's OWN selector map (grocery/profiles.py), so the
per-site selectors are really exercised: a Zepto selector does not work on the fake Blinkit.
Scenario knobs: ``logged_in`` (False = login expired), ``closed`` (store closed), ``sold_out``
(product codes sold out from the start), ``sold_out_on_add`` (taken once the user approved, i.e.
at the first add to cart), ``price_bump_pct`` / ``fee_bump_paise`` (rise at the same moment),
``names`` (code -> replacement product name, used for prompt injection), ``banner`` (page text),
``block`` ("captcha"), ``address_on_cart`` (a different delivery address on the cart page),
``no_slots``, ``subs_on`` (substitution switch default; None = the site's own quirk).
"""

from __future__ import annotations

import base64
import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.contract import format_rupees
from friday.connectors.sites.grocery.profiles import PROFILES

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
CATALOG = {  # code -> (name, brand, size, price paise)
    "milk5": ("Toned Milk", "Fresh Dairy", "500 ml", 2800),
    "milk1": ("Toned Milk", "Fresh Dairy", "1 L", 5400),
    "gmilk": ("Toned Milk", "Green Farm", "500 ml", 3000),
    "butter": ("Salted Butter", "Golden Churn", "500 g", 28500),
    "butter2": ("Salted Butter", "Meadow", "100 g", 5800),
    "eggs": ("Farm Eggs", "Farm Fresh", "6 pcs", 6000),
    "bread": ("Sandwich Bread", "Soft Loaf", "400 g", 4500),
}
SLOTS = [("sl1", "Today 6-8 pm", 3000), ("sl2", "Tomorrow 8-10 am", 0), ("sl3", "Today 8-10 pm", 0)]


def _rx(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{(\w+)\}", template)
    body = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^'\"\\]]+)" for i, p in enumerate(parts))
    return re.compile(rf"^{body}$")


class FakeGrocerySite:
    def __init__(self, site: str, *, logged_in: bool = True, closed: bool = False,
                 sold_out: set[str] | None = None, sold_out_on_add: set[str] | None = None,
                 price_bump_pct: int = 0, fee_bump_paise: int = 0, names: dict[str, str] | None = None,
                 banner: str = "", block: str | None = None, address: str = "Flat 4, Sector 12",
                 address_on_cart: str | None = None, no_slots: bool = False,
                 subs_on: bool | None = None) -> None:
        self.site, self.p = site, PROFILES[site]
        self.logged_in, self.closed, self.banner, self.block = logged_in, closed, banner, block
        self.sold_out, self.sold_out_on_add = set(sold_out or ()), set(sold_out_on_add or ())
        self.price_bump_pct, self.fee_bump, self._bumped = price_bump_pct, fee_bump_paise, False
        self.names, self.address, self.address_on_cart = dict(names or {}), address, address_on_cart
        self.no_slots = no_slots
        self.subs_default = self.p.subs_default_on if subs_on is None else subs_on
        self.prices = {c: v[3] for c, v in CATALOG.items()}
        self.orders: dict[str, dict[str, Any]] = {}
        self.sessions: list[GroceryFakeSession] = []

    def session(self, renamed: dict[str, str] | None = None) -> GroceryFakeSession:
        s = GroceryFakeSession(self, renamed)
        self.sessions.append(s)
        return s

    def expire_login(self) -> None:
        self.logged_in = False

    # ---- data
    def pid(self, code: str) -> str:
        return f"{self.site}-{code}"

    def code(self, item_id: str) -> str | None:
        c = item_id.removeprefix(self.site + "-")
        return c if c in CATALOG and item_id == self.pid(c) else None

    def product(self, code: str) -> dict[str, Any]:
        name, brand, size, _ = CATALOG[code]
        return {"item_id": self.pid(code), "name": self.names.get(code, name), "brand": brand,
                "size": size, "price": self.prices[code], "stock": code not in self.sold_out}

    def bump(self) -> None:
        if not self._bumped:
            self._bumped = True
            self.prices = {c: v * (100 + self.price_bump_pct) // 100 for c, v in self.prices.items()}
            self.sold_out |= self.sold_out_on_add


class GroceryFakeSession:
    def __init__(self, site: FakeGrocerySite, renamed: dict[str, str] | None = None) -> None:
        self.site, self.p = site, site.p
        self._sel = {**self.p.selectors, "page_body": "body", **(renamed or {})}
        self._paths = {k: _rx(v.split("?")[0]) for k, v in self.p.paths.items()}
        self.page: tuple[str, str] = ("home", "")
        self.cart: dict[str, int] = {}
        self.slot = ""
        self.subs_on = site.subs_default
        self.calls: list[str] = []
        self.closed = False

    # ---- selector -> (key, params)
    def _key(self, selector: str) -> tuple[str, dict[str, str]]:
        for key, sel in self._sel.items():
            m = _rx(sel).match(selector)
            if m:
                return key, m.groupdict()
        raise ElementNotFound(f"unknown selector: {selector}")

    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        u = urlsplit(url)
        path, q = unquote(u.path) or "/", {k: v[0] for k, v in parse_qs(u.query).items()}
        for key, rx in self._paths.items():
            m = rx.match(path)
            if m:
                arg = q.get("q", "") if key == "search" else next(iter(m.groupdict().values()), "")
                self.page = (key, arg)
                return
        self.page = ("notfound", "")

    async def fill(self, selector: str, value: str) -> None:
        raise ElementNotFound("this fake has no text inputs")

    async def click(self, selector: str) -> None:
        key, params = self._key(selector)
        self._require(key, params)
        self.calls.append(f"click:{key}")
        s = self.site
        if key == "add_button":
            code = s.code(params["item_id"])
            s.bump()
            if code in s.sold_out:
                raise ElementNotFound("sold out")
            self.cart[params["item_id"]] = self.cart.get(params["item_id"], 0) + 1
        elif key == "subs_toggle":
            self.subs_on = not self.subs_on
        elif key == "slot_pick":
            self.slot = params["slot_id"]
        elif key == "checkout_button":
            ref = "GR" + secrets.token_hex(3).upper()
            s.orders[ref] = {"amount": self._bill()["total"], "state": "Awaiting payment"}
            self.page = ("pay", ref)

    # ---- the bill
    def _bill(self) -> dict[str, Any]:
        s, p = self.site, self.p
        lines = []
        for item_id, qty in self.cart.items():
            code = s.code(item_id)
            assert code
            prod = s.product(code)
            lines.append({**prod, "qty": qty, "line": prod["price"] * qty})
        sub = sum(x["line"] for x in lines)
        fees: list[tuple[str, int]] = []
        if lines:
            if sub < p.free_delivery_above_paise:
                fees.append(("Delivery fee", p.delivery_fee_paise))
            if s.fee_bump:
                fees.append(("Platform fee", s.fee_bump))
            if p.handling_fee_paise:
                fees.append(("Handling fee", p.handling_fee_paise))
            if not p.hard_min and sub < p.min_cart_paise:
                fees.append(("Small cart fee", p.small_cart_fee_paise))
            slot_fee = next((f for i, _, f in SLOTS if i == self.slot), 0)
            if slot_fee:
                fees.append(("Slot fee", slot_fee))
        tax = (sum(f for _, f in fees) * 18 + 50) // 100
        return {"lines": lines, "sub": sub, "fees": fees, "tax": tax,
                "total": sub + sum(f for _, f in fees) + tax}

    def _eta(self) -> str:
        if self.p.kind == "scheduled":
            return next((lb for i, lb, _ in SLOTS if i == self.slot), "")
        return self.p.default_eta

    # ---- what each page shows
    def _present(self, key: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        s, (kind, arg) = self.site, self.page
        if key == "page_body":
            if s.block == "captcha":
                return [{"text": "Please verify you are a human. Captcha"}]
            extra = ""
            if kind == "search":
                extra = "\n".join(s.product(c)["name"] for c in self._search(arg))
            return [{"text": f"page {kind}\n{s.banner}\n{extra}".strip()}]
        if key == "banner":
            return [{"text": s.banner}] if s.banner else []
        if kind == "home":
            if key == "account_name":
                return [{"text": "Test User"}] if s.logged_in else []
            if key == "store_closed":
                return [{"text": "Store closed"}] if s.closed else []
            if key == "address_badge":
                return [{"text": s.address}]
            if key == "eta_badge" and self.p.kind == "instant":
                return [{"text": self.p.default_eta}]
        if kind == "search" and key == "product_card":
            return [{**s.product(c), "text": s.product(c)["name"]} for c in self._search(arg)]
        if kind == "item":
            code = s.code(arg)
            if code is None:
                return []
            if key == "product_card":
                return [{**s.product(code), "text": s.product(code)["name"]}]
            if key == "add_button" and code not in s.sold_out and params and params.get("item_id") == arg:
                return [{"text": ""}]
        if kind == "cart" and self.cart:
            b = self._bill()
            if key == "cart_line":
                return [{"item_id": x["item_id"], "name": x["name"], "qty": str(x["qty"]),
                         "unit": format_rupees(x["price"]), "total": format_rupees(x["line"]),
                         "text": x["name"]} for x in b["lines"]]
            if key == "fee_row":
                return [{"name": n, "amount": format_rupees(a), "text": n} for n, a in b["fees"]]
            if key == "tax_row":
                return [{"name": "GST on fees", "amount": format_rupees(b["tax"]), "text": "tax"}] if b["tax"] else []
            if key == "cart_total":
                return [{"text": format_rupees(b["total"])}]
            if key == "cart_address":
                return [{"text": s.address_on_cart or s.address}]
            if key == "cart_eta":
                return [{"text": self._eta()}] if self._eta() else []
            if key == "subs_toggle":
                return [{"on": "true" if self.subs_on else "false", "text": "Replace if unavailable"}]
            if key == "checkout_button":
                return [{"text": ""}]
        if kind == "slots" and self.p.kind == "scheduled":
            if key == "slot_option":
                return [{"slot_id": i, "label": lb, "fee": format_rupees(f),
                         "available": "false" if (s.no_slots or i == "sl3") else "true", "text": lb}
                        for i, lb, f in SLOTS]
            if key == "slot_pick" and params and any(i == params.get("slot_id") for i, _, _ in SLOTS):
                return [{"text": ""}]
        if kind == "pay" and arg in s.orders:
            amt = s.orders[arg]["amount"]
            t = {"pay_amount": {"text": format_rupees(amt)}, "pay_merchant": {"text": "FakeGrocer Pvt Ltd"},
                 "pay_order_ref": {"text": arg},
                 "pay_qr": {"text": "", "src": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                 "pay_upi_link": {"text": "Pay", "href": f"upi://pay?pa=fakegrocer@fakebank&pn=FakeGrocer&am={amt / 100:.2f}&cu=INR&tr={arg}"}}
            return [t[key]] if key in t else []
        if kind == "order" and arg in s.orders and key == "order_state":
            return [{"text": s.orders[arg]["state"]}]
        return []

    def _search(self, q: str) -> list[str]:
        nq = re.sub(r"[^a-z0-9]", "", q.lower())
        return [c for c, (n, b, _, _) in CATALOG.items()
                if nq and nq in re.sub(r"[^a-z0-9]", "", (b + n).lower())]

    def _require(self, key: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        rows = self._present(key, params)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    async def text(self, selector: str) -> str:
        key, params = self._key(selector)
        return str(self._require(key, params)[0]["text"])

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None
                        ) -> list[dict[str, str]]:
        try:
            key, params = self._key(selector)
        except ElementNotFound:
            return []
        rows = self._present(key, params)
        if fields is None:
            return [{"text": str(r.get("text", ""))} for r in rows]
        return [{**{k: str(r.get(k, "")).lower() if k in {"stock", "available"} else (
            format_rupees(r[k]) if k == "price" and isinstance(r.get(k), int) else str(r.get(k, "")))
            for k in fields}, "text": str(r.get("text", ""))} for r in rows]

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        key, params = self._key(selector)
        self._require(key, params)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True

