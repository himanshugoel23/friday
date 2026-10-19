"""Bill reminders (W3) and life-state follow-ups + morning brief (W4) as ProactiveEngine inputs.

They are registered on the existing engine (``register_source`` / ``register_briefing_provider`` /
``register_sent_hook``), so ONE tick runs everything through the same ``process()`` path: the
daily cap (3, shared with every other nudge), quiet hours, dedupe by key, ignore-learning, the
digest for the over-cap overflow. Nothing here sends a message.

Dedupe between the two packages: W3 owns the reminders of the bills it tracks. A W4 "bill due" item
whose due day matches an active W3 bill of the same user is skipped, so a forwarded bill that the
user also mentioned in words is reminded once.

The wording is the packages' own (savings/copy.py, lifestate/copy.py), carried on the candidate as
``fixed_text`` so the brain does not rewrite approved text.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from friday.core.clock import Clock, is_quiet_hours, to_ist
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import NudgeCandidate, Urgency
from friday.lifestate.followups import (
    BRIEF_HOUR,
    _nudge_kind,
    build_morning_brief,
    is_muted,
    plan_followups,
    render,
    why_of,
)
from friday.lifestate.models import EventKind, Followup
from friday.lifestate.now import busy_until
from friday.lifestate.ports import BillRef, BillsPort, TravelBufferHook
from friday.lifestate.store import LifeStore
from friday.savings.bills import Bill, bill_reminders
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig

log = get_logger(__name__)

ActiveBills = Callable[[str], Awaitable[list[Bill]]]


def _fixed(c: NudgeCandidate) -> NudgeCandidate:
    """Copy the package's own text and buttons into the keys the engine sends as is."""
    data = dict(c.data)
    if data.get("text"):
        data["fixed_text"] = data["text"]
    if data.get("buttons"):
        data["fixed_buttons"] = data["buttons"]
    return c.model_copy(update={"data": data})


class BillReminderSource:
    """W3's ``bill_reminders`` for one user: 3 days before, 1 day before, on the day (IST 09:00)."""

    def __init__(
        self, active_bills: ActiveBills, clock: Clock, config: SavingsConfig = DEFAULT_CONFIG
    ) -> None:
        self.active_bills, self.clock, self.config = active_bills, clock, config

    async def __call__(self, user_id: str, now: datetime) -> list[NudgeCandidate]:
        bills = await self.active_bills(user_id)
        return [_fixed(c) for c in bill_reminders(user_id, bills, now, self.config)]


class SavingsBillsPort(BillsPort):
    """W3's bills as the life state sees them (for the morning brief and for dedupe)."""

    def __init__(self, active_bills: ActiveBills) -> None:
        self.active_bills = active_bills

    async def pending_bills(self, user_id: str, now: datetime) -> list[BillRef]:
        return [
            BillRef(id=b.id, due_on=b.due_date, biller=b.biller, pay_link=b.pay_link)
            for b in await self.active_bills(user_id)
            if b.confirmed
        ]


def topic_of_key(key: str, kind: EventKind | None) -> tuple[str, str | None]:
    """(topic, event id) from a follow-up dedupe key such as ``after:<event>:<ts>``."""
    head, _, rest = key.partition(":")
    event_id = rest.split(":")[0] if rest else None
    if head == "after":
        return f"after_event:{kind.value if kind else 'other'}", event_id
    if head == "before":
        return f"before_event:{kind.value if kind else 'other'}", event_id
    if head in ("bill", "billref"):
        return "bill_due", None if head == "billref" else event_id
    if head == "commit":
        return "commitment", None
    return head, None


