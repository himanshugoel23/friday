"""The real DrivePort: Google Drive v3 REST for one connected user (scope ``drive.file`` only).

Every call goes through the existing OAuth service (``GoogleOAuth.access_token``), so tokens stay in
the encrypted store and never leave this module except as a Bearer header. Nothing here has run
against real Google: endpoints, query syntax and error shapes follow Google's public documentation
as remembered, and ``tests/google/fake_google.py`` mirrors that. See docs/FAMILY_DRIVE.md for the
one-day spike that must confirm them (UNVERIFIED).

Privacy: file bytes are sent as a streamed ``multipart/related`` body built from the caller's
in-memory ``bytes`` (a generator yields 64 KiB chunks; nothing is written to disk) and are not kept.
File names are chosen by our own code (``naming.py``), never by document text. Names and ids are
never logged: log lines carry a short reason code only.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from friday.core.config import Settings
from friday.core.logging import get_logger
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
from friday.google import scopes as sc
from friday.google.oauth import (
    GoogleError,
    GoogleOAuth,
    NeedsReconnect,
    NotConnected,
    ScopeMissing,
    default_http,
)

log = get_logger(__name__)

_FIELDS = "id,name,mimeType,parents,trashed,size,webViewLink"
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,120}$")  # keys are ours; never user text
_ROLES = {"viewer": "reader", "editor": "writer"}
_CHUNK = 64 * 1024


def _item(d: dict[str, Any]) -> DriveItem:
    parents = d.get("parents") or []
    size = d.get("size")
    return DriveItem(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        mime=str(d.get("mimeType", "")),
        parent_id=str(parents[0]) if parents else None,
        trashed=bool(d.get("trashed", False)),
        size=int(size) if size is not None and str(size).isdigit() else None,
        web_link=d.get("webViewLink"),
    )


class GoogleDrive:
    def __init__(
        self,
        oauth: GoogleOAuth,
        user_id: str,
        *,
        settings: Settings,
        http: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.oauth, self.user_id = oauth, user_id
        self.base = settings.google_drive_base_url.rstrip("/")
        self.upload_base = settings.google_drive_upload_url.rstrip("/")
        self.max_bytes = settings.family_drive_max_bytes
        self._http = http or default_http

    # ------------------------------------------------------------------ HTTP
    async def _token(self) -> str:
        try:
            return await self.oauth.access_token(self.user_id, scope=sc.DRIVE_FILE)
        except NotConnected:
            raise DriveNotLinked("no Google connection") from None
        except NeedsReconnect:
            raise DriveNeedsReconnect("reconnect needed") from None
        except ScopeMissing:
            raise DriveScopeMissing("drive.file not granted") from None
        except GoogleError as e:
            raise DriveError(f"google: {e.code}", code=e.code) from None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        ok: tuple[int, ...] = (200,),
        content: Callable[[], Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> httpx.Response:
        token = await self._token()
        for attempt in (1, 2):
            try:
                async with self._http() as client:
                    r = await client.request(
                        method,
                        url,
                        headers={"Authorization": f"Bearer {token}", **(headers or {})},
                        content=content() if content else None,
                        **kw,
                    )
            except httpx.HTTPError as e:
                raise DriveUnreachable(f"drive unreachable ({type(e).__name__})") from None
            if r.status_code == 401 and attempt == 1:
                try:
                    token = await self.oauth.force_refresh(self.user_id)
                except NeedsReconnect:
                    raise DriveNeedsReconnect("reconnect needed") from None
                except GoogleError as e:
                    raise DriveError(f"google: {e.code}", code=e.code) from None
                continue
            if r.status_code in ok:
                return r
            if r.status_code == 404:
                raise _NotFound()
            if r.status_code >= 500 or r.status_code == 429:
                raise DriveUnreachable(
                    f"drive returned {r.status_code}", code=f"http_{r.status_code}"
                )
            raise DriveRejected(f"drive returned {r.status_code}", code=f"http_{r.status_code}")
        raise DriveRejected("drive rejected the token", code="http_401")  # pragma: no cover

    # ------------------------------------------------------------------ reads
    async def find_by_key(self, key: str, *, parent_id: str | None = None) -> DriveItem | None:
        if not _KEY_RE.match(key):
            raise DriveRejected("bad key", code="bad_key")
        q = f"appProperties has {{ key='friday_key' and value='{key}' }} and trashed=false"
        if parent_id:
            if not _KEY_RE.match(parent_id):
                raise DriveRejected("bad parent id", code="bad_id")
            q += f" and '{parent_id}' in parents"
        r = await self._request(
            "GET",
            f"{self.base}/files",
            params={"q": q, "fields": f"files({_FIELDS})", "pageSize": 2, "spaces": "drive"},
        )
        files = r.json().get("files") or []
        return _item(files[0]) if files else None

    async def get(self, file_id: str) -> DriveItem | None:
        self._check_id(file_id)
        try:
            r = await self._request(
                "GET", f"{self.base}/files/{file_id}", params={"fields": _FIELDS}
            )
        except _NotFound:
            return None
        return _item(r.json())

    async def download(self, file_id: str) -> bytes:
        self._check_id(file_id)
        try:
            r = await self._request("GET", f"{self.base}/files/{file_id}", params={"alt": "media"})
        except _NotFound:
            raise DriveRejected("file not found", code="not_found") from None
        if len(r.content) > self.max_bytes:
            raise DriveRejected("file too large", code="too_large")
        return r.content

    # ------------------------------------------------------------------ writes
    async def create_folder(self, name: str, parent_id: str | None, *, key: str) -> DriveItem:
        body: dict[str, Any] = {
            "name": name,
            "mimeType": FOLDER_MIME,
            "appProperties": {"friday_key": key},
        }
        if parent_id:
            body["parents"] = [parent_id]
        r = await self._request("POST", f"{self.base}/files", params={"fields": _FIELDS}, json=body)
        return _item(r.json())

    async def upload(
        self, name: str, data: bytes, mime: str, parent_id: str, *, key: str
    ) -> DriveItem:
        if len(data) > self.max_bytes:
            raise DriveRejected("file too large", code="too_large")
        meta = json.dumps(
            {"name": name, "parents": [parent_id], "appProperties": {"friday_key": key}},
            ensure_ascii=False,
        ).encode()
        boundary = "friday-" + secrets.token_hex(12)
        head = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + meta
            + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
        )
        tail = f"\r\n--{boundary}--".encode()

        async def stream() -> AsyncIterator[bytes]:
            yield head
            for i in range(0, len(data), _CHUNK):
                yield data[i : i + _CHUNK]
            yield tail

        r = await self._request(
            "POST",
            f"{self.upload_base}/files",
            params={"uploadType": "multipart", "fields": _FIELDS},
            content=stream,
            headers={
                "Content-Type": f"multipart/related; boundary={boundary}",
                "Content-Length": str(len(head) + len(data) + len(tail)),
            },
        )
        return _item(r.json())

    async def trash(self, file_id: str) -> None:
        self._check_id(file_id)
        try:
            await self._request(
                "PATCH",
                f"{self.base}/files/{file_id}",
                params={"fields": "id"},
                json={"trashed": True},
            )
        except _NotFound:
            return  # already gone

    async def share(self, file_id: str, email: str, role: str) -> str:
        self._check_id(file_id)
        if role not in _ROLES:
            raise DriveRejected("bad role", code="bad_role")
        r = await self._request(
            "POST",
            f"{self.base}/files/{file_id}/permissions",
            params={"fields": "id"},
            json={"type": "user", "role": _ROLES[role], "emailAddress": email},
        )
        return str(r.json().get("id", ""))

    async def unshare(self, file_id: str, permission_id: str) -> None:
        self._check_id(file_id)
        self._check_id(permission_id)
        try:
            await self._request(
                "DELETE",
                f"{self.base}/files/{file_id}/permissions/{permission_id}",
                ok=(200, 204),
            )
        except _NotFound:
            return

    @staticmethod
    def _check_id(value: str) -> None:
        if not _KEY_RE.match(value) or "/" in value:
            raise DriveRejected("bad id", code="bad_id")


class _NotFound(DriveError):
    """HTTP 404 from Drive (a creating call whose parent vanished surfaces it as a DriveError)."""

    code = "not_found"


__all__ = ["GoogleDrive"]
