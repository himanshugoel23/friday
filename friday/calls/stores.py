"""Storage ports for consumer calls plus in-memory implementations (used by tests and by the
simulator). The database implementation is ``friday.db.repositories.consumer_calls`` and passes the
same contract tests (tests/calls/test_store_contract.py).

Per-recipient counters work on the keyed number hash and count across ALL users; everything else
is scoped by ``user_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from friday.calls.models import CallBrief, CallOutcome, CallRequest, CallStatus


@dataclass(frozen=True)
class RecordingRecord:
    user_id: str
    request_id: str
    attempt: int
    ref: str  # object-store URL or key; never shown to anyone but the owner
    created_at: datetime


@dataclass(frozen=True)
class AttemptRecord:
    """One dial attempt, kept for caps and for the per-recipient frequency limit."""

    user_id: str
    request_id: str
    number_hash: str
    started_at: datetime
    duration_s: float


class CallStore(Protocol):
    async def create_request(self, req: CallRequest) -> tuple[CallRequest, bool]:
        """Insert unless a request with the same idempotency key exists: (stored, created)."""
        ...

    async def get_request(self, request_id: str) -> CallRequest | None: ...
    async def save_request(self, req: CallRequest) -> CallRequest: ...
    async def children(self, parent_id: str) -> list[CallRequest]: ...
    async def due(self, now: datetime, limit: int = 50) -> list[CallRequest]: ...
    async def list_for_user(self, user_id: str, limit: int = 50) -> list[CallRequest]: ...
    async def stale_calling(self, before: datetime) -> list[CallRequest]: ...

    async def save_brief(self, brief: CallBrief) -> CallBrief: ...
    async def get_brief(self, request_id: str) -> CallBrief | None: ...

    async def add_outcome(
        self, user_id: str, outcome: CallOutcome, number_hash: str | None
    ) -> None: ...
    async def outcomes(self, request_id: str) -> list[CallOutcome]: ...

    async def record_attempt(self, rec: AttemptRecord) -> None: ...
    async def calls_between(self, user_id: str, start: datetime, end: datetime) -> int: ...
    async def seconds_between(self, user_id: str, start: datetime, end: datetime) -> float: ...
    async def number_calls_since(self, number_hash: str, since: datetime) -> int: ...

    async def add_strike(self, user_id: str, reason: str, at: datetime) -> int: ...
    async def strikes(self, user_id: str) -> int: ...

    async def recordings(self, user_id: str) -> list[RecordingRecord]: ...
    async def recordings_before(self, cutoff: datetime) -> list[RecordingRecord]: ...
    async def clear_recording(self, user_id: str, ref: str) -> bool: ...


class MemoryCallStore:
    def __init__(self) -> None:
        self.requests: dict[str, CallRequest] = {}
        self._by_key: dict[str, str] = {}
        self.briefs: dict[str, CallBrief] = {}
        self._outcomes: dict[str, list[tuple[CallOutcome, str | None, str]]] = {}
        self.attempts: list[AttemptRecord] = []
        self._strikes: dict[str, list[str]] = {}

    async def create_request(self, req: CallRequest) -> tuple[CallRequest, bool]:
        key = req.idempotency_key
        if key in self._by_key:
            return self.requests[self._by_key[key]].model_copy(deep=True), False
        self.requests[req.id] = req.model_copy(deep=True)
        self._by_key[key] = req.id
        return req.model_copy(deep=True), True

    async def get_request(self, request_id: str) -> CallRequest | None:
        r = self.requests.get(request_id)
        return r.model_copy(deep=True) if r else None

    async def save_request(self, req: CallRequest) -> CallRequest:
        self.requests[req.id] = req.model_copy(deep=True)
        return req

    async def children(self, parent_id: str) -> list[CallRequest]:
        return [r.model_copy(deep=True) for r in self.requests.values() if r.parent_id == parent_id]

    async def due(self, now: datetime, limit: int = 50) -> list[CallRequest]:
        rows = [
            r
            for r in self.requests.values()
            if r.status == CallStatus.SCHEDULED and r.next_attempt_at and r.next_attempt_at <= now
        ]
        rows.sort(key=lambda r: r.next_attempt_at)  # type: ignore[arg-type,return-value]
        return [r.model_copy(deep=True) for r in rows[:limit]]

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[CallRequest]:
        rows = [r for r in self.requests.values() if r.user_id == user_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return [r.model_copy(deep=True) for r in rows[:limit]]

    async def stale_calling(self, before: datetime) -> list[CallRequest]:
        return [
            r.model_copy(deep=True)
            for r in self.requests.values()
            if r.status == CallStatus.CALLING and r.updated_at < before
        ]

    async def save_brief(self, brief: CallBrief) -> CallBrief:
        self.briefs[brief.request_id] = brief.model_copy(deep=True)
        return brief

    async def get_brief(self, request_id: str) -> CallBrief | None:
        b = self.briefs.get(request_id)
        return b.model_copy(deep=True) if b else None

    async def add_outcome(
        self, user_id: str, outcome: CallOutcome, number_hash: str | None
    ) -> None:
        self._outcomes.setdefault(outcome.request_id, []).append(
            (outcome.model_copy(deep=True), number_hash, user_id)
        )

    async def outcomes(self, request_id: str) -> list[CallOutcome]:
        return [o.model_copy(deep=True) for o, _, _ in self._outcomes.get(request_id, [])]

    async def record_attempt(self, rec: AttemptRecord) -> None:
        self.attempts.append(rec)

    async def calls_between(self, user_id: str, start: datetime, end: datetime) -> int:
        return sum(1 for a in self.attempts if a.user_id == user_id and start <= a.started_at < end)

    async def seconds_between(self, user_id: str, start: datetime, end: datetime) -> float:
        return sum(
            a.duration_s
            for a in self.attempts
            if a.user_id == user_id and start <= a.started_at < end
        )

    async def number_calls_since(self, number_hash: str, since: datetime) -> int:
        return sum(
            1 for a in self.attempts if a.number_hash == number_hash and a.started_at >= since
        )

    async def add_strike(self, user_id: str, reason: str, at: datetime) -> int:
        self._strikes.setdefault(user_id, []).append(reason)
        return len(self._strikes[user_id])

    async def strikes(self, user_id: str) -> int:
        return len(self._strikes.get(user_id, []))

    async def recordings(self, user_id: str) -> list[RecordingRecord]:
        out = []
        for rid, rows in self._outcomes.items():
            for o, _, uid in rows:
                if uid == user_id and o.recording_ref:
                    at = o.started_at or datetime.min.replace(tzinfo=UTC)
                    out.append(RecordingRecord(uid, rid, o.attempt, o.recording_ref, at))
        return out

    async def recordings_before(self, cutoff: datetime) -> list[RecordingRecord]:
        out = []
        for rid, rows in self._outcomes.items():
            for o, _, uid in rows:
                if o.recording_ref and o.started_at and o.started_at < cutoff:
                    out.append(RecordingRecord(uid, rid, o.attempt, o.recording_ref, o.started_at))
        return out

    async def clear_recording(self, user_id: str, ref: str) -> bool:
        done = False
        for rows in self._outcomes.values():
            for o, _, uid in rows:
                if uid == user_id and o.recording_ref == ref:
                    o.recording_ref = None
                    done = True
        return done
