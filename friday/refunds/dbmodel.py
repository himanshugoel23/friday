"""Tables of refund tracking (migration 0018_refunds).

No column holds a file or document text. Vendor name, the user-typed vendor number, notes, evidence
summaries and payloads and reminder text are encrypted at rest with the field cipher (AES-GCM, AAD
``table.column``). Amounts are paise (int), states and kinds are short codes. ``user_id`` is the
erasure key and the only way a per-user row is read.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


def _user_fk() -> Mapped[str]:
    return mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _case_fk() -> Mapped[str]:
    return mapped_column(
        String(32), ForeignKey("refund_cases.id", ondelete="CASCADE"), nullable=False
    )


class RefundCaseRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "refund_cases"
    __table_args__ = (
        Index("ix_refund_cases_user_state", "user_id", "state"),
        Index("ix_refund_cases_origin", "user_id", "origin", "origin_ref"),
    )

    user_id: Mapped[str] = _user_fk()
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(14), nullable=False)
    origin_ref: Mapped[str | None] = mapped_column(String(64))
    vendor_name: Mapped[str] = mapped_column(
        EncryptedText("refund_cases.vendor_name"), nullable=False
    )
    amount_expected_paise: Mapped[int | None] = mapped_column(Integer)
    amount_received_paise: Mapped[int | None] = mapped_column(Integer)
    promised_date: Mapped[date | None] = mapped_column(Date)
    promised_amount_paise: Mapped[int | None] = mapped_column(Integer)
    paid_with_bank: Mapped[str | None] = mapped_column(EncryptedText("refund_cases.paid_with_bank"))
    user_number: Mapped[str | None] = mapped_column(EncryptedText("refund_cases.user_number"))
    task_id: Mapped[str | None] = mapped_column(String(32))
    state_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    closed_reason: Mapped[str | None] = mapped_column(String(20))
    closed_basis: Mapped[str | None] = mapped_column(String(8))
    proposal: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON("refund_cases.proposal"))
    chase_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(EncryptedText("refund_cases.note"))


class RefundEventRow(IdMixin, Base):
    __tablename__ = "refund_events"
    __table_args__ = (Index("ix_refund_events_case", "case_id"),)

    user_id: Mapped[str] = _user_fk()
    case_id: Mapped[str] = _case_fk()
    from_state: Mapped[str | None] = mapped_column(String(20))
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str | None] = mapped_column(EncryptedText("refund_events.note"))
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class RefundEvidenceRow(IdMixin, Base):
    __tablename__ = "refund_evidence"
    __table_args__ = (Index("ix_refund_evidence_case", "case_id"),)

    user_id: Mapped[str] = _user_fk()
    case_id: Mapped[str] = _case_fk()
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str | None] = mapped_column(EncryptedText("refund_evidence.summary"))
    payload: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON("refund_evidence.payload"))
    amount_paise: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    proof_item_id: Mapped[str | None] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RefundNudgeRow(IdMixin, Base):
    __tablename__ = "refund_nudges"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_refund_nudges_user_key"),
        Index("ix_refund_nudges_user_sent", "user_id", "sent_at"),
    )

    user_id: Mapped[str] = _user_fk()
    case_id: Mapped[str] = _case_fk()
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str | None] = mapped_column(EncryptedText("refund_nudges.text"))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


async def purge_user_refunds(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every refund row of the user."""
    out: dict[str, int] = {}
    for table in (RefundNudgeRow, RefundEvidenceRow, RefundEventRow, RefundCaseRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out


__all__ = [
    "RefundCaseRow",
    "RefundEventRow",
    "RefundEvidenceRow",
    "RefundNudgeRow",
    "purge_user_refunds",
]
