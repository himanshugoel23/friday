"""One-time channel for the LOGIN OTP: secure page -> this object -> the browser worker.

The code is held in memory only, per task, single use, short TTL. ``take`` returns it once and
wipes it. It is never logged and never part of repr/str, never sent to a model. (Payment OTPs are
not handled at all: payment ends in a QR / UPI link the user pays in their own app.)
"""

from __future__ import annotations

import time
from collections.abc import Callable


class OneTimeOtpChannel:
    __slots__ = ("_clock", "_ttl", "_codes")

    def __init__(self, ttl_seconds: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._codes: dict[str, tuple[str, float]] = {}

    def submit(self, task_id: str, code: str) -> None:
        code = code.strip().replace(" ", "")
        if not (code.isdigit() and 4 <= len(code) <= 8):
            raise ValueError("a login code is 4 to 8 digits")  # never echo the value
        self._codes[task_id] = (code, self._clock() + self._ttl)

    def take(self, task_id: str) -> str | None:
        """The code once, then it is gone. None when absent, expired or already taken."""
        entry = self._codes.pop(task_id, None)
        if entry is None:
            return None
        code, expires = entry
        return code if self._clock() < expires else None

    def has_pending(self, task_id: str) -> bool:
        entry = self._codes.get(task_id)
        if entry is not None and self._clock() >= entry[1]:
            self._codes.pop(task_id, None)
            return False
        return entry is not None

    def wipe(self, task_id: str) -> None:
        self._codes.pop(task_id, None)

    def __repr__(self) -> str:
        return f"OneTimeOtpChannel(pending={len(self._codes)})"

    __str__ = __repr__
