"""Evidence storage (tables in friday/evidence/dbmodel.py). Every read takes the ``user_id`` and
filters by it: one user's proof is never reachable through another user's id."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from friday.db.repositories._base import Repo
from friday.evidence.dbmodel import DoneClaimRow, EvidenceItemRow
from friday.evidence.models import (
    ClaimType,
    DoneClaim,
    EvidenceItem,
    EvidenceKind,
    EvidenceLevel,
    ProofStatus,
    Redaction,
)


def _item(r: EvidenceItemRow) -> EvidenceItem:
    return EvidenceItem(
        id=r.id,
        user_id=r.user_id,
        task_id=r.task_id,
        call_id=r.call_id,
        kind=EvidenceKind(r.kind),
        level=EvidenceLevel(r.level),
        summary=r.summary or "",
        payload=dict(r.payload or {}),
        object_key=r.object_key,
        sha256=r.sha256,
        source=r.source,
        captured_at=r.captured_at,
        expires_at=r.expires_at,
        shareable=r.shareable,
        redaction=Redaction(r.redaction),
    )


def _claim(r: DoneClaimRow) -> DoneClaim:
    return DoneClaim(
        id=r.id,
        user_id=r.user_id,
        task_id=r.task_id,
        claim_type=ClaimType(r.claim_type),
        required_level=EvidenceLevel(r.required_level),
        status=ProofStatus(r.status),
        evidence_ids=list(r.evidence_ids or []),
        missing=list(r.missing or []),
        created_at=r.created_at,
    )


class EvidenceRepo(Repo):
    async def add_items(self, items: list[EvidenceItem]) -> None:
        async with self.db.session() as s:
            for i in items:
                s.add(
                    EvidenceItemRow(
                        id=i.id,
                        user_id=i.user_id,
                        task_id=i.task_id,
                        call_id=i.call_id,
                        kind=i.kind.value,
                        level=i.level.value,
                        summary=i.summary or None,
                        payload=i.payload or None,
                        object_key=i.object_key,
                        sha256=i.sha256,
                        source=i.source,
                        captured_at=i.captured_at,
                        expires_at=i.expires_at,
                        shareable=i.shareable,
                        redaction=i.redaction.value,
                    )
                )

    async def list_for_task(self, user_id: str, task_id: str) -> list[EvidenceItem]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(EvidenceItemRow)
                    .where(EvidenceItemRow.user_id == user_id, EvidenceItemRow.task_id == task_id)
                    .order_by(EvidenceItemRow.captured_at)
                )
            ).scalars()
            return [_item(r) for r in rows]

    async def save_claim(self, claim: DoneClaim) -> None:
        async with self.db.session() as s:
            await s.execute(delete(DoneClaimRow).where(DoneClaimRow.task_id == claim.task_id))
            s.add(
                DoneClaimRow(
                    id=claim.id,
                    user_id=claim.user_id,
                    task_id=claim.task_id,
                    claim_type=claim.claim_type.value,
                    required_level=claim.required_level.value,
                    status=claim.status.value,
                    evidence_ids=claim.evidence_ids,
                    missing=claim.missing,
                )
            )

    async def get_claim(self, user_id: str, task_id: str) -> DoneClaim | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(DoneClaimRow).where(
                        DoneClaimRow.user_id == user_id, DoneClaimRow.task_id == task_id
                    )
                )
            ).scalar_one_or_none()
            return _claim(row) if row else None

    async def expire(self, now: datetime) -> tuple[int, list[str]]:
        """Delete items past ``expires_at``. Returns (count, object keys to erase from the store).
        Claims keep their codes (no text) until the task goes."""
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(EvidenceItemRow.id, EvidenceItemRow.object_key).where(
                        EvidenceItemRow.expires_at.is_not(None), EvidenceItemRow.expires_at < now
                    )
                )
            ).all()
            ids = [r.id for r in rows]
            if ids:
                await s.execute(delete(EvidenceItemRow).where(EvidenceItemRow.id.in_(ids)))
            return len(ids), [r.object_key for r in rows if r.object_key]

    async def object_keys(self, user_id: str) -> list[str]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(EvidenceItemRow.object_key).where(
                        EvidenceItemRow.user_id == user_id, EvidenceItemRow.object_key.is_not(None)
                    )
                )
            ).scalars()
            return [k for k in rows if k]
