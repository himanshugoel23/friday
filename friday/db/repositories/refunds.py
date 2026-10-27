"""Refund storage (tables in friday/refunds/dbmodel.py). Every per-user method takes the ``user_id``
and filters by it: one user's cases are never reachable through another user's id. Same surface as
``friday.refunds.store.MemoryRefundStore``."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from friday.db.repositories._base import Repo
from friday.evidence.models import EvidenceKind, EvidenceLevel
from friday.refunds.dbmodel import (
    RefundCaseRow,
    RefundEventRow,
    RefundEvidenceRow,
    RefundNudgeRow,
)
from friday.refunds.models import (
    OPEN_STATES,
    Basis,
    CloseReason,
    Origin,
    Proposal,
    RefundCase,
    RefundEvent,
    RefundEvidence,
    RefundNudge,
    RefundState,
    Source,
)


def _case(r: RefundCaseRow) -> RefundCase:
    return RefundCase(
        id=r.id,
        user_id=r.user_id,
        state=RefundState(r.state),
        origin=Origin(r.origin),
        origin_ref=r.origin_ref,
        vendor_name=r.vendor_name or "",
        amount_expected_paise=r.amount_expected_paise,
        amount_received_paise=r.amount_received_paise,
        promised_date=r.promised_date,
        promised_amount_paise=r.promised_amount_paise,
        paid_with_bank=r.paid_with_bank,
        user_number=r.user_number,
        task_id=r.task_id,
        state_epoch=r.state_epoch,
        state_changed_at=r.state_changed_at,
        closed_reason=CloseReason(r.closed_reason) if r.closed_reason else None,
        closed_basis=Basis(r.closed_basis) if r.closed_basis else None,
        proposal=Proposal.model_validate(r.proposal) if r.proposal else None,
        chase_count=r.chase_count,
        muted=r.muted,
        note=r.note,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _evidence(r: RefundEvidenceRow) -> RefundEvidence:
    return RefundEvidence(
        id=r.id,
        user_id=r.user_id,
        case_id=r.case_id,
        kind=EvidenceKind(r.kind),
        level=EvidenceLevel(r.level),
        summary=r.summary or "",
        payload=dict(r.payload or {}),
        amount_paise=r.amount_paise,
        sha256=r.sha256,
        proof_item_id=r.proof_item_id,
        captured_at=r.captured_at,
    )


def _nudge(r: RefundNudgeRow) -> RefundNudge:
    return RefundNudge(
        id=r.id,
        user_id=r.user_id,
        case_id=r.case_id,
        key=r.key,
        stage=r.stage,
        status=r.status,
        text=r.text,
        sent_at=r.sent_at,
    )


class RefundRepo(Repo):
    # ------------------------------------------------------------------ cases
    async def save_case(self, case: RefundCase) -> None:
        async with self.db.session() as s:
            row = await s.get(RefundCaseRow, case.id)
            if row is not None and row.user_id != case.user_id:
                raise PermissionError("case belongs to another user")
            if row is None:
                row = RefundCaseRow(id=case.id, user_id=case.user_id, created_at=case.created_at)
                s.add(row)
            row.state, row.origin, row.origin_ref = (
                case.state.value,
                case.origin.value,
                case.origin_ref,
            )
            row.vendor_name = case.vendor_name
            row.amount_expected_paise = case.amount_expected_paise
            row.amount_received_paise = case.amount_received_paise
            row.promised_date = case.promised_date
            row.promised_amount_paise = case.promised_amount_paise
            row.paid_with_bank, row.user_number = case.paid_with_bank, case.user_number
            row.task_id, row.state_epoch = case.task_id, case.state_epoch
            row.state_changed_at = case.state_changed_at
            row.closed_reason = case.closed_reason.value if case.closed_reason else None
            row.closed_basis = case.closed_basis.value if case.closed_basis else None
            row.proposal = case.proposal.model_dump(mode="json") if case.proposal else None
            row.chase_count, row.muted, row.note = case.chase_count, case.muted, case.note
            row.updated_at = self.now()

    async def get_case(self, user_id: str, case_id: str) -> RefundCase | None:
        async with self.db.session() as s:
            r = await s.get(RefundCaseRow, case_id)
            return _case(r) if r is not None and r.user_id == user_id else None

    async def list_cases(
        self, user_id: str, states: tuple[RefundState, ...] | None = None
    ) -> list[RefundCase]:
        async with self.db.session() as s:
            q = select(RefundCaseRow).where(RefundCaseRow.user_id == user_id)
            if states is not None:
                q = q.where(RefundCaseRow.state.in_([x.value for x in states]))
            rows = (
                await s.execute(q.order_by(RefundCaseRow.created_at, RefundCaseRow.id))
            ).scalars()
            return [_case(r) for r in rows]

    async def find_by_origin(
        self, user_id: str, origin: Origin, origin_ref: str
    ) -> RefundCase | None:
        async with self.db.session() as s:
            r = (
                (
                    await s.execute(
                        select(RefundCaseRow).where(
                            RefundCaseRow.user_id == user_id,
                            RefundCaseRow.origin == origin.value,
                            RefundCaseRow.origin_ref == origin_ref,
                        )
                    )
                )
                .scalars()
                .first()
            )
            return _case(r) if r is not None else None

    async def users_with_open_cases(self) -> list[str]:
        async with self.db.session() as s:
            rows = await s.execute(
                select(RefundCaseRow.user_id)
                .where(RefundCaseRow.state.in_([x.value for x in OPEN_STATES]))
                .distinct()
            )
            return sorted(rows.scalars())

    # ------------------------------------------------------------------ events
    async def add_event(self, event: RefundEvent) -> None:
        async with self.db.session() as s:
            s.add(
                RefundEventRow(
                    id=event.id,
                    user_id=event.user_id,
                    case_id=event.case_id,
                    from_state=event.from_state.value if event.from_state else None,
                    to_state=event.to_state.value,
                    source=Source(event.source).value,
                    note=event.note,
                    at=event.at,
                )
            )

    async def list_events(self, user_id: str, case_id: str) -> list[RefundEvent]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(RefundEventRow)
                    .where(RefundEventRow.user_id == user_id, RefundEventRow.case_id == case_id)
                    .order_by(RefundEventRow.at)
                )
            ).scalars()
            return [
                RefundEvent(
                    id=r.id,
                    user_id=r.user_id,
                    case_id=r.case_id,
                    from_state=RefundState(r.from_state) if r.from_state else None,
                    to_state=RefundState(r.to_state),
                    source=Source(r.source),
                    note=r.note,
                    at=r.at,
                )
                for r in rows
            ]

    # ------------------------------------------------------------------ evidence
    async def add_evidence(self, e: RefundEvidence) -> None:
        async with self.db.session() as s:
            case = await s.get(RefundCaseRow, e.case_id)
            if case is None or case.user_id != e.user_id:
                raise PermissionError("evidence for a case of another user")
            s.add(
                RefundEvidenceRow(
                    id=e.id,
                    user_id=e.user_id,
                    case_id=e.case_id,
                    kind=e.kind.value,
                    level=e.level.value,
                    summary=e.summary,
                    payload=dict(e.payload),
                    amount_paise=e.amount_paise,
                    sha256=e.sha256,
                    proof_item_id=e.proof_item_id,
                    captured_at=e.captured_at,
                )
            )

    async def list_evidence(self, user_id: str, case_id: str) -> list[RefundEvidence]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(RefundEvidenceRow)
                    .where(
                        RefundEvidenceRow.user_id == user_id, RefundEvidenceRow.case_id == case_id
                    )
                    .order_by(RefundEvidenceRow.captured_at, RefundEvidenceRow.id)
                )
            ).scalars()
            return [_evidence(r) for r in rows]

    # ------------------------------------------------------------------ nudges
    async def add_nudge(self, n: RefundNudge) -> bool:
        async with self.db.session() as s:
            exists = (
                await s.execute(
                    select(RefundNudgeRow.id).where(
                        RefundNudgeRow.user_id == n.user_id, RefundNudgeRow.key == n.key
                    )
                )
            ).first()
            if exists is not None:
                return False
            s.add(
                RefundNudgeRow(
                    id=n.id,
                    user_id=n.user_id,
                    case_id=n.case_id,
                    key=n.key,
                    stage=n.stage,
                    status=n.status,
                    text=n.text,
                    sent_at=n.sent_at,
                )
            )
            return True

    async def list_nudges(self, user_id: str, case_id: str) -> list[RefundNudge]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(RefundNudgeRow)
                    .where(RefundNudgeRow.user_id == user_id, RefundNudgeRow.case_id == case_id)
                    .order_by(RefundNudgeRow.sent_at)
                )
            ).scalars()
            return [_nudge(r) for r in rows]

    async def count_sent_since(self, user_id: str, since: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(RefundNudgeRow)
                        .where(
                            RefundNudgeRow.user_id == user_id,
                            RefundNudgeRow.status == "sent",
                            RefundNudgeRow.sent_at >= since,
                        )
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ retention
    async def _drop(self, s, case_ids: list[str]) -> None:  # noqa: ANN001
        if not case_ids:
            return
        for table in (RefundNudgeRow, RefundEvidenceRow, RefundEventRow):
            await s.execute(delete(table).where(table.case_id.in_(case_ids)))
        await s.execute(delete(RefundCaseRow).where(RefundCaseRow.id.in_(case_ids)))

    async def expire(self, now: datetime, retention_days: int) -> int:
        """Closed cases closed more than ``retention_days`` ago, with everything under them."""
        cutoff = now - timedelta(days=retention_days)
        async with self.db.session() as s:
            ids = list(
                (
                    await s.execute(
                        select(RefundCaseRow.id).where(
                            RefundCaseRow.state == RefundState.CLOSED.value,
                            RefundCaseRow.state_changed_at < cutoff,
                        )
                    )
                ).scalars()
            )
            await self._drop(s, ids)
            return len(ids)

    async def purge_user(self, user_id: str) -> int:
        async with self.db.session() as s:
            ids = list(
                (
                    await s.execute(
                        select(RefundCaseRow.id).where(RefundCaseRow.user_id == user_id)
                    )
                ).scalars()
            )
            await self._drop(s, ids)
            return len(ids)
