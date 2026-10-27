"""Tables of the document feature (migration 0014_documents).

No column holds file bytes. ``value`` of a field and ``pointer_ref`` are encrypted at rest with the
field cipher (AES-GCM, AAD ``table.column``). ``user_id`` is the erasure key. ``expires_at`` drives
the retention job (unconfirmed 7 days, confirmed per ``FRIDAY_DOCS_RETENTION_DAYS``). A passport
number exists here only in masked form.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedText
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class DocumentRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_status", "user_id", "status"),
        Index("ix_documents_expires", "expires_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mime: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="hinglish")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    injection_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pointer_kind: Mapped[str | None] = mapped_column(String(16))  # item E: "gdrive"
    pointer_ref: Mapped[str | None] = mapped_column(EncryptedText("documents.pointer_ref"))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DocumentFieldRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_fields"
    __table_args__ = (
        Index("ix_document_fields_doc", "document_id"),
        Index("ix_document_fields_user", "user_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(EncryptedText("document_fields.value"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="doc")
    masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


async def purge_user_documents(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every document row of the user.
    A Drive file the user filed (item E) is theirs and is not touched; only our pointer goes."""
    out: dict[str, int] = {}
    for table in (DocumentFieldRow, DocumentRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
