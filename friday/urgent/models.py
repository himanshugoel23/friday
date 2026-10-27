# ruff: noqa: E501
"""Data of the urgent-call escalation (docs/URGENT_ESCALATION.md). Nothing here talks to a network.

One ``EscalationState`` per urgent receptionist message (unique per user and message, so a replayed
webhook or a restart can never open a second one). The row holds NO personal text: the user's number
lives only in the encrypted per-user config.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

MIN_WAIT_MINUTES, MAX_WAIT_MINUTES = 2, 60  # a user override is clamped (never an instant call)
MIN_SPACING_MINUTES, MAX_SPACING_MINUTES = 2, 30
MAX_CALLS_LIMIT = 3


class EscStatus(StrEnum):
    PENDING = "pending"  # alert out, waiting for Acknowledge / the next call is due
    ACKED = "acked"  # the user tapped Acknowledge (or Call back / Ignore / Block on the alert)
    STOPPED = "stopped"  # the user rang Friday / wrote back: they know
    ANSWERED = "answered"  # Friday rang and the user picked up and heard the line
    EXHAUSTED = "exhausted"  # every allowed call was made, nobody answered
    CANCELLED = "cancelled"  # a rule said not to call (quiet hours, stale, cap, switch ...)
    REFUSED = "refused"  # a safety rule refused the dial (not the user's own number, gate deny)


FINAL = frozenset(
    {EscStatus.ACKED, EscStatus.STOPPED, EscStatus.ANSWERED, EscStatus.EXHAUSTED, EscStatus.CANCELLED, EscStatus.REFUSED}
)


class RingResult(StrEnum):
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    FAILED = "failed"
    REFUSED = "refused"  # the caller port refused (line pending, kill switch, allow-list)
    UNKNOWN = "unknown"  # the process died while ringing: counted as made, never redialled at once


class UserEscalationConfig(BaseModel):
    """What one user chose. ``number`` is the user's own phone, confirmed when they opted in; the
    call target must still equal the user's current phone at dial time."""

    opted_in: bool = False
    number: str | None = None  # E.164, the user's own
    minutes: int | None = None  # override of FRIDAY_URGENT_ESCALATION_MINUTES
    max_calls: int | None = None
    spacing_minutes: int | None = None
    emergency_in_quiet_hours: bool = True  # False: never ring in quiet hours, not even an emergency
    language: str = "hinglish"

    @field_validator("minutes")
    @classmethod
    def _minutes(cls, v: int | None) -> int | None:
        return None if v is None else max(MIN_WAIT_MINUTES, min(MAX_WAIT_MINUTES, int(v)))

    @field_validator("spacing_minutes")
    @classmethod
    def _spacing(cls, v: int | None) -> int | None:
        return None if v is None else max(MIN_SPACING_MINUTES, min(MAX_SPACING_MINUTES, int(v)))

    @field_validator("max_calls")
    @classmethod
    def _calls(cls, v: int | None) -> int | None:
        return None if v is None else max(1, min(MAX_CALLS_LIMIT, int(v)))


class Policy(BaseModel):
    """The global defaults (from ``Settings``)."""

    wait_s: int = 300
    max_calls: int = 2
    spacing_s: int = 300
    stale_s: int = 1800
    daily_cap: int = 3
    retention_days: int = 30

    @classmethod
    def from_settings(cls, s) -> Policy:  # noqa: ANN001
        return cls(
            wait_s=s.urgent_escalation_minutes * 60,
            max_calls=s.urgent_escalation_max_calls,
            spacing_s=s.urgent_escalation_spacing_minutes * 60,
            stale_s=s.urgent_escalation_stale_minutes * 60,
            daily_cap=s.urgent_escalation_daily_cap,
            retention_days=s.urgent_escalation_retention_days,
        )


class EscalationState(BaseModel):
    id: str = ""
    user_id: str
    message_id: str  # the receptionist message that was urgent
    status: EscStatus = EscStatus.PENDING
    emergency: bool = False  # a true emergency (may ring in quiet hours)
    alert_ok: bool = False  # the WhatsApp alert went out
    alert_sent_at: datetime | None = None
    wait_s: int = 300  # snapshot at open: later setting changes never move a running timer
    max_calls: int = 2
    spacing_s: int = 300
    next_action_at: datetime | None = None
    calls_made: int = 0
    in_flight: bool = False  # an attempt was claimed and has no result yet
    last_call_at: datetime | None = None
    last_call_result: str | None = None
    ack_at: datetime | None = None
    stop_reason: str | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def open(self) -> bool:
        return self.status == EscStatus.PENDING


class RingOutcome(BaseModel):
    result: RingResult
    detail: str = ""  # machine code, never user text
    duration_s: float = 0.0


class Decision(BaseModel):
    """What the policy says about one due state right now."""

    action: str  # call | wait | cancel | refuse
    reason: str = ""
    status: EscStatus | None = None  # for cancel / refuse
    next_action_at: datetime | None = Field(default=None)
