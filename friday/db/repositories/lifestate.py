"""Life state storage (tables in friday/lifestate/dbmodel.py).

Every method takes ``user_id`` and filters by it: one user's rows are never reachable through
another user's id. Personal text is encrypted by the column types.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select

from friday.db.repositories._base import Repo
from friday.lifestate.dbmodel import (
    LifeCommitmentRow,
    LifeEventRow,
    LifeFollowupRow,
    MuteTopicRow,
)
from friday.lifestate.models import (
    Followup,
    LifeCommitment,
    LifeEvent,
    PersonRef,
    Repeat,
    TopicPref,
)


def _event(r: LifeEventRow) -> LifeEvent:
    return LifeEvent(
        id=r.id,
        user_id=r.user_id,
        title=r.title,
        start=r.start_at,
        end=r.end_at,
        kind=r.kind,
        source=r.source,
        source_ref=r.source_ref,
        location=r.location,
        protected=r.protected,
        status=r.status,
        note=r.note,
        repeat=Repeat.model_validate(r.repeat) if r.repeat else None,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _commitment(r: LifeCommitmentRow) -> LifeCommitment:
    return LifeCommitment(
        id=r.id,
        user_id=r.user_id,
        text=r.text,
        due=r.due_at,
        source=r.source,
        status=r.status,
        repeat=Repeat.model_validate(r.repeat) if r.repeat else None,
        person=PersonRef.model_validate(r.person) if r.person else None,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _followup(r: LifeFollowupRow) -> Followup:
    return Followup(
        id=r.id,
        user_id=r.user_id,
        key=r.key,
        topic=r.topic,
        event_id=r.event_id,
        status=r.status,
        text=r.text,
        due_at=r.due_at,
        sent_at=r.sent_at,
        responded_at=r.responded_at,
        created_at=r.created_at,
    )


class LifeRepo(Repo):
    """Implements ``friday.lifestate.store.LifeStore``."""

    # ------------------------------------------------------------------ events
    async def save_event(self, e: LifeEvent) -> LifeEvent:
        async with self.db.session() as s:
            row = await s.get(LifeEventRow, e.id)
            if row is not None and row.user_id != e.user_id:
                raise PermissionError("event belongs to another user")
            if row is None:
                row = LifeEventRow(id=e.id, user_id=e.user_id, created_at=e.created_at)
                s.add(row)
            row.title, row.start_at, row.end_at = e.title, e.start, e.end
            row.kind, row.source, row.source_ref = e.kind.value, e.source.value, e.source_ref
            row.location, row.protected, row.status = e.location, e.protected, e.status.value
            row.note = e.note
            row.repeat = e.repeat.model_dump() if e.repeat else None
            row.updated_at = self.now()
        return e

    async def get_event(self, user_id: str, event_id: str) -> LifeEvent | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(LifeEventRow).where(
                        LifeEventRow.id == event_id, LifeEventRow.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            return _event(row) if row else None

    async def find_event_by_ref(
        self, user_id: str, source: str, source_ref: str
    ) -> LifeEvent | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(LifeEventRow).where(
                        LifeEventRow.user_id == user_id,
                        LifeEventRow.source == source,
                        LifeEventRow.source_ref == source_ref,
                    )
                )
            ).scalar_one_or_none()
            return _event(row) if row else None

    async def events_between(
        self, user_id: str, start: datetime, end: datetime, *, include_inactive: bool = False
    ) -> list[LifeEvent]:
        async with self.db.session() as s:
            q = select(LifeEventRow).where(
                LifeEventRow.user_id == user_id,
                LifeEventRow.start_at < end,
                LifeEventRow.end_at >= start,
            )
            if not include_inactive:
                q = q.where(LifeEventRow.status == "active")
            rows = (await s.execute(q.order_by(LifeEventRow.start_at))).scalars().all()
        return [e for e in map(_event, rows) if e.overlaps(start, end)]

    async def list_events(self, user_id: str, *, include_inactive: bool = True) -> list[LifeEvent]:
        async with self.db.session() as s:
            q = select(LifeEventRow).where(LifeEventRow.user_id == user_id)
            if not include_inactive:
                q = q.where(LifeEventRow.status == "active")
            rows = (await s.execute(q.order_by(LifeEventRow.start_at))).scalars().all()
        return [_event(r) for r in rows]

    async def delete_event(self, user_id: str, event_id: str) -> bool:
        async with self.db.session() as s:
            res = await s.execute(
                delete(LifeEventRow).where(
                    LifeEventRow.id == event_id, LifeEventRow.user_id == user_id
                )
            )
            return bool(res.rowcount)

    # ------------------------------------------------------------------ commitments
    async def save_commitment(self, c: LifeCommitment) -> LifeCommitment:
        async with self.db.session() as s:
            row = await s.get(LifeCommitmentRow, c.id)
            if row is not None and row.user_id != c.user_id:
                raise PermissionError("commitment belongs to another user")
            if row is None:
                row = LifeCommitmentRow(id=c.id, user_id=c.user_id, created_at=c.created_at)
                s.add(row)
            row.text, row.due_at = c.text, c.due
            row.source, row.status = c.source.value, c.status.value
            row.repeat = c.repeat.model_dump() if c.repeat else None
            row.person = c.person.model_dump() if c.person else None
            row.updated_at = self.now()
        return c

    async def get_commitment(self, user_id: str, commitment_id: str) -> LifeCommitment | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(LifeCommitmentRow).where(
                        LifeCommitmentRow.id == commitment_id,
                        LifeCommitmentRow.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return _commitment(row) if row else None

    async def list_commitments(
        self, user_id: str, *, status: str | None = None
    ) -> list[LifeCommitment]:
        async with self.db.session() as s:
            q = select(LifeCommitmentRow).where(LifeCommitmentRow.user_id == user_id)
            if status:
                q = q.where(LifeCommitmentRow.status == status)
            rows = (await s.execute(q.order_by(LifeCommitmentRow.due_at))).scalars().all()
        return [_commitment(r) for r in rows]

    async def delete_commitment(self, user_id: str, commitment_id: str) -> bool:
        async with self.db.session() as s:
            res = await s.execute(
                delete(LifeCommitmentRow).where(
                    LifeCommitmentRow.id == commitment_id, LifeCommitmentRow.user_id == user_id
                )
            )
            return bool(res.rowcount)

    # ------------------------------------------------------------------ topic prefs
    async def set_topic(
        self, user_id: str, topic: str, *, muted: bool | None = None, channel: str | None = None
    ) -> TopicPref:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(MuteTopicRow).where(
                        MuteTopicRow.user_id == user_id, MuteTopicRow.topic == topic
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = MuteTopicRow(user_id=user_id, topic=topic, muted=False, channel="text")
                s.add(row)
            if muted is not None:
                row.muted = muted
            if channel is not None:
                row.channel = channel
            row.updated_at = self.now()
            pref = TopicPref(topic=row.topic, muted=row.muted, channel=row.channel)
        return pref

    async def list_topics(self, user_id: str) -> list[TopicPref]:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(MuteTopicRow).where(MuteTopicRow.user_id == user_id))
            ).scalars()
            return [TopicPref(topic=r.topic, muted=r.muted, channel=r.channel) for r in rows]

    # ------------------------------------------------------------------ follow-up log
    async def get_followup(self, user_id: str, key: str) -> Followup | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(LifeFollowupRow).where(
                        LifeFollowupRow.user_id == user_id, LifeFollowupRow.key == key
                    )
                )
            ).scalar_one_or_none()
            return _followup(row) if row else None

    async def save_followup(self, f: Followup) -> Followup:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(LifeFollowupRow).where(
                        LifeFollowupRow.user_id == f.user_id, LifeFollowupRow.key == f.key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = LifeFollowupRow(id=f.id, user_id=f.user_id, key=f.key)
                s.add(row)
            row.topic, row.event_id, row.status, row.text = f.topic, f.event_id, f.status, f.text
            row.due_at, row.sent_at, row.responded_at = f.due_at, f.sent_at, f.responded_at
            row.created_at = f.created_at
        return f

    async def list_followups(
        self, user_id: str, *, since: datetime | None = None
    ) -> list[Followup]:
        async with self.db.session() as s:
            q = select(LifeFollowupRow).where(LifeFollowupRow.user_id == user_id)
            if since is not None:
                q = q.where(LifeFollowupRow.created_at >= since)
            rows = (await s.execute(q.order_by(LifeFollowupRow.created_at))).scalars().all()
        return [_followup(r) for r in rows]

    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(LifeFollowupRow)
                        .where(
                            LifeFollowupRow.user_id == user_id,
                            LifeFollowupRow.status == "sent",
                            LifeFollowupRow.topic != "morning_brief",
                            LifeFollowupRow.sent_at >= start,
                            LifeFollowupRow.sent_at < end,
                        )
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ erase
    async def delete_all(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self.db.session() as s:
            for table in (LifeFollowupRow, MuteTopicRow, LifeCommitmentRow, LifeEventRow):
                res = await s.execute(delete(table).where(table.user_id == user_id))
                counts[table.__tablename__] = int(res.rowcount or 0)
        return counts
