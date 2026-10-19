"""Small interfaces the life state depends on. Each has a fake in the tests.

* ``CalendarPort``: READ-ONLY view of the user's calendar. ``friday.google.calendar.CalendarClient``
  already fits (its ``list_events`` returns objects with id, summary, start, end, all_day, busy,
  location); nothing here can write back.
* ``BillsPort``: W3's bills (billers, due dates). Until it lands the generic bill events are used.
* ``TravelBufferHook``: minutes needed to get to an event's location (maps/traffic later).
* ``CaptureLLM``: optional language-model fallback for messages the deterministic parser cannot
  read. Its output is validated by code and always confirmed back to the user.
* ``Sender``: delivers a proactive message (the notifier adapter in production).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from friday.lifestate.models import LifeEvent


@runtime_checkable
class ExternalEvent(Protocol):
    """Shape of a calendar event as ``friday.google.calendar.CalendarEvent`` provides it.
    A ``status`` attribute ("cancelled") is optional; a missing event means cancelled too."""

    id: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    busy: bool
    location: str | None


class CalendarPort(Protocol):
    async def list_events(self, time_min: datetime, time_max: datetime) -> list[ExternalEvent]: ...


@dataclass(frozen=True)
class BillRef:
    id: str
    due_on: date
    biller: str | None = None
    pay_link: str | None = None


class BillsPort(Protocol):
    async def pending_bills(self, user_id: str, now: datetime) -> list[BillRef]: ...


class TravelBufferHook(Protocol):
    async def minutes_needed(self, event: LifeEvent) -> int | None: ...


@dataclass(frozen=True)
class LLMExtraction:
    """What a language model may propose. Code re-validates every field."""

    title: str
    start: datetime
    end: datetime | None = None
    kind: str | None = None
    is_commitment: bool = False


class CaptureLLM(Protocol):
    async def extract(self, text: str, now: datetime) -> LLMExtraction | None: ...


class Sender(Protocol):
    async def send(
        self, user_id: str, text: str, *, channel: str = "text", dedupe_key: str | None = None
    ) -> bool:
        """True if the message was handed to the channel."""
        ...
