# ruff: noqa: E501
"""Shared ride connector and adapter. Each site (sites.py) is a profile of selectors and quirks.

Rules kept here for every ride site:
* ``prepare`` is read-only: pickup, drop, vehicle list with the PRICE RANGE, surge, cancellation
  fee. No ride is requested. The approval card expires after 3 minutes (fares move fast).
* After approval: the live quote is read again. A higher fare, a new or higher surge, a higher
  cancellation fee, a different pickup / drop, or an expired approval means a NEW approval card.
  Only then is the one irreversible click (``request_ride_button``) armed and pressed.
* The ride-start code (OTP) is read by code, parked in a one-time reveal store and shown to the
  user only as a link to the one-time page. It never goes into the chat text, the Proposal, the
  result, a log or a model. Driver name / vehicle are plain text for the user, never parsed by a model.
* No payment at all (cash or the user's own app). A bot check stops the run for good.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.contract import (
    ConnectorError,
    ItemQty,
    LayoutChanged,
    LoginRequired,
    format_rupees,
    rupees_to_paise,
)
from friday.connectors.gate import Grant, Verdict
from friday.connectors.sites.adapters import ExecResult, Prepared, Problem, Proposal, RunCtx, norm
from friday.connectors.sites.errors import SiteBlocked
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.grocery.base import clean  # same label cleaner as grocery
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.ride.contract import DriverInfo, RideQuote, VehicleOption
from friday.connectors.sites.ride.profiles import IRREVERSIBLE, RideProfile, norm_kind
from friday.connectors.sites.ride.reveal import DEFAULT_REVEAL, OneTimeReveal
from friday.connectors.sites.safety import ExtendedGate, SiteSafety
from friday.connectors.sites.verifier import Expect, Verifier

RIDE_APPROVAL_TTL = timedelta(minutes=3)
LINK_BASE = "/ride/code"  # the integrator sets the absolute base of the one-time page
_PIN = re.compile(r"^(?:pin:?\s*)?(-?\d{1,2}\.\d+)[,\s]+(-?\d{1,3}\.\d+)$", re.IGNORECASE)
_MONEY = re.compile(r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?", re.IGNORECASE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SURGE = re.compile(r"(\d+(?:\.\d+)?)\s*x", re.IGNORECASE)


@dataclass
class RideProblem(Problem):
    """``Problem`` plus the kinds this package adds (needs_login, closed); ``options`` lists what
    else is available so the flow can ASK. See docs/BROWSER_GROCERY_RIDE.md for the flow mapping."""

    options: tuple[str, ...] = ()


@dataclass
class RideResult(ExecResult):
    """``ExecResult`` for a ride: status ``ride_requested`` (no payment, so no handoff)."""

    driver: DriverInfo | None = None
    otp_link: str = ""  # link to the one-time page that shows the ride-start code
    share_link: str = ""  # the live trip share link (host checked against the allow-list)
    ride_state: str = ""


class PlaceNotFound(ConnectorError):
    def __init__(self, which: str) -> None:
        super().__init__(f"could not set the {which}")
        self.which = which


class RideGate(ExtendedGate):
    """Maps the ride tools onto the one gate: choosing a vehicle is ``build_cart`` (reversible),
    requesting the ride is ``get_payment_handoff`` (needs ``total_paise`` within the approved cap)."""

    def explain(self, tool_name: str, args: Mapping[str, Any], grants: Any) -> tuple[Verdict, str]:
        grants = list(grants)
        if tool_name == "select_vehicle":
            return super().explain("build_cart", args, grants)
        if tool_name == "request_ride":
            return super().explain("get_payment_handoff", args, grants)
        return super().explain(tool_name, args, grants)


def build_kit(inner: BrowserSession, profile: RideProfile, *, task_id: str,
              repairer: SelectorRepairer | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    safety = SiteSafety(profile.hosts() | extra_hosts, IRREVERSIBLE)
    log = RepairLog()
    loc = ElementLocator(profile.selectors, profile.alternates, repairer=repairer, log=log,
                         task_id=task_id, irreversible=IRREVERSIBLE)
    seen = (profile.selectors["ride_state"],)
    exp = {profile.selectors["request_ride_button"]: Expect(present=seen)}
    for alt in profile.alternates.get("request_ride_button", []):
        exp[alt] = Expect(present=seen)
    return AgentKit(GuardedSession(inner, safety, loc, PageReader(), Verifier(exp)), safety, loc, log)


def _money_in(text: str) -> int:
    m = _MONEY.search(text or "")
    return rupees_to_paise(m.group(0)) if m else 0


def parse_place(text: str) -> tuple[str, str]:
    """('pin', 'lat,lng') for a dropped pin, else ('text', place name). Digits-only text gets a word
    in front so it is never mistaken for a code by the typing guard."""
    t = (text or "").strip()
    m = _PIN.match(t)
    if m:
        return "pin", f"{m.group(1)},{m.group(2)}"
    return "text", f"pincode {t}" if t.isdigit() else t[:120]


class RideConnector:
    use_case = "ride"
    backend = "scripted_browser"

    def __init__(self, session: BrowserSession, profile: RideProfile, *, base_url: str,
                 task_id: str, kit: AgentKit | None = None) -> None:
        self._s, self.p, self._base, self._task = session, profile, base_url.rstrip("/"), task_id
        self._kit = kit
        self.blocked = False  # after a bot check nothing else is sent to the site

    @property
    def site(self) -> str:
        return self.p.key

    def __repr__(self) -> str:
        return f"RideConnector({self.p.key!r}, task_id={self._task!r})"

    def _sel(self, key: str) -> str:
        return self.p.selectors[key]

    async def _guard(self, coro: Awaitable[Any]) -> Any:
        if self.blocked:
            close = getattr(coro, "close", None)
            if close:
                close()
            raise SiteBlocked("a bot check was shown earlier; not trying again")
        try:
            return await coro
        except SiteBlocked:
            self.blocked = True
            raise

    async def _goto(self, key: str) -> None:
        await self._guard(self._s.goto(self._base + self.p.paths[key]))

    async def _click(self, key: str, **params: str) -> None:
        await self._guard(self._s.click(self._sel(key).format(**params)))

    async def _fill(self, key: str, value: str) -> None:
        await self._guard(self._s.fill(self._sel(key), value))

    async def _texts(self, key: str, limit: int = 120) -> str:
        rows = await self._s.query_all(self._sel(key))
        return clean(rows[0]["text"], self._kit, limit) if rows else ""

    # ---- read-only
    async def status(self) -> tuple[bool, bool]:
        """(logged in, service closed)"""
        await self._goto("home")
        closed = bool(await self._s.query_all(self._sel("service_closed")))
        return bool(await self._s.query_all(self._sel("account_name"))), closed

    async def set_route(self, pickup: str, drop: str) -> tuple[str, str]:
        """Enter both places and open the price list; returns the labels the SITE shows."""
        await self._goto("ride")
        await self._set_place("pickup", pickup)
        await self._set_place("drop", drop)
        try:
            await self._click("see_prices_button")
        except ElementNotFound:
            raise LayoutChanged("selector 'see_prices_button' not found") from None
        return (await self._texts("quote_pickup", 80) or clean(pickup, self._kit, 80),
                await self._texts("quote_drop", 80) or clean(drop, self._kit, 80))

    async def _set_place(self, which: str, text: str) -> None:
        kind, value = parse_place(text)
        if kind == "pin":
            await self._fill(f"{which}_point_input", value)
            await self._click("point_confirm")
            return
        await self._fill(f"{which}_input", value)
        rows = await self._s.query_all(self._sel("suggestion"), self.p.fields["suggestion"])
        if not rows:
            raise PlaceNotFound(which)  # geocoder knows no such place: ask, never guess
        await self._click("suggestion_pick", n=_sid(rows[0].get("n") or "1"))

    def _options(self, rows: list[dict[str, str]]) -> list[VehicleOption]:
        out: list[VehicleOption] = []
        for r in rows:
            name = clean(r.get("name", ""), self._kit, 40)
            kind = self.p.kind_of(name)
            if not kind or not _SAFE_ID.match(r.get("vehicle_id", "")):
                continue  # unknown or instruction-only label: not trusted
            try:
                out.append(VehicleOption(
                    vehicle_id=r["vehicle_id"], name=name, kind=kind,
                    eta_min=int(re.sub(r"\D", "", r.get("eta", "")) or 0),
                    fare_low_paise=rupees_to_paise(r["low"]), fare_high_paise=rupees_to_paise(r["high"]),
                    surge_x100=_surge(r.get("surge", "")),
                    available=r.get("available", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError):
                continue
        return out

    async def options(self) -> tuple[list[VehicleOption], int]:
        rows = await self._s.query_all(self._sel("vehicle_option"), self.p.fields["vehicle_option"])
        opts = self._options(rows)
        if not opts:
            raise LayoutChanged("no vehicle options found")
        notice = await self._s.query_all(self._sel("cancel_fee_notice"))
        return opts, _money_in(notice[0]["text"]) if notice else 0

    # ---- after approval
    async def select(self, vehicle_id: str) -> RideQuote:
        await self._click("vehicle_pick", vehicle_id=_sid(vehicle_id))
        try:
            await self._s.wait_for(self._sel("request_ride_button"), 3000)
        except ElementNotFound:
            raise LayoutChanged("selector 'request_ride_button' not found") from None
        try:
            return RideQuote(
                vehicle_id=vehicle_id, name=await self._texts("quote_vehicle", 40),
                pickup=await self._texts("quote_pickup", 80), drop=await self._texts("quote_drop", 80),
                fare_low_paise=_money_in(await self._texts("quote_low")),
                fare_high_paise=_money_in(await self._texts("quote_high")),
                surge_x100=_surge(await self._texts("quote_surge")),
                cancel_fee_paise=_money_in(await self._texts("quote_cancel_fee")))
        except ValidationError:
            raise LayoutChanged("quote could not be read") from None

    async def request(self, *, polls: int, poll_s: float,
                      sleep: Callable[[float], Awaitable[None]]) -> str:
        """Press the (armed) request button and wait for a driver: 'assigned' | 'no_driver'."""
        await self._click("request_ride_button")
        for _ in range(polls):
            state = norm(await self._texts("ride_state", 60))
            if "nodriver" in state or "nodriversfound" in state:
                return "no_driver"
            if "assigned" in state or "ontheway" in state or "arriving" in state:
                return "assigned"
            await sleep(poll_s)
        with_cancel = await self._s.query_all(self._sel("cancel_request"))
        if with_cancel:  # nobody accepted: withdraw the request instead of leaving it open
            await self._click("cancel_request")
        return "no_driver"

    async def driver(self) -> DriverInfo:
        try:
            eta = re.sub(r"\D", "", await self._texts("driver_eta", 20))
            return DriverInfo(name=await self._texts("driver_name", 40) or "your driver",
                              vehicle_no=await self._texts("driver_vehicle_no", 20),
                              vehicle_model=await self._texts("driver_vehicle_model", 40),
                              rating=await self._texts("driver_rating", 10),
                              eta_min=int(eta) if eta else None)
        except ValidationError:
            raise LayoutChanged("driver details could not be read") from None

    async def start_code(self) -> str:
        """The ride-start code, in memory only for the caller to park in the reveal store."""
        rows = await self._s.query_all(self._sel("ride_otp"))
        return re.sub(r"\D", "", rows[0]["text"])[:8] if rows else ""

    async def share_link(self) -> str:
        for r in await self._s.query_all(self._sel("share_link"), self.p.fields["share_link"]):
            href = r.get("href", "")
            if self._kit is not None and self._kit.safety.host_ok(href):
                return href
        return ""


def _sid(value: str) -> str:
    if not _SAFE_ID.match(value or ""):
        raise ConnectorError("unexpected id format")
    return value


def _surge(text: str) -> int:
    m = _SURGE.search(text or "")
    return max(100, round(float(m.group(1)) * 100)) if m else 100


def _fare_line(lo: int, hi: int) -> str:
    return f"Fare {format_rupees(lo)} to {format_rupees(hi)} (a range, not fixed)"


class RideAdapter:
    """What BrowserFlow drives. One subclass per site key sets ``key`` / ``site`` / ``profile``."""

    use_case = "ride"
    required = ("pickup", "drop", "vehicle")
    key = ""
    site = ""
    site_name = ""
    profile: RideProfile
    driver_polls = 20

    def __init__(self, ctx: RunCtx, *, reveal: OneTimeReveal | None = None,
                 link_base: str | None = None) -> None:
        self.ctx, self.reveal, self.link_base = ctx, reveal or DEFAULT_REVEAL, link_base or LINK_BASE
        self.gate = RideGate(now=ctx.now)
        self.kit = build_kit(ctx.session, self.profile, task_id=ctx.task_id, repairer=ctx.repairer)
        self.conn = RideConnector(self.kit.session, self.profile, base_url=ctx.base_url,
                                  task_id=ctx.task_id, kit=self.kit)

    def flags(self) -> dict[str, bool]:
        return {"injection": self.kit.safety.injection_count > 0, "repaired": bool(self.kit.repairs.records)}

    def _problem(self, kind: str, what: str, options: tuple[str, ...] = ()) -> Prepared:
        return Prepared(problem=RideProblem(kind, what, options))  # type: ignore[arg-type]

    def _pick(self, opts: list[VehicleOption], want: str) -> VehicleOption | None:
        return next((o for o in opts if o.kind == want), None)

    @staticmethod
    def _route_key(a: str, b: str) -> str:
        return f"{norm(a)}>{norm(b)}"[:60]

    # ------------------------------------------------------------ prepare (read-only)
    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        want = norm_kind(str(slots["vehicle"]))
        if not want or want not in self.profile.vehicles.values():
            return self._problem("no_match", f"a {slots['vehicle']} on {self.site_name}")
        logged_in, closed = await self.conn.status()
        if not logged_in:
            return self._problem("needs_login", self.site_name)
        if closed:
            return self._problem("closed", self.site_name)
        try:
            pickup, drop = await self.conn.set_route(str(slots["pickup"]), str(slots["drop"]))
        except PlaceNotFound as e:
            return self._problem("no_match", f"the {e.which} '{clean(str(slots[e.which]), self.kit, 40)}'")
        opts, cancel = await self.conn.options()
        opt = self._pick(opts, want)
        if opt is None or not opt.available:
            others = tuple(o.name for o in opts if o.available and o.kind != want)
            return self._problem("out_of_stock", f"a {want}", others)
        return Prepared(proposal=self._proposal(
            opt, pickup, drop, cancel, (str(slots["pickup"])[:120], str(slots["drop"])[:120]), exact=False))

    def _proposal(self, opt: VehicleOption, pickup: str, drop: str, cancel: int, src: tuple[str, str],
                  *, exact: bool) -> Proposal:
        lines = [f"{opt.name} ({opt.kind}) from {pickup} to {drop}",
                 _fare_line(opt.fare_low_paise, opt.fare_high_paise)]
        if opt.surge_x100 > 100:
            lines.append(f"Surge pricing {opt.surge_x100 / 100:g}x is on")
        if cancel:
            lines.append(f"Cancellation fee {format_rupees(cancel)} applies after the driver is assigned")
        details = {"route_key": self._route_key(pickup, drop), "vehicle_id": opt.vehicle_id,
                   "kind": opt.kind, "pickup": pickup, "drop": drop, "surge_x100": opt.surge_x100,
                   "cancel_fee_paise": cancel, "eta_min": opt.eta_min,
                   "pickup_in": src[0], "drop_in": src[1], "payment": "cash or your own app"}
        return Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name, area=drop,
            lines=lines, subtotal_paise=opt.fare_low_paise, max_total_paise=opt.fare_high_paise,
            address=pickup, when=f"pickup in about {opt.eta_min} min", exact=exact, details=details,
            expires_at=self.ctx.now() + RIDE_APPROVAL_TTL)

    # ------------------------------------------------------------ execute (after approval)
    async def execute(self, p: Proposal) -> ExecResult:
        if self.conn.blocked:
            raise SiteBlocked("a bot check was shown earlier; not trying again")
        d = p.details
        logged_in, closed = await self.conn.status()
        if not logged_in:
            raise LoginRequired("not logged in; the user must log in through the secure page")
        if closed:
            return ExecResult("out_of_stock", names="a ride (the service is closed)", notes=self.flags())
        timed_out = p.expires_at <= self.ctx.now()
        grant = Grant(task_id=self.ctx.task_id, connector=self.key, restaurant_id=d["route_key"],
                      items=[ItemQty(item_id=d["vehicle_id"], qty=1)], max_total_paise=p.max_total_paise,
                      expires_at=p.expires_at)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "restaurant_id": d["route_key"],
                "items": [{"item_id": d["vehicle_id"], "qty": 1}]}
        try:
            pickup, drop = await self.conn.set_route(d["pickup_in"], d["drop_in"])
        except PlaceNotFound:
            return ExecResult("no_match", reason="the pickup or drop is no longer found", notes=self.flags())
        opts, cancel = await self.conn.options()
        opt = self._pick(opts, d["kind"])
        if opt is None or not opt.available:
            return ExecResult("out_of_stock", names=f"a {d['kind']}", notes=self.flags())
        if timed_out:  # fares move fast: an old card is never acted on, show the live numbers again
            new = self._proposal(opt, pickup, drop, cancel, (d["pickup_in"], d["drop_in"]), exact=True)
            return ExecResult("reapprove", reason="the approval timed out and ride prices change quickly",
                              proposal=new, notes=self.flags())
        if self.gate.decide("select_vehicle", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        q = await self.conn.select(opt.vehicle_id)
        grant.mark_used("build_cart")
        why = self._changed(p, q, pickup, drop)
        if why:
            live = opt.model_copy(update={"fare_low_paise": q.fare_low_paise, "fare_high_paise": q.fare_high_paise,
                                          "surge_x100": q.surge_x100})
            return ExecResult("reapprove", reason=why, notes=self.flags(),
                              proposal=self._proposal(live, q.pickup or pickup, q.drop or drop,
                                                      q.cancel_fee_paise, (d["pickup_in"], d["drop_in"]),
                                                      exact=True))
        pay = {**args, "total_paise": max(1, q.fare_high_paise)}
        if self.gate.decide("request_ride", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        sleep = self.ctx.sleep or asyncio.sleep
        with self.kit.safety.approved("request_ride_button"):
            state = await self.conn.request(polls=self.driver_polls, poll_s=self.ctx.poll_s, sleep=sleep)
        if state != "assigned":
            return ExecResult("out_of_stock", names="a driver nearby", notes=self.flags())
        return await self._ride_result(state)

    @staticmethod
    def _changed(p: Proposal, q: RideQuote, pickup: str, drop: str) -> str:
        d = p.details
        if q.surge_x100 > d.get("surge_x100", 100):
            return "surge pricing started or went up"
        if q.fare_high_paise > p.max_total_paise or q.fare_low_paise > p.subtotal_paise:
            return "the fare went up"
        if q.cancel_fee_paise > d.get("cancel_fee_paise", 0):
            return "the cancellation fee went up"
        for got, was in ((q.pickup or pickup, d["pickup"]), (q.drop or drop, d["drop"])):
            if norm(got) not in norm(was) and norm(was) not in norm(got):
                return "the pickup or drop on the site is different"
        return ""

    async def _ride_result(self, state: str) -> RideResult:
        driver = await self.conn.driver()
        code = await self.conn.start_code()
        link = f"{self.link_base.rstrip('/')}/{self.reveal.put(self.ctx.task_id, code)}" if code else ""
        del code  # only the link token leaves this function
        return RideResult("ride_requested", handoff=None, notes=self.flags(), driver=driver,
                          otp_link=link, share_link=await self.conn.share_link(), ride_state=state)

