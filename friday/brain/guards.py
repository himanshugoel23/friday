"""Hard rules enforced in CODE on every call action, whichever path produced it
(founder rules + ARCHITECTURE §1.4). The voice runner enforces safety/can_commit
again; doing it here too means the brain never even proposes a violating action.

1. Commitments: any text that confirms a booking/order is flagged
   ``commits_booking``; if the brief does not allow committing (no approved terms,
   no mid-call approval, no delegation) -> replaced by the call-back route.
   Under a delegation, the offer must also be inside its price/time limits.
2. Money: no promise to pay / prepay / deposit.
3. Secrets & numbers: ``friday.core.safety`` on text and DTMF; violations are
   replaced by a safe action (patch-in or NEEDS_USER_VERIFICATION).
4. Shape: ASK_USER always carries a question (<= 3 options); HANGUP always has an
   outcome; no filler words; quote/care converted to core models.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from friday.core.clock import utcnow
from friday.core.models import (
    CallAction,
    CallActionType,
    CallBrief,
    CallOutcome,
    CareOutcome,
    EscalationLevel,
    MidCallQuestion,
    Quote,
    TaskType,
    UserAnswer,
)
from friday.core.safety import check_keys, check_speech

from .lang import text_language
from .schemas import CallActionOut, CareOut, QuoteOut
from .textutil import (
    format_inr,
    has_any,
    minutes_of,
    norm,
    parse_time_of_day,
    slot_to_datetime,
)

_FILLERS = re.compile(r"(?<!\w)(u+m+|u+h+|h+m+|e+r+m*|a+h+)(?!\w)[,.]?\s*", re.I)
_COMMIT_PHRASES = (
    "confirm kar dijiye",
    "confirm kar do",
    "book kar dijiye",
    "book kar do",
    "please confirm",
    "please book",
    "go ahead and book",
    "confirm the booking",
    "confirm it",
    "book it",
    "order place kar",
    "place the order",
    "kar dijiye book",
    "pakka kar dijiye",
    "कन्फ़र्म कर दीजिए",
    "बुक कर दीजिए",
    "we'll take it",
    "lock it",
    "final kar dijiye",
)
_MONEY_PROMISE = (
    "i will pay",
    "i'll pay",
    "we will pay",
    "we'll pay",
    "payment kar dungi",
    "pay kar dungi",
    "advance de",
    "advance bhej",
    "deposit de",
    "deposit kar",
    "transfer kar dungi",
    "upi kar",
    "paise bhej",
    "send the money",
    "make the payment",
)
_COMMIT_TYPES_NEED_APPROVAL = {
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


_BOOKING_TYPES = {
    TaskType.BOOKING,
    TaskType.HEALTHCARE,
    TaskType.ORDER,
    TaskType.RECURRING_BOOKING,
    TaskType.HOTEL_BOOKING,
    TaskType.RESCHEDULE,
}
# inbound call-back successes that are not new commitments (E-37)
_INBOUND_SUCCESS_KEYS = {"reconfirmed", "ready", "closed_loop", "message_taken"}


def strip_fillers(text: str | None) -> str | None:
    if not text:
        return text
    out = _FILLERS.sub("", text).strip()
    return re.sub(r"\s{2,}", " ", out) or text


_COMMIT_VERB = re.compile(
    r"\b(reserve|reserved|book|booked|confirm|confirmed|final|finali[sz]e|"
    r"lock|pakka|done)\b",
    re.I,
)
_SLOT_MENTION = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|baje|bje|o'?clock)\b|"
    r"\b(?:today|tomorrow|kal|aaj|slot)\b|₹\s*\d",
    re.I,
)
_NOT_A_COMMIT = (
    "call back",
    "callback",
    "confirm karke",
    "se confirm",
    "confirm with",
    "check with",
    "checking with",
    "like to book",
    "want to book",
    "chahiye tha",
    "what slots",
    "kaunse slot",
    "available",
    "kya aap",
    "could you",
    "can you",
    "kar sakte",
    "will confirm",
    "baad mein",
    "get back",
    "check karke",
    "hold kar",
    "share this",
    "bata ke",
)


def _looks_like_commit(text: str | None) -> bool:
    """Catches verbal commitments the model did not flag: an explicit phrase, or a
    commit verb next to a slot/time/price - unless it is clearly a call-back/ask."""
    if not text:
        return False
    t = norm(text)
    if has_any(t, _COMMIT_PHRASES):
        return True
    if has_any(t, _NOT_A_COMMIT):
        return False
    return bool(_COMMIT_VERB.search(t) and _SLOT_MENTION.search(t))


def quote_from(out: QuoteOut | None, brief: CallBrief) -> Quote | None:
    if out is None:
        return None
    within = None
    if out.amount_inr is not None and brief.budget and brief.budget.max_inr:
        within = out.amount_inr <= brief.budget.max_inr
    return Quote(
        business_id=brief.business.id if brief.business else brief.target.business_id,
        business_name=brief.target.name,
        amount_inr=out.amount_inr,
        original_amount_inr=out.original_amount_inr,
        price_text=out.price_text or (format_inr(out.amount_inr) if out.amount_inr else "-"),
        inclusions=out.inclusions,
        exclusions=out.exclusions,
        validity=out.validity,
        available_slots=out.available_slots,
        notes=out.notes,
        within_budget=within,
        task_id=brief.task_id,
    )


def care_from(out: CareOut | None, brief: CallBrief) -> CareOutcome | None:
    if out is None:
        return None
    promised = None
    if out.promised_date:
        try:
            promised = date.fromisoformat(out.promised_date[:10])
        except ValueError:
            promised = None
    level = min(max(int(out.escalation_level or 1), 1), 5)
    return CareOutcome(
        company=brief.company or brief.target.name,
        request_kind=brief.care_request,
        ticket_number=out.ticket_number,
        agent_name=out.agent_name,
        promised_date=promised,
        promised_text=out.promised_text,
        escalation_level=EscalationLevel(level),
        resolved=out.resolved,
        ivr_path=out.ivr_path,
    )


def within_delegation(brief: CallBrief, quote: Quote | None, text: str | None) -> bool:
    """Is the offer being confirmed inside the explicit delegation's limits?"""
    d = brief.delegation
    if not d.granted:
        return False
    amount = quote.amount_inr if quote else None
    if d.max_price_inr is not None and not d.allows_price(amount):
        return False
    slots = list(quote.available_slots) if quote else []
    # the slot being confirmed is the one named in the text, else the first offered
    named = [s for s in slots if text and norm(s) in norm(text)]
    chosen = named[0] if named else (slots[0] if slots else None)
    if chosen is None:
        return d.window_start is None and d.window_end is None and not d.time_window_text
    when = slot_to_datetime(chosen, _ref_now(brief))
    if when is None:
        return False
    if (d.window_start or d.window_end) and not d.allows_time(when):
        return False
    if d.time_window_text:
        s, e, _exact = parse_time_of_day(d.time_window_text)
        if s is not None:
            e = e if e is not None else s + 60
            if not (s <= minutes_of(when) <= e):
                return False
    return True


