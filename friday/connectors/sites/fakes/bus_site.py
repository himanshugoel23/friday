# ruff: noqa: E501
"""FAKE bus sites (redBus-like, AbhiBus-like): two different selector dialects and URL shapes.

Like fakes/stay_site.py this file spells the selectors and paths out independently of the adapters.
Invented operators, seats, prices and codes. Knobs (``make_session(key, **knobs)``): ``taken`` (seat
ids taken from the start), ``taken_on_pick`` (taken once the first seat is picked, i.e. after the
user approved), ``price_bump_pct`` (prices rise at the first seat pick), ``hold_s`` (seconds the
site shows on the hold timer), ``hold_lapse`` (the hold is released after that many timer reads,
0 = never), ``pay_bump_pct`` (the pay page asks more than the held summary), ``name_injection`` (text appended to the first operator), ``banner``, ``block``
("captcha"), ``block_at`` ("any" | "review"), ``renamed``.
"""

from __future__ import annotations

import base64
import re
import secrets
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.sites.fakes.stay_site import ATTRS, OTP, PNG, Layout

KNOWN_FIELDS = ATTRS | {"name", "price", "label", "time", "depart", "window", "amount"}
PLAIN = ("account_name", "phone_input", "send_otp_button", "otp_input", "submit_otp_button",
         "result_card", "seat", "boarding_option", "dropping_option", "cancel_policy_row",
         "hold_button", "hold_timer", "review_line", "review_fee_row", "review_tax_row",
         "review_total", "proceed_to_pay", "pay_amount", "pay_merchant", "pay_order_ref",
         "pay_qr", "pay_upi_link")
PARAM = {"seat_pick": "seat_id", "boarding_pick": "point_id", "dropping_pick": "point_id",
         "passenger_name_input": "n"}
ALT_KEYS = ("hold_button", "proceed_to_pay")
DIALECTS = {
    "redbus": ("[data-rb={d}]", "[data-rb={d}]", "data-rb-{d}", "snake",
               {"hold_button": "button#rb-block-seat", "review_total": "[data-rb=payable_amount]"},
               lambda r: f"INR {r:,}"),
    "abhibus": (".ab-{d}", "span.ab-{d}", "data-ab-{d}", "dash",
                {"result_card": "li.ab-service-row", "review_total": ".ab-payable"},
                lambda r: f"Rs.{r}"),
}
PAGES = {
    "redbus": {"home": "/", "login": "/signin",
               "search": "/search?fromCityName={origin}&toCityName={destination}&onward={date}",
               "detail": "/bus-tickets/{item_id}?fromCityName={origin}&toCityName={destination}&onward={date}"},
    "abhibus": {"home": "/", "login": "/user/login",
                "search": "/booking/bus-search?src={origin}&dst={destination}&doj={date}",
                "detail": "/booking/seat-layout/{item_id}?src={origin}&dst={destination}&doj={date}"},
}
CITIES = {"bengaluru", "hyderabad", "chennai", "pune"}
BUSES = [("b-1", "Fake Travels Volvo", "sleeper-ac", "22:00", 120000),
         ("b-2", "Hill Express", "seater-nonac", "20:30", 70000),
         ("b-3", "Night Rider", "sleeper-nonac", "23:15", 95000),
         ("b-4", "Royal Cruiser", "seater-ac", "21:00", 90000)]
BOARDING = [("pb-1", "Majestic Bus Stand", "21:30"), ("pb-2", "Silk Board", "22:15")]
DROPPING = [("pd-1", "Hyderabad MG Bus Station", "06:00"), ("pd-2", "Miyapur Metro", "05:30")]
POLICY = [("Up to 24 hours before departure", "90"), ("12 to 24 hours before departure", "50"),
          ("Within 12 hours of departure", "0")]
SEAT_LABELS = [f"{r}{n}" for r in "AB" for n in range(1, 5)]
FEE = 3000  # per seat


def _r(x: int) -> int:
    return x // 100 * 100


