"""Call memory (BRIEF E.30): which Friday caller-ID called which business number, for
which task/user, when, and the outcome - plus inbound/missed calls and business
messages. Caller-IDs are sticky per business so call-backs route back reliably.

Persistence: uses ``repos.call_memory`` when the bundle provides it (proposed in
docs/CORE_CHANGES.md: ``add(record)``, ``for_phone(phone_key, since)``,
``sticky_caller_id(phone_key)``); otherwise an engine-local in-memory store.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from friday.core.models import CallOutcome, new_id
from friday.discovery.geo import phone_key
from friday.tasks.ports import call_opt

Kind = Literal["outbound", "inbound", "missed", "message"]


class CallRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: Kind
    business_phone: str  # the business side (E.164)
    caller_id: str | None = None  # the Friday number used / dialled
    task_id: str | None = None
    user_id: str | None = None
    business_id: str | None = None
    call_id: str | None = None
    outcome: CallOutcome | None = None
    note: str | None = None
    at: datetime

    @property
    def key(self) -> str:
        return phone_key(self.business_phone)


class CallMemory:
    def __init__(self, *, store: Any = None, caller_ids: list[str] | None = None) -> None:
        self.store = store
        self.pool = [c for c in (caller_ids or []) if c]
        self._records: list[CallRecord] = []
        self._sticky: dict[str, str] = {}

    async def caller_id_for(self, business_phone: str) -> str | None:
        """Sticky: the first Friday number used for a business is reused forever."""
        key = phone_key(business_phone)
        sticky = await call_opt(self.store, "sticky_caller_id", key)
        if sticky:
            return sticky
        if key in self._sticky:
            return self._sticky[key]
        for r in reversed(self._records):
            if r.key == key and r.kind == "outbound" and r.caller_id:
                return r.caller_id
        if not self.pool:
            return None
        idx = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(self.pool)
        self._sticky[key] = self.pool[idx]
        return self.pool[idx]

    async def record(self, record: CallRecord) -> CallRecord:
        self._records.append(record)
        await call_opt(self.store, "add", record)
        return record

    async def for_phone(self, phone: str, *, since: datetime | None = None) -> list[CallRecord]:
        """Newest first."""
        key = phone_key(phone)
        stored = await call_opt(self.store, "for_phone", key, since)
        records = stored if stored is not None else self._records
        out = [r for r in records if r.key == key and (since is None or r.at >= since)]
        return sorted(out, key=lambda r: r.at, reverse=True)

    async def count(self, task_id: str, kind: Kind) -> int:
        return sum(1 for r in self._records if r.task_id == task_id and r.kind == kind)
