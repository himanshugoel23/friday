# ruff: noqa: E501
"""C6: append-only, hash-chained audit log of every staff action.

Entry = (seq, at, staff_id, action, target_id, counts, prev_hash, hash). ``counts`` holds small integers only and ``target_id`` an id: there
is no way to put message text, a name or a number in an entry (the writer refuses). ``hash`` = SHA-256 over the canonical form of the entry
including ``prev_hash``, so editing, deleting or re-ordering any past entry breaks every later hash (``verify`` names the first bad seq).
The store has no update or delete for audit rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

GENESIS = "0" * 64
ACTIONS = frozenset({
    "login", "login_failed", "logout", "session_expired", "denied",
    "queue_view", "request_view", "claim", "release", "assign", "note", "proof", "done", "escalate", "waiting_user", "cancel", "pay_link",
    "contact_parent", "contact_child", "contact_end", "contact_refused",
    "handoff_received", "desk_paged", "desk_ack", "desk_no_answer", "human_joined", "hand_back", "false_alarm", "incident_close", "review",
    "roster_set", "audit_view", "export_denied", "intake", "child_yes",
})
_ID = re.compile(r"[A-Za-z0-9_.:-]{0,48}")
_KEY = re.compile(r"[a-z][a-z0-9_]{0,23}")


class AuditRefused(ValueError):
    pass


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: datetime
    staff_id: str
    action: str
    target_id: str
    counts: dict[str, int]
    prev_hash: str
    hash: str


def _canonical(seq: int, at: datetime, staff_id: str, action: str, target_id: str, counts: dict[str, int], prev_hash: str) -> str:
    body: dict[str, Any] = {"seq": seq, "at": at.isoformat(), "staff": staff_id, "action": action, "target": target_id, "counts": dict(sorted(counts.items())), "prev": prev_hash}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def compute_hash(seq: int, at: datetime, staff_id: str, action: str, target_id: str, counts: dict[str, int], prev_hash: str) -> str:
    return hashlib.sha256(_canonical(seq, at, staff_id, action, target_id, counts, prev_hash).encode()).hexdigest()


class AuditLog:
    def __init__(self, store, clock) -> None:  # noqa: ANN001 - ConciergeStore, friday.core.clock.Clock
        self.store, self.clock = store, clock
        self._lock = asyncio.Lock()

    async def record(self, staff_id: str, action: str, target_id: str = "", **counts: int) -> AuditEntry:
        if action not in ACTIONS:
            raise AuditRefused(f"unknown audit action {action!r}")
        if not _ID.fullmatch(staff_id or "") or not _ID.fullmatch(target_id or ""):
            raise AuditRefused("staff_id and target_id must be plain ids")
        for k, v in counts.items():
            if not _KEY.fullmatch(k) or isinstance(v, bool) or not isinstance(v, int):
                raise AuditRefused("counts must be small integers under plain keys (no text)")
        async with self._lock:
            last = await self.store.audit_last()
            seq = (last.seq + 1) if last else 1
            prev = last.hash if last else GENESIS
            at = self.clock.now()
            e = AuditEntry(seq, at, staff_id, action, target_id, dict(counts), prev, compute_hash(seq, at, staff_id, action, target_id, dict(counts), prev))
            await self.store.audit_append(e)
            return e

    async def entries(self, *, after_seq: int = 0, limit: int = 200) -> list[AuditEntry]:
        return [e for e in await self.store.audit_all() if e.seq > after_seq][:limit]

    async def verify(self) -> int | None:
        """None when the whole chain is intact; else the first seq whose hash or link does not match."""
        prev, expect = GENESIS, 1
        for e in await self.store.audit_all():
            if e.seq != expect or e.prev_hash != prev or e.hash != compute_hash(e.seq, e.at, e.staff_id, e.action, e.target_id, e.counts, e.prev_hash):
                return e.seq
            prev, expect = e.hash, expect + 1
        return None
