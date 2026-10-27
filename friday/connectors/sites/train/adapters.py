# ruff: noqa: E501
"""Train adapters: IRCTC (``irctc.train``), ixigo (``ixigo.train``), eRail info (``erail.train_info``).

Booking flow: from, to, date, class, quota (tatkal only when the user says so), train shortlist with
honest availability, passengers from the user only -> approval -> login (password via autofill, then
the site's own code) -> availability re-check -> passengers -> fare page, extras unticked -> total
check (a rise means ask again) -> ONE armed click -> QR / UPI hand-off. A waitlisted or RAC ticket
needs an explicit extra approval; a captcha or a closed booking window is a hand-over.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from friday.connectors.contract import ItemQty, format_rupees
from friday.connectors.sites.adapters import ExecResult, Prepared, Problem, Proposal
from friday.connectors.sites.train.base import ScriptedAdapter
from friday.connectors.sites.train.common import AddOnStuck, clean, norm
from friday.connectors.sites.train.connector import ERailConnector, TrainConnector, make_kit
from friday.connectors.sites.train.contract import (
    CLASSES,
    Passenger,
    TrainOption,
    parse_passengers,
)

SHORTLIST = 5
FEE_CAP_PER_TICKET = 15000  # paise: reservation + convenience + gateway charges we accept (an assumption)
RANK = {"confirmed": 3, "rac": 2, "waitlist": 1}
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$|^(\d{2})-(\d{2})-(\d{4})$")


def parse_date(text: str, now: datetime) -> str | None:
    """ISO ``YYYY-MM-DD`` (or ``DD-MM-YYYY``), not in the past; else None (the user is asked)."""
    m = _DATE.match((text or "").strip())
    if not m:
        return None
    y, mo, d = (int(m.group(i)) for i in ((1, 2, 3) if m.group(1) else (6, 5, 4)))
    try:
        day = datetime(y, mo, d, tzinfo=now.tzinfo)
    except ValueError:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}" if day.date() >= now.date() else None


def norm_quota(text: str) -> str | None:
    t = (text or "").strip().lower()
    return {"general": "general", "gen": "general", "ordinary": "general", "tatkal": "tatkal",
            "tkl": "tatkal"}.get(t)


def option_line(o: TrainOption) -> str:
    fare = f", {format_rupees(o.fare_paise)} each" if o.fare_paise else ""
    return f"{o.train_no} {o.name}, {o.depart} to {o.arrive}, {o.cls}: {o.availability or o.status} ({o.status}){fare}"


class _TrainBookingAdapter(ScriptedAdapter):
    use_case = "train"
    required = ("from", "to", "date", "cls", "quota", "passengers")

    def make_kit(self):  # noqa: ANN201
        return make_kit(self.ctx.session, self.site, task_id=self.ctx.task_id, repairer=self.ctx.repairer)

    def make_conn(self) -> TrainConnector:
        return TrainConnector(self.kit.session, site=self.site, credentials=self.credentials,
                              raw_session=self.ctx.session, **self._kw())

    # ---- what the user still has to give (nothing is defaulted)
    def missing(self, slots: dict[str, Any]) -> str | None:
        for slot in self.required:
            if slot == "passengers":
                if parse_passengers(slots.get("passengers"))[1]:
                    return slot
            elif slot == "quota":
                if norm_quota(str(slots.get("quota") or "")) is None:
                    return slot
            elif slot == "cls":
                if str(slots.get("cls") or "").upper() not in CLASSES:
                    return slot
            elif slot == "date":
                if parse_date(str(slots.get("date") or ""), self.ctx.now()) is None:
                    return slot
            elif not slots.get(slot):
                return slot
        return None

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        gap = self.missing(slots)
        if gap:
            detail = parse_passengers(slots.get("passengers"))[1] if gap == "passengers" else gap
            return self._need("need_detail", gap, f"q_train_{gap}", detail or gap)
        pax, _ = parse_passengers(slots["passengers"])
        cls, quota = str(slots["cls"]).upper(), norm_quota(str(slots["quota"])) or "general"
        date = parse_date(str(slots["date"]), self.ctx.now()) or ""
        options = await self.conn.search(str(slots["from"]), str(slots["to"]), date, cls, quota)
        if not options:
            return Prepared(problem=Problem("no_match", f"trains {slots['from']} to {slots['to']}"))
        shortlist = options[:SHORTLIST]
        want = norm(str(slots.get("train") or ""))
        pick = next((o for o in shortlist if want and (want == norm(o.train_no) or want in norm(o.name))), None)
        if pick is None:  # the user chooses: we never pick a train for them
            return self._need("need_choice", "train", "q_train_pick", "which train", [option_line(o) for o in shortlist])
        if not pick.bookable:
            return Prepared(problem=Problem("out_of_stock", f"{pick.name} {cls}"))
        n, sub = len(pax), pick.fare_paise * len(pax)
        extra = pick.status if pick.status in {"waitlist", "rac"} else None
        lines = [option_line(pick), f"Date {date}, quota {quota}"]
        lines += [f"Passenger {i}: {p.name}, {p.age}, {p.gender}, berth {p.berth}" for i, p in enumerate(pax, 1)]
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name, area="",
            lines=lines, subtotal_paise=sub, max_total_paise=sub + FEE_CAP_PER_TICKET + sub // 50,
            when=f"{date} {pick.depart}",
            details={"mode": "book", "train_no": pick.train_no, "train_name": pick.name, "cls": cls,
                     "quota": quota, "date": date, "from": str(slots["from"]), "to": str(slots["to"]),
                     "status": pick.status, "availability": pick.availability, "unit": pick.fare_paise,
                     "passengers": [p.model_dump() for p in pax],
                     "shortlist": [option_line(o) for o in shortlist],
                     "extra_approval": extra, "extra_approval_given": False, "n": n},
            expires_at=self._expires()))

    async def execute(self, p: Proposal) -> ExecResult:
        d = p.details
        if d.get("extra_approval") and not d.get("extra_approval_given"):
            return self._reask(p, f"a {d['extra_approval']} ticket needs your explicit extra OK")
        pax = [Passenger(**x) for x in d["passengers"]]
        group = f"{d['train_no']}-{d['cls']}-{d['quota']}-{d['date']}"
        items = [ItemQty(item_id=f"{d['train_no']}-{d['cls']}", qty=len(pax))]
        grant, args = self._grant(group, items, p.max_total_paise), self._args(group, items)
        if not self._allowed("build_cart", args, grant):
            return self._reask(p, "approval no longer matches")
        await self.conn.ensure_logged_in()  # LoginRequired / LoginFailed / HandOver stop here
        opts = await self.conn.search(d["from"], d["to"], d["date"], d["cls"], d["quota"])
        if not any(o.train_no == d["train_no"] for o in opts):
            return ExecResult("out_of_stock", names=d["train_name"], notes=self.flags())
        now = await self.conn.availability(d["train_no"], d["cls"])
        if not now.bookable:
            return ExecResult("out_of_stock", names=d["train_name"], notes=self.flags())
        grant.mark_used("build_cart")
        if RANK[now.status] < RANK[d["status"]] or now.fare_paise > d["unit"]:
            extra = now.status if now.status in {"waitlist", "rac"} else None
            sub = now.fare_paise * len(pax)
            return self._reask(p, "seat availability or fare on the site changed", subtotal_paise=sub,
                               max_total_paise=max(p.max_total_paise, sub + FEE_CAP_PER_TICKET + sub // 50),
                               lines=[option_line(now), *p.lines[1:]],
                               details={**d, "status": now.status, "availability": now.availability,
                                        "unit": now.fare_paise, "extra_approval": extra,
                                        "extra_approval_given": False})
        await self.conn.fill_passengers(pax)
        quote = await self.conn.read_fare(pax)
        notes = self.flags()
        if quote.ticked():
            try:
                quote = await self.conn.untick_addons(quote, pax)
                notes["addon_unticked"] = True
            except AddOnStuck as e:  # cannot untick: say so and show the real total, never go on silently
                q = e.quote
                notes["addon_stuck"] = True
                extras = [f"Extra on the site: {a.label} ({format_rupees(a.amount_paise)})" for a in q.ticked()]
                return self._reask(p, "an extra (" + ", ".join(e.names) + ") could not be removed and is in the total",
                                   subtotal_paise=q.fare_paise, max_total_paise=q.total_paise,
                                   lines=[*p.lines, *extras], notes=notes)
        if quote.fare_paise > p.subtotal_paise or quote.total_paise > p.max_total_paise:
            return self._reask(p, "the fare on the site went up", subtotal_paise=quote.fare_paise,
                               max_total_paise=quote.total_paise,
                               lines=[*p.lines[:2], *[f"{f.name} ({format_rupees(f.amount_paise)})" for f in quote.fares]])
        pay = {**args, "total_paise": quote.total_paise}
        if not self._allowed("get_payment_handoff", pay, grant):
            return self._reask(p, "approval no longer matches")
        with self.kit.safety.approved("book_confirm"):
            handoff = await self.conn.confirm_booking(quote.total_paise)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=quote.total_paise, notes=notes)


class IrctcTrainAdapter(_TrainBookingAdapter):
    key, site, site_name = "irctc.train", "irctc", "IRCTC"


class IxigoTrainAdapter(_TrainBookingAdapter):
    key, site, site_name = "ixigo.train", "ixigo", "ixigo"


class ErailInfoAdapter(ScriptedAdapter):
    """Read-only: timetable and seat availability. No login, no booking, no approval, no clicks."""

    key, site, use_case, site_name = "erail.train_info", "erail", "train_info", "eRail"
    required = ("from", "to", "date")

    def make_kit(self):  # noqa: ANN201
        return make_kit(self.ctx.session, "erail", task_id=self.ctx.task_id, repairer=self.ctx.repairer)

    def make_conn(self) -> ERailConnector:
        return ERailConnector(self.kit.session, **{k: v for k, v in self._kw().items()
                                                    if k in {"base_url", "task_id"}})

    async def lookup(self, slots: dict[str, Any]) -> list[TrainOption]:
        date = parse_date(str(slots["date"]), self.ctx.now()) or str(slots["date"])
        trains = (await self.conn.timetable(str(slots["from"]), str(slots["to"]), date))[:SHORTLIST]
        cls = str(slots.get("cls") or "").upper()
        if cls not in CLASSES:
            return trains
        out = []
        for t in trains:
            seat = await self.conn.seats(t.train_no, date, cls)
            out.append(t if seat is None else TrainOption(**{**t.model_dump(), "cls": cls, "fare_paise": seat.fare_paise,
                                                              "status": seat.status, "availability": seat.availability}))
        return out

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        if str(slots.get("intent") or "").lower() in {"book", "booking"}:
            return Prepared(problem=Problem("not_supported", "booking on eRail (information only)"))  # type: ignore[arg-type]
        if self.missing(slots):
            gap = self.missing(slots) or ""
            return self._need("need_detail", gap, f"q_train_{gap}", gap)
        trains = await self.lookup(slots)
        if not trains:
            return Prepared(problem=Problem("no_match", f"trains {slots['from']} to {slots['to']}"))
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name,
            lines=[option_line(t) if t.cls else f"{t.train_no} {t.name}, {t.depart} to {t.arrive}" for t in trains],
            subtotal_paise=0, max_total_paise=0, details={"mode": "info", "read_only": True},
            expires_at=self._expires()))

    async def execute(self, p: Proposal) -> ExecResult:
        return ExecResult("info", reason="\n".join(clean(x, 160) for x in p.lines), notes=self.flags())


ADAPTERS = {"irctc.train": IrctcTrainAdapter, "ixigo.train": IxigoTrainAdapter,
            "erail.train_info": ErailInfoAdapter}
__all__ = ["ADAPTERS", "IrctcTrainAdapter", "IxigoTrainAdapter", "ErailInfoAdapter",
           "parse_date", "norm_quota", "option_line"]
