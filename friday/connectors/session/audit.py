"""Per-task audit log. Records WHAT happened (event, task, user, site, host, counts), never typed
values, cookies, codes or page content. Detail dicts go through ``scrub`` (sensitive keys are
dropped, secret-looking text is redacted) and strings are length-capped."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

from friday.connectors.scrub import scrub

MAX_ENTRIES = 5000


class AuditLog:
    def __init__(self, clock: Callable[[], float] = time.time, max_entries: int = MAX_ENTRIES,
                 sink: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._clock, self._sink = clock, sink
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)

    def record(self, event: str, *, task_id: str = "", user_id: str = "", site: str = "",
               **detail: Any) -> dict[str, Any]:
        clean = scrub(detail)
        clean = {k: (v[:200] if isinstance(v, str) else v) for k, v in clean.items()}
        entry = {"ts": self._clock(), "event": event, "task_id": task_id, "user_id": user_id,
                 "site": site, **clean}
        self._entries.append(entry)
        if self._sink:
            self._sink(entry)
        return entry

    def entries(self, *, task_id: str | None = None, event: str | None = None) -> list[dict]:
        return [e for e in self._entries
                if (task_id is None or e["task_id"] == task_id)
                and (event is None or e["event"] == event)]

    def clear_task(self, task_id: str) -> int:
        keep = [e for e in self._entries if e["task_id"] != task_id]
        gone = len(self._entries) - len(keep)
        self._entries = deque(keep, maxlen=self._entries.maxlen)
        return gone
