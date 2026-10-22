"""Append-only audit log for tool calls. Arguments are scrubbed and hashed, results are status only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from friday.connectors.scrub import scrub


@dataclass(frozen=True)
class AuditEntry:
    ts: datetime
    user_id: str
    task_id: str
    tool: str  # "browser.act@1"
    level: str
    decision: str  # allow | deny | ask | killed | invalid | error
    reason: str
    args_hash: str
    args_preview: str  # scrubbed, truncated
    result_status: str  # ok | error | not_run
    cost_paise: int = 0


def args_hash(args: dict[str, Any]) -> str:
    raw = json.dumps(scrub(args), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class AuditLog:
    """In-memory, append-only. A DB-backed sink can subclass ``_write``."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(self, *, user_id: str, task_id: str, tool: str, level: str, decision: str,
               reason: str, args: dict[str, Any], result_status: str, cost_paise: int = 0) -> AuditEntry:
        preview = json.dumps(scrub(args), sort_keys=True, default=str)[:300]
        e = AuditEntry(datetime.now(UTC), user_id, task_id, tool, level, decision,
                       scrub(reason) if isinstance(reason, str) else "", args_hash(args), preview,
                       result_status, cost_paise)
        self._write(e)
        return e

    def _write(self, e: AuditEntry) -> None:
        self._entries.append(e)

    def entries(self, user_id: str | None = None) -> list[AuditEntry]:
        return [e for e in self._entries if user_id is None or e.user_id == user_id]
