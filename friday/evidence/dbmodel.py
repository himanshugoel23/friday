"""Tables of the proof feature (migration 0013_evidence).

``summary`` and ``payload`` (call words, references) are encrypted at rest with the field cipher
(AES-GCM, AAD ``table.column``). ``user_id`` is the erasure key. No column holds raw document or
image bytes: a screenshot lives in the object store (``object_key``), a receipt is a sha-256 plus
extracted fields. ``expires_at`` drives the 90-day retention job.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


class EvidenceItemRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        Index("ix_evidence_items_task", "task_id"),
        Index("ix_evidence_items_user_captured", "user_id", "captured_at"),
        Index("ix_evidence_items_expires", "expires_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str | None] = mapped_column(EncryptedText("evidence_items.summary"))
    payload: Mapped[dict | None] = mapped_column(EncryptedJSON("evidence_items.payload"))
    object_key: Mapped[str | None] = mapped_column(String(300))
    sha256: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="engine")
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    shareable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction: Mapped[str] = mapped_column(String(8), nullable=False, default="none")


class DoneClaimRow(IdMixin, TimestampMixin, Base):
    """One claim per task (re-judging replaces it). Holds ids and codes only, no text."""

    __tablename__ = "done_claims"
    __table_args__ = (Index("ix_done_claims_task", "task_id", unique=True),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    claim_type: Mapped[str] = mapped_column(String(24), nullable=False)
    required_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence_ids: Mapped[list | None] = mapped_column(JSONType)
    missing: Mapped[list | None] = mapped_column(JSONType)


async def purge_user_evidence(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every proof row of the user."""
    out: dict[str, int] = {}
    for table in (DoneClaimRow, EvidenceItemRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
