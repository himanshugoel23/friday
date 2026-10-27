"""Pure derivations: what to do and when, from a trip's legs. No I/O, no clock, no model.

Money and times are never decided by a language model (principle 1). Every function here is a
table-testable rule; the numbers are ``TripConfig`` values the founder approves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from friday.trips.config import TripConfig
from friday.trips.models import LegKind, TaskKind, Trip, TripLeg

TRAVEL_KINDS = (LegKind.FLIGHT, LegKind.TRAIN)


def zone_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:  # noqa: BLE001 - an unknown zone name falls back to the home zone
        return ZoneInfo("Asia/Kolkata")


def local(dt: datetime, tz: str | None) -> datetime:
    return dt.astimezone(zone_of(tz))


def local_at(d: date, hour: int, tz: str | None, minute: int = 0) -> datetime:
    """UTC instant for ``hour:minute`` wall-clock on ``d`` in ``tz``."""
    return datetime.combine(d, time(hour, minute), tzinfo=zone_of(tz)).astimezone(UTC)


# --------------------------------------------------------------------------- leave-by
@dataclass(frozen=True)
class LeaveBy:
    leave_at: datetime  # when to set off (UTC)
    depart_at: datetime
    buffer_minutes: int  # at the airport / station before departure
    travel_minutes: int
    travel_assumed: bool  # the user did not say: the default was used and is shown
    buffer_kind: str  # "domestic" | "international" | "train"
    international_assumed: bool = False


def leave_by(
    leg: TripLeg, trip: Trip, cfg: TripConfig, depart_at: datetime | None = None
) -> LeaveBy:
    """leave = departure - airport/station buffer - travel time (the user's number, else the
    stated default). ``depart_at`` overrides the leg time (a delayed flight re-derives it)."""
    depart = depart_at or leg.starts_at
    if leg.kind == LegKind.TRAIN:
        buf, kind = cfg.train_buffer_min, "train"
    elif leg.international:
        buf, kind = cfg.international_buffer_min, "international"
    else:
        buf, kind = cfg.domestic_buffer_min, "domestic"
    assumed = trip.travel_minutes is None
    travel = cfg.default_travel_min if assumed else int(trip.travel_minutes or 0)
    return LeaveBy(
        leave_at=depart - timedelta(minutes=buf + travel),
        depart_at=depart,
        buffer_minutes=buf,
        travel_minutes=travel,
        travel_assumed=assumed,
        buffer_kind=kind,
        international_assumed="intl_assumed" in leg.assumptions,
    )


# --------------------------------------------------------------------------- planned tasks
@dataclass(frozen=True)
class PlannedTask:
    kind: TaskKind
    leg_id: str | None
    due_at: datetime
    expires_at: datetime
    key: str
    params: dict[str, Any] = field(default_factory=dict)


def task_key(trip_id: str, kind: TaskKind, ref: str) -> str:
    return f"trip:{trip_id}:{kind.value}:{ref}"


def _stay_day_end(leg: TripLeg) -> datetime:
    d = local(leg.starts_at, leg.tz).date()
    return local_at(d, 23, leg.tz, 59)


def plan_leg(trip: Trip, leg: TripLeg, cfg: TripConfig) -> list[PlannedTask]:
    if leg.status != "active":
        return []
    out: list[PlannedTask] = []
    if leg.kind in TRAVEL_KINDS:
        lb = leave_by(leg, trip, cfg)
        due = lb.leave_at - timedelta(minutes=cfg.leave_heads_up_min)
        out.append(
            PlannedTask(
                TaskKind.LEAVE_BY,
                leg.id,
                due,
                lb.leave_at + timedelta(minutes=20),
                task_key(trip.id, TaskKind.LEAVE_BY, leg.id),
                {
                    "leave_at": lb.leave_at.isoformat(),
                    "buffer_minutes": lb.buffer_minutes,
                    "travel_minutes": lb.travel_minutes,
                    "travel_assumed": lb.travel_assumed,
                    "buffer_kind": lb.buffer_kind,
                    "critical": True,
                },
            )
        )
        out.append(
            PlannedTask(
                TaskKind.CAB,
                leg.id,
                lb.leave_at - timedelta(hours=cfg.cab_propose_hours_before),
                lb.leave_at,
                task_key(trip.id, TaskKind.CAB, leg.id),
                {"pickup_at": lb.leave_at.isoformat(), "proposal": True},
            )
        )
        if leg.number:
            start = leg.starts_at - timedelta(hours=cfg.watch_start_hours)
            out.append(
                PlannedTask(
                    TaskKind.FLIGHT_WATCH,
                    leg.id,
                    start,
                    leg.starts_at + timedelta(minutes=cfg.watch_stop_after_min),
                    task_key(trip.id, TaskKind.FLIGHT_WATCH, leg.id),
                    {"mode": leg.kind.value, "number": leg.number},
                )
            )
        if leg.kind == LegKind.FLIGHT:
            out.append(
                PlannedTask(
                    TaskKind.LOUNGE,
                    leg.id,
                    leg.starts_at - timedelta(hours=cfg.lounge_hours_before),
                    lb.leave_at,
                    task_key(trip.id, TaskKind.LOUNGE, leg.id),
                    {"international": leg.international},
                )
            )
    elif leg.kind == LegKind.STAY:
        d = local(leg.starts_at, leg.tz).date()
        expires = leg.starts_at if leg.time_known else _stay_day_end(leg)
        info_due = (
            leg.starts_at - timedelta(hours=3)
            if leg.time_known
            else local_at(d, cfg.hotel_default_checkin_hour, leg.tz)
        )
        out.append(
            PlannedTask(
                TaskKind.CHECKIN,
                leg.id,
                info_due,
                expires,
                task_key(trip.id, TaskKind.CHECKIN, leg.id),
                {"time_known": leg.time_known},
            )
        )
        out.append(
            PlannedTask(
                TaskKind.HOTEL_CALL,
                leg.id,
                local_at(d - timedelta(days=1), cfg.hotel_call_hour, leg.tz),
                expires,
                task_key(trip.id, TaskKind.HOTEL_CALL, leg.id),
                {"proposal": True, "phone_known": bool(leg.phone), "time_known": leg.time_known},
            )
        )
        if leg.ends_at is not None:
            ed = local(leg.ends_at, leg.end_tz or leg.tz).date()
            known = "checkout_time_unknown" not in leg.assumptions
            due = (
                leg.ends_at - timedelta(hours=cfg.checkout_heads_up_hours)
                if known
                else local_at(ed, cfg.hotel_default_checkin_hour, leg.end_tz or leg.tz)
            )
            out.append(
                PlannedTask(
                    TaskKind.CHECKOUT,
                    leg.id,
                    due,
                    due + timedelta(hours=6),
                    task_key(trip.id, TaskKind.CHECKOUT, leg.id),
                    {"time_known": known},
                )
            )
    return out


def plan_trip(trip: Trip, legs: list[TripLeg], cfg: TripConfig) -> list[PlannedTask]:
    """Every task of the trip, plus one morning plan per trip day that has something in it."""
    out: list[PlannedTask] = []
    for leg in sorted(legs, key=lambda x: x.starts_at):
        out.extend(plan_leg(trip, leg, cfg))
    days: dict[date, str] = {}
    for item in timeline_items(trip, legs, cfg):
        days.setdefault(item.local_date, item.tz)
    for d, tz in sorted(days.items()):
        due = local_at(d, cfg.day_plan_hour, tz)
        out.append(
            PlannedTask(
                TaskKind.DAY_PLAN,
                None,
                due,
                local_at(d, 12, tz),
                task_key(trip.id, TaskKind.DAY_PLAN, d.isoformat()),
                {"date": d.isoformat(), "tz": tz},
            )
        )
    return out


# --------------------------------------------------------------------------- day-wise timeline
@dataclass(frozen=True)
class PlanItem:
    at: datetime  # UTC
    tz: str
    kind: str  # "leave", "depart", "arrive", "hotel_call", "checkin", "checkout"
    leg: TripLeg
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def local_date(self) -> date:
        return local(self.at, self.tz).date()


def timeline_items(trip: Trip, legs: list[TripLeg], cfg: TripConfig) -> list[PlanItem]:
    items: list[PlanItem] = []
    for leg in legs:
        if leg.status != "active":
            continue
        if leg.kind in TRAVEL_KINDS:
            lb = leave_by(leg, trip, cfg)
            items.append(PlanItem(lb.leave_at, leg.tz, "leave", leg, {"leave": lb}))
            items.append(PlanItem(leg.starts_at, leg.tz, "depart", leg))
            if leg.ends_at is not None:
                items.append(PlanItem(leg.ends_at, leg.end_tz or leg.tz, "arrive", leg))
        elif leg.kind == LegKind.STAY:
            d = local(leg.starts_at, leg.tz).date()
            items.append(
                PlanItem(
                    local_at(d - timedelta(days=1), cfg.hotel_call_hour, leg.tz),
                    leg.tz,
                    "hotel_call",
                    leg,
                )
            )
            items.append(PlanItem(leg.starts_at, leg.tz, "checkin", leg))
            if leg.ends_at is not None:
                items.append(PlanItem(leg.ends_at, leg.end_tz or leg.tz, "checkout", leg))
    return sorted(items, key=lambda i: i.at)


def group_by_day(items: list[PlanItem]) -> list[tuple[date, list[PlanItem]]]:
    days: dict[date, list[PlanItem]] = {}
    for it in items:
        days.setdefault(it.local_date, []).append(it)
    return sorted(days.items())


# --------------------------------------------------------------------------- status watch schedule
def next_check_at(now: datetime, depart_at: datetime, cfg: TripConfig) -> datetime | None:
    """When to look at the status next. Before the watch window opens: its start. Then every
    ``watch_every_hours`` until the last ``watch_last_hours``, then hourly; none after departure
    plus ``watch_stop_after_min``."""
    if now > depart_at + timedelta(minutes=cfg.watch_stop_after_min):
        return None
    start = depart_at - timedelta(hours=cfg.watch_start_hours)
    if now < start:
        return start
    last = depart_at - timedelta(hours=cfg.watch_last_hours)
    if now < last:
        return min(now + timedelta(hours=cfg.watch_every_hours), last)
    return now + timedelta(minutes=cfg.watch_last_every_min)


@dataclass(frozen=True)
class StatusChange:
    kind: str  # "delay" | "cancelled" | "gate" | "terminal" | "back_on_time"
    delay_minutes: int = 0
    new_depart_at: datetime | None = None
    gate: str | None = None
    terminal: str | None = None


def detect_changes(
    leg: TripLeg,
    prev_delay: int,
    prev_info: dict[str, Any],
    prev_status: str | None,
    *,
    status: str,
    estimated_dep: datetime | None,
    gate: str | None,
    terminal: str | None,
    cfg: TripConfig,
) -> list[StatusChange]:
    """Only a real change is reported (delay beyond the threshold, cancellation, gate or terminal
    change). The first observation reports a gate/terminal only if it differs from the document."""
    out: list[StatusChange] = []
    if status == "cancelled":
        return [] if prev_status == "cancelled" else [StatusChange("cancelled")]
    delay = 0
    if estimated_dep is not None:
        delay = int((estimated_dep - leg.starts_at).total_seconds() // 60)
    if abs(delay - prev_delay) >= cfg.delay_threshold_min:
        if delay >= cfg.delay_threshold_min:
            out.append(StatusChange("delay", delay, estimated_dep))
        elif prev_delay >= cfg.delay_threshold_min and delay < cfg.delay_threshold_min:
            out.append(StatusChange("back_on_time", 0, leg.starts_at))
    if gate and gate != prev_info.get("gate"):
        out.append(StatusChange("gate", gate=gate))
    if terminal and terminal != (prev_info.get("terminal") or leg.terminal):
        out.append(StatusChange("terminal", terminal=terminal))
    return out
