"""In-memory trip store (tests, simulator). Same surface as ``db.repositories.trips.TripRepo``.
Every method takes the ``user_id`` and filters by it."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from friday.trips.models import (
    FlightWatch,
    Trip,
    TripLeg,
    TripNudge,
    TripStatus,
    TripTask,
)
from friday.trips.perks import CardPerk, PerkSource, load_perks


def _cp(x):  # noqa: ANN001, ANN202
    return x.model_copy(deep=True)


class MemoryTripStore:
    def __init__(self) -> None:
        self.trips: dict[str, Trip] = {}
        self.legs: dict[str, TripLeg] = {}
        self.tasks: dict[str, TripTask] = {}
        self.watches: dict[str, FlightWatch] = {}
        self.nudges: dict[tuple[str, str], TripNudge] = {}

    # ------------------------------------------------------------------ trips
    async def save_trip(self, trip: Trip) -> None:
        old = self.trips.get(trip.id)
        if old is not None and old.user_id != trip.user_id:
            raise PermissionError("trip belongs to another user")
        self.trips[trip.id] = _cp(trip)

    async def get_trip(self, user_id: str, trip_id: str) -> Trip | None:
        t = self.trips.get(trip_id)
        return _cp(t) if t and t.user_id == user_id else None

    async def list_trips(
        self, user_id: str, statuses: tuple[TripStatus, ...] | None = None
    ) -> list[Trip]:
        rows = [
            t
            for t in self.trips.values()
            if t.user_id == user_id and (statuses is None or t.status in statuses)
        ]
        return [_cp(t) for t in sorted(rows, key=lambda t: (t.start_date, t.created_at))]

    async def delete_trip(self, user_id: str, trip_id: str) -> bool:
        t = self.trips.get(trip_id)
        if t is None or t.user_id != user_id:
            return False
        self._drop(trip_id)
        return True

    def _drop(self, trip_id: str) -> None:
        self.trips.pop(trip_id, None)
        for d in (self.legs, self.tasks):
            for k in [k for k, v in d.items() if v.trip_id == trip_id]:
                del d[k]
        for k in [k for k, v in self.watches.items() if v.trip_id == trip_id]:
            del self.watches[k]
        for k in [k for k, v in self.nudges.items() if v.trip_id == trip_id]:
            del self.nudges[k]

    async def users_with_active_trips(self) -> list[str]:
        return sorted({t.user_id for t in self.trips.values() if t.status == TripStatus.ACTIVE})

    # ------------------------------------------------------------------ legs
    async def save_leg(self, leg: TripLeg) -> None:
        old = self.legs.get(leg.id)
        if old is not None and old.user_id != leg.user_id:
            raise PermissionError("leg belongs to another user")
        self.legs[leg.id] = _cp(leg)

    async def list_legs(self, user_id: str, trip_id: str) -> list[TripLeg]:
        rows = [l for l in self.legs.values() if l.user_id == user_id and l.trip_id == trip_id]  # noqa: E741
        return [_cp(x) for x in sorted(rows, key=lambda x: x.starts_at)]

    async def find_leg(self, user_id: str, dedupe_key: str) -> TripLeg | None:
        for leg in self.legs.values():
            if leg.user_id == user_id and leg.dedupe_key == dedupe_key:
                return _cp(leg)
        return None

    # ------------------------------------------------------------------ tasks
    async def save_task(self, task: TripTask) -> None:
        old = self.tasks.get(task.id)
        if old is not None and old.user_id != task.user_id:
            raise PermissionError("task belongs to another user")
        self.tasks[task.id] = _cp(task)

    async def list_tasks(self, user_id: str, trip_id: str) -> list[TripTask]:
        rows = [t for t in self.tasks.values() if t.user_id == user_id and t.trip_id == trip_id]
        return [_cp(t) for t in sorted(rows, key=lambda t: (t.due_at, t.kind.value))]

    async def get_task(self, user_id: str, task_id: str) -> TripTask | None:
        t = self.tasks.get(task_id)
        return _cp(t) if t and t.user_id == user_id else None

    async def find_task(self, user_id: str, dedupe_key: str) -> TripTask | None:
        for t in self.tasks.values():
            if t.user_id == user_id and t.dedupe_key == dedupe_key:
                return _cp(t)
        return None

    async def find_task_by_engine_id(self, user_id: str, engine_task_id: str) -> TripTask | None:
        for t in self.tasks.values():
            if t.user_id == user_id and t.task_id == engine_task_id:
                return _cp(t)
        return None

    # ------------------------------------------------------------------ flight watch
    async def get_watch(self, user_id: str, leg_id: str) -> FlightWatch | None:
        w = self.watches.get(leg_id)
        return _cp(w) if w and w.user_id == user_id else None

    async def save_watch(self, watch: FlightWatch) -> None:
        old = self.watches.get(watch.leg_id)
        if old is not None and old.user_id != watch.user_id:
            raise PermissionError("watch belongs to another user")
        self.watches[watch.leg_id] = _cp(watch)

    # ------------------------------------------------------------------ nudges
    async def add_nudge(self, nudge: TripNudge) -> bool:
        """False if this key was already recorded for the user (never twice)."""
        k = (nudge.user_id, nudge.key)
        if k in self.nudges:
            return False
        self.nudges[k] = _cp(nudge)
        return True

    async def has_nudge(self, user_id: str, key: str) -> bool:
        return (user_id, key) in self.nudges

    async def count_sent(self, user_id: str, start: datetime, end: datetime) -> int:
        return sum(
            1
            for n in self.nudges.values()
            if n.user_id == user_id and n.status == "sent" and start <= n.sent_at < end
        )

    async def list_nudges(self, user_id: str, trip_id: str) -> list[TripNudge]:
        rows = [n for n in self.nudges.values() if n.user_id == user_id and n.trip_id == trip_id]
        return [_cp(n) for n in sorted(rows, key=lambda n: n.sent_at)]

    async def last_sent(self, user_id: str, topic: str) -> TripNudge | None:
        rows = [
            n
            for n in self.nudges.values()
            if n.user_id == user_id and n.topic == topic and n.status == "sent"
        ]
        return _cp(max(rows, key=lambda n: n.sent_at)) if rows else None

    # ------------------------------------------------------------------ retention
    async def expire(self, today: date, retention_days: int) -> int:
        """Delete trips that ended more than ``retention_days`` ago (with everything under them)."""
        cutoff = today - timedelta(days=retention_days)
        gone = [t.id for t in self.trips.values() if t.end_date < cutoff]
        for tid in gone:
            self._drop(tid)
        return len(gone)

    async def purge_user(self, user_id: str) -> int:
        ids = [t.id for t in self.trips.values() if t.user_id == user_id]
        for tid in ids:
            self._drop(tid)
        return len(ids)


class MemoryPerkStore(PerkSource):
    """Shared perks table in memory. ``served_perks`` is what the lounge hint reads."""

    def __init__(
        self, perks: list[CardPerk] | None = None, *, allow_examples: bool = False
    ) -> None:
        self.perks: dict[tuple[str, str], CardPerk] = {}
        self.allow_examples = allow_examples
        for p in perks or []:
            self.perks[p.ident] = _cp(p)

    async def all(self) -> list[CardPerk]:
        return [_cp(p) for p in self.perks.values()]

    async def upsert(self, perk: CardPerk) -> bool:
        new = perk.ident not in self.perks
        self.perks[perk.ident] = _cp(perk)
        return new

    async def served_perks(self, today: date) -> list[CardPerk]:
        return load_perks(await self.all(), today, allow_examples=self.allow_examples).accepted
