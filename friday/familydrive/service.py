"""FamilyDrive: the family's documents live in the family's OWN Google Drive (scope drive.file).

What we keep: a file-id pointer on the ``documents`` row (``pointer_kind="gdrive"``, encrypted
``pointer_ref``), the minimal confirmed fields item D already holds, the folder-id cache and share
requests. What we never keep: the file bytes (they arrive as ``bytes`` from the caller, are streamed
to Drive and dropped), tokens (existing encrypted store), passport/ID numbers (item D has none).

Actor model for the pilot: the OWNER (the connected user) is the only actor. Every method takes the
owner's user id and every repository read filters by it, so another user's id reaches nothing. A
family member's access to the folder is a Drive share (owner-approved), not a Friday login.

Failure rule: fail closed. If Drive is unreachable or the token is dead nothing is stored, the
caller gets a ``DriveError`` with a short code, and a dead token marks the link ``needs_reconnect``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from friday.core.clock import Clock, SystemClock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.db.repositories import Repositories
from friday.db.repositories.family_drive import (
    LINK_ACTIVE,
    LINK_NEEDS_RECONNECT,
    POINTER_KIND,
    SHARE_DECLINED,
    SHARE_PENDING,
    SHARE_REVOKED,
    SHARE_SHARED,
    DriveShare,
)
from friday.docunderstand.models import DocStatus, DocType, Document
from friday.docunderstand.ports import ALLOWED_MIMES, sniff_mime
from friday.familydrive import copy, tree
from friday.familydrive.ports import (
    DriveError,
    DriveNeedsReconnect,
    DriveNotLinked,
    DrivePort,
    DriveUnreachable,
    drive_link,
)

log = get_logger(__name__)

DriveFactory = Callable[[str], DrivePort]
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63}){1,3}$")
_MAX_PENDING_SHARES = 5
ROLES = ("viewer", "editor")

_TYPE_WORDS: dict[DocType, tuple[str, ...]] = {
    DocType.PASSPORT: ("passport", "pasport", "पासपोर्ट"),
    DocType.FLIGHT: ("flight", "ticket", "tickets", "udaan", "फ्लाइट", "टिकट", "boarding"),
    DocType.TRAIN: ("train", "ticket", "tickets", "irctc", "ट्रेन", "टिकट"),
    DocType.HOTEL: ("hotel", "booking", "होटल", "stay"),
    DocType.BILL: ("bill", "bills", "बिल", "invoice"),
}
_STOP = frozenset(
    {
        *("my", "the", "a", "an", "of", "for", "is", "where", "mera", "meri", "mere", "ka"),
        *("ki", "ke", "kahan", "hai", "hain", "kaha", "dikhao", "bhejo", "send", "show"),
        *("find", "me", "to", "and", "ya", "aur", "kidhar", ""),
        *("मेरा", "मेरी", "मेरे", "का", "की", "के", "कहाँ", "कहां", "है", "हैं", "दिखाओ", "भेजो"),
    }
)


class FamilyDriveError(DriveError):
    code = "family_drive_error"


@dataclass(frozen=True)
class LinkInfo:
    state: str  # active | needs_reconnect | not_linked
    root_link: str | None = None


@dataclass(frozen=True)
class FiledDocument:
    document_id: str
    link: str
    name: str
    path: str
    already_filed: bool = False


@dataclass(frozen=True)
class DriveHit:
    document_id: str
    doc_type: str
    name: str
    path: str
    link: str
    verified: bool = True


@dataclass(frozen=True)
class DisconnectResult:
    pointers: int
    folders: int
    shares: int
    links: int
    root_trashed: bool = False


@dataclass
class _Pointer:
    id: str
    path: str = ""
    name: str = ""


def _parse_pointer(ref: str | None) -> _Pointer | None:
    try:
        d = json.loads(ref or "")
        return _Pointer(str(d["id"]), str(d.get("path", "")), str(d.get("name", "")))
    except (ValueError, KeyError, TypeError):
        return None


@dataclass
class FamilyDrive:
    settings: Settings
    repos: Repositories
    drive_factory: DriveFactory
    clock: Clock = field(default_factory=SystemClock)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ gates
    @property
    def enabled(self) -> bool:
        return self.settings.family_drive_enabled

    def _need_enabled(self) -> None:
        if not self.enabled:
            raise FamilyDriveError("family Drive is switched off", code="disabled")

    def _lock(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def _active_link(self, user_id: str):  # noqa: ANN202
        self._need_enabled()
        link = await self.repos.family_drive.get_link(user_id)
        if link is None:
            raise DriveNotLinked("Drive not connected")
        if link.status != LINK_ACTIVE:
            raise DriveNeedsReconnect("reconnect needed")
        return link

    async def _guard(self, user_id: str, exc: DriveError) -> DriveError:
        """A dead token marks the link ``needs_reconnect`` (shown as a prompt, not an outage)."""
        if isinstance(exc, DriveNeedsReconnect):
            await self.repos.family_drive.set_link_status(user_id, LINK_NEEDS_RECONNECT)
        log.warning("family drive call failed user=%s reason=%s", user_id, exc.code)
        return exc

    # ------------------------------------------------------------------ link and tree
    async def status(self, user_id: str) -> LinkInfo:
        link = await self.repos.family_drive.get_link(user_id)
        if link is None:
            return LinkInfo("not_linked")
        root = drive_link(link.root_folder_id, folder=True) if link.root_folder_id else None
        return LinkInfo(link.status, root)

    async def link(self, user_id: str) -> LinkInfo:
        """After the user granted ``drive.file`` (the consent flow in ``friday/google``): create the
        ``Friday`` root folder (or find the one we made before) and record the link."""
        self._need_enabled()
        drive = self.drive_factory(user_id)
        async with self._lock(user_id):
            try:
                root = await self._folder(user_id, drive, tree.ROOT, None)
            except DriveError as e:
                raise await self._guard(user_id, e) from None
            await self.repos.family_drive.upsert_link(user_id, root_folder_id=root)
        await self.repos.audit.log("drive.linked", user_id=user_id)
        return LinkInfo(LINK_ACTIVE, drive_link(root, folder=True))

    async def _folder(
        self,
        user_id: str,
        drive: DrivePort,
        path_key: str,
        parent_id: str | None,
        name: str | None = None,
    ) -> str:
        """Folder id for ``path_key``, created if missing. Idempotent: the saved id is checked
        first (a folder the user deleted or trashed is recreated), then the Drive-side key (a lost
        local row or a retry after a timeout finds the folder we already made), then create."""
        repo = self.repos.family_drive
        saved = await repo.get_folder(user_id, path_key)
        if saved:
            item = await drive.get(saved)
            if item is not None and not item.trashed:
                return item.id
            await repo.delete_folders(user_id, path_key)  # it and everything cached below it
        dkey = tree.drive_key(user_id, path_key)
        item = await drive.find_by_key(dkey, parent_id=parent_id)
        if item is None:
            item = await drive.create_folder(
                name or copy.folder_name(path_key.rsplit("/", 1)[-1]), parent_id, key=dkey
            )
        await repo.put_folder(user_id, path_key, item.id)
        return item.id

    async def _path(
        self,
        user_id: str,
        drive: DrivePort,
        *,
        scope: str,
        label: str,
        subs: tuple[str, ...],
    ) -> dict[str, str]:
        """Ensure ``Friday/<Family|Trips>/<label>/<sub>`` for each sub. Returns sub -> folder id."""
        link = await self._active_link(user_id)
        root = await self._folder(user_id, drive, tree.ROOT, None)
        if root != link.root_folder_id:
            await self.repos.family_drive.upsert_link(user_id, root_folder_id=root)
        top_key = tree.FAMILY if scope == "person" else tree.TRIPS
        top = await self._folder(user_id, drive, top_key, root)
        leaf_key = tree.person_key(label) if scope == "person" else tree.trip_key(label)
        leaf = await self._folder(
            user_id, drive, leaf_key, top, name=tree.clean_folder_name(label, "Unnamed")
        )
        return {sub: await self._folder(user_id, drive, f"{leaf_key}/{sub}", leaf) for sub in subs}

    async def ensure_tree(
        self, user_id: str, *, person: str | None = None, trip: str | None = None
    ) -> dict[str, str]:
        """Create (idempotently) the whole standard tree for a person and/or a trip. Returns
        path key -> Drive link of each leaf folder."""
        out: dict[str, str] = {}
        drive = self.drive_factory(user_id)
        async with self._lock(user_id):
            try:
                if person is not None:
                    for sub, fid in (
                        await self._path(
                            user_id, drive, scope="person", label=person, subs=tree.PERSON_SUBS
                        )
                    ).items():
                        out[f"{tree.person_key(person)}/{sub}"] = drive_link(fid, folder=True)
                if trip is not None:
                    for sub, fid in (
                        await self._path(
                            user_id, drive, scope="trip", label=trip, subs=tree.TRIP_SUBS
                        )
                    ).items():
                        out[f"{tree.trip_key(trip)}/{sub}"] = drive_link(fid, folder=True)
            except DriveError as e:
                raise await self._guard(user_id, e) from None
        return out

    # ------------------------------------------------------------------ filing
    async def file_document(
        self,
        user_id: str,
        document_id: str,
        data: bytes,
        *,
        mime: str | None = None,
        person: str | None = None,
        trip: str | None = None,
    ) -> FiledDocument:
        """Upload the CONFIRMED document's original to its folder and keep only the pointer.

        ``data`` stays in the caller's memory; it is streamed to Drive and not retained here. If the
        upload fails nothing is stored (the user is asked to send the file again)."""
        self._need_enabled()
        doc = await self.repos.documents.get(user_id, document_id)  # filters by user
        if doc is None:
            raise FamilyDriveError("unknown document", code="unknown_document")
        if doc.status is not DocStatus.CONFIRMED:
            raise FamilyDriveError("document not confirmed yet", code="not_confirmed")
        existing = _parse_pointer(doc.pointer_ref) if doc.pointer_kind == POINTER_KIND else None
        if existing is not None:
            return FiledDocument(
                doc.id, drive_link(existing.id), existing.name, existing.path, True
            )
        sniffed = sniff_mime(data)
        if (
            not data
            or sniffed is None
            or sniffed not in ALLOWED_MIMES
            or (mime and mime != sniffed)
        ):
            raise FamilyDriveError("unsupported or empty file", code="bad_file")
        if len(data) > self.settings.family_drive_max_bytes:
            raise FamilyDriveError("file too large", code="too_large")
        if doc.sha256 and hashlib.sha256(data).hexdigest() != doc.sha256:
            raise FamilyDriveError("file is not the confirmed document", code="hash_mismatch")

        scope, sub = tree.destination(doc.doc_type, has_trip=bool(trip))
        label = (trip if scope == "trip" else person) or copy.folder_name(
            "default_trip" if scope == "trip" else "default_person"
        )
        name = tree.file_name(doc, sniffed)
        drive = self.drive_factory(user_id)
        async with self._lock(user_id):
            try:
                folders = await self._path(user_id, drive, scope=scope, label=label, subs=(sub,))
                parent = folders[sub]
                fkey = tree.file_key(user_id, doc.id)
                item = await drive.find_by_key(fkey, parent_id=parent)  # a retry after a timeout
                if item is None:
                    item = await drive.upload(name, data, sniffed, parent, key=fkey)
            except DriveError as e:
                raise await self._guard(user_id, e) from None
            folder_label = copy.folder_name("family" if scope == "person" else "trips")
            path = "/".join(
                [
                    copy.folder_name("root"),
                    folder_label,
                    tree.clean_folder_name(label, "Unnamed"),
                    copy.folder_name(sub),
                ]
            )
            ref = json.dumps({"id": item.id, "path": path, "name": name}, ensure_ascii=False)
            try:
                ok = await self.repos.documents.set_pointer(user_id, doc.id, POINTER_KIND, ref)
                if not ok:
                    raise FamilyDriveError("document vanished", code="unknown_document")
            except Exception:
                try:  # never leave a file Friday cannot find again
                    await drive.trash(item.id)
                except DriveError:
                    log.warning("family drive orphan could not be trashed user=%s", user_id)
                raise
        await self.repos.audit.log(
            "drive.filed", user_id=user_id, subject_id=doc.id, doc_type=doc.doc_type.value
        )
        return FiledDocument(doc.id, item.web_link or drive_link(item.id), name, path)

    # ------------------------------------------------------------------ lookup
    async def where_is(self, user_id: str, query: str, *, verify: bool = True) -> list[DriveHit]:
        """ "Where is my X": the Drive link(s) of matching filed documents, newest first. A pointer
        whose file the user deleted or trashed is dropped when found (dangling)."""
        self._need_enabled()
        docs = await self.repos.documents.list_with_pointer(user_id, POINTER_KIND)
        words = [w for w in re.split(r"[\s,.;:!?\-]+", query.casefold()) if w not in _STOP]
        types = {dt for dt, ws in _TYPE_WORDS.items() if any(w in ws for w in words)}
        names = [w for w in words if not any(w in ws for ws in _TYPE_WORDS.values())]
        scored: list[tuple[int, Document, _Pointer]] = []
        for d in docs:
            ptr = _parse_pointer(d.pointer_ref)
            if ptr is None or (types and d.doc_type not in types):
                continue
            hay = " ".join([ptr.path, ptr.name, *d.values().values()]).casefold()
            hits = sum(1 for w in names if w in hay)
            if names and hits == 0:
                continue
            scored.append((hits, d, ptr))
        scored.sort(key=lambda x: (-x[0], -x[1].created_at.timestamp()))
        out: list[DriveHit] = []
        drive = self.drive_factory(user_id) if verify else None
        for _, d, ptr in scored[:5]:
            verified = True
            link = drive_link(ptr.id)
            if drive is not None:
                try:
                    item = await drive.get(ptr.id)
                except DriveUnreachable:
                    verified = False
                except DriveError as e:
                    raise await self._guard(user_id, e) from None
                else:
                    if item is None or item.trashed:
                        await self.repos.documents.clear_pointer(user_id, d.id)
                        continue
                    link = item.web_link or link
            out.append(DriveHit(d.id, d.doc_type.value, ptr.name, ptr.path, link, verified))
        return out

    async def fetch_document(self, user_id: str, document_id: str) -> tuple[bytes, str]:
        """Download a filed document into memory to send to THE USER ONLY (sending it anywhere
        else is a separate approved action). Returns (bytes, name). Nothing is written to disk."""
        self._need_enabled()
        doc = await self.repos.documents.get(user_id, document_id)
        ptr = _parse_pointer(doc.pointer_ref) if doc and doc.pointer_kind == POINTER_KIND else None
        if doc is None or ptr is None:
            raise FamilyDriveError("not filed in Drive", code="not_filed")
        try:
            return await self.drive_factory(user_id).download(ptr.id), ptr.name
        except DriveError as e:
            raise await self._guard(user_id, e) from None

    # ------------------------------------------------------------------ sharing (owner approves)
    def _need_sharing(self) -> None:
        self._need_enabled()
        if not self.settings.family_drive_sharing_enabled:
            raise FamilyDriveError("folder sharing is switched off", code="sharing_disabled")

    async def request_share(self, user_id: str, email: str, role: str = "viewer") -> DriveShare:
        """Record that the owner WANTS to share the Friday folder with ``email``. Nothing happens
        at Google until ``approve_share``: the caller shows the e-mail back and asks yes/no."""
        self._need_sharing()
        await self._active_link(user_id)
        addr = (email or "").strip().lower()
        if role not in ROLES or not _EMAIL_RE.match(addr):
            raise FamilyDriveError("bad e-mail or role", code="bad_share")
        conn = await self.repos.google.get(user_id)
        if conn is not None and conn.email and conn.email.strip().lower() == addr:
            raise FamilyDriveError("that is the owner's own account", code="own_account")
        open_ = await self.repos.family_drive.list_shares(user_id, (SHARE_PENDING, SHARE_SHARED))
        for s in open_:
            if s.email.lower() == addr:
                return s
        if sum(1 for s in open_ if s.status == SHARE_PENDING) >= _MAX_PENDING_SHARES:
            raise FamilyDriveError("too many open requests", code="too_many")
        return await self.repos.family_drive.add_share(
            user_id,
            email=addr,
            role=role,
            expires_at=self.clock.now() + timedelta(days=self.settings.family_drive_share_ttl_days),
        )

    async def approve_share(self, user_id: str, share_id: str) -> DriveShare:
        """The owner said yes: give the member access to the root folder (Drive share)."""
        self._need_sharing()
        link = await self._active_link(user_id)
        share = await self.repos.family_drive.get_share(user_id, share_id)  # owner's own only
        if share is None or share.status != SHARE_PENDING:
            raise FamilyDriveError("no such open request", code="unknown_share")
        if share.expires_at < self.clock.now():
            raise FamilyDriveError("request expired", code="expired")
        if not link.root_folder_id:
            raise FamilyDriveError("no folder yet", code="no_folder")
        try:
            pid = await self.drive_factory(user_id).share(
                link.root_folder_id, share.email, share.role
            )
        except DriveError as e:
            raise await self._guard(user_id, e) from None  # stays pending: the owner can retry
        done = await self.repos.family_drive.update_share(
            user_id, share_id, status=SHARE_SHARED, permission_id=pid
        )
        await self.repos.audit.log(
            "drive.shared", user_id=user_id, subject_id=share_id, role=share.role
        )
        assert done is not None
        return done

    async def decline_share(self, user_id: str, share_id: str) -> bool:
        share = await self.repos.family_drive.get_share(user_id, share_id)
        if share is None or share.status != SHARE_PENDING:
            return False
        await self.repos.family_drive.update_share(user_id, share_id, status=SHARE_DECLINED)
        return True

    async def revoke_share(self, user_id: str, share_id: str) -> bool:
        self._need_enabled()
        link = await self._active_link(user_id)
        share = await self.repos.family_drive.get_share(user_id, share_id)
        if share is None or share.status != SHARE_SHARED:
            return False
        if share.permission_id and link.root_folder_id:
            try:
                await self.drive_factory(user_id).unshare(link.root_folder_id, share.permission_id)
            except DriveError as e:
                raise await self._guard(user_id, e) from None
        await self.repos.family_drive.update_share(user_id, share_id, status=SHARE_REVOKED)
        return True

    async def list_shares(self, user_id: str) -> list[DriveShare]:
        return await self.repos.family_drive.list_shares(user_id)

    # ------------------------------------------------------------------ disconnect
    async def disconnect(self, user_id: str, *, trash_root: bool = False) -> DisconnectResult:
        """Delete everything we keep about the user's Drive: link, folder cache, share requests and
        the pointers (with their minimal fields) of documents filed there. Works with the switch
        off, and even when Drive is unreachable. The user's FILES are theirs and are not deleted;
        moving the Friday folder to Drive's trash is a separate, explicit ``trash_root=True``.
        The Google token is untouched here (Calendar may still use it): ``/google/disconnect``
        revokes it and also clears this data."""
        trashed = False
        link = await self.repos.family_drive.get_link(user_id)
        if trash_root and link is not None and link.root_folder_id:
            try:
                await self.drive_factory(user_id).trash(link.root_folder_id)
                trashed = True
            except DriveError:
                log.warning("family drive root not trashed user=%s", user_id)
        c = await self.repos.family_drive.delete_all(user_id)
        await self.repos.audit.log("drive.disconnected", user_id=user_id, pointers=c["pointers"])
        return DisconnectResult(c["pointers"], c["folders"], c["shares"], c["links"], trashed)


__all__ = [
    "DisconnectResult",
    "DriveHit",
    "FamilyDrive",
    "FamilyDriveError",
    "FiledDocument",
    "LinkInfo",
]
