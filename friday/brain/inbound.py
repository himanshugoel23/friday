"""Inbound business call-backs & missed calls (BRIEF section E, items 30-35).

Core has no inbound fields on ``CallBrief`` yet (proposed in docs/CORE_CHANGES.md),
so the brain uses ``InboundCallBrief`` - a ``CallBrief`` subclass carrying
``direction`` and an ``InboundContext``. It IS a ``CallBrief`` (the voice runner
needs nothing new); the policy reads the extras via ``inbound_of(brief)``, which
also works once core grows ``CallBrief.direction`` / ``CallBrief.inbound``.

Three situations
* ``answered``: a business called Friday's number back and we answered.
* ``missed_call``: a business rang and we missed it; Friday calls them back
  (an OUTBOUND call with call-back context).
* ``unknown``: no match in call memory -> take a message, reveal nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from friday.core.models import (
    CallBrief,
    CallDirection,
    CallOutcome,
    Quote,
    TaskStatus,
    TaskType,
)

InboundKind = Literal["answered", "missed_call", "unknown"]

# Resolution state of the related task (BRIEF E-37) - decides how a late call-back
# is handled:
#   open                -> resume the task normally (E-31)
#   fulfilled_elsewhere -> need met with ANOTHER business / user cancelled / stock found:
#   cancelled              politely close the loop, reveal nothing about where, hang up
#   stock_found
#   booked_here         -> booked with THIS business: the call is about that booking
#                          (reconfirm / reschedule / cancel / ready for pickup)
Resolution = Literal["open", "fulfilled_elsewhere", "cancelled", "stock_found", "booked_here"]
CLOSED_ELSEWHERE: frozenset[str] = frozenset({"fulfilled_elsewhere", "cancelled", "stock_found"})


class RelatedTask(BaseModel):
    """One earlier task/call with this business that the call-back may be about."""

    task_id: str
    task_type: TaskType
    goal: str
    label: str  # short spoken label: "haircut", "facial booking"
    beneficiary_name: str | None = None
    status: TaskStatus | None = None
    last_outcome: CallOutcome | None = None
    called_at: datetime | None = None
    discussed: str | None = None  # prior transcript summary / what was agreed so far
    last_quote: Quote | None = None
    approved_terms: str | None = None
    resolution: Resolution = "open"
    booking_details: str | None = None  # booked_here: the confirmed terms ("Sat 12:30, ₹600")


class InboundContext(BaseModel):
    kind: InboundKind = "answered"
    caller_phone: str
    friday_number: str | None = None  # which Friday caller-ID they rang / we dial from
    caller_matches_business: bool = True  # caller ID equals the business record (item 34)
    business_name: str | None = None
    related: list[RelatedTask] = Field(default_factory=list)  # candidates, newest first
    matched_task_id: str | None = None  # set when exactly one task matches

    @property
    def is_unknown(self) -> bool:
        return self.kind == "unknown" or not self.related

    @property
    def needs_disambiguation(self) -> bool:
        return self.matched_task_id is None and len(self.related) > 1


class InboundCallBrief(CallBrief):
    direction: CallDirection = CallDirection.INBOUND
    inbound: InboundContext | None = None


def inbound_of(brief: CallBrief) -> InboundContext | None:
    ctx = getattr(brief, "inbound", None)
    if isinstance(ctx, InboundContext):
        return ctx
    if isinstance(ctx, dict):
        return InboundContext.model_validate(ctx)
    return None


def task_label(task_type: TaskType, goal: str, item: str | None = None) -> str:
    """Short spoken label for "is this about the haircut or the facial?"."""
    g = (item or goal or "").strip()
    low = g.lower()
    for prefix in ("book ", "get ", "find ", "order ", "check ", "ask ", "cancel ", "move "):
        if low.startswith(prefix):
            g = g[len(prefix):]
            break
    for cut in (" for ", " at ", " with ", ",", " on ", " tomorrow", " today"):
        idx = g.lower().find(cut)
        if idx > 0:
            g = g[:idx]
    g = g.strip().removeprefix("a ").removeprefix("an ").strip()
    return g[:40] or task_type.value.replace("_", " ")
