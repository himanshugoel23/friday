"""SQLAlchemy declarative base + portable column types.

Owner: Engineering Manager (scaffold). After the scaffold lands, the Backend
Engineer owns friday/db/ (tables.py migrations-by-hand, repositories/).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, MetaData, String, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from friday.core.clock import UTC, ensure_utc, utcnow
from friday.core.models import new_id

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Stores UTC, always returns aware-UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        value = ensure_utc(value)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# JSON column usable on SQLite and Postgres (swap to JSONB variant later if needed).
JSONType = JSON().with_variant(JSON(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
