"""RecurrenceRule -> next occurrence / next run (A12 recurring bookings, A13 check-ins).

Occurrences are IST wall-clock (``rule.time_ist``). The engine *runs* (places the
booking call) ``lead_days`` before each occurrence.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from friday.core.clock import at_ist, to_ist
from friday.core.models import Recurrence, RecurrenceRule
from friday.tasks.scheduling import hhmm

MAX_SCAN_DAYS = 800

# A12 defaults when the rule doesn't say: weekly -> book 3 days ahead, monthly -> 7.
DEFAULT_LEAD_DAYS = {Recurrence.WEEKLY: 3, Recurrence.MONTHLY: 7, Recurrence.YEARLY: 14}


def _matches(rule: RecurrenceRule, d: date, anchor: date) -> bool:
    interval = max(1, rule.interval)
    if rule.interval_days:
        return (d - anchor).days % rule.interval_days == 0 and d >= anchor
    if rule.freq == Recurrence.WEEKLY:
        weekdays = rule.weekdays or [anchor.weekday()]
        anchor_monday = anchor - timedelta(days=anchor.weekday())
        weeks = (d - anchor_monday).days // 7
        return d.weekday() in weekdays and weeks >= 0 and weeks % interval == 0
    if rule.freq == Recurrence.MONTHLY:
        months = (d.year - anchor.year) * 12 + d.month - anchor.month
        dom = rule.day_of_month or anchor.day
        dom = min(dom, calendar.monthrange(d.year, d.month)[1])
        return months >= 0 and months % interval == 0 and d.day == dom
    if rule.freq == Recurrence.YEARLY:
        years = d.year - anchor.year
        day = min(anchor.day, calendar.monthrange(d.year, anchor.month)[1])
        return years >= 0 and years % interval == 0 and (d.month, d.day) == (anchor.month, day)
    return False


def next_run(
    rule: RecurrenceRule, after: datetime, *, anchor: date | None = None
) -> tuple[datetime, datetime] | None:
    """(run_at, occurrence) with run_at strictly after ``after``; None if the series ended."""
    h, m = hhmm(rule.time_ist)
    start = to_ist(after).date()
    anchor = anchor or start
    for i in range(MAX_SCAN_DAYS):
        d = start + timedelta(days=i)
        if rule.until and d > rule.until:
            return None
        if not _matches(rule, d, anchor):
            continue
        occurrence = at_ist(d, h, m)
        run_at = occurrence - timedelta(days=rule.lead_days)
        if run_at > after:
            return run_at, occurrence
    return None
