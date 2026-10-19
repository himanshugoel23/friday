"""Tables for the life state (migration 0009_life_state).

Personal text (titles, locations, notes, commitment text, the person a commitment is about, and the
text of a sent follow-up) is encrypted at rest with the field cipher (AES-GCM, AAD
``table.column``). ``user_id`` is the erasure key and the ONLY way rows are read (repositories
always filter by it; Row Level Security is on with no policy for the public API roles).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


class LifeEventRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "life_events"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_ref", name="uq_life_events_source_ref"),
        Index("ix_life_events_user_start", "user_id", "start_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(EncryptedText("life_events.title"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(EncryptedText("life_events.location"))
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(EncryptedText("life_events.note"))
    repeat: Mapped[dict | None] = mapped_column(JSONType)


class LifeCommitmentRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "life_commitments"
    __table_args__ = (Index("ix_life_commitments_user_due", "user_id", "due_at"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(EncryptedText("life_commitments.text"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    repeat: Mapped[dict | None] = mapped_column(JSONType)
    person: Mapped[dict | None] = mapped_column(EncryptedJSON("life_commitments.person"))


class MuteTopicRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "mute_topics"
    __table_args__ = (UniqueConstraint("user_id", "topic", name="uq_mute_topics_user_topic"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False, default="text")


class LifeFollowupRow(IdMixin, Base):
    __tablename__ = "life_followups"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_life_followups_user_key"),
        Index("ix_life_followups_user_sent", "user_id", "sent_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    topic: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    text: Mapped[str | None] = mapped_column(EncryptedText("life_followups.text"))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


__all__ = ["LifeCommitmentRow", "LifeEventRow", "LifeFollowupRow", "MuteTopicRow"]
