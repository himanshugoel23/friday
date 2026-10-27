# ruff: noqa: E501
"""FAKE ride site (one class, parametrised by site key). Invented places, drivers, fares, codes.

Addressed through each site's OWN selector map (ride/profiles.py), so per-site selectors are
really exercised. Scenario knobs: ``logged_in`` (False = login expired), ``closed`` (no service),
``unavailable`` (vehicle kinds with no driver in the list), ``no_driver`` (nobody accepts after the
request), ``searching_forever`` (the request never gets an answer), ``surge_on_pick`` (x100, applied
when the user has approved and the vehicle is selected), ``fare_bump_pct`` (same moment),
``cancel_fee_bump`` (paise, same moment), ``vehicle_names`` (kind -> replacement label, used for
prompt injection), ``banner`` (page text), ``block`` ("captcha"), ``quote_drop`` (the site shows
another drop than the one asked for), ``otp`` (ride-start code shown on the trip page).
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import unquote, urlsplit

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.contract import format_rupees
from friday.connectors.sites.ride.profiles import PROFILES

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PLACES = {"sector12": "Sector 12", "oldmarket": "Old Market", "citystation": "City Station",
          "fakeairport": "Fake Airport"}
RATE = {"bike": 800, "auto": 1400, "cab": 1900, "premium": 3000}  # paise per km, 6 km trip
ORDER = ("auto", "bike", "cab", "premium")
_PIN = re.compile(r"^(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)$")


def _rx(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{(\w+)\}", template)
    body = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^'\"\\]]+)" for i, p in enumerate(parts))
    return re.compile(rf"^{body}$")


class FakeRideSite:
    def __init__(self, site: str, *, logged_in: bool = True, closed: bool = False,
                 unavailable: set[str] | None = None, no_driver: bool = False,
                 searching_forever: bool = False, surge_x100: int = 100, surge_on_pick: int = 0,
                 fare_bump_pct: int = 0, cancel_fee: int = 3000, cancel_fee_bump: int = 0,
                 vehicle_names: dict[str, str] | None = None, banner: str = "",
                 block: str | None = None, quote_drop: str | None = None, otp: str = "4821") -> None:
        self.site, self.p = site, PROFILES[site]
        self.logged_in, self.closed, self.banner, self.block = logged_in, closed, banner, block
        self.unavailable, self.no_driver, self.searching_forever = set(unavailable or ()), no_driver, searching_forever
        self.surge, self.surge_on_pick, self.fare_bump_pct = surge_x100, surge_on_pick, fare_bump_pct
        self.cancel_fee, self.cancel_fee_bump, self._bumped = cancel_fee, cancel_fee_bump, False
        self.vehicle_names, self.quote_drop, self.otp = dict(vehicle_names or {}), quote_drop, otp
        self.trips: list[dict[str, Any]] = []
        self.sessions: list[RideFakeSession] = []

    def session(self, renamed: dict[str, str] | None = None) -> RideFakeSession:
        s = RideFakeSession(self, renamed)
        self.sessions.append(s)
        return s

    def expire_login(self) -> None:
        self.logged_in = False

    def vehicles(self) -> list[dict[str, Any]]:
        by_kind = {k: n for n, k in self.p.vehicles.items()}
        out = []
        for kind in ORDER:
            if kind not in by_kind:
                continue
            low = 3000 + 6 * RATE[kind]
            low = low * self.surge // 100
            if self._bumped:
                low = low * (100 + self.fare_bump_pct) // 100
            out.append({"vehicle_id": f"{self.site}-{kind}", "kind": kind,
                        "name": self.vehicle_names.get(kind, by_kind[kind]), "eta": 3 + ORDER.index(kind),
                        "low": low, "high": low * 12 // 10 // 100 * 100, "surge": self.surge,
                        "available": kind not in self.unavailable})
        return out

    def bump(self) -> None:
        if not self._bumped:
            self._bumped = True
            self.surge = self.surge_on_pick or self.surge
            self.cancel_fee += self.cancel_fee_bump


def _geocode(text: str) -> list[str]:
    n = re.sub(r"[^a-z0-9]", "", text.lower())
    return [lb for k, lb in PLACES.items() if n and (n in k or k in n)]


class RideFakeSession:
    def __init__(self, site: FakeRideSite, renamed: dict[str, str] | None = None) -> None:
        self.site, self.p = site, site.p
        self._sel = {**self.p.selectors, "page_body": "body", **(renamed or {})}
        self.page = "home"
        self.place: dict[str, str] = {}
        self.focus, self.point, self.sugg = "pickup", "", []
        self.vehicle = ""
        self.trip: dict[str, Any] | None = None
        self.calls: list[str] = []
        self.closed = False

    def _key(self, selector: str) -> tuple[str, dict[str, str]]:
        for key, sel in self._sel.items():
            m = _rx(sel).match(selector)
            if m:
                return key, m.groupdict()
        raise ElementNotFound(f"unknown selector: {selector}")

    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        path = unquote(urlsplit(url).path) or "/"
        self.page = next((k for k, v in self.p.paths.items() if v == path), "notfound")

    async def fill(self, selector: str, value: str) -> None:
        key, params = self._key(selector)
        self._require(key, params)
        self.calls.append(f"fill:{key}")
        which = key.split("_")[0]
        self.focus = which
        if key.endswith("_point_input"):
            self.point = value
        else:
            self.sugg = _geocode(value)

    async def click(self, selector: str) -> None:
        key, params = self._key(selector)
        self._require(key, params)
        self.calls.append(f"click:{key}")
        s = self.site
        if key == "point_confirm":
            m = _PIN.match(self.point)
            if m:
                self.place[self.focus] = f"Pin ({m.group(1)}, {m.group(2)})"
        elif key == "suggestion_pick":
            self.place[self.focus] = self.sugg[int(params["n"]) - 1]
        elif key == "see_prices_button":
            self.page = "prices"
        elif key == "vehicle_pick":
            s.bump()
            self.vehicle = params["vehicle_id"]
            self.page = "quote"
        elif key == "request_ride_button":
            self.trip = {"vehicle": self.vehicle, "state": "searching" if s.searching_forever else (
                "No driver found" if s.no_driver else "Driver assigned")}
            s.trips.append(self.trip)
            self.page = "trip"
        elif key == "cancel_request" and self.trip:
            self.trip["state"] = "Cancelled"

    def _vehicle(self) -> dict[str, Any]:
        return next(v for v in self.site.vehicles() if v["vehicle_id"] == self.vehicle)

    def _present(self, key: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        s, page = self.site, self.page
        if key == "page_body":
            if s.block == "captcha":
                return [{"text": "Please verify you are a human. Captcha"}]
            extra = "\n".join(v["name"] for v in s.vehicles()) if page == "prices" else ""
            if page == "trip":
                extra = f"Ride start OTP: {s.otp}"
            return [{"text": f"page {page}\n{s.banner}\n{extra}".strip()}]
        if key == "banner":
            return [{"text": s.banner}] if s.banner else []
        if page == "home":
            if key == "account_name":
                return [{"text": "Test User"}] if s.logged_in else []
            if key == "service_closed":
                return [{"text": "No rides in your area"}] if s.closed else []
        if page == "ride":
            if key in {"pickup_input", "drop_input", "pickup_point_input", "drop_point_input"}:
                return [{"text": ""}]
            if key == "point_confirm" and self.point:
                return [{"text": ""}]
            if key == "suggestion":
                return [{"label": lb, "n": str(i + 1), "text": lb} for i, lb in enumerate(self.sugg)]
            if key == "suggestion_pick" and params and params.get("n", "").isdigit() and 1 <= int(params["n"]) <= len(self.sugg):
                return [{"text": ""}]
            if key == "see_prices_button" and len(self.place) == 2:
                return [{"text": ""}]
        if page in {"prices", "quote"} and key in {"quote_pickup", "quote_drop"}:
            which = key[6:]
            label = s.quote_drop if (which == "drop" and s.quote_drop and page == "quote") else self.place.get(which, "")
            return [{"text": label}] if label else []
        if page == "prices":
            if key == "vehicle_option":
                return [{**v, "low": v["low"], "high": v["high"], "surge": f"{v['surge'] / 100:g}x" if v["surge"] > 100 else "",
                         "available": "true" if v["available"] else "false", "eta": f"{v['eta']} min", "text": v["name"]} for v in s.vehicles()]
            if key == "vehicle_pick" and params and any(v["vehicle_id"] == params.get("vehicle_id") and v["available"] for v in s.vehicles()):
                return [{"text": ""}]
            if key == "cancel_fee_notice":
                return [{"text": f"Cancel after the driver is assigned: {format_rupees(s.cancel_fee)} fee"}]
        if page == "quote" and self.vehicle:
            v = self._vehicle()
            t = {"quote_vehicle": v["name"], "quote_low": format_rupees(v["low"]),
                 "quote_high": format_rupees(v["high"]),
                 "quote_cancel_fee": f"Cancellation fee {format_rupees(s.cancel_fee)}", "request_ride_button": ""}
            if v["surge"] > 100 and key == "quote_surge":
                return [{"text": f"{v['surge'] / 100:g}x surge"}]
            return [{"text": t[key]}] if key in t else []
        if page == "trip" and self.trip:
            t = {"ride_state": self.trip["state"], "driver_name": "Ravi K", "driver_vehicle_no": "FAKE 1234",
                 "driver_vehicle_model": "Fake Auto", "driver_rating": "4.8", "driver_eta": "4 min",
                 "ride_otp": s.otp}
            if key == "cancel_request" and self.trip["state"] == "searching":
                return [{"text": ""}]
            if key == "share_link" and self.trip["state"] == "Driver assigned":
                return [{"text": "Share trip", "href": "https://fake.invalid/trip/abc123"}]
            if key in t and (self.trip["state"] == "Driver assigned" or key == "ride_state"):
                return [{"text": t[key]}]
        return []

    def _require(self, key: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        rows = self._present(key, params)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    async def text(self, selector: str) -> str:
        key, params = self._key(selector)
        return str(self._require(key, params)[0]["text"])

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None) -> list[dict[str, str]]:
        try:
            key, params = self._key(selector)
        except ElementNotFound:
            return []
        rows = self._present(key, params)
        if fields is None:
            return [{"text": str(r.get("text", ""))} for r in rows]

        def val(r: dict[str, Any], k: str) -> str:
            v = r.get(k, "")
            return format_rupees(v) if k in {"low", "high"} and isinstance(v, int) else str(v)

        return [{**{k: val(r, k) for k in fields}, "text": str(r.get("text", ""))} for r in rows]

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        key, params = self._key(selector)
        self._require(key, params)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True
