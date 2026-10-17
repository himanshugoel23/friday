"""Data + rules of the fake site, shared by the HTTP server and the in-process simulator."""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass, field

from friday.connectors.contract import format_rupees  # noqa: F401 - re-exported for pages

# 1x1 PNG: stands in for the QR image on the fake pay page.
FAKE_QR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
FAKE_MERCHANT_VPA = "fakemerchant@fakebank"  # invented


@dataclass
class _Session:
    phone: str = ""
    otp_sent: bool = False
    logged_in: bool = False
    cart: dict[str, int] = field(default_factory=dict)
    restaurant_id: str = ""


@dataclass
class CartView:
    lines: list[dict]  # item_id, name, qty, line_total_paise
    subtotal_paise: int
    fees: list[tuple[str, int]]
    taxes: list[tuple[str, int]]
    discount_paise: int
    grand_total_paise: int


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class FakeSiteState:
    def __init__(
        self, *, otp: str = "246810", tamper_paise: int = 0, discount_paise: int = 0,
        block: str | None = None, block_path: str = "/",
    ) -> None:
        # block: "captcha" | "empty" | "forbidden" -> every GET under block_path answers with
        # that page (tests for blocked-run detection).
        self.block, self.block_path = block, block_path
        self.otp = otp  # the only code this fake site accepts
        self.tamper_paise = tamper_paise  # shown grand total is off by this (inconsistent page)
        self.discount_paise = discount_paise
        self.restaurants = [
            {"id": "r-dom-1", "name": "Domino's Pizza", "area": "Sector 12", "rating": "4.1"},
            {"id": "r-dom-2", "name": "Domino's Pizza", "area": "Old Market", "rating": "3.8"},
            {"id": "r-pz-1", "name": "Pizza Corner", "area": "Sector 12", "rating": "4.4"},
        ]
        base = [
            ("i-marg", "Margherita", 19900, True),
            ("i-pep", "Pepperoni Feast", 34900, False),
            ("i-garlic", "Garlic Breadsticks", 12900, True),
            ("i-coke", "Coke 500ml", 6000, True),
        ]
        self.menus = {
            r["id"]: [{"id": i, "name": n, "price": p, "veg": v} for i, n, p, v in base]
            for r in self.restaurants
        }
        self.sessions: dict[str, _Session] = {}
        self.orders: dict[str, dict] = {}

    # ---- browse
    def search(self, q: str) -> list[dict]:
        nq = _norm(q)
        return [r for r in self.restaurants if nq and nq in _norm(r["name"])]

    def restaurant(self, rid: str) -> dict | None:
        return next((r for r in self.restaurants if r["id"] == rid), None)

    # ---- sessions / login
    def new_session(self) -> str:
        sid = secrets.token_hex(8)
        self.sessions[sid] = _Session()
        return sid

    def session(self, sid: str | None) -> _Session | None:
        return self.sessions.get(sid or "")

    def send_otp(self, sid: str, phone: str) -> None:
        s = self.sessions[sid]
        s.phone, s.otp_sent = phone, True

    def check_otp(self, sid: str, code: str) -> bool:
        s = self.sessions[sid]
        if s.otp_sent and code == self.otp:
            s.logged_in = True
            return True
        return False

    # ---- cart
    def add(self, sid: str, rid: str, item_id: str, qty: int) -> None:
        s = self.sessions[sid]
        if s.restaurant_id != rid:
            s.cart.clear()
            s.restaurant_id = rid
        if any(m["id"] == item_id for m in self.menus.get(rid, [])) and qty > 0:
            s.cart[item_id] = s.cart.get(item_id, 0) + qty

    def clear(self, sid: str) -> None:
        self.sessions[sid].cart.clear()

    def cart_view(self, sid: str) -> CartView:
        s = self.sessions[sid]
        menu = {m["id"]: m for m in self.menus.get(s.restaurant_id, [])}
        lines = [
            {"item_id": i, "name": menu[i]["name"], "qty": q,
             "line_total_paise": menu[i]["price"] * q}
            for i, q in s.cart.items()
        ]
        subtotal = sum(line["line_total_paise"] for line in lines)
        fees = [("Delivery fee", 3500), ("Packaging", 1000), ("Platform fee", 500)] if lines else []
        taxes = [("GST (5%)", (subtotal * 5 + 50) // 100)] if lines else []
        gross = subtotal + sum(a for _, a in fees) + sum(a for _, a in taxes)
        discount = min(self.discount_paise, gross)
        grand = gross - discount + self.tamper_paise
        return CartView(lines, subtotal, fees, taxes, discount, grand)

    def checkout(self, sid: str) -> str | None:
        view = self.cart_view(sid)
        if not view.lines:
            return None
        ref = "FK" + secrets.token_hex(3).upper()
        self.orders[ref] = {
            "amount": view.grand_total_paise, "state": "Awaiting payment", "eta": 35,
        }
        return ref
