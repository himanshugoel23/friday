from datetime import date, datetime

from friday.core.clock import (
    IST,
    UTC,
    FakeClock,
    at_ist,
    ensure_utc,
    format_ist,
    is_quiet_hours,
    ist_day_bounds,
    next_quiet_hours_end,
    to_ist,
)


def test_fake_clock_is_utc_and_advances(clock: FakeClock):
    assert clock.now().tzinfo == UTC
    assert to_ist(clock.now()).hour == 10
    clock.advance(hours=2)
    assert to_ist(clock.now()).hour == 12


async def test_fake_clock_sleep_is_instant(clock: FakeClock):
    start = clock.now()
    await clock.sleep(3600)
    assert (clock.now() - start).total_seconds() == 3600


def test_quiet_hours_wrap_midnight():
    assert is_quiet_hours(datetime(2026, 1, 5, 22, 30, tzinfo=IST))
    assert is_quiet_hours(datetime(2026, 1, 6, 7, 59, tzinfo=IST))
    assert not is_quiet_hours(datetime(2026, 1, 6, 8, 0, tzinfo=IST))
    assert not is_quiet_hours(datetime(2026, 1, 5, 21, 59, tzinfo=IST))


def test_next_quiet_hours_end():
    late = datetime(2026, 1, 5, 23, 0, tzinfo=IST)
    assert to_ist(next_quiet_hours_end(late)) == datetime(2026, 1, 6, 8, 0, tzinfo=IST)
    early = datetime(2026, 1, 6, 6, 0, tzinfo=IST)
    assert to_ist(next_quiet_hours_end(early)) == datetime(2026, 1, 6, 8, 0, tzinfo=IST)
    day = datetime(2026, 1, 6, 12, 0, tzinfo=IST)
    assert next_quiet_hours_end(day) == ensure_utc(day)


def test_ist_day_bounds_and_helpers():
    # 01:00 IST on the 6th is still 19:30 UTC on the 5th
    t = datetime(2026, 1, 6, 1, 0, tzinfo=IST)
    start, end = ist_day_bounds(t)
    assert start == datetime(2026, 1, 5, 18, 30, tzinfo=UTC)
    assert (end - start).days == 1
    assert at_ist(date(2026, 1, 6), 9) == datetime(2026, 1, 6, 3, 30, tzinfo=UTC)
    assert ensure_utc(datetime(2026, 1, 1)).tzinfo == UTC
    assert "10:00 AM" in format_ist(datetime(2026, 1, 5, 4, 30, tzinfo=UTC))
