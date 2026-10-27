"""Tables of the trip timeline (migration 0017_trips).

No column holds a file or a document's text. Personal values (titles, airports, booking references,
hotel phone and address, the pickup address, message text) are encrypted at rest with the field
cipher (AES-GCM, AAD ``table.column``). A booking reference is also kept as a blind index
(``dedupe_hmac``) so a duplicate document is found without storing it in the clear. ``user_id`` is
the erasure key and the only way a per-user row is read. ``card_perks`` is shared (no personal data,
no revenue column), like ``card_rules``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
)
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


def _user_fk() -> Mapped[str]:
    return mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _trip_fk() -> Mapped[str]:
    return mapped_column(String(32), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)


class TripRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "trips"
    __table_args__ = (Index("ix_trips_user_status", "user_id", "status"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(EncryptedText("trips.title"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    created_from: Mapped[str] = mapped_column(String(8), nullable=False)
    travel_minutes: Mapped[int | None] = mapped_column(Integer)
    pickup_address: Mapped[str | None] = mapped_column(EncryptedText("trips.pickup_address"))
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TripLegRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "trip_legs"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_hmac", name="uq_trip_legs_user_dedupe"),
        Index("ix_trip_legs_trip", "trip_id"),
    )

    user_id: Mapped[str] = _user_fk()
    trip_id: Mapped[str] = _trip_fk()
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tz: Mapped[str] = mapped_column(String(40), nullable=False)
    end_tz: Mapped[str | None] = mapped_column(String(40))
    origin: Mapped[str | None] = mapped_column(EncryptedText("trip_legs.origin"))
    dest: Mapped[str | None] = mapped_column(EncryptedText("trip_legs.dest"))
    ref: Mapped[str | None] = mapped_column(EncryptedText("trip_legs.ref"))
    data: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON("trip_legs.data"), nullable=False)
    international: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    document_id: Mapped[str | None] = mapped_column(String(32))
    pointer_kind: Mapped[str | None] = mapped_column(String(16))
    dedupe_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")


class TripTaskRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "trip_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_trip_tasks_user_dedupe"),
        Index("ix_trip_tasks_trip", "trip_id"),
        Index("ix_trip_tasks_due", "due_at"),
    )

    user_id: Mapped[str] = _user_fk()
    trip_id: Mapped[str] = _trip_fk()
    leg_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(14), nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    state: Mapped[str] = mapped_column(String(14), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(32))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON("trip_tasks.params"), nullable=False
    )


class FlightWatchRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "flight_watch"
    __table_args__ = (
        UniqueConstraint("leg_id", name="uq_flight_watch_leg"),
        Index("ix_flight_watch_next", "next_check_at"),
    )

    user_id: Mapped[str] = _user_fk()
    trip_id: Mapped[str] = _trip_fk()
    leg_id: Mapped[str] = mapped_column(String(32), nullable=False)
    last_status: Mapped[str | None] = mapped_column(String(14))
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON("flight_watch.info"), nullable=False)


class TripNudgeRow(IdMixin, Base):
    __tablename__ = "trip_nudges"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_trip_nudges_user_key"),
        Index("ix_trip_nudges_user_sent", "user_id", "sent_at"),
    )

    user_id: Mapped[str] = _user_fk()
    trip_id: Mapped[str] = _trip_fk()
    key: Mapped[str] = mapped_column(String(140), nullable=False)
    topic: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str | None] = mapped_column(EncryptedText("trip_nudges.text"))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CardPerkRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "card_perks"
    __table_args__ = (UniqueConstraint("card_key", "perk", name="uq_card_perks_card_perk"),)

    card_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    perk: Mapped[str] = mapped_column(String(20), nullable=False)
    bank: Mapped[str] = mapped_column(String(80), nullable=False)
    card_name: Mapped[str] = mapped_column(String(80), nullable=False)
    visits_per_period: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    conditions_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    min_spend_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checked_on: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="draft")


async def purge_user_trips(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every trip row of the user. The
    shared ``card_perks`` table holds no personal data and is not touched."""
    out: dict[str, int] = {}
    for table in (TripNudgeRow, FlightWatchRow, TripTaskRow, TripLegRow, TripRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out


__all__ = [
    "CardPerkRow",
    "FlightWatchRow",
    "TripLegRow",
    "TripNudgeRow",
    "TripRow",
    "TripTaskRow",
    "purge_user_trips",
]
