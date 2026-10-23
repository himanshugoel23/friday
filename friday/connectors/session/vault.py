"""Encrypted storage-state vault: one slot per (user, site), AES-GCM via the field cipher.

* Key: the existing field-key setting (``FRIDAY_FIELD_KEY`` / KMS) through ``FieldCipher``; the
  vault holds no key of its own.
* AAD = ``browser_vault:<user>:<site>``: ciphertext copied into another user's or site's slot
  fails to decrypt (fail closed -> treated as "no saved login").
* Slot ids are blind indexes, so a file listing reveals neither users nor sites.
* Entries expire (default 30 days); ``disconnect`` deletes one site, ``disconnect_user`` all.
* Plaintext (cookies) exists only inside ``load``/``save`` and the browser; it is never logged.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from friday.core.crypto import DecryptionError, FieldCipher, LocalKeyProvider


class VaultStore(Protocol):
    def get(self, slot: str) -> dict[str, Any] | None: ...

    def put(self, slot: str, record: dict[str, Any]) -> None: ...

    def delete(self, slot: str) -> None: ...

    def slots_for_user(self, uid: str) -> list[str]: ...


class InMemoryVaultStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def get(self, slot: str) -> dict[str, Any] | None:
        rec = self.data.get(slot)
        return dict(rec) if rec else None

    def put(self, slot: str, record: dict[str, Any]) -> None:
        self.data[slot] = dict(record)

    def delete(self, slot: str) -> None:
        self.data.pop(slot, None)

    def slots_for_user(self, uid: str) -> list[str]:
        return [s for s, r in self.data.items() if r.get("uid") == uid]


class FileVaultStore:
    """One 0600 JSON file per slot under ``root`` (keep ``var/`` out of git)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _p(self, slot: str) -> Path:
        if not slot.isalnum():
            raise ValueError("bad slot id")
        return self.root / f"{slot}.json"

    def get(self, slot: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._p(slot).read_text())
        except (OSError, ValueError):
            return None

    def put(self, slot: str, record: dict[str, Any]) -> None:
        tmp = self._p(slot).with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        os.replace(tmp, self._p(slot))

    def delete(self, slot: str) -> None:
        with contextlib.suppress(OSError):
            self._p(slot).unlink()

    def slots_for_user(self, uid: str) -> list[str]:
        out = []
        for p in self.root.glob("*.json"):
            rec = self.get(p.stem)
            if rec and rec.get("uid") == uid:
                out.append(p.stem)
        return out


class StorageVault:
    def __init__(self, store: VaultStore, cipher: FieldCipher, *, ttl_days: int = 30,
                 clock: Callable[[], float] = time.time) -> None:
        self._store, self._cipher = store, cipher
        self._ttl = ttl_days * 86400.0
        self._clock = clock

    def _slot(self, user_id: str, site: str) -> str:
        return self._cipher.blind_index(f"{user_id}|{site}", label="browser_vault_slot")[:48]

    def _uid(self, user_id: str) -> str:
        return self._cipher.blind_index(user_id, label="browser_vault_user")[:48]

    @staticmethod
    def _aad(user_id: str, site: str) -> str:
        return f"browser_vault:{user_id}:{site}"

    def save(self, user_id: str, site: str, state: dict[str, Any]) -> None:
        ct = self._cipher.encrypt(json.dumps(state), aad=self._aad(user_id, site))
        self._store.put(self._slot(user_id, site), {
            "ct": ct, "uid": self._uid(user_id), "saved_at": self._clock(),
            "expires_at": self._clock() + self._ttl})

    def load(self, user_id: str, site: str) -> dict[str, Any] | None:
        slot = self._slot(user_id, site)
        rec = self._store.get(slot)
        if rec is None:
            return None
        if self._clock() >= float(rec.get("expires_at", 0)):
            self._store.delete(slot)
            return None
        try:
            return json.loads(self._cipher.decrypt(rec["ct"], aad=self._aad(user_id, site)))
        except (DecryptionError, KeyError, ValueError):
            return None  # tampered / wrong slot: act as logged out, never raise secrets

    def has(self, user_id: str, site: str) -> bool:
        return self.load(user_id, site) is not None

    def disconnect(self, user_id: str, site: str) -> None:
        self._store.delete(self._slot(user_id, site))

    def disconnect_user(self, user_id: str) -> int:
        slots = self._store.slots_for_user(self._uid(user_id))
        for s in slots:
            self._store.delete(s)
        return len(slots)


def cipher_from_settings(core_settings: Any) -> FieldCipher:
    """FieldCipher on the existing field-key setting (dev/local key; live may pass the
    container's KMS-backed cipher to ``StorageVault`` instead)."""
    return FieldCipher(LocalKeyProvider.from_settings(core_settings))
