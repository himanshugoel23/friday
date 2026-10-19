"""What is the user doing right now, and a short safe summary for other channels.

``now_status`` is derived (never stored) from the user's events and the quiet hours.
``context_summary`` is what the front door / live call engine inject so every channel knows the
context. It carries only kinds, times and counts: never a title, note, location or person name.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import at_ist, ensure_utc, is_quiet_hours, next_quiet_hours_end, to_ist
from friday.core.config import Settings
from friday.lifestate import copy
from friday.lifestate.models import (
    EventKind,
    EventStatus,
    LifeEvent,
    NowState,
    NowStatus,
    UserContext,
    aware,
)
from friday.lifestate.ports import BillsPort
from friday.lifestate.store import LifeStore

LOOKAHEAD = timedelta(hours=14)


def _busy(events: list[LifeEvent]) -> list[LifeEvent]:
    """Events that occupy the user (bills and cancelled/done events do not)."""
    return [
        e
        for e in events
        if e.status == EventStatus.ACTIVE and e.kind != EventKind.BILL_DUE and e.end > e.start
    ]


def busy_until(
    events: list[LifeEvent], at: datetime, *, protected_only: bool = False
) -> datetime | None:
    """End of the contiguous busy block that covers ``at`` (back-to-back events are chained), or
    None when the user is free at ``at``."""
    at = aware(at)
    pool = [e for e in _busy(events) if e.protected or not protected_only]
    covering = [e for e in pool if e.start <= at < e.end]
    if not covering:
        return None
    end = max(e.end for e in covering)
    changed = True
    while changed:
        changed = False
        for e in pool:
            if e.start <= end < e.end:
                end, changed = e.end, True
    return end


def compute_now_status(
    events: list[LifeEvent],
    at: datetime,
    *,
    quiet_start: int = 22,
    quiet_end: int = 8,
) -> NowStatus:
    at = aware(at)
    active = [e for e in _busy(events) if e.start <= at < e.end]
    if active:
        # the protected one wins, then the one that ends last
        primary = sorted(active, key=lambda e: (not e.protected, -e.end.timestamp()))[0]
        end = busy_until(events, at) or primary.end
        state = NowState.TRAVELLING if primary.kind == EventKind.TRAVEL else NowState.IN_EVENT
        return NowStatus(
            state=state,
            at=at,
            kind=primary.kind,
            ends_at=end,
            event_id=primary.id,
            protected=any(e.protected for e in active),
        )
    if is_quiet_hours(at, quiet_start, quiet_end):
        return NowStatus(
            state=NowState.QUIET_HOURS,
            at=at,
            ends_at=next_quiet_hours_end(at, quiet_start, quiet_end),
        )
    return NowStatus(state=NowState.FREE, at=at)


def _quiet(settings: Settings | None) -> tuple[int, int]:
    if settings is None:
        return 22, 8
    return settings.quiet_hours_start, settings.quiet_hours_end


async def now_status(
    store: LifeStore, user_id: str, at: datetime, settings: Settings | None = None
) -> NowStatus:
    at = aware(at)
    # events that started up to a day ago may still cover ``at`` (e.g. a night train)
    events = await store.events_between(user_id, at - timedelta(days=1), at + LOOKAHEAD)
    qs, qe = _quiet(settings)
    return compute_now_status(events, at, quiet_start=qs, quiet_end=qe)


async def build_user_context(
    store: LifeStore,
    user_id: str,
    at: datetime,
    settings: Settings | None = None,
    bills: BillsPort | None = None,
) -> UserContext:
    at = aware(at)
    status = await now_status(store, user_id, at, settings)
    day_start = at_ist(to_ist(at).date(), 0)
    day_end = day_start + timedelta(days=1)
    today = [
        e
        for e in await store.events_between(user_id, day_start, day_end)
        if e.kind != EventKind.BILL_DUE
    ]
    upcoming = sorted(
        (
            e
            for e in _busy(await store.events_between(user_id, at, at + timedelta(days=2)))
            if e.start > at
        ),
        key=lambda e: e.start,
    )
    week = await store.events_between(user_id, at, at + timedelta(days=7))
    bill_events = [e for e in week if e.kind == EventKind.BILL_DUE]
    n_bills = len(bill_events)
    if bills is not None:
        due_cut = (to_ist(at) + timedelta(days=7)).date()
        refs = await bills.pending_bills(user_id, at)
        n_bills = max(n_bills, sum(1 for b in refs if b.due_on <= due_cut))
    commits = [
        c
        for c in await store.list_commitments(user_id, status="open")
        if day_start <= c.due < day_end
    ]
    return UserContext(
        at=at,
        status=status,
        next_kind=upcoming[0].kind if upcoming else None,
        next_start=upcoming[0].start if upcoming else None,
        events_today=len(today),
        bills_due_this_week=n_bills,
        commitments_open_today=len(commits),
    )


def _hhmm(dt: datetime) -> str:
    return to_ist(ensure_utc(dt)).strftime("%H:%M IST")


def render_context(ctx: UserContext) -> str:
    st = ctx.status
    if st.state == NowState.IN_EVENT and st.kind and st.ends_at:
        now_txt = copy.ctx_in_event(st.kind, _hhmm(st.ends_at), st.protected)
    elif st.state == NowState.TRAVELLING and st.ends_at:
        now_txt = copy.ctx_travelling(_hhmm(st.ends_at))
    elif st.state == NowState.QUIET_HOURS and st.ends_at:
        now_txt = copy.ctx_quiet(_hhmm(st.ends_at))
    else:
        now_txt = copy.ctx_free()
    parts = [f"now: {now_txt}"]
    if ctx.next_kind and ctx.next_start:
        parts.append(f"next: {ctx.next_kind.value} at {_hhmm(ctx.next_start)}")
    if ctx.events_today:
        parts.append(f"events today: {ctx.events_today}")
    if ctx.bills_due_this_week:
        parts.append(f"bills due this week: {ctx.bills_due_this_week}")
    if ctx.commitments_open_today:
        parts.append(f"reminders today: {ctx.commitments_open_today}")
    return "; ".join(parts)


async def context_summary(
    store: LifeStore,
    user_id: str,
    at: datetime,
    settings: Settings | None = None,
    bills: BillsPort | None = None,
) -> str:
    """One short line: ``now: in event (interview) until 15:00 IST; bills due this week: 2``."""
    return render_context(await build_user_context(store, user_id, at, settings, bills))
