"""Per-task audit log. Records WHAT happened (event, task, user, site, host, counts), never typed
values, cookies, codes or page content. Detail dicts go through ``scrub`` (sensitive keys are
dropped, secret-looking text is redacted) and strings are length-capped."""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
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


class JsonlAuditSink:
    """Durable sink for ``AuditLog(sink=...)`` (EM review A4): one scrubbed JSON object per line in
    a 0600 file (keep ``var/`` out of git). Entries are already scrubbed; a write error never breaks
    a task (it is swallowed, the in-memory log still has the entry)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def __call__(self, entry: dict[str, Any]) -> None:
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
        except OSError:
            pass
