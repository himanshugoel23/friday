"""Life state storage port + an in-memory store + export / erase helpers.

``LifeStore`` is implemented by ``friday.db.repositories.lifestate.LifeRepo`` (the real, encrypted
store: ``container.repos.life``) and by ``MemoryLifeStore`` (tests, simulator). Every call takes the
``user_id`` and only ever sees that user's rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from friday.lifestate.models import (
    Followup,
    LifeCommitment,
    LifeEvent,
    TopicPref,
    aware,
)


@runtime_checkable
class LifeStore(Protocol):
    async def save_event(self, e: LifeEvent) -> LifeEvent: ...
    async def get_event(self, user_id: str, event_id: str) -> LifeEvent | None: ...
    async def find_event_by_ref(
        self, user_id: str, source: str, source_ref: str
    ) -> LifeEvent | None: ...
    async def events_between(
        self, user_id: str, start: datetime, end: datetime, *, include_inactive: bool = False
    ) -> list[LifeEvent]: ...
    async def list_events(
        self, user_id: str, *, include_inactive: bool = True
    ) -> list[LifeEvent]: ...
    async def delete_event(self, user_id: str, event_id: str) -> bool: ...
    async def save_commitment(self, c: LifeCommitment) -> LifeCommitment: ...
    async def get_commitment(self, user_id: str, commitment_id: str) -> LifeCommitment | None: ...
    async def list_commitments(
        self, user_id: str, *, status: str | None = None
    ) -> list[LifeCommitment]: ...
    async def delete_commitment(self, user_id: str, commitment_id: str) -> bool: ...
    async def set_topic(
        self, user_id: str, topic: str, *, muted: bool | None = None, channel: str | None = None
    ) -> TopicPref: ...
    async def list_topics(self, user_id: str) -> list[TopicPref]: ...
    async def get_followup(self, user_id: str, key: str) -> Followup | None: ...
    async def save_followup(self, f: Followup) -> Followup: ...
    async def list_followups(
        self, user_id: str, *, since: datetime | None = None
    ) -> list[Followup]: ...
    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int: ...
    async def delete_all(self, user_id: str) -> dict[str, int]: ...


class MemoryLifeStore:
    """Same contract as ``LifeRepo``, in memory. Rows are copied in and out."""

    def __init__(self) -> None:
        self._events: dict[str, LifeEvent] = {}
        self._commitments: dict[str, LifeCommitment] = {}
        self._topics: dict[tuple[str, str], TopicPref] = {}
        self._followups: dict[tuple[str, str], Followup] = {}

    # events
    async def save_event(self, e: LifeEvent) -> LifeEvent:
        old = self._events.get(e.id)
        if old is not None and old.user_id != e.user_id:
            raise PermissionError("event belongs to another user")
        self._events[e.id] = e.model_copy(deep=True)
        return e

    async def get_event(self, user_id: str, event_id: str) -> LifeEvent | None:
        e = self._events.get(event_id)
        return e.model_copy(deep=True) if e and e.user_id == user_id else None

    async def find_event_by_ref(
        self, user_id: str, source: str, source_ref: str
    ) -> LifeEvent | None:
        for e in self._events.values():
            if e.user_id == user_id and e.source == source and e.source_ref == source_ref:
                return e.model_copy(deep=True)
        return None

    async def events_between(
        self, user_id: str, start: datetime, end: datetime, *, include_inactive: bool = False
    ) -> list[LifeEvent]:
        out = [
            e.model_copy(deep=True)
            for e in self._events.values()
            if e.user_id == user_id
            and (include_inactive or e.status == "active")
            and e.overlaps(start, end)
        ]
        return sorted(out, key=lambda e: e.start)

    async def list_events(self, user_id: str, *, include_inactive: bool = True) -> list[LifeEvent]:
        out = [
            e.model_copy(deep=True)
            for e in self._events.values()
            if e.user_id == user_id and (include_inactive or e.status == "active")
        ]
        return sorted(out, key=lambda e: e.start)

    async def delete_event(self, user_id: str, event_id: str) -> bool:
        e = self._events.get(event_id)
        if e is None or e.user_id != user_id:
            return False
        del self._events[event_id]
        return True

    # commitments
    async def save_commitment(self, c: LifeCommitment) -> LifeCommitment:
        old = self._commitments.get(c.id)
        if old is not None and old.user_id != c.user_id:
            raise PermissionError("commitment belongs to another user")
        self._commitments[c.id] = c.model_copy(deep=True)
        return c

    async def get_commitment(self, user_id: str, commitment_id: str) -> LifeCommitment | None:
        c = self._commitments.get(commitment_id)
        return c.model_copy(deep=True) if c and c.user_id == user_id else None

    async def list_commitments(
        self, user_id: str, *, status: str | None = None
    ) -> list[LifeCommitment]:
        out = [
            c.model_copy(deep=True)
            for c in self._commitments.values()
            if c.user_id == user_id and (status is None or c.status == status)
        ]
        return sorted(out, key=lambda c: c.due)

    async def delete_commitment(self, user_id: str, commitment_id: str) -> bool:
        c = self._commitments.get(commitment_id)
        if c is None or c.user_id != user_id:
            return False
        del self._commitments[commitment_id]
        return True

    # topics
    async def set_topic(
        self, user_id: str, topic: str, *, muted: bool | None = None, channel: str | None = None
    ) -> TopicPref:
        cur = self._topics.get((user_id, topic)) or TopicPref(topic=topic)
        data = cur.model_dump()
        if muted is not None:
            data["muted"] = muted
        if channel is not None:
            data["channel"] = channel
        pref = TopicPref.model_validate(data)
        self._topics[(user_id, topic)] = pref
        return pref

    async def list_topics(self, user_id: str) -> list[TopicPref]:
        return [p.model_copy() for (u, _), p in self._topics.items() if u == user_id]

    # follow-up log
    async def get_followup(self, user_id: str, key: str) -> Followup | None:
        f = self._followups.get((user_id, key))
        return f.model_copy(deep=True) if f else None

    async def save_followup(self, f: Followup) -> Followup:
        self._followups[(f.user_id, f.key)] = f.model_copy(deep=True)
        return f

    async def list_followups(
        self, user_id: str, *, since: datetime | None = None
    ) -> list[Followup]:
        out = [
            f.model_copy(deep=True)
            for (u, _), f in self._followups.items()
            if u == user_id and (since is None or f.created_at >= aware(since))
        ]
        return sorted(out, key=lambda f: f.created_at)

    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int:
        s, e = aware(start), aware(end)
        return sum(
            1
            for (u, _), f in self._followups.items()
            if u == user_id
            and f.status == "sent"
            and f.topic != "morning_brief"
            and f.sent_at is not None
            and s <= f.sent_at < e
        )

    async def delete_all(self, user_id: str) -> dict[str, int]:
        counts = {}
        for name, table in (
            ("life_followups", self._followups),
            ("mute_topics", self._topics),
            ("life_commitments", self._commitments),
            ("life_events", self._events),
        ):
            doomed = [
                k
                for k, v in table.items()
                if (k[0] if isinstance(k, tuple) else v.user_id) == user_id
            ]
            for k in doomed:
                del table[k]
            counts[name] = len(doomed)
        return counts


# --------------------------------------------------------------------------- export / erase


async def export_life_state(store: LifeStore, user_id: str) -> dict[str, Any]:
    """The user's whole life state as plain JSON-able data (decrypted: it is THEIR data)."""
    events = await store.list_events(user_id)
    commitments = await store.list_commitments(user_id)
    topics = await store.list_topics(user_id)
    followups = await store.list_followups(user_id)
    return {
        "format": "friday-life-state-v1",
        "user_id": user_id,
        "events": [e.model_dump(mode="json") for e in events],
        "commitments": [c.model_dump(mode="json") for c in commitments],
        "topic_preferences": [t.model_dump(mode="json") for t in topics],
        "messages_sent": [f.model_dump(mode="json") for f in followups],
    }


async def delete_everything(store: LifeStore, user_id: str) -> dict[str, int]:
    """Hard-delete the user's whole life state. Returns per-table counts (no personal text)."""
    return await store.delete_all(user_id)
