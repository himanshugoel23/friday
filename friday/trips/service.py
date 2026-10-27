# ruff: noqa: E501
"""The trip service: build trips, keep the derived tasks fresh, nudge on time, watch status.

Everything outbound goes through ports (sender, task engine, status provider) that have fakes. A
proposal (call the hotel, cab) never runs on its own: the user approves it, and the existing task
engine then asks again before it dials. Friday books nothing here.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from friday.core.clock import Clock, ist_date, ist_day_bounds
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import CallMode, Language, TaskSpec, TaskType
from friday.docunderstand.models import DocType, Document
from friday.trips import copy
from friday.trips.builder import BuildResult, TripBuilder, _clean_phone
from friday.trips.config import TripConfig
from friday.trips.copy import fmt_day, fmt_time, t
from friday.trips.derive import (
    PlannedTask,
    detect_changes,
    leave_by,
    local,
    next_check_at,
    plan_leg,
    plan_trip,
    timeline_items,
)
from friday.trips.handoff import ride_link
from friday.trips.lounge import lounge_hints
from friday.trips.models import (
    OPEN_STATES,
    FlightWatch,
    LegKind,
    TaskKind,
    TaskState,
    Trip,
    TripLeg,
    TripNudge,
    TripStatus,
    TripTask,
)
from friday.trips.perks import PerkSource
from friday.trips.ports import (
    Button,
    FlightStatusPort,
    ProviderUnavailable,
    StatusQuery,
    TripMessage,
    TripSender,
    TripTaskPort,
    WalletReader,
)
from friday.trips.render import prefix, render_plan

log = get_logger(__name__)

TOPIC = "trip"
TOPIC_FLIGHT = "trip_flight"
TOPIC_LOUNGE = "trip_lounge"


class TripsDisabled(RuntimeError):
    """The trip switch is off (or this user is not on the allow-list)."""


@dataclass
class Outcome:
    key: str
    kind: str
    action: str  # sent | held_quiet | held_cap | expired | muted | skipped | failed | watched
    text: str | None = None
    reason: str = ""


@dataclass
class TripReply:
    text: str
    buttons: list[Button] = field(default_factory=list)
    trip_id: str | None = None


def _in_quiet(dt: datetime, tz: str, start: int, end: int) -> bool:
    h = local(dt, tz).hour
    if start == end:
        return False
    return start <= h < end if start < end else (h >= start or h < end)


class TripService:
    def __init__(
        self,
        settings: Settings,
        store: Any,
        clock: Clock,
        *,
        docs: Any = None,
        sender: TripSender | None = None,
        tasks: TripTaskPort | None = None,
        status: FlightStatusPort | None = None,
        perks: PerkSource | None = None,
        wallet: WalletReader | None = None,
        config: TripConfig | None = None,
        language: str = "hinglish",
        extra_sent_today: Callable[[str], Awaitable[int]] | None = None,
        refunds: Any = None,
    ) -> None:
        self.settings, self.store, self.clock = settings, store, clock
        self.docs, self.sender, self.tasks, self.status = docs, sender, tasks, status
        self.perks, self.wallet = perks, wallet
        self.cfg = config or TripConfig.from_settings(settings)
        self.lang = language
        self.extra_sent_today = extra_sent_today
        self.refunds = refunds  # RefundService (optional): a cancellation proposes a refund case
        self.builder = TripBuilder(store, clock)

    # ------------------------------------------------------------------ switch
    def enabled_for(self, user_id: str) -> bool:
        if not self.settings.trips_enabled:
            return False
        allowed = {x.strip() for x in self.settings.trips_enabled_users if x.strip()}
        return not allowed or user_id in allowed

    def _need(self, user_id: str) -> None:
        if not self.enabled_for(user_id):
            raise TripsDisabled("trips are off")

    # ------------------------------------------------------------------ building
    async def create_from_documents(
        self, user_id: str, doc_ids: list[str] | None = None
    ) -> BuildResult:
        """Build or extend trips from the user's CONFIRMED documents (all, or the ones named)."""
        self._need(user_id)
        if self.docs is None:
            return BuildResult()
        docs: list[Document] = await self.docs.list_confirmed(user_id)
        if doc_ids is not None:
            docs = [d for d in docs if d.id in set(doc_ids)]
        res = await self.builder.from_documents(
            user_id,
            [d for d in docs if d.doc_type in (DocType.FLIGHT, DocType.TRAIN, DocType.HOTEL)],
        )
        for trip in res.trips:
            await self.refresh(user_id, trip.id)
        return res

    async def create_from_user(
        self, user_id: str, doc_type: DocType, values: dict[str, str]
    ) -> BuildResult:
        self._need(user_id)
        res = await self.builder.from_user(user_id, doc_type, values)
        for trip in res.trips:
            await self.refresh(user_id, trip.id)
        return res

    async def create_trip(self, user_id: str, title: str, start: date, end: date) -> Trip:
        self._need(user_id)
        return await self.builder.new_trip(user_id, title, start, end)

    # ------------------------------------------------------------------ derived tasks
    async def _watches(self, user_id: str, legs: list[TripLeg]) -> dict[str, FlightWatch]:
        out: dict[str, FlightWatch] = {}
        for leg in legs:
            w = await self.store.get_watch(user_id, leg.id)
            if w is not None:
                out[leg.id] = w
        return out

    def _planned(
        self, trip: Trip, legs: list[TripLeg], watches: dict[str, FlightWatch]
    ) -> list[PlannedTask]:
        plan = plan_trip(trip, legs, self.cfg)
        shifted: dict[tuple[str, str], PlannedTask] = {}
        for leg in legs:
            w = watches.get(leg.id)
            if w and w.delay_minutes > 0 and leg.kind in (LegKind.FLIGHT, LegKind.TRAIN):
                shadow = leg.model_copy(
                    update={"starts_at": leg.starts_at + timedelta(minutes=w.delay_minutes)}
                )
                for p in plan_leg(trip, shadow, self.cfg):
                    if p.kind in (TaskKind.LEAVE_BY, TaskKind.CAB):
                        shifted[(p.kind.value, leg.id)] = p
        return [shifted.get((p.kind.value, p.leg_id or ""), p) for p in plan]

    async def refresh(self, user_id: str, trip_id: str) -> list[TripTask]:
        """Re-derive the trip's tasks from its legs. Done/skipped/running tasks and times the user
        moved are left alone; a task whose leg is gone is skipped."""
        trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            return []
        legs = await self.store.list_legs(user_id, trip_id)
        leg_tz = {x.id: x.tz for x in legs}
        planned = self._planned(trip, legs, await self._watches(user_id, legs))
        now = self.clock.now()
        keys = set()
        for p in planned:
            keys.add(p.key)
            params = dict(p.params)
            params.setdefault("tz", leg_tz.get(p.leg_id or "", "Asia/Kolkata"))
            cur = await self.store.find_task(user_id, p.key)
            if cur is None:
                await self.store.save_task(
                    TripTask(
                        user_id=user_id,
                        trip_id=trip_id,
                        leg_id=p.leg_id,
                        kind=p.kind,
                        due_at=p.due_at,
                        expires_at=p.expires_at,
                        dedupe_key=p.key,
                        params=params,
                        created_at=now,
                        updated_at=now,
                    )
                )
                continue
            if cur.locked or cur.state in (
                TaskState.DONE,
                TaskState.SKIPPED,
                TaskState.RUNNING,
                TaskState.APPROVED,
            ):
                continue
            moved = cur.due_at != p.due_at
            cur.params = {**cur.params, **params}
            cur.due_at, cur.expires_at, cur.updated_at = p.due_at, p.expires_at, now
            if moved and cur.kind == TaskKind.LEAVE_BY and cur.state == TaskState.NUDGED:
                cur.state = TaskState.PLANNED  # the leave-by time changed: a fresh heads-up
            await self.store.save_task(cur)
        for cur in await self.store.list_tasks(user_id, trip_id):
            if cur.dedupe_key not in keys and cur.state in OPEN_STATES:
                cur.state, cur.updated_at = TaskState.SKIPPED, now
                await self.store.save_task(cur)
        return await self.store.list_tasks(user_id, trip_id)

    # ------------------------------------------------------------------ the user's inputs
    async def _trip_for(self, user_id: str, trip_id: str | None) -> Trip | None:
        if trip_id:
            return await self.store.get_trip(user_id, trip_id)
        trips = await self.store.list_trips(user_id, (TripStatus.ACTIVE, TripStatus.DRAFT))
        today = ist_date(self.clock.now())
        upcoming = [x for x in trips if x.end_date >= today] or trips
        return upcoming[0] if upcoming else None

    async def set_travel_minutes(self, user_id: str, trip_id: str, minutes: int) -> TripReply:
        self._need(user_id)
        trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        trip.travel_minutes = max(0, min(600, int(minutes)))
        trip.updated_at = self.clock.now()
        await self.store.save_trip(trip)
        await self.refresh(user_id, trip_id)
        return TripReply(
            prefix(trip, t("travel.set", self.lang, mins=trip.travel_minutes)), trip_id=trip_id
        )

    async def set_pickup_address(self, user_id: str, trip_id: str, address: str) -> TripReply:
        self._need(user_id)
        trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        trip.pickup_address = copy.clean_name(address, 120) or None
        await self.store.save_trip(trip)
        out = [t("pickup.set", self.lang)]
        for task in await self.store.list_tasks(user_id, trip_id):
            if task.kind == TaskKind.CAB and task.state == TaskState.NUDGED and trip.pickup_address:
                task.state = TaskState.DONE
                await self.store.save_task(task)
                link = ride_link(trip.pickup_address, task.params.get("drop"))
                out.append(t("cab.handoff", self.lang, link=link))
        return TripReply(prefix(trip, "\n".join(out)), trip_id=trip_id)

    async def set_muted(self, user_id: str, trip_id: str, muted: bool) -> TripReply:
        trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        trip.muted = muted
        await self.store.save_trip(trip)
        return TripReply(
            prefix(trip, t("muted" if muted else "unmuted", self.lang)), trip_id=trip_id
        )

    async def skip_task(self, user_id: str, task_id: str) -> TripReply:
        task = await self.store.get_task(user_id, task_id)
        if task is None:
            return TripReply(t("task.unknown", self.lang))
        task.state = TaskState.SKIPPED  # a user message always wins over a derived task
        await self.store.save_task(task)
        return TripReply(t("task.skipped", self.lang), trip_id=task.trip_id)

    async def set_task_time(self, user_id: str, task_id: str, due_at: datetime) -> bool:
        task = await self.store.get_task(user_id, task_id)
        if task is None:
            return False
        task.due_at, task.locked = due_at, True
        if task.state == TaskState.NUDGED:
            task.state = TaskState.PLANNED
        await self.store.save_task(task)
        return True

    # ------------------------------------------------------------------ proposals
    async def approve_task(self, user_id: str, task_id: str) -> TripReply:
        self._need(user_id)
        task = await self.store.get_task(user_id, task_id)
        if (
            task is None
            or task.kind != TaskKind.HOTEL_CALL
            or task.state not in (TaskState.NUDGED, TaskState.NEEDS_NUMBER)
        ):
            return TripReply(t("task.unknown", self.lang))
        trip = await self.store.get_trip(user_id, task.trip_id)
        leg = next(
            (x for x in await self.store.list_legs(user_id, task.trip_id) if x.id == task.leg_id),
            None,
        )
        if trip is None or leg is None or self.tasks is None:
            return TripReply(t("task.unknown", self.lang))
        if not leg.phone:  # the number comes from the document or the user, never from us
            task.state, task.params = TaskState.NEEDS_NUMBER, {**task.params, "approved": True}
            await self.store.save_task(task)
            return TripReply(prefix(trip, t("hotel_call.ask_number", self.lang)), trip_id=trip.id)
        spec = TaskSpec(
            type=TaskType.RECONFIRM,
            goal=f"Confirm the hotel booking and arrival with {leg.label or 'the hotel'}",
            business_name=leg.label,
            business_phone=leg.phone,
            reference=leg.ref,
            questions=list(copy.HOTEL_CALL_QUESTIONS["hinglish"]),
            window_start=leg.starts_at,
            call_mode=CallMode.AGENT,
            call_language=Language.HINGLISH,
            notes="Proposed by the trip timeline; approved by the user.",
        )
        task.task_id = await self.tasks.create_task(user_id, spec, approved=False)
        task.state = TaskState.RUNNING
        await self.store.save_task(task)
        return TripReply(prefix(trip, t("hotel_call.queued", self.lang)), trip_id=trip.id)

    async def provide_hotel_number(self, user_id: str, trip_id: str, number: str) -> TripReply:
        self._need(user_id)
        phone = _clean_phone(number)
        trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        if phone is None:
            return TripReply(prefix(trip, t("hotel_call.bad_number", self.lang)), trip_id=trip_id)
        waiting = [
            x
            for x in await self.store.list_tasks(user_id, trip_id)
            if x.kind == TaskKind.HOTEL_CALL and x.state == TaskState.NEEDS_NUMBER
        ]
        if not waiting:
            return TripReply(t("task.unknown", self.lang))
        task = waiting[0]
        legs = await self.store.list_legs(user_id, trip_id)
        leg = next(x for x in legs if x.id == task.leg_id)
        leg.phone = phone
        await self.store.save_leg(leg)
        if task.params.get("approved"):
            return await self.approve_task(user_id, task.id)
        task.state = TaskState.NUDGED  # asked for the number first: now ask for the go-ahead
        await self.store.save_task(task)
        return TripReply(self._hotel_text(trip, leg), self._hotel_buttons(trip, task), trip_id)

    async def mark_engine_task_finished(
        self, user_id: str, engine_task_id: str, *, evidence_ids: list[str] | None = None
    ) -> bool:
        task = await self.store.find_task_by_engine_id(user_id, engine_task_id)
        if task is None:
            return False
        task.state = TaskState.DONE
        task.evidence_ids = list(evidence_ids or task.evidence_ids)
        await self.store.save_task(task)
        return True

    # ------------------------------------------------------------------ text views
    async def plan_text(self, user_id: str, trip_id: str | None = None) -> TripReply:
        """The per-trip timeline message ("your day-wise plan"); also the pinned thread card."""
        self._need(user_id)
        trip = await self._trip_for(user_id, trip_id)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        legs = await self.store.list_legs(user_id, trip.id)
        return TripReply(render_plan(trip, legs, self.cfg, self.lang), trip_id=trip.id)

    async def leave_text(self, user_id: str) -> TripReply:
        self._need(user_id)
        trip = await self._trip_for(user_id, None)
        if trip is None:
            return TripReply(t("no_trip", self.lang))
        now = self.clock.now()
        legs = [
            x
            for x in await self.store.list_legs(user_id, trip.id)
            if x.kind in (LegKind.FLIGHT, LegKind.TRAIN)
            and x.status == "active"
            and x.starts_at > now
        ]
        if not legs:
            return TripReply(t("no_trip", self.lang), trip_id=trip.id)
        leg = legs[0]
        w = await self.store.get_watch(user_id, leg.id)
        lb = leave_by(
            leg, trip, self.cfg, leg.starts_at + timedelta(minutes=w.delay_minutes if w else 0)
        )
        return TripReply(prefix(trip, self._leave_text(lb, leg)), trip_id=trip.id)

    async def timeline_message(self, user_id: str, trip_id: str) -> TripMessage | None:
        r = await self.plan_text(user_id, trip_id)
        return TripMessage(
            r.text, [Button(f"trip:{trip_id}:plan", "Plan")], trip_id, f"plan:{trip_id}"
        )

    # ------------------------------------------------------------------ message builders
    def _leave_text(self, lb: Any, leg: TripLeg) -> str:
        assume = (
            t("nudge.leave_by.assume", self.lang, mins=lb.travel_minutes)
            if lb.travel_assumed
            else ""
        )
        return t(
            "nudge.leave_by",
            self.lang,
            time=fmt_time(lb.leave_at, leg.tz),
            mode="train" if leg.kind == LegKind.TRAIN else "flight",
            dep=fmt_time(lb.depart_at, leg.tz),
            assume=assume,
            buf=lb.buffer_minutes,
            travel=lb.travel_minutes,
            stop=copy.stop_hint(self.lang),
        )

    def _hotel_text(self, trip: Trip, leg: TripLeg) -> str:
        if leg.time_known:
            when = f"{fmt_day(leg.starts_at, leg.tz)} {fmt_time(leg.starts_at, leg.tz)}"
        else:
            when = (
                f"{fmt_day(leg.starts_at, leg.tz)} (time pata nahi)"
                if self.lang == "hinglish"
                else f"{fmt_day(leg.starts_at, leg.tz)} (time unknown)"
            )
        return prefix(
            trip,
            t(
                "nudge.hotel_call",
                self.lang,
                hotel=leg.label or "hotel",
                when=when,
                stop=copy.stop_hint(self.lang),
            ),
        )

    def _hotel_buttons(self, trip: Trip, task: TripTask) -> list[Button]:
        return [
            Button(f"trip:{trip.id}:ok:{task.id}", t("btn.yes", self.lang)),
            Button(f"trip:{trip.id}:no:{task.id}", t("btn.no", self.lang)),
        ]

    async def _message_for(
        self,
        user_id: str,
        trip: Trip,
        task: TripTask,
        leg: TripLeg | None,
        legs: list[TripLeg],
        now: datetime,
    ) -> tuple[TripMessage | None, TaskState, str]:
        """(message, state after sending, topic). message None = nothing to say."""
        stop, lang = copy.stop_hint(self.lang), self.lang
        k = task.kind
        if k == TaskKind.LEAVE_BY and leg:
            w = await self.store.get_watch(user_id, leg.id)
            lb = leave_by(
                leg, trip, self.cfg, leg.starts_at + timedelta(minutes=w.delay_minutes if w else 0)
            )
            return (
                TripMessage(prefix(trip, self._leave_text(lb, leg)), trip_id=trip.id),
                TaskState.DONE,
                TOPIC,
            )
        if k == TaskKind.HOTEL_CALL and leg:
            if not leg.phone:
                return (
                    TripMessage(
                        prefix(trip, t("nudge.hotel_call.nonumber", lang)), trip_id=trip.id
                    ),
                    TaskState.NEEDS_NUMBER,
                    TOPIC,
                )
            return (
                TripMessage(self._hotel_text(trip, leg), self._hotel_buttons(trip, task), trip.id),
                TaskState.NUDGED,
                TOPIC,
            )
        if k == TaskKind.CAB and leg:
            pickup_at = leg.starts_at  # replaced below from params
            raw = task.params.get("pickup_at")
            pickup_at = datetime.fromisoformat(raw) if raw else pickup_at
            tm = fmt_time(pickup_at, leg.tz)
            if not trip.pickup_address:
                return (
                    TripMessage(
                        prefix(trip, t("nudge.cab.noaddr", lang, time=tm, stop=stop)),
                        trip_id=trip.id,
                    ),
                    TaskState.NUDGED,
                    TOPIC,
                )
            link = ride_link(trip.pickup_address, leg.origin)
            return (
                TripMessage(
                    prefix(
                        trip,
                        t(
                            "nudge.cab",
                            lang,
                            time=tm,
                            place=trip.pickup_address,
                            link=link,
                            stop=stop,
                        ),
                    ),
                    trip_id=trip.id,
                ),
                TaskState.DONE,
                TOPIC,
            )
        if k == TaskKind.CHECKIN and leg:
            name = leg.label or "hotel"
            if leg.time_known:
                return (
                    TripMessage(
                        prefix(
                            trip,
                            t(
                                "nudge.checkin",
                                lang,
                                hotel=name,
                                time=fmt_time(leg.starts_at, leg.tz),
                                stop=stop,
                            ),
                        ),
                        trip_id=trip.id,
                    ),
                    TaskState.DONE,
                    TOPIC,
                )
            return (
                TripMessage(
                    prefix(trip, t("nudge.checkin.unknown", lang, hotel=name, stop=stop)),
                    trip_id=trip.id,
                ),
                TaskState.DONE,
                TOPIC,
            )
        if k == TaskKind.CHECKOUT and leg and leg.ends_at:
            name, tz = leg.label or "hotel", leg.end_tz or leg.tz
            key = (
                "nudge.checkout"
                if task.params.get("time_known", True)
                else "nudge.checkout.unknown"
            )
            return (
                TripMessage(
                    prefix(
                        trip, t(key, lang, hotel=name, time=fmt_time(leg.ends_at, tz), stop=stop)
                    ),
                    trip_id=trip.id,
                ),
                TaskState.DONE,
                TOPIC,
            )
        if k == TaskKind.LOUNGE and leg:
            if not self.cfg.lounge_enabled:
                return None, TaskState.SKIPPED, TOPIC_LOUNGE
            hints = await lounge_hints(user_id, leg, self.wallet, self.perks, ist_date(now))
            if not hints:
                return None, TaskState.SKIPPED, TOPIC_LOUNGE  # no verified rule: say nothing
            h = hints[0]
            conf = (
                ""
                if h.confidence == "high"
                else t(f"lounge.conf.{h.confidence}", lang)
                if h.confidence in ("medium", "low")
                else ""
            )
            text = t(
                "nudge.lounge",
                lang,
                card=h.card_display,
                airport=h.airport or "airport",
                checked=str(h.perk.checked_on),
                conf=conf,
                dep=fmt_time(leg.starts_at, leg.tz),
                stop=stop,
            )
            return TripMessage(prefix(trip, text), trip_id=trip.id), TaskState.DONE, TOPIC_LOUNGE
        if k == TaskKind.DAY_PLAN:
            d = date.fromisoformat(task.params["date"])
            tz = task.params.get("tz", "Asia/Kolkata")
            lines = [
                self._item_text(i)
                for i in timeline_items(trip, legs, self.cfg)
                if local(i.at, i.tz).date() == d
            ]
            if not lines:
                return None, TaskState.SKIPPED, TOPIC
            return (
                TripMessage(
                    prefix(
                        trip, t("nudge.day_plan", lang, lines="; ".join(lines) + ".", stop=stop)
                    ),
                    trip_id=trip.id,
                ),
                TaskState.DONE,
                TOPIC,
            )
        return None, TaskState.SKIPPED, TOPIC

    def _item_text(self, it: Any) -> str:
        from friday.trips.render import item_line

        return item_line(it, self.lang)

    # ------------------------------------------------------------------ the scheduler
    async def _sent_today(self, user_id: str, now: datetime) -> int:
        start, end = ist_day_bounds(now)
        n = await self.store.count_sent(user_id, start, end)
        if self.extra_sent_today is not None:
            n += await self.extra_sent_today(user_id)
        return n

    async def tick(self) -> dict[str, list[Outcome]]:
        out: dict[str, list[Outcome]] = {}
        for uid in await self.store.users_with_active_trips():
            if self.enabled_for(uid):
                out[uid] = await self.run_user(uid)
        return out

    async def run_user(self, user_id: str) -> list[Outcome]:
        self._need(user_id)
        now = self.clock.now()
        outcomes: list[Outcome] = []
        for trip in await self.store.list_trips(user_id, (TripStatus.ACTIVE,)):
            if trip.end_date + timedelta(days=1) < ist_date(now):
                trip.status = TripStatus.DONE
                await self.store.save_trip(trip)
                continue
            legs = await self.store.list_legs(user_id, trip.id)
            by_id = {x.id: x for x in legs}
            outcomes += await self._poll_status(user_id, trip, legs, now)
            tasks = [
                x
                for x in await self.store.list_tasks(user_id, trip.id)
                if x.state in (TaskState.PLANNED,)
                and x.due_at <= now
                and x.kind != TaskKind.FLIGHT_WATCH
            ]
            for task in sorted(tasks, key=lambda x: x.due_at):
                res = await self._consider(
                    user_id, trip, task, by_id.get(task.leg_id or ""), legs, now
                )
                if res:
                    outcomes.append(res)
        return outcomes

    async def _consider(
        self,
        user_id: str,
        trip: Trip,
        task: TripTask,
        leg: TripLeg | None,
        legs: list[TripLeg],
        now: datetime,
    ) -> Outcome | None:
        key = (
            task.dedupe_key
            if task.kind != TaskKind.LEAVE_BY
            else f"{task.dedupe_key}:{int(task.due_at.timestamp())}"
        )
        if now >= task.expires_at:
            task.state = TaskState.SKIPPED
            await self.store.save_task(task)
            return Outcome(key, task.kind.value, "expired", reason="stale")
        if trip.muted:
            return Outcome(key, task.kind.value, "muted", reason="trip muted by the user")
        if await self.store.has_nudge(user_id, key):
            return None
        msg, after, topic = await self._message_for(user_id, trip, task, leg, legs, now)
        if msg is None:
            task.state = after
            await self.store.save_task(task)
            return Outcome(key, task.kind.value, "skipped", reason="nothing to say")
        critical = bool(task.params.get("critical"))
        tz = task.params.get("tz", leg.tz if leg else "Asia/Kolkata")
        quiet = _in_quiet(now, tz, self.cfg.quiet_start, self.cfg.quiet_end)
        if quiet and not (critical and self.cfg.critical_bypasses_quiet_hours):
            return Outcome(key, task.kind.value, "held_quiet", reason="quiet hours")
        if not critical and await self._sent_today(user_id, now) >= self.cfg.daily_cap:
            return Outcome(key, task.kind.value, "held_cap", reason="daily cap reached")
        msg.dedupe_key = key
        return await self._deliver(user_id, trip, key, topic, msg, task, after)

    async def _deliver(
        self,
        user_id: str,
        trip: Trip,
        key: str,
        topic: str,
        msg: TripMessage,
        task: TripTask | None,
        after: TaskState,
    ) -> Outcome:
        kind = task.kind.value if task else "flight_watch"
        if self.sender is None or not await self.sender.send(user_id, msg):
            return Outcome(key, kind, "failed", text=msg.text, reason="sender refused")
        await self.store.add_nudge(
            TripNudge(
                user_id=user_id,
                trip_id=trip.id,
                key=key,
                topic=topic,
                text=msg.text,
                sent_at=self.clock.now(),
            )
        )
        if task is not None:
            task.state = after
            await self.store.save_task(task)
        return Outcome(key, kind, "sent", text=msg.text)

    # ------------------------------------------------------------------ flight / train watch
    async def _poll_status(
        self, user_id: str, trip: Trip, legs: list[TripLeg], now: datetime
    ) -> list[Outcome]:
        if not self.cfg.watch_enabled or self.status is None:
            return []
        out: list[Outcome] = []
        tasks = {
            x.leg_id: x
            for x in await self.store.list_tasks(user_id, trip.id)
            if x.kind == TaskKind.FLIGHT_WATCH
        }
        for leg in legs:
            wt = tasks.get(leg.id)
            if wt is None or leg.status != "active" or not (wt.due_at <= now < wt.expires_at):
                continue
            w = await self.store.get_watch(user_id, leg.id) or FlightWatch(
                leg_id=leg.id, user_id=user_id, trip_id=trip.id
            )
            if w.next_check_at is not None and w.next_check_at > now:
                continue
            q = StatusQuery(
                leg.kind.value,
                leg.number or "",
                local(leg.starts_at, leg.tz).date(),
                leg.origin,
                leg.starts_at,
            )
            try:
                st = await self.status.get_status(q)
            except ProviderUnavailable:
                w.failures += 1
                w.next_check_at = now + timedelta(minutes=self.cfg.watch_backoff_min)
                await self.store.save_watch(w)
                out.append(
                    Outcome(
                        f"watch:{leg.id}", "flight_watch", "watched", reason="provider unavailable"
                    )
                )
                continue
            changes = detect_changes(
                leg,
                w.delay_minutes,
                w.info,
                w.last_status,
                status=st.status,
                estimated_dep=st.estimated_dep,
                gate=st.gate,
                terminal=st.terminal,
                cfg=self.cfg,
            )
            age_min = int((now - st.fetched_at).total_seconds() // 60)
            age = (
                t("age.stale", self.lang, mins=age_min)
                if age_min > self.cfg.stale_status_min
                else ""
            )
            old_delay, prev = w.delay_minutes, w.model_copy(deep=True)
            w.failures, w.last_checked_at, w.last_status = 0, now, st.status
            for c in changes:
                if c.kind in ("delay", "back_on_time"):
                    w.delay_minutes = c.delay_minutes
            if st.gate:
                w.info["gate"] = st.gate
            if st.terminal:
                w.info["terminal"] = st.terminal
            depart = leg.starts_at + timedelta(minutes=w.delay_minutes)
            w.next_check_at = next_check_at(now, depart, self.cfg)
            w.changed_notified = bool(changes)
            await self.store.save_watch(w)
            if not changes:
                continue
            if w.delay_minutes != old_delay:
                await self.refresh(user_id, trip.id)
            res = await self._status_message(user_id, trip, leg, w, changes, age, now)
            if res.action in ("held_quiet", "held_cap", "failed"):
                # not told yet: forget the change so the next look reports it again
                prev.last_checked_at = now
                prev.next_check_at = now + timedelta(minutes=15)
                await self.store.save_watch(prev)
            out.append(res)
        return out

    async def _propose_refund(self, user_id: str, leg: TripLeg) -> None:
        """A cancelled leg: ask the refund tracker to PROPOSE a case (the user confirms; nothing
        is requested from anyone). A refund-tracker failure never breaks the trip flow."""
        if self.refunds is None:
            return
        vendor = re.sub(r"\b[A-Za-z0-9]{1,3}\s?\d{1,4}\b", "", leg.label or "")  # drop "EX 101"
        vendor = " ".join(vendor.split())
        try:
            await self.refunds.propose_from_trip_cancellation(
                user_id, leg.id, vendor or leg.kind.value
            )
        except Exception:  # noqa: BLE001
            log.warning("refund proposal from a trip cancellation failed", exc_info=True)

    async def _status_message(
        self,
        user_id: str,
        trip: Trip,
        leg: TripLeg,
        w: FlightWatch,
        changes: list[Any],
        age: str,
        now: datetime,
    ) -> Outcome:
        first = next(
            (c for c in changes if c.kind in ("cancelled", "delay", "back_on_time")), changes[0]
        )
        flight = leg.label or leg.number or "flight"
        stop, lang = copy.stop_hint(self.lang), self.lang
        lb = leave_by(leg, trip, self.cfg, leg.starts_at + timedelta(minutes=w.delay_minutes))
        leave = fmt_time(lb.leave_at, leg.tz)
        if first.kind == "cancelled":
            text = t("watch.cancelled", lang, flight=flight, age=age, stop=stop)
        elif first.kind == "delay":
            text = t(
                "watch.delay",
                lang,
                flight=flight,
                mins=first.delay_minutes,
                age=age,
                stop=stop,
                new_dep=fmt_time(leg.starts_at + timedelta(minutes=w.delay_minutes), leg.tz),
                old_dep=fmt_time(leg.starts_at, leg.tz),
                leave=leave,
            )
        elif first.kind == "back_on_time":
            text = t(
                "watch.back",
                lang,
                flight=flight,
                dep=fmt_time(leg.starts_at, leg.tz),
                leave=leave,
                age=age,
                stop=stop,
            )
        elif first.kind == "gate":
            text = t("watch.gate", lang, flight=flight, gate=first.gate or "", age=age, stop=stop)
        else:
            text = t(
                "watch.terminal",
                lang,
                flight=flight,
                terminal=first.terminal or "",
                age=age,
                stop=stop,
            )
        critical = first.kind in ("cancelled", "delay", "back_on_time")
        if first.kind == "cancelled":
            await self._propose_refund(user_id, leg)
        key = f"watch:{leg.id}:{first.kind}:{w.delay_minutes}:{w.info.get('gate')}:{w.info.get('terminal')}"
        if trip.muted:
            return Outcome(key, "flight_watch", "muted")
        if await self.store.has_nudge(user_id, key):
            return Outcome(key, "flight_watch", "skipped", reason="already told")
        tz = leg.tz
        if _in_quiet(now, tz, self.cfg.quiet_start, self.cfg.quiet_end) and not (
            critical and self.cfg.critical_bypasses_quiet_hours
        ):
            return Outcome(key, "flight_watch", "held_quiet", reason="quiet hours")
        if not critical and await self._sent_today(user_id, now) >= self.cfg.daily_cap:
            return Outcome(key, "flight_watch", "held_cap", reason="daily cap reached")
        return await self._deliver(
            user_id,
            trip,
            key,
            TOPIC_FLIGHT,
            TripMessage(prefix(trip, text), trip_id=trip.id, dedupe_key=key),
            None,
            TaskState.DONE,
        )
