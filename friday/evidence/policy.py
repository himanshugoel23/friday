"""Minimum evidence per claim type. Pure code, no model: the table below decides.

A claim is PROVEN when every requirement of its rule is met, PARTIAL when some evidence exists but a
requirement is missing, UNPROVEN when there is no evidence at all. Strictness (may the message say
"done" without PROVEN?) is configuration: strict for bookings and orders, soft for information.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from friday.core.models import TaskType
from friday.evidence.models import (
    OBSERVATION_KINDS,
    REFERENCE_KINDS,
    VENDOR_WORD_KINDS,
    ClaimType,
    EvidenceItem,
    EvidenceLevel,
    ProofStatus,
)

# codes for what is missing (copy.py has one line per code)
MISSING_REFERENCE = "reference"  # an order id / booking ref / ticket number
MISSING_OBSERVED = "observed"  # a recorded call outcome or a screenshot WE captured
MISSING_VENDOR_WORD = "vendor_word"  # the business confirming, by ref or in words
MISSING_ANY = "any"  # no usable evidence of any kind

DEFAULT_STRICT_CLAIMS = (
    ClaimType.BOOKED,
    ClaimType.ORDERED,
    ClaimType.CANCELLED,
    ClaimType.RESCHEDULED,
    ClaimType.REFUND_REQUESTED,
)


@dataclass(frozen=True)
class Rule:
    needs_reference: bool = False
    needs_observed: bool = False
    needs_vendor_word: bool = False  # a vendor_stated item, or a reference
    needs_any_trusted: bool = False  # any observed / vendor_stated item


RULES: dict[ClaimType, Rule] = {
    # a booking or an order without a reference is not proven, however sure the call sounded
    ClaimType.BOOKED: Rule(needs_reference=True, needs_observed=True),
    ClaimType.ORDERED: Rule(needs_reference=True, needs_observed=True),
    # vendors often give no reference when cancelling or moving a slot: our own record of the
    # call plus the vendor saying so is enough, and the message says that no reference exists
    ClaimType.CANCELLED: Rule(needs_observed=True, needs_vendor_word=True),
    ClaimType.RESCHEDULED: Rule(needs_observed=True, needs_vendor_word=True),
    ClaimType.REFUND_REQUESTED: Rule(needs_reference=True, needs_observed=True),
    ClaimType.INFO_FOUND: Rule(needs_any_trusted=True),
}

_CLAIM_BY_TASK: dict[TaskType, ClaimType] = {
    TaskType.BOOKING: ClaimType.BOOKED,
    TaskType.HEALTHCARE: ClaimType.BOOKED,
    TaskType.HOTEL_BOOKING: ClaimType.BOOKED,
    TaskType.RECURRING_BOOKING: ClaimType.BOOKED,
    TaskType.ORDER: ClaimType.ORDERED,
    TaskType.RESCHEDULE: ClaimType.RESCHEDULED,
    TaskType.CANCEL_BOOKING: ClaimType.CANCELLED,
}
_REFUND_TYPES = {TaskType.CUSTOMER_CARE, TaskType.COMPLAINT, TaskType.STATUS_CHASE}


def claim_type_for(task_type: TaskType, goal: str = "") -> ClaimType:
    if task_type in _CLAIM_BY_TASK:
        return _CLAIM_BY_TASK[task_type]
    if task_type in _REFUND_TYPES and "refund" in goal.lower():
        return ClaimType.REFUND_REQUESTED
    return ClaimType.INFO_FOUND


def is_strict(
    claim: ClaimType, *, strict: bool = True, strict_claims: Iterable[ClaimType | str] | None = None
) -> bool:
    """``strict`` is the master switch (False = every claim soft). ``strict_claims`` is the list of
    claim types that are strict (default: everything but information tasks)."""
    if not strict:
        return False
    chosen = DEFAULT_STRICT_CLAIMS if strict_claims is None else strict_claims
    return str(claim) in {str(c) for c in chosen}


def required_level(claim: ClaimType, *, strict: bool) -> EvidenceLevel:
    """Strict claims need something WE observed; soft ones accept the vendor's word."""
    return EvidenceLevel.OBSERVED if strict else EvidenceLevel.VENDOR_STATED


def evaluate(claim: ClaimType, items: Iterable[EvidenceItem]) -> tuple[ProofStatus, list[str]]:
    items = list(items)
    if not items:
        return ProofStatus.UNPROVEN, [MISSING_ANY]
    rule = RULES[claim]
    has_ref = any(i.kind in REFERENCE_KINDS and i.payload.get("ref") for i in items)
    has_observed = any(
        i.kind in OBSERVATION_KINDS and i.level == EvidenceLevel.OBSERVED for i in items
    )
    has_vendor_word = has_ref or any(
        i.level == EvidenceLevel.VENDOR_STATED and i.kind in (VENDOR_WORD_KINDS | REFERENCE_KINDS)
        for i in items
    )
    has_trusted = any(
        i.level in (EvidenceLevel.OBSERVED, EvidenceLevel.VENDOR_STATED) for i in items
    )
    missing: list[str] = []
    if rule.needs_reference and not has_ref:
        missing.append(MISSING_REFERENCE)
    if rule.needs_observed and not has_observed:
        missing.append(MISSING_OBSERVED)
    if rule.needs_vendor_word and not has_vendor_word:
        missing.append(MISSING_VENDOR_WORD)
    if rule.needs_any_trusted and not has_trusted:
        missing.append(MISSING_ANY)
    if not missing:
        return ProofStatus.PROVEN, []
    if rule.needs_any_trusted:
        return ProofStatus.UNPROVEN, missing
    return ProofStatus.PARTIAL, missing
