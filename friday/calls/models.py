"""Data model of a consumer call: request, brief (what the user approved) and outcome.

``CallBrief.content_hash`` covers EVERYTHING that decides what Friday says or does on the call
(goal, must say, must not say, questions, limits, facts, the exact opening line the user saw and
the callee number hash). Approval stores that hash; any edit changes it, which invalidates the
approval (enforced in code in ``CallGate``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.models import new_id


class CalleeKind(StrEnum):
    BUSINESS = "business"
    PROVIDER = "provider"  # plumber, driver, cook, tutor, landlord the user already uses
    CUSTOMER_CARE = "customer_care"
    FAMILY_FRIEND = "family_friend"
    OFFICIAL = "official"  # school, RWA, society office, help desk, clinic desk
    UNKNOWN = "unknown"  # a number from a message or an ad
    GROUP = "group"  # parent request that fans out to children


class PurposeKind(StrEnum):
    INFORM = "inform"  # "tell mummy I'm late"
    ASK = "ask"  # "ask the school office the fee date"
    REQUEST = "request"  # "ask the plumber to come tomorrow"
    DISPUTE = "dispute"  # "dispute a bill"
    REMIND = "remind"
    INVITE = "invite"
    CONFIRM = "confirm"
    CALLBACK = "callback"
    OTHER = "other"


class CallStatus(StrEnum):
    """Lifecycle of one call request."""

    DRAFT = "draft"
    NEEDS_INFO = "needs_info"  # one question out to the user
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"  # waiting for its time (first call, retry or call-back)
    CALLING = "calling"
    COMPLETED = "completed"
    GROUP_WAITING = "group_waiting"  # parent: children still running
    DENIED = "denied"  # the safety gate said no
    FAILED = "failed"  # tries used up
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            CallStatus.COMPLETED,
            CallStatus.DENIED,
            CallStatus.FAILED,
            CallStatus.CANCELLED,
        )


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"  # goal met
    PARTIAL = "partial"  # some answers, goal not fully met
    DECLINED = "declined"  # the other side said no
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    CALLBACK_LATER = "callback_later"  # "call after 5"
    WRONG_PERSON = "wrong_person"
    OPTED_OUT = "opted_out"  # "do not call me again"
    SAFETY_STOP = "safety_stop"  # distress / hostile / told to stop; engine ended it
    FAILED = "failed"  # technical

    @property
    def is_retryable(self) -> bool:
        return self in (
            OutcomeStatus.NO_ANSWER,
            OutcomeStatus.BUSY,
            OutcomeStatus.VOICEMAIL,
            OutcomeStatus.CALLBACK_LATER,
            OutcomeStatus.FAILED,
        )


class NextAction(StrEnum):
    DONE = "done"
    CALL_AGAIN = "call_again"
    CALL_LATER = "call_later"
    SEND_MESSAGE = "send_message"
    ADD_REMINDER = "add_reminder"
    APPROVE_COMMITMENT = "approve_commitment"
    DECLINE_COMMITMENT = "decline_commitment"
    STOP_CALLING = "stop_calling"
    DELETE_RECORDING = "delete_recording"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TimeWindow(_M):
    start: str  # "HH:MM" IST
    end: str


class Limits(_M):
    max_price_inr: int | None = None
    deadline: datetime | None = None
    time_windows: list[TimeWindow] = Field(default_factory=list)  # when the OTHER side may be asked
    max_duration_s: int | None = None


class CallRequest(_M):
    id: str = Field(default_factory=new_id)
    user_id: str
    callee_kind: CalleeKind
    purpose: str  # the user's own words (trimmed), never rewritten into new facts
    purpose_kind: PurposeKind = PurposeKind.OTHER
    callee_ref: str | None = None  # what the user called them: "mummy", "Airtel", "Sharma ji"
    callee_name: str | None = None  # resolved display name
    callee_number: str | None = Field(default=None, repr=False)  # E.164; never logged
    number_confirmed: bool = False  # user confirmed the number back (first call to it)
    company: str | None = None
    language: str = "hinglish"
    scheduled_for: datetime | None = None
    parent_id: str | None = None  # group child -> parent request
    callback_of: str | None = None  # id of the missed call / earlier request being answered
    group_members: list[str] = Field(default_factory=list)  # group parent: member references
    raw_text: str | None = Field(default=None, repr=False)  # the user's message, for the classifier
    source_message_id: str | None = None
    status: CallStatus = CallStatus.DRAFT
    attempts: int = 0
    next_attempt_at: datetime | None = None
    task_id: str | None = None  # the task-engine task that tracks the current attempt
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def idempotency_key(self) -> str:
        """Same user message => same key, so a webhook re-delivery never makes a second request."""
        basis = (
            f"{self.user_id}|{self.source_message_id}|{self.callee_ref}|{self.purpose}|"
            f"{self.callback_of}|{self.parent_id}"
            if self.source_message_id
            else self.id
        )
        return hashlib.sha256(basis.encode()).hexdigest()[:32]


class CallBrief(_M):
    request_id: str
    user_id: str
    version: int = 1
    callee_kind: CalleeKind
    callee_name: str | None = None
    callee_number_hash: str | None = None
    goal: str
    must_say: list[str] = Field(default_factory=list)
    must_not_say: list[str] = Field(default_factory=list)
    ask_list: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    tone: str = "friendly"
    relationship: str | None = None  # "mother", "plumber", "customer care"
    language: str = "hinglish"
    user_display_name: str | None = None  # used in the fixed disclosure line
    shareable_facts: list[str] = Field(default_factory=list)  # may be told to the callee
    private_facts: list[str] = Field(default_factory=list, repr=False)  # never leave Friday
    opening_line: str | None = None  # EXACT first line the user saw (from OpeningLineProvider)
    # approval (set only by ApprovalService after the user pressed Approve)
    approved: bool = False
    approval_hash: str | None = None
    approved_at: datetime | None = None

    _APPROVAL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"approved", "approval_hash", "approved_at"}
    )

    def content_hash(self) -> str:
        data: dict[str, Any] = self.model_dump(mode="json", exclude=set(self._APPROVAL_FIELDS))
        blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def is_approved_as_is(self) -> bool:
        """Approved AND the content still hashes to what the user approved."""
        return bool(self.approved and self.approval_hash == self.content_hash())


class Commitment(_M):
    text: str  # "plumber will come tomorrow 10am"
    needs_user_approval: bool = False
    approved: bool | None = None  # None = not asked yet


class CallOutcome(_M):
    request_id: str
    attempt: int = 1
    status: OutcomeStatus
    summary: str = ""  # plain words, from what the callee said
    answers: dict[str, str] = Field(default_factory=dict)  # ask_list item -> what they said
    commitments: list[Commitment] = Field(default_factory=list)
    needs_user_approval: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    callback_at: datetime | None = None  # "call me after 5" -> when
    do_not_call_again: bool = False  # the callee asked not to be called
    started_at: datetime | None = None
    duration_s: float = 0.0
    transcript_ref: str | None = None
    recording_ref: str | None = None
