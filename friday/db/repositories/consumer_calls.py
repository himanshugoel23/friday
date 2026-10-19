"""Database implementations of the consumer-call ports (tables: friday/calls/dbmodel.py).

``ConsumerCallsRepo`` implements ``friday.calls.stores.CallStore``, ``ConsumerContactsRepo``
implements ``friday.calls.contacts.ContactStore`` and ``CallDncRepo`` implements
``friday.calls.dnc.DncStore``. Every read of user data filters by ``user_id``; the do-not-call
table has no user dimension by design. The same contract tests run against the in-memory and
the database versions (tests/calls/test_store_contract.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from friday.calls.contacts import Contact
from friday.calls.dbmodel import (
    CallAttemptRow,
    CallBriefRow,
    CallDncRow,
    CallOutcomeRow,
    CallRequestRow,
    CallStrikeRow,
    ConsumerContactRow,
)
from friday.calls.dnc import DncEntry
from friday.calls.models import CallBrief, CallOutcome, CallRequest, CallStatus
from friday.calls.stores import AttemptRecord, RecordingRecord
from friday.db.repositories._base import Repo


def _hash_of(number: str | None) -> str | None:
    """Keyed hash of a number, using the process-wide field cipher (same as NumberHasher())."""
    from friday.calls.numbers import NumberHasher

    return NumberHasher().hash(number) if number else None


def _to_request(r: CallRequestRow) -> CallRequest:
    return CallRequest(
        id=r.id, user_id=r.user_id, callee_kind=r.callee_kind, purpose=r.purpose,
        purpose_kind=r.purpose_kind, callee_ref=r.callee_ref, callee_name=r.callee_name,
        callee_number=r.callee_number, number_confirmed=r.number_confirmed, company=r.company,
        language=r.language, scheduled_for=r.scheduled_for, parent_id=r.parent_id,
        callback_of=r.callback_of, group_members=list(r.group_members or []),
        raw_text=r.raw_text, source_message_id=r.source_message_id, status=r.status,
        attempts=r.attempts, next_attempt_at=r.next_attempt_at, task_id=r.task_id,
        created_at=r.created_at, updated_at=r.updated_at,
    )  # fmt: skip


def _fill_request(row: CallRequestRow, req: CallRequest) -> None:
    row.user_id, row.callee_kind = req.user_id, req.callee_kind.value
    row.purpose, row.purpose_kind = req.purpose, req.purpose_kind.value
    row.callee_ref, row.callee_name = req.callee_ref, req.callee_name
    row.callee_number = req.callee_number
    row.callee_number_hash = _hash_of(req.callee_number)
    row.number_confirmed, row.company, row.language = (
        req.number_confirmed, req.company, req.language,
    )  # fmt: skip
    row.scheduled_for, row.parent_id, row.callback_of = (
        req.scheduled_for, req.parent_id, req.callback_of,
    )  # fmt: skip
    row.group_members = list(req.group_members)
    row.raw_text, row.source_message_id = req.raw_text, req.source_message_id
    row.idempotency_key = req.idempotency_key
    row.status, row.attempts = req.status.value, req.attempts
    row.next_attempt_at, row.task_id = req.next_attempt_at, req.task_id


class ConsumerCallsRepo(Repo):
    # ------------------------------------------------------------------ requests
    async def create_request(self, req: CallRequest) -> tuple[CallRequest, bool]:
        key = req.idempotency_key
        async with self.db.session() as s:
            found = (
                await s.execute(select(CallRequestRow).where(CallRequestRow.idempotency_key == key))
            ).scalar_one_or_none()
            if found is not None:
                return _to_request(found), False
            row = CallRequestRow(id=req.id)
            _fill_request(row, req)
            row.created_at, row.updated_at = req.created_at, req.updated_at
            s.add(row)
            try:
                await s.flush()
            except IntegrityError:  # a concurrent delivery won the race: return theirs
                await s.rollback()
                async with self.db.session() as s2:
                    other = (
                        await s2.execute(
                            select(CallRequestRow).where(CallRequestRow.idempotency_key == key)
                        )
                    ).scalar_one()
                    return _to_request(other), False
        return req, True

    async def get_request(self, request_id: str) -> CallRequest | None:
        async with self.db.session() as s:
            row = await s.get(CallRequestRow, request_id)
            return _to_request(row) if row else None

    async def save_request(self, req: CallRequest) -> CallRequest:
        async with self.db.session() as s:
            row = await s.get(CallRequestRow, req.id)
            if row is None:
                row = CallRequestRow(id=req.id)
                s.add(row)
            _fill_request(row, req)
            row.updated_at = req.updated_at
        return req

    async def children(self, parent_id: str) -> list[CallRequest]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallRequestRow)
                    .where(CallRequestRow.parent_id == parent_id)
                    .order_by(CallRequestRow.created_at, CallRequestRow.id)
                )
            ).scalars()
            return [_to_request(r) for r in rows]

    async def due(self, now: datetime, limit: int = 50) -> list[CallRequest]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallRequestRow)
                    .where(
                        CallRequestRow.status == CallStatus.SCHEDULED.value,
                        CallRequestRow.next_attempt_at <= now,
                    )
                    .order_by(CallRequestRow.next_attempt_at)
                    .limit(limit)
                )
            ).scalars()
            return [_to_request(r) for r in rows]

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[CallRequest]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallRequestRow)
                    .where(CallRequestRow.user_id == user_id)
                    .order_by(CallRequestRow.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return [_to_request(r) for r in rows]

    async def stale_calling(self, before: datetime) -> list[CallRequest]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallRequestRow).where(
                        CallRequestRow.status == CallStatus.CALLING.value,
                        CallRequestRow.updated_at < before,
                    )
                )
            ).scalars()
            return [_to_request(r) for r in rows]

    # ------------------------------------------------------------------ briefs
    async def save_brief(self, brief: CallBrief) -> CallBrief:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(CallBriefRow).where(CallBriefRow.request_id == brief.request_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = CallBriefRow(request_id=brief.request_id, user_id=brief.user_id)
                s.add(row)
            row.payload = brief.model_dump(mode="json")
            row.content_hash = brief.content_hash()
            row.approved, row.approval_hash = brief.approved, brief.approval_hash
            row.approved_at, row.version = brief.approved_at, brief.version
        return brief

    async def get_brief(self, request_id: str) -> CallBrief | None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(CallBriefRow).where(CallBriefRow.request_id == request_id))
            ).scalar_one_or_none()
            return CallBrief.model_validate(row.payload) if row else None

    # ------------------------------------------------------------------ outcomes / counters
    async def add_outcome(
        self, user_id: str, outcome: CallOutcome, number_hash: str | None
    ) -> None:
        async with self.db.session() as s:
            s.add(
                CallOutcomeRow(
                    request_id=outcome.request_id,
                    user_id=user_id,
                    attempt=outcome.attempt,
                    status=outcome.status.value,
                    payload=outcome.model_dump(mode="json"),
                    number_hash=number_hash,
                    duration_s=outcome.duration_s,
                    started_at=outcome.started_at,
                    recording_ref=outcome.recording_ref,
                    transcript_ref=outcome.transcript_ref,
                )  # fmt: skip
            )

    async def outcomes(self, request_id: str) -> list[CallOutcome]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallOutcomeRow)
                    .where(CallOutcomeRow.request_id == request_id)
                    .order_by(CallOutcomeRow.attempt, CallOutcomeRow.created_at)
                )
            ).scalars()
            out = []
            for r in rows:
                o = CallOutcome.model_validate(r.payload)
                o.recording_ref = r.recording_ref  # the column is the source of truth
                out.append(o)
            return out

    async def record_attempt(self, rec: AttemptRecord) -> None:
        async with self.db.session() as s:
            s.add(
                CallAttemptRow(
                    user_id=rec.user_id,
                    request_id=rec.request_id,
                    number_hash=rec.number_hash,
                    started_at=rec.started_at,
                    duration_s=rec.duration_s,
                )  # fmt: skip
            )

    async def calls_between(self, user_id: str, start: datetime, end: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(CallAttemptRow)
                        .where(
                            CallAttemptRow.user_id == user_id,
                            CallAttemptRow.started_at >= start,
                            CallAttemptRow.started_at < end,
                        )
                    )
                ).scalar_one()
            )

    async def seconds_between(self, user_id: str, start: datetime, end: datetime) -> float:
        async with self.db.session() as s:
            total = (
                await s.execute(
                    select(func.coalesce(func.sum(CallAttemptRow.duration_s), 0.0)).where(
                        CallAttemptRow.user_id == user_id,
                        CallAttemptRow.started_at >= start,
                        CallAttemptRow.started_at < end,
                    )
                )
            ).scalar_one()
            return float(total)

    async def number_calls_since(self, number_hash: str, since: datetime) -> int:
        async with self.db.session() as s:  # across ALL users, by design
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(CallAttemptRow)
                        .where(
                            CallAttemptRow.number_hash == number_hash,
                            CallAttemptRow.started_at >= since,
                        )
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ strikes
    async def add_strike(self, user_id: str, reason: str, at: datetime) -> int:
        async with self.db.session() as s:
            s.add(CallStrikeRow(user_id=user_id, reason=reason[:40], created_at=at))
        return await self.strikes(user_id)

    async def strikes(self, user_id: str) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(CallStrikeRow)
                        .where(CallStrikeRow.user_id == user_id)
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ recordings
    async def recordings(self, user_id: str) -> list[RecordingRecord]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallOutcomeRow).where(
                        CallOutcomeRow.user_id == user_id,
                        CallOutcomeRow.recording_ref.is_not(None),
                    )
                )
            ).scalars()
            return [
                RecordingRecord(r.user_id, r.request_id, r.attempt, r.recording_ref,
                                r.started_at or r.created_at)
                for r in rows
            ]  # fmt: skip

    async def recordings_before(self, cutoff: datetime) -> list[RecordingRecord]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CallOutcomeRow).where(
                        CallOutcomeRow.recording_ref.is_not(None),
                        CallOutcomeRow.started_at < cutoff,
                    )
                )
            ).scalars()
            return [
                RecordingRecord(r.user_id, r.request_id, r.attempt, r.recording_ref, r.started_at)
                for r in rows
            ]  # fmt: skip

    async def clear_recording(self, user_id: str, ref: str) -> bool:
        async with self.db.session() as s:
            # the column is encrypted with a random nonce, so match in Python
            rows = (
                await s.execute(
                    select(CallOutcomeRow).where(
                        CallOutcomeRow.user_id == user_id, CallOutcomeRow.recording_ref.is_not(None)
                    )
                )
            ).scalars()
            done = False
            for r in rows:
                if r.recording_ref == ref:
                    r.recording_ref = None
                    done = True
            return done


# ====================================================================== contacts


def _to_contact(r: ConsumerContactRow) -> Contact:
    return Contact(
        id=r.id, user_id=r.user_id, name=r.name, number=r.number, number_hash=r.number_hash,
        nicknames=list(r.nicknames or []), relationship=r.relationship,
        confirmed_at=r.confirmed_at, created_at=r.created_at,
    )  # fmt: skip


class ConsumerContactsRepo(Repo):
    async def list_for_user(self, user_id: str) -> list[Contact]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ConsumerContactRow).where(ConsumerContactRow.user_id == user_id)
                )
            ).scalars()
            return [_to_contact(r) for r in rows]

    async def get(self, user_id: str, contact_id: str) -> Contact | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ConsumerContactRow).where(
                        ConsumerContactRow.id == contact_id, ConsumerContactRow.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            return _to_contact(row) if row else None

    async def find_by_hash(self, user_id: str, number_hash: str) -> Contact | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ConsumerContactRow).where(
                        ConsumerContactRow.user_id == user_id,
                        ConsumerContactRow.number_hash == number_hash,
                    )
                )
            ).scalar_one_or_none()
            return _to_contact(row) if row else None

    async def save(self, contact: Contact) -> Contact:
        async with self.db.session() as s:
            row = await s.get(ConsumerContactRow, contact.id)
            if row is not None and row.user_id != contact.user_id:
                raise PermissionError("contact belongs to another user")
            if row is None:
                row = ConsumerContactRow(id=contact.id, user_id=contact.user_id)
                row.created_at = contact.created_at
                s.add(row)
            row.name, row.nicknames = contact.name, list(contact.nicknames)
            row.relationship, row.number = contact.relationship, contact.number
            row.number_hash, row.confirmed_at = contact.number_hash, contact.confirmed_at
            row.updated_at = self.now()
        return contact

    async def delete(self, user_id: str, contact_id: str) -> bool:
        async with self.db.session() as s:
            res = await s.execute(
                delete(ConsumerContactRow).where(
                    ConsumerContactRow.id == contact_id, ConsumerContactRow.user_id == user_id
                )
            )
            return bool(res.rowcount)  # type: ignore[attr-defined]


# ====================================================================== do-not-call


class CallDncRepo(Repo):
    async def add(self, entry: DncEntry) -> bool:
        async with self.db.session() as s:
            found = (
                await s.execute(
                    select(CallDncRow).where(CallDncRow.number_hash == entry.number_hash)
                )
            ).scalar_one_or_none()
            if found is not None:
                return False
            s.add(
                CallDncRow(
                    number_hash=entry.number_hash,
                    reason=entry.reason,
                    source=entry.source,
                    created_at=entry.created_at,
                )  # fmt: skip
            )
        return True

    async def get(self, number_hash: str) -> DncEntry | None:
        async with self.db.session() as s:
            r = (
                await s.execute(select(CallDncRow).where(CallDncRow.number_hash == number_hash))
            ).scalar_one_or_none()
            return DncEntry(r.number_hash, r.reason, r.source, r.created_at) if r else None

    async def delete(self, number_hash: str) -> bool:
        async with self.db.session() as s:
            res = await s.execute(delete(CallDncRow).where(CallDncRow.number_hash == number_hash))
            return bool(res.rowcount)  # type: ignore[attr-defined]

    async def count(self) -> int:
        async with self.db.session() as s:
            return int((await s.execute(select(func.count()).select_from(CallDncRow))).scalar_one())


async def purge_user_calls(s: Any, user_id: str) -> dict[str, int]:
    """Erasure of a user's consumer-call data inside an open session (DataPurger calls this).
    The global do-not-call registry is NOT touched: it protects third parties."""
    counts: dict[str, int] = {}
    for table in (
        CallAttemptRow, CallStrikeRow, CallOutcomeRow, CallBriefRow, CallRequestRow,
        ConsumerContactRow,
    ):  # fmt: skip
        res = await s.execute(delete(table).where(table.user_id == user_id))
        counts[table.__tablename__] = int(res.rowcount or 0)
    return counts


__all__ = [
    "CallDncRepo",
    "ConsumerCallsRepo",
    "ConsumerContactsRepo",
    "purge_user_calls",
]
