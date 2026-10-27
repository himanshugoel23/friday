"""Trip storage (tables in friday/trips/dbmodel.py). Every per-user method takes the ``user_id`` and
filters by it: one user's trips are never reachable through another user's id. Same surface as
``friday.trips.store.MemoryTripStore``."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select

from friday.core.crypto import get_field_cipher
from friday.db.repositories._base import Repo
from friday.trips.dbmodel import (
    CardPerkRow,
    FlightWatchRow,
    TripLegRow,
    TripNudgeRow,
    TripRow,
    TripTaskRow,
)
from friday.trips.models import (
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
from friday.trips.perks import CardPerk, PerkKind, PerkSource, load_perks

_LEG_DATA = ("label", "number", "phone", "address", "terminal", "assumptions", "dedupe_key")


def _blind(value: str) -> str:
    return get_field_cipher().blind_index(value, label="trip_leg")


def _trip(r: TripRow) -> Trip:
    return Trip(
        id=r.id,
        user_id=r.user_id,
        title=r.title,
        start_date=r.start_date,
        end_date=r.end_date,
        status=TripStatus(r.status),
        created_from=r.created_from,
        travel_minutes=r.travel_minutes,
        pickup_address=r.pickup_address,
        muted=r.muted,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _leg(r: TripLegRow) -> TripLeg:
    d = dict(r.data or {})
    return TripLeg(
        id=r.id,
        user_id=r.user_id,
        trip_id=r.trip_id,
        kind=LegKind(r.kind),
        starts_at=r.starts_at,
        ends_at=r.ends_at,
        tz=r.tz,
        end_tz=r.end_tz,
        origin=r.origin,
        dest=r.dest,
        ref=r.ref,
        label=d.get("label"),
        number=d.get("number"),
        phone=d.get("phone"),
        address=d.get("address"),
        terminal=d.get("terminal"),
        international=r.international,
        time_known=r.time_known,
        assumptions=list(d.get("assumptions") or []),
        document_id=r.document_id,
        pointer_kind=r.pointer_kind,
        dedupe_key=str(d.get("dedupe_key") or ""),
        status=r.status,
        created_at=r.created_at,
    )


def _task(r: TripTaskRow) -> TripTask:
    return TripTask(
        id=r.id,
        user_id=r.user_id,
        trip_id=r.trip_id,
        leg_id=r.leg_id,
        kind=TaskKind(r.kind),
        due_at=r.due_at,
        expires_at=r.expires_at,
        state=TaskState(r.state),
        task_id=r.task_id,
        evidence_ids=list(r.evidence_ids or []),
        dedupe_key=r.dedupe_key,
        locked=r.locked,
        params=dict(r.params or {}),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _watch(r: FlightWatchRow) -> FlightWatch:
    return FlightWatch(
        leg_id=r.leg_id,
        user_id=r.user_id,
        trip_id=r.trip_id,
        last_status=r.last_status,
        last_checked_at=r.last_checked_at,
        next_check_at=r.next_check_at,
        delay_minutes=r.delay_minutes,
        changed_notified=r.changed_notified,
        info=dict(r.info or {}),
        failures=r.failures,
    )


def _nudge(r: TripNudgeRow) -> TripNudge:
    return TripNudge(
        id=r.id,
        user_id=r.user_id,
        trip_id=r.trip_id,
        key=r.key,
        topic=r.topic,
        status=r.status,
        text=r.text,
        sent_at=r.sent_at,
    )


class TripRepo(Repo):
    # ------------------------------------------------------------------ trips
    async def save_trip(self, trip: Trip) -> None:
        async with self.db.session() as s:
            row = await s.get(TripRow, trip.id)
            if row is not None and row.user_id != trip.user_id:
                raise PermissionError("trip belongs to another user")
            if row is None:
                row = TripRow(id=trip.id, user_id=trip.user_id, created_at=trip.created_at)
                s.add(row)
            row.title, row.start_date, row.end_date = trip.title, trip.start_date, trip.end_date
            row.status, row.created_from = trip.status.value, trip.created_from
            row.travel_minutes, row.pickup_address = trip.travel_minutes, trip.pickup_address
            row.muted, row.updated_at = trip.muted, self.now()

    async def get_trip(self, user_id: str, trip_id: str) -> Trip | None:
        async with self.db.session() as s:
            r = await s.get(TripRow, trip_id)
            return _trip(r) if r is not None and r.user_id == user_id else None

    async def list_trips(
        self, user_id: str, statuses: tuple[TripStatus, ...] | None = None
    ) -> list[Trip]:
        async with self.db.session() as s:
            q = select(TripRow).where(TripRow.user_id == user_id)
            if statuses is not None:
                q = q.where(TripRow.status.in_([x.value for x in statuses]))
            rows = (await s.execute(q.order_by(TripRow.start_date, TripRow.created_at))).scalars()
            return [_trip(r) for r in rows]

    async def _drop(self, s, trip_ids: list[str]) -> None:  # noqa: ANN001
        if not trip_ids:
            return
        for table in (TripNudgeRow, FlightWatchRow, TripTaskRow, TripLegRow):
            await s.execute(delete(table).where(table.trip_id.in_(trip_ids)))
        await s.execute(delete(TripRow).where(TripRow.id.in_(trip_ids)))

    async def delete_trip(self, user_id: str, trip_id: str) -> bool:
        async with self.db.session() as s:
            r = await s.get(TripRow, trip_id)
            if r is None or r.user_id != user_id:
                return False
            await self._drop(s, [trip_id])
            return True

    async def users_with_active_trips(self) -> list[str]:
        async with self.db.session() as s:
            rows = await s.execute(
                select(TripRow.user_id).where(TripRow.status == TripStatus.ACTIVE.value).distinct()
            )
            return sorted(rows.scalars())

    # ------------------------------------------------------------------ legs
    async def save_leg(self, leg: TripLeg) -> None:
        async with self.db.session() as s:
            row = await s.get(TripLegRow, leg.id)
            if row is not None and row.user_id != leg.user_id:
                raise PermissionError("leg belongs to another user")
            if row is None:
                row = TripLegRow(id=leg.id, user_id=leg.user_id, created_at=leg.created_at)
                s.add(row)
            row.trip_id, row.kind = leg.trip_id, leg.kind.value
            row.starts_at, row.ends_at, row.tz, row.end_tz = (
                leg.starts_at,
                leg.ends_at,
                leg.tz,
                leg.end_tz,
            )
            row.origin, row.dest, row.ref = leg.origin, leg.dest, leg.ref
            row.data = {k: getattr(leg, k) for k in _LEG_DATA}
            row.international, row.time_known = leg.international, leg.time_known
            row.document_id, row.pointer_kind = leg.document_id, leg.pointer_kind
            row.dedupe_hmac, row.status = _blind(leg.dedupe_key), leg.status
            row.updated_at = self.now()

    async def list_legs(self, user_id: str, trip_id: str) -> list[TripLeg]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TripLegRow)
                    .where(TripLegRow.user_id == user_id, TripLegRow.trip_id == trip_id)
                    .order_by(TripLegRow.starts_at)
                )
            ).scalars()
            return [_leg(r) for r in rows]

    async def find_leg(self, user_id: str, dedupe_key: str) -> TripLeg | None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(TripLegRow).where(
                        TripLegRow.user_id == user_id, TripLegRow.dedupe_hmac == _blind(dedupe_key)
                    )
                )
            ).scalar_one_or_none()
            return _leg(r) if r is not None else None

    # ------------------------------------------------------------------ tasks
    async def save_task(self, task: TripTask) -> None:
        async with self.db.session() as s:
            row = await s.get(TripTaskRow, task.id)
            if row is not None and row.user_id != task.user_id:
                raise PermissionError("task belongs to another user")
            if row is None:
                row = TripTaskRow(id=task.id, user_id=task.user_id, created_at=task.created_at)
                s.add(row)
            row.trip_id, row.leg_id, row.kind = task.trip_id, task.leg_id, task.kind.value
            row.due_at, row.expires_at, row.state = task.due_at, task.expires_at, task.state.value
            row.task_id, row.evidence_ids = task.task_id, list(task.evidence_ids)
            row.dedupe_key, row.locked, row.params = task.dedupe_key, task.locked, dict(task.params)
            row.updated_at = self.now()

    async def list_tasks(self, user_id: str, trip_id: str) -> list[TripTask]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TripTaskRow)
                    .where(TripTaskRow.user_id == user_id, TripTaskRow.trip_id == trip_id)
                    .order_by(TripTaskRow.due_at, TripTaskRow.kind)
                )
            ).scalars()
            return [_task(r) for r in rows]

    async def get_task(self, user_id: str, task_id: str) -> TripTask | None:
        async with self.db.session() as s:
            r = await s.get(TripTaskRow, task_id)
            return _task(r) if r is not None and r.user_id == user_id else None

    async def find_task(self, user_id: str, dedupe_key: str) -> TripTask | None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(TripTaskRow).where(
                        TripTaskRow.user_id == user_id, TripTaskRow.dedupe_key == dedupe_key
                    )
                )
            ).scalar_one_or_none()
            return _task(r) if r is not None else None

    async def find_task_by_engine_id(self, user_id: str, engine_task_id: str) -> TripTask | None:
        async with self.db.session() as s:
            r = (
                (
                    await s.execute(
                        select(TripTaskRow).where(
                            TripTaskRow.user_id == user_id, TripTaskRow.task_id == engine_task_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            return _task(r) if r is not None else None

    # ------------------------------------------------------------------ flight watch
    async def get_watch(self, user_id: str, leg_id: str) -> FlightWatch | None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(FlightWatchRow).where(
                        FlightWatchRow.user_id == user_id, FlightWatchRow.leg_id == leg_id
                    )
                )
            ).scalar_one_or_none()
            return _watch(r) if r is not None else None

    async def save_watch(self, watch: FlightWatch) -> None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(FlightWatchRow).where(FlightWatchRow.leg_id == watch.leg_id))
            ).scalar_one_or_none()
            if row is not None and row.user_id != watch.user_id:
                raise PermissionError("watch belongs to another user")
            if row is None:
                row = FlightWatchRow(
                    user_id=watch.user_id, trip_id=watch.trip_id, leg_id=watch.leg_id
                )
                s.add(row)
            row.last_status, row.last_checked_at = watch.last_status, watch.last_checked_at
            row.next_check_at, row.delay_minutes = watch.next_check_at, watch.delay_minutes
            row.changed_notified, row.failures = watch.changed_notified, watch.failures
            row.info, row.updated_at = dict(watch.info), self.now()

    # ------------------------------------------------------------------ nudges
    async def add_nudge(self, nudge: TripNudge) -> bool:
        async with self.db.session() as s:
            exists = (
                await s.execute(
                    select(TripNudgeRow.id).where(
                        TripNudgeRow.user_id == nudge.user_id, TripNudgeRow.key == nudge.key
                    )
                )
            ).first()
            if exists is not None:
                return False
            s.add(
                TripNudgeRow(
                    id=nudge.id,
                    user_id=nudge.user_id,
                    trip_id=nudge.trip_id,
                    key=nudge.key,
                    topic=nudge.topic,
                    status=nudge.status,
                    text=nudge.text,
                    sent_at=nudge.sent_at,
                )
            )
            return True

    async def has_nudge(self, user_id: str, key: str) -> bool:
        async with self.db.session() as s:
            return (
                await s.execute(
                    select(TripNudgeRow.id).where(
                        TripNudgeRow.user_id == user_id, TripNudgeRow.key == key
                    )
                )
            ).first() is not None

    async def count_sent(self, user_id: str, start: datetime, end: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(TripNudgeRow)
                        .where(
                            TripNudgeRow.user_id == user_id,
                            TripNudgeRow.status == "sent",
                            TripNudgeRow.sent_at >= start,
                            TripNudgeRow.sent_at < end,
                        )
                    )
                ).scalar_one()
            )

    async def list_nudges(self, user_id: str, trip_id: str) -> list[TripNudge]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TripNudgeRow)
                    .where(TripNudgeRow.user_id == user_id, TripNudgeRow.trip_id == trip_id)
                    .order_by(TripNudgeRow.sent_at)
                )
            ).scalars()
            return [_nudge(r) for r in rows]

    async def last_sent(self, user_id: str, topic: str) -> TripNudge | None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(TripNudgeRow)
                    .where(
                        TripNudgeRow.user_id == user_id,
                        TripNudgeRow.topic == topic,
                        TripNudgeRow.status == "sent",
                    )
                    .order_by(TripNudgeRow.sent_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _nudge(r) if r is not None else None

    # ------------------------------------------------------------------ retention
    async def expire(self, today: date, retention_days: int) -> int:
        cutoff = today - timedelta(days=retention_days)
        async with self.db.session() as s:
            ids = list(
                (await s.execute(select(TripRow.id).where(TripRow.end_date < cutoff))).scalars()
            )
            await self._drop(s, ids)
            return len(ids)

    async def purge_user(self, user_id: str) -> int:
        async with self.db.session() as s:
            ids = list(
                (await s.execute(select(TripRow.id).where(TripRow.user_id == user_id))).scalars()
            )
            await self._drop(s, ids)
            return len(ids)


# ---------------------------------------------------------------------- shared perks table
def _perk(r: CardPerkRow) -> CardPerk:
    return CardPerk(
        card_key=r.card_key,
        bank=r.bank,
        card_name=r.card_name,
        perk=PerkKind(r.perk),
        visits_per_period=r.visits_per_period,
        period=r.period,
        conditions_text=r.conditions_text,
        min_spend_paise=r.min_spend_paise,
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        source_url=r.source_url,
        checked_on=r.checked_on,
        verified_by=r.verified_by,
        status=r.status,  # type: ignore[arg-type]
    )


class PerkRepo(Repo, PerkSource):
    """The card-perks table. ``served_perks`` is what the lounge hint reads; drafts, examples and
    anything the validator rejects stay out of it."""

    allow_examples: bool = False

    async def all(self) -> list[CardPerk]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CardPerkRow).order_by(CardPerkRow.card_key, CardPerkRow.perk)
                )
            ).scalars()
            return [_perk(r) for r in rows]

    async def upsert(self, perk: CardPerk) -> bool:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(CardPerkRow).where(
                        CardPerkRow.card_key == perk.card_key, CardPerkRow.perk == perk.perk.value
                    )
                )
            ).scalar_one_or_none()
            new = row is None
            if row is None:
                row = CardPerkRow(
                    card_key=perk.card_key, perk=perk.perk.value, created_at=self.now()
                )
                s.add(row)
            row.bank, row.card_name = perk.bank, perk.card_name
            row.visits_per_period, row.period = perk.visits_per_period, perk.period
            row.conditions_text, row.min_spend_paise = perk.conditions_text, perk.min_spend_paise
            row.valid_from, row.valid_to = perk.valid_from, perk.valid_to
            row.source_url, row.checked_on = perk.source_url, perk.checked_on
            row.verified_by, row.status = perk.verified_by, perk.status
            row.updated_at = self.now()
            return new

    async def served_perks(self, today: date) -> list[CardPerk]:
        return load_perks(await self.all(), today, allow_examples=self.allow_examples).accepted
