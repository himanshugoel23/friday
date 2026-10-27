"""Evidence vocabulary. Levels say WHO saw the thing, never "the model believes it"."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.models import new_id


class EvidenceLevel(StrEnum):
    OBSERVED = "observed"  # our own system saw it (a recorded call outcome, a browser step)
    VENDOR_STATED = "vendor_stated"  # the business said it on the call / in a message
    USER_SUPPLIED = "user_supplied"  # the user forwarded it
    # No "verified_by_model": a model's opinion is never evidence.


class EvidenceKind(StrEnum):
    CALL_SUMMARY = "call_summary"
    CALL_RECORDING_REF = "call_recording_ref"
    TRANSCRIPT_EXCERPT = "transcript_excerpt"
    SCREENSHOT = "screenshot"
    ORDER_ID = "order_id"
    BOOKING_REF = "booking_ref"
    RECEIPT_FILE = "receipt_file"  # fingerprint + extracted fields only, never the bytes
    CONFIRMATION_TEXT = "confirmation_text"  # SMS/email text the user forwarded
    VENDOR_MESSAGE = "vendor_message"
    USER_CONFIRMED = "user_confirmed"


REFERENCE_KINDS = frozenset({EvidenceKind.ORDER_ID, EvidenceKind.BOOKING_REF})
OBSERVATION_KINDS = frozenset({EvidenceKind.CALL_SUMMARY, EvidenceKind.SCREENSHOT})
VENDOR_WORD_KINDS = frozenset(
    {EvidenceKind.CONFIRMATION_TEXT, EvidenceKind.VENDOR_MESSAGE, EvidenceKind.TRANSCRIPT_EXCERPT}
)


class ClaimType(StrEnum):
    BOOKED = "booked"
    ORDERED = "ordered"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"
    REFUND_REQUESTED = "refund_requested"
    INFO_FOUND = "info_found"


class ProofStatus(StrEnum):
    PROVEN = "proven"
    PARTIAL = "partial"
    UNPROVEN = "unproven"


class Redaction(StrEnum):
    NONE = "none"
    MASKED = "masked"


class EvidenceItem(BaseModel):
    """One piece of evidence. ``payload`` is small structured data (ref, outcome, host, duration);
    ``summary`` is short scrubbed text. Neither ever holds raw document or image bytes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    task_id: str
    call_id: str | None = None
    kind: EvidenceKind
    level: EvidenceLevel
    summary: str = ""
    payload: dict[str, str] = Field(default_factory=dict)
    object_key: str | None = None  # a masked screenshot in the object store, if any
    sha256: str | None = None
    source: str = "engine"
    captured_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    shareable: bool = False
    redaction: Redaction = Redaction.NONE


class DoneClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    task_id: str
    claim_type: ClaimType
    required_level: EvidenceLevel
    status: ProofStatus
    evidence_ids: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # codes, see policy.MISSING_*
    created_at: datetime = Field(default_factory=utcnow)


class DoneMessage(BaseModel):
    """What the engine sends instead of the bare summary. ``says_done`` is False whenever the
    text must not claim completion."""

    model_config = ConfigDict(extra="forbid")

    text: str
    status: ProofStatus
    says_done: bool
    claim: DoneClaim
