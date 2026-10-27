"""Family Drive storage (tables in friday/familydrive/dbmodel.py): links, folder cache, share
requests. Every method takes the ``user_id`` and filters by it: one user's rows are never reachable
through another user's id. Drive ids and e-mail addresses are encrypted by the column type."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select

from friday.db.repositories._base import Repo
from friday.docunderstand.dbmodel import DocumentFieldRow, DocumentRow
from friday.familydrive.dbmodel import DriveFolderRow, DriveLinkRow, DriveShareRow

LINK_ACTIVE = "active"
LINK_NEEDS_RECONNECT = "needs_reconnect"

SHARE_PENDING = "pending"
SHARE_SHARED = "shared"
SHARE_DECLINED = "declined"
SHARE_REVOKED = "revoked"
SHARE_EXPIRED = "expired"
_SHARE_DONE_KEEP_DAYS = 30
POINTER_KIND = "gdrive"


@dataclass
class DriveLink:
    user_id: str
    status: str
    root_folder_id: str | None
    connected_at: datetime
    updated_at: datetime | None = None


@dataclass
class DriveShare:
    id: str
    user_id: str
    email: str
    role: str
    status: str
    permission_id: str | None
    expires_at: datetime
    decided_at: datetime | None = None


def _link(r: DriveLinkRow) -> DriveLink:
    return DriveLink(r.user_id, r.status, r.root_folder_id, r.connected_at, r.updated_at)


def _share(r: DriveShareRow) -> DriveShare:
    return DriveShare(
        r.id, r.user_id, r.email, r.role, r.status, r.permission_id, r.expires_at, r.decided_at
    )


class FamilyDriveRepo(Repo):
    # ------------------------------------------------------------------ link
    async def get_link(self, user_id: str) -> DriveLink | None:
        async with self.db.session() as s:
            r = (
                await s.execute(select(DriveLinkRow).where(DriveLinkRow.user_id == user_id))
            ).scalar_one_or_none()
            return _link(r) if r else None

    async def upsert_link(
        self, user_id: str, *, root_folder_id: str | None, status: str = LINK_ACTIVE
    ) -> DriveLink:
        async with self.db.session() as s:
            r = (
                await s.execute(select(DriveLinkRow).where(DriveLinkRow.user_id == user_id))
            ).scalar_one_or_none()
            if r is None:
                r = DriveLinkRow(user_id=user_id, connected_at=self.now())
                s.add(r)
            r.status, r.root_folder_id, r.updated_at = status, root_folder_id, self.now()
            await s.flush()
            return _link(r)

    async def set_link_status(self, user_id: str, status: str) -> None:
        async with self.db.session() as s:
            r = (
                await s.execute(select(DriveLinkRow).where(DriveLinkRow.user_id == user_id))
            ).scalar_one_or_none()
            if r is not None and r.status != status:
                r.status, r.updated_at = status, self.now()

    # ------------------------------------------------------------------ folder cache
    async def get_folder(self, user_id: str, path_key: str) -> str | None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(DriveFolderRow).where(
                        DriveFolderRow.user_id == user_id, DriveFolderRow.path_key == path_key
                    )
                )
            ).scalar_one_or_none()
            return r.folder_id if r else None

    async def put_folder(self, user_id: str, path_key: str, folder_id: str) -> None:
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(DriveFolderRow).where(
                        DriveFolderRow.user_id == user_id, DriveFolderRow.path_key == path_key
                    )
                )
            ).scalar_one_or_none()
            if r is None:
                s.add(DriveFolderRow(user_id=user_id, path_key=path_key, folder_id=folder_id))
            else:
                r.folder_id, r.updated_at = folder_id, self.now()

    async def delete_folders(self, user_id: str, path_key: str) -> int:
        """The folder row and every row below it (``path_key`` + "/...")."""
        async with self.db.session() as s:
            res = await s.execute(
                delete(DriveFolderRow).where(
                    DriveFolderRow.user_id == user_id,
                    or_(
                        DriveFolderRow.path_key == path_key,
                        DriveFolderRow.path_key.like(path_key.replace("%", "") + "/%"),
                    ),
                )
            )
            return int(res.rowcount or 0)

    async def count_folders(self, user_id: str) -> int:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(DriveFolderRow.id).where(DriveFolderRow.user_id == user_id))
            ).all()
            return len(rows)

    # ------------------------------------------------------------------ shares
    async def add_share(
        self, user_id: str, *, email: str, role: str, expires_at: datetime
    ) -> DriveShare:
        async with self.db.session() as s:
            r = DriveShareRow(
                user_id=user_id,
                email=email,
                role=role,
                status=SHARE_PENDING,
                expires_at=expires_at,
            )
            s.add(r)
            await s.flush()
            return _share(r)

    async def get_share(self, user_id: str, share_id: str) -> DriveShare | None:
        async with self.db.session() as s:
            r = await s.get(DriveShareRow, share_id)
            return _share(r) if r is not None and r.user_id == user_id else None

    async def list_shares(
        self, user_id: str, statuses: tuple[str, ...] | None = None
    ) -> list[DriveShare]:
        async with self.db.session() as s:
            q = select(DriveShareRow).where(DriveShareRow.user_id == user_id)
            if statuses:
                q = q.where(DriveShareRow.status.in_(statuses))
            rows = (await s.execute(q.order_by(DriveShareRow.created_at))).scalars().all()
            return [_share(r) for r in rows]

    async def update_share(
        self, user_id: str, share_id: str, *, status: str, permission_id: str | None = None
    ) -> DriveShare | None:
        async with self.db.session() as s:
            r = await s.get(DriveShareRow, share_id)
            if r is None or r.user_id != user_id:
                return None
            r.status, r.decided_at, r.updated_at = status, self.now(), self.now()
            if permission_id is not None:
                r.permission_id = permission_id
            await s.flush()
            return _share(r)

    # ------------------------------------------------------------------ delete / retention
    async def delete_all(self, user_id: str) -> dict[str, int]:
        """Disconnect: delete every Drive row of the user AND the pointers of documents filed in
        the Drive (the document row with its fields: its only purpose was the vault). The files in
        the user's Drive are theirs and are never touched here."""
        out: dict[str, int] = {}
        async with self.db.session() as s:
            ids = list(
                (
                    await s.execute(
                        select(DocumentRow.id).where(
                            DocumentRow.user_id == user_id,
                            DocumentRow.pointer_kind == POINTER_KIND,
                        )
                    )
                ).scalars()
            )
            if ids:
                await s.execute(
                    delete(DocumentFieldRow).where(DocumentFieldRow.document_id.in_(ids))
                )
                await s.execute(delete(DocumentRow).where(DocumentRow.id.in_(ids)))
            out["pointers"] = len(ids)
            for table, name in (
                (DriveShareRow, "shares"),
                (DriveFolderRow, "folders"),
                (DriveLinkRow, "links"),
            ):
                res = await s.execute(delete(table).where(table.user_id == user_id))
                out[name] = int(res.rowcount or 0)
        return out

    async def expire(self, now: datetime, *, stale_link_days: int) -> dict[str, int]:
        """Retention: unanswered share requests past ``expires_at`` become ``expired``; finished
        ones are deleted after 30 days; a link stuck in needs_reconnect for ``stale_link_days`` is
        dropped with everything under it."""
        out = {"drive_shares_expired": 0, "drive_shares_deleted": 0, "drive_links_dropped": 0}
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(DriveShareRow).where(
                        DriveShareRow.status == SHARE_PENDING, DriveShareRow.expires_at < now
                    )
                )
            ).scalars()
            for r in rows:
                r.status, r.decided_at, r.updated_at = SHARE_EXPIRED, now, now
                out["drive_shares_expired"] += 1
            res = await s.execute(
                delete(DriveShareRow).where(
                    DriveShareRow.status.in_([SHARE_DECLINED, SHARE_REVOKED, SHARE_EXPIRED]),
                    DriveShareRow.updated_at < now - timedelta(days=_SHARE_DONE_KEEP_DAYS),
                )
            )
            out["drive_shares_deleted"] = int(res.rowcount or 0)
            stale = list(
                (
                    await s.execute(
                        select(DriveLinkRow.user_id).where(
                            DriveLinkRow.status == LINK_NEEDS_RECONNECT,
                            DriveLinkRow.updated_at < now - timedelta(days=stale_link_days),
                        )
                    )
                ).scalars()
            )
        for uid in stale:
            await self.delete_all(uid)
            out["drive_links_dropped"] += 1
        return out


__all__ = [
    "LINK_ACTIVE",
    "LINK_NEEDS_RECONNECT",
    "POINTER_KIND",
    "SHARE_DECLINED",
    "SHARE_EXPIRED",
    "SHARE_PENDING",
    "SHARE_REVOKED",
    "SHARE_SHARED",
    "DriveLink",
    "DriveShare",
    "FamilyDriveRepo",
]