class LifeFollowupSource:
    """W4's event-aware follow-ups as candidates. Mirrors ``FollowupScheduler._consider`` for the
    parts that need life-state knowledge (expiry, muted topics, protected events, quiet hours); the
    engine then applies the shared caps and dedupe."""

    def __init__(
        self,
        store: LifeStore,
        settings: Settings,
        clock: Clock,
        *,
        travel: TravelBufferHook | None = None,
        active_bills: ActiveBills | None = None,
    ) -> None:
        self.store, self.settings, self.clock = store, settings, clock
        self.travel, self.active_bills = travel, active_bills

    async def __call__(self, user_id: str, now: datetime) -> list[NudgeCandidate]:
        events = await self.store.events_between(
            user_id, now - timedelta(hours=14), now + timedelta(days=3)
        )
        commitments = await self.store.list_commitments(user_id, status="open")
        prefs = await self.store.list_topics(user_id)
        travel_minutes: dict[str, int] = {}
        if self.travel:
            for e in events:
                if e.location and e.start > now:
                    mins = await self.travel.minutes_needed(e)
                    if mins:
                        travel_minutes[e.id] = mins
        w3_days: set[date] = set()
        if self.active_bills is not None:
            w3_days = {b.due_date for b in await self.active_bills(user_id) if b.confirmed}
        plan = plan_followups(events, commitments, now, travel_minutes=travel_minutes)
        out: list[NudgeCandidate] = []
        quiet = is_quiet_hours(now, self.settings.quiet_hours_start, self.settings.quiet_hours_end)
        protected_until = busy_until(events, now, protected_only=True)
        for p in plan:
            if p.due_at > now or now >= p.expires_at:
                continue
            if await self.store.get_followup(user_id, p.key):
                continue
            if p.base_topic == "bill_due" and to_ist(p.subject_start or p.due_at).date() in w3_days:
                continue  # W3 already reminds this bill
            if is_muted(prefs, p.topic):
                await self._record(user_id, p, "muted", now)
                continue
            if p.urgency != Urgency.URGENT and (protected_until is not None or quiet):
                continue  # not now; asked again on the next tick while it is still fresh
            kind, category = _nudge_kind(p)
            out.append(
                NudgeCandidate(
                    user_id=user_id,
                    kind=kind,
                    category=category,
                    urgency=p.urgency,
                    reason=why_of(p),
                    due_at=p.due_at,
                    dedupe_key=p.key,
                    data={
                        "expires_at": p.expires_at,
                        "fixed_text": render(p, now),
                        "topic": p.topic,
                        "event_id": p.event_id,
                    },
                )
            )
        return out

    async def _record(self, user_id: str, p: Any, status: str, now: datetime) -> None:
        await self.store.save_followup(
            Followup(
                user_id=user_id, key=p.key, topic=p.topic, event_id=p.event_id, status=status,  # type: ignore[arg-type]
                due_at=p.due_at, created_at=now,
            )
        )  # fmt: skip

    # ------------------------------------------------------------------ after the engine sent it
    async def on_sent(self, nudge: Any, cand: NudgeCandidate) -> None:
        """Record the follow-up as sent, so W4's reply handling ("interview achha gaya") and its
        ignore tracking see it. Only keys this source can have produced are recorded."""
        key = cand.dedupe_key
        if key.split(":")[0] not in ("after", "before", "bill", "commit"):
            return
        if await self.store.get_followup(nudge.user_id, key):
            return
        topic = cand.data.get("topic")
        event_id = cand.data.get("event_id")
        if topic is None:
            ev_id = key.split(":")[1] if ":" in key else None
            ev = await self.store.get_event(nudge.user_id, ev_id) if ev_id else None
            topic, event_id = topic_of_key(key, ev.kind if ev else None)
            event_id = event_id or (ev.id if ev else None)
        now = self.clock.now()
        await self.store.save_followup(
            Followup(
                user_id=nudge.user_id, key=key, topic=topic, event_id=event_id, status="sent",
                text=nudge.text, due_at=cand.due_at, sent_at=now, created_at=now,
            )
        )  # fmt: skip


class LifeBriefingProvider:
    """W4's morning brief as the TEXT of the engine's morning briefing (same opt-in, key, hour
    window, quiet hours and digest delivery as before)."""

    def __init__(
        self,
        store: LifeStore,
        clock: Clock,
        *,
        bills: BillsPort | None = None,
        travel: TravelBufferHook | None = None,
    ) -> None:
        self.store, self.clock, self.bills, self.travel = store, clock, bills, travel

    async def __call__(self, user_id: str, now: datetime, digest_lines: list[str]) -> str | None:
        if to_ist(now).hour < BRIEF_HOUR:
            return None
        prefs = await self.store.list_topics(user_id)
        if is_muted(prefs, "morning_brief"):
            return ""  # the user muted the brief: drop the generic one too
        brief = await build_morning_brief(
            self.store, user_id, now, bills=self.bills, travel=self.travel,
            digest_lines=digest_lines,
        )  # fmt: skip
        return brief.text  # None keeps the generic briefing text
