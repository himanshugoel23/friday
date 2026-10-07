"""Field-level encryption primitives (SECURITY-12, -13, -30). KMS-ready design.

    provider = LocalKeyProvider.from_settings(settings)      # dev / tests
    cipher = FieldCipher(provider)
    token = cipher.encrypt("dad is diabetic", aad="people.notes")
    cipher.decrypt(token, aad="people.notes")               # -> "dad is diabetic"
    cipher.blind_index("+919876543210", label="phone")      # stable HMAC for lookups

Format: ``v1:<key_id>:<b64 nonce>:<b64 ciphertext+tag>`` (AES-256-GCM, 96-bit nonce,
AAD = "<table>.<column>" so a value can't be swapped into another column).

Keys
----
* ``KeyProvider`` hands out 32-byte data keys by id and names the current one, so
  rotation = add a new current key; old ciphertext stays readable by its key id.
* ``LocalKeyProvider``: keys from Settings (``field_key`` or HKDF(secret_key)) - dev only.
* Live (OPS-1): a KMS provider unwraps per-key-id data keys (envelope encryption):
  the DB/env stores only KMS-wrapped DEKs; ``data_key(key_id)`` calls KMS Decrypt once
  and caches in memory. ``KmsKeyProvider`` below is the skeleton (Backend A + Ops).
* Index (blind-index) and PIN-pepper keys are separate from the field key (SECURITY-30).

SQLAlchemy column types ``EncryptedText`` / ``EncryptedJSON`` use the process-wide
cipher installed with ``set_field_cipher()`` (the Container does it at startup).
Decrypt errors fail closed (``DecryptionError``); ciphertext is never logged.

Owner: Engineering Manager (core). Backend A switches the columns (friday/db/tables.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Protocol, runtime_checkable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text, TypeDecorator
from sqlalchemy.engine import Dialect

from friday.core.config import Settings

PREFIX = "v1"


class DecryptionError(ValueError):
    """Ciphertext can't be decrypted (wrong key, tampered, wrong column). Fail closed."""


@runtime_checkable
class KeyProvider(Protocol):
    def current_key_id(self) -> str: ...

    def data_key(self, key_id: str) -> bytes:
        """32-byte AES key for ``key_id``; raises KeyError if unknown."""
        ...

    def index_key(self) -> bytes:
        """HMAC key for blind indexes (separate from data keys)."""
        ...


class LocalKeyProvider:
    """Dev/test keys. ``keys`` maps key_id -> 32 bytes; first is current unless set."""

    def __init__(
        self, keys: dict[str, bytes], *, current: str | None = None, index_key: bytes
    ) -> None:
        if not keys:
            raise ValueError("at least one key required")
        for kid, k in keys.items():
            if len(k) != 32:
                raise ValueError(f"key {kid} must be 32 bytes")
            if ":" in kid:
                raise ValueError("key ids must not contain ':'")
        self._keys = dict(keys)
        self._current = current or next(iter(keys))
        self._index = index_key

    @classmethod
    def from_settings(cls, settings: Settings, *, previous: dict[str, bytes] | None = None):
        material = settings.key_material("field_key")
        key = material if len(material) == 32 else hashlib.sha256(material).digest()
        kid = "local-" + hashlib.sha256(key).hexdigest()[:8]
        keys = {kid: key, **(previous or {})}
        return cls(keys, current=kid, index_key=settings.key_material("index_key"))

    def current_key_id(self) -> str:
        return self._current

    def data_key(self, key_id: str) -> bytes:
        return self._keys[key_id]

    def index_key(self) -> bytes:
        return self._index


class KmsKeyProvider:  # pragma: no cover - skeleton for Backend A + Ops (OPS-1)
    """Envelope encryption: ``wrapped`` maps key_id -> KMS-encrypted DEK (base64).
    ``unwrap`` is the KMS Decrypt call (AWS KMS / GCP KMS in an India region)."""

    def __init__(self, wrapped: dict[str, str], current: str, unwrap, index_key: bytes) -> None:
        self._wrapped, self._current, self._unwrap = wrapped, current, unwrap
        self._cache: dict[str, bytes] = {}
        self._index = index_key

    def current_key_id(self) -> str:
        return self._current

    def data_key(self, key_id: str) -> bytes:
        if key_id not in self._cache:
            self._cache[key_id] = self._unwrap(base64.b64decode(self._wrapped[key_id]))
        return self._cache[key_id]

    def index_key(self) -> bytes:
        return self._index


