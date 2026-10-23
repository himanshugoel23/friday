# ruff: noqa: E501
"""FAKE movie-ticket site: state + in-process BrowserSession. Invented films, cinemas, prices, codes.

Scenario knobs: ``taken_on_pick`` (a seat becomes taken once the user has approved, i.e. when the
first seat is picked), ``price_bump_pct`` (prices rise at the same moment), ``banner`` (page text,
used for prompt injection), ``block`` ("captcha"), ``renamed`` selectors (layout change).
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.contract import format_rupees
from friday.connectors.sites.movies.bookmyshow import EXTRA, SELECTORS

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
OTP = "864209"
FEE = 3000  # per ticket


class FakeMovieState:
    def __init__(self, *, otp: str = OTP, taken: set[str] | None = None,
                 taken_on_pick: set[str] | None = None, price_bump_pct: int = 0,
                 banner: str = "", block: str | None = None) -> None:
        self.otp, self.banner, self.block = otp, banner, block
        self.taken, self.taken_on_pick = set(taken or ()), set(taken_on_pick or ())
        self.price_bump_pct, self._bumped = price_bump_pct, False
        self.shows = [
            {"id": "s-1", "movie": "Pixel Heist", "cinema": "Fake Cinemas Sector 12",
             "area": "Sector 12", "time": "19:00"},
            {"id": "s-2", "movie": "Pixel Heist", "cinema": "Fake Cinemas Sector 12",
             "area": "Sector 12", "time": "21:30"},
            {"id": "s-3", "movie": "Moon Garden", "cinema": "Old Market Screens",
             "area": "Old Market", "time": "18:00"},
        ]
        self.price = {"A": 25000, "B": 35000}
        self.sessions: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}

    def new_session(self) -> str:
        sid = secrets.token_hex(8)
        self.sessions[sid] = {"phone": "", "otp_sent": False, "logged_in": False, "picked": [],
                              "show": ""}
        return sid

    def seats(self, show_id: str) -> list[dict]:
        return [{"id": f"{show_id}-{r}{n}", "label": f"{r}{n}",
                 "price": self.price[r], "free": f"{show_id}-{r}{n}" not in self.taken}
                for r in "AB" for n in range(1, 5)]

    def pick(self, sid: str, show_id: str, seat_id: str) -> None:
        s = self.sessions[sid]
        if self.price_bump_pct and not self._bumped:
            self._bumped = True
            self.price = {k: v * (100 + self.price_bump_pct) // 100 for k, v in self.price.items()}
        self.taken |= self.taken_on_pick
        if any(x["id"] == seat_id and x["free"] for x in self.seats(show_id)):
            if s["show"] != show_id:
                s["picked"] = []
            s["show"] = show_id
            if seat_id not in s["picked"]:
                s["picked"].append(seat_id)

    def summary(self, sid: str) -> dict:
        s = self.sessions[sid]
        by_id = {x["id"]: x for x in self.seats(s["show"])} if s["show"] else {}
        lines = [by_id[i] for i in s["picked"] if i in by_id]
        sub = sum(x["price"] for x in lines)
        fee = FEE * len(lines)
        tax = (fee * 18 + 50) // 100
        return {"lines": lines, "sub": sub, "fee": fee, "tax": tax, "total": sub + fee + tax}


class MovieSimSession:
    def __init__(self, state: FakeMovieState, renamed: dict[str, str] | None = None) -> None:
        self.state, self.sid = state, state.new_session()
        self._sel = {**SELECTORS, **EXTRA, "page_body": "body", **(renamed or {})}
        self.page, self.fills, self.calls = ("home", ""), {}, []
        self.closed = False

    @property
    def _s(self) -> dict:
        return self.state.sessions[self.sid]

    def _key(self, selector: str) -> tuple[str, str]:
        for key, sel in self._sel.items():
            if "{seat_id}" in sel:
                for show in self.state.shows:
                    for seat in self.state.seats(show["id"]):
                        if sel.format(seat_id=seat["id"]) == selector:
                            return key, seat["id"]
            elif sel == selector:
                return key, ""
        raise ElementNotFound(f"unknown selector: {selector}")

    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        u = urlsplit(url)
        parts = [unquote(p) for p in u.path.strip("/").split("/")]
        head, arg = parts[0] or "home", (parts[1] if len(parts) > 1 else "")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if head == "search":
            self.page = ("search", q.get("q", ""))
        elif head in {"summary", "show"} and not self._s["logged_in"] and head == "summary":
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
            s["phone"], s["otp_sent"] = self.fills.get("phone_input", ""), True
            self.page = ("otp", "")
        elif key == "submit_otp_button":
            ok = s["otp_sent"] and self.fills.pop("otp_input", "") == st.otp
            s["logged_in"] = bool(ok)
            self.page = ("home", "") if ok else ("otp_error", "")
        elif key == "seat_pick":
            st.pick(self.sid, self.page[1], arg)
        elif key == "hold_button":
            self.page = ("summary", "")
        elif key == "proceed_to_pay":
            ref = "BK" + secrets.token_hex(3).upper()
            st.orders[ref] = {"amount": st.summary(self.sid)["total"], "state": "Awaiting payment"}
            self.page = ("pay", ref)

    def _present(self, key: str) -> list[dict[str, str]]:
        st, (kind, arg), logged = self.state, self.page, self._s["logged_in"]
        if key == "page_body":
            if st.block == "captcha":
                return [{"text": "Please verify you are a human. Captcha"}]
            return [{"text": f"page {kind}\n{st.banner}".strip()}]
        if key == "banner":
            return [{"text": st.banner}] if st.banner else []
        if key == "account_name":
            return [{"text": "Test User"}] if logged else []
        if kind == "login" and key in {"phone_input", "send_otp_button"}:
            return [{"text": ""}]
        if kind in {"otp", "otp_error"} and key in {"otp_input", "submit_otp_button"}:
            return [{"text": ""}]
        if kind == "search" and key == "show_card":
            nq = "".join(c for c in arg.lower() if c.isalnum())
            return [{"show_id": x["id"], "movie": x["movie"], "cinema": x["cinema"],
                     "area": x["area"], "time": x["time"], "price": format_rupees(25000),
                     "text": x["movie"]} for x in st.shows
                    if nq and nq in "".join(c for c in x["movie"].lower() if c.isalnum())]
        if kind == "show":
            seats = st.seats(arg)
            if key == "seat":
                return [{"seat_id": x["id"], "label": x["label"], "price": format_rupees(x["price"]),
                         "available": "true" if x["free"] else "false", "text": x["label"]}
                        for x in seats]
            if key in {"seat_pick", "hold_button"}:
                return [{"text": ""}]
        if kind == "summary" and logged:
            v = st.summary(self.sid)
            if not v["lines"]:
                return []
            if key == "summary_line":
                return [{"seat_id": x["id"], "label": x["label"], "price": format_rupees(x["price"]),
                         "text": x["label"]} for x in v["lines"]]
            if key == "summary_fee_row":
                return [{"name": "Booking fee", "amount": format_rupees(v["fee"]), "text": "fee"}]
            if key == "summary_tax_row":
                return [{"name": "GST", "amount": format_rupees(v["tax"]), "text": "tax"}]
            if key == "summary_total":
                return [{"text": format_rupees(v["total"])}]
            if key == "proceed_to_pay":
                return [{"text": ""}]
        if kind == "pay" and arg in st.orders:
            amt = st.orders[arg]["amount"]
            t = {"pay_amount": {"text": format_rupees(amt)},
                 "pay_merchant": {"text": "FakeTix Pvt Ltd"}, "pay_order_ref": {"text": arg},
                 "pay_qr": {"text": "", "src": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                 "pay_upi_link": {"text": "Pay", "href":
                                  f"upi://pay?pa=faketix@fakebank&pn=FakeTix&am={amt / 100:.2f}&cu=INR&tr={arg}"}}
            return [t[key]] if key in t else []
        if kind == "booking" and arg in st.orders and key == "booking_state":
            return [{"text": st.orders[arg]["state"]}]
        return []

    def _require(self, key: str) -> list[dict[str, str]]:
        rows = self._present(key)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    async def text(self, selector: str) -> str:
        return self._require(self._key(selector)[0])[0]["text"]

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None
                        ) -> list[dict[str, str]]:
        try:
            key = self._key(selector)[0]
        except ElementNotFound:
            return []
        return self._present(key)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        self._require(self._key(selector)[0])

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True
