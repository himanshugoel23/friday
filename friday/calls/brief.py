"""Draft -> CallRequest + CallBrief. Deterministic: the brief holds the user's own words and fixed
guards, never a model's idea of what to say. The user then approves it (approval.py).

Defaults that are NOT facts: a tone per callee kind, and a fixed "never say" guard list. Nothing
else is added. ``private_facts`` is empty unless the user marked something private.
"""

from __future__ import annotations

import re

from friday.calls.models import (
    CallBrief,
    CalleeKind,
    CallRequest,
    Limits,
    PurposeKind,
)
from friday.calls.understand import Draft

TONE = {
    CalleeKind.FAMILY_FRIEND: "warm",
    CalleeKind.PROVIDER: "friendly and clear",
    CalleeKind.CUSTOMER_CARE: "polite and firm",
    CalleeKind.OFFICIAL: "formal and respectful",
    CalleeKind.BUSINESS: "polite",
    CalleeKind.UNKNOWN: "careful and brief",
    CalleeKind.GROUP: "friendly",
}
# Fixed guards (not facts about the user). Shown to the user on the approval message.
DEFAULT_MUST_NOT_SAY = (
    "OTP, PIN, card or bank details",
    "anything that is not in this plan",
)
_PRIVATE = re.compile(
    r"\b(?:mat\s+(?:batana|bolna|kehna)|nahi\s+(?:batana|bolna)|don'?t\s+(?:tell|say|mention)|"
    r"do\s+not\s+(?:tell|say|mention))\s+(?P<what>[^.;\n]+)",
    re.I,
)


def request_from_draft(
    draft: Draft,
    *,
    user_id: str,
    message_id: str | None,
    callee_name: str | None = None,
    callee_number: str | None = None,
    number_confirmed: bool = False,
    kind: CalleeKind | None = None,
    parent_id: str | None = None,
) -> CallRequest:
    return CallRequest(
        user_id=user_id,
        callee_kind=kind or draft.callee_kind or CalleeKind.UNKNOWN,
        purpose=draft.purpose or "",
        purpose_kind=draft.purpose_kind,
        callee_ref=draft.callee_ref,
        callee_name=callee_name or draft.callee_ref,
        callee_number=callee_number,
        number_confirmed=number_confirmed,
        company=draft.company,
        language=draft.language,
        scheduled_for=draft.scheduled_for,
        parent_id=parent_id,
        callback_of=draft.callback_of,
        group_members=list(draft.group_members),
        raw_text=draft.raw_text,
        source_message_id=message_id,
    )


def build_brief(
    request: CallRequest,
    draft: Draft,
    *,
    number_hash: str | None,
    relationship: str | None = None,
    user_display_name: str | None = None,
) -> CallBrief:
    purpose = request.purpose.strip()
    goal = purpose if not draft.details else f"{purpose} ({draft.details})"
    kind = request.purpose_kind
    must_say: list[str] = []
    ask_list: list[str] = []
    if kind in (PurposeKind.INFORM, PurposeKind.REMIND, PurposeKind.INVITE):
        must_say.append(purpose)
    elif kind != PurposeKind.CALLBACK or purpose:
        ask_list.append(purpose)
    must_not_say = list(DEFAULT_MUST_NOT_SAY)
    private: list[str] = []
    for m in _PRIVATE.finditer(request.raw_text or ""):
        what = m.group("what").strip()
        if what:
            must_not_say.append(what)
            private.append(what)
    limits = draft.limits if isinstance(draft.limits, Limits) else Limits()
    return CallBrief(
        request_id=request.id,
        user_id=request.user_id,
        callee_kind=request.callee_kind,
        callee_name=request.callee_name,
        callee_number_hash=number_hash,
        goal=goal or "(no goal)",
        must_say=must_say,
        must_not_say=must_not_say,
        ask_list=ask_list,
        limits=limits,
        tone=TONE.get(request.callee_kind, "polite"),
        relationship=relationship or request.callee_kind.value.replace("_", " "),
        language=request.language,
        user_display_name=user_display_name,
        shareable_facts=[purpose] if purpose else [],
        private_facts=private,
    )
