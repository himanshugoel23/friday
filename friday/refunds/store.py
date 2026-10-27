# ruff: noqa: E501
"""In-memory refund store (tests, simulator). Same surface as ``db.repositories.refunds.RefundRepo``.
Every method takes the ``user_id`` and filters by it."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.refunds.models import (
    OPEN_STATES,
    Origin,
    RefundCase,
    RefundEvent,
    RefundEvidence,
    RefundNudge,
    RefundState,
)


def _cp(x):  # noqa: ANN001, ANN202
    return x.model_copy(deep=True)


class MemoryRefundStore:
    def __init__(self) -> None:
        self.cases: dict[str, RefundCase] = {}
        self.events: list[RefundEvent] = []
        self.evidence: dict[str, RefundEvidence] = {}
        self.nudges: dict[tuple[str, str], RefundNudge] = {}

    # ------------------------------------------------------------------ cases
    async def save_case(self, case: RefundCase) -> None:
        old = self.cases.get(case.id)
        if old is not None and old.user_id != case.user_id:
            raise PermissionError("case belongs to another user")
        self.cases[case.id] = _cp(case)

    async def get_case(self, user_id: str, case_id: str) -> RefundCase | None:
        c = self.cases.get(case_id)
        return _cp(c) if c and c.user_id == user_id else None

    async def list_cases(
        self, user_id: str, states: tuple[RefundState, ...] | None = None
    ) -> list[RefundCase]:
        rows = [
            c
            for c in self.cases.values()
            if c.user_id == user_id and (states is None or c.state in states)
        ]
        return [_cp(c) for c in sorted(rows, key=lambda c: (c.created_at, c.id))]

    async def find_by_origin(
        self, user_id: str, origin: Origin, origin_ref: str
    ) -> RefundCase | None:
        for c in self.cases.values():
            if c.user_id == user_id and c.origin == origin and c.origin_ref == origin_ref:
                return _cp(c)
        return None

    async def users_with_open_cases(self) -> list[str]:
        return sorted({c.user_id for c in self.cases.values() if c.state in OPEN_STATES})

    # ------------------------------------------------------------------ events
    async def add_event(self, event: RefundEvent) -> None:
        self.events.append(_cp(event))

    async def list_events(self, user_id: str, case_id: str) -> list[RefundEvent]:
        return [_cp(e) for e in self.events if e.user_id == user_id and e.case_id == case_id]

    # ------------------------------------------------------------------ evidence
    async def add_evidence(self, ev: RefundEvidence) -> None:
        c = self.cases.get(ev.case_id)
        if c is None or c.user_id != ev.user_id:
            raise PermissionError("evidence for a case of another user")
        self.evidence[ev.id] = _cp(ev)

    async def list_evidence(self, user_id: str, case_id: str) -> list[RefundEvidence]:
        rows = [e for e in self.evidence.values() if e.user_id == user_id and e.case_id == case_id]
        return [_cp(e) for e in sorted(rows, key=lambda e: (e.captured_at, e.id))]

    # ------------------------------------------------------------------ nudges
    async def add_nudge(self, nudge: RefundNudge) -> bool:
        k = (nudge.user_id, nudge.key)
        if k in self.nudges:
            return False
        self.nudges[k] = _cp(nudge)
        return True

    async def list_nudges(self, user_id: str, case_id: str) -> list[RefundNudge]:
        rows = [n for n in self.nudges.values() if n.user_id == user_id and n.case_id == case_id]
        return [_cp(n) for n in sorted(rows, key=lambda n: n.sent_at)]

    async def count_sent_since(self, user_id: str, since: datetime) -> int:
        return sum(
            1
            for n in self.nudges.values()
            if n.user_id == user_id and n.status == "sent" and n.sent_at >= since
        )

    # ------------------------------------------------------------------ retention
    def _drop(self, case_id: str) -> None:
        self.cases.pop(case_id, None)
        self.events = [e for e in self.events if e.case_id != case_id]
        for k in [k for k, v in self.evidence.items() if v.case_id == case_id]:
            del self.evidence[k]
        for k in [k for k, v in self.nudges.items() if v.case_id == case_id]:
            del self.nudges[k]

    async def expire(self, now: datetime, retention_days: int) -> int:
        """Delete closed cases closed more than ``retention_days`` ago, with everything under them."""
        cutoff = now - timedelta(days=retention_days)
        gone = [
            c.id
            for c in self.cases.values()
            if c.state == RefundState.CLOSED and c.state_changed_at < cutoff
        ]
        for cid in gone:
            self._drop(cid)
        return len(gone)

    async def purge_user(self, user_id: str) -> int:
        ids = [c.id for c in self.cases.values() if c.user_id == user_id]
        for cid in ids:
            self._drop(cid)
        return len(ids)
