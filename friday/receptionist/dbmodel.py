# ruff: noqa: E501
"""Tables of the receptionist (migration 0011_receptionist).

Personal text (caller number, name, reason, snippet, contacts) is encrypted at rest with the field
cipher (AES-GCM, AAD ``table.column``). ``user_id`` is the erasure key; ``caller_hash`` /
``number_hash`` are blind indexes (equality only: caps and the block list). An UNROUTED message
(redirecting number unknown) has ``user_id`` NULL and is deleted after a few days.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


class ReceptionistConfigRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "receptionist_configs"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(EncryptedJSON("receptionist_configs.config"), nullable=False)


class ReceptionistMessageRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "receptionist_messages"
    __table_args__ = (
        Index("ix_receptionist_messages_user_created", "user_id", "created_at"),
        Index("ix_receptionist_messages_caller_created", "caller_hash", "created_at"),
    )

    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    caller_hash: Mapped[str | None] = mapped_column(String(64))
    caller_number: Mapped[str | None] = mapped_column(
        EncryptedText("receptionist_messages.caller_number")
    )
    caller_name: Mapped[str | None] = mapped_column(EncryptedText("receptionist_messages.caller_name"))
    reason: Mapped[str | None] = mapped_column(EncryptedText("receptionist_messages.reason"))
    snippet: Mapped[str | None] = mapped_column(EncryptedText("receptionist_messages.snippet"))
    callback_number: Mapped[str | None] = mapped_column(
        EncryptedText("receptionist_messages.callback_number")
    )
    known_contact_name: Mapped[str | None] = mapped_column(
        EncryptedText("receptionist_messages.known_contact_name")
    )
    urgency: Mapped[str] = mapped_column(String(8), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="new")
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasons: Mapped[list | None] = mapped_column(JSONType)  # classifier reasons (no personal text)


class ReceptionistBlockRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "receptionist_blocks"
    __table_args__ = (UniqueConstraint("user_id", "number_hash", name="uq_receptionist_blocks"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    number: Mapped[str] = mapped_column(EncryptedText("receptionist_blocks.number"), nullable=False)


class ReceptionistSpamRow(IdMixin, TimestampMixin, Base):
    """SHARED across users and ANONYMISED (migration 0012): a keyed hash of the caller number and a
    count. No user id, no number, no text: nothing here can be erased per user, because nothing in it
    belongs to one user. ``updated_at`` is the last report."""

    __tablename__ = "receptionist_spam"
    __table_args__ = (UniqueConstraint("number_hash", name="uq_receptionist_spam_number_hash"),)

    number_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reports: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


async def purge_user_receptionist(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every receptionist row of the user."""
    out: dict[str, int] = {}
    for table in (ReceptionistMessageRow, ReceptionistBlockRow, ReceptionistConfigRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
