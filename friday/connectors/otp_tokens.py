"""Tokens for the one-time LOGIN-code page (separate from watch tokens).

A token is 24 random bytes in the URL path (the only credential), valid for a short time, usable
for ONE successful submit, and burned after ``max_attempts`` tries. It stores only the task id and
the last two digits of the phone (to tell the user which number the code was sent to). The code
itself is never stored here: it goes straight into ``OneTimeOtpChannel``.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

OTP_TTL_SECONDS = 600.0  # 10 minutes
OTP_MAX_ATTEMPTS = 5


@dataclass
class OtpTokenEntry:
    task_id: str
    phone_hint: str  # e.g. "..42": last two digits only
    expires_at: float
    attempts: int = 0
    used: bool = False


class OtpTokenRegistry:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = OTP_TTL_SECONDS,
        max_attempts: int = OTP_MAX_ATTEMPTS,
    ) -> None:
        self._clock, self._ttl, self.max_attempts = clock, ttl_seconds, max_attempts
        self._entries: dict[str, OtpTokenEntry] = {}

    def create(self, task_id: str, phone_last2: str = "") -> str:
        token = secrets.token_urlsafe(24)
        hint = f"..{phone_last2[-2:]}" if phone_last2 else ""
        self._entries[token] = OtpTokenEntry(task_id, hint, self._clock() + self._ttl)
        return token

    def get(self, token: str) -> OtpTokenEntry | None:
        """The entry if the token is known, unexpired, unused and not burned; else None."""
        entry = self._entries.get(token)
        if entry is None:
            return None
        if entry.used or entry.attempts >= self.max_attempts or self._clock() >= entry.expires_at:
            self._entries.pop(token, None)
            return None
        return entry

    def revoke(self, token: str) -> bool:
        return self._entries.pop(token, None) is not None

    def revoke_task(self, task_id: str) -> int:
        gone = [t for t, e in self._entries.items() if e.task_id == task_id]
        for t in gone:
            self._entries.pop(t, None)
        return len(gone)