def _ref_now(brief: CallBrief) -> datetime:
    return brief.window_start or brief.delegation.window_start or utcnow()


def callback_action(brief: CallBrief, out: CallActionOut, reason: str) -> CallAction:
    lang = text_language(out.language)
    name = brief.on_behalf_of.split()[0] if brief.on_behalf_of else "my user"
    text = {
        "en": f"Thank you. I'll confirm with {name} and call you back shortly.",
        "hi": f"शुक्रिया जी। मैं {name} जी से कन्फ़र्म करके थोड़ी देर में कॉल बैक करती हूँ।",
    }.get(
        lang.value,
        f"Shukriya ji. Main {name} ji se confirm karke thodi der mein call back karti hoon.",
    )
    collected = {kv.key: kv.value for kv in out.collected}
    collected["guard"] = reason
    return CallAction(
        type=CallActionType.HANGUP,
        text=text,
        language=lang if lang == out.language else out.language,
        outcome=CallOutcome.PENDING_APPROVAL,
        collected=collected,
        quote=quote_from(out.quote, brief),
        care=care_from(out.care, brief),
    )


def to_call_action(out: CallActionOut, brief: CallBrief, answers: list[UserAnswer]) -> CallAction:
    """Validate + guard a wire action and convert it to the core ``CallAction``."""
    text = strip_fillers(out.text)
    quote = quote_from(out.quote, brief)
    collected = {kv.key: kv.value for kv in out.collected}

    # ---- money promises are never allowed
    if text and has_any(norm(text), _MONEY_PROMISE):
        return callback_action(brief, out, "money_promise")

    # ---- commitments
    commits = out.commits_booking or (
        out.type in (CallActionType.SAY, CallActionType.HANGUP)
        and _looks_like_commit(text)
        and brief.task_type in _COMMIT_TYPES_NEED_APPROVAL
    )
    if commits:
        approved_here = any(a.approves for a in answers)
        if not brief.can_commit(list(answers)):
            return callback_action(brief, out, "no_approval")
        if (
            not brief.approved_terms
            and not approved_here
            and not within_delegation(brief, quote, text)
        ):
            return callback_action(brief, out, "outside_delegation")
    if (
        out.type == CallActionType.HANGUP
        and out.outcome == CallOutcome.SUCCESS
        and brief.task_type in _BOOKING_TYPES
        and not brief.can_commit(list(answers))
        and not (set(collected) & _INBOUND_SUCCESS_KEYS)
    ):
        # a booking "success" without any approval is a hallucinated confirmation:
        # report it as an offer (call-back route) or as partial info, never as booked
        out.outcome = CallOutcome.PENDING_APPROVAL if quote is not None else CallOutcome.PARTIAL
        collected["guard"] = "unapproved_success_downgraded"

    # ---- safety on speech / keys
    if text and out.type in (
        CallActionType.SAY,
        CallActionType.HANGUP,
        CallActionType.ASK_USER,
        CallActionType.BRIDGE_USER,
    ):
        check = check_speech(text, brief)
        if not check.allowed:
            return _safe_alternative(brief, out, "; ".join(check.reasons))
    if out.type == CallActionType.PRESS_KEYS:
        if not out.digits:
            out.type = CallActionType.WAIT
        else:
            check = check_keys(out.digits, brief)
            if not check.allowed:
                return _safe_alternative(brief, out, "; ".join(check.reasons))

    # ---- shape
    question = None
    if out.type == CallActionType.ASK_USER:
        q = out.question
        if q is None:
            q_text = text or "Quick question from the call - how should I proceed?"
            question = MidCallQuestion(task_id=brief.task_id, text=q_text)
        else:
            question = MidCallQuestion(
                task_id=brief.task_id,
                text=q.text,
                purpose=q.purpose,
                options=[o[:60] for o in q.options[:3]],
                timeout_s=brief.approval.hold_timeout_s,
            )
    outcome = out.outcome
    if out.type == CallActionType.HANGUP and outcome is None:
        if (
            quote is not None
            and brief.task_type in _COMMIT_TYPES_NEED_APPROVAL
            and not brief.can_commit(list(answers))
        ):
            outcome = CallOutcome.PENDING_APPROVAL
        else:
            outcome = CallOutcome.PARTIAL
    if out.type == CallActionType.BRIDGE_USER and not brief.user_phone:
        return CallAction(
            type=CallActionType.HANGUP,
            text=text,
            language=out.language,
            outcome=CallOutcome.NEEDS_USER_VERIFICATION,
            collected=collected,
            quote=quote,
            care=care_from(out.care, brief),
        )
    return CallAction(
        type=out.type,
        text=text,
        language=out.language,
        question=question,
        digits=out.digits.replace(" ", "") if out.digits else None,
        outcome=outcome if out.type == CallActionType.HANGUP else None,
        collected=collected,
        quote=quote,
        commits_booking=bool(commits),
        slot_at=out.slot_at,
        leave_after_bridge=out.leave_after_bridge,
        max_hold_s=out.max_hold_s
        or (brief.max_hold_s if out.type == CallActionType.WAIT_ON_HOLD else None),
        care=care_from(out.care, brief),
        user_update=out.user_update,
    )