class FakeBusState:
    def __init__(self, site: str, *, otp: str = OTP, taken: set[str] | None = None,
                 taken_on_pick: set[str] | None = None, price_bump_pct: int = 0, hold_s: int = 600,
                 hold_lapse: int = 0, pay_bump_pct: int = 0, name_injection: str = "", banner: str = "",
                 block: str | None = None, block_at: str = "any") -> None:
        self.site, self.otp, self.banner, self.block, self.block_at = site, otp, banner, block, block_at
        self.taken, self.taken_on_pick = set(taken or ()), set(taken_on_pick or ())
        self.price_bump_pct, self.hold_s, self.hold_lapse = price_bump_pct, hold_s, hold_lapse
        self.pay_bump_pct = pay_bump_pct
        self.name_injection, self.bumped, self.timer_reads = name_injection, False, 0
        self.sessions: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}

    def new_session(self) -> str:
        sid = secrets.token_hex(8)
        self.sessions[sid] = {"otp_sent": False, "logged_in": False, "bus": "", "picked": [],
                              "board": "", "drop": "", "names": {}, "held": False}
        return sid

    def buses(self) -> list[tuple[str, str, str, str, int]]:
        out = []
        for bid, name, kind, dep, price in BUSES:
            out.append((bid, f"{name}. {self.name_injection}" if self.name_injection else name,
                        kind, dep, self._price(price)))
        return out

    def _price(self, p: int) -> int:
        return _r(p * (100 + self.price_bump_pct) // 100) if self.bumped else p

    def seats(self, bus: str) -> list[dict]:
        row = next(b for b in self.buses() if b[0] == bus)
        kind = row[2].split("-")[0]
        return [{"id": f"{bus}-{lab}", "label": lab, "kind": kind, "price": row[4],
                 "free": f"{bus}-{lab}" not in self.taken} for lab in SEAT_LABELS]


class BusSimSession:
    def __init__(self, state: FakeBusState, renamed: Mapping[str, str] | None = None) -> None:
        self.state, self.sid = state, state.new_session()
        self.layout = Layout(state.site, renamed, DIALECTS)
        self.pages = PAGES[state.site]
        self._sel = {k: self.layout.selector(k) for k in PLAIN}
        self._sel.update({k: self.layout.param(k, p) for k, p in PARAM.items()})
        self._alt = {self.layout.alt(k): k for k in ALT_KEYS}
        self._rx = {k: (re.compile(re.escape(v).replace(r"\{" + PARAM[k] + r"\}", r"(?P<arg>[^'\"\]]+)") + "$")
                        if k in PARAM else None) for k, v in self._sel.items()}
        self.page, self.ctx, self.fills, self.calls, self.closed = ("home", ""), {}, {}, [], False

    @property
    def _s(self) -> dict:
        return self.state.sessions[self.sid]

    def _key(self, selector: str) -> tuple[str, str]:
        if selector in self._alt:
            return self._alt[selector], ""
        for key, sel in self._sel.items():
            rx = self._rx.get(key)
            if rx is not None:
                m = rx.match(selector)
                if m:
                    return key, m.group("arg")
            elif sel == selector:
                return key, ""
        if selector == "body":
            return "page_body", ""
        raise ElementNotFound(f"unknown selector: {selector}")

    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        u = urlsplit(url)
        q = {k: unquote(v[0]) for k, v in parse_qs(u.query).items()}
        for name, tpl in self.pages.items():
            tpath, _, tquery = tpl.partition("?")
            m = re.fullmatch(re.sub(r"\\\{item_id\\\}", "(?P<arg>[^/]+)", re.escape(tpath)), unquote(u.path))
            if not m:
                continue
            logical = {}
            for pair in tquery.split("&") if tquery else []:
                pname, _, ph = pair.partition("=")
                logical[ph.strip("{}")] = q.get(pname, "")
            if logical:
                self.ctx = logical
            self.page = (name, m.groupdict().get("arg", ""))
            return
        self.page = ("notfound", "")

    async def fill(self, selector: str, value: str) -> None:
        key, arg = self._key(selector)
        self._require(key)
        self.calls.append(f"fill:{key}")
        self.fills[key + arg] = value
        if key == "passenger_name_input":
            self._s["names"][arg] = value

    async def click(self, selector: str) -> None:
        key, arg = self._key(selector)
        self._require(key)
        self.calls.append(f"click:{key}")
        st, s = self.state, self._s
        if key == "send_otp_button":
            s["otp_sent"] = True
            self.page = ("otp", "")
        elif key == "submit_otp_button":
            ok = s["otp_sent"] and self.fills.pop("otp_input", "") == st.otp
            s["logged_in"] = bool(ok)
            self.page = ("home", "") if ok else ("otp_error", "")
        elif key == "seat_pick":
            if st.price_bump_pct and not st.bumped:
                st.bumped = True
            st.taken |= st.taken_on_pick
            if s["bus"] != self.page[1]:
                s["bus"], s["picked"] = self.page[1], []
            if any(x["id"] == arg and x["free"] for x in st.seats(self.page[1])) and arg not in s["picked"]:
                s["picked"].append(arg)
        elif key == "boarding_pick":
            s["board"] = arg
        elif key == "dropping_pick":
            s["drop"] = arg
        elif key == "hold_button":
            if (s["picked"] and s["board"] and s["drop"] and len(s["names"]) >= len(s["picked"])
                    and s["logged_in"]):
                s["held"] = True
                st.timer_reads = 0
                self.page = ("review", "")
        elif key == "proceed_to_pay" and s["held"]:
            ref = "BS" + secrets.token_hex(3).upper()
            amt = self._review()["total"] * (100 + st.pay_bump_pct) // 100 // 100 * 100
            st.orders[ref] = {"amount": amt, "state": "Awaiting payment"}
            self.page = ("pay", ref)

    def _review(self) -> dict:
        st, s = self.state, self._s
        by = {x["id"]: x for x in st.seats(s["bus"])}
        lines = [by[i] for i in s["picked"] if i in by]
        sub = sum(x["price"] for x in lines)
        fee = FEE * len(lines)
        tax = _r((sub + fee) * 5 // 100)
        return {"lines": lines, "sub": sub, "fee": fee, "tax": tax, "total": sub + fee + tax}

    def _m(self, paise: int) -> str:
        return self.layout.fmt(paise // 100)

    def _present(self, key: str) -> list[dict[str, str]]:
        st, (kind, arg), s = self.state, self.page, self._s
        if key == "page_body":
            if st.block and (st.block_at == "any" or kind in {"review", "pay"}):
                return [{"text": "Please verify you are a human. Captcha"}]
            return [{"text": f"page {kind}\n{st.banner}".strip()}]
        if key == "account_name":
            return [{"text": "Test User"}] if s["logged_in"] else []
        if kind == "login" and key in {"phone_input", "send_otp_button"}:
            return [{"text": ""}]
        if kind in {"otp", "otp_error"} and key in {"otp_input", "submit_otp_button"}:
            return [{"text": ""}]
        if kind == "search" and key == "result_card":
            if self.ctx.get("origin", "").lower() not in CITIES or self.ctx.get("destination", "").lower() not in CITIES:
                return []
            return [{"item_id": b, "name": n, "kind": k, "depart": d, "price": self._m(p), "text": n}
                    for b, n, k, d, p in st.buses()]
        if kind == "detail":
            seats = st.seats(arg)
            rows = {"seat": [{"seat_id": x["id"], "label": x["label"], "kind": x["kind"], "price": self._m(x["price"]),
                              "available": "true" if x["free"] else "false", "text": x["label"]} for x in seats],
                    "boarding_option": [{"point_id": i, "name": n, "time": t, "text": n} for i, n, t in BOARDING],
                    "dropping_option": [{"point_id": i, "name": n, "time": t, "text": n} for i, n, t in DROPPING],
                    "cancel_policy_row": [{"window": w, "pct": p, "text": w} for w, p in POLICY]}
            if key in rows:
                return rows[key]
            if key in {"seat_pick", "boarding_pick", "dropping_pick", "hold_button"}:
                return [{"text": ""}]
            if key == "passenger_name_input":
                return [{"text": ""}]
        if kind == "review" and s["held"]:
            if key == "hold_timer":
                st.timer_reads += 1
                if st.hold_lapse and st.timer_reads > st.hold_lapse:
                    s["held"] = False  # the site released the seats
                    return [{"seconds": "0", "text": "0"}]
                return [{"seconds": str(st.hold_s), "text": str(st.hold_s)}]
            v = self._review()
            if key == "review_line":
                return [{"seat_id": x["id"], "label": x["label"], "price": self._m(x["price"]), "text": x["label"]} for x in v["lines"]]
            if key == "review_fee_row":
                return [{"name": "Convenience fee", "amount": self._m(v["fee"]), "text": "fee"}]
            if key == "review_tax_row":
                return [{"name": "GST", "amount": self._m(v["tax"]), "text": "tax"}]
            if key == "review_total":
                return [{"text": self._m(v["total"]), "currency": "INR"}]
            if key == "proceed_to_pay":
                return [{"text": ""}]
        if kind == "review" and key == "hold_timer":
            return [{"seconds": "0", "text": "0"}]
        if kind == "pay" and arg in st.orders:
            amt = st.orders[arg]["amount"]
            t = {"pay_amount": {"text": self._m(amt), "currency": "INR"},
                 "pay_merchant": {"text": "FakeBus Pvt Ltd"}, "pay_order_ref": {"text": arg},
                 "pay_qr": {"text": "", "src": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                 "pay_upi_link": {"text": "Pay", "href":
                                  f"upi://pay?pa=fakebus@fakebank&pn=FakeBus&am={amt / 100:.2f}&cu=INR&tr={arg}"}}
            return [t[key]] if key in t else []
        return []

    def _require(self, key: str) -> list[dict[str, str]]:
        rows = self._present(key)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    async def text(self, selector: str) -> str:
        return self._require(self._key(selector)[0])[0]["text"]

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None) -> list[dict[str, str]]:
        try:
            key = self._key(selector)[0]
        except ElementNotFound:
            return []
        for f, spec in (fields or {}).items():
            if f in KNOWN_FIELDS and spec != self.layout.field(f):
                return []
        return self._present(key)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        self._require(self._key(selector)[0])

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True


def make_session(key: str, *, renamed: Mapping[str, str] | None = None, **knobs) -> BusSimSession:  # noqa: ANN003
    """``key`` is an adapter key such as ``"redbus.bus"``."""
    return BusSimSession(FakeBusState(key.split(".")[0], **knobs), renamed)
