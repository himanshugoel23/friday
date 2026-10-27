# ruff: noqa: E501
"""FAKE stay sites (hotel + flight) for makemytrip, goibibo, booking, agoda, oyo, cleartrip.

One in-process engine, six DIFFERENT sites: each site has its own selector dialect, its own URL
shapes and query-parameter names, its own money format. This file spells them out independently of
stay/*.py (it does not import the adapters' selector maps), so a selector or path that drifts in an
adapter makes the fake answer "not on this page" and the tests fail. Invented hotels, flights,
prices and codes; not any real site.

Knobs (``make_session(key, **knobs)``): ``sold_out`` (variant ids sold out from the start),
``sold_on_pick`` (variants that sell out the moment the user has approved and the first pick is
made), ``price_bump_pct`` + ``bump_at`` ("select" | "pay"), ``currency`` ("USD": prices in a foreign
currency), ``preselect_addons`` (the site pre-ticks baggage and meal), ``name_injection`` (text
appended to the first hotel / airline name), ``banner`` (page text), ``block`` ("captcha") with
``block_at`` ("any" | "review"), ``renamed`` (logical key -> selector, a layout change), ``free_days`` (days before check-in / departure the free cancellation ends), ``free_days_on_pick``
(the same, changed once the user has approved: worse terms).
"""

from __future__ import annotations

import base64
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
OTP = "864209"
ATTRS = {"item_id", "variant_id", "seat_id", "point_id", "addon_id", "currency", "free_until",
         "nonrefundable", "sold_out", "checked", "available", "seconds", "kind", "pct"}
KNOWN_FIELDS = ATTRS | {"name", "price", "rating", "base", "fees", "taxes", "amount"}
PLAIN = ("account_name", "phone_input", "send_otp_button", "otp_input", "submit_otp_button",
         "result_card", "variant_row", "reserve_button", "review_line", "review_fee_row",
         "review_tax_row", "review_total", "review_policy", "guest_name_input", "proceed_to_pay",
         "addon_row", "pay_amount", "pay_merchant", "pay_order_ref", "pay_qr", "pay_upi_link")
PARAM = {"variant_pick": "variant_id", "addon_toggle": "addon_id", "passenger_name_input": "n"}
ALT_KEYS = ("reserve_button", "proceed_to_pay")

# site -> (element selector, row sub-selector, attribute, case, per-site quirks, money format)
DIALECTS = {
    "makemytrip": ("[data-testid={d}]", "[data-testid={d}]", "data-{d}", "dash",
                   {"result_card": "[data-testid=listing-card]", "reserve_button": "[data-testid=book-room-cta]"},
                   lambda r: f"₹ {r:,}"),
    "goibibo": (".gi-{d}", ".gi-{d}", "data-gi-{d}", "dash",
                {"review_total": ".gi-grand-total", "reserve_button": "button.gi-book-room"},
                lambda r: f"Rs. {r:,}"),
    "booking": ("[data-ba={d}]", "[data-ba={d}]", "data-ba-{d}", "camel",
                {"result_card": "[data-ba=propertyCard]", "guest_name_input": "input[name=booker_name]"},
                lambda r: f"INR {r:,}"),
    "agoda": ("[data-selenium={d}]", "[data-selenium={d}]", "data-ag-{d}", "snake",
              {"account_name": "#ag_user_name", "review_total": "[data-selenium=grand_total_amount]"},
              lambda r: f"₹{r:,}"),
    "oyo": ("[class~=oyo-{d}]", "span.o-{d}", "data-oyo-{d}", "dash",
            {"phone_input": "input#oyo-mobile", "send_otp_button": "button#oyo-get-otp"},
            lambda r: f"₹{r}"),
    "cleartrip": ("[data-cy=ct-{d}]", "[data-cy=ct-f-{d}]", "data-ct-{d}", "dash",
                  {"pay_qr": "img[data-cy=ct-upi-qr]"}, lambda r: f"Rs {r:,}.00"),
}
FOREIGN = lambda r, cur: f"{'US$' if cur == 'USD' else cur} {r:,.2f}"  # noqa: E731

