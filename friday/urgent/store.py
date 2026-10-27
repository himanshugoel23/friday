# ruff: noqa: E501
"""Storage of the urgent-call escalation: per-user config and one state row per urgent message.

``MemoryEscalationStore`` (tests, simulator) and ``SqlEscalationStore`` (tables of migration
0015_urgent_escalation) implement the same ``EscalationStore`` protocol and run the same test suite.

Restart safety lives here, in three compare-and-set operations that return False when someone else
(another replica, a tap on Acknowledge) got there first:

* ``create``     UNIQUE (user, message): opening twice returns the existing row, never a second one;
* ``claim``      pending + not in flight + calls_made == expected  ->  in flight, calls_made + 1.
                 The attempt is recorded BEFORE the dial, so a crash while ringing can never lead to
                 a second dial of the same attempt;
* ``close``      only a PENDING row can be closed, so a late Acknowledge never reopens anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, or_, select, update

from friday.core.clock import Clock, SystemClock
from friday.core.models import new_id
from friday.db.repositories._base import Repo
from friday.urgent.dbmodel import (
    UrgentEscalationConfigRow,
    UrgentEscalationRow,
    purge_user_urgent,
)
from friday.urgent.models import FINAL, EscalationState, EscStatus, UserEscalationConfig

PENDING = EscStatus.PENDING.value
FINAL_VALUES = [s.value for s in FINAL]


class EscalationStore(Protocol):
    async def get_config(self, user_id: str) -> UserEscalationConfig | None: ...
    async def save_config(self, user_id: str, cfg: UserEscalationConfig) -> None: ...
    async def create(self, st: EscalationState) -> tuple[EscalationState, bool]: ...
    async def get(self, user_id: str, esc_id: str) -> EscalationState | None: ...
    async def by_message(self, user_id: str, message_id: str) -> EscalationState | None: ...
    async def set_alert(
        self, esc_id: str, *, ok: bool, sent_at: datetime | None, next_action_at: datetime
    ) -> bool: ...
    async def due(self, now: datetime, limit: int = 50) -> list[EscalationState]: ...
    async def claim(self, esc_id: str, expected_calls: int, now: datetime) -> bool: ...
    async def finish_attempt(
        self, esc_id: str, *, result: str, next_action_at: datetime | None
    ) -> bool: ...
    async def close(
        self, user_id: str, esc_id: str, status: EscStatus, reason: str, now: datetime
    ) -> bool: ...
    async def close_open_for_user(
        self, user_id: str, status: EscStatus, reason: str, now: datetime
    ) -> int: ...
    async def close_for_message(
        self, user_id: str, message_id: str, status: EscStatus, reason: str, now: datetime
    ) -> int: ...
    async def escalations_with_calls_since(self, user_id: str, since: datetime) -> int: ...
    async def open_for_user(self, user_id: str) -> list[EscalationState]: ...
    async def purge_finished(self, before: datetime) -> int: ...
    async def delete_user(self, user_id: str) -> int: ...


# =============================================================================== memory
class MemoryEscalationStore:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self.configs: dict[str, UserEscalationConfig] = {}
        self.rows: dict[str, EscalationState] = {}

    async def get_config(self, user_id: str) -> UserEscalationConfig | None:
        c = self.configs.get(user_id)
        return c.model_copy(deep=True) if c else None

    async def save_config(self, user_id: str, cfg: UserEscalationConfig) -> None:
        self.configs[user_id] = cfg.model_copy(deep=True)

    async def create(self, st: EscalationState) -> tuple[EscalationState, bool]:
        for r in self.rows.values():
            if r.user_id == st.user_id and r.message_id == st.message_id:
                return r.model_copy(), False
        st = st.model_copy(update={"id": st.id or new_id(), "created_at": st.created_at or self.clock.now()})
        self.rows[st.id] = st
        return st.model_copy(), True

    async def get(self, user_id: str, esc_id: str) -> EscalationState | None:
        r = self.rows.get(esc_id)
        return r.model_copy() if r and r.user_id == user_id else None

    async def by_message(self, user_id: str, message_id: str) -> EscalationState | None:
        for r in self.rows.values():
            if r.user_id == user_id and r.message_id == message_id:
                return r.model_copy()
        return None

    async def set_alert(self, esc_id: str, *, ok: bool, sent_at: datetime | None, next_action_at: datetime) -> bool:
        r = self.rows.get(esc_id)
        if r is None or r.status != EscStatus.PENDING:
            return False
        r.alert_ok, r.alert_sent_at, r.next_action_at = ok, sent_at, next_action_at
        return True

    async def due(self, now: datetime, limit: int = 50) -> list[EscalationState]:
        out = [
            r.model_copy() for r in self.rows.values()
            if r.status == EscStatus.PENDING and r.next_action_at is not None and r.next_action_at <= now
        ]  # fmt: skip
        return sorted(out, key=lambda r: r.next_action_at)[:limit]  # type: ignore[arg-type,return-value]

    async def claim(self, esc_id: str, expected_calls: int, now: datetime) -> bool:
        r = self.rows.get(esc_id)
        if r is None or r.status != EscStatus.PENDING or r.in_flight or r.calls_made != expected_calls:
            return False
        r.in_flight, r.calls_made, r.last_call_at = True, r.calls_made + 1, now
        return True

    async def finish_attempt(self, esc_id: str, *, result: str, next_action_at: datetime | None) -> bool:
        r = self.rows.get(esc_id)
        if r is None or not r.in_flight:
            return False
        r.in_flight, r.last_call_result = False, result
        if r.status == EscStatus.PENDING:
            r.next_action_at = next_action_at
        return True

    async def close(self, user_id: str, esc_id: str, status: EscStatus, reason: str, now: datetime) -> bool:
        r = self.rows.get(esc_id)
        if r is None or r.user_id != user_id or r.status != EscStatus.PENDING:
            return False
        r.status, r.stop_reason, r.finished_at, r.next_action_at = status, reason[:32], now, None
        if status == EscStatus.ACKED:
            r.ack_at = now
        return True

    async def close_open_for_user(self, user_id: str, status: EscStatus, reason: str, now: datetime) -> int:
        n = 0
        for r in list(self.rows.values()):
            if r.user_id == user_id and await self.close(user_id, r.id, status, reason, now):
                n += 1
        return n

    async def close_for_message(self, user_id: str, message_id: str, status: EscStatus, reason: str, now: datetime) -> int:
        n = 0
        for r in list(self.rows.values()):
            if r.user_id == user_id and r.message_id == message_id and await self.close(user_id, r.id, status, reason, now):
                n += 1
        return n

    async def escalations_with_calls_since(self, user_id: str, since: datetime) -> int:
        return sum(1 for r in self.rows.values() if r.user_id == user_id and r.calls_made > 0 and r.last_call_result != "refused" and r.last_call_at and r.last_call_at >= since)

    async def open_for_user(self, user_id: str) -> list[EscalationState]:
        return [r.model_copy() for r in self.rows.values() if r.user_id == user_id and r.status == EscStatus.PENDING]

    async def purge_finished(self, before: datetime) -> int:
        gone = [k for k, r in self.rows.items() if r.status in FINAL and (r.finished_at or r.created_at or before) < before]
        for k in gone:
            del self.rows[k]
        return len(gone)

    async def delete_user(self, user_id: str) -> int:
        n = sum(1 for r in self.rows.values() if r.user_id == user_id)
        self.rows = {k: v for k, v in self.rows.items() if v.user_id != user_id}
        self.configs.pop(user_id, None)
        return n


# =============================================================================== SQL
def _state(r: UrgentEscalationRow) -> EscalationState:
    return EscalationState(
        id=r.id, user_id=r.user_id, message_id=r.message_id, status=EscStatus(r.status),
        emergency=r.emergency, alert_ok=r.alert_ok, alert_sent_at=r.alert_sent_at, wait_s=r.wait_s,
        max_calls=r.max_calls, spacing_s=r.spacing_s, next_action_at=r.next_action_at,
        calls_made=r.calls_made, in_flight=r.in_flight, last_call_at=r.last_call_at,
        last_call_result=r.last_call_result, ack_at=r.ack_at, stop_reason=r.stop_reason,
        finished_at=r.finished_at, created_at=r.created_at,
    )  # fmt: skip


class SqlEscalationStore(Repo):
    async def get_config(self, user_id: str) -> UserEscalationConfig | None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(UrgentEscalationConfigRow).where(UrgentEscalationConfigRow.user_id == user_id))
            ).scalar_one_or_none()
            return UserEscalationConfig.model_validate(row.config) if row else None

    async def save_config(self, user_id: str, cfg: UserEscalationConfig) -> None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(UrgentEscalationConfigRow).where(UrgentEscalationConfigRow.user_id == user_id))
            ).scalar_one_or_none()
            data = cfg.model_dump(mode="json")
            if row is None:
                s.add(UrgentEscalationConfigRow(user_id=user_id, opted_in=cfg.opted_in, config=data))
            else:
                row.opted_in, row.config = cfg.opted_in, data

    async def create(self, st: EscalationState) -> tuple[EscalationState, bool]:
        existing = await self.by_message(st.user_id, st.message_id)
        if existing is not None:
            return existing, False
        try:
            async with self.db.session() as s:
                row = UrgentEscalationRow(
                    user_id=st.user_id, message_id=st.message_id, status=st.status.value,
                    emergency=st.emergency, alert_ok=st.alert_ok, alert_sent_at=st.alert_sent_at,
                    wait_s=st.wait_s, max_calls=st.max_calls, spacing_s=st.spacing_s,
                    next_action_at=st.next_action_at, calls_made=0, in_flight=False,
                )  # fmt: skip
                row.created_at = st.created_at or self.now()
                s.add(row)
                await s.flush()
                return _state(row), True
        except Exception:  # noqa: BLE001 - lost the race on UNIQUE (user, message): return the winner
            again = await self.by_message(st.user_id, st.message_id)
            if again is None:
                raise
            return again, False

    async def _one(self, where) -> EscalationState | None:  # noqa: ANN001
        async with self.db.session() as s:
            row = (await s.execute(select(UrgentEscalationRow).where(*where))).scalar_one_or_none()
            return _state(row) if row else None

    async def get(self, user_id: str, esc_id: str) -> EscalationState | None:
        return await self._one((UrgentEscalationRow.id == esc_id, UrgentEscalationRow.user_id == user_id))

    async def by_message(self, user_id: str, message_id: str) -> EscalationState | None:
        return await self._one((UrgentEscalationRow.user_id == user_id, UrgentEscalationRow.message_id == message_id))

    async def _cas(self, where, values: dict) -> bool:  # noqa: ANN001
        async with self.db.session() as s:
            res = await s.execute(update(UrgentEscalationRow).where(*where).values(**values))
            return bool(res.rowcount)

    async def set_alert(self, esc_id: str, *, ok: bool, sent_at: datetime | None, next_action_at: datetime) -> bool:
        return await self._cas(
            (UrgentEscalationRow.id == esc_id, UrgentEscalationRow.status == PENDING),
            {"alert_ok": ok, "alert_sent_at": sent_at, "next_action_at": next_action_at},
        )

    async def due(self, now: datetime, limit: int = 50) -> list[EscalationState]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(UrgentEscalationRow)
                    .where(UrgentEscalationRow.status == PENDING, UrgentEscalationRow.next_action_at <= now)
                    .order_by(UrgentEscalationRow.next_action_at)
                    .limit(limit)
                )
            ).scalars()
            return [_state(r) for r in rows]

    async def claim(self, esc_id: str, expected_calls: int, now: datetime) -> bool:
        return await self._cas(
            (
                UrgentEscalationRow.id == esc_id,
                UrgentEscalationRow.status == PENDING,
                UrgentEscalationRow.in_flight.is_(False),
                UrgentEscalationRow.calls_made == expected_calls,
            ),
            {"in_flight": True, "calls_made": expected_calls + 1, "last_call_at": now},
        )

    async def finish_attempt(self, esc_id: str, *, result: str, next_action_at: datetime | None) -> bool:
        ok = await self._cas(
            (UrgentEscalationRow.id == esc_id, UrgentEscalationRow.in_flight.is_(True)),
            {"in_flight": False, "last_call_result": result},
        )
        if ok:  # the next time only moves while the row is still pending (never reopens a closed one)
            await self._cas(
                (UrgentEscalationRow.id == esc_id, UrgentEscalationRow.status == PENDING),
                {"next_action_at": next_action_at},
            )
        return ok

    async def close(self, user_id: str, esc_id: str, status: EscStatus, reason: str, now: datetime) -> bool:
        vals: dict = {"status": status.value, "stop_reason": reason[:32], "finished_at": now, "next_action_at": None}
        if status == EscStatus.ACKED:
            vals["ack_at"] = now
        return await self._cas(
            (UrgentEscalationRow.id == esc_id, UrgentEscalationRow.user_id == user_id, UrgentEscalationRow.status == PENDING),
            vals,
        )

    async def _close_many(self, where, status: EscStatus, reason: str, now: datetime) -> int:  # noqa: ANN001
        vals: dict = {"status": status.value, "stop_reason": reason[:32], "finished_at": now, "next_action_at": None}
        if status == EscStatus.ACKED:
            vals["ack_at"] = now
        async with self.db.session() as s:
            res = await s.execute(update(UrgentEscalationRow).where(UrgentEscalationRow.status == PENDING, *where).values(**vals))
            return int(res.rowcount or 0)

    async def close_open_for_user(self, user_id: str, status: EscStatus, reason: str, now: datetime) -> int:
        return await self._close_many((UrgentEscalationRow.user_id == user_id,), status, reason, now)

    async def close_for_message(self, user_id: str, message_id: str, status: EscStatus, reason: str, now: datetime) -> int:
        return await self._close_many(
            (UrgentEscalationRow.user_id == user_id, UrgentEscalationRow.message_id == message_id), status, reason, now
        )

    async def escalations_with_calls_since(self, user_id: str, since: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count()).select_from(UrgentEscalationRow).where(
                            UrgentEscalationRow.user_id == user_id,
                            UrgentEscalationRow.calls_made > 0,
                            or_(UrgentEscalationRow.last_call_result.is_(None), UrgentEscalationRow.last_call_result != "refused"),
                            UrgentEscalationRow.last_call_at >= since,
                        )
                    )
                ).scalar_one()
            )

    async def open_for_user(self, user_id: str) -> list[EscalationState]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(UrgentEscalationRow).where(UrgentEscalationRow.user_id == user_id, UrgentEscalationRow.status == PENDING)
                )
            ).scalars()
            return [_state(r) for r in rows]

    async def purge_finished(self, before: datetime) -> int:
        async with self.db.session() as s:
            res = await s.execute(
                delete(UrgentEscalationRow).where(
                    UrgentEscalationRow.status.in_(FINAL_VALUES), UrgentEscalationRow.finished_at < before
                )
            )
            return int(res.rowcount or 0)

    async def delete_user(self, user_id: str) -> int:
        async with self.db.session() as s:
            counts = await purge_user_urgent(s, user_id)
        return counts["urgent_escalations"]


def retention_cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)
