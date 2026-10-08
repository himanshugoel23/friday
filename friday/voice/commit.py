"""Runner-side commitment gate (SECURITY-3/4/27).

The runner is the last code gate: even if a policy forgets ``commits_booking=True`` (or
is prompt-injected), any utterance that *sounds* like a confirmation is treated as a
commitment and must pass ``friday.core.safety.check_commit``. Mirrors the brain's
detector (voice never imports ``friday.brain``); proposed as a core helper
``safety.looks_like_commitment`` in docs/CORE_CHANGES.md.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from friday.core.clock import ensure_utc
from friday.core.models import CallAction, CallBrief, TaskType

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

_PHRASES = (
    "i confirm", "please confirm the", "confirm the booking", "book it", "book kar dijiye",
    "book kar do", "confirm kar dijiye", "confirm kijiye", "pakka kar", "lock kar",
    "go ahead and book", "please book", "place the order", "order kar dijiye",
    "rakh lijiye", "reserve kar", "reserve the", "reserved",
)  # fmt: skip
_COMMIT_VERB = re.compile(
    r"\b(reserve|reserved|book|booked|confirm|confirmed|final|finali[sz]e|lock|pakka|done|"
    r"kar dijiye|rakh lijiye|fix)\b|बुक|कन्फर्म|पक्का|फाइनल",
    re.I,
)
_SLOT = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|baje|bje|o'?clock)\b|"
    r"\b(?:today|tomorrow|kal|aaj|slot|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"sat|sun)\b|₹\s*\d|\brs\.?\s*\d|\b\d+\s*(?:rupees|rupaye)\b|बजे|कल|आज|स्लॉट",
    re.I,
)
_NOT_A_COMMIT = (
    "call back", "callback", "confirm karke", "se confirm", "confirm with", "check with",
    "checking with", "like to book", "want to book", "chahiye tha", "what slots",
    "kaunse slot", "available", "kya aap", "could you", "can you", "kar sakte",
    "will confirm", "baad mein", "get back", "check karke", "hold kar", "share this",
    "bata ke", "after checking", "wapas call", "phir call", "puchh", "pooch", "पूछकर",
    "वापस कॉल",
)  # fmt: skip


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def looks_like_commitment(text: str | None) -> bool:
    """True when ``text`` reads as confirming a booking/order/price. When unsure and the
    text contains a commit verb next to a slot/price, we treat it as a commitment."""
    if not text:
        return False
    t = _norm(text)
    if any(p in t for p in _PHRASES):
        return True
    if any(p in t for p in _NOT_A_COMMIT):
        return False
    return bool(_COMMIT_VERB.search(t) and _SLOT.search(t))


def is_commit_action(action: CallAction) -> bool:
    return bool(action.commits_booking or looks_like_commitment(action.text))


def slot_of(action: CallAction) -> datetime | None:
    """Resolved slot start (aware UTC) if the policy supplied ``collected["slot_at"]``
    (ISO-8601). Without it a delegation WINDOW can't be verified -> call-back flow."""
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