class FieldCipher:
    def __init__(self, keys: KeyProvider) -> None:
        self.keys = keys

    def encrypt(self, plaintext: str, *, aad: str) -> str:
        kid = self.keys.current_key_id()
        nonce = os.urandom(12)
        ct = AESGCM(self.keys.data_key(kid)).encrypt(nonce, plaintext.encode(), aad.encode())
        b64 = base64.urlsafe_b64encode
        return f"{PREFIX}:{kid}:{b64(nonce).decode()}:{b64(ct).decode()}"

    def decrypt(self, token: str, *, aad: str) -> str:
        try:
            prefix, kid, nonce_b64, ct_b64 = token.split(":", 3)
            if prefix != PREFIX:
                raise ValueError("unknown format")
            key = self.keys.data_key(kid)
            pt = AESGCM(key).decrypt(
                base64.urlsafe_b64decode(nonce_b64), base64.urlsafe_b64decode(ct_b64), aad.encode()
            )
        except Exception as e:  # noqa: BLE001 - fail closed, never echo the token
            raise DecryptionError(f"cannot decrypt {aad}") from e
        return pt.decode()

    @staticmethod
    def is_ciphertext(value: str) -> bool:
        return value.startswith(PREFIX + ":") and value.count(":") >= 3

    def blind_index(self, value: str, *, label: str) -> str:
        """Deterministic HMAC-SHA256 for equality lookups (e.g. phone_hmac)."""
        return hmac.new(self.keys.index_key(), f"{label}:{value}".encode(), "sha256").hexdigest()

    def needs_rotation(self, token: str) -> bool:
        return self.is_ciphertext(token) and token.split(":", 2)[1] != self.keys.current_key_id()


# ------------------------------------------------------------------ process-wide cipher

_CIPHER: FieldCipher | None = None


def set_field_cipher(cipher: FieldCipher | None) -> None:
    global _CIPHER
    _CIPHER = cipher


def get_field_cipher() -> FieldCipher:
    """Installed cipher; in non-live processes falls back to a local dev key."""
    global _CIPHER
    if _CIPHER is None:
        from friday.core.config import get_settings

        settings = get_settings()
        if settings.is_live:
            raise RuntimeError("field cipher not configured (call set_field_cipher at startup)")
        _CIPHER = FieldCipher(LocalKeyProvider.from_settings(settings))
    return _CIPHER


class EncryptedText(TypeDecorator[str]):
    """Text column encrypted with AES-GCM; AAD = ``aad`` (use "<table>.<column>").

    ``allow_plaintext=True`` (default) reads legacy unencrypted rows as-is so columns
    can be switched before a backfill; set False once migrated."""

    impl = Text
    cache_ok = True

    def __init__(self, aad: str, *, allow_plaintext: bool = True) -> None:
        super().__init__()
        self.aad = aad
        self.allow_plaintext = allow_plaintext

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return get_field_cipher().encrypt(self._dump(value), aad=self.aad)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        cipher = get_field_cipher()
        if not cipher.is_ciphertext(value):
            if self.allow_plaintext:
                return self._load(value)
            raise DecryptionError(f"plaintext found in encrypted column {self.aad}")
        return self._load(cipher.decrypt(value, aad=self.aad))

    def _dump(self, value: Any) -> str:
        return str(value)

    def _load(self, text: str) -> Any:
        return text


class EncryptedJSON(EncryptedText):
    """JSON-serialisable value (dict/list/number) encrypted as text."""

    cache_ok = True

    def _dump(self, value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)

    def _load(self, text: str) -> Any:
        return json.loads(text)


def build_local_key_provider(c) -> LocalKeyProvider:  # noqa: ANN001 - Container
    return LocalKeyProvider.from_settings(c.settings)
