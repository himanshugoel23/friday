"""Tiny stdlib HTTP server for the fake site (no deps, own thread, localhost only)."""

from __future__ import annotations

import base64
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from friday.connectors.fake_site.catalog import (
    FAKE_MERCHANT_VPA,
    FAKE_QR_PNG,
    FakeSiteState,
    format_rupees,
)


def _page(logged_in: bool, body: str) -> bytes:
    who = (
        '<span data-testid="account-name">Test User</span>'
        if logged_in else '<a data-testid="login-link" href="/login">Log in</a>'
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>FakeEats</title></head><body>"
        f"<header><a href='/'>FakeEats</a> {who} <a href='/cart'>Cart</a></header>"
        f"{body}</body></html>"
    )
    return html.encode()


class FakeSiteServer:
    """``with FakeSiteServer(state) as base_url:`` serves the fake site on 127.0.0.1."""

    def __init__(self, state: FakeSiteState | None = None) -> None:
        self.state = state or FakeSiteState()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:  # noqa: ANN002 - silence
                pass

            # ---- plumbing
            def _sid(self) -> tuple[str, bool]:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "fsid" and state.session(v):
                        return v, False
                return state.new_session(), True

            def _send(self, sid: str, new: bool, body: bytes, code: int = 200,
                      location: str | None = None) -> None:
                self.send_response(code)
                if location:
                    self.send_header("Location", location)
                if new:
                    self.send_header("Set-Cookie", f"fsid={sid}; Path=/; HttpOnly")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, sid: str, new: bool, to: str) -> None:
                self._send(sid, new, b"", 303, to)

            def _form(self) -> dict[str, str]:
                n = int(self.headers.get("Content-Length") or 0)
                raw = parse_qs(self.rfile.read(n).decode(), keep_blank_values=True)
                return {k: v[0] for k, v in raw.items()}

            # ---- routes
            def do_GET(self) -> None:  # noqa: N802
                sid, new = self._sid()
                s = state.session(sid)
                logged = bool(s and s.logged_in)
                url = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                path = url.path
                if path == "/":
                    self._send(sid, new, _page(logged, "<h1>Order food</h1>"))
                elif path == "/search":
                    cards = "".join(
                        f'<div data-testid="restaurant-card" data-restaurant-id="{r["id"]}">'
                        f'<a href="/restaurant/{r["id"]}" data-testid="restaurant-name">'
                        f'{escape(r["name"])}</a>'
                        f'<span data-testid="restaurant-area">{escape(r["area"])}</span>'
                        f'<span data-testid="restaurant-rating">{r["rating"]}</span></div>'
                        for r in state.search(q.get("q", ""))
                    )
                    self._send(sid, new, _page(logged, f"<h1>Results</h1>{cards}"))
                elif path.startswith("/restaurant/"):
                    rid = path.rsplit("/", 1)[1]
                    r = state.restaurant(rid)
                    if not r:
                        self._send(sid, new, _page(logged, "not found"), 404)
                        return
                    items = "".join(
                        f'<div data-testid="menu-item" data-item-id="{m["id"]}" '
                        f'data-veg="{"true" if m["veg"] else "false"}">'
                        f'<span data-testid="item-name">{escape(m["name"])}</span>'
                        f'<span data-testid="item-price">{format_rupees(m["price"])}</span>'
                        f'<form method="post" action="/cart/add">'
                        f'<input type="hidden" name="restaurant_id" value="{rid}">'
                        f'<input type="hidden" name="item_id" value="{m["id"]}">'
                        f'<input data-testid="qty-input" name="qty" value="1">'
                        f'<button data-testid="add-button" type="submit">Add</button></form></div>'
                        for m in state.menus[rid]
                    )
                    self._send(sid, new, _page(logged, f"<h1>{escape(r['name'])}</h1>{items}"))
                elif path == "/login":
                    self._send(sid, new, _page(logged, _phone_form()))
                elif path == "/cart":
                    if not logged:
                        self._redirect(sid, new, "/login")
                        return
                    self._send(sid, new, _page(logged, _cart_html(state, sid)))
                elif path.startswith("/pay/"):
                    ref = path.rsplit("/", 1)[1]
                    o = state.orders.get(ref)
                    if not (logged and o):
                        self._send(sid, new, _page(logged, "not found"), 404)
                        return
                    self._send(sid, new, _page(logged, _pay_html(ref, o["amount"])))
                elif path.startswith("/order/"):
                    ref = path.rsplit("/", 1)[1]
                    o = state.orders.get(ref)
                    if not o:
                        self._send(sid, new, _page(logged, "not found"), 404)
                        return
                    self._send(sid, new, _page(
                        logged,
                        f'<div data-testid="order-state">{escape(o["state"])}</div>'
                        f'<div data-testid="order-eta">{o["eta"]} min</div>'))
                else:
                    self._send(sid, new, _page(logged, "not found"), 404)

            def do_POST(self) -> None:  # noqa: N802
                sid, new = self._sid()
                form = self._form()
                path = urlsplit(self.path).path
                s = state.session(sid)
                if path == "/login/phone":
                    state.send_otp(sid, form.get("phone", ""))
                    self._send(sid, new, _page(False, _otp_form()))
                elif path == "/login/otp":
                    if state.check_otp(sid, form.get("otp", "")):
                        self._redirect(sid, new, "/")
                    else:
                        self._send(sid, new, _page(
                            False, '<p data-testid="login-error">That code did not work</p>'
                            + _otp_form()))
                elif path == "/cart/add" and s and s.logged_in:
                    try:
                        qty = int(form.get("qty", "1"))
                    except ValueError:
                        qty = 0
                    rid = form.get("restaurant_id", "")
                    state.add(sid, rid, form.get("item_id", ""), qty)
                    self._redirect(sid, new, f"/restaurant/{quote(rid)}")
                elif path == "/cart/clear" and s and s.logged_in:
                    state.clear(sid)
                    self._redirect(sid, new, "/cart")
                elif path == "/checkout" and s and s.logged_in:
                    ref = state.checkout(sid)
                    self._redirect(sid, new, f"/pay/{ref}" if ref else "/cart")
                else:
                    self._redirect(sid, new, "/login")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> str:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _phone_form() -> str:
    return (
        '<form method="post" action="/login/phone">'
        '<input data-testid="phone-input" name="phone">'
        '<button data-testid="send-otp-button" type="submit">Send code</button></form>'
    )


