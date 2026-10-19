"""Approval of the call plan (A2.4): the WhatsApp message, its three buttons, and the hash binding.

The user approves THIS brief: goal, what will be said and asked, what will not be said, limits and
the exact opening line (supplied by W2 through ``OpeningLineProvider`` and stored in the brief).
Approving stamps ``approval_hash = brief.content_hash()``; any later edit changes the hash, so the
approval no longer matches and ``CallGate`` asks again. A button carries the first 8 hex digits of
the hash that was shown, so a tap on an old message cannot approve a newer plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from friday.calls import copy
from friday.calls.interfaces import OpeningLineProvider
from friday.calls.models import CallBrief, CallRequest
from friday.calls.privacy import scrub
from friday.core.clock import Clock, SystemClock, format_ist
from friday.core.models import ReplyButton

PREFIX = "callap"
ACTIONS = ("approve", "edit", "cancel")
# fields a user edit may change; everything else on the brief is not user-editable
EDITABLE = (
    "goal", "must_say", "must_not_say", "ask_list", "limits", "tone", "language",
    "shareable_facts", "private_facts", "opening_line",
)  # fmt: skip


class StaleApproval(Exception):  # noqa: N818 - control flow
    """The button belongs to an older version of the plan."""


@dataclass
class ApprovalPrompt:
    text: str
    buttons: list[ReplyButton]
    shown_hash: str


@dataclass(frozen=True)
class ButtonPress:
    request_id: str
    action: str
    hash8: str


def parse_button(button_id: str) -> ButtonPress | None:
    parts = button_id.split(":")
    if len(parts) != 4 or parts[0] != PREFIX or parts[2] not in ACTIONS:
        return None
    return ButtonPress(parts[1], parts[2], parts[3])


def _items(values: list[str]) -> str:
    return "; ".join(v for v in values if v)


def _limits(brief: CallBrief, lang: str) -> str:
    out: list[str] = []
    lim = brief.limits
    if lim.max_price_inr:
        out.append(f"max Rs {lim.max_price_inr}")
    if lim.deadline:
        out.append(("by " if lang == "en" else "tak: ") + format_ist(lim.deadline, "%a %d %b"))
    for w in lim.time_windows:
        out.append(f"{w.start}-{w.end}")
    return ", ".join(out)


class ApprovalService:
    def __init__(self, opening: OpeningLineProvider, clock: Clock | None = None) -> None:
        self.opening = opening
        self.clock: Clock = clock or SystemClock()

    async def prepare(
        self, request: CallRequest, brief: CallBrief, *, stale: bool = False
    ) -> tuple[CallBrief, ApprovalPrompt]:
        """Fetch the opening line, drop any earlier approval, and build the message."""
        line = await self.opening.opening_line(brief, request.callee_name)
        fresh = brief.model_copy(
            update={"opening_line": line, "approved": False, "approval_hash": None,
                    "approved_at": None}
        )  # fmt: skip
        return fresh, self.prompt(request, fresh, stale=stale)

    def prompt(
        self, request: CallRequest, brief: CallBrief, *, stale: bool = False
    ) -> ApprovalPrompt:
        lang = brief.language if brief.language in ("hinglish", "en") else copy.DEFAULT_LANGUAGE
        h = brief.content_hash()
        who = request.callee_name or request.callee_ref or "-"
        rows: list[str] = []
        if stale:
            rows.append(copy.line("approval_stale", lang))
        rows.append(copy.line("approval_header", lang))
        rows.append(copy.line("approval_to", lang, name=who))
        rows.append(copy.line("approval_goal", lang, goal=brief.goal))
        if brief.must_say:
            rows.append(copy.line("approval_say", lang, items=_items(brief.must_say)))
        if brief.ask_list:
            rows.append(copy.line("approval_ask", lang, items=_items(brief.ask_list)))
        if brief.must_not_say:
            rows.append(copy.line("approval_not_say", lang, items=_items(brief.must_not_say)))
        if lim := _limits(brief, lang):
            rows.append(copy.line("approval_limits", lang, items=lim))
        if request.scheduled_for:
            rows.append(copy.line("approval_when", lang, when=format_ist(request.scheduled_for)))
        if brief.opening_line:
            rows.append(copy.line("approval_opening", lang, line=brief.opening_line))
        rows.append(copy.line("approval_footer", lang))
        text = scrub("\n".join(rows), request=request, brief=brief)
        buttons = [
            ReplyButton(id=f"{PREFIX}:{request.id}:{a}:{h[:8]}", title=copy.line(f"btn_{a}", lang))
            for a in ACTIONS
        ]
        return ApprovalPrompt(text=text, buttons=buttons, shown_hash=h)

    def approve(self, brief: CallBrief, hash8: str, now: datetime | None = None) -> CallBrief:
        """Record the user's approval of exactly the plan whose hash starts with ``hash8``."""
        current = brief.content_hash()
        if not hash8 or not current.startswith(hash8):
            raise StaleApproval("the plan changed after this message was sent")
        return brief.model_copy(
            update={"approved": True, "approval_hash": current,
                    "approved_at": now or self.clock.now()}
        )  # fmt: skip

    def edit(self, brief: CallBrief, **changes: Any) -> CallBrief:
        """Apply a user edit. The approval is dropped and the version bumped, always."""
        bad = set(changes) - set(EDITABLE)
        if bad:
            raise ValueError(f"not editable: {sorted(bad)}")
        return brief.model_copy(
            update={**changes, "version": brief.version + 1, "approved": False,
                    "approval_hash": None, "approved_at": None}
        )  # fmt: skip

    def derive_children(
        self, parent: CallBrief, children: list[tuple[CallRequest, CallBrief]]
    ) -> list[CallBrief]:
        """Stamp each child brief with approval, but only if the parent is approved as shown."""
        if not parent.is_approved_as_is():
            raise StaleApproval("group plan is not approved")
        out = []
        for _req, child in children:
            stamped = child.model_copy(
                update={"approved": True, "approval_hash": None, "approved_at": parent.approved_at}
            )
            stamped = stamped.model_copy(update={"approval_hash": stamped.content_hash()})
            out.append(stamped)
        return out
