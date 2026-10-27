# ruff: noqa: E501
"""Storage of the receptionist: per-user config, messages, block list, counters.

``MemoryReceptionistStore`` (tests, simulator, offline demo) and ``SqlReceptionistStore`` (the
encrypted tables of migration 0011) implement the same ``ReceptionistStore`` protocol and are
tested by the same suite. Numbers are looked up by blind index only.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select, update

from friday.core.clock import Clock, SystemClock
from friday.core.models import new_id
from friday.db.repositories._base import Repo, phone_index
from friday.receptionist.dbmodel import (
    ReceptionistBlockRow,
    ReceptionistConfigRow,
    ReceptionistMessageRow,
    ReceptionistSpamRow,
    purge_user_receptionist,
)
from friday.receptionist.models import (
    CallOutcomeKind,
    MessageStatus,
    ReceptionistConfig,
    StoredMessage,
    Urgency,
)

UNROUTED_KEEP_DAYS = 7


def _digits10(n: str | None) -> str:
    return re.sub(r"\D", "", n or "")[-10:]


def spam_key(number: str | None) -> str | None:
    """Keyed hash (HMAC with the index key, own label) of the last 10 digits; None without digits.
    The shared spam table stores only this and a count."""
    d = _digits10(number)
    if len(d) < 10:
        return None
    from friday.core.crypto import get_field_cipher  # noqa: PLC0415

    return get_field_cipher().blind_index(d, label="receptionist-spam")


class ReceptionistStore(Protocol):
    async def get_config(self, user_id: str) -> ReceptionistConfig | None: ...
    async def save_config(self, user_id: str, cfg: ReceptionistConfig) -> None: ...
    async def add_message(self, m: StoredMessage) -> StoredMessage: ...
    async def get_message(self, user_id: str, message_id: str) -> StoredMessage | None: ...
    async def list_messages(
        self, user_id: str, *, since: datetime | None = None, statuses: tuple[MessageStatus, ...] = ()
    ) -> list[StoredMessage]: ...
    async def set_status(
        self, user_id: str, message_id: str, status: MessageStatus, *, notified_at: datetime | None = None
    ) -> bool: ...
    async def block(self, user_id: str, number: str) -> None: ...
    async def unblock(self, user_id: str, number: str) -> bool: ...
    async def is_blocked(self, user_id: str, number: str | None) -> bool: ...
    async def blocked_numbers(self, user_id: str) -> list[str]: ...
    async def count_for_user(self, user_id: str, since: datetime) -> int: ...
    async def count_from_caller(self, number: str | None, since: datetime) -> int: ...
    async def purge_expired(self, now: datetime, snippet_days: int) -> dict[str, int]: ...
    async def delete_user(self, user_id: str) -> int: ...
    async def enabled_user_ids(self) -> list[str]: ...
    async def record_spam(self, number: str | None) -> int: ...
    async def spam_reports(self, number: str | None) -> int: ...


# =============================================================================== memory
class MemoryReceptionistStore:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self.configs: dict[str, ReceptionistConfig] = {}
        self.messages: dict[str, StoredMessage] = {}
        self.blocks: dict[str, set[str]] = {}
        self.spam: dict[str, int] = {}  # keyed hash -> reports (shared, no user)

    async def record_spam(self, number: str | None) -> int:
        k = spam_key(number)
        if k is None:
            return 0
        self.spam[k] = self.spam.get(k, 0) + 1
        return self.spam[k]

    async def spam_reports(self, number: str | None) -> int:
        k = spam_key(number)
        return self.spam.get(k, 0) if k else 0

    async def get_config(self, user_id: str) -> ReceptionistConfig | None:
        c = self.configs.get(user_id)
        return c.model_copy(deep=True) if c else None

    async def save_config(self, user_id: str, cfg: ReceptionistConfig) -> None:
        self.configs[user_id] = cfg.model_copy(deep=True)

    async def add_message(self, m: StoredMessage) -> StoredMessage:
        m = m.model_copy(update={"id": m.id or new_id(), "created_at": m.created_at or self.clock.now()})
        self.messages[m.id] = m
        return m.model_copy()

    async def get_message(self, user_id: str, message_id: str) -> StoredMessage | None:
        m = self.messages.get(message_id)
        return m.model_copy() if m and m.user_id == user_id else None

    async def list_messages(
        self, user_id: str, *, since: datetime | None = None, statuses: tuple[MessageStatus, ...] = ()
    ) -> list[StoredMessage]:
        out = [
            m for m in self.messages.values()
            if m.user_id == user_id
            and (since is None or (m.created_at and m.created_at >= since))
            and (not statuses or m.status in statuses)
        ]  # fmt: skip
        return sorted((m.model_copy() for m in out), key=lambda m: m.created_at or datetime.min)

    async def set_status(
        self, user_id: str, message_id: str, status: MessageStatus, *, notified_at: datetime | None = None
    ) -> bool:
        m = self.messages.get(message_id)
        if m is None or m.user_id != user_id:
            return False
        m.status = status
        if notified_at:
            m.notified_at = notified_at
        return True

    async def block(self, user_id: str, number: str) -> None:
        self.blocks.setdefault(user_id, set()).add(_digits10(number))

    async def unblock(self, user_id: str, number: str) -> bool:
        s = self.blocks.get(user_id, set())
        had = _digits10(number) in s
        s.discard(_digits10(number))
        return had

    async def is_blocked(self, user_id: str, number: str | None) -> bool:
        return bool(number) and _digits10(number) in self.blocks.get(user_id, set())

    async def blocked_numbers(self, user_id: str) -> list[str]:
        return sorted(self.blocks.get(user_id, set()))

    async def count_for_user(self, user_id: str, since: datetime) -> int:
        return sum(
            1 for m in self.messages.values()
            if m.user_id == user_id and m.created_at and m.created_at >= since
        )  # fmt: skip

    async def count_from_caller(self, number: str | None, since: datetime) -> int:
        if not number:
            return 0
        d = _digits10(number)
        return sum(
            1 for m in self.messages.values()
            if _digits10(m.caller_number) == d and m.created_at and m.created_at >= since
        )  # fmt: skip

    async def purge_expired(self, now: datetime, snippet_days: int) -> dict[str, int]:
        cut_snip = now - timedelta(days=snippet_days)
        cut_unr = now - timedelta(days=UNROUTED_KEEP_DAYS)
        snips = unrouted = 0
        for mid, m in list(self.messages.items()):
            if m.user_id is None and m.created_at and m.created_at < cut_unr:
                del self.messages[mid]
                unrouted += 1
            elif m.snippet and m.created_at and m.created_at < cut_snip:
                m.snippet = None
                snips += 1
        return {"snippets_cleared": snips, "unrouted_deleted": unrouted}

    async def enabled_user_ids(self) -> list[str]:
        return sorted(u for u, c in self.configs.items() if c.enabled)

    async def delete_user(self, user_id: str) -> int:
        n = sum(1 for m in self.messages.values() if m.user_id == user_id)
        self.messages = {k: v for k, v in self.messages.items() if v.user_id != user_id}
        self.blocks.pop(user_id, None)
        self.configs.pop(user_id, None)
        return n


# =============================================================================== SQL
def _msg(r: ReceptionistMessageRow) -> StoredMessage:
    return StoredMessage(
        id=r.id, user_id=r.user_id, caller_number=r.caller_number, caller_name=r.caller_name,
        reason=r.reason, urgency=Urgency(r.urgency), snippet=r.snippet,
        callback_number=r.callback_number, outcome=CallOutcomeKind(r.outcome),
        status=MessageStatus(r.status), known_contact_name=r.known_contact_name,
        created_at=r.created_at, notified_at=r.notified_at, duration_s=r.duration_s,
        classification_reasons=list(r.reasons or []),
    )  # fmt: skip


class SqlReceptionistStore(Repo):
    async def record_spam(self, number: str | None) -> int:
        k = spam_key(number)
        if k is None:
            return 0
        async with self.db.session() as s:
            row = (
                await s.execute(select(ReceptionistSpamRow).where(ReceptionistSpamRow.number_hash == k))
            ).scalar_one_or_none()
            if row is None:
                s.add(ReceptionistSpamRow(number_hash=k, reports=1))
                return 1
            row.reports = int(row.reports) + 1
            return int(row.reports)

    async def spam_reports(self, number: str | None) -> int:
        k = spam_key(number)
        if k is None:
            return 0
        async with self.db.session() as s:
            row = (
                await s.execute(select(ReceptionistSpamRow.reports).where(ReceptionistSpamRow.number_hash == k))
            ).scalar_one_or_none()
            return int(row or 0)

    async def get_config(self, user_id: str) -> ReceptionistConfig | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ReceptionistConfigRow).where(ReceptionistConfigRow.user_id == user_id)
                )
            ).scalar_one_or_none()
            return ReceptionistConfig.model_validate(row.config) if row else None

    async def save_config(self, user_id: str, cfg: ReceptionistConfig) -> None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ReceptionistConfigRow).where(ReceptionistConfigRow.user_id == user_id)
                )
            ).scalar_one_or_none()
            data = cfg.model_dump(mode="json")
            if row is None:
                s.add(ReceptionistConfigRow(user_id=user_id, enabled=cfg.enabled, config=data))
            else:
                row.enabled, row.config = cfg.enabled, data

    async def add_message(self, m: StoredMessage) -> StoredMessage:
        async with self.db.session() as s:
            row = ReceptionistMessageRow(
                user_id=m.user_id,
                caller_hash=phone_index(m.caller_number) if m.caller_number else None,
                caller_number=m.caller_number, caller_name=m.caller_name, reason=m.reason,
                snippet=m.snippet, callback_number=m.callback_number,
                known_contact_name=m.known_contact_name, urgency=m.urgency.value,
                outcome=m.outcome.value, status=m.status.value, duration_s=m.duration_s,
                reasons=list(m.classification_reasons),
            )  # fmt: skip
            row.created_at = m.created_at or self.now()
            s.add(row)
            await s.flush()
            return _msg(row)

    async def get_message(self, user_id: str, message_id: str) -> StoredMessage | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ReceptionistMessageRow).where(
                        ReceptionistMessageRow.id == message_id,
                        ReceptionistMessageRow.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return _msg(row) if row else None

    async def list_messages(
        self, user_id: str, *, since: datetime | None = None, statuses: tuple[MessageStatus, ...] = ()
    ) -> list[StoredMessage]:
        q = select(ReceptionistMessageRow).where(ReceptionistMessageRow.user_id == user_id)
        if since is not None:
            q = q.where(ReceptionistMessageRow.created_at >= since)
        if statuses:
            q = q.where(ReceptionistMessageRow.status.in_([x.value for x in statuses]))
        async with self.db.session() as s:
            rows = (await s.execute(q.order_by(ReceptionistMessageRow.created_at))).scalars()
            return [_msg(r) for r in rows]

    async def set_status(
        self, user_id: str, message_id: str, status: MessageStatus, *, notified_at: datetime | None = None
    ) -> bool:
        vals: dict = {"status": status.value}
        if notified_at:
            vals["notified_at"] = notified_at
        async with self.db.session() as s:
            res = await s.execute(
                update(ReceptionistMessageRow)
                .where(
                    ReceptionistMessageRow.id == message_id,
                    ReceptionistMessageRow.user_id == user_id,
                )
                .values(**vals)
            )
            return bool(res.rowcount)

    async def block(self, user_id: str, number: str) -> None:
        h = phone_index(_digits10(number))
        async with self.db.session() as s:
            exists = (
                await s.execute(
                    select(ReceptionistBlockRow.id).where(
                        ReceptionistBlockRow.user_id == user_id, ReceptionistBlockRow.number_hash == h
                    )
                )
            ).first()
            if not exists:
                s.add(ReceptionistBlockRow(user_id=user_id, number_hash=h, number=number))

    async def unblock(self, user_id: str, number: str) -> bool:
        h = phone_index(_digits10(number))
        async with self.db.session() as s:
            res = await s.execute(
                delete(ReceptionistBlockRow).where(
                    ReceptionistBlockRow.user_id == user_id, ReceptionistBlockRow.number_hash == h
                )
            )
            return bool(res.rowcount)

    async def is_blocked(self, user_id: str, number: str | None) -> bool:
        if not number:
            return False
        h = phone_index(_digits10(number))
        async with self.db.session() as s:
            return bool(
                (
                    await s.execute(
                        select(ReceptionistBlockRow.id).where(
                            ReceptionistBlockRow.user_id == user_id,
                            ReceptionistBlockRow.number_hash == h,
                        )
                    )
                ).first()
            )

    async def blocked_numbers(self, user_id: str) -> list[str]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ReceptionistBlockRow.number).where(ReceptionistBlockRow.user_id == user_id)
                )
            ).scalars()
            return sorted(_digits10(n) for n in rows)

    async def count_for_user(self, user_id: str, since: datetime) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count()).select_from(ReceptionistMessageRow).where(
                            ReceptionistMessageRow.user_id == user_id,
                            ReceptionistMessageRow.created_at >= since,
                        )
                    )
                ).scalar_one()
            )

    async def count_from_caller(self, number: str | None, since: datetime) -> int:
        if not number:
            return 0
        h = phone_index(number)
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count()).select_from(ReceptionistMessageRow).where(
                            ReceptionistMessageRow.caller_hash == h,
                            ReceptionistMessageRow.created_at >= since,
                        )
                    )
                ).scalar_one()
            )

    async def purge_expired(self, now: datetime, snippet_days: int) -> dict[str, int]:
        async with self.db.session() as s:
            a = await s.execute(
                update(ReceptionistMessageRow)
                .where(
                    ReceptionistMessageRow.created_at < now - timedelta(days=snippet_days),
                    ReceptionistMessageRow.snippet.is_not(None),
                )
                .values(snippet=None)
            )
            b = await s.execute(
                delete(ReceptionistMessageRow).where(
                    ReceptionistMessageRow.user_id.is_(None),
                    ReceptionistMessageRow.created_at < now - timedelta(days=UNROUTED_KEEP_DAYS),
                )
            )
            return {"snippets_cleared": int(a.rowcount or 0), "unrouted_deleted": int(b.rowcount or 0)}

    async def enabled_user_ids(self) -> list[str]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ReceptionistConfigRow.user_id).where(ReceptionistConfigRow.enabled.is_(True))
                )
            ).scalars()
            return sorted(rows)

    async def delete_user(self, user_id: str) -> int:
        return await purge_user_receptionist_standalone(self, user_id)


async def purge_user_receptionist_standalone(store: SqlReceptionistStore, user_id: str) -> int:
    async with store.db.session() as s:
        counts = await purge_user_receptionist(s, user_id)
    return counts["receptionist_messages"]
