# ruff: noqa: E501
"""Storage of the Robin family core on the four tables of migration 0019_robin_family.

One ``RobinStore`` over the async ``Database`` (tests run it on SQLite, production on Postgres). Records
(medicines, dose events, check-ins, incidents, audit rows) are one generic table keyed by ``kind``; the
restart-safe operations are compare-and-set on ``status`` (``cas``), the same idea as friday/urgent/store.py:
two replicas ticking together move a row once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from friday.calls.numbers import NumberHasher
from friday.core.clock import Clock, SystemClock
from friday.core.models import new_id
from friday.robin.dbmodel import (
    RobinConsentRow,
    RobinFamilyRow,
    RobinMemberRow,
    RobinRecordRow,
    purge_user_robin,
)
from friday.robin.models import (
    Consent,
    ConsentSource,
    Family,
    FamilySettings,
    FamilyStatus,
    Member,
    Role,
)

KINDS = ("medicine", "dose", "checkin", "incident", "audit", "intro", "pending", "digest")


class Record(BaseModel):
    id: str = Field(default_factory=new_id)
    family_id: str
    user_id: str
    kind: str
    key: str | None = None
    status: str = "open"
    at: datetime
    due_at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _record(r: RobinRecordRow) -> Record:
    return Record(id=r.id, family_id=r.family_id, user_id=r.user_id, kind=r.kind, key=r.key, status=r.status, at=r.at, due_at=r.due_at, data=dict(r.data or {}))


class RobinStore:
    def __init__(self, db, clock: Clock | None = None, hasher: NumberHasher | None = None) -> None:  # noqa: ANN001
        self.db = db
        self.clock = clock or SystemClock()
        self.hasher = hasher or NumberHasher()

    # ------------------------------------------------------------------ families
    @staticmethod
    def _family(r: RobinFamilyRow) -> Family:
        d = dict(r.data or {})
        return Family(
            id=r.id, owner_user_id=r.user_id, status=FamilyStatus(r.status), parent_label=d.get("parent_label", "Papa"),
            settings=FamilySettings(**(d.get("settings") or {})), created_at=r.created_at,
        )

    @staticmethod
    def _family_data(f: Family) -> dict[str, Any]:
        return {"parent_label": f.parent_label, "settings": f.settings.model_dump(mode="json")}

    async def save_family(self, f: Family) -> Family:
        async with self.db.session() as s:
            row = await s.get(RobinFamilyRow, f.id)
            if row is None:
                s.add(RobinFamilyRow(id=f.id, user_id=f.owner_user_id, status=f.status.value, data=self._family_data(f)))
            else:
                row.status, row.data = f.status.value, self._family_data(f)
        return f

    async def get_family(self, family_id: str) -> Family | None:
        async with self.db.session() as s:
            r = await s.get(RobinFamilyRow, family_id)
            return self._family(r) if r else None

    async def families_for_owner(self, user_id: str) -> list[Family]:
        async with self.db.session() as s:
            rows = (await s.execute(select(RobinFamilyRow).where(RobinFamilyRow.user_id == user_id).order_by(RobinFamilyRow.created_at))).scalars()
            return [self._family(r) for r in rows]

    async def all_families(self, statuses: tuple[str, ...] = ("active", "paused", "onboarding")) -> list[Family]:
        async with self.db.session() as s:
            rows = (await s.execute(select(RobinFamilyRow).where(RobinFamilyRow.status.in_(statuses)))).scalars()
            return [self._family(r) for r in rows]

    # ------------------------------------------------------------------ members
    def phone_hash(self, phone: str) -> str:
        return self.hasher.hash(phone)

    def _member(self, r: RobinMemberRow) -> Member:
        d = dict(r.data or {})
        return Member(id=r.id, family_id=r.family_id, role=Role(r.role), phone_hash=r.phone_hash, **d)

    @staticmethod
    def _member_data(m: Member) -> dict[str, Any]:
        d = m.model_dump(mode="json", exclude={"id", "family_id", "role", "phone_hash"})
        return d

    async def save_member(self, m: Member, owner_user_id: str) -> Member:
        if m.phone:
            m.phone_hash = self.phone_hash(m.phone)
        async with self.db.session() as s:
            row = await s.get(RobinMemberRow, m.id)
            if row is None:
                s.add(RobinMemberRow(id=m.id, user_id=owner_user_id, family_id=m.family_id, role=m.role.value, phone_hash=m.phone_hash, data=self._member_data(m)))
            else:
                row.role, row.phone_hash, row.data = m.role.value, m.phone_hash, self._member_data(m)
        return m

    async def get_member(self, member_id: str) -> Member | None:
        async with self.db.session() as s:
            r = await s.get(RobinMemberRow, member_id)
            return self._member(r) if r else None

    async def members(self, family_id: str, role: Role | None = None) -> list[Member]:
        async with self.db.session() as s:
            q = select(RobinMemberRow).where(RobinMemberRow.family_id == family_id).order_by(RobinMemberRow.created_at)
            if role is not None:
                q = q.where(RobinMemberRow.role == role.value)
            return [self._member(r) for r in (await s.execute(q)).scalars()]

    async def members_by_phone(self, phone: str) -> list[Member]:
        h = self.phone_hash(phone)
        async with self.db.session() as s:
            rows = (await s.execute(select(RobinMemberRow).where(RobinMemberRow.phone_hash == h))).scalars()
            return [self._member(r) for r in rows]

    async def delete_member(self, member_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(RobinConsentRow).where(RobinConsentRow.member_id == member_id))
            await s.execute(delete(RobinMemberRow).where(RobinMemberRow.id == member_id))

    # ------------------------------------------------------------------ consents
    @staticmethod
    def _consent(r: RobinConsentRow) -> Consent:
        return Consent(id=r.id, family_id=r.family_id, member_id=r.member_id, item=r.item, given_at=r.given_at, source=ConsentSource(r.source), given_by=r.given_by, withdrawn_at=r.withdrawn_at)

    async def save_consent(self, c: Consent, owner_user_id: str) -> Consent:
        """One row per member and item: giving again after a withdrawal re-opens it with a new timestamp."""
        async with self.db.session() as s:
            row = (await s.execute(select(RobinConsentRow).where(RobinConsentRow.member_id == c.member_id, RobinConsentRow.item == c.item))).scalar_one_or_none()
            if row is None:
                s.add(RobinConsentRow(id=c.id, user_id=owner_user_id, family_id=c.family_id, member_id=c.member_id, item=c.item, given_at=c.given_at, source=c.source.value, given_by=c.given_by, withdrawn_at=c.withdrawn_at))
            else:
                row.given_at, row.source, row.given_by, row.withdrawn_at = c.given_at, c.source.value, c.given_by, c.withdrawn_at
                c.id = row.id
        return c

    async def consents(self, family_id: str, member_id: str | None = None) -> list[Consent]:
        async with self.db.session() as s:
            q = select(RobinConsentRow).where(RobinConsentRow.family_id == family_id)
            if member_id is not None:
                q = q.where(RobinConsentRow.member_id == member_id)
            return [self._consent(r) for r in (await s.execute(q)).scalars()]

    async def withdraw(self, member_id: str, item: str, at: datetime) -> bool:
        async with self.db.session() as s:
            res = await s.execute(update(RobinConsentRow).where(RobinConsentRow.member_id == member_id, RobinConsentRow.item == item, RobinConsentRow.withdrawn_at.is_(None)).values(withdrawn_at=at))
            return bool(res.rowcount)

    # ------------------------------------------------------------------ records
    async def put(self, rec: Record) -> tuple[Record, bool]:
        """Insert; with a ``key`` the same (family, kind, key) returns the existing row and False."""
        if rec.key is not None:
            old = await self.by_key(rec.family_id, rec.kind, rec.key)
            if old is not None:
                return old, False
        try:
            async with self.db.session() as s:
                s.add(RobinRecordRow(id=rec.id, user_id=rec.user_id, family_id=rec.family_id, kind=rec.kind, key=rec.key, status=rec.status, at=rec.at, due_at=rec.due_at, data=rec.data))
        except IntegrityError:
            old = await self.by_key(rec.family_id, rec.kind, rec.key or "")
            if old is not None:
                return old, False
            raise
        return rec, True

    async def get(self, rec_id: str) -> Record | None:
        async with self.db.session() as s:
            r = await s.get(RobinRecordRow, rec_id)
            return _record(r) if r else None

    async def by_key(self, family_id: str, kind: str, key: str) -> Record | None:
        async with self.db.session() as s:
            r = (await s.execute(select(RobinRecordRow).where(RobinRecordRow.family_id == family_id, RobinRecordRow.kind == kind, RobinRecordRow.key == key))).scalar_one_or_none()
            return _record(r) if r else None

    async def list(self, family_id: str, kind: str, *, status: str | tuple[str, ...] | None = None, since: datetime | None = None, until: datetime | None = None, limit: int = 500) -> list[Record]:
        async with self.db.session() as s:
            q = select(RobinRecordRow).where(RobinRecordRow.family_id == family_id, RobinRecordRow.kind == kind)
            if status is not None:
                q = q.where(RobinRecordRow.status.in_([status] if isinstance(status, str) else list(status)))
            if since is not None:
                q = q.where(RobinRecordRow.at >= since)
            if until is not None:
                q = q.where(RobinRecordRow.at < until)
            rows = (await s.execute(q.order_by(RobinRecordRow.at, RobinRecordRow.created_at).limit(limit))).scalars()
            return [_record(r) for r in rows]

    async def due(self, kind: str, statuses: tuple[str, ...], now: datetime, limit: int = 100) -> list[Record]:
        async with self.db.session() as s:
            q = select(RobinRecordRow).where(RobinRecordRow.kind == kind, RobinRecordRow.status.in_(list(statuses)), RobinRecordRow.due_at.is_not(None), RobinRecordRow.due_at <= now).order_by(RobinRecordRow.due_at).limit(limit)
            return [_record(r) for r in (await s.execute(q)).scalars()]

    async def cas(self, rec_id: str, expected: str | tuple[str, ...], *, status: str | None = None, due_at: Any = ..., data: dict[str, Any] | None = None) -> bool:
        """Move a record only if its status is still ``expected``; False when someone else moved it first."""
        vals: dict[str, Any] = {}
        if status is not None:
            vals["status"] = status
        if due_at is not ...:
            vals["due_at"] = due_at
        if data is not None:
            vals["data"] = data
        if not vals:
            return True
        exp = [expected] if isinstance(expected, str) else list(expected)
        async with self.db.session() as s:
            res = await s.execute(update(RobinRecordRow).where(RobinRecordRow.id == rec_id, RobinRecordRow.status.in_(exp)).values(**vals))
            return bool(res.rowcount)

    async def set_data(self, rec_id: str, data: dict[str, Any]) -> None:
        async with self.db.session() as s:
            await s.execute(update(RobinRecordRow).where(RobinRecordRow.id == rec_id).values(data=data))

    async def delete_record(self, rec_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(RobinRecordRow).where(RobinRecordRow.id == rec_id))

    async def purge_before(self, kind: str, before: datetime, statuses: tuple[str, ...] | None = None) -> int:
        async with self.db.session() as s:
            q = delete(RobinRecordRow).where(RobinRecordRow.kind == kind, RobinRecordRow.at < before)
            if statuses is not None:
                q = q.where(RobinRecordRow.status.in_(list(statuses)))
            res = await s.execute(q)
            return int(res.rowcount or 0)

    # ------------------------------------------------------------------ erasure
    async def erase_family(self, family_id: str) -> dict[str, int]:
        out: dict[str, int] = {}
        async with self.db.session() as s:
            for table, col in ((RobinRecordRow, RobinRecordRow.family_id), (RobinConsentRow, RobinConsentRow.family_id), (RobinMemberRow, RobinMemberRow.family_id)):
                res = await s.execute(delete(table).where(col == family_id))
                out[table.__tablename__] = int(res.rowcount or 0)
            res = await s.execute(delete(RobinFamilyRow).where(RobinFamilyRow.id == family_id))
            out["robin_families"] = int(res.rowcount or 0)
        return out

    async def erase_owner(self, user_id: str) -> dict[str, int]:
        async with self.db.session() as s:
            return await purge_user_robin(s, user_id)
