"""Repeat rules for life items, reusing the task engine's recurrence maths."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from friday.core.clock import to_ist
from friday.core.models import Recurrence, RecurrenceRule
from friday.lifestate.models import Repeat, aware
from friday.tasks.recurrence import next_run


def to_rule(rep: Repeat) -> RecurrenceRule:
    if rep.freq == "daily":
        return RecurrenceRule(freq=Recurrence.WEEKLY, interval_days=1, time_ist=rep.time)
    if rep.freq == "weekly":
        return RecurrenceRule(
            freq=Recurrence.WEEKLY, weekdays=list(rep.weekdays), time_ist=rep.time
        )
    return RecurrenceRule(freq=Recurrence.MONTHLY, day_of_month=rep.day_of_month, time_ist=rep.time)


def next_occurrence(rep: Repeat, after: datetime, *, anchor: date | None = None) -> datetime | None:
    """First occurrence strictly after ``after`` (aware UTC), or None."""
    after = aware(after)
    hit = next_run(to_rule(rep), after, anchor=anchor or to_ist(after).date())
    return hit[1] if hit else None


def occurrences_between(
    rep: Repeat, start: datetime, end: datetime, *, anchor: date | None = None, limit: int = 64
) -> list[datetime]:
    """Occurrences in (start, end]. ``start`` is exclusive so a caller can resume from the last."""
    out: list[datetime] = []
    cur = aware(start)
    end = aware(end)
    anchor = anchor or to_ist(cur).date()
    while len(out) < limit:
        nxt = next_occurrence(rep, cur, anchor=anchor)
        if nxt is None or nxt > end:
            break
        out.append(nxt)
        cur = nxt + timedelta(seconds=1)
    return out
