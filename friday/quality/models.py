"""SQLAlchemy table for stored transcripts (migration 0004_quality_calls).

One row per consented front-door call. Transcript and the founder's note are encrypted
at rest (AAD ``quality_calls.<column>``); labels, rating and call metadata are not PII.
``user_id`` is the erasure key: "delete everything" removes every row of the user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, UTCDateTime


class QualityCallRow(IdMixin, Base):
    __tablename__ = "quality_calls"

    call_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stored_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    # non-PII call facts (kind, outcome, duration, languages, turns, p95_ms, cost)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # redacted turns: [{"speaker","text","language","at"}]
    transcript: Mapped[Any] = mapped_column(
        EncryptedJSON("quality_calls.transcript"), nullable=False
    )
    labels: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    note: Mapped[str | None] = mapped_column(EncryptedText("quality_calls.note"))
    rating: Mapped[int | None] = mapped_column(Integer)
    rated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    labelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
