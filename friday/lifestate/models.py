"""Life state domain models (W4): one per-user picture of the day that every channel reads.

All datetimes are aware. Naive input is read as Asia/Kolkata (the default zone) and every value is
stored and compared as UTC. Titles and notes are personal text: the database columns encrypt them
(see ``dbmodel.py``) and ``context_summary`` never includes them.

Titles that come from a calendar or an e-mail are UNTRUSTED data. They are stored and may be shown
back to their owner after ``display_title`` cleaning, but they are never parsed as instructions.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from friday.core.clock import IST, ensure_utc, utcnow
from friday.core.models import new_id

MAX_TITLE = 200
MAX_NOTE = 1000


class EventKind(StrEnum):
    INTERVIEW = "interview"
    MEETING = "meeting"
    APPOINTMENT = "appointment"
    TRAVEL = "travel"
    BILL_DUE = "bill_due"
    PERSONAL = "personal"
    OTHER = "other"


class EventSource(StrEnum):
    USER = "user"
    CALENDAR = "calendar"
    BOOKING = "booking"
    BILL = "bill"
    CALL_OUTCOME = "call_outcome"


class EventStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    DONE = "done"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


# Events of these kinds are protected by default: no proactive pings while they run.
PROTECTED_BY_DEFAULT = frozenset(
    {EventKind.INTERVIEW, EventKind.MEETING, EventKind.APPOINTMENT, EventKind.TRAVEL}
)
# Sources whose text is not typed by the user: titles are untrusted.
UNTRUSTED_SOURCES = frozenset({EventSource.CALENDAR})


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def aware(dt: datetime) -> datetime:
    """Aware UTC; naive input is Asia/Kolkata wall clock."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return ensure_utc(dt)


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile(r"\s+")


def clean_text(s: str, limit: int = MAX_TITLE) -> str:
    """Strip control characters, collapse whitespace, cap the length. Never interprets the text."""
    return _WS.sub(" ", _CTRL.sub("", s or "")).strip()[:limit]


class Repeat(_M):
    """A simple repeat rule (daily / weekly / monthly) at an IST wall-clock time."""

    freq: Literal["daily", "weekly", "monthly"]
    time: str = "09:00"  # HH:MM, IST
    weekdays: list[int] = Field(default_factory=list)  # 0=Monday, for weekly
    day_of_month: int | None = None  # for monthly

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        h, _, m = v.partition(":")
        if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError("time must be HH:MM")
        return f"{int(h):02d}:{int(m):02d}"


class PersonRef(_M):
    """Minimal reference to someone in the user's life ("mummy", relationship "mother")."""

    name: str
    relationship: str | None = None

    @field_validator("name", "relationship")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v, 80)


class LifeEvent(_M):
    # no validate_assignment: start and end are moved one after the other; callers pass aware,
    # cleaned values (the constructor validates everything)
    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    id: str = Field(default_factory=new_id)
    user_id: str
    title: str
    start: datetime
    end: datetime
    kind: EventKind = EventKind.OTHER
    source: EventSource = EventSource.USER
    source_ref: str | None = None  # calendar event id, task id, bill id ...
    location: str | None = None
    protected: bool = False
    status: EventStatus = EventStatus.ACTIVE
    note: str | None = None  # what the user said afterwards ("accha gaya")
    repeat: Repeat | None = None  # e.g. a bill that comes every month
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("start", "end", "created_at", "updated_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return aware(v)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return clean_text(v) or "(no title)"

    @field_validator("location")
    @classmethod
    def _loc(cls, v: str | None) -> str | None:
        return (clean_text(v, 200) or None) if v else None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return (clean_text(v, MAX_NOTE) or None) if v else None

    @model_validator(mode="after")
    def _order(self) -> LifeEvent:
        if self.end < self.start:
            raise ValueError("end before start")
        return self

    @property
    def untrusted(self) -> bool:
        return self.source in UNTRUSTED_SOURCES

    def overlaps(self, start: datetime, end: datetime) -> bool:
        s, e = aware(start), aware(end)
        if self.end == self.start:  # a point event overlaps a window that contains it
            return s <= self.start < e
        return self.start < e and s < self.end


class LifeCommitment(_M):
    id: str = Field(default_factory=new_id)
    user_id: str
    text: str
    due: datetime
    source: EventSource = EventSource.USER
    status: CommitmentStatus = CommitmentStatus.OPEN
    repeat: Repeat | None = None
    person: PersonRef | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("due", "created_at", "updated_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return aware(v)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        return clean_text(v) or "(empty)"


class NowState(StrEnum):
    FREE = "free"
    IN_EVENT = "in_event"
    TRAVELLING = "travelling"
    QUIET_HOURS = "quiet_hours"  # sleeping


class NowStatus(_M):
    """Derived, never stored: what the user is doing at ``at``."""

    state: NowState
    at: datetime
    kind: EventKind | None = None
    ends_at: datetime | None = None  # end of the busy block, or end of quiet hours
    event_id: str | None = None
    protected: bool = False

    @property
    def busy(self) -> bool:
        return self.state in (NowState.IN_EVENT, NowState.TRAVELLING)


class UserContext(_M):
    """Snapshot handed to other channels. Holds no titles, notes, locations or names."""

    at: datetime
    status: NowStatus
    next_kind: EventKind | None = None
    next_start: datetime | None = None
    events_today: int = 0
    bills_due_this_week: int = 0
    commitments_open_today: int = 0


def default_duration(kind: EventKind) -> timedelta:
    return {
        EventKind.INTERVIEW: timedelta(hours=1),
        EventKind.MEETING: timedelta(hours=1),
        EventKind.APPOINTMENT: timedelta(minutes=45),
        EventKind.TRAVEL: timedelta(hours=2),
        EventKind.BILL_DUE: timedelta(0),
    }.get(kind, timedelta(hours=1))


def display_title(event: LifeEvent, limit: int = 40) -> str:
    """Title safe to show back to the owner. Calendar/e-mail titles are untrusted: URLs, long digit
    runs (phone numbers, codes) and markup are removed and the text is shortened, so a hostile
    invite cannot smuggle a link or an instruction into a message we send."""
    t = clean_text(event.title, 200)
    if event.untrusted:
        t = re.sub(r"(?i)\b(?:https?://|www\.)\S+", "", t)
        t = re.sub(r"\S+@\S+\.\S+", "", t)
        t = re.sub(r"\d[\d\s().-]{5,}\d", "", t)
        t = re.sub(r"[<>`*_\[\]{}|\\]", "", t)
        t = clean_text(t, limit)
        return t or event.kind.value
    return clean_text(t, limit * 2)


class TopicPref(_M):
    """Per-topic nudge preference: muted, and which channel the user opted in to for it.

    ``channel`` is "text" unless the user explicitly asked for voice notes or calls on this topic.
    """

    topic: str
    muted: bool = False
    channel: Literal["text", "voice_note", "call"] = "text"


class Followup(_M):
    """One planned/sent proactive message, keyed so it is never sent twice."""

    id: str = Field(default_factory=new_id)
    user_id: str
    key: str  # e.g. "after:<event_id>:<start_ts>"
    topic: str  # after_event | before_event | bill_due | commitment | morning_brief
    event_id: str | None = None
    status: Literal["sent", "muted", "expired", "suppressed", "digest", "digested"] = "sent"
    text: str | None = None
    due_at: datetime
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("due_at", "sent_at", "responded_at", "created_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else aware(v)
