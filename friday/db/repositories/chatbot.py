"""Storage for the chatbot pilot (tables in ``friday/chatbot/dbmodel.py``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from friday.chatbot.dbmodel import ChatbotInboxRow, ChatbotSessionRow, ChatbotWaitlistRow
from friday.db.repositories._base import Repo, phone_index


@dataclass
class Session:
    """Where one person is in the first-run flow."""

    phone_hash: str
    step: str
    lang: str
    step_at: datetime
    id: str | None = None
    user_id: str | None = None
    pending_kind: str | None = None
    pending: dict[str, Any] = field(default_factory=dict)
    last_hash: str | None = None
    refused_at: datetime | None = None


@dataclass(frozen=True)
class InboxItem:
    id: str
    kind: str
    user_id: str | None
    text: str
    lang: str
    status: str
    created_at: datetime


def _session(r: ChatbotSessionRow) -> Session:
    return Session(
        phone_hash=r.phone_hash, step=r.step, lang=r.lang, step_at=r.step_at, id=r.id,
        user_id=r.user_id, pending_kind=r.pending_kind, pending=dict(r.pending or {}),
        last_hash=r.last_hash, refused_at=r.refused_at,
    )  # fmt: skip


def _item(r: ChatbotInboxRow) -> InboxItem:
    return InboxItem(r.id, r.kind, r.user_id, r.text, r.lang, r.status, r.created_at)


class ChatbotRepo(Repo):
    # ------------------------------------------------------------------ sessions
    async def session_for_phone(self, phone: str) -> Session | None:
        return await self._by("phone_hash", phone_index(phone))

    async def session_for_user(self, user_id: str) -> Session | None:
        return await self._by("user_id", user_id)

    async def _by(self, column: str, value: str) -> Session | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ChatbotSessionRow).where(getattr(ChatbotSessionRow, column) == value)
                )
            ).scalar_one_or_none()
            return _session(row) if row else None

    async def save_session(self, sess: Session) -> Session:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ChatbotSessionRow).where(ChatbotSessionRow.phone_hash == sess.phone_hash)
                )
            ).scalar_one_or_none()
            if row is None:
                row = ChatbotSessionRow(phone_hash=sess.phone_hash, step_at=sess.step_at)
                s.add(row)
            row.user_id = sess.user_id
            row.step, row.lang, row.step_at = sess.step, sess.lang, sess.step_at
            row.pending_kind = sess.pending_kind
            row.pending = dict(sess.pending) if sess.pending else None
            row.last_hash, row.refused_at = sess.last_hash, sess.refused_at
            row.updated_at = self.now()
            await s.flush()
            sess.id = row.id
        return sess

    async def delete_session(self, phone_hash: str) -> None:
        async with self.db.session() as s:
            await s.execute(
                delete(ChatbotSessionRow).where(ChatbotSessionRow.phone_hash == phone_hash)
            )

    async def count_sessions(self) -> dict[str, int]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ChatbotSessionRow.step, func.count()).group_by(ChatbotSessionRow.step)
                )
            ).all()
            return {step: int(n) for step, n in rows}

    # ------------------------------------------------------------------ waitlist
    async def waitlist_add(self, phone: str) -> bool:
        """Record a waitlisted number (hash only). True when it is new."""
        h, now = phone_index(phone), self.now()
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ChatbotWaitlistRow).where(ChatbotWaitlistRow.phone_hash == h)
                )
            ).scalar_one_or_none()
            if row is None:
                s.add(ChatbotWaitlistRow(phone_hash=h, first_seen_at=now, last_seen_at=now))
                return True
            row.hits += 1
            row.last_seen_at = now
            return False

    async def waitlist_count(self) -> int:
        async with self.db.session() as s:
            return int(
                (await s.execute(select(func.count()).select_from(ChatbotWaitlistRow))).scalar_one()
            )

    async def waitlist_has(self, phone: str) -> bool:
        async with self.db.session() as s:
            return (
                await s.execute(
                    select(ChatbotWaitlistRow.id).where(
                        ChatbotWaitlistRow.phone_hash == phone_index(phone)
                    )
                )
            ).first() is not None

    # ------------------------------------------------------------------ inbox
    async def inbox_add(
        self, kind: str, text: str, *, user_id: str | None, lang: str = "hinglish"
    ) -> InboxItem:
        row = ChatbotInboxRow(
            kind=kind, user_id=user_id, text=text, lang=lang, status="new", created_at=self.now()
        )
        async with self.db.session() as s:
            s.add(row)
            await s.flush()
            return _item(row)

    async def inbox_list(self, kind: str, *, limit: int = 200) -> list[InboxItem]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ChatbotInboxRow)
                    .where(ChatbotInboxRow.kind == kind)
                    .order_by(ChatbotInboxRow.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return [_item(r) for r in rows]

    async def last_inbox_text(self, kind: str, user_id: str) -> str | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ChatbotInboxRow)
                    .where(ChatbotInboxRow.kind == kind, ChatbotInboxRow.user_id == user_id)
                    .order_by(ChatbotInboxRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row.text if row else None


async def purge_user_chatbot(s: Any, user_id: str) -> dict[str, int]:
    """Erase everything the chatbot holds for ``user_id`` (called by the data purger)."""
    out: dict[str, int] = {}
    for table in (ChatbotInboxRow, ChatbotSessionRow):
        res = await s.execute(delete(table).where(table.user_id == user_id))
        out[table.__tablename__] = int(res.rowcount or 0)
    return out
