from datetime import date, datetime, timedelta

import pytest

from friday.core.clock import IST, to_ist
from friday.core.config import Settings
from friday.core.models import (
    BusinessHours,
    CallOutcome,
    OpeningPeriod,
    Recurrence,
    RecurrenceRule,
)
from friday.tasks.policy import TaskPolicy
from friday.tasks.recurrence import next_run
from friday.tasks.scheduling import next_call_time, retry_at

S = Settings(_env_file=None)
P = TaskPolicy(_env_file=None)


def ist(*a):
    return datetime(*a, tzinfo=IST)


@pytest.mark.parametrize(
    "now,expected",
    [
        (ist(2026, 1, 5, 7, 0), "2026-01-05 09:30"),  # before window
        (ist(2026, 1, 5, 11, 0), "2026-01-05 11:00"),  # inside
        (ist(2026, 1, 5, 13, 45), "2026-01-05 14:30"),  # lunch (hours unknown)
        (ist(2026, 1, 5, 20, 30), "2026-01-06 09:30"),  # after window
    ],
)
def test_window_and_lunch(now, expected):
    assert to_ist(next_call_time(now, S)).strftime("%Y-%m-%d %H:%M") == expected


def test_person_window_and_hours():
    assert to_ist(next_call_time(ist(2026, 1, 5, 8, 30), S, is_person=True)).hour == 9
    assert to_ist(next_call_time(ist(2026, 1, 5, 13, 45), S, is_person=True)).minute == 45
    hours = BusinessHours(periods=[OpeningPeriod(weekday=1, open="11:00", close="19:00")])
    # Monday closed -> Tuesday 11:00 + grace
    got = to_ist(next_call_time(ist(2026, 1, 5, 12, 0), S, hours=hours))
    assert got.strftime("%a %H:%M") == "Tue 11:05"
    # open hours + call window clamp
    late = BusinessHours(periods=[OpeningPeriod(weekday=0, open="06:00", close="23:00")])
    assert to_ist(next_call_time(ist(2026, 1, 5, 7, 0), S, hours=late)).strftime("%H:%M") == "09:30"


def test_retry_table():
    now = ist(2026, 1, 5, 11, 0)
    assert retry_at(CallOutcome.BUSY, 1, now, P) - now == timedelta(minutes=5)
    assert retry_at(CallOutcome.NO_ANSWER, 1, now, P) - now == timedelta(minutes=10)
    assert retry_at(CallOutcome.VOICEMAIL, 2, now, P) - now == timedelta(minutes=45)
    assert retry_at(CallOutcome.NO_ANSWER, 3, now, P) - now == timedelta(minutes=120)
    assert retry_at(CallOutcome.FAILED, 1, now, P) - now == timedelta(minutes=5)
    assert retry_at(CallOutcome.CALLBACK_LATER, 1, now, P) - now == timedelta(hours=2)
    cb = now + timedelta(hours=5)
    assert retry_at(CallOutcome.CALLBACK_LATER, 1, now, P, callback_at=cb) == cb + timedelta(minutes=5)
    assert to_ist(retry_at(CallOutcome.HOLD_TIMEOUT, 1, now, P)).strftime("%d %H") == "06 10"
    custom = TaskPolicy(_env_file=None, no_answer_delays_min=[1], busy_delay_min=2)
    assert retry_at(CallOutcome.NO_ANSWER, 1, now, custom) - now == timedelta(minutes=1)
    assert retry_at(CallOutcome.BUSY, 1, now, custom) - now == timedelta(minutes=2)


def test_policy_env_override(monkeypatch):
    monkeypatch.setenv("FRIDAY_TASKS_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("FRIDAY_TASKS_NO_ANSWER_DELAYS_MIN", "[15, 60]")
    p = TaskPolicy(_env_file=None)
    assert p.max_attempts == 5 and p.no_answer_delays_min == [15, 60]


def test_recurrence_weekly_monthly_yearly_daily():
    after = ist(2026, 1, 5, 11, 0)  # Monday
    weekly = RecurrenceRule(freq=Recurrence.WEEKLY, weekdays=[1, 4], time_ist="10:00", lead_days=3)
    run, occ = next_run(weekly, after)
    assert occ.date() == date(2026, 1, 9) and run == occ - timedelta(days=3)
    fortnightly = RecurrenceRule(freq=Recurrence.WEEKLY, interval=2, weekdays=[0], time_ist="09:00")
    _, occ = next_run(fortnightly, after, anchor=date(2026, 1, 5))
    assert to_ist(occ).date() == date(2026, 1, 19)
    monthly = RecurrenceRule(freq=Recurrence.MONTHLY, day_of_month=31, time_ist="10:00")
    _, occ = next_run(monthly, ist(2026, 2, 1, 0, 0))
    assert to_ist(occ).date() == date(2026, 2, 28)  # clamped to month length
    quarterly = RecurrenceRule(freq=Recurrence.MONTHLY, interval=3, time_ist="10:00")
    _, occ = next_run(quarterly, after, anchor=date(2026, 1, 3))
    assert to_ist(occ).date() == date(2026, 4, 3)
    yearly = RecurrenceRule(freq=Recurrence.YEARLY, time_ist="08:00")
    _, occ = next_run(yearly, after, anchor=date(2025, 3, 1))
    assert to_ist(occ).date() == date(2026, 3, 1)
    daily = RecurrenceRule(freq=Recurrence.WEEKLY, interval_days=1, time_ist="10:30")
    _, occ = next_run(daily, after)
    assert to_ist(occ) == ist(2026, 1, 6, 10, 30)
    ended = RecurrenceRule(freq=Recurrence.WEEKLY, until=date(2026, 1, 1))
    assert next_run(ended, after) is None
    assert next_run(RecurrenceRule(freq=Recurrence.NONE), after) is None
