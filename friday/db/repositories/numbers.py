"""Caller-ID pool persistence (NP-1): numbers, sticky assignments, outcomes, DNC.

Backend B's ``NumberPool`` (friday/tasks/number_pool.py) keeps its policy there and
stores state here via ``c.repos.numbers``. DNC and assignments are looked up by the
phone blind index; clear business phones are encrypted at rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, update

from friday.core.models import (
    FridayNumber,
    NumberHealth,
    NumberLimits,
    NumberOutcome,
    NumberStatus,
)
from friday.db.repositories._base import Repo, copy_simple, phone_index, row_dict
from friday.db.tables import DncRow, FridayNumberRow, NumberAssignmentRow, NumberOutcomeRow


class NumberAssignment(BaseModel):
    business_phone: str
    number_phone: str
    assigned_at: datetime
    last_used_at: datetime | None = None
    previous_number: str | None = None


class OutcomeRecord(BaseModel):
    number_phone: str
    outcome: NumberOutcome
    duration_s: float = 0.0
    at: datetime
    business: str | None = None  # blind index of the business phone (stable id, no PII)


class DncEntry(BaseModel):
    phone: str
    reason: str
    number_phone: str | None = None
    at: datetime


def _number(row: FridayNumberRow) -> FridayNumber:
    d = row_dict(row, skip={"limits", "health"})
    d["limits"] = NumberLimits.model_validate(row.limits or {})
    d["health"] = NumberHealth.model_validate(row.health or {})
    return FridayNumber.model_validate(d)


class NumberRepo(Repo):
    # ------------------------------------------------------------------ NumberStore adapter
    # Backend B's pool (friday/tasks/number_pool.py::NumberStore) talks to these names.
    async def list_numbers(self) -> list[FridayNumber]:
        return await self.list()

    async def save_number(self, number: FridayNumber) -> None:
        await self.upsert(number)

    async def set_assignment(self, business_key: str, number_phone: str) -> None:
        await self.assign(business_key, number_phone)

    async def clear_outcomes(self, number_phone: str) -> None:
        """Start a fresh health window (rows are archived, never deleted: append-only)."""
        async with self.db.session() as s:
            await s.execute(
                update(NumberOutcomeRow)
                .where(NumberOutcomeRow.number_phone == number_phone)
                .values(archived=True)
            )

    # ------------------------------------------------------------------ numbers
    async def upsert(self, number: FridayNumber) -> FridayNumber:
        values = copy_simple(number, FridayNumberRow, skip={"limits", "health"})
        values["limits"] = number.limits.model_dump(mode="json")
        values["health"] = number.health.model_dump(mode="json")
        async with self.db.session() as s:
            existing = (
                await s.execute(
                    select(FridayNumberRow).where(FridayNumberRow.phone == number.phone)
                )
            ).scalar_one_or_none()
            if existing is not None and existing.id != number.id:
                number.id = existing.id
                values["id"] = existing.id
            await s.merge(FridayNumberRow(**values))
        return number

    async def get(self, phone: str) -> FridayNumber | None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(FridayNumberRow).where(FridayNumberRow.phone == phone))
            ).scalar_one_or_none()
            return _number(row) if row else None

    async def list(self, *, statuses: Sequence[NumberStatus] | None = None) -> list[FridayNumber]:
        async with self.db.session() as s:
            q = select(FridayNumberRow)
            if statuses:
                q = q.where(FridayNumberRow.status.in_([st.value for st in statuses]))
            rows = (await s.execute(q.order_by(FridayNumberRow.created_at))).scalars()
            return [_number(r) for r in rows]

    # ------------------------------------------------------------------ sticky assignment
    async def get_assignment(self, business_phone: str) -> str | None:
        rec = await self.get_assignment_record(business_phone)
        return rec.number_phone if rec else None

    async def get_assignment_record(self, business_phone: str) -> NumberAssignment | None:
        async with self.db.session() as s:
            row = await s.get(NumberAssignmentRow, phone_index(business_phone))
            if row is None:
                return None
            return NumberAssignment.model_validate(row_dict(row, skip={"business_phone_hmac"}))

    async def assign(self, business_phone: str, number_phone: str) -> NumberAssignment:
        """Sticky: keep the row; moving to a new number records ``previous_number``."""
        now = self.now()
        async with self.db.session() as s:
            key = phone_index(business_phone)
            row = await s.get(NumberAssignmentRow, key)
            if row is None:
                row = NumberAssignmentRow(
                    business_phone_hmac=key,
                    business_phone=business_phone,
                    number_phone=number_phone,
                    assigned_at=now,
                )
                s.add(row)
            elif row.number_phone != number_phone:
                row.previous_number = row.number_phone
                row.number_phone = number_phone
                row.assigned_at = now
            row.last_used_at = now
            await s.flush()
            return NumberAssignment.model_validate(row_dict(row, skip={"business_phone_hmac"}))

    async def assignments_for(self, number_phone: str) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(NumberAssignmentRow)
                        .where(NumberAssignmentRow.number_phone == number_phone)
                    )
                ).scalar_one()
            )

    # ------------------------------------------------------------------ outcomes (append-only)
    async def add_outcome(
        self,
        number_phone: str,
        outcome: Any,
        *,
        business_phone: str | None = None,
        duration_s: float = 0.0,
        at: datetime | None = None,
    ) -> None:
        """``outcome`` is a ``NumberOutcome`` or a pool row (``at/outcome/business/duration_s``)."""
        if not isinstance(outcome, NumberOutcome):
            row = outcome
            outcome, duration_s, at = row.outcome, row.duration_s, row.at
            business_hmac = row.business and phone_index(row.business)
        else:
            business_hmac = phone_index(business_phone) if business_phone else None
        async with self.db.session() as s:
            s.add(
                NumberOutcomeRow(
                    number_phone=number_phone,
                    outcome=outcome.value,
                    business_phone_hmac=business_hmac,
                    duration_s=float(duration_s),
                    at=at or self.now(),
                )
            )

    async def recent_outcomes(self, number_phone: str, limit: int = 50) -> list[OutcomeRecord]:
        """The last ``limit`` outcomes of the current health window, oldest first."""
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(NumberOutcomeRow)
                        .where(
                            NumberOutcomeRow.number_phone == number_phone,
                            NumberOutcomeRow.archived.is_(False),
                        )
                        .order_by(NumberOutcomeRow.at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                OutcomeRecord(
                    number_phone=r.number_phone,
                    outcome=NumberOutcome(r.outcome),
                    duration_s=r.duration_s,
                    at=r.at,
                    business=r.business_phone_hmac,
                )
                for r in reversed(rows)
            ]

    async def count_outcomes(
        self,
        number_phone: str,
        *,
        since: datetime,
        until: datetime | None = None,
        outcomes: Sequence[NumberOutcome] | None = None,
    ) -> int:
        """Pacing: calls placed on a number in a window."""
        async with self.db.session() as s:
            q = (
                select(func.count())
                .select_from(NumberOutcomeRow)
                .where(NumberOutcomeRow.number_phone == number_phone, NumberOutcomeRow.at >= since)
            )
            if until is not None:
                q = q.where(NumberOutcomeRow.at < until)
            if outcomes:
                q = q.where(NumberOutcomeRow.outcome.in_([o.value for o in outcomes]))
            return int((await s.execute(q)).scalar_one())

    # ------------------------------------------------------------------ DNC (pool-wide)
    async def add_dnc(
        self,
        phone: str,
        reason: str = "dnc_request",
        at: datetime | None = None,
        *,
        number_phone: str | None = None,
    ) -> DncEntry:
        async with self.db.session() as s:
            key = phone_index(phone)
            row = (
                await s.execute(select(DncRow).where(DncRow.phone_hmac == key))
            ).scalar_one_or_none()
            if row is None:
                row = DncRow(
                    phone_hmac=key,
                    phone=phone,
                    reason=reason,
                    number_phone=number_phone,
                    at=at or self.now(),
                )
                s.add(row)
                await s.flush()
            return DncEntry.model_validate(row_dict(row))

    async def is_dnc(self, phone: str) -> bool:
        async with self.db.session() as s:
            row = (
                await s.execute(select(DncRow.id).where(DncRow.phone_hmac == phone_index(phone)))
            ).first()
            return row is not None

    async def list_dnc(self, *, limit: int = 500) -> list[DncEntry]:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(DncRow).order_by(DncRow.at.desc()).limit(limit))
            ).scalars()
            return [DncEntry.model_validate(row_dict(r)) for r in rows]
