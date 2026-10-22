"""Tables of the chatbot pilot (migration 0010_chatbot).

* ``chatbot_sessions``: where each person is in the first-run flow. Keyed by the blind index of the
  phone (the number itself is never stored here), so a person who has not agreed yet leaves no
  readable trace; ``user_id`` is filled when consent creates the user and is the erasure key.
  The pending capture (a shared contact waiting for a nickname, a location pin waiting for a label)
  is encrypted.
* ``chatbot_waitlist``: pilot gate. Number hash only.
* ``chatbot_inbox``: wishlist (off-topic asks, numbers masked) and support requests, for the
  founder's review. Text is encrypted; rows are erased with the user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class ChatbotSessionRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "chatbot_sessions"

    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(24), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="hinglish")
    step_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    pending_kind: Mapped[str | None] = mapped_column(String(24))
    pending: Mapped[dict[str, Any] | None] = mapped_column(
        EncryptedJSON("chatbot_sessions.pending")
    )
    last_hash: Mapped[str | None] = mapped_column(String(32))
    refused_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ChatbotWaitlistRow(IdMixin, Base):
    __tablename__ = "chatbot_waitlist"

    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ChatbotInboxRow(IdMixin, Base):
    __tablename__ = "chatbot_inbox"
    __table_args__ = (Index("ix_chatbot_inbox_kind_created", "kind", "created_at"),)

    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # wishlist | support
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(EncryptedText("chatbot_inbox.text"), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="hinglish")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
