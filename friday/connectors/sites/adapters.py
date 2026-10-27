# ruff: noqa: E501
"""Use-case adapters: the flow talks to these, they talk to connectors. Two exist: food and movie.

``prepare`` is read-only (search, menu / seats, sold-out check) and builds the ``Proposal`` the user
approves. ``execute`` runs only after approval: ActionGate -> build cart / hold seats -> price
checks (a rise after approval means RE-ASK, never a silent go-ahead) -> ActionGate -> arm the one
irreversible click -> QR / UPI handoff. Nothing here pays.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from friday.connectors.browser.port import BrowserSession
from friday.connectors.contract import ItemQty, PaymentHandoff, format_rupees
from friday.connectors.gate import Grant, Verdict
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.sites import movies as _movies  # noqa: F401
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.executor import AgentKit
from friday.connectors.sites.locator import SelectorRepairer
from friday.connectors.sites.movies import bookmyshow as bms
from friday.connectors.sites.safety import ExtendedGate
from friday.connectors.sites.zomato_agent import AgentZomatoConnector, build_kit

APPROVAL_TTL = timedelta(minutes=15)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse_minutes(text: str) -> int | None:
    m = re.search(r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?\b", text or "")
    if not m:
        return None
    h, mi, tag = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if h > 23 or mi > 59:
        return None
    if tag == "pm" and h < 12:
        h += 12
    elif tag == "am" and h == 12:
        h = 0
    elif tag in {"baje", ""} and 1 <= h <= 11:
        h += 12  # evening shows: "7" / "7 baje" is read as 7 pm
    return h * 60 + mi


@dataclass
class Profile:
    address: str = ""
    area: str = ""
    phone: str = ""  # login phone; held in memory, never in task state or messages


class Proposal(BaseModel):
    task_id: str
    connector: str
    merchant: str
    area: str = ""
    lines: list[str]  # display lines, e.g. "2 x Margherita (₹398.00)"
    subtotal_paise: int
    max_total_paise: int
    address: str = ""
    movie: str = ""
    when: str = ""
    exact: bool = False  # True once the site showed the real total (a re-ask)
    details: dict[str, Any] = {}
    expires_at: datetime


@dataclass
class Problem:
    kind: Literal["no_match", "out_of_stock"]
    what: str


@dataclass
class Prepared:
    proposal: Proposal | None = None
    problem: Problem | None = None


@dataclass
class ExecResult:
    status: Literal["payment_ready", "reapprove", "out_of_stock", "no_match"]
    handoff: PaymentHandoff | None = None
    proposal: Proposal | None = None  # for reapprove
    reason: str = ""
    names: str = ""
    amount_paise: int = 0
    notes: dict[str, bool] = field(default_factory=dict)


@dataclass
class RunCtx:
    task_id: str
    user_id: str
    session: BrowserSession
    profile: Profile
    otp: OneTimeOtpChannel
    on_code_wait: Callable[[], Awaitable[None]]
    base_url: str
    repairer: SelectorRepairer | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    otp_wait_s: float = 120.0
    poll_s: float = 0.5
    sleep: Callable[[float], Awaitable[None]] | None = None
    credentials: Any = None  # CredentialService (password sites such as IRCTC) or None


def _grant(ctx: RunCtx, conn: str, group: str, items: list[ItemQty], max_total: int) -> Grant:
    return Grant(task_id=ctx.task_id, connector=conn, restaurant_id=group, items=items,
                 max_total_paise=max_total, expires_at=ctx.now() + APPROVAL_TTL)


def _kw(ctx: RunCtx) -> dict[str, Any]:
    kw: dict[str, Any] = dict(base_url=ctx.base_url, task_id=ctx.task_id, otp_channel=ctx.otp,
                              phone=ctx.profile.phone or None, on_code_wait=ctx.on_code_wait,
                              otp_wait_s=ctx.otp_wait_s, poll_s=ctx.poll_s)
    if ctx.sleep:
        kw["sleep"] = ctx.sleep
    return kw


def _flags(kit: AgentKit) -> dict[str, bool]:
    return {"injection": kit.safety.injection_count > 0, "repaired": bool(kit.repairs.records)}


# ============================================================ food
class FoodAdapter:
    key = "zomato.food"
    site, use_case, site_name = "zomato", "food", "Zomato"
    required = ("items", "restaurant")

    def __init__(self, ctx: RunCtx) -> None:
        self.ctx, self.gate = ctx, ExtendedGate()
        self.kit = build_kit(ctx.session, task_id=ctx.task_id, repairer=ctx.repairer)
        self.conn = AgentZomatoConnector(self.kit.session, **_kw(ctx))

    def flags(self) -> dict[str, bool]:
        return _flags(self.kit)

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        area = slots.get("area") or self.ctx.profile.area
        address = slots.get("address") or self.ctx.profile.address
        found = await self.conn.search_restaurants(slots["restaurant"], area)
        if not found:
            return Prepared(problem=Problem("no_match", slots["restaurant"]))
        chosen = next((r for r in found if area and norm(area) in norm(r.area)), found[0])
        menu = await self.conn.get_menu(chosen.restaurant_id)
        gone = await self.conn.sold_out_ids(chosen.restaurant_id)
        lines, items, sub = [], [], 0
        for w in slots["items"]:
            hit = next((m for m in menu.items if norm(w["query"]) in norm(m.name)), None)
            if hit is None:
                return Prepared(problem=Problem("no_match", w["query"]))
            if hit.item_id in gone:
                return Prepared(problem=Problem("out_of_stock", hit.name))
            qty = int(w.get("qty", 1))
            items.append({"item_id": hit.item_id, "qty": qty, "unit": hit.price_paise})
            lines.append(f"{qty} x {hit.name} ({format_rupees(hit.price_paise * qty)})")
            sub += hit.price_paise * qty
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=chosen.name, area=chosen.area,
            lines=lines, subtotal_paise=sub, max_total_paise=sub + sub // 5 + 15000,
            address=address, details={"restaurant_id": chosen.restaurant_id, "items": items},
            expires_at=self.ctx.now() + APPROVAL_TTL))

    async def execute(self, p: Proposal) -> ExecResult:
        rid, items = p.details["restaurant_id"], p.details["items"]
        qty = [ItemQty(item_id=i["item_id"], qty=i["qty"]) for i in items]
        grant = _grant(self.ctx, self.key, rid, qty, p.max_total_paise)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "restaurant_id": rid,
                "items": [q.model_dump() for q in qty]}
        if self.gate.decide("build_cart", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        try:
            cart = await self.conn.build_cart(rid, qty)
        except OutOfStock as e:
            return ExecResult("out_of_stock", names=", ".join(e.names), notes=self.flags())
        grant.mark_used("build_cart")
        unit = {i["item_id"]: i["unit"] for i in items}
        rose = [ln for ln in cart.lines if ln.unit_price_paise > unit.get(ln.item_id, 0)]
        addr = await self.conn.delivery_address()
        wrong_addr = bool(addr and p.address and norm(p.address) not in norm(addr)
                          and norm(addr) not in norm(p.address))
        if rose or cart.grand_total_paise > p.max_total_paise or wrong_addr:
            reason = ("the delivery address on the site is different" if wrong_addr
                      else "prices on the site went up")
            new = p.model_copy(update={
                "lines": [f"{ln.qty} x {ln.name} ({format_rupees(ln.line_total_paise)})"
                          for ln in cart.lines],
                "subtotal_paise": cart.subtotal_paise, "max_total_paise": cart.grand_total_paise,
                "exact": True, "address": addr or p.address,
                "details": {**p.details, "items": [{"item_id": ln.item_id, "qty": ln.qty,
                                                    "unit": ln.unit_price_paise}
                                                   for ln in cart.lines]},
                "expires_at": self.ctx.now() + APPROVAL_TTL})
            return ExecResult("reapprove", reason=reason, proposal=new, notes=self.flags())
        pay = {**args, "items": [q.model_dump() for q in cart.items()],
               "total_paise": cart.grand_total_paise}
        if self.gate.decide("get_payment_handoff", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        with self.kit.safety.approved("checkout_button"):
            handoff = await self.conn.get_payment_handoff(cart)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=cart.grand_total_paise,
                          notes=self.flags())


# ============================================================ movie
class MovieAdapter:
    key = "bookmyshow.movie"
    site, use_case, site_name = "bookmyshow", "movie", "BookMyShow"
    required = ("title", "seats", "time")

    def __init__(self, ctx: RunCtx) -> None:
        self.ctx, self.gate = ctx, ExtendedGate()
        self.kit = bms.build_kit(ctx.session, task_id=ctx.task_id, repairer=ctx.repairer)
        self.conn = bms.BookMyShowConnector(self.kit.session, **_kw(ctx))

    def flags(self) -> dict[str, bool]:
        return _flags(self.kit)

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        area = slots.get("area") or self.ctx.profile.area
        want = parse_minutes(slots["time"])
        shows = await self.conn.search_shows(slots["title"], area)
        if area:
            near = [s for s in shows if norm(area) in norm(s.area) or norm(area) in norm(s.cinema)]
            shows = near or shows
        if want is not None:
            shows = [s for s in shows if abs(s.minutes - want) <= 45]
        if not shows:
            return Prepared(problem=Problem("no_match", f"{slots['title']} at {slots['time']}"))
        show = min(shows, key=lambda s: abs(s.minutes - (want or s.minutes)))
        n = int(slots["seats"])
        seats = [s for s in await self.conn.get_seats(show.show_id) if s.available]
        rows: dict[str, list] = {}
        for s in seats:
            rows.setdefault(s.label[:1], []).append(s)
        pick = next((r[:n] for r in rows.values() if len(r) >= n), seats[:n])
        if len(pick) < n:
            return Prepared(problem=Problem("out_of_stock", f"{n} seats"))
        sub = sum(s.price_paise for s in pick)
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=show.cinema, area=show.area,
            lines=[f"{s.label} ({format_rupees(s.price_paise)})" for s in pick],
            subtotal_paise=sub, max_total_paise=sub + sub // 10 + 4000 * n, movie=show.movie,
            when=show.starts_at,
            details={"show_id": show.show_id,
                     "seats": [{"seat_id": s.seat_id, "unit": s.price_paise, "label": s.label}
                               for s in pick]},
            expires_at=self.ctx.now() + APPROVAL_TTL))

    async def execute(self, p: Proposal) -> ExecResult:
        sid, seats = p.details["show_id"], p.details["seats"]
        ids = [s["seat_id"] for s in seats]
        grant = _grant(self.ctx, self.key, sid, [ItemQty(item_id=i, qty=1) for i in ids],
                       p.max_total_paise)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "show_id": sid, "seat_ids": ids}
        if self.gate.decide("hold_seats", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        try:
            hold = await self.conn.hold_seats(sid, ids)
        except OutOfStock as e:
            return ExecResult("out_of_stock", names=", ".join(e.names) or "those seats",
                              notes=self.flags())
        grant.mark_used("build_cart")
        unit = {s["seat_id"]: s["unit"] for s in seats}
        rose = [ln for ln in hold.lines if ln.price_paise > unit.get(ln.seat_id, 0)]
        if rose or hold.total_paise > p.max_total_paise:
            new = p.model_copy(update={
                "lines": [f"{ln.label} ({format_rupees(ln.price_paise)})" for ln in hold.lines],
                "subtotal_paise": hold.subtotal_paise, "max_total_paise": hold.total_paise,
                "exact": True, "expires_at": self.ctx.now() + APPROVAL_TTL,
                "details": {**p.details, "seats": [{"seat_id": ln.seat_id, "unit": ln.price_paise,
                                                    "label": ln.label} for ln in hold.lines]}})
            return ExecResult("reapprove", reason="ticket prices on the site went up",
                              proposal=new, notes=self.flags())
        pay = {**args, "total_paise": hold.total_paise}
        if self.gate.decide("get_payment_handoff", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        with self.kit.safety.approved("proceed_to_pay"):
            handoff = await self.conn.get_payment_handoff(hold)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=hold.total_paise,
                          notes=self.flags())


ADAPTERS = {"zomato.food": FoodAdapter, "bookmyshow.movie": MovieAdapter}
