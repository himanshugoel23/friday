"""Tables of the family Drive feature (migration 0016_family_drive).

Pointers only: no column holds file bytes, document text or a token (tokens stay in the existing
encrypted ``google_connections``). Drive ids and e-mail addresses are encrypted at rest with the
field cipher (AES-GCM, AAD ``table.column``). ``user_id`` is the erasure key and the only way a row
is read. The pointer to a filed document lives in ``documents.pointer_kind/pointer_ref`` (0014).

* ``drive_links``: one row per user who connected a Drive (the consent record + root folder id).
* ``drive_folders``: folder tree cache, one row per (user, path key) -> Drive folder id.
* ``drive_shares``: a request to share the root folder with a family member's Google account.
  Nothing is shared until the owner approves (status ``pending`` -> ``shared``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedText
from friday.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class DriveLinkRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "drive_links"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    root_folder_id: Mapped[str | None] = mapped_column(EncryptedText("drive_links.root_folder_id"))
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class DriveFolderRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "drive_folders"
    __table_args__ = (UniqueConstraint("user_id", "path_key", name="uq_drive_folders_user_key"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_key: Mapped[str] = mapped_column(String(160), nullable=False)
    folder_id: Mapped[str] = mapped_column(EncryptedText("drive_folders.folder_id"), nullable=False)


class DriveShareRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "drive_shares"
    __table_args__ = (Index("ix_drive_shares_user_status", "user_id", "status"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(EncryptedText("drive_shares.email"), nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)  # viewer | editor
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    permission_id: Mapped[str | None] = mapped_column(EncryptedText("drive_shares.permission_id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


async def purge_user_family_drive(s, user_id: str) -> dict[str, int]:  # noqa: ANN001
    """Used by ``DataPurger.purge_user`` (inside its session): every Drive row of the user. The
    document pointers go with the ``documents`` rows. Files in the user's Drive are theirs."""
    out: dict[str, int] = {}
    for table in (DriveShareRow, DriveFolderRow, DriveLinkRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out


__all__ = [
    "DriveFolderRow",
    "DriveLinkRow",
    "DriveShareRow",
    "purge_user_family_drive",
]
