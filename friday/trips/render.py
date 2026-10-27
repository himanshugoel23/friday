"""Text of the day-wise plan and the thread prefix. Pure: structured items in, wording from copy."""

from __future__ import annotations

from friday.trips import copy
from friday.trips.config import TripConfig
from friday.trips.copy import fmt_date, fmt_day, fmt_time, t
from friday.trips.derive import PlanItem, group_by_day, timeline_items
from friday.trips.models import LegKind, Trip, TripLeg


def prefix(trip: Trip, text: str) -> str:
    """Every trip message starts with the trip name: the per-trip thread inside the 1:1 chat."""
    return f"[{copy.clean_name(trip.title, 40)}] {text}"


def _route(leg: TripLeg) -> str:
    return " - ".join(x for x in (leg.origin, leg.dest) if x)


def mode_word(leg: TripLeg, lang: str) -> str:
    if leg.kind == LegKind.TRAIN:
        return "train"
    return "flight"


def item_line(it: PlanItem, lang: str) -> str:
    leg, tm = it.leg, fmt_time(it.at, it.tz)
    if it.kind == "leave":
        lb = it.data["leave"]
        return t(
            "plan.leave",
            lang,
            time=tm,
            mode=mode_word(leg, lang),
            dep=fmt_time(leg.starts_at, leg.tz),
            buf=lb.buffer_minutes,
            travel=lb.travel_minutes,
        )
    if it.kind == "depart":
        return t(
            "plan.depart", lang, time=tm, label=leg.label or mode_word(leg, lang), route=_route(leg)
        ).strip()
    if it.kind == "arrive":
        return t("plan.arrive", lang, time=tm, route=_route(leg))
    if it.kind == "hotel_call":
        return t("plan.hotel_call", lang, time=tm, hotel=leg.label or "hotel")
    if it.kind == "checkin":
        if not leg.time_known:
            return t("plan.checkin.unknown", lang, hotel=leg.label or "hotel")
        return t("plan.checkin", lang, time=tm, hotel=leg.label or "hotel")
    return t("plan.checkout", lang, time=tm, hotel=leg.label or "hotel")


def assumption_lines(trip: Trip, legs: list[TripLeg], cfg: TripConfig, lang: str) -> list[str]:
    out: list[str] = []
    travel = [x for x in legs if x.kind in (LegKind.FLIGHT, LegKind.TRAIN) and x.status == "active"]
    if travel and trip.travel_minutes is None:
        out.append(t("plan.assume.travel", lang, mins=cfg.default_travel_min))
    if any("intl_assumed" in x.assumptions for x in legs):
        out.append(t("plan.assume.intl", lang))
    if any("tz_assumed" in x.assumptions for x in legs):
        out.append(t("plan.assume.tz", lang))
    if any(x.pointer_kind for x in legs):
        out.append(t("plan.pointer", lang))
    return out


def render_plan(trip: Trip, legs: list[TripLeg], cfg: TripConfig, lang: str = "hinglish") -> str:
    items = timeline_items(trip, legs, cfg)
    lines = [t("plan.header", lang, start=fmt_date(trip.start_date), end=fmt_date(trip.end_date))]
    for _day, its in group_by_day(items):
        lines.append(t("plan.day", lang, day=fmt_day(its[0].at, its[0].tz)))
        lines.extend(f"- {item_line(i, lang)}" for i in its)
    lines.extend(assumption_lines(trip, legs, cfg, lang))
    return prefix(trip, "\n".join(lines))
