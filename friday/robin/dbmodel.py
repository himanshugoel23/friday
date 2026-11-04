# ruff: noqa: E501
"""Tables of the Robin family core (migration 0019_robin_family).

``robin_families``, ``robin_members``, ``robin_consents`` and ``robin_records`` (medicines, dose events,
check-ins, incidents and the audit log, one generic table keyed by ``kind``). Everything personal is
inside encrypted JSON (AES-GCM, AAD ``table.column``): phones, names, medicine names, answers, the
safe-word hash. The indexed columns hold ids, states and times only; the phone has a keyed hash for
lookup. ``user_id`` (the child) is the erasure key everywhere.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class RobinFamilyRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_families"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_families.data"), nullable=False)


class RobinMemberRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_members"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(32), ForeignKey("robin_families.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_members.data"), nullable=False)


class RobinConsentRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_consents"
    __table_args__ = (UniqueConstraint("member_id", "item", name="uq_robin_consents_member_item"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(32), ForeignKey("robin_families.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(String(32), ForeignKey("robin_members.id", ondelete="CASCADE"), nullable=False)
    item: Mapped[str] = mapped_column(String(32), nullable=False)
    given_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    given_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RobinRecordRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_records"
    __table_args__ = (
        UniqueConstraint("family_id", "kind", "key", name="uq_robin_records_family_kind_key"),
        Index("ix_robin_records_due", "kind", "status", "due_at"),
        Index("ix_robin_records_family_kind", "family_id", "kind", "at"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(32), ForeignKey("robin_families.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_records.data"), nullable=False)


async def purge_user_robin(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every Robin row of the child."""
    out: dict[str, int] = {}
    for table in (RobinRecordRow, RobinConsentRow, RobinMemberRow, RobinFamilyRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
