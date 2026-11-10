# ruff: noqa: E501
"""Tables and the DB store of the human desk (migration 0021_concierge).

* ``robin_concierge_requests``: one row per errand. Structural plain columns only (ids, state words, time); the whole request
  (summary, notes, proofs, pay link) is ``data`` = encrypted JSON (AES-GCM, AAD ``table.column``).
* ``robin_concierge_audit``: the append-only hash chain. Plain columns are ids, an action word and hashes; the integer ``counts`` are
  encrypted JSON. ``seq`` is unique, so two writers cannot both append the same position. No update or delete is offered.
* ``robin_concierge_docs``: handoffs and roster shifts, encrypted JSON keyed by (kind, target_id).
Never stored: message text, phone numbers (the bridge holds those), audio.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String, UniqueConstraint, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from friday.concierge.audit import AuditEntry
from friday.concierge.models import OPEN, ConciergeRequest
from friday.concierge.store import Conflict
from friday.core.crypto import EncryptedJSON
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class ConciergeRequestRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_concierge_requests"

    family_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    lane: Mapped[str] = mapped_column(String(16), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(48))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_concierge_requests.data"), nullable=False)


class ConciergeAuditRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_concierge_audit"
    __table_args__ = (UniqueConstraint("seq", name="uq_robin_concierge_audit_seq"),)

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    staff_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(48), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_concierge_audit.data"), nullable=False)


class ConciergeDocRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_concierge_docs"
    __table_args__ = (UniqueConstraint("kind", "target_id", name="uq_robin_concierge_docs_kind_target"),)

    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(48), nullable=False)
    parent_id: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_concierge_docs.data"), nullable=False)


def _entry(r: ConciergeAuditRow) -> AuditEntry:
    return AuditEntry(r.seq, r.at, r.staff_id, r.action, r.target_id, {k: int(v) for k, v in dict(r.data or {}).items()}, r.prev_hash, r.entry_hash)


class DbConciergeStore:
    def __init__(self, db) -> None:  # noqa: ANN001 - friday.db.session.Database
        self.db = db

    # ------------------------------------------------------------------ requests
    async def request_save(self, req: ConciergeRequest, *, expect_version: int | None) -> None:
        async with self.db.session() as s:
            row = await s.get(ConciergeRequestRow, req.id)
            if expect_version is not None and (row is None or row.version != expect_version):
                raise Conflict(req.id)
            if row is None:
                row = ConciergeRequestRow(id=req.id, family_id=req.family_id, parent_id=req.parent_id, status="", priority="", lane="", due_at=req.finish_due_at, version=req.version, data={})
                s.add(row)
            row.status, row.priority, row.lane, row.claimed_by = req.status.value, req.priority.value, req.lane.value, req.claimed_by
            row.due_at, row.version, row.data = req.finish_due_at, req.version, req.to_dict()
            await s.commit()

    async def request_get(self, request_id: str) -> ConciergeRequest | None:
        async with self.db.session() as s:
            row = await s.get(ConciergeRequestRow, request_id)
            return ConciergeRequest.from_dict(dict(row.data)) if row else None

    async def requests_open(self) -> list[ConciergeRequest]:
        async with self.db.session() as s:
            rows = (await s.execute(select(ConciergeRequestRow).where(ConciergeRequestRow.status.in_([x.value for x in OPEN])))).scalars().all()
            return [ConciergeRequest.from_dict(dict(r.data)) for r in rows]

    async def requests_for_parent(self, parent_id: str) -> list[ConciergeRequest]:
        async with self.db.session() as s:
            rows = (await s.execute(select(ConciergeRequestRow).where(ConciergeRequestRow.parent_id == parent_id))).scalars().all()
            return [ConciergeRequest.from_dict(dict(r.data)) for r in rows]

    async def erase_parent(self, parent_id: str) -> dict[str, int]:
        async with self.db.session() as s:
            a = await s.execute(delete(ConciergeRequestRow).where(ConciergeRequestRow.parent_id == parent_id))
            b = await s.execute(delete(ConciergeDocRow).where(ConciergeDocRow.parent_id == parent_id))
            await s.commit()
            return {"requests": int(a.rowcount or 0), "docs": int(b.rowcount or 0)}

    # ------------------------------------------------------------------ audit (append-only: no update, no delete)
    async def audit_last(self) -> AuditEntry | None:
        async with self.db.session() as s:
            r = (await s.execute(select(ConciergeAuditRow).order_by(ConciergeAuditRow.seq.desc()).limit(1))).scalars().first()
            return _entry(r) if r else None

    async def audit_append(self, entry: AuditEntry) -> None:
        async with self.db.session() as s:
            s.add(ConciergeAuditRow(seq=entry.seq, at=entry.at, staff_id=entry.staff_id, action=entry.action, target_id=entry.target_id, prev_hash=entry.prev_hash, entry_hash=entry.hash, data=dict(entry.counts)))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                raise Conflict("audit seq") from None

    async def audit_all(self) -> list[AuditEntry]:
        async with self.db.session() as s:
            rows = (await s.execute(select(ConciergeAuditRow).order_by(ConciergeAuditRow.seq))).scalars().all()
            return [_entry(r) for r in rows]

    # ------------------------------------------------------------------ docs (handoffs, shifts)
    async def doc_save(self, kind: str, target_id: str, data: dict[str, Any], *, parent_id: str = "", status: str = "") -> None:
        async with self.db.session() as s:
            row = (await s.execute(select(ConciergeDocRow).where(ConciergeDocRow.kind == kind, ConciergeDocRow.target_id == target_id))).scalars().first()
            if row is None:
                row = ConciergeDocRow(kind=kind, target_id=target_id, parent_id=parent_id, status=status, data={})
                s.add(row)
            row.parent_id, row.status, row.data = parent_id, status, data
            await s.commit()

    async def doc_get(self, kind: str, target_id: str) -> dict[str, Any] | None:
        async with self.db.session() as s:
            row = (await s.execute(select(ConciergeDocRow).where(ConciergeDocRow.kind == kind, ConciergeDocRow.target_id == target_id))).scalars().first()
            return dict(row.data) if row else None

    async def doc_list(self, kind: str) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            rows = (await s.execute(select(ConciergeDocRow).where(ConciergeDocRow.kind == kind))).scalars().all()
            return [dict(r.data) for r in rows]