# site -> page -> URL template (path?query); {names} are the logical parameters
PAGES = {
    "makemytrip": {
        "home": "/", "login": "/login",
        "search_hotel": "/hotels/search?city={destination}&checkin={checkin}&checkout={checkout}&roomCount={rooms}&guests={guests}",
        "detail_hotel": "/hotels/detail/{item_id}?city={destination}&checkin={checkin}&checkout={checkout}&roomCount={rooms}&guests={guests}",
        "search_flight": "/flights/search?from={origin}&to={destination}&depart={depart}&return={return_date}&tripType={trip}&pax={adults}",
        "detail_flight": "/flights/fare/{item_id}?from={origin}&to={destination}&depart={depart}&return={return_date}&tripType={trip}&pax={adults}"},
    "goibibo": {
        "home": "/", "login": "/accounts/login",
        "search_hotel": "/hotels/results/?dest={destination}&ci={checkin}&co={checkout}&rms={rooms}&gst={guests}",
        "detail_hotel": "/hotels/property/{item_id}/?dest={destination}&ci={checkin}&co={checkout}&rms={rooms}&gst={guests}",
        "search_flight": "/flight/results/?src={origin}&dst={destination}&dep={depart}&ret={return_date}&type={trip}&adt={adults}",
        "detail_flight": "/flight/offer/{item_id}/?src={origin}&dst={destination}&dep={depart}&ret={return_date}&type={trip}&adt={adults}"},
    "booking": {
        "home": "/index.html", "login": "/signin.html",
        "search_hotel": "/searchresults.html?ss={destination}&checkin={checkin}&checkout={checkout}&no_rooms={rooms}&group_adults={guests}&selected_currency=INR",
        "detail_hotel": "/hotel/in/{item_id}.html?ss={destination}&checkin={checkin}&checkout={checkout}&no_rooms={rooms}&group_adults={guests}&selected_currency=INR"},
    "agoda": {
        "home": "/", "login": "/account/signin.html",
        "search_hotel": "/search?textToSearch={destination}&checkIn={checkin}&checkOut={checkout}&rooms={rooms}&adults={guests}",
        "detail_hotel": "/hotel-room/{item_id}?textToSearch={destination}&checkIn={checkin}&checkOut={checkout}&rooms={rooms}&adults={guests}"},
    "oyo": {
        "home": "/", "login": "/login-oyo",
        "search_hotel": "/hotels-in-city/?location={destination}&checkin={checkin}&checkout={checkout}&roomConfig={rooms}&guests={guests}",
        "detail_hotel": "/rooms/{item_id}/?location={destination}&checkin={checkin}&checkout={checkout}&roomConfig={rooms}&guests={guests}"},
    "cleartrip": {
        "home": "/", "login": "/signin",
        "search_hotel": "/hotels/results?q={destination}&from={checkin}&to={checkout}&rooms={rooms}&adults={guests}",
        "detail_hotel": "/hotels/info/{item_id}?q={destination}&from={checkin}&to={checkout}&rooms={rooms}&adults={guests}",
        "search_flight": "/flights/results?origin={origin}&destination={destination}&depart_date={depart}&return_date={return_date}&trip={trip}&adults={adults}",
        "detail_flight": "/flights/itinerary/{item_id}?origin={origin}&destination={destination}&depart_date={depart}&return_date={return_date}&trip={trip}&adults={adults}"},
}

CITIES = {"jaipur", "goa", "delhi", "mumbai", "bengaluru"}
HOTELS = [("h-1", "Lakeview Residency", 320000, "4.3"), ("h-2", "Sunrise Inn", 180000, "3.9"),
          ("h-3", "Grand Fake Palace", 950000, "4.7"), ("h-4", "Budget Nest", 90000, "3.4"),
          ("h-5", "Old Town Haveli", 410000, "4.5"), ("h-6", "Station Lodge", 150000, "3.6")]
FLIGHTS = [("f-1", "AirFake 101", 450000, "4.0"), ("f-2", "SkyDemo 202", 520000, "4.1"),
           ("f-3", "Budget Wings 303", 380000, "3.5"), ("f-4", "Prime Air 404", 1250000, "4.6")]
ADDONS = [("ad-bag", "Extra baggage", 60000), ("ad-meal", "In-flight meal", 30000)]
SERVICE_NAME = {"hotel": "Service fee", "flight": "Convenience fee"}