def _safe_alternative(brief: CallBrief, out: CallActionOut, reason: str) -> CallAction:
    collected = {kv.key: kv.value for kv in out.collected}
    collected["guard"] = f"safety: {reason}"
    lang = text_language(out.language)
    name = brief.on_behalf_of.split()[0] if brief.on_behalf_of else "my user"
    if brief.user_phone:
        text = (
            f"I can't share that detail. I'll connect {name} directly."
            if lang.value == "en"
            else f"Woh detail main share nahi kar sakti. Main {name} ji ko call pe jod deti hoon."
        )
        return CallAction(
            type=CallActionType.BRIDGE_USER,
            text=text,
            language=lang,
            collected=collected,
            leave_after_bridge=True,
            quote=quote_from(out.quote, brief),
            care=care_from(out.care, brief),
        )
    text = (
        f"I can't share that detail. {name} will get back to you. Thank you."
        if lang.value == "en"
        else f"Woh detail main share nahi kar sakti. {name} ji aapse baat kar lenge. Shukriya."
    )
    return CallAction(
        type=CallActionType.HANGUP,
        text=text,
        language=lang,
        outcome=CallOutcome.NEEDS_USER_VERIFICATION,
        collected=collected,
        quote=quote_from(out.quote, brief),
        care=care_from(out.care, brief),
    )
