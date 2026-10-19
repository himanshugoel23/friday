"""Tables for consumer calls (migration 0007_consumer_calls).

* ``consumer_contacts``: the user's own contact book. Name, nicknames and number are encrypted
  (AES-GCM, AAD ``table.column``); ``number_hash`` is a keyed hash for lookups. Per user only.
* ``call_requests`` / ``call_briefs`` / ``call_outcomes``: one request, its current brief (what the
  user approved, as encrypted JSON plus the approval hash) and one outcome per attempt. The callee's
  number is encrypted; ``callee_number_hash`` is the keyed hash used for per-recipient counters.
* ``call_attempts``: one row per dial, for daily caps and per-recipient frequency limits.
* ``call_strikes``: abuse strikes against a user.
* ``call_dnc``: the GLOBAL do-not-call registry. Keyed hash only, no plain number, no user id: it
  protects the recipient across all users and is never part of a user's erasure.

``user_id`` is the erasure key for everything except ``call_dnc``; repositories always filter by it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


def _enc(table: str, column: str) -> EncryptedText:
    return EncryptedText(f"{table}.{column}")


def _enc_json(table: str, column: str) -> EncryptedJSON:
    return EncryptedJSON(f"{table}.{column}")


def _user_fk() -> Mapped[str]:
    return mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ConsumerContactRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "consumer_contacts"
    __table_args__ = (UniqueConstraint("user_id", "number_hash"),)

    user_id: Mapped[str] = _user_fk()
    name: Mapped[str] = mapped_column(_enc("consumer_contacts", "name"), nullable=False)
    nicknames: Mapped[Any] = mapped_column(_enc_json("consumer_contacts", "nicknames"))
    relationship: Mapped[str | None] = mapped_column(String(40))
    number: Mapped[str] = mapped_column(_enc("consumer_contacts", "number"), nullable=False)
    number_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CallRequestRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "call_requests"

    user_id: Mapped[str] = _user_fk()
    callee_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(_enc("call_requests", "purpose"), nullable=False)
    purpose_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    callee_ref: Mapped[str | None] = mapped_column(_enc("call_requests", "callee_ref"))
    callee_name: Mapped[str | None] = mapped_column(_enc("call_requests", "callee_name"))
    callee_number: Mapped[str | None] = mapped_column(_enc("call_requests", "callee_number"))
    callee_number_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    number_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    company: Mapped[str | None] = mapped_column(_enc("call_requests", "company"))
    language: Mapped[str] = mapped_column(String(12), default="hinglish", nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime())
    parent_id: Mapped[str | None] = mapped_column(String(32), index=True)
    callback_of: Mapped[str | None] = mapped_column(String(32))
    group_members: Mapped[Any] = mapped_column(_enc_json("call_requests", "group_members"))
    raw_text: Mapped[str | None] = mapped_column(_enc("call_requests", "raw_text"))
    source_message_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32))


class CallBriefRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "call_briefs"

    request_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("call_requests.id", ondelete="CASCADE"), nullable=False,
        unique=True,
    )  # fmt: skip
    user_id: Mapped[str] = _user_fk()
    payload: Mapped[Any] = mapped_column(_enc_json("call_briefs", "payload"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_hash: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CallOutcomeRow(IdMixin, Base):
    __tablename__ = "call_outcomes"

    request_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("call_requests.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )  # fmt: skip
    user_id: Mapped[str] = _user_fk()
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[Any] = mapped_column(_enc_json("call_outcomes", "payload"), nullable=False)
    number_hash: Mapped[str | None] = mapped_column(String(64))
    duration_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    recording_ref: Mapped[str | None] = mapped_column(_enc("call_outcomes", "recording_ref"))
    transcript_ref: Mapped[str | None] = mapped_column(_enc("call_outcomes", "transcript_ref"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CallAttemptRow(IdMixin, Base):
    __tablename__ = "call_attempts"

    user_id: Mapped[str] = _user_fk()
    request_id: Mapped[str] = mapped_column(String(32), nullable=False)
    number_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class CallStrikeRow(IdMixin, Base):
    __tablename__ = "call_strikes"

    user_id: Mapped[str] = _user_fk()
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CallDncRow(IdMixin, Base):
    """Global do-not-call registry: keyed hash only (no number, no user)."""

    __tablename__ = "call_dnc"

    number_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


__all__ = [
    "CallAttemptRow",
    "CallBriefRow",
    "CallDncRow",
    "CallOutcomeRow",
    "CallRequestRow",
    "CallStrikeRow",
    "ConsumerContactRow",
]