def _c(word: str, case: str) -> str:
    p = word.split("_")
    return "-".join(p) if case == "dash" else (p[0] + "".join(x.title() for x in p[1:]) if case == "camel" else "_".join(p))


class Layout:
    def __init__(self, site: str, renamed: Mapping[str, str] | None = None,
                 table: Mapping[str, tuple] | None = None) -> None:
        self.sel_f, self.fld_f, self.attr_f, self.case, self.quirks, self.fmt = (table or DIALECTS)[site]
        self.renamed = dict(renamed or {})

    def selector(self, key: str) -> str:
        return self.renamed.get(key) or self.quirks.get(key) or self.sel_f.format(d=_c(key, self.case))

    def param(self, key: str, p: str) -> str:
        return self.selector(key) + f"[{self.attr_f.format(d=_c(p, self.case))}='{{{p}}}']"

    def field(self, name: str) -> str:
        if name in ATTRS:
            return "@" + self.attr_f.format(d=_c(name, self.case))
        return self.fld_f.format(d=_c(name, self.case))

    def alt(self, key: str) -> str:
        return self.sel_f.format(d=_c(key + "_alt", self.case))


class FakeStayState:
    def __init__(self, site: str, *, otp: str = OTP, sold_out: set[str] | None = None,
                 sold_on_pick: set[str] | None = None, price_bump_pct: int = 0, bump_at: str = "select",
                 currency: str = "INR", preselect_addons: bool = False, name_injection: str = "",
                 banner: str = "", block: str | None = None, block_at: str = "any",
                 free_days: int = 2, free_days_on_pick: int | None = None) -> None:
        self.site, self.otp, self.banner, self.block, self.block_at = site, otp, banner, block, block_at
        self.sold_out, self.sold_on_pick = set(sold_out or ()), set(sold_on_pick or ())
        self.price_bump_pct, self.bump_at, self.currency = price_bump_pct, bump_at, currency
        self.preselect_addons, self.name_injection, self.free_days = preselect_addons, name_injection, free_days
        self.free_days_on_pick = free_days_on_pick
        self.bumped = False
        self.sessions: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}

    def new_session(self) -> str:
        sid = secrets.token_hex(8)
        self.sessions[sid] = {"otp_sent": False, "logged_in": False, "variant": "", "item": "",
                              "ctx": {}, "addons": set(), "names": {}}
        return sid

    # ---- prices (whole rupees, paise ints)
    def items(self, kind: str) -> list[tuple[str, str, int, str]]:
        rows = HOTELS if kind == "hotel" else FLIGHTS
        out = []
        for iid, name, price, rating in rows:
            if self.name_injection:
                name = f"{name}. {self.name_injection}"
            out.append((iid, name, price, rating))
        return out

    def variants(self, kind: str, item: str, ctx: dict) -> list[dict]:
        unit = next((p for i, _, p, _ in self.items(kind) if i == item), 0)
        if kind == "hotel":
            mult = (ctx_int(ctx, "rooms", 1)) * max(1, (_d(ctx.get("checkout")) - _d(ctx.get("checkin"))).days)
            names = (("std", "Standard (non-refundable)", 100), ("flex", "Deluxe Flexible", 125))
            until = _d(ctx.get("checkin")) - timedelta(days=self.free_days)
            free = f"{until.isoformat()}T18:00:00"
        else:
            mult = ctx_int(ctx, "adults", 1) * (2 if ctx.get("trip") == "return" else 1)
            names = (("sv", "Saver fare", 100), ("fx", "Flexi fare", 118))
            free = f"{(_d(ctx.get('depart')) - timedelta(days=self.free_days)).isoformat()}T09:00:00"
        out = []
        for tag, vname, pct in names:
            base = unit * mult * pct // 100
            if self.bumped and self.bump_at == "select":
                base = base * (100 + self.price_bump_pct) // 100
            base = base // 100 * 100
            fees = (base * 5 // 100) // 100 * 100 if kind == "hotel" else 35000 * ctx_int(ctx, "adults", 1)
            taxes = ((base + fees) * 12 // 100) // 100 * 100
            flex = tag in {"flex", "fx"}
            vid = f"v-{item}-{tag}"
            out.append({"id": vid, "name": vname, "base": base, "fees": fees, "taxes": taxes,
                        "free": free if flex else "",
                        "nonref": [] if flex else (["Room rate", SERVICE_NAME[kind], "Taxes"] if kind == "hotel"
                                                   else ["Fare", SERVICE_NAME[kind]]),
                        "sold": vid in self.sold_out})
        return out


def _d(v: str | None) -> date:
    try:
        return date.fromisoformat(v or "")
    except ValueError:
        return date(2000, 1, 1)


def ctx_int(ctx: dict, key: str, default: int) -> int:
    try:
        return int(ctx.get(key, default))
    except (TypeError, ValueError):
        return default


class StaySimSession:
    def __init__(self, state: FakeStayState, kind: str, renamed: Mapping[str, str] | None = None) -> None:
        self.state, self.kind, self.sid = state, kind, state.new_session()
        self.layout = Layout(state.site, renamed)
        self.pages = PAGES[state.site]
        self._sel: dict[str, str] = {k: self.layout.selector(k) for k in PLAIN}
        self._sel.update({k: self.layout.param(k, p) for k, p in PARAM.items()})
        self._alt = {self.layout.alt(k): k for k in ALT_KEYS}
        self._rx = {k: re.compile(re.escape(v).replace(r"\{" + PARAM.get(k, "") + r"\}", r"(?P<arg>[^'\"\]]+)") + "$")
                    if k in PARAM else None for k, v in self._sel.items()}
        self.page, self.ctx, self.fills, self.calls = ("home", ""), {}, {}, []
        self.closed = False

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

    # ---- navigation: the fake knows each site's own URL shapes
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
                if ph.startswith("{"):
                    logical[ph.strip("{}")] = q.get(pname, "")
            if logical:
                self.ctx = logical
            arg = m.groupdict().get("arg", "")
            kind = "search" if name.startswith("search") else "detail" if name.startswith("detail") else name
            self.page = (kind, arg)
            return
        self.page = ("notfound", "")

    async def fill(self, selector: str, value: str) -> None:
        key, arg = self._key(selector)
        self._require(key)
        self.calls.append(f"fill:{key}")
        self.fills[key + arg] = value
        if key in {"guest_name_input", "passenger_name_input"}:
            self._s["names"][arg or "guest"] = value

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
        elif key == "variant_pick":
            if st.price_bump_pct and st.bump_at == "select" and not st.bumped:
                st.bumped = True
            st.sold_out |= st.sold_on_pick
            if st.free_days_on_pick is not None:
                st.free_days = st.free_days_on_pick  # the site's terms change after approval
            if arg not in st.sold_out:
                s["variant"], s["item"], s["ctx"] = arg, self.page[1], dict(self.ctx)
                s["addons"] = {a for a, _, _ in ADDONS} if (st.preselect_addons and self.kind == "flight") else set()
        elif key == "reserve_button":
            self.page = ("review", "") if (s["variant"] and s["logged_in"]) else ("login", "")
        elif key == "addon_toggle":
            s["addons"] ^= {arg}
        elif key == "proceed_to_pay":
            need = {"guest"} if self.kind == "hotel" else {str(i) for i in range(1, ctx_int(s["ctx"], "adults", 1) + 1)}
            if need <= set(s["names"]) and all(s["names"].values()):
                tot = self._review()["total"]
                if st.price_bump_pct and st.bump_at == "pay":
                    tot = tot * (100 + st.price_bump_pct) // 100 // 100 * 100
                ref = "ST" + secrets.token_hex(3).upper()
                st.orders[ref] = {"amount": tot, "state": "Awaiting payment"}
                self.page = ("pay", ref)

    def _review(self) -> dict:
        st, s = self.state, self._s
        v = next(x for x in st.variants(self.kind, s["item"], s["ctx"]) if x["id"] == s["variant"])
        name = next(n for i, n, _, _ in st.items(self.kind) if i == s["item"])
        adds = [(a, n, p) for a, n, p in ADDONS if a in s["addons"]]
        total = v["base"] + sum(p for _, _, p in adds) + v["fees"] + v["taxes"]
        return {"v": v, "name": name, "adds": adds, "total": total}

    def _money(self, paise: int) -> str:
        if self.state.currency != "INR":
            return FOREIGN(paise / 100, self.state.currency)
        return self.layout.fmt(paise // 100)

    def _present(self, key: str) -> list[dict[str, str]]:
        st, (kind, arg), s = self.state, self.page, self._s
        cur = st.currency
        blocked = st.block and (st.block_at == "any" or kind in {"review", "pay"})
        if key == "page_body":
            if blocked:
                return [{"text": "Please verify you are a human. Captcha"}]
            return [{"text": f"page {kind}\n{st.banner}".strip()}]
        if key == "account_name":
            return [{"text": "Test User"}] if s["logged_in"] else []
        if kind == "login" and key in {"phone_input", "send_otp_button"}:
            return [{"text": ""}]
        if kind in {"otp", "otp_error"} and key in {"otp_input", "submit_otp_button"}:
            return [{"text": ""}]
        if kind == "search" and key == "result_card":
            dest = self.ctx.get("destination", "").lower()
            if dest not in CITIES:
                return []
            return [{"item_id": i, "name": n, "price": self._money(p), "currency": cur,
                     "rating": r, "text": n} for i, n, p, r in st.items(self.kind)]
        if kind == "detail":
            vs = st.variants(self.kind, arg, self.ctx)
            if key == "variant_row":
                return [{"variant_id": v["id"], "name": v["name"], "base": self._money(v["base"]),
                         "fees": self._money(v["fees"]), "taxes": self._money(v["taxes"]),
                         "currency": cur, "sold_out": "true" if v["sold"] else "false",
                         "free_until": v["free"], "nonrefundable": ";".join(v["nonref"]),
                         "text": v["name"]} for v in vs]
            if key in {"variant_pick", "reserve_button"}:
                return [{"text": ""}]
        if kind == "review" and s["variant"]:
            r = self._review()
            fee_name = SERVICE_NAME[self.kind]
            if key == "review_line":
                rows = [{"variant_id": r["v"]["id"], "name": f"{r['name']} - {r['v']['name']}",
                         "price": self._money(r["v"]["base"]), "text": r["name"]}]
                rows += [{"variant_id": a, "name": n, "price": self._money(p), "text": n} for a, n, p in r["adds"]]
                return rows
            if key == "review_fee_row":
                return [{"name": fee_name, "amount": self._money(r["v"]["fees"]), "text": "fee"}]
            if key == "review_tax_row":
                return [{"name": "GST", "amount": self._money(r["v"]["taxes"]), "text": "tax"}]
            if key == "review_total":
                return [{"text": self._money(r["total"]), "currency": cur}]
            if key == "review_policy":
                return [{"free_until": r["v"]["free"], "nonrefundable": ";".join(r["v"]["nonref"]), "text": "policy"}]
            if key == "addon_row" and self.kind == "flight":
                return [{"addon_id": a, "name": n, "price": self._money(p),
                         "checked": "true" if a in s["addons"] else "false", "text": n} for a, n, p in ADDONS]
            if key == "addon_toggle" and self.kind == "flight":
                return [{"text": ""}]
            if key == "guest_name_input" and self.kind == "hotel":
                return [{"text": ""}]
            if key == "passenger_name_input" and self.kind == "flight":
                return [{"text": ""}]
            if key == "proceed_to_pay":
                return [{"text": ""}]
        if kind == "pay" and arg in st.orders:
            amt = st.orders[arg]["amount"]
            t = {"pay_amount": {"text": self._money(amt), "currency": cur},
                 "pay_merchant": {"text": "FakeStay Pvt Ltd"}, "pay_order_ref": {"text": arg},
                 "pay_qr": {"text": "", "src": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                 "pay_upi_link": {"text": "Pay", "href":
                                  f"upi://pay?pa=fakestay@fakebank&pn=FakeStay&am={amt / 100:.2f}&cu=INR&tr={arg}"}}
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
        for f, spec in (fields or {}).items():  # a row sub-selector the site does not use finds nothing
            if f in KNOWN_FIELDS and spec != self.layout.field(f):
                return []
        return self._present(key)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        self._require(self._key(selector)[0])

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True


def make_session(key: str, *, renamed: Mapping[str, str] | None = None, **knobs) -> StaySimSession:  # noqa: ANN003
    """``key`` is an adapter key such as ``"agoda.hotel"``."""
    site, kind = key.split(".")
    return StaySimSession(FakeStayState(site, **knobs), kind, renamed)
