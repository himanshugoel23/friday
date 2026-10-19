"""Bring events in from outside: a calendar (read-only), booking outcomes, call outcomes.

* ``sync_calendar`` imports a window of the user's calendar through a ``CalendarPort`` into life
  events: deduped by ``(source=calendar, source_ref=<calendar event id>)``, moved events are
  updated, events that vanished from the window are marked cancelled. The port can only READ; this
  module never creates, edits or deletes anything in the user's calendar (writing back is a
  separate, explicit action elsewhere, see friday/google/calendar.py).
* If the calendar cannot be read the sync changes NOTHING (a failed fetch must not look like "all
  events cancelled").
* Titles from the calendar are untrusted data: stored (cleaned and shortened), classified into a
  kind by fixed word lists, never interpreted.
* ``check_booking_slot`` is the clash check used before accepting a booking time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from friday.core.logging import get_logger
from friday.lifestate.kinds import default_protected, guess_kind
from friday.lifestate.models import (
    EventKind,
    EventSource,
    EventStatus,
    LifeEvent,
    aware,
    clean_text,
    default_duration,
)
from friday.lifestate.ports import CalendarPort
from friday.lifestate.store import LifeStore

log = get_logger(__name__)

MERGE_TOLERANCE = timedelta(minutes=15)
DEFAULT_BUFFER = timedelta(minutes=15)


# --------------------------------------------------------------------------- clash check
def _occupies(e: LifeEvent) -> bool:
    return e.status == EventStatus.ACTIVE and e.kind != EventKind.BILL_DUE and e.end > e.start


async def find_clashes(
    store: LifeStore,
    user_id: str,
    start: datetime,
    end: datetime,
    *,
    buffer: timedelta = timedelta(0),
    exclude_id: str | None = None,
) -> list[LifeEvent]:
    """Active events that overlap [start, end) once each side is widened by ``buffer``."""
    s, e = aware(start) - buffer, aware(end) + buffer
    found = await store.events_between(user_id, s, e)
    return [x for x in found if _occupies(x) and x.id != exclude_id]


@dataclass
class ClashResult:
    ok: bool
    clashes: list[LifeEvent] = field(default_factory=list)
    calendar_clashes: int = 0
    calendar_checked: bool = False

    @property
    def count(self) -> int:
        return len(self.clashes) + self.calendar_clashes


async def check_booking_slot(
    store: LifeStore,
    user_id: str,
    start: datetime,
    end: datetime,
    *,
    buffer: timedelta = DEFAULT_BUFFER,
    calendar: CalendarPort | None = None,
) -> ClashResult:
    """Call before accepting a time a vendor offers: does it collide with the user's day?
    Uses the stored life state and, when a calendar port is given, a live read of that slot."""
    clashes = await find_clashes(store, user_id, start, end, buffer=buffer)
    cal_n, checked = 0, False
    if calendar is not None:
        try:
            live = await calendar.list_events(aware(start) - buffer, aware(end) + buffer)
            checked = True
            known = {c.source_ref for c in clashes if c.source == EventSource.CALENDAR}
            cal_n = sum(
                1
                for ev in live
                if getattr(ev, "busy", True)
                and getattr(ev, "status", "confirmed") != "cancelled"
                and str(ev.id) not in known
            )
        except Exception:  # noqa: BLE001 - an unreadable calendar must not block, but is reported
            log.warning("calendar unreadable during clash check")
    return ClashResult(
        ok=not clashes and cal_n == 0,
        clashes=clashes,
        calendar_clashes=cal_n,
        calendar_checked=checked,
    )


# --------------------------------------------------------------------------- bookings and calls
async def record_booking(
    store: LifeStore,
    user_id: str,
    *,
    title: str,
    start: datetime,
    end: datetime | None = None,
    task_id: str,
    kind: EventKind = EventKind.APPOINTMENT,
    location: str | None = None,
    source: EventSource = EventSource.BOOKING,
) -> LifeEvent:
    """Add (or update) the event for an appointment Friday booked. Idempotent per ``task_id``."""
    start = aware(start)
    end = aware(end) if end else start + default_duration(kind)
    existing = await store.find_event_by_ref(user_id, source.value, task_id)
    ev = existing or LifeEvent(
        user_id=user_id,
        title=title,
        start=start,
        end=end,
        kind=kind,
        source=source,
        source_ref=task_id,
    )
    ev.title, ev.start, ev.end, ev.kind = clean_text(title) or "(no title)", start, end, kind
    ev.location = clean_text(location, 200) or None if location else ev.location
    ev.protected = default_protected(kind)
    if existing is None or existing.status != EventStatus.CANCELLED:
        ev.status = EventStatus.ACTIVE
    return await store.save_event(ev)


async def record_booking_from_task(store: LifeStore, task: object) -> LifeEvent | None:
    """Booking outcome of a finished task -> a protected appointment event (source ``booking``).

    Duck-typed on ``friday.core.models.Task`` (id, requester_user_id, status, target.name,
    result.success / result.appointment_at) so this module does not import the task engine."""
    result = getattr(task, "result", None)
    status = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
    if result is None or status != "completed" or not result.success or not result.appointment_at:
        return None
    name = getattr(getattr(task, "target", None), "name", None)
    return await record_booking(
        store,
        task.requester_user_id,  # type: ignore[attr-defined]
        title=f"Appointment at {name}" if name else "Appointment",
        start=result.appointment_at,
        task_id=task.id,  # type: ignore[attr-defined]
    )


async def record_call_outcome(
    store: LifeStore,
    user_id: str,
    *,
    call_id: str,
    title: str,
    start: datetime,
    end: datetime | None = None,
    kind: EventKind = EventKind.APPOINTMENT,
) -> LifeEvent:
    """W1 call outcomes ("plumber will come Thursday 4 pm") become events, deduped per call."""
    return await record_booking(
        store,
        user_id,
        title=title,
        start=start,
        end=end,
        task_id=call_id,
        kind=kind,
        source=EventSource.CALL_OUTCOME,
    )


async def cancel_booking(
    store: LifeStore, user_id: str, task_id: str, *, source: EventSource = EventSource.BOOKING
) -> bool:
    ev = await store.find_event_by_ref(user_id, source.value, task_id)
    if ev is None or ev.status == EventStatus.CANCELLED:
        return False
    ev.status = EventStatus.CANCELLED
    await store.save_event(ev)
    return True


# --------------------------------------------------------------------------- calendar import
@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    unchanged: int = 0
    skipped: int = 0  # free/transparent entries
    merged: int = 0  # already known from what the user told Friday
    error: str | None = None

    @property
    def changed(self) -> int:
        return self.created + self.updated + self.cancelled


async def sync_calendar(
    store: LifeStore,
    user_id: str,
    port: CalendarPort,
    now: datetime,
    *,
    window: timedelta = timedelta(days=14),
    lookback: timedelta = timedelta(hours=12),
) -> SyncReport:
    now = aware(now)
    t_min, t_max = now - lookback, now + window
    report = SyncReport()
    try:
        fetched = list(await port.list_events(t_min, t_max))
    except Exception as e:  # noqa: BLE001
        report.error = type(e).__name__
        log.warning("calendar sync failed (%s); nothing changed", report.error)
        return report

    seen: set[str] = set()
    for ext in fetched:
        ref = str(ext.id)
        seen.add(ref)
        cancelled = getattr(ext, "status", "confirmed") == "cancelled"
        existing = await store.find_event_by_ref(user_id, EventSource.CALENDAR.value, ref)
        if cancelled:
            if existing and existing.status == EventStatus.ACTIVE:
                existing.status = EventStatus.CANCELLED
                await store.save_event(existing)
                report.cancelled += 1
            continue
        if not getattr(ext, "busy", True):
            report.skipped += 1
            continue
        start, end = aware(ext.start), aware(ext.end)
        if end < start:
            report.skipped += 1
            continue
        title = clean_text(ext.summary) or "(no title)"
        location = clean_text(ext.location, 200) or None if getattr(ext, "location", None) else None
        all_day = bool(getattr(ext, "all_day", False))
        kind = guess_kind(title)
        if existing is None:
            if await _known_from_user(store, user_id, kind, start):
                report.merged += 1
                continue
            await store.save_event(
                LifeEvent(
                    user_id=user_id,
                    title=title,
                    start=start,
                    end=end,
                    kind=kind,
                    source=EventSource.CALENDAR,
                    source_ref=ref,
                    location=location,
                    protected=default_protected(kind) and not all_day,
                )
            )
            report.created += 1
            continue
        moved = (existing.start, existing.end, existing.title, existing.location) != (
            start,
            end,
            title,
            location,
        )
        revived = existing.status != EventStatus.ACTIVE
        if moved or revived:
            existing.start, existing.end = start, end
            existing.title, existing.location, existing.kind = title, location, kind
            existing.protected = default_protected(kind) and not all_day
            existing.status = EventStatus.ACTIVE
            await store.save_event(existing)
            report.updated += 1
        else:
            report.unchanged += 1

    # events that left the window's feed were deleted or declined in the calendar
    for ev in await store.events_between(user_id, t_min, t_max):
        if (
            ev.source == EventSource.CALENDAR
            and ev.source_ref not in seen
            and ev.status == EventStatus.ACTIVE
            and t_min <= ev.start < t_max
        ):
            ev.status = EventStatus.CANCELLED
            await store.save_event(ev)
            report.cancelled += 1
    return report


async def _known_from_user(
    store: LifeStore, user_id: str, kind: EventKind, start: datetime
) -> bool:
    if kind == EventKind.OTHER:
        return False
    near = await store.events_between(user_id, start - MERGE_TOLERANCE, start + MERGE_TOLERANCE)
    return any(
        e.source == EventSource.USER
        and e.kind == kind
        and e.status == EventStatus.ACTIVE
        and abs(e.start - start) <= MERGE_TOLERANCE
        for e in near
    )


class GoogleCalendarAdapter:
    """Read-only adapter over ``friday.google.calendar.CalendarClient``.

    It exposes ``list_events`` and nothing else, so code holding it cannot create or delete
    calendar entries. ``CalendarEvent`` already has the fields ``ExternalEvent`` needs.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    async def list_events(self, time_min: datetime, time_max: datetime):  # noqa: ANN201
        return await self._client.list_events(time_min, time_max)  # type: ignore[attr-defined]
