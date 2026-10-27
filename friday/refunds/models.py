"""Plain models of refund tracking. Money is paise (int); times are aware UTC.

A refund case is the user's claim "money should come back". Friday never sees the bank, so
"received" is only ever the user's word or a document/message the user supplied (proof levels from
``friday.evidence``: observed / vendor_stated / user_supplied).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.models import new_id
from friday.evidence.models import EvidenceKind, EvidenceLevel


class RefundState(StrEnum):
    SUSPECTED = "suspected"  # Friday noticed a cancellation: a PROPOSAL, the user must confirm
    OPENED = "opened"
    REQUESTED = "requested"
    VENDOR_ACKNOWLEDGED = "vendor_acknowledged"
    PROMISED = "promised"  # the vendor named a date and an amount
    RECEIVED = "received"  # the user says (or proves) it arrived, but the amount is short
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CLOSED = "closed"


ACTIVE_STATES = (
    RefundState.OPENED,
    RefundState.REQUESTED,
    RefundState.VENDOR_ACKNOWLEDGED,
    RefundState.PROMISED,
    RefundState.RECEIVED,
    RefundState.REJECTED,
    RefundState.ESCALATED,
)
OPEN_STATES = (RefundState.SUSPECTED, *ACTIVE_STATES)


class Origin(StrEnum):
    TRIP_LEG = "trip_leg"  # a cancelled flight / train / stay of a trip
    ORDER = "order"  # a cancelled order (a Friday task)
    BILL_DISPUTE = "bill_dispute"  # a wrong bill or charge
    USER = "user"  # "mera refund nahi aaya"


class CloseReason(StrEnum):
    RECEIVED = "received"  # money arrived (proof or the user's confirmation)
    ACCEPTED_REJECTION = "accepted_rejection"  # the user accepted the vendor's no
    USER_DROPPED = "user_dropped"  # the user does not want to chase it
    DECLINED = "declined"  # a suspected case the user said no to
    UNCONFIRMED = "unconfirmed"  # a suspected case nobody confirmed (only a SUSPECTED case)


class Source(StrEnum):
    USER = "user"
    SYSTEM = "system"
    TIMER = "timer"
    CALL = "call"
    TRIP = "trip"


class Basis(StrEnum):
    """Why a case may say money was received / may be closed."""

    USER = "user"  # the user confirmed
    PROOF = "proof"  # a document / message with the amount (user_supplied or better)


class Proposal(BaseModel):
    """A vendor follow-up Friday suggests. Nothing runs until the user approves it."""

    model_config = ConfigDict(extra="forbid")

    kind: str  # "call" | "message_draft"
    status: str = "offered"  # offered | approved | declined | needs_number
    contact_id: str | None = None  # which resolved contact (hash), re-resolved at approval
    task_id: str | None = None  # the Friday task started after approval
    offered_at: datetime = Field(default_factory=utcnow)


class RefundCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    state: RefundState = RefundState.OPENED
    origin: Origin = Origin.USER
    origin_ref: str | None = None  # trip leg id / Friday task id / bill id (an id, never text)
    vendor_name: str = ""
    amount_expected_paise: int | None = Field(default=None, ge=0)
    amount_received_paise: int | None = Field(default=None, ge=0)
    promised_date: date | None = None
    promised_amount_paise: int | None = Field(default=None, ge=0)
    paid_with_bank: str | None = None  # a bank NAME the user gave; never a number
    user_number: str | None = None  # a vendor number the user typed (E.164)
    task_id: str | None = None  # the Friday task that did the booking / order, if any
    state_epoch: int = 0  # +1 on every change; part of the reminder key
    state_changed_at: datetime = Field(default_factory=utcnow)
    closed_reason: CloseReason | None = None
    closed_basis: Basis | None = None
    proposal: Proposal | None = None
    chase_count: int = 0  # approved vendor follow-ups so far
    muted: bool = False
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def is_open(self) -> bool:
        return self.state != RefundState.CLOSED


class RefundEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    case_id: str
    from_state: RefundState | None
    to_state: RefundState
    source: Source
    note: str | None = None
    at: datetime = Field(default_factory=utcnow)


class RefundEvidence(BaseModel):
    """One piece of evidence on a case. Same levels as the proof module; no raw bytes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    case_id: str
    kind: EvidenceKind
    level: EvidenceLevel
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    amount_paise: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    proof_item_id: str | None = None  # the evidence_items row of a follow-up task, if linked
    captured_at: datetime = Field(default_factory=utcnow)


class RefundNudge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    case_id: str
    key: str  # refund:<case_id>:<epoch>:<n>
    stage: str
    status: str = "sent"  # sent | expired
    text: str | None = None
    sent_at: datetime = Field(default_factory=utcnow)
