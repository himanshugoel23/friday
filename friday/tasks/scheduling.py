"""Call timing (B19, US-6, US-28): when may we dial, and when do we retry?

All inputs/outputs are aware UTC; rules are evaluated in IST.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import at_ist, ensure_utc, to_ist
from friday.core.config import Settings
from friday.core.models import BusinessHours, CallOutcome
from friday.tasks.policy import TaskPolicy

OPENING_GRACE = timedelta(minutes=5)  # "Clinic opens at 5 PM. I'll call at 5:05."
PERSON_WINDOW = ("09:00", "20:00")  # A13 / US-28.2: private individuals


def hhmm(s: str) -> tuple[int, int]:
    h, _, m = s.strip().partition(":")
    return int(h), int(m or 0)


def _window(settings: Settings, is_person: bool) -> tuple[tuple[int, int], tuple[int, int]]:
    if is_person:
        return hhmm(PERSON_WINDOW[0]), hhmm(PERSON_WINDOW[1])
    return hhmm(settings.business_call_window_start), hhmm(settings.business_call_window_end)


def _lunch(settings: Settings) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if not settings.avoid_lunch_window:
        return None
    a, _, b = settings.avoid_lunch_window.partition("-")
    return hhmm(a), hhmm(b)


def next_call_time(
    now: datetime,
    settings: Settings,
    *,
    hours: BusinessHours | None = None,
    is_person: bool = False,
    margin_min: int = 15,
) -> datetime:
    """Earliest instant >= ``now`` inside the outer call window, inside the business's
    known opening hours (staying open ``margin_min``), and - when hours are unknown -
    outside the lunch window."""
    when = ensure_utc(now)
    (ws_h, ws_m), (we_h, we_m) = _window(settings, is_person)
    lunch = None if (is_person or (hours and hours.periods)) else _lunch(settings)
    for _ in range(64):
        local = to_ist(when)
        start = at_ist(local.date(), ws_h, ws_m)
        end = at_ist(local.date(), we_h, we_m)
        if when < start:
            when = start
            continue
        if when >= end:
            when = at_ist(local.date() + timedelta(days=1), ws_h, ws_m)
            continue
        if lunch:
            ls = at_ist(local.date(), *lunch[0])
            le = at_ist(local.date(), *lunch[1])
            if ls <= when < le:
                when = le
                continue
        if hours and hours.periods:
            nxt = hours.next_open(when, margin_min=margin_min)
            if nxt is None:  # never open within a week: fall back to the window
                return when
            if nxt > when:
                when = nxt + OPENING_GRACE
                continue
        return when
    return when


HOLD_TIMEOUT_RETRY_HOUR_IST = 10  # best-known time for care lines (weekday 10-11 AM)


def retry_at(
    outcome: CallOutcome,
    attempts_done: int,
    now: datetime,
    policy: TaskPolicy,
    *,
    callback_at: datetime | None = None,
) -> datetime:
    """When to dial again after a retryable outcome (BRIEF E.36), BEFORE call-window /
    business-hours alignment (``next_call_time``)."""
    if outcome == CallOutcome.CALLBACK_LATER:
        if callback_at and callback_at > now:
            return callback_at + timedelta(minutes=5)
        return now + timedelta(minutes=policy.vague_callback_min)
    if outcome == CallOutcome.HOLD_TIMEOUT:
        return at_ist(to_ist(now).date() + timedelta(days=1), HOLD_TIMEOUT_RETRY_HOUR_IST)
    if outcome == CallOutcome.BUSY:
        return now + timedelta(minutes=policy.busy_delay_min)
    if outcome == CallOutcome.FAILED:
        return now + timedelta(minutes=policy.failed_delay_min)
    delays = policy.no_answer_delays_min  # NO_ANSWER / VOICEMAIL
    idx = max(attempts_done, 1) - 1
    if idx < len(delays):
        return now + timedelta(minutes=delays[idx])
    return now + timedelta(minutes=policy.final_window_gap_min)
