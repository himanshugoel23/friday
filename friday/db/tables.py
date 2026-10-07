"""ORM tables mirroring friday.core.models.

Conventions:
* ids: 32-char uuid4 hex strings (``new_id``).
* enums stored as their string/int value (portable, readable).
* nested value objects (TaskSpec, TaskResult, ReplyButtons...) stored as JSON via
  ``model_dump(mode="json")``; repositories convert with ``Model.model_validate``.
* all datetimes are ``UTCDateTime`` (aware UTC in Python).
* PII lives in users/profiles/people/places/messages/facts/call_turns - all keyed
  by user so "delete everything" can cascade (Backend implements the purge).

Owner: EM scaffold -> Backend Engineer owns after hand-off.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime

_USER_FK = "users.id"


def _user_fk(nullable: bool = False) -> Mapped[Any]:
    return mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=nullable, index=True
    )


# ------------------------------------------------------------------------------ people


class UserRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="onboarding")
    onboarding_step: Mapped[str] = mapped_column(String(20), nullable=False, default="invite_code")
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invited_by_user_id: Mapped[str | None] = mapped_column(String(32))
    invites_remaining: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    rate_limited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_inbound_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProfileRow(Base):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(12), default="hinglish", nullable=False)
    tone: Mapped[str] = mapped_column(String(12), default="friendly", nullable=False)
    morning_briefing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    briefing_hour_ist: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    preferred_channel: Mapped[str] = mapped_column(String(12), default="whatsapp", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class ConsentRow(IdMixin, Base):
    __tablename__ = "consents"

    user_id: Mapped[str] = _user_fk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="CASCADE")
    )
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class InviteRow(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="SET NULL"), index=True
    )
    redeemed_by_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="SET NULL")
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AutonomySettingRow(Base):
    __tablename__ = "autonomy_settings"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(20), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class PersonRow(IdMixin, TimestampMixin, Base):
    """Circle member. ``notes`` private to owner."""

    __tablename__ = "people"

    owner_user_id: Mapped[str] = _user_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    relation: Mapped[str | None] = mapped_column(String(40))
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    language: Mapped[str | None] = mapped_column(String(12))
    notes: Mapped[str | None] = mapped_column(Text)
    contact_consent: Mapped[str] = mapped_column(String(16), default="not_asked", nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    checkin_consent: Mapped[str] = mapped_column(String(16), default="not_asked", nullable=False)
    linked_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="SET NULL")
    )


class PlaceRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "places"

    owner_user_id: Mapped[str] = _user_fk()
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    address_text: Mapped[str | None] = mapped_column(Text)
    formatted_address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="typed", nullable=False)
    person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="SET NULL"), index=True
    )
    ephemeral: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ------------------------------------------------------------------------------ memory


class BusinessRow(IdMixin, Base):
    __tablename__ = "businesses"
    __table_args__ = (Index("ix_businesses_phone", "phone"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(60))
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    hours: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # BusinessHours
    best_call_times: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    is_customer_care: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ivr_notes: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    verification: Mapped[str | None] = mapped_column(String(12))
    notes: Mapped[str | None] = mapped_column(Text)
    language_hint: Mapped[str | None] = mapped_column(String(12))
    directory_provider: Mapped[str | None] = mapped_column(String(30))
    directory_place_id: Mapped[str | None] = mapped_column(String(255), index=True)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="SET NULL")
    )
    last_called_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class FactRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "facts"

    user_id: Mapped[str] = _user_fk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    recurrence: Mapped[str] = mapped_column(String(10), default="none", nullable=False)
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="CASCADE")
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(32))


class VendorInteractionRow(IdMixin, Base):
    """Vendor memory (B20): per-user history with a business."""

    __tablename__ = "vendor_interactions"
    __table_args__ = (Index("ix_vendor_user_business", "user_id", "business_id"),)

    user_id: Mapped[str] = _user_fk()
    business_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(32))
    call_id: Mapped[str | None] = mapped_column(String(32))
    amount_inr: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AccountIdentifierRow(IdMixin, TimestampMixin, Base):
    """C22/C24: identifiers shareable on care calls when approved per task.
    ``value_encrypted`` is encrypted by the repository with Settings.secret_key."""

    __tablename__ = "account_identifiers"

    user_id: Mapped[str] = _user_fk()
    company: Mapped[str | None] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    last4: Mapped[str | None] = mapped_column(String(4))


# ------------------------------------------------------------------------------ messages


class MessageRow(IdMixin, Base):
    """Every inbound/outbound message on any channel (action log + 24h window)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_user_at", "user_id", "at"),)

    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE")
    )
    person_id: Mapped[str | None] = mapped_column(  # circle member counterpart, if any
        String(32), ForeignKey("people.id", ondelete="SET NULL")
    )
    business_id: Mapped[str | None] = mapped_column(  # business counterpart (B15)
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)  # from/to
    text: Mapped[str | None] = mapped_column(Text)
    buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    button_id: Mapped[str | None] = mapped_column(String(256))
    template: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    media_url: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), index=True)
    nudge_id: Mapped[str | None] = mapped_column(String(32))
    question_id: Mapped[str | None] = mapped_column(String(32))
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


# ------------------------------------------------------------------------------ tasks & calls


class TaskRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_next", "status", "next_attempt_at"),
        Index("ix_tasks_requester_status", "requester_user_id", "status"),
    )

    requester_user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False
    )
    beneficiary_person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="SET NULL")
    )
    place_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("places.id", ondelete="SET NULL")
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)  # TaskSpec
    target: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # ContactTarget
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # RecurrenceRule
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_outcome: Mapped[str | None] = mapped_column(String(20))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # TaskResult
    candidate: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # BusinessCandidate
    shortlist: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    approved_terms: Mapped[str | None] = mapped_column(Text)
    delegation: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # Delegation
    cost_inr_est: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(32))


class CallRow(IdMixin, Base):
    """One call attempt (CallResult)."""

    __tablename__ = "calls"

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(10), default="outbound", nullable=False)
    to_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    dial_status: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    collected: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    languages_heard: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    care: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # CareOutcome
    hold_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_inr_est: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="agent", nullable=False)
    recording_url: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)


class CallTurnRow(Base):
    __tablename__ = "call_turns"
    __table_args__ = (UniqueConstraint("call_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(12))
    confidence: Mapped[float | None] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CallQuestionRow(IdMixin, Base):
    """Mid-call questions to the user and their answers (survives restarts)."""

    __tablename__ = "call_questions"

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[str | None] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(20), default="clarify", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    asked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_option_index: Mapped[int | None] = mapped_column(Integer)
    answer_approves: Mapped[bool | None] = mapped_column(Boolean)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class QuoteRow(IdMixin, Base):
    __tablename__ = "quotes"

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("calls.id", ondelete="SET NULL")
    )
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_inr: Mapped[int | None] = mapped_column(Integer)
    original_amount_inr: Mapped[int | None] = mapped_column(Integer)
    price_text: Mapped[str] = mapped_column(Text, nullable=False)
    inclusions: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    exclusions: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    validity: Mapped[str | None] = mapped_column(String(200))
    available_slots: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    within_budget: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class HotelBookingRow(IdMixin, TimestampMixin, Base):
    """D27-29: held / linked / confirmed stays. ``property`` = HotelProperty JSON."""

    __tablename__ = "hotel_bookings"

    task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[str] = _user_fk()
    guest_person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    property: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    room_type: Mapped[str | None] = mapped_column(String(120))
    check_in: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    guests: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    total_inr: Mapped[int | None] = mapped_column(Integer)
    confirmation_ref: Mapped[str | None] = mapped_column(String(80))
    booking_link: Mapped[str | None] = mapped_column(Text)
    hold_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    guest_name: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


# ------------------------------------------------------------------------------ proactive


class NudgeRow(IdMixin, Base):
    __tablename__ = "nudges"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key"),
        Index("ix_nudges_user_sent", "user_id", "sent_at"),
    )

    user_id: Mapped[str] = _user_fk()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    urgency: Mapped[str] = mapped_column(String(10), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    proposed_task: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # TaskSpec
    task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    fact_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("facts.id", ondelete="SET NULL")
    )
    person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="SET NULL")
    )
    recipient_person_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("people.id", ondelete="SET NULL")
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class NudgeFeedbackRow(IdMixin, Base):
    __tablename__ = "nudge_feedback"

    nudge_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("nudges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = _user_fk()
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


# ------------------------------------------------------------------------------ audit


class AuditRow(IdMixin, Base):
    """Append-only action log. Kept (with PII scrubbed) after data deletion."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_user_at", "user_id", "at"),)

    user_id: Mapped[str | None] = mapped_column(String(32))  # no FK: survives deletion
    actor: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


# ------------------------------------------------------------------------------ costs


class CostEntryRow(IdMixin, Base):
    """Internal per-user cost ledger (never shown to users). One row per billable
    leg: call, llm, message, sms, api. Roll-ups feed ops alerts (no user cap)."""

    __tablename__ = "cost_entries"
    __table_args__ = (Index("ix_cost_user_at", "user_id", "at"),)

    user_id: Mapped[str] = _user_fk()
    task_id: Mapped[str | None] = mapped_column(String(32))
    call_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


# -------------------------------------------------------------------------- call memory (E30-35)


class CallMemoryRow(IdMixin, Base):
    """Which Friday caller-ID number called which business number, for which
    task/user, when, and the outcome (E30). One row per outbound call attempt
    (``call_id`` unique). Drives sticky caller-ID and call-back matching."""

    __tablename__ = "call_memory"
    __table_args__ = (
        UniqueConstraint("call_id"),
        Index("ix_call_memory_phone_at", "business_phone", "at"),
    )

    call_id: Mapped[str | None] = mapped_column(String(32))
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = _user_fk()
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    business_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    friday_number: Mapped[str | None] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10), default="outbound", nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(24))
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class InboundContactRow(IdMixin, Base):
    """Inbound call / missed call / message from a non-user number to Friday (E31-35).
    ``status``: matched | ambiguous | unmatched. Unmatched rows hold no user link."""

    __tablename__ = "inbound_contacts"
    __table_args__ = (Index("ix_inbound_contacts_phone_at", "from_phone", "at"),)

    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # call | missed_call | message
    channel: Mapped[str] = mapped_column(String(12), default="voice", nullable=False)
    from_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    friday_number: Mapped[str | None] = mapped_column(String(20))
    provider_ref: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    business_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("businesses.id", ondelete="SET NULL")
    )
    task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(_USER_FK, ondelete="CASCADE"), index=True
    )
    candidate_task_ids: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)  # caller's message (unmatched: name/purpose)
    handled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


ALL_TABLES = sorted(Base.metadata.tables)
