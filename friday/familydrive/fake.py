"""In-memory Drive for tests and the simulator (no network). Mirrors what matters to us:

* one separate "Drive" per user (``FakeDriveHub.for_user``), so isolation is testable;
* objects are found only by id or by the ``friday_key`` Friday stamped (drive.file semantics);
* files hold the uploaded bytes ONLY so tests can assert what reached "Drive"; the service never
  reads them back except through ``download``;
* switches to fail a call (unreachable, needs_reconnect, scope missing) and to simulate the user
  deleting or trashing things in their own Drive.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from friday.familydrive.ports import (
    FOLDER_MIME,
    DriveError,
    DriveItem,
    DriveNeedsReconnect,
    DriveNotLinked,
    DriveRejected,
    DriveScopeMissing,
    DriveUnreachable,
)

_ids = itertools.count(1)


@dataclass
class _Obj:
    id: str
    name: str
    mime: str
    parent_id: str | None
    key: str | None
    data: bytes = b""
    trashed: bool = False
    permissions: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (email, role)


class FakeDrive:
    """One user's fake Drive. ``calls`` records every operation name (never names or bytes)."""

    def __init__(self, owner_email: str = "owner.example@gmail.com") -> None:
        self.owner_email = owner_email
        self.objects: dict[str, _Obj] = {}
        self.calls: list[str] = []
        self.fail: DriveError | None = None  # raised by the next/every call while set
        self.fail_upload_once = False

    # ------------------------------------------------------------------ test helpers
    def _enter(self, op: str) -> None:
        self.calls.append(op)
        if self.fail is not None:
            raise self.fail

    def set_failure(self, kind: str | None) -> None:
        self.fail = {
            None: None,
            "unreachable": DriveUnreachable("down"),
            "needs_reconnect": DriveNeedsReconnect("reconnect"),
            "scope_missing": DriveScopeMissing("scope"),
            "not_linked": DriveNotLinked("none"),
            "rejected": DriveRejected("no"),
        }[kind]

    def count(self, op: str) -> int:
        return self.calls.count(op)

    def files(self) -> list[_Obj]:
        return [o for o in self.objects.values() if o.mime != FOLDER_MIME]

    def folders(self) -> list[_Obj]:
        return [o for o in self.objects.values() if o.mime == FOLDER_MIME]

    def user_deletes(self, file_id: str) -> None:
        self.objects.pop(file_id, None)

    def user_trashes(self, file_id: str) -> None:
        """Trash a file or folder; like Drive, everything below it reads as trashed too."""
        self.objects[file_id].trashed = True
        for o in self.objects.values():
            if o.parent_id == file_id:
                self.user_trashes(o.id)

    def path_of(self, file_id: str) -> str:
        parts: list[str] = []
        cur: str | None = file_id
        while cur:
            o = self.objects[cur]
            parts.append(o.name)
            cur = o.parent_id
        return "/".join(reversed(parts))

    @staticmethod
    def _item(o: _Obj) -> DriveItem:
        return DriveItem(
            id=o.id,
            name=o.name,
            mime=o.mime,
            parent_id=o.parent_id,
            trashed=o.trashed,
            size=len(o.data) if o.mime != FOLDER_MIME else None,
        )

    # ------------------------------------------------------------------ the port
    async def find_by_key(self, key: str, *, parent_id: str | None = None) -> DriveItem | None:
        self._enter("find_by_key")
        for o in self.objects.values():
            if o.key == key and not o.trashed and (parent_id is None or o.parent_id == parent_id):
                return self._item(o)
        return None

    async def create_folder(self, name: str, parent_id: str | None, *, key: str) -> DriveItem:
        self._enter("create_folder")
        if parent_id is not None and parent_id not in self.objects:
            raise DriveError("parent missing", code="not_found")
        o = _Obj(f"fk{next(_ids):06d}", name, FOLDER_MIME, parent_id, key)
        self.objects[o.id] = o
        return self._item(o)

    async def upload(
        self, name: str, data: bytes, mime: str, parent_id: str, *, key: str
    ) -> DriveItem:
        self._enter("upload")
        if self.fail_upload_once:
            self.fail_upload_once = False
            raise DriveUnreachable("dropped")
        if parent_id not in self.objects:
            raise DriveError("parent missing", code="not_found")
        o = _Obj(f"ff{next(_ids):06d}", name, mime, parent_id, key, data=bytes(data))
        self.objects[o.id] = o
        return self._item(o)

    async def get(self, file_id: str) -> DriveItem | None:
        self._enter("get")
        o = self.objects.get(file_id)
        return self._item(o) if o else None

    async def download(self, file_id: str) -> bytes:
        self._enter("download")
        o = self.objects.get(file_id)
        if o is None or o.trashed:
            raise DriveRejected("gone", code="not_found")
        return o.data

    async def trash(self, file_id: str) -> None:
        self._enter("trash")
        if file_id in self.objects:
            self.objects[file_id].trashed = True

    async def share(self, file_id: str, email: str, role: str) -> str:
        self._enter("share")
        o = self.objects.get(file_id)
        if o is None:
            raise DriveError("gone", code="not_found")
        pid = f"perm{next(_ids):05d}"
        o.permissions[pid] = (email, role)
        return pid

    async def unshare(self, file_id: str, permission_id: str) -> None:
        self._enter("unshare")
        o = self.objects.get(file_id)
        if o is not None:
            o.permissions.pop(permission_id, None)


class FakeDriveHub:
    """``factory`` is what ``FamilyDrive`` takes: user id -> that user's own FakeDrive."""

    def __init__(self) -> None:
        self.drives: dict[str, FakeDrive] = {}

    def for_user(self, user_id: str) -> FakeDrive:
        return self.drives.setdefault(user_id, FakeDrive())

    def factory(self, user_id: str) -> FakeDrive:
        return self.for_user(user_id)


__all__ = ["FakeDrive", "FakeDriveHub"]
