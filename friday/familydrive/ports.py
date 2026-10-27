"""The Drive port: the only things the family-Drive service may ask of a Drive.

One port instance acts for ONE user (the connected owner). Nothing here lists, searches or reads
files by name across the whole Drive: with the ``drive.file`` scope Friday only ever sees what it
created, and every lookup below is by a file id Friday saved or by a key Friday stamped on the
object it created (``friday_key`` in the file's app properties).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveError(Exception):
    """Base class. ``code`` is a short machine reason; messages never hold a token or name."""

    code = "drive_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or (code or self.code))
        if code:
            self.code = code


class DriveUnreachable(DriveError):
    code = "unreachable"


class DriveNotLinked(DriveError):
    """The user never connected a Drive (or disconnected it)."""

    code = "not_linked"


class DriveNeedsReconnect(DriveError):
    code = "needs_reconnect"


class DriveScopeMissing(DriveError):
    """The Google connection exists but the user did not grant ``drive.file``."""

    code = "scope_missing"


class DriveRejected(DriveError):
    """Drive refused the call (HTTP 4xx other than 401/404)."""

    code = "rejected"


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str
    mime: str
    parent_id: str | None = None
    trashed: bool = False
    size: int | None = None
    web_link: str | None = None  # Drive's own link when it returned one


@runtime_checkable
class DrivePort(Protocol):
    async def find_by_key(self, key: str, *, parent_id: str | None = None) -> DriveItem | None:
        """The (untrashed) object Friday created with this key, if any."""

    async def create_folder(self, name: str, parent_id: str | None, *, key: str) -> DriveItem: ...

    async def upload(
        self, name: str, data: bytes, mime: str, parent_id: str, *, key: str
    ) -> DriveItem:
        """Stream ``data`` (held in memory by the caller) to Drive. Not retained here."""

    async def get(self, file_id: str) -> DriveItem | None:
        """Metadata, or None when the file is gone (deleted by the user, or not ours to see)."""

    async def download(self, file_id: str) -> bytes: ...

    async def trash(self, file_id: str) -> None: ...

    async def share(self, file_id: str, email: str, role: str) -> str:
        """Give ``email`` read (``viewer``) or write (``editor``) access; returns a permission id"""

    async def unshare(self, file_id: str, permission_id: str) -> None: ...


def drive_link(file_id: str, *, folder: bool = False) -> str:
    """A link the user can open in Drive. Built from the id only (the id is the pointer)."""
    if folder:
        return f"https://drive.google.com/drive/folders/{file_id}"
    return f"https://drive.google.com/file/d/{file_id}/view"