def _otp_form() -> str:
    return (
        '<form method="post" action="/login/otp">'
        '<input data-testid="otp-input" name="otp">'
        '<button data-testid="submit-otp-button" type="submit">Verify</button></form>'
    )


def _cart_html(state: FakeSiteState, sid: str) -> str:
    v = state.cart_view(sid)
    rows = "".join(
        f'<div data-testid="cart-line" data-item-id="{line["item_id"]}">'
        f'<span data-testid="line-name">{escape(line["name"])}</span>'
        f'<span data-testid="line-qty">{line["qty"]}</span>'
        f'<span data-testid="line-total">{format_rupees(line["line_total_paise"])}</span></div>'
        for line in v.lines
    )

    def charges(kind: str, items: list[tuple[str, int]]) -> str:
        return "".join(
            f'<div data-testid="{kind}-row"><span data-testid="charge-name">{escape(n)}</span>'
            f'<span data-testid="charge-amount">{format_rupees(a)}</span></div>'
            for n, a in items
        )

    disc = (
        f'<div data-testid="cart-discount">-{format_rupees(v.discount_paise)}</div>'
        if v.discount_paise else ""
    )
    return (
        f"<h1>Your cart</h1>{rows}"
        f'<div data-testid="cart-subtotal">{format_rupees(v.subtotal_paise)}</div>'
        f'{charges("fee", v.fees)}{charges("tax", v.taxes)}{disc}'
        f'<div data-testid="cart-grand-total">{format_rupees(v.grand_total_paise)}</div>'
        '<form method="post" action="/cart/clear">'
        '<button data-testid="clear-cart" type="submit">Clear</button></form>'
        '<form method="post" action="/checkout">'
        '<button data-testid="checkout-button" type="submit">Proceed to pay</button></form>'
    )


def _pay_html(ref: str, amount: int) -> str:
    qr = base64.b64encode(FAKE_QR_PNG).decode()
    link = f"upi://pay?pa={FAKE_MERCHANT_VPA}&pn=FakeEats&am={amount / 100:.2f}&cu=INR&tr={ref}"
    return (
        f'<div data-testid="pay-order-ref">{ref}</div>'
        f'<div data-testid="pay-amount">{format_rupees(amount)}</div>'
        '<div data-testid="pay-merchant">FakeEats Pvt Ltd</div>'
        f'<img data-testid="pay-qr" alt="Scan to pay" src="data:image/png;base64,{qr}">'
        f'<a data-testid="pay-upi-link" href="{escape(link)}">Pay with UPI app</a>'
    )
