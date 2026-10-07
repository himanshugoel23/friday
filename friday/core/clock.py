"""Injectable clock + IST helpers.

Rules (whole codebase):
  * Every datetime that is stored or passed around is timezone-aware **UTC**.
  * Convert to IST (Asia/Kolkata, fixed +05:30, no DST) only for display and for
    user-facing rules such as quiet hours or "morning briefing at 8am".
  * Never call ``datetime.now()`` / ``asyncio.sleep`` directly in business logic;
    take a ``Clock`` so tests can use ``FakeClock``.

Owner: Engineering Manager (core, frozen). Others import only.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Protocol, runtime_checkable

UTC = UTC
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


@runtime_checkable
class Clock(Protocol):
    """Source of time. ``now()`` always returns an aware UTC datetime."""

    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Real wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


class FakeClock:
    """Deterministic clock for tests and the simulator.

    ``sleep`` advances virtual time instantly (and yields to the loop once), so
    code that waits for "2 hours" completes immediately in tests.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = ensure_utc(start) if start else datetime(2026, 1, 5, 4, 30, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, when: datetime) -> None:
        self._now = ensure_utc(when)

    def advance(self, seconds: float = 0, **delta: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, **delta)
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.advance(max(0.0, seconds))
        await asyncio.sleep(0)


# --------------------------------------------------------------------------- helpers


def utcnow() -> datetime:
    """Convenience for defaults in models. Business logic should use a ``Clock``."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as aware UTC. Naive datetimes are assumed to already be UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_ist(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(IST)


def from_ist(local: datetime) -> datetime:
    """Interpret a naive (or IST-aware) wall-clock datetime as IST and return UTC."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=IST)
    return local.astimezone(UTC)


def ist_date(dt: datetime) -> date:
    return to_ist(dt).date()


def ist_day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    """UTC [start, end) of the IST calendar day containing ``dt`` (for daily caps)."""
    d = ist_date(dt)
    start = datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)
    return start, start + timedelta(days=1)


def at_ist(d: date, hour: int, minute: int = 0) -> datetime:
    """UTC instant for ``hour:minute`` IST on IST date ``d``."""
    return datetime.combine(d, time(hour, minute), tzinfo=IST).astimezone(UTC)


def is_quiet_hours(dt: datetime, start_hour: int = 22, end_hour: int = 8) -> bool:
    """True if ``dt`` falls inside IST quiet hours [start_hour, end_hour) (wraps midnight)."""
    h = to_ist(dt).hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= h < end_hour
    return h >= start_hour or h < end_hour


def next_quiet_hours_end(dt: datetime, start_hour: int = 22, end_hour: int = 8) -> datetime:
    """If ``dt`` is in quiet hours return the UTC instant they end, else ``dt`` unchanged."""
    if not is_quiet_hours(dt, start_hour, end_hour):
        return ensure_utc(dt)
    local = to_ist(dt)
    end = local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)


def format_ist(dt: datetime, fmt: str = "%a %d %b, %I:%M %p") -> str:
    """Human friendly IST string, e.g. 'Mon 05 Jan, 10:00 AM'."""
    return to_ist(dt).strftime(fmt)
