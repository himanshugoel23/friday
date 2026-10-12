"""Conversation state of the WhatsApp quotes flow (stored as one JSON document per request)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from friday.core.clock import utcnow
from friday.core.models import new_id


class State(StrEnum):
    COLLECTING = "collecting"  # asking for the missing slot, one question at a time
    CONFIRMING = "confirming"  # shortlist shown, waiting for "Haan, call karo" / "Badlo"
    QUEUED = "queued"  # approved, waiting for the calling window / next pass
    CALLING = "calling"  # vendor calls in progress (server side, no user input needed)
    AWAITING_BOOK = "awaiting_book"  # comparison delivered, waiting for a Book tap
    BOOKING = "booking"  # booking call in progress
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def active(self) -> bool:
        return self not in (State.DONE, State.CANCELLED, State.FAILED)


class VStatus(StrEnum):
    PENDING = "pending"
    CALLING = "calling"
    DONE = "done"


class Outcome(StrEnum):
    QUOTE = "quote"
    NO_ANSWER = "no_answer"
    DECLINED = "declined"
    WRONG_NUMBER = "wrong_number"
    CLOSED = "closed"
    DNC = "dnc"
    FAILED = "failed"
    BOOKED = "booked"
    NO_SLOT = "no_slot"
    PRICE_TOO_HIGH = "price_too_high"
    BLOCKED = "blocked"  # pilot allow-list refused the call

    @property
    def retryable(self) -> bool:
        return self in (Outcome.NO_ANSWER, Outcome.FAILED)


class Vendor(BaseModel):
    place_id: str
    name: str
    phone: str
    rating: float | None = None
    review_count: int = 0
    distance_km: float | None = None
    address: str | None = None
    category: str | None = None
    open_now: bool | None = None
    status: VStatus = VStatus.PENDING
    outcome: Outcome | None = None
    attempts: int = 0
    task_id: str | None = None
    price_inr: int | None = None
    slots: list[str] = Field(default_factory=list)
    next_try_at: datetime | None = None
    claimed_at: datetime | None = None


class Location(BaseModel):
    text: str | None = None
    lat: float | None = None
    lng: float | None = None
    city: str | None = None  # "gurgaon" | "bangalore"
    address: str | None = None

    @property
    def ok(self) -> bool:
        return self.lat is not None and self.lng is not None and self.city is not None


class Slots(BaseModel):
    services: list[str] = Field(default_factory=list)
    for_name: str | None = None  # None = the user themself
    for_other_unnamed: bool = False  # said "someone else" without a name
    day_set: bool = False
    when_text: str | None = None  # canonical Hinglish: "kal shaam 6 baje"
    when_start: datetime | None = None
    when_end: datetime | None = None
    exact_time: bool = False
    budget_inr: int | None = None
    book_intent: bool = False  # explicit "book at this time and price"
    location: Location = Field(default_factory=Location)


class Delivery(BaseModel):
    """How the final message reached (or did not reach) the user (HANDOFF 2b)."""

    text: str | None = None
    buttons: list[tuple[str, str]] = Field(default_factory=list)  # (id, title)
    kind: str = "comparison"  # comparison | booking | note
    sent_at: datetime | None = None
    provider_id: str | None = None
    delivered: bool = False
    failed: bool = False
    sms_sent: bool = False
    voice_requested: bool = False


class Conv(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    state: State = State.COLLECTING
    lang: str = "hinglish"  # en | hinglish | hi
    asking: str | None = None  # services | when | location | for_name | book_time
    slots: Slots = Field(default_factory=Slots)
    shortlist: list[Vendor] = Field(default_factory=list)
    alternates: list[Vendor] = Field(default_factory=list)
    mode: str = "quote_only"  # quote_only | book
    category: str = "salon"  # scouting/vendors category key (friday/vendors/packs.py)
    places_calls: int = 0
    seen_ids: list[str] = Field(default_factory=list)  # provider message ids already handled
    queued_until: datetime | None = None
    redo_count: int = 0
    person_id: str | None = None
    # booking after the quotes
    book_vendor: int | None = None
    book_task_id: str | None = None
    book_when_text: str | None = None
    book_ceiling: int | None = None
    delivery: Delivery | None = None
    final_text: str | None = None  # last result, returned by "status"
    counted: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_user_at: datetime = Field(default_factory=utcnow)
    extra: dict[str, Any] = Field(default_factory=dict)

    def vendor_by_task(self, task_id: str) -> Vendor | None:
        return next((v for v in self.shortlist if v.task_id == task_id), None)
