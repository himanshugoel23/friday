# ruff: noqa: E501
"""Item 3: per-user invite counter and tokenized share links. Tokens are hashed at rest.

``InviteLedger`` is an in-memory implementation of the store (tests, and the shape a DB table
should follow). The raw token exists only in the link handed to the user; only its SHA-256 is kept.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

DEFAULT_QUOTA = 3
TOKEN_BYTES = 16


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def build_link(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/i/{token}"


@dataclass
class InviteLedger:
    quota: int = DEFAULT_QUOTA
    _issued: dict[str, list[str]] = field(default_factory=dict)  # inviter -> token hashes
    _owner: dict[str, str] = field(default_factory=dict)  # token hash -> inviter
    _used: set[str] = field(default_factory=set)

    def used(self, user_id: str) -> int:
        return sum(1 for h in self._issued.get(user_id, []) if h in self._used)

    def left(self, user_id: str) -> int:
        return max(0, self.quota - len(self._issued.get(user_id, [])))

    def issue(self, user_id: str, base_url: str) -> str | None:
        """A new link, or None when the user has no invites left."""
        if self.left(user_id) <= 0:
            return None
        token = new_token()
        h = hash_token(token)
        self._issued.setdefault(user_id, []).append(h)
        self._owner[h] = user_id
        return build_link(base_url, token)

    def redeem(self, token: str) -> str | None:
        """The inviter's id once per valid token; None for unknown or already used tokens."""
        h = hash_token(token)
        for known, owner in self._owner.items():
            if hmac.compare_digest(known, h) and known not in self._used:
                self._used.add(known)
                return owner
        return None

    def stored_hashes(self) -> list[str]:
        return list(self._owner)
