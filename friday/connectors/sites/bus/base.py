# ruff: noqa: E501
"""Shared base for the BUS use case (redBus, AbhiBus). Selectors target the FAKE bus sites only
(sites/fakes/bus_site.py); the real sites are UNVERIFIED.

Flow: search -> options (at most 5) -> pick -> seat map (seat type, availability) -> boarding and
dropping point -> approval card (operator cancellation policy read back, total cap, expiry) -> ONLY
THEN select seats (the site holds them for a short time) -> total check (a rise means RE-ASK) ->
re-check the hold is still alive -> ONE irreversible click armed by the approval -> QR / UPI.
The approval card expires (5 minutes) BEFORE any seat hold can (the site's hold is 8+ minutes and is
only started after approval), and the hold is re-checked just before the click.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from friday.connectors.browser.port import ElementNotFound
from friday.connectors.contract import (
    Charge,
    ConnectorError,
    ItemQty,
    LayoutChanged,
    TotalsMismatch,
    format_rupees,
)
from friday.connectors.gate import ActionGate, Grant, Verdict
from friday.connectors.sites.adapters import ExecResult, Prepared, Problem, Proposal
from friday.connectors.sites.bus.contract import (
    BusOption,
    HoldExpired,
    Point,
    PolicyRow,
    Seat,
    SeatHold,
    SeatLine,
)
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.stay import base as sb
from friday.connectors.sites.stay.base import (
    HandoverProblem,
    ScriptedSiteBase,
    SiteConfig,
    build_kit,
    clean_names,
    clean_text,
    parse_inr,
    safe_id,
)

BUS_APPROVAL_TTL = timedelta(minutes=5)  # shorter than every site's seat hold (cfg.hold_s)
MIN_HOLD_LEFT_S = 120  # below this the hold is too short to finish: ask again
BUS_PLAIN = (
    "account_name", "phone_input", "send_otp_button", "otp_input", "submit_otp_button",
    "result_card", "seat", "boarding_option", "dropping_option", "cancel_policy_row", "hold_button",
    "hold_timer", "review_line", "review_fee_row", "review_tax_row", "review_total",
    "proceed_to_pay", "pay_amount", "pay_merchant", "pay_order_ref", "pay_qr", "pay_upi_link",
)
BUS_PARAM = {"seat_pick": "seat_id", "boarding_pick": "point_id", "dropping_pick": "point_id",
             "passenger_name_input": "n"}
BUS_ROWS = {
    "result_card": ("item_id", "name", "kind", "depart", "price"),
    "seat": ("seat_id", "label", "kind", "price", "available"),
    "boarding_option": ("point_id", "name", "time"),
    "dropping_option": ("point_id", "name", "time"),
    "cancel_policy_row": ("window", "pct"),
    "hold_timer": ("seconds",),
    "review_line": ("seat_id", "label", "price"),
    "charge_row": ("name", "amount"),
    "review_total": ("currency",),
}


def bus_config(**kw: Any) -> SiteConfig:
    return SiteConfig(plain=BUS_PLAIN, params=dict(BUS_PARAM), rows=dict(BUS_ROWS), **kw)


def norm_type(raw: str) -> str:
    return re.sub(r"[^a-z]+", " ", (raw or "").lower()).strip()


class BusConnector(ScriptedSiteBase):
    async def search(self, **params: Any) -> list[BusOption]:
        await self._goto("search", **params)
        out = []
        for r in await self._rows("result_card"):
            if not sb._SAFE_ID.match(r.get("item_id", "")):  # noqa: SLF001
                continue
            try:
                out.append(BusOption(item_id=r["item_id"], operator=clean_text(self._kit, r.get("name", "")) or "Operator",
                                     bus_type=norm_type(r.get("kind", "")), depart=clean_text(None, r.get("depart", ""), 8),
                                     price_paise=parse_inr(r.get("price", ""), r.get("currency", ""))))
            except ValidationError:
                continue
        return out

    async def layout(self, item_id: str, **params: Any) -> tuple[list[Seat], list[Point], list[Point], list[PolicyRow]]:
        await self._goto("detail", item_id=safe_id(item_id, "bus id"), **params)
        seats = []
        for r in await self._rows("seat"):
            try:
                seats.append(Seat(seat_id=safe_id(r["seat_id"], "seat id"), label=r.get("label", ""),
                                  kind=norm_type(r.get("kind", "")), price_paise=parse_inr(r["price"]),
                                  available=r.get("available", "").lower() == "true"))
            except (KeyError, ValidationError, ConnectorError):
                continue
        if not seats:
            raise LayoutChanged("no seats found")
        pts = {}
        for key in ("boarding_option", "dropping_option"):
            pts[key] = []
            for r in await self._rows(key):
                try:
                    pts[key].append(Point(point_id=safe_id(r["point_id"], "point id"),
                                          name=clean_text(self._kit, r.get("name", ""), 60), time=clean_text(None, r.get("time", ""), 8)))
                except (KeyError, ValidationError, ConnectorError):
                    continue
        policy = [PolicyRow(window=clean_text(self._kit, r.get("window") or r.get("text", ""), 80), refund_pct=r.get("pct", "").strip()[:4])
                  for r in await self._rows("cancel_policy_row")]
        return seats, pts["boarding_option"], pts["dropping_option"], policy

    async def hold(self, item_id: str, params: dict[str, Any], seat_ids: list[str], boarding: str,
                   dropping: str, names: list[str]) -> SeatHold:
        """Select seats + points + the names the USER gave, then let the site hold the seats."""
        seats, _, _, _ = await self.layout(item_id, **params)
        by = {s.seat_id: s for s in seats}
        gone = [s for s in seat_ids if s not in by or not by[s].available]
        if gone:
            raise OutOfStock("a seat is taken", [by[g].label if g in by else g for g in gone])
        for sid in seat_ids:
            await self._s.click(self.sel["seat_pick"].format(seat_id=safe_id(sid, "seat id")))
        await self._s.click(self.sel["boarding_pick"].format(point_id=safe_id(boarding, "point id")))
        await self._s.click(self.sel["dropping_pick"].format(point_id=safe_id(dropping, "point id")))
        for i, name in enumerate(names, 1):
            await self._s.fill(self.sel["passenger_name_input"].format(n=i), name)
        await self._s.click(self.sel["hold_button"])
        try:
            h = await self.read_hold()
        except HoldExpired:
            raise OutOfStock("the seats could not be held", []) from None
        if sorted(x.seat_id for x in h.lines) != sorted(seat_ids):
            raise OutOfStock("the held seats differ from the request", [])
        return h

    async def read_hold(self) -> SeatHold:
        timer = await self._rows("hold_timer")
        try:
            left = int(timer[0].get("seconds", "0")) if timer else 0
            await self._s.wait_for(self.sel["review_total"], 3000)
        except (ValueError, ElementNotFound):
            left = 0
        if left <= 0:
            raise HoldExpired("the seat hold has run out")
        lines = []
        for r in await self._rows("review_line"):
            try:
                lines.append(SeatLine(seat_id=safe_id(r["seat_id"], "seat id"), label=r.get("label", ""), price_paise=parse_inr(r["price"])))
            except (KeyError, ValidationError):
                raise LayoutChanged("summary line could not be read") from None
        tot = (await self._rows("review_total"))[:1]
        total = parse_inr(await self._text("review_total"), tot[0].get("currency", "") if tot else "")
        fees: list[Charge] = await self._charges("review_fee_row")
        taxes: list[Charge] = await self._charges("review_tax_row")
        try:
            return SeatHold(lines=lines, fees=fees, taxes=taxes, subtotal_paise=sum(x.price_paise for x in lines),
                            total_paise=total, seconds_left=left)
        except ValidationError:
            raise TotalsMismatch("booking totals on the page do not add up") from None

    async def finalize(self, approved: SeatHold):  # noqa: ANN201
        again = await self.read_hold()  # raises HoldExpired when the seats lapsed meanwhile
        if again.total_paise != approved.total_paise:
            raise TotalsMismatch("the total changed since the booking was approved")
        if again.seconds_left < MIN_HOLD_LEFT_S // 2:
            raise HoldExpired("the seat hold is about to run out")
        await self._s.click(self.sel["proceed_to_pay"])
        return await self.read_handoff(approved.total_paise)


def _match(options: list[Point], wanted: str) -> Point | None:
    w = sb_norm(wanted)
    return next((o for o in options if w and (w in sb_norm(o.name) or sb_norm(o.name) in w)), None) if w else None


def sb_norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class BusAdapter:
    cfg: SiteConfig
    key: str
    site: str
    site_name: str
    use_case = "bus"
    required = ("origin", "destination", "date", "passengers")

    def __init__(self, ctx) -> None:  # noqa: ANN001 - RunCtx
        self.ctx, self.gate = ctx, ActionGate(now=ctx.now)
        self.kit = build_kit(ctx.session, self.cfg, task_id=ctx.task_id, repairer=ctx.repairer)
        kw: dict[str, Any] = dict(cfg=self.cfg, base_url=ctx.base_url, task_id=ctx.task_id, otp_channel=ctx.otp,
                                  phone=ctx.profile.phone or None, on_code_wait=ctx.on_code_wait,
                                  otp_wait_s=ctx.otp_wait_s, poll_s=ctx.poll_s)
        if ctx.sleep:
            kw["sleep"] = ctx.sleep
        self.conn = BusConnector(self.kit.session, **kw)
        self.conn._kit = self.kit  # noqa: SLF001

    @property
    def link(self) -> str:
        return self.cfg.home

    def flags(self) -> dict[str, bool]:
        return {"injection": self.kit.safety.injection_count > 0, "repaired": bool(self.kit.repairs.records)}

    def _need(self, slot: str, what: str = "", options: list[str] | None = None) -> Prepared:
        return Prepared(problem=HandoverProblem("need_info", what or slot, slot=slot, options=options or [], link=self.link))

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        today = self.ctx.now().date()
        for k in ("origin", "destination"):
            if not str(slots.get(k, "")).strip():
                return self._need(k)
        day = sb._day(slots.get("date"))  # noqa: SLF001
        if day is None or day < today:
            return self._need("date")
        names = clean_names(slots.get("passengers"))
        n = len(names)
        want = sb._int(slots.get("passenger_count"), n or 1, 6)  # noqa: SLF001
        if not names or n != want:  # never invent a name
            return self._need("passengers", f"{want} passenger name(s) as on the ID")
        params = {"origin": str(slots["origin"]).strip()[:60], "destination": str(slots["destination"]).strip()[:60],
                  "date": day.isoformat()}
        kind = norm_type(str(slots.get("seat_type", "")))
        budget = sb._paise(slots.get("budget"))  # noqa: SLF001
        options = await self.conn.search(**params)
        if kind in {"sleeper", "seater"}:
            options = [o for o in options if kind in o.bus_type.split()]
        if slots.get("ac") is True:
            options = [o for o in options if "non" not in o.bus_type.split() and "ac" in o.bus_type.split()]
        if budget is not None:
            options = [o for o in options if o.price_paise * n <= budget]
        if not options:
            return Prepared(problem=Problem("no_match", f"a bus from {params['origin']} to {params['destination']}"))
        shortlist = sorted(options, key=lambda o: o.price_paise)[:5]
        choice = sb._int(slots.get("choice"), 0, 5)  # noqa: SLF001
        order = [shortlist[choice - 1]] if 1 <= choice <= len(shortlist) else shortlist
        sold = False
        for opt in order:
            seats, board, drop, policy = await self.conn.layout(opt.item_id, **params)
            free = [s for s in seats if s.available and (kind not in {"sleeper", "seater"} or s.kind == kind)]
            rows: dict[str, list[Seat]] = {}
            for s in free:
                rows.setdefault(s.label[:1], []).append(s)
            pick = next((r[:n] for r in rows.values() if len(r) >= n), free[:n])
            if len(pick) < n:
                sold = True
                continue
            b, d = _match(board, str(slots.get("boarding", ""))), _match(drop, str(slots.get("dropping", "")))
            if b is None:
                return self._need("boarding", "boarding point", [f"{x.name} {x.time}".strip() for x in board])
            if d is None:
                return self._need("dropping", "dropping point", [f"{x.name} {x.time}".strip() for x in drop])
            sub = sum(s.price_paise for s in pick)
            cap = sub + sub * 12 // 100 + 5000 * n
            lines = [f"{opt.operator} ({opt.bus_type}) departs {opt.depart}",
                     "Seats: " + ", ".join(f"{s.label} ({format_rupees(s.price_paise)})" for s in pick),
                     f"Board: {b.name} {b.time}".strip(), f"Drop: {d.name} {d.time}".strip()]
            lines += [f"Cancellation: {r.window}: {r.refund_pct}% refund" for r in policy]
            return Prepared(proposal=Proposal(
                task_id=self.ctx.task_id, connector=self.key, merchant=opt.operator, area=params["destination"],
                lines=lines, subtotal_paise=sub, max_total_paise=cap, when=f"{day.isoformat()} {opt.depart}",
                details={"item_id": opt.item_id, "params": params, "names": names, "bus_type": opt.bus_type,
                         "seats": [{"seat_id": s.seat_id, "label": s.label, "unit": s.price_paise} for s in pick],
                         "boarding": {"point_id": b.point_id, "name": b.name, "time": b.time},
                         "dropping": {"point_id": d.point_id, "name": d.name, "time": d.time},
                         "policy": [{"window": r.window, "pct": r.refund_pct} for r in policy],
                         "hold_s": self.cfg.hold_s,
                         "shortlist": [{"n": i, "name": o.operator, "from_paise": o.price_paise} for i, o in enumerate(shortlist, 1)]},
                expires_at=self.ctx.now() + BUS_APPROVAL_TTL))
        return Prepared(problem=Problem("out_of_stock" if sold else "no_match", f"{n} seat(s)"))

    def _refreshed(self, p: Proposal, **update: Any) -> Proposal:
        return p.model_copy(update={"expires_at": self.ctx.now() + BUS_APPROVAL_TTL, **update})

    async def execute(self, p: Proposal) -> ExecResult:
        d = p.details
        seats = d["seats"]
        ids = [s["seat_id"] for s in seats]
        grant = Grant(task_id=self.ctx.task_id, connector=self.key, restaurant_id=d["item_id"],
                      items=[ItemQty(item_id=i, qty=1) for i in ids], max_total_paise=p.max_total_paise,
                      expires_at=self.ctx.now() + BUS_APPROVAL_TTL)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "restaurant_id": d["item_id"],
                "items": [{"item_id": i, "qty": 1} for i in ids]}
        if self.gate.decide("build_cart", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        await self.conn.ensure_logged_in()
        try:
            hold = await self.conn.hold(d["item_id"], d["params"], ids, d["boarding"]["point_id"],
                                        d["dropping"]["point_id"], list(d["names"]))
        except OutOfStock as e:
            return ExecResult("out_of_stock", names=", ".join(e.names) or "those seats", notes=self.flags())
        grant.mark_used("build_cart")
        unit = {s["seat_id"]: s["unit"] for s in seats}
        rose = [x for x in hold.lines if x.price_paise > unit.get(x.seat_id, 0)]
        if rose or hold.total_paise > p.max_total_paise:
            new = self._refreshed(p, lines=[x for x in p.lines if not x.startswith("Seats:")] + [
                "Seats: " + ", ".join(f"{x.label} ({format_rupees(x.price_paise)})" for x in hold.lines),
                f"Total {format_rupees(hold.total_paise)} including fees and taxes"],
                subtotal_paise=hold.subtotal_paise, max_total_paise=hold.total_paise, exact=True,
                details={**d, "seats": [{"seat_id": x.seat_id, "label": x.label, "unit": x.price_paise} for x in hold.lines]})
            return ExecResult("reapprove", reason="ticket prices on the site went up", proposal=new, notes=self.flags())
        if hold.seconds_left < MIN_HOLD_LEFT_S:
            return ExecResult("reapprove", reason="the seat hold is too short to finish safely",
                              proposal=self._refreshed(p), notes=self.flags())
        pay = {**args, "total_paise": hold.total_paise}
        if self.gate.decide("get_payment_handoff", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        try:
            with self.kit.safety.approved("proceed_to_pay"):
                handoff = await self.conn.finalize(hold)
        except HoldExpired:
            return ExecResult("reapprove", reason="the seat hold ran out before the last step",
                              proposal=self._refreshed(p), notes=self.flags())
        return ExecResult("payment_ready", handoff=handoff, amount_paise=hold.total_paise, notes=self.flags())
