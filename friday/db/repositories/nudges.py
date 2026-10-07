"""Proactive nudges + feedback."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from friday.core.models import (
    FeedbackType,
    Nudge,
    NudgeFeedback,
    NudgeKind,
    NudgeStatus,
    ReplyButton,
    TaskSpec,
)
from friday.db.repositories._base import Repo, copy_simple, dump_json, dump_json_list, row_dict
from friday.db.tables import NudgeFeedbackRow, NudgeRow


def _values(n: Nudge) -> dict:
    v = copy_simple(n, NudgeRow, skip={"buttons", "proposed_task"})
    v["buttons"] = dump_json_list(list(n.buttons))
    v["proposed_task"] = dump_json(n.proposed_task)
    return v


def _nudge(row: NudgeRow) -> Nudge:
    d = row_dict(row, skip={"buttons", "proposed_task"})
    d["buttons"] = [ReplyButton.model_validate(b) for b in row.buttons or []]
    d["proposed_task"] = TaskSpec.model_validate(row.proposed_task) if row.proposed_task else None
    return Nudge.model_validate(d)


class NudgeRepo(Repo):
    """Implements ``NudgeRepository`` (+ extras for guardrails / feedback)."""

    async def add(self, nudge: Nudge) -> Nudge:
        async with self.db.session() as s:
            s.add(NudgeRow(**_values(nudge)))
        return nudge

    async def save(self, nudge: Nudge) -> Nudge:
        async with self.db.session() as s:
            await s.merge(NudgeRow(**_values(nudge)))
        return nudge

    async def get(self, nudge_id: str) -> Nudge | None:
        async with self.db.session() as s:
            row = await s.get(NudgeRow, nudge_id)
            return _nudge(row) if row else None

    async def exists(self, user_id: str, dedupe_key: str) -> bool:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(NudgeRow.id).where(
                        NudgeRow.user_id == user_id, NudgeRow.dedupe_key == dedupe_key
                    )
                )
            ).first()
            return row is not None

    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(NudgeRow)
                        .where(
                            NudgeRow.user_id == user_id,
                            NudgeRow.sent_at.is_not(None),
                            NudgeRow.sent_at >= start,
                            NudgeRow.sent_at < end,
                        )
                    )
                ).scalar_one()
            )

    async def list_for_user(
        self,
        user_id: str,
        *,
        kind: NudgeKind | None = None,
        status: NudgeStatus | None = None,
        limit: int = 50,
    ) -> list[Nudge]:
        """Newest first."""
        async with self.db.session() as s:
            q = select(NudgeRow).where(NudgeRow.user_id == user_id)
            if kind:
                q = q.where(NudgeRow.kind == kind.value)
            if status:
                q = q.where(NudgeRow.status == status.value)
            rows = (await s.execute(q.order_by(NudgeRow.created_at.desc()).limit(limit))).scalars()
            return [_nudge(r) for r in rows]

    async def list_scheduled_due(self, now: datetime) -> list[Nudge]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(NudgeRow)
                    .where(
                        NudgeRow.status == NudgeStatus.SCHEDULED.value,
                        NudgeRow.scheduled_for.is_not(None),
                        NudgeRow.scheduled_for <= now,
                    )
                    .order_by(NudgeRow.scheduled_for)
                )
            ).scalars()
            return [_nudge(r) for r in rows]

    async def list_sent_unanswered_before(self, cutoff: datetime) -> list[Nudge]:
        """SENT nudges with no response sent before ``cutoff`` (-> IGNORED)."""
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(NudgeRow).where(
                        NudgeRow.status == NudgeStatus.SENT.value,
                        NudgeRow.responded_at.is_(None),
                        NudgeRow.sent_at < cutoff,
                    )
                )
            ).scalars()
            return [_nudge(r) for r in rows]

    async def add_feedback(self, feedback: NudgeFeedback) -> NudgeFeedback:
        async with self.db.session() as s:
            s.add(NudgeFeedbackRow(**copy_simple(feedback, NudgeFeedbackRow)))
        return feedback

    async def feedback_for_user(
        self, user_id: str, *, limit: int = 50, type: FeedbackType | None = None
    ) -> list[NudgeFeedback]:
        """Newest first."""
        async with self.db.session() as s:
            q = select(NudgeFeedbackRow).where(NudgeFeedbackRow.user_id == user_id)
            if type:
                q = q.where(NudgeFeedbackRow.type == type.value)
            rows = (await s.execute(q.order_by(NudgeFeedbackRow.at.desc()).limit(limit))).scalars()
            return [NudgeFeedback.model_validate(row_dict(r)) for r in rows]

    async def consecutive_ignored(self, user_id: str, kind: NudgeKind) -> int:
        """How many of the latest SENT-or-later nudges of ``kind`` were IGNORED in a row."""
        n = 0
        for nudge in await self.list_for_user(user_id, kind=kind, limit=20):
            if nudge.status == NudgeStatus.IGNORED:
                n += 1
            elif nudge.status in (NudgeStatus.ACTED, NudgeStatus.DISMISSED):
                break
        return n
