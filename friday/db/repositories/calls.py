"""Call memory (E30) + inbound calls / missed calls / business messages (E31-35).

* ``record_outbound``  - one row per outbound call attempt: Friday caller-ID number,
  business number, task, user, time, outcome (upsert by ``call_id``).
  ``TaskRepo.save_call`` also records it automatically (without the caller ID
  unless ``CallResult`` carries ``from_number``); the engine/voice should call
  ``record_outbound`` with ``friday_number`` once known.
* ``sticky_number``    - the Friday number last used for a business (reuse it).
* ``match``            - inbound caller/sender phone (+ Friday number dialled) ->
  recent call memory: matched (one task) | ambiguous (several open tasks) | unmatched.
* ``record_inbound``   - persist the inbound contact and its match status.

Matching never returns anything for numbers we did not call: unmatched callers
get no user/task details (E33/E34).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import select

from friday.core.models import CallOutcome, new_id
from friday.db.repositories._base import Repo, row_dict
from friday.db.tables import CallMemoryRow, InboundContactRow, TaskRow

DEFAULT_MATCH_WINDOW = timedelta(days=30)


class CallMemory(BaseModel):
    id: str = Field(default_factory=new_id)
    call_id: str | None = None
    task_id: str
    user_id: str
    business_id: str | None = None
    business_phone: str
    friday_number: str | None = None
    direction: str = "outbound"
    outcome: CallOutcome | None = None
    at: datetime


class MatchStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


class InboundKind(StrEnum):
    CALL = "call"  # business called a Friday number and we answered
    MISSED_CALL = "missed_call"  # rang, nobody/nothing answered
    MESSAGE = "message"  # WhatsApp / SMS from a business


class CallbackMatch(BaseModel):
    """Result of matching an inbound business contact to call memory.

    ``task_id``/``user_id`` set only when MATCHED. ``candidates`` holds the
    distinct (most recent per task) memories; for AMBIGUOUS the caller must be
    asked which task this is about. ``completed_only`` = every candidate task is
    terminal (E32: reopen / follow-up task)."""

    status: MatchStatus
    from_phone: str
    friday_number: str | None = None
    business_id: str | None = None
    task_id: str | None = None
    user_id: str | None = None
    candidates: list[CallMemory] = Field(default_factory=list)
    completed_only: bool = False


class InboundContact(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: InboundKind
    channel: str = "voice"
    from_phone: str
    friday_number: str | None = None
    provider_ref: str | None = None
    status: MatchStatus
    business_id: str | None = None
    task_id: str | None = None
    user_id: str | None = None
    candidate_task_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    handled: bool = False
    at: datetime


def _memory(row: CallMemoryRow) -> CallMemory:
    return CallMemory.model_validate(row_dict(row))


def _contact(row: InboundContactRow) -> InboundContact:
    return InboundContact.model_validate(row_dict(row))


class CallMemoryRepo(Repo):
    async def record_outbound(
        self,
        *,
        task_id: str,
        user_id: str,
        business_phone: str,
        friday_number: str | None = None,
        call_id: str | None = None,
        business_id: str | None = None,
        outcome: CallOutcome | None = None,
        at: datetime | None = None,
    ) -> CallMemory:
        """Upsert by ``call_id`` (fields given as None keep their stored value)."""
        async with self.db.session() as s:
            row = None
            if call_id is not None:
                row = (
                    await s.execute(select(CallMemoryRow).where(CallMemoryRow.call_id == call_id))
                ).scalar_one_or_none()
            if row is None:
                row = CallMemoryRow(
                    id=new_id(),
                    call_id=call_id,
                    task_id=task_id,
                    user_id=user_id,
                    business_phone=business_phone,
                    direction="outbound",
                    at=at or self.now(),
                )
                s.add(row)
            row.business_phone = business_phone or row.business_phone
            if friday_number is not None:
                row.friday_number = friday_number
            if business_id is not None:
                row.business_id = business_id
            if outcome is not None:
                row.outcome = outcome.value
            await s.flush()
            return _memory(row)

    async def for_task(self, task_id: str) -> list[CallMemory]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallMemoryRow)
                    .where(CallMemoryRow.task_id == task_id)
                    .order_by(CallMemoryRow.at)
                )
            ).scalars()
            return [_memory(r) for r in rows]

    async def recent_for_phone(
        self, business_phone: str, *, since: datetime | None = None, limit: int = 50
    ) -> list[CallMemory]:
        """Newest first."""
        async with self.db.session() as s:
            q = select(CallMemoryRow).where(CallMemoryRow.business_phone == business_phone)
            if since is not None:
                q = q.where(CallMemoryRow.at >= since)
            rows = (await s.execute(q.order_by(CallMemoryRow.at.desc()).limit(limit))).scalars()
            return [_memory(r) for r in rows]

    async def sticky_number(self, business_phone: str) -> str | None:
        """Friday number most recently used to call this business (E30)."""
        for m in await self.recent_for_phone(business_phone, limit=20):
            if m.friday_number:
                return m.friday_number
        return None

    async def choose_number(self, business_phone: str, pool: Sequence[str]) -> str | None:
        """Sticky number if still in the pool, else a stable hash pick from ``pool``."""
        if not pool:
            return None
        sticky = await self.sticky_number(business_phone)
        if sticky in pool:
            return sticky
        idx = int(hashlib.sha256(business_phone.encode()).hexdigest(), 16) % len(pool)
        return list(pool)[idx]

    async def match(
        self,
        from_phone: str,
        *,
        friday_number: str | None = None,
        window: timedelta = DEFAULT_MATCH_WINDOW,
    ) -> CallbackMatch:
        """Match an inbound call/message from ``from_phone`` to call memory.

        Prefers memories made from the dialled ``friday_number``; among the
        remaining tasks, open tasks win over terminal ones. One task -> MATCHED,
        several open tasks -> AMBIGUOUS, none -> UNMATCHED."""
        since = self.now() - window
        memories = await self.recent_for_phone(from_phone, since=since, limit=100)
        if friday_number:
            same_line = [m for m in memories if m.friday_number == friday_number]
            if same_line:
                memories = same_line
        per_task: dict[str, CallMemory] = {}
        for m in memories:  # newest first -> first seen per task is the latest
            per_task.setdefault(m.task_id, m)
        if not per_task:
            return CallbackMatch(
                status=MatchStatus.UNMATCHED, from_phone=from_phone, friday_number=friday_number
            )
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(TaskRow.id, TaskRow.status).where(TaskRow.id.in_(list(per_task)))
                )
            ).all()
        from friday.core.models import TaskStatus

        status_of = {tid: TaskStatus(st) for tid, st in rows}
        cands = [m for m in per_task.values() if m.task_id in status_of]
        open_ = [m for m in cands if not status_of[m.task_id].is_terminal]
        chosen = open_ or cands
        if not chosen:
            return CallbackMatch(
                status=MatchStatus.UNMATCHED, from_phone=from_phone, friday_number=friday_number
            )
        business_id = next((m.business_id for m in chosen if m.business_id), None)
        base = {
            "from_phone": from_phone,
            "friday_number": friday_number,
            "business_id": business_id,
            "candidates": chosen,
            "completed_only": not open_,
        }
        if len(open_) > 1:
            return CallbackMatch(status=MatchStatus.AMBIGUOUS, **base)
        top = chosen[0]  # newest (only open one, or newest terminal)
        return CallbackMatch(
            status=MatchStatus.MATCHED, task_id=top.task_id, user_id=top.user_id, **base
        )

    async def record_inbound(
        self,
        kind: InboundKind,
        match: CallbackMatch,
        *,
        channel: str = "voice",
        provider_ref: str | None = None,
        note: str | None = None,
        at: datetime | None = None,
    ) -> InboundContact:
        contact = InboundContact(
            kind=kind,
            channel=channel,
            from_phone=match.from_phone,
            friday_number=match.friday_number,
            provider_ref=provider_ref,
            status=match.status,
            business_id=match.business_id,
            task_id=match.task_id,
            user_id=match.user_id,
            candidate_task_ids=[m.task_id for m in match.candidates],
            note=note,
            at=at or self.now(),
        )
        async with self.db.session() as s:
            values = contact.model_dump()
            values |= {"kind": contact.kind.value, "status": contact.status.value}
            s.add(InboundContactRow(**values))
        return contact

    async def mark_handled(self, contact_id: str, *, note: str | None = None) -> bool:
        async with self.db.session() as s:
            row = await s.get(InboundContactRow, contact_id)
            if row is None:
                return False
            row.handled = True
            if note is not None:
                row.note = note
            return True

    async def get_inbound(self, contact_id: str) -> InboundContact | None:
        async with self.db.session() as s:
            row = await s.get(InboundContactRow, contact_id)
            return _contact(row) if row else None

    async def inbound_for_task(self, task_id: str) -> list[InboundContact]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(InboundContactRow)
                    .where(
                        (InboundContactRow.task_id == task_id)
                        | (InboundContactRow.status == MatchStatus.AMBIGUOUS.value)
                    )
                    .order_by(InboundContactRow.at)
                )
            ).scalars()
            return [
                _contact(r)
                for r in rows
                if r.task_id == task_id or task_id in (r.candidate_task_ids or [])
            ]

    async def unhandled_inbound(self, *, kind: InboundKind | None = None) -> list[InboundContact]:
        async with self.db.session() as s:
            q = select(InboundContactRow).where(InboundContactRow.handled.is_(False))
            if kind:
                q = q.where(InboundContactRow.kind == kind.value)
            rows = (await s.execute(q.order_by(InboundContactRow.at))).scalars()
            return [_contact(r) for r in rows]
