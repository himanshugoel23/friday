"""Watch tokens: short-lived, unguessable handles that let the founder SEE a browser run.

The token is the only credential in the URL (24 random bytes). Entries expire and can be revoked.
STUB for later: the same page is meant to become the takeover view for login (user types their own
OTP into a streamed browser). That is deliberately NOT built; see ``TakeoverHook`` below.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from friday.connectors.recorder import StepRecorder


@dataclass
class WatchEntry:
    task_id: str
    recorder: StepRecorder
    expires_at: float
    trace_path: str | None = None
    revoked: bool = False
    extra: dict = field(default_factory=dict)


class TakeoverHook(Protocol):  # pragma: no cover - placeholder, intentionally unimplemented
    """Future: forward the viewer's clicks / keystrokes to the worker's page so the USER can log
    in themselves on the watch page. Not built; no input is accepted by the watch page today."""

    async def send_input(self, token: str, event: dict) -> None: ...


class WatchRegistry:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._entries: dict[str, WatchEntry] = {}

    def create(self, task_id: str, recorder: StepRecorder, ttl_seconds: float = 1800.0) -> str:
        token = secrets.token_urlsafe(24)
        self._entries[token] = WatchEntry(task_id, recorder, self._clock() + ttl_seconds)
        return token

    def get(self, token: str) -> WatchEntry | None:
        entry = self._entries.get(token)
        if entry is None:
            return None
        if entry.revoked or self._clock() >= entry.expires_at:
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
