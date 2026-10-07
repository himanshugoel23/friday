"""Shared helpers for repositories: base class, row<->model copying, crypto."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from cryptography.fernet import Fernet, InvalidToken
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


class SecretBox:
    """Symmetric encryption for identifier values at rest (Fernet, key derived from
    ``Settings.secret_key``). Never log plaintext or ciphertext."""

    def __init__(self, secret: str) -> None:
        key = hashlib.sha256(("friday-identifiers:" + secret).encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:  # wrong key / tampered
            raise ValueError("identifier could not be decrypted (secret key changed?)") from e
