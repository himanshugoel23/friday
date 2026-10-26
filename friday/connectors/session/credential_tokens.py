"""Links for the one-time "save a login" page. Same rules as the OTP page tokens: 24 random bytes
in the path (the only credential), short life, ONE successful save, burned after a few tries.
The token stores who and which site, never a username or password."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

CRED_LINK_TTL_SECONDS = 600.0
CRED_MAX_ATTEMPTS = 5


@dataclass
class CredentialLink:
    user_id: str
    site: str
    hosts: tuple[str, ...]
    expires_at: float
    attempts: int = 0
    used: bool = False


class CredentialTokenRegistry:
    def __init__(self, clock: Callable[[], float] = time.time,
                 ttl_seconds: float = CRED_LINK_TTL_SECONDS,
                 max_attempts: int = CRED_MAX_ATTEMPTS) -> None:
        self._clock, self._ttl, self.max_attempts = clock, ttl_seconds, max_attempts
        self._entries: dict[str, CredentialLink] = {}

    def create(self, user_id: str, site: str, hosts: tuple[str, ...]) -> str:
        token = secrets.token_urlsafe(24)
        self._entries[token] = CredentialLink(user_id, site, hosts, self._clock() + self._ttl)
        return token

    def get(self, token: str) -> CredentialLink | None:
        e = self._entries.get(token)
        if e is None:
            return None
        if e.used or e.attempts >= self.max_attempts or self._clock() >= e.expires_at:
            self._entries.pop(token, None)
            return None
        return e

    def revoke(self, token: str) -> bool:
        return self._entries.pop(token, None) is not None

    def revoke_user(self, user_id: str) -> int:
        gone = [t for t, e in self._entries.items() if e.user_id == user_id]
        for t in gone:
            self._entries.pop(t, None)
        return len(gone)
