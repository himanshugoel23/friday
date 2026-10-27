"""One-time reveal store for the ride-start code (OTP-to-start).

The code is read from the page by code (never by a model), kept here in memory and shown to the
user only on a one-time page the user opens with a link. The chat, the Proposal, the result, the
logs and the task state only ever hold the link token, never the code. A token works once and
expires; ``wipe`` drops everything for a task.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable


class OneTimeReveal:
    def __init__(self, ttl_seconds: float = 900.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl, self._clock = ttl_seconds, clock
        self._items: dict[str, tuple[str, str, float]] = {}  # token -> (task_id, code, expiry)

    def put(self, task_id: str, code: str) -> str:
        token = secrets.token_urlsafe(18)
        self._items[token] = (task_id, code, self._clock() + self._ttl)
        return token

    def take(self, token: str) -> str | None:
        """The code, once. A second call, an unknown or an expired token gives None."""
        item = self._items.pop(token, None)
        if item is None or item[2] < self._clock():
            return None
        return item[1]

    def wipe(self, task_id: str) -> None:
        for t in [t for t, v in self._items.items() if v[0] == task_id]:
            del self._items[t]

    def __repr__(self) -> str:
        return f"OneTimeReveal(pending={len(self._items)})"


DEFAULT_REVEAL = OneTimeReveal()
