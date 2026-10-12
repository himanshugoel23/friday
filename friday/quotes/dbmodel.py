"""Table for the WhatsApp quotes conversations (migration 0005_quote_conversations).

One row per request ("kal shaam haircut quotes"). ``data`` (the slots, the location, the
shortlist, vendor outcomes) is encrypted at rest: it holds an address and names.
``user_id`` is the erasure key ("delete everything" removes the rows).
``version`` is an optimistic-concurrency counter: a button tap and a finished call may update
the same conversation at once, the loser reloads and re-applies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON
from friday.db.base import Base, IdMixin, UTCDateTime


class QuoteConversationRow(IdMixin, Base):
    __tablename__ = "quote_conversations"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    counted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON("quote_conversations.data"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
