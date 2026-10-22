"""Data models of the receptionist: per-user config, the captured message, urgency.

Phone numbers are E.164 strings in memory; they are masked in logs (``mask_phone``) and encrypted
at rest in the SQL store. Nothing here talks to a network.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

MIN_RINGS, MAX_RINGS, DEFAULT_RINGS = 3, 6, 5


class Urgency(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    SPAM = "spam"


class MessageStatus(StrEnum):
    NEW = "new"  # stored, user not told yet (normal ones wait for the morning brief)
    NOTIFIED = "notified"  # the WhatsApp summary was sent
    CALLED_BACK = "called_back"  # the user tapped "Call back"
    IGNORED = "ignored"
    BLOCKED = "blocked"


class CallOutcomeKind(StrEnum):
    MESSAGE = "message"  # name and/or reason captured
    NO_MESSAGE = "no_message"  # caller hung up or stayed silent
    SPAM_ENDED = "spam_ended"
    ABUSE_ENDED = "abuse_ended"
    BLOCKED = "blocked"  # number is on the user's block list: short polite end, nothing stored
    UNROUTED = "unrouted"  # redirecting number unknown: generic message-taker
    WRONG_NUMBER = "wrong_number"
    CAP_REACHED = "cap_reached"


class QuietHours(BaseModel):
    """Local (IST) hours in which a NORMAL message is never pushed; urgent ones still are."""

    start_hour: int = Field(default=22, ge=0, le=23)
    end_hour: int = Field(default=8, ge=0, le=23)

    def contains(self, hour: int) -> bool:
        if self.start_hour == self.end_hour:
            return False
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour


class ReceptionistConfig(BaseModel):
    """What one user chose in the setup page."""

    enabled: bool = False
    rings: int = Field(default=DEFAULT_RINGS, ge=MIN_RINGS, le=MAX_RINGS)
    forward_no_answer: bool = True
    forward_busy: bool = True  # also covers a declined call on most phones (verify per carrier)
    forward_unreachable: bool = True
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    urgent_keywords: list[str] = Field(default_factory=list)  # added to the built-in lists
    urgent_contacts: list[str] = Field(default_factory=list)  # E.164: always urgent
    known_contacts: dict[str, str] = Field(default_factory=dict)  # E.164 -> display name
    user_name: str = ""  # how callers hear the user's name ("Himanshu"); never a pronoun
    language: str = "hinglish"  # hinglish | hi | en
    # Facts that must NEVER be spoken (city, address, schedule). Used only by the safety checks.
    private_facts: list[str] = Field(default_factory=list)

    @field_validator("urgent_keywords")
    @classmethod
    def _clean_keywords(cls, v: list[str]) -> list[str]:
        return [k.strip().lower() for k in v if k and k.strip()][:50]


class Classification(BaseModel):
    urgency: Urgency
    reasons: list[str] = Field(default_factory=list)
    source: str = "rules"  # rules | llm
    known_contact: bool = False
    contact_name: str | None = None


class CallCapture(BaseModel):
    """Everything the call produced (before storing). ``snippet`` is the caller's own words,
    secrets redacted, only kept when the caller did not object."""

    caller_name: str | None = None
    reason: str | None = None
    callback_number: str | None = None  # only when the caller volunteered one
    snippet: str | None = None
    language: str = "hinglish"
    outcome: CallOutcomeKind = CallOutcomeKind.NO_MESSAGE
    declined_notes: bool = False  # the caller said "do not note this down"
    asked_if_ai: bool = False
    asked_secret: bool = False  # the caller asked for an OTP / PIN / card detail
    duration_s: float = 0.0
    turns: int = 0
    transcript: list[tuple[str, str]] = Field(default_factory=list)  # (speaker, text), NOT stored


class StoredMessage(BaseModel):
    id: str = ""
    user_id: str | None = None  # None: unrouted (no user could be identified)
    caller_number: str | None = None
    caller_name: str | None = None
    reason: str | None = None
    urgency: Urgency = Urgency.NORMAL
    snippet: str | None = None
    callback_number: str | None = None
    outcome: CallOutcomeKind = CallOutcomeKind.MESSAGE
    status: MessageStatus = MessageStatus.NEW
    known_contact_name: str | None = None
    created_at: datetime | None = None
    notified_at: datetime | None = None
    duration_s: float = 0.0
    classification_reasons: list[str] = Field(default_factory=list)


def as_dict(m: BaseModel) -> dict[str, Any]:
    return m.model_dump(mode="json")
