# ruff: noqa: E501
"""An in-process fake grocery store (stdlib HTTP server on 127.0.0.1, no JavaScript) with three markup 'skins' so the
three site servers are driven by DIFFERENT selectors, like real sites. It has a pay button; the tests assert it is never hit."""

from __future__ import annotations

import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

LOCATIONS = {"560034": "Koramangala, Bengaluru", "131001": "Sonipat, Haryana", "122001": "Gurgaon, Haryana",
             "koramangala": "Koramangala, Bengaluru"}
PRODUCTS = {
    "aashirvaad-atta-5kg": ("Aashirvaad Whole Wheat Atta", 289.0, 315.0, "5 kg", "4.5", False),
    "fortune-atta-5kg": ("Fortune Chakki Fresh Atta", 265.0, 290.0, "5 kg", "4.3", False),
    "pillsbury-atta-10kg": ("Pillsbury Atta", 540.0, 560.0, "10 kg", "4.1", True),
    "amul-milk-1l": ("Amul Taaza Milk", 56.0, 56.0, "1 L", "4.7", False),
}
OTP = "246810"


def skin_attr(skin: str, role: str) -> str:
    return {"testid": f'data-testid="{role}"', "class": f'class="{role}"', "qa": f'data-qa="{role}"'}[skin]


def skin_sel(skin: str, role: str) -> str:
    return {"testid": f"[data-testid={role}]", "class": f".{role}", "qa": f"[data-qa={role}]"}[skin]


def fake_kb(site: str, base_url: str, skin: str, *, proceed_verified: bool = True) -> dict[str, Any]:
    """A knowledge document (same schema as the real ones) matching the fake store's markup for this skin."""
    S = lambda r: skin_sel(skin, r)  # noqa: E731
    host = urlsplit(base_url).hostname or "127.0.0.1"
    return {
        "schema": 1, "site": site, "display": site.title(), "version": 1, "status": "unverified", "domains": [host],
        "base_url": base_url, "rate": {"min_interval_s": 0.0, "per_user_min_interval_s": 0.0, "max_wait_s": 5.0},
        "urls": {"home": "/", "search": "/search?query={query}", "cart": "/cart"},
        "blocked": {"markers": ["verify you are human", "access denied"], "selectors": ["iframe[src*=captcha]"], "cooldown_s": 600},
        "location": {"open": "", "input": S("loc-input"), "submit": S("loc-submit"), "suggestion": "", "current": S("location-bar"),
                     "not_found_markers": ["we are not here yet"]},
        "search": {"row": S("product-card"), "fields": {"title": S("product-name"), "price": S("product-price"), "pack": S("product-pack"),
                                                         "rating": S("product-rating"), "stock": S("out-of-stock"), "url": f"{S('product-name')}@href"},
                   "empty_markers": ["no results"]},
        "product": {"title": "h1", "price": S("product-price"), "mrp": S("product-mrp"), "pack": S("product-pack"), "rating": S("product-rating"),
                    "stock": S("out-of-stock"), "add": S("add-to-cart"), "qty_plus": S("qty-plus"), "oos_markers": ["out of stock"]},
        "cart": {"row": S("cart-item"), "fields": {"name": S("cart-item-name"), "qty": S("cart-item-qty"), "price": S("cart-item-price")},
                 "empty_markers": ["your cart is empty"]},
        "checkout": {"proceed": S("cart-proceed"), "proceed_verified": proceed_verified, "fee_row": S("bill-row"),
                     "fee_fields": {"label": S("bill-label"), "amount": S("bill-amount")}, "total": S("bill-total"), "payment_marker": S("payment-options")},
        "login": {"open": S("login-button"), "phone": "input[type=tel]", "send_otp": "form[action$=phone] button", "otp": "input[autocomplete=one-time-code]",
                  "verify": "form[action$=otp] button", "logged_in_marker": S("account-menu"), "logout": S("logout"), "wrong_otp_markers": ["invalid otp"]},
        "probe": {"public_pages": [{"id": "home", "path": "/", "selectors": [S("location-bar")]}]},
    }


