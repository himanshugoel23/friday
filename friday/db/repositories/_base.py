"""Shared helpers for repositories: base class, row<->model copying, crypto."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import BaseModel

from friday.core.clock import Clock, SystemClock
from friday.db.session import Database

M = TypeVar("M", bound=BaseModel)


class Repo:
    """Every repository holds the Database and a Clock (for updated_at stamps)."""

    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock: Clock = clock or SystemClock()

    def now(self) -> datetime:
        return self.clock.now()


def plain(value: Any) -> Any:
    """Enum -> its value; everything else unchanged."""
    if isinstance(value, Enum):
        return value.value
    return value


def dump_json(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump(mode="json")


def dump_json_list(models: list[BaseModel]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in models]


def columns(row_cls: type) -> set[str]:
    return {c.key for c in row_cls.__table__.columns}  # type: ignore[attr-defined]


def copy_simple(model: BaseModel, row_cls: type, *, skip: set[str] = frozenset()) -> dict[str, Any]:
    """Model fields that are plain scalar columns of ``row_cls`` (enums as values)."""
    cols = columns(row_cls)
    out: dict[str, Any] = {}
    for name in type(model).model_fields:
        if name in cols and name not in skip:
            out[name] = plain(getattr(model, name))
    return out


def row_dict(row: Any, *, skip: set[str] = frozenset()) -> dict[str, Any]:
    return {k: getattr(row, k) for k in columns(type(row)) if k not in skip}


def phone_index(phone: str) -> str:
    """Blind index (HMAC-SHA256, index key) for equality lookups on encrypted phones."""
    from friday.core.crypto import get_field_cipher

    return get_field_cipher().blind_index(phone, label="phone")


def _hkdf(secret: str, label: str) -> bytes:
    """HKDF-SHA256 (RFC 5869) -> 32 bytes, purpose-labelled (SECURITY-13)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"friday-kdf-v1", info=label.encode()
    ).derive(secret.encode())


def _legacy_key(secret: str) -> bytes:
    """Wave-1 derivation (bare SHA-256); read-only so old rows stay readable."""
    return hashlib.sha256(("friday-identifiers:" + secret).encode()).digest()


class SecretBox:
    """Symmetric encryption for identifier values at rest (Fernet).

    SECURITY-13: keys are HKDF-derived with a purpose label; ``previous`` secrets (and
    the wave-1 SHA-256 derivation) stay readable via ``MultiFernet``; ``rotate`` re-
    encrypts a token under the current key. Never log plaintext or ciphertext."""

    LABEL = "identifiers"

    def __init__(self, secret: str, previous: Sequence[str] = ()) -> None:
        keys = [_hkdf(secret, self.LABEL)]
        keys += [_hkdf(p, self.LABEL) for p in previous]
        keys += [_legacy_key(secret)] + [_legacy_key(p) for p in previous]
        self._fernet = MultiFernet([Fernet(base64.urlsafe_b64encode(k)) for k in keys])
        self._current = Fernet(base64.urlsafe_b64encode(keys[0]))

    def encrypt(self, plaintext: str) -> str:
        return self._current.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:  # wrong key / tampered
            raise ValueError("identifier could not be decrypted (secret key changed?)") from e

    def needs_rotation(self, token: str) -> bool:
        try:
            self._current.decrypt(token.encode())
        except InvalidToken:
            return True
        return False

    def rotate(self, token: str) -> str:
        try:
            return self._fernet.rotate(token.encode()).decode()
        except InvalidToken as e:
            raise ValueError("identifier could not be decrypted (secret key changed?)") from e
