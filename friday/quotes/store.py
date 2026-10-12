# ruff: noqa: E501
"""Persistence for quote conversations: optimistic concurrency, one row per request."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import func, select, update

from friday.core.clock import Clock, SystemClock
from friday.db.session import Database
from friday.quotes.dbmodel import QuoteConversationRow
from friday.quotes.models import Conv, State


class Conflict(Exception):  # noqa: N818
    pass


def _conv(row: QuoteConversationRow) -> tuple[Conv, int]:
    return Conv.model_validate(row.data), row.version


class QuoteStore:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    async def create(self, conv: Conv) -> Conv:
        async with self.db.session() as s:
            s.add(
                QuoteConversationRow(
                    id=conv.id,
                    user_id=conv.user_id,
                    state=conv.state.value,
                    active=conv.state.active,
                    version=0,
                    data=conv.model_dump(mode="json"),
                    created_at=conv.created_at,
                    updated_at=self.clock.now(),
                )
            )
        return conv

    async def get(self, conv_id: str) -> tuple[Conv, int] | None:
        async with self.db.session() as s:
            row = await s.get(QuoteConversationRow, conv_id)
            return _conv(row) if row else None

    async def active_for_user(self, user_id: str) -> tuple[Conv, int] | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(QuoteConversationRow)
                    .where(QuoteConversationRow.user_id == user_id, QuoteConversationRow.active)
                    .order_by(QuoteConversationRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _conv(row) if row else None

    async def latest_for_user(self, user_id: str) -> tuple[Conv, int] | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(QuoteConversationRow)
                    .where(QuoteConversationRow.user_id == user_id)
                    .order_by(QuoteConversationRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _conv(row) if row else None

    async def list_active(self) -> list[tuple[Conv, int]]:
        async with self.db.session() as s:
            rows = (
                await s.execute(select(QuoteConversationRow).where(QuoteConversationRow.active))
            ).scalars()
            return [_conv(r) for r in rows]

    async def list_awaiting_delivery(self) -> list[tuple[Conv, int]]:
        """Conversations whose final message has not been confirmed delivered yet."""
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(QuoteConversationRow).order_by(QuoteConversationRow.updated_at.desc())
                )
            ).scalars()
            out = []
            for r in rows:
                conv, ver = _conv(r)
                d = conv.delivery
                if d and d.text and not d.delivered and not (d.sms_sent and d.voice_requested):
                    out.append((conv, ver))
                if len(out) >= 200:
                    break
            return out

    async def count_counted_between(self, user_id: str, start: datetime, end: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(QuoteConversationRow)
                        .where(
                            QuoteConversationRow.user_id == user_id,
                            QuoteConversationRow.counted_at >= start,
                            QuoteConversationRow.counted_at < end,
                        )
                    )
                ).scalar_one()
            )

    async def save(self, conv: Conv, version: int) -> int:
        """Compare-and-set; returns the new version or raises ``Conflict``."""
        async with self.db.session() as s:
            res = await s.execute(
                update(QuoteConversationRow)
                .where(QuoteConversationRow.id == conv.id, QuoteConversationRow.version == version)
                .values(
                    state=conv.state.value,
                    active=conv.state.active,
                    version=version + 1,
                    counted_at=(
                        func.coalesce(QuoteConversationRow.counted_at, self.clock.now())
                        if conv.counted
                        else QuoteConversationRow.counted_at
                    ),
                    data=conv.model_dump(mode="json"),
                    updated_at=self.clock.now(),
                )
            )
            if not res.rowcount:
                raise Conflict(conv.id)
        return version + 1

    async def mutate(
        self, conv_id: str, fn: Callable[[Conv], Awaitable[None] | None], *, tries: int = 6
    ) -> Conv | None:
        """Load, apply ``fn`` (pure, no I/O), save with CAS; retry on conflict."""
        for _ in range(tries):
            got = await self.get(conv_id)
            if got is None:
                return None
            conv, ver = got
            res = fn(conv)
            if res is not None and hasattr(res, "__await__"):
                await res
            try:
                await self.save(conv, ver)
            except Conflict:
                continue
            return conv
        raise Conflict(conv_id)


_ = State