class FakeStore:
    def __init__(self, skin: str = "testid") -> None:
        self.skin = skin
        self.mode = "ok"  # ok | challenge | denied | rate429
        self.robots = "User-agent: *\nDisallow: /private/\n"
        self.hits: list[str] = []
        self.payments = 0
        self.sessions: dict[str, dict[str, Any]] = {}
        self._n = 0
        self._httpd: ThreadingHTTPServer | None = None
        self.base_url = ""

    def start(self) -> str:
        store = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:  # noqa: ANN401
                pass

            def _sess(self) -> tuple[str, dict[str, Any], bool]:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sid" and v in store.sessions:
                        return v, store.sessions[v], False
                store._n += 1
                sid = f"s{store._n}"
                store.sessions[sid] = {"loc": "", "logged": False, "cart": {}, "phone": ""}
                return sid, store.sessions[sid], True

            def _send(self, sid: str, new: bool, body: str, code: int = 200, location: str | None = None) -> None:
                self.send_response(code)
                if location:
                    self.send_header("Location", location)
                if new:
                    self.send_header("Set-Cookie", f"sid={sid}; Path=/")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                data = body.encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _form(self) -> dict[str, str]:
                n = int(self.headers.get("Content-Length") or 0)
                return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode(), keep_blank_values=True).items()}

            def do_GET(self) -> None:  # noqa: N802
                self._route("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._route("POST")

            def _route(self, method: str) -> None:
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                store.hits.append(u.path)
                if u.path == "/robots.txt":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    data = store.robots.encode()
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                sid, s, new = self._sess()
                if store.mode == "challenge":
                    return self._send(sid, new, store.page("<h1>Verify you are human</h1><iframe src='/captcha'></iframe>"))
                if store.mode == "denied":
                    return self._send(sid, new, store.page("<h1>Access Denied</h1>"), 403)
                if store.mode == "rate429":
                    return self._send(sid, new, store.page("<p>slow down</p>"), 429)
                body = store.render(method, u.path, q, s, self._form() if method == "POST" else {})
                if isinstance(body, tuple):
                    return self._send(sid, new, "", 303, body[0])
                return self._send(sid, new, body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        return self.base_url

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    def __enter__(self) -> FakeStore:
        self.start()
        return self

    def __exit__(self, *a: Any) -> None:  # noqa: ANN401
        self.stop()

    # ------------------------------------------------------------------ pages
    def A(self, role: str) -> str:  # noqa: N802
        return skin_attr(self.skin, role)

    def page(self, body: str, s: dict[str, Any] | None = None) -> str:
        s = s or {"loc": "", "logged": False}
        loc = escape(LOCATIONS.get(s["loc"], "")) or "Select location"
        acct = f'<a {self.A("account-menu")} href="/">My account</a> <a {self.A("logout")} href="/logout">Logout</a>' if s["logged"] else f'<a {self.A("login-button")} href="/login">Login</a>'
        return (f"<!doctype html><html><head><title>FakeMart</title></head><body><header><span {self.A('location-bar')}>{loc}</span> "
                f"<form action='/loc' method='get'><input {self.A('loc-input')} name='q' type='text'><button {self.A('loc-submit')} type='submit'>Set</button></form>"
                f"{acct}</header>{body}</body></html>")

    def render(self, method: str, path: str, q: dict[str, str], s: dict[str, Any], form: dict[str, str]):  # noqa: ANN201
        A = self.A
        if path == "/":
            return self.page("<p>Welcome</p>", s)
        if path == "/loc":
            key = q.get("q", "").strip().lower()
            if key in LOCATIONS:
                s["loc"] = key
                return ("/",)
            return self.page("<p>We are not here yet</p>", s)
        if path == "/search":
            if not s["loc"]:
                return self.page("<p>Select a location first</p>", s)
            term = q.get("query", "").lower()
            rows = ""
            for pid, (title, price, _mrp, pack, rating, oos) in PRODUCTS.items():
                if term and any(w in (title + pid).lower() for w in term.split()):
                    rows += (f"<div {A('product-card')}><a {A('product-name')} href='/p/{pid}'>{escape(title)}</a> "
                             f"<span {A('product-price')}>Rs. {price:,.0f}</span> <span {A('product-pack')}>{pack}</span> "
                             f"<span {A('product-rating')}>{rating}</span>" + (f"<span {A('out-of-stock')}>Out of stock</span>" if oos else "") + "</div>")
            return self.page(rows or "<p>No results</p>", s)
        if path.startswith("/p/"):
            pid = path[3:]
            if pid not in PRODUCTS:
                return self.page("<p>Not found</p>", s)
            title, price, mrp, pack, rating, oos = PRODUCTS[pid]
            add = "" if oos else (f"<a {A('add-to-cart')} href='/cart/add?id={quote(pid)}'>Add</a> <a {A('qty-plus')} href='/cart/add?id={quote(pid)}'>+</a>")
            return self.page(f"<h1>{escape(title)}</h1><span {A('product-price')}>Rs. {price:,.0f}</span> <s {A('product-mrp')}>Rs. {mrp:,.0f}</s> "
                             f"<span {A('product-pack')}>{pack}</span> <span {A('product-rating')}>{rating}</span>"
                             + (f"<span {A('out-of-stock')}>Out of stock</span>" if oos else "") + add, s)
        if path == "/cart/add":
            pid = q.get("id", "")
            if pid in PRODUCTS:
                s["cart"][pid] = s["cart"].get(pid, 0) + 1
            return (f"/p/{pid}",)
        if path == "/cart":
            return self.page(self.cart_html(s), s)
        if path == "/checkout":
            if not s["logged"]:
                return self.page("<h1>Login to continue</h1><form action='/login/phone' method='post'><input type='tel' name='phone'><button type='submit'>Send code</button></form>", s)
            return self.page(self.cart_html(s, bill_only=True) + f"<div {A('payment-options')}>Choose payment: UPI, Card"
                             "<form action='/pay' method='post'><button class='pay-now' type='submit'>Pay now</button></form></div>", s)
        if path == "/pay":
            self.payments += 1
            return self.page("<h1>Order placed</h1>", s)
        if path == "/login":
            return self.page("<form action='/login/phone' method='post'><input type='tel' name='phone'><button type='submit'>Send code</button></form>", s)
        if path == "/login/phone":
            s["phone"] = form.get("phone", "")
            return self.page("<form action='/login/otp' method='post'><input autocomplete='one-time-code' name='otp'><button type='submit'>Verify</button></form>", s)
        if path == "/login/otp":
            if form.get("otp") == OTP:
                s["logged"] = True
                return ("/",)
            return self.page("<p>Invalid OTP</p>", s)
        if path == "/logout":
            s["logged"] = False
            return ("/",)
        return self.page("<p>Not found</p>", s)

    def cart_html(self, s: dict[str, Any], bill_only: bool = False) -> str:
        A = self.A
        if not s["cart"]:
            return "<p>Your cart is empty</p>"
        rows, sub = "", 0.0
        for pid, qty in s["cart"].items():
            title, price = PRODUCTS[pid][0], PRODUCTS[pid][1]
            sub += price * qty
            rows += f"<div {A('cart-item')}><span {A('cart-item-name')}>{escape(title)}</span> <span {A('cart-item-qty')}>{qty}</span> <span {A('cart-item-price')}>Rs. {price * qty:,.0f}</span></div>"
        delivery, handling = 0.0 if sub >= 199 else 25.0, 5.0
        bill = (f"<div {A('bill-row')}><span {A('bill-label')}>Item total</span><span {A('bill-amount')}>Rs. {sub:,.0f}</span></div>"
                f"<div {A('bill-row')}><span {A('bill-label')}>Delivery fee</span><span {A('bill-amount')}>Rs. {delivery:,.0f}</span></div>"
                f"<div {A('bill-row')}><span {A('bill-label')}>Handling fee</span><span {A('bill-amount')}>Rs. {handling:,.0f}</span></div>"
                f"<div {A('bill-total')}>To pay Rs. {sub + delivery + handling:,.0f}</div>")
        return (rows if not bill_only else "") + bill + ("" if bill_only else f"<a {A('cart-proceed')} href='/checkout'>Proceed</a>")
