"""Facts, account identifiers (encrypted), audit log, cost ledger."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select

from friday.core.clock import Clock
from friday.core.models import AccountIdentifier, AuditEntry, Fact
from friday.db.repositories._base import Repo, SecretBox, copy_simple, row_dict
from friday.db.session import Database
from friday.db.tables import AccountIdentifierRow, AuditRow, CostEntryRow, FactRow


class FactRepo(Repo):
    """Implements ``FactRepository``."""

    async def get(self, fact_id: str) -> Fact | None:
        async with self.db.session() as s:
            row = await s.get(FactRow, fact_id)
            return Fact.model_validate(row_dict(row)) if row else None

    async def list_for_user(self, user_id: str) -> list[Fact]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(FactRow).where(FactRow.user_id == user_id).order_by(FactRow.created_at)
                )
            ).scalars()
            return [Fact.model_validate(row_dict(r)) for r in rows]

    async def upsert(self, fact: Fact) -> Fact:
        """Upsert by id; a new fact with the same (user, key, person) replaces the old one."""
        fact.updated_at = self.now()
        async with self.db.session() as s:
            existing = await s.get(FactRow, fact.id)
            if existing is None:
                q = select(FactRow).where(FactRow.user_id == fact.user_id, FactRow.key == fact.key)
                q = q.where(
                    FactRow.person_id == fact.person_id
                    if fact.person_id
                    else FactRow.person_id.is_(None)
                )
                same_key = (await s.execute(q)).scalars().first()
                if same_key is not None:
                    fact.id = same_key.id
                    fact.created_at = same_key.created_at
            await s.merge(FactRow(**copy_simple(fact, FactRow)))
        return fact

    async def delete(self, fact_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(FactRow, fact_id)
            if row is None:
                return False
            await s.delete(row)
            return True

    async def list_due_between(self, start: date, end: date) -> list[Fact]:
        """All users' facts with ``start <= due_on <= end`` (proactive date nudges)."""
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(FactRow)
                    .where(FactRow.due_on >= start, FactRow.due_on <= end)
                    .order_by(FactRow.due_on)
                )
            ).scalars()
            return [Fact.model_validate(row_dict(r)) for r in rows]


class IdentifierRepo(Repo):
    """Implements ``IdentifierRepository``. Values encrypted at rest with the
    app secret key; only ``last4`` is stored in clear (for masked display)."""

    def __init__(self, db: Database, clock: Clock | None, box: SecretBox) -> None:
        super().__init__(db, clock)
        self._box = box

    def _model(self, row: AccountIdentifierRow) -> AccountIdentifier:
        return AccountIdentifier(
            id=row.id,
            user_id=row.user_id,
            company=row.company,
            label=row.label,
            value=self._box.decrypt(row.value_encrypted),
        )

    async def get(self, identifier_id: str) -> AccountIdentifier | None:
        async with self.db.session() as s:
            row = await s.get(AccountIdentifierRow, identifier_id)
            return self._model(row) if row else None

    async def get_many(self, ids: list[str]) -> list[AccountIdentifier]:
        if not ids:
            return []
        async with self.db.session() as s:
            rows = (
                await s.execute(select(AccountIdentifierRow).where(AccountIdentifierRow.id.in_(ids)))
            ).scalars()
            return [self._model(r) for r in rows]

    async def list_for_user(self, user_id: str) -> list[AccountIdentifier]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(AccountIdentifierRow)
                    .where(AccountIdentifierRow.user_id == user_id)
                    .order_by(AccountIdentifierRow.created_at)
                )
            ).scalars()
            return [self._model(r) for r in rows]

    async def upsert(self, identifier: AccountIdentifier) -> AccountIdentifier:
        now = self.now()
        async with self.db.session() as s:
            existing = await s.get(AccountIdentifierRow, identifier.id)
            await s.merge(
                AccountIdentifierRow(
                    id=identifier.id,
                    user_id=identifier.user_id,
                    company=identifier.company,
                    label=identifier.label,
                    value_encrypted=self._box.encrypt(identifier.value),
                    last4=identifier.value[-4:],
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                )
            )
        return identifier

    async def delete(self, identifier_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(AccountIdentifierRow, identifier_id)
            if row is None:
                return False
            await s.delete(row)
            return True


class AuditRepo(Repo):
    """Append-only action log. Survives "delete everything" (PII scrubbed)."""

    async def add(self, entry: AuditEntry) -> AuditEntry:
        async with self.db.session() as s:
            s.add(AuditRow(**copy_simple(entry, AuditRow)))
        return entry

    async def log(
        self,
        action: str,
        *,
        user_id: str | None,
        actor: str = "friday",
        subject_id: str | None = None,
        **detail: object,
    ) -> AuditEntry:
        return await self.add(
            AuditEntry(
                user_id=user_id,
                actor=actor,  # type: ignore[arg-type]
                action=action,
                subject_id=subject_id,
                detail={k: v for k, v in detail.items() if v is not None},
                at=self.now(),
            )
        )

    async def list_for_user(self, user_id: str, *, limit: int = 200) -> list[AuditEntry]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(AuditRow)
                    .where(AuditRow.user_id == user_id)
                    .order_by(AuditRow.at.desc())
                    .limit(limit)
                )
            ).scalars()
            return [AuditEntry.model_validate(row_dict(r)) for r in rows]

    async def scrub_user(self, user_id: str) -> int:
        """Drop details/subjects of a deleted user's entries (keep the tombstones)."""
        async with self.db.session() as s:
            rows = (await s.execute(select(AuditRow).where(AuditRow.user_id == user_id))).scalars()
            n = 0
            for r in rows:
                r.detail = {}
                r.subject_id = None
                n += 1
            return n


class CostRepo(Repo):
    """Internal cost ledger (INR). Never surfaced to users - ops alerts only."""

    async def record(
        self,
        user_id: str,
        amount_inr: float,
        *,
        kind: str,
        task_id: str | None = None,
        call_id: str | None = None,
        at: datetime | None = None,
    ) -> None:
        async with self.db.session() as s:
            s.add(
                CostEntryRow(
                    user_id=user_id,
                    task_id=task_id,
                    call_id=call_id,
                    kind=kind,
                    amount_inr=float(amount_inr),
                    at=at or self.now(),
                )
            )

    async def total_between(self, user_id: str, start: datetime, end: datetime) -> float:
        async with self.db.session() as s:
            total = (
                await s.execute(
                    select(func.coalesce(func.sum(CostEntryRow.amount_inr), 0.0)).where(
                        CostEntryRow.user_id == user_id,
                        CostEntryRow.at >= start,
                        CostEntryRow.at < end,
                    )
                )
            ).scalar_one()
            return float(total)

    async def count_between(
        self, user_id: str, start: datetime, end: datetime, *, kind: str | None = None
    ) -> int:
        async with self.db.session() as s:
            q = select(func.count()).select_from(CostEntryRow).where(
                CostEntryRow.user_id == user_id, CostEntryRow.at >= start, CostEntryRow.at < end
            )
            if kind:
                q = q.where(CostEntryRow.kind == kind)
            return int((await s.execute(q)).scalar_one())
