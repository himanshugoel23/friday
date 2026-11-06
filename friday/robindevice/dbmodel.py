# ruff: noqa: E501
"""Tables and the DB-backed store of the Robin device side (migration 0020_robin_device).

``robin_device_states``: one row per parent. ``data`` is encrypted JSON (AES-GCM, AAD ``table.column``) holding
the whole ``ParentState`` (device record, events, prompts, fired ranks, shadow clock, counters, trusted-number
hashes, audit of what the child was told). ``token_hash`` is the SHA-256 of the device token, never the token.
``robin_device_codes``: pairing codes as a keyed hash with an expiry (single use).
Never stored: message text, contact names, digits, audio. ``parent_id`` is the family member id; T03 adds the
erase and retention hooks.

``DbDeviceStore`` keeps the loaded states in memory (the service and the engine mutate them in place) and
writes a state back with ``save`` after every operation, only when its serialised form changed. One process
owns the cache: a second process sees changes at ``refresh`` (used by ``sweep``) or by token lookup.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import BigInteger, Integer, String, delete, select, update
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.crypto import EncryptedJSON, get_field_cipher
from friday.core.logging import get_logger
from friday.db.base import Base, IdMixin, TimestampMixin
from friday.robindevice.store import ParentState, sha256_hex, state_from_dict, state_to_dict

log = get_logger(__name__)


class RobinDeviceStateRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_device_states"

    parent_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON("robin_device_states.data"), nullable=False)


class RobinDeviceCodeRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "robin_device_codes"

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    parent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expires_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


def _code_hash(code: str) -> str:
    """Keyed hash (the 8-character code is short, so a plain hash would be guessable from a leaked row)."""
    try:
        return get_field_cipher().blind_index(code, label="robin_device_code")
    except Exception:  # noqa: BLE001 - no cipher configured: still hashed, never plain
        return sha256_hex("robin_device_code:" + code)


class DbDeviceStore:
    def __init__(self, db) -> None:  # noqa: ANN001 - friday.db.session.Database
        self.db = db
        self._parents: dict[str, ParentState] = {}
        self._by_token: dict[str, str] = {}
        self._snap: dict[str, str] = {}  # parent_id -> last saved serialised form
        self._ver: dict[str, int] = {}  # parent_id -> row version we hold
        self._dirty: set[str] = set()
        self._loaded = False
        self._load_lock = asyncio.Lock()

    # --- loading
    async def ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            async with self.db.session() as s:
                rows = (await s.execute(select(RobinDeviceStateRow))).scalars().all()
            for r in rows:
                self._adopt(r)
            self._loaded = True

    def _adopt(self, r: RobinDeviceStateRow) -> ParentState:
        st = state_from_dict(r.parent_id, dict(r.data or {}))
        old = self._parents.get(r.parent_id)
        if old is not None and old.device is not None:
            self._by_token.pop(old.device.token_hash, None)
        self._parents[r.parent_id] = st
        self._snap[r.parent_id] = self._dump(st)
        self._ver[r.parent_id] = int(r.version)
        if st.device is not None:
            self._by_token[st.device.token_hash] = r.parent_id
        self._dirty.discard(r.parent_id)
        return st

    @staticmethod
    def _dump(st: ParentState) -> str:
        return json.dumps(state_to_dict(st), sort_keys=True, separators=(",", ":"), default=str)

    def _need_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("device store not loaded yet (await ensure_loaded() first)")

    # --- parents (sync reads of the loaded cache)
    def state(self, parent_id: str) -> ParentState:
        self._need_loaded()
        st = self._parents.get(parent_id)
        if st is None:
            st = self._parents[parent_id] = ParentState(parent_id)
            self._dirty.add(parent_id)
        return st

    def peek(self, parent_id: str) -> ParentState | None:
        return self._parents.get(parent_id)

    def parent_ids(self) -> list[str]:
        return list(self._parents)

    def touch(self, parent_id: str) -> None:
        """Mark a state changed by a sync caller (``set_policy``); written by the next ``save``/``save_dirty``."""
        self._dirty.add(parent_id)

    # --- tokens
    def bind_token(self, parent_id: str, token_hash: str) -> None:
        self._by_token[token_hash] = parent_id

    def unbind_token(self, token_hash: str) -> None:
        self._by_token.pop(token_hash, None)

    async def parent_for_token(self, token: str) -> ParentState | None:
        await self.ensure_loaded()
        th = sha256_hex(token)
        pid = self._by_token.get(th)
        if pid is None:  # paired by another process since we loaded
            async with self.db.session() as s:
                row = (await s.execute(select(RobinDeviceStateRow).where(RobinDeviceStateRow.token_hash == th))).scalars().first()
            if row is None:
                return None
            st = self._parents.get(row.parent_id)
            if st is None or self._ver.get(row.parent_id) != int(row.version):
                st = self._adopt(row)
            pid = row.parent_id
            self._by_token[th] = pid
        return self._parents.get(pid)

    # --- pairing codes
    async def put_code(self, parent_id: str, code: str, expires_ms: int) -> None:
        async with self.db.session() as s:
            await s.execute(delete(RobinDeviceCodeRow).where(RobinDeviceCodeRow.parent_id == parent_id))  # one live code per parent
            s.add(RobinDeviceCodeRow(code_hash=_code_hash(code), parent_id=parent_id, expires_ms=int(expires_ms)))

    async def take_code(self, code: str, now_ms: int) -> str | None:
        ch = _code_hash(code)
        async with self.db.session() as s:
            row = (await s.execute(select(RobinDeviceCodeRow).where(RobinDeviceCodeRow.code_hash == ch))).scalars().first()
            if row is None:
                return None
            res = await s.execute(delete(RobinDeviceCodeRow).where(RobinDeviceCodeRow.id == row.id))
            if int(res.rowcount or 0) != 1:  # another process took it first: single use
                return None
            pid, exp = row.parent_id, int(row.expires_ms)
        return pid if exp >= now_ms else None

    # --- persistence
    async def save(self, parent_id: str) -> None:
        st = self._parents.get(parent_id)
        if st is None:
            return
        blob = self._dump(st)
        if blob == self._snap.get(parent_id) and parent_id not in self._dirty:
            return
        th = st.device.token_hash if st.device else None
        data = state_to_dict(st)
        async with self.db.session() as s:
            row = (await s.execute(select(RobinDeviceStateRow).where(RobinDeviceStateRow.parent_id == parent_id))).scalars().first()
            if row is None:
                s.add(RobinDeviceStateRow(parent_id=parent_id, token_hash=th, version=1, data=data))
                self._ver[parent_id] = 1
            else:
                newv = int(row.version) + 1
                await s.execute(update(RobinDeviceStateRow).where(RobinDeviceStateRow.id == row.id).values(token_hash=th, version=newv, data=data))
                self._ver[parent_id] = newv
        self._snap[parent_id] = blob
        self._dirty.discard(parent_id)

    async def save_dirty(self) -> None:
        for pid in list(self._parents):
            await self.save(pid)

    async def refresh(self, parent_id: str) -> ParentState | None:
        """Re-read a parent from the DB when another process saved a newer version (our unsaved changes win)."""
        await self.ensure_loaded()
        async with self.db.session() as s:
            row = (await s.execute(select(RobinDeviceStateRow).where(RobinDeviceStateRow.parent_id == parent_id))).scalars().first()
        if row is None:
            return self._parents.get(parent_id)
        if self._ver.get(parent_id) == int(row.version) or parent_id in self._dirty:
            return self._parents.get(parent_id)
        return self._adopt(row)

    async def drop(self, parent_id: str) -> None:
        st = self._parents.pop(parent_id, None)
        if st and st.device:
            self._by_token.pop(st.device.token_hash, None)
        self._snap.pop(parent_id, None)
        self._ver.pop(parent_id, None)
        self._dirty.discard(parent_id)
        async with self.db.session() as s:
            await s.execute(delete(RobinDeviceStateRow).where(RobinDeviceStateRow.parent_id == parent_id))
            await s.execute(delete(RobinDeviceCodeRow).where(RobinDeviceCodeRow.parent_id == parent_id))
