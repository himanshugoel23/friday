"""Call timing (B19, US-6, US-28): when may we dial, and when do we retry?

All inputs/outputs are aware UTC; rules are evaluated in IST.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import at_ist, ensure_utc, to_ist
from friday.core.config import Settings
from friday.core.models import BusinessHours, CallOutcome

OPENING_GRACE = timedelta(minutes=5)  # "Clinic opens at 5 PM. I'll call at 5:05."
PERSON_WINDOW = ("09:00", "20:00")  # A13 / US-28.2: private individuals
_BASE_BACKOFF_S = 900


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


# US-6 retry table, expressed as multiples of Settings.call_retry_backoff_s (900s):
# busy +10m/+30m, no answer & voicemail +20m/+90m, technical failure +5m.
_RETRY_FACTORS: dict[CallOutcome, tuple[float, ...]] = {
    CallOutcome.BUSY: (10 / 15, 2.0),
    CallOutcome.NO_ANSWER: (20 / 15, 6.0),
    CallOutcome.VOICEMAIL: (20 / 15, 6.0),
    CallOutcome.FAILED: (5 / 15,),
}
VAGUE_CALLBACK = timedelta(hours=2)
CALLBACK_GRACE = timedelta(minutes=5)
HOLD_TIMEOUT_RETRY_HOUR_IST = 10  # best-known time for care lines (weekday 10-11 AM)


def retry_at(
    outcome: CallOutcome,
    attempt: int,
    now: datetime,
    settings: Settings,
    *,
    callback_at: datetime | None = None,
) -> datetime:
    """When to try again after a retryable outcome (before window alignment)."""
    if outcome == CallOutcome.CALLBACK_LATER:
        if callback_at and callback_at > now:
            return callback_at + CALLBACK_GRACE
        return now + VAGUE_CALLBACK
    if outcome == CallOutcome.HOLD_TIMEOUT:
        return at_ist(to_ist(now).date() + timedelta(days=1), HOLD_TIMEOUT_RETRY_HOUR_IST)
    factors = _RETRY_FACTORS.get(outcome, (1.0,))
    factor = factors[min(max(attempt, 1), len(factors)) - 1]
    base = settings.call_retry_backoff_s or _BASE_BACKOFF_S
    return now + timedelta(seconds=base * factor)
