# ruff: noqa: E501
"""Plain models of the trip timeline. Times are aware UTC; the leg keeps the IANA zone it is local to.

Everything that came out of a document is minimal (codes, times, a booking reference). Titles are
cleaned (a document is untrusted data) and personal text is encrypted by the database columns
(friday/trips/dbmodel.py).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.models import new_id


class TripStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class LegKind(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"
    STAY = "stay"
    CAB = "cab"
    OTHER = "other"


class TaskKind(StrEnum):
    LEAVE_BY = "leave_by"
    HOTEL_CALL = "hotel_call"
    CAB = "cab"
    FLIGHT_WATCH = "flight_watch"
    LOUNGE = "lounge"
    CHECKIN = "checkin"  # hotel check-in information
    CHECKOUT = "checkout"
    DAY_PLAN = "day_plan"  # the morning "aaj ka plan" of a trip day


class TaskState(StrEnum):
    PLANNED = "planned"
    NUDGED = "nudged"
    NEEDS_NUMBER = "needs_number"  # approved, but no hotel number in the document: ask the user
    APPROVED = "approved"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"


OPEN_STATES = (TaskState.PLANNED, TaskState.NUDGED, TaskState.NEEDS_NUMBER)
PROPOSAL_KINDS = (
    TaskKind.HOTEL_CALL,
    TaskKind.CAB,
)  # need the user's approval before anything runs


class Trip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    title: str
    start_date: date
    end_date: date
    status: TripStatus = TripStatus.ACTIVE
    created_from: str = "doc"  # "doc" | "user"
    travel_minutes: int | None = Field(default=None, ge=0, le=600)  # home -> airport/station
    pickup_address: str | None = None  # the user's words; never taken from a document
    muted: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TripLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    trip_id: str
    kind: LegKind
    starts_at: datetime  # departure / check-in (UTC)
    ends_at: datetime | None = None  # arrival / check-out (UTC)
    tz: str = "Asia/Kolkata"  # IANA zone the start is local to
    end_tz: str | None = None
    origin: str | None = None  # IATA code, station or city (as read)
    dest: str | None = None
    ref: str | None = None  # PNR / confirmation number
    label: str | None = None  # "IndiGo 6E123", "Hotel Example"
    number: str | None = None  # flight or train number (for the status watch)
    phone: str | None = None  # hotel phone, ONLY if the document or the user gave it
    address: str | None = None
    terminal: str | None = None
    international: bool = False
    time_known: bool = True  # False: only the date is known (hotel with no check-in time)
    assumptions: list[str] = Field(default_factory=list)  # codes shown to the user
    document_id: str | None = None
    pointer_kind: str | None = None  # "gdrive" when the document is filed in the family's Drive
    dedupe_key: str
    status: str = "active"  # "active" | "cancelled"
    created_at: datetime = Field(default_factory=utcnow)


class TripTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    trip_id: str
    leg_id: str | None = None
    kind: TaskKind
    due_at: datetime
    expires_at: datetime
    state: TaskState = TaskState.PLANNED
    task_id: str | None = None  # the Friday task started from an approved proposal
    evidence_ids: list[str] = Field(default_factory=list)
    dedupe_key: str
    locked: bool = False  # the user moved it: a re-derive does not touch the time
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class FlightWatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leg_id: str
    user_id: str
    trip_id: str
    last_status: str | None = None
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    delay_minutes: int = 0
    changed_notified: bool = False
    info: dict[str, Any] = Field(default_factory=dict)  # last gate / terminal / estimated time
    failures: int = 0


class TripNudge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    trip_id: str
    key: str
    topic: str  # "trip", "trip_flight", "trip_lounge": the mute topics
    status: str = "sent"  # "sent" | "expired" | "muted"
    text: str | None = None
    sent_at: datetime = Field(default_factory=utcnow)
