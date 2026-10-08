"""Runner-side commitment gate (SECURITY-3/4/27).

The runner is the last code gate: even if a policy forgets ``commits_booking=True`` (or
is prompt-injected), any utterance that *sounds* like a confirmation is treated as a
commitment and must pass ``friday.core.safety.check_commit``. Mirrors the brain's
detector (voice never imports ``friday.brain``); the detector now lives in core:
``friday.core.safety.looks_like_commitment`` (re-exported here for compatibility).
"""

from __future__ import annotations

from datetime import datetime

from friday.core.clock import ensure_utc
from friday.core.models import CallAction, CallBrief, TaskType
from friday.core.safety import looks_like_commitment  # noqa: F401  (moved to core; re-export)

# Task types where a SUCCESS outcome means "something was booked/ordered/agreed".
COMMIT_TYPES = frozenset(
    {
        TaskType.BOOKING,
        TaskType.HEALTHCARE,
        TaskType.RESCHEDULE,
        TaskType.ORDER,
        TaskType.RECURRING_BOOKING,
        TaskType.HOTEL_BOOKING,
        TaskType.QUOTE,
        TaskType.DISCOVERY,
        TaskType.RENTAL_HUNT,
        TaskType.SERVICE_COORDINATION,
        TaskType.COMPLAINT,
    }
)

def is_commit_action(action: CallAction) -> bool:
    return bool(action.commits_booking or looks_like_commitment(action.text))


def slot_of(action: CallAction) -> datetime | None:
    """Resolved slot start (aware UTC) if the policy supplied ``collected["slot_at"]``
    (ISO-8601). Without it a delegation WINDOW can't be verified -> call-back flow."""
    if action.slot_at is not None:
        return ensure_utc(action.slot_at)
    raw = action.collected.get("slot_at") if action.collected else None
    if not raw:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except ValueError:
        return None


def decisions_for(action: CallAction) -> list[str]:
    """Which delegated decisions this commitment makes ("slot", "price")."""
    explicit = (action.collected or {}).get("decision")
    if explicit:
        return [x.strip() for x in str(explicit).split(",") if x.strip()]
    out = ["slot"]
    if action.quote is not None and action.quote.amount_inr is not None:
        out.append("price")
    return out


def commit_reasons(brief: CallBrief, answers: list, action: CallAction) -> list[str]:
    """Reasons the commitment in ``action`` is NOT allowed ([] = allowed)."""
    from friday.core.safety import check_commit

    amount = action.quote.amount_inr if action.quote else None
    reasons: list[str] = []
    for decision in decisions_for(action):
        chk = check_commit(
            brief, answers, amount_inr=amount, slot_at=slot_of(action), decision=decision
        )
        for r in chk.reasons:
            if r not in reasons:
                reasons.append(r)
    return reasons
