"""Memory controls: the user sees, changes, exports and erases what Friday remembers.

    "tumhe kya yaad hai"          -> summary of events, reminders, muted topics
    "bhool jao dentist"           -> deletes the matching item (asks to be clearer if several match)
    "interview ko 3 baje kar do"  -> moves the event
    "mera data export karo"       -> the whole life state as JSON (the caller sends it as a file)
    "sab delete karo"             -> asks for the exact phrase "haan, sab mita do"; only that exact
                                     phrase erases everything (stateless: nothing to time out)

Everything is scoped to the calling ``user_id``; nothing here can see another user's rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from friday.core.clock import Clock, to_ist
from friday.lifestate import copy
from friday.lifestate.capture import _combine, _resolve_hour, parse_when
from friday.lifestate.kinds import guess_kind
from friday.lifestate.models import (
    EventKind,
    EventSource,
    EventStatus,
    LifeCommitment,
    LifeEvent,
    aware,
    display_title,
)
from friday.lifestate.store import LifeStore, delete_everything, export_life_state

_I = re.IGNORECASE
_REMEMBER = re.compile(
    r"(kya\s+(?:kya\s+)?yaad\s+hai|what\s+do\s+you\s+remember|kya\s+yaad\s+rakha|"
    r"meri\s+memory|my\s+memory|mere\s+baare\s+mein\s+kya)",
    _I,
)
_EXPORT = re.compile(
    r"\b(export|download|mera\s+data\s+(?:do|bhejo|chahiye|dikhao)|meri\s+saari\s+jaankari)\b", _I
)
_DELETE_ALL = re.compile(
    r"(?:\b(?:sab|saara|saari|poora|puri|everything|all)\b.{0,25}"
    r"\b(?:delete|mita|mitao|hata|bhool|bhul|erase|forget)\b)|"
    r"(?:\b(?:delete|erase|forget)\s+(?:everything|all|my\s+data))",
    _I,
)
_CONFIRM_DELETE = re.compile(
    r"^\s*(?:haan|han|yes)[,.]?\s*(?:sab\s+mita\s+do|delete\s+everything)\s*[.!]?\s*$", _I
)
_FORGET = re.compile(
    r"^\s*(?:(?:bhool|bhul)\s+jao|forget|hata\s+do|hata\s+dena|delete|mita\s+do|remove)\s+(?P<q>.+?)\s*[.!]?$",
    _I,
)
_FORGET_AFTER = re.compile(
    r"^\s*(?P<q>.+?)\s+(?:bhool\s+jao|bhul\s+jao|delete\s+karo|delete\s+kar\s+do|hata\s+do|"
    r"mita\s+do|forget)\s*[.!]?$",
    _I,
)
_EDIT = re.compile(
    r"^\s*(?P<q>.+?)\s+(?:ko|ka\s+time|ka\s+samay|ki\s+timing)\s+(?P<w>.+?)\s+"
    r"(?:kar\s+do|kardo|karo|kar\s+dena|badal\s+do|shift\s+karo|rakh\s+do)\s*[.!]?$",
    _I,
)
_QUERY_NOISE = {
    "wo",
    "woh",
    "vo",
    "ye",
    "yeh",
    "wala",
    "wali",
    "ka",
    "ki",
    "ke",
    "event",
    "reminder",
    "ko",
}


@dataclass
class MemoryReply:
    handled: bool
    text: str | None = None
    action: str | None = None  # remember | forget | edit | export | delete_prompt | delete_all
    export: dict[str, Any] | None = None
    counts: dict[str, int] = field(default_factory=dict)


class MemoryControls:
    def __init__(self, store: LifeStore, clock: Clock) -> None:
        self.store, self.clock = store, clock

    async def handle(self, user_id: str, text: str) -> MemoryReply:
        t = (text or "").strip()
        if not t or len(t) > 300:
            return MemoryReply(False)
        if _CONFIRM_DELETE.match(t):
            counts = await delete_everything(self.store, user_id)
            return MemoryReply(True, copy.delete_all_done(), "delete_all", counts=counts)
        if _EXPORT.search(t):
            data = await export_life_state(self.store, user_id)
            return MemoryReply(True, copy.export_ready(), "export", export=data)
        if _DELETE_ALL.search(t):
            return MemoryReply(True, copy.delete_all_prompt(), "delete_prompt")
        if _REMEMBER.search(t):
            return MemoryReply(True, await self.summary(user_id), "remember")
        if m := _EDIT.match(t):
            return await self.reschedule(user_id, m.group("q"), m.group("w"))
        m = _FORGET.match(t) or _FORGET_AFTER.match(t)
        if m:
            return await self.forget(user_id, m.group("q"))
        return MemoryReply(False)

    # ------------------------------------------------------------------ view
    async def summary(self, user_id: str) -> str:
        now = self.clock.now()
        events = [
            e
            for e in await self.store.list_events(user_id, include_inactive=False)
            if e.end >= now - timedelta(days=1)
        ][:8]
        commitments = (await self.store.list_commitments(user_id, status="open"))[:8]
        prefs = [p for p in await self.store.list_topics(user_id) if p.muted]
        if not (events or commitments or prefs):
            return copy.remember_empty()
        ev_lines = [
            f"{copy.fmt_when(e.start, now)}: "
            f"{e.title if e.source == EventSource.USER else display_title(e)}"
            for e in events
        ]
        co_lines = [
            f"{copy.fmt_when(c.due, now)}: {c.text}" + (" (repeat)" if c.repeat else "")
            for c in commitments
        ]
        return copy.remember_summary(ev_lines, co_lines, [copy.topic_label(p.topic) for p in prefs])

    # ------------------------------------------------------------------ forget
    async def _matches(
        self, user_id: str, query: str
    ) -> tuple[list[LifeEvent], list[LifeCommitment]]:
        words = [w for w in re.findall(r"\w+", query.lower()) if w not in _QUERY_NOISE]
        if not words:
            return [], []
        kind = guess_kind(query)

        def hit(blob: str, k: EventKind | None) -> bool:
            b = blob.lower()
            return all(w in b for w in words) or (
                k is not None and kind != EventKind.OTHER and k == kind and len(words) == 1
            )

        events = [
            e
            for e in await self.store.list_events(user_id)
            if hit(f"{e.title} {e.note or ''}", e.kind)
        ]
        commits = [c for c in await self.store.list_commitments(user_id) if hit(c.text, None)]
        return events, commits

    async def forget(self, user_id: str, query: str) -> MemoryReply:
        q = query.strip()
        every = bool(re.match(r"^(?:sab|saare|saari|all)\s+", q, _I))
        if every:
            q = re.sub(r"^(?:sab|saare|saari|all)\s+", "", q, flags=_I)
        events, commits = await self._matches(user_id, q)
        total = len(events) + len(commits)
        if total == 0:
            return MemoryReply(True, copy.forget_none(q), "forget")
        if total > 1 and not every:
            now = self.clock.now()
            names = [f"{copy.fmt_when(e.start, now)} {e.title}" for e in events] + [
                f"{copy.fmt_when(c.due, now)} {c.text}" for c in commits
            ]
            return MemoryReply(True, copy.forget_ambiguous(names[:6]), "forget")
        for e in events:
            await self.store.delete_event(user_id, e.id)
        for c in commits:
            await self.store.delete_commitment(user_id, c.id)
        return MemoryReply(True, copy.forgot(total), "forget", counts={"deleted": total})

    # ------------------------------------------------------------------ edit
    async def reschedule(self, user_id: str, query: str, when_text: str) -> MemoryReply:
        events, _ = await self._matches(user_id, query)
        events = [e for e in events if e.status == EventStatus.ACTIVE]
        if len(events) != 1:
            return MemoryReply(True, copy.edit_none(), "edit")
        ev = events[0]
        now = aware(self.clock.now())
        w = parse_when(when_text, now)
        if w.clock is None and w.day is None:
            return MemoryReply(True, copy.edit_none(), "edit")
        day = w.day or to_ist(ev.start).date()
        if w.clock is not None:
            hour, shift, issue = _resolve_hour(w.clock, w.period, False)
            if issue:
                return MemoryReply(True, copy.ask_am_pm(12), "edit")
            start = _combine(day, hour, w.clock.minute, 1 if shift else 0)
        else:
            local = to_ist(ev.start)
            start = _combine(day, local.hour, local.minute)
        ev.end = start + (ev.end - ev.start)
        ev.start = start
        await self.store.save_event(ev)
        return MemoryReply(True, copy.edit_done(ev.kind, copy.fmt_when(ev.start, now)), "edit")
