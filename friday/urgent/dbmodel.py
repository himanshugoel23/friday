# ruff: noqa: E501
"""Tables of the urgent-call escalation (migration 0015_urgent_escalation).

``urgent_escalation_configs``: one row per user, the opt-in and overrides; the user's own number is
inside the encrypted JSON (AES-GCM, AAD ``table.column``). ``urgent_escalations``: one row per urgent
receptionist message (UNIQUE user + message = idempotent open), state machine fields only, no personal
text. ``user_id`` is the erasure key; finished rows are deleted after the retention period.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class UrgentEscalationConfigRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "urgent_escalation_configs"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    opted_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(EncryptedJSON("urgent_escalation_configs.config"), nullable=False)


class UrgentEscalationRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "urgent_escalations"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_urgent_escalations_user_message"),
        Index("ix_urgent_escalations_due", "status", "next_action_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    wait_s: Mapped[int] = mapped_column(Integer, nullable=False)
    max_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    spacing_s: Mapped[int] = mapped_column(Integer, nullable=False)
    next_action_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    calls_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_flight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_call_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_call_result: Mapped[str | None] = mapped_column(String(16))
    ack_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


async def purge_user_urgent(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every escalation row of the user."""
    out: dict[str, int] = {}
    for table in (UrgentEscalationRow, UrgentEscalationConfigRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
