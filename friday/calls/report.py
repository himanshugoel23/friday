"""Outcome -> plain-language WhatsApp report with next-action buttons (A4.1, A4.2, A4.4).

* Commitments that need the user's OK are listed apart and get Yes / No buttons.
* A wrong-person call produces an apology line for the user, is marked urgent (sent at once) and
  the orchestrator adds the number to the do-not-call registry.
* Every text goes through ``privacy.scrub``: no private fact and no plain phone number can reach
  the user's chat through a report, even if the engine's summary contained one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from friday.calls import copy
from friday.calls.models import CallBrief, CallOutcome, CallRequest, NextAction, OutcomeStatus
from friday.calls.privacy import scrub
from friday.core.clock import format_ist
from friday.core.models import ReplyButton

ACT_PREFIX = "callact"
_BTN_FOR: dict[NextAction, str] = {
    NextAction.DONE: "btn_done",
    NextAction.CALL_AGAIN: "btn_call_again",
    NextAction.CALL_LATER: "btn_call_later",
    NextAction.SEND_MESSAGE: "btn_message",
    NextAction.ADD_REMINDER: "btn_reminder",
    NextAction.APPROVE_COMMITMENT: "btn_ok_commit",
    NextAction.DECLINE_COMMITMENT: "btn_no_commit",
    NextAction.STOP_CALLING: "btn_stop",
    NextAction.DELETE_RECORDING: "btn_delete_rec",
}


@dataclass
class Report:
    text: str
    buttons: list[ReplyButton] = field(default_factory=list)
    urgent: bool = False
    actions: list[NextAction] = field(default_factory=list)


def parse_action(button_id: str) -> tuple[str, NextAction] | None:
    parts = button_id.split(":")
    if len(parts) != 3 or parts[0] != ACT_PREFIX:
        return None
    try:
        return parts[1], NextAction(parts[2])
    except ValueError:
        return None


def _buttons(request_id: str, actions: list[NextAction], lang: str) -> list[ReplyButton]:
    out: list[ReplyButton] = []
    for a in actions[:3]:
        out.append(
            ReplyButton(
                id=f"{ACT_PREFIX}:{request_id}:{a.value}", title=copy.line(_BTN_FOR[a], lang)
            )
        )
    return out


def _lang(brief: CallBrief | None, request: CallRequest) -> str:
    lang = brief.language if brief else request.language
    return lang if lang in ("hinglish", "en") else copy.DEFAULT_LANGUAGE


def _who(request: CallRequest) -> str:
    return request.callee_name or request.callee_ref or "-"


def _dedupe(actions: list[NextAction]) -> list[NextAction]:
    seen: list[NextAction] = []
    for a in actions:
        if a not in seen:
            seen.append(a)
    return seen


class ReportBuilder:
    def single(
        self,
        request: CallRequest,
        brief: CallBrief | None,
        outcome: CallOutcome,
        *,
        attempts_used: int | None = None,
    ) -> Report:
        """The FINAL report for one request (retries are announced by ``retry_notice``)."""
        lang = _lang(brief, request)
        who = _who(request)
        n = attempts_used if attempts_used is not None else outcome.attempt
        st = outcome.status
        summary = outcome.summary.strip()
        urgent = False
        parts: list[str] = []
        actions: list[NextAction] = []
        if st == OutcomeStatus.COMPLETED:
            parts.append(copy.line("report_completed", lang, name=who, summary=summary))
            actions = [NextAction.DONE, NextAction.ADD_REMINDER, NextAction.CALL_AGAIN]
        elif st == OutcomeStatus.PARTIAL:
            parts.append(copy.line("report_partial", lang, name=who, summary=summary))
            actions = [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE, NextAction.DONE]
        elif st == OutcomeStatus.DECLINED:
            parts.append(copy.line("report_declined", lang, name=who, summary=summary))
            actions = [NextAction.SEND_MESSAGE, NextAction.CALL_AGAIN, NextAction.DONE]
        elif st == OutcomeStatus.NO_ANSWER:
            parts.append(copy.line("report_no_answer_final", lang, name=who, n=n))
            actions = [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE, NextAction.DONE]
        elif st == OutcomeStatus.BUSY:
            parts.append(copy.line("report_busy_final", lang, name=who, n=n))
            actions = [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE, NextAction.DONE]
        elif st == OutcomeStatus.VOICEMAIL:
            parts.append(copy.line("report_voicemail_final", lang, name=who))
            actions = [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE, NextAction.DONE]
        elif st == OutcomeStatus.CALLBACK_LATER:
            parts.append(copy.line("report_callback_later", lang, name=who, summary=summary))
            actions = [NextAction.DONE, NextAction.STOP_CALLING]
        elif st == OutcomeStatus.WRONG_PERSON:
            parts.append(copy.line("report_wrong_person", lang, name=who))
            actions, urgent = [NextAction.DONE], True
        elif st == OutcomeStatus.OPTED_OUT:
            parts.append(copy.line("report_opted_out", lang, name=who))
            actions = [NextAction.DONE]
        elif st == OutcomeStatus.SAFETY_STOP:
            parts.append(copy.line("report_safety_stop", lang, summary=summary))
            actions = [NextAction.SEND_MESSAGE, NextAction.DONE]
        else:  # FAILED
            parts.append(copy.line("report_failed_final", lang, name=who))
            actions = [NextAction.CALL_AGAIN, NextAction.DONE]

        if outcome.do_not_call_again and st not in (
            OutcomeStatus.OPTED_OUT,
            OutcomeStatus.WRONG_PERSON,
        ):
            parts.append(copy.line("report_opted_out", lang, name=who))
        if outcome.answers and st in (OutcomeStatus.COMPLETED, OutcomeStatus.PARTIAL):
            items = "; ".join(f"{q}: {a}" for q, a in outcome.answers.items())
            parts.append(copy.line("report_answers", lang, items=items))
        agreed = [c.text for c in outcome.commitments if not c.needs_user_approval or c.approved]
        pending = [c.text for c in outcome.commitments if c.needs_user_approval and not c.approved]
        pending += [t for t in outcome.needs_user_approval if t not in pending]
        if agreed:
            parts.append(copy.line("report_commitments_done", lang, items="; ".join(agreed)))
        if pending:
            parts.append(copy.line("report_commitments", lang, items="; ".join(pending)))
            actions = [NextAction.APPROVE_COMMITMENT, NextAction.DECLINE_COMMITMENT, *actions]
        if st not in (OutcomeStatus.WRONG_PERSON, OutcomeStatus.OPTED_OUT):
            actions = _dedupe([*outcome.next_actions, *actions]) if not pending else actions
        actions = _dedupe(actions)[:3]
        text = scrub("\n".join(p for p in parts if p.strip()), request=request, brief=brief)
        return Report(text, _buttons(request.id, actions, lang), urgent, actions)

    def retry_notice(
        self, request: CallRequest, brief: CallBrief | None, status: OutcomeStatus, when: datetime
    ) -> str:
        lang = _lang(brief, request)
        key = "sched_callback" if status == OutcomeStatus.CALLBACK_LATER else "sched_retry"
        return copy.line(key, lang, name=_who(request), when=format_ist(when, "%a %I:%M %p"))

    def group(
        self,
        parent: CallRequest,
        brief: CallBrief | None,
        rows: list[tuple[CallRequest, CallOutcome | None]],
    ) -> Report:
        lang = _lang(brief, parent)
        answered = [r for r in rows if r[1] is not None and r[1].status == OutcomeStatus.COMPLETED]
        lines = [copy.line("report_group_header", lang, done=len(rows), answered=len(answered))]
        pending_all: list[str] = []
        for child, outcome in rows:
            if outcome is None and child.status.is_terminal:
                word = copy.line("word_skipped", lang)  # denied or cancelled: never dialled
            elif outcome is None:
                word = copy.line("word_pending", lang)
            elif outcome.summary.strip() and outcome.status in (
                OutcomeStatus.COMPLETED, OutcomeStatus.PARTIAL, OutcomeStatus.DECLINED,
            ):  # fmt: skip
                word = outcome.summary.strip()
            else:
                word = copy.line(f"word_{outcome.status.value}", lang)
            lines.append(copy.line("report_group_line", lang, name=_who(child), summary=word))
            if outcome is not None:
                pending_all += [
                    f"{_who(child)}: {c.text}"
                    for c in outcome.commitments
                    if c.needs_user_approval and not c.approved
                ]
        if pending_all:
            lines.append(copy.line("report_commitments", lang, items="; ".join(pending_all)))
        actions = (
            [NextAction.APPROVE_COMMITMENT, NextAction.DECLINE_COMMITMENT]
            if pending_all
            else [NextAction.DONE, NextAction.CALL_AGAIN]
        )
        text = "\n".join(lines)
        for child, _ in rows:  # one scrub pass per member number, then the parent
            text = scrub(text, request=child, brief=None)
        text = scrub(text, request=parent, brief=brief)
        return Report(text, _buttons(parent.id, actions, lang), False, actions)
