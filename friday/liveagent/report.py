# ruff: noqa: E501
"""After the call: the masked transcript and the plain-language CallOutcome summary."""

from __future__ import annotations

import re

from friday.liveagent.contracts import (
    ApprovalRequest,
    CallBrief,
    Callee,
    CallOutcome,
    Commitment,
    OutcomeStatus,
)

_DIGIT_RUN = re.compile(r"\d(?:[ \-.]?\d){4,}")  # 5+ digits, possibly spaced or hyphenated
_DIGIT_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|shunya|ek|do|teen|char|chaar|"
    r"paanch|panch|chhe|saat|aath|nau)"
)
_SPOKEN_RUN = re.compile(rf"(?<![\w])(?:{_DIGIT_WORD}[\s,-]+){{4,}}{_DIGIT_WORD}(?![\w])", re.I)


def mask_numbers(text: str) -> str:
    """Hide phone/account/card-like digit runs (5+ digits, also when spoken as words or spaced),
    keeping the last two digits so a reader can still tell which one it was."""

    def repl(m: re.Match[str]) -> str:
        d = re.sub(r"\D", "", m.group())
        return "X" * (len(d) - 2) + d[-2:]

    return _SPOKEN_RUN.sub("[number]", _DIGIT_RUN.sub(repl, text))


_STATUS_TEXT: dict[OutcomeStatus, str] = {
    OutcomeStatus.COMPLETED: "The call went well and everything on the list was covered.",
    OutcomeStatus.PARTIAL: "The call was only partly completed.",
    OutcomeStatus.NEEDS_USER_APPROVAL: "Something came up that needs your decision before I can go further.",
    OutcomeStatus.CALL_BACK_LATER: "They were busy and asked for a call back.",
    OutcomeStatus.DECLINED: "They did not want to go ahead.",
    OutcomeStatus.VOICEMAIL_LEFT: "It went to voicemail and I left the short fixed message.",
    OutcomeStatus.VOICEMAIL_NO_MESSAGE: "It went to voicemail; I did not leave a message.",
    OutcomeStatus.UNREACHABLE: "The number was switched off or not reachable.",
    OutcomeStatus.WRONG_NUMBER: "Wrong person reached; I apologised and ended the call.",
    OutcomeStatus.DO_NOT_CALL: "They asked not to be called again; I stopped at once.",
    OutcomeStatus.DISTRESS: "The person sounded distressed; I ended the call and this needs your attention now.",
    OutcomeStatus.HOSTILE: "The person was upset or abusive; I ended the call politely.",
    OutcomeStatus.UNRESOLVED: "We were not getting through, so I ended the call politely.",
    OutcomeStatus.CUT_OFF: "The call reached its time limit and I ended it politely.",
    OutcomeStatus.DROPPED: "The line dropped during the call.",
}


def build_outcome(
    brief: CallBrief,
    callee: Callee,
    status: OutcomeStatus,
    *,
    answers: dict[str, str],
    commitments: list[Commitment],
    approvals: list[ApprovalRequest],
    next_actions: list[str],
    unanswered: list[str],
    callback_time: str | None = None,
    ivr_path: list[str] | None = None,
) -> CallOutcome:
    who = callee.name or brief.callee_name or callee.kind.value.replace("_", " ")
    parts = [f"Call to {who} for {brief.user_name}: {_STATUS_TEXT[status]}"]
    if answers:
        parts.append(
            "What they said: "
            + "; ".join(f"{q or 'note'} -> {mask_numbers(a)}" for q, a in answers.items())
            + "."
        )
    if unanswered:
        parts.append("Not answered: " + "; ".join(unanswered) + ".")
    if commitments:
        parts.append(
            "Agreed inside your limits: "
            + "; ".join(f"{c.kind}: {mask_numbers(c.text)}" for c in commitments)
            + "."
        )
    if approvals:
        parts.append(
            "Needs your yes/no: "
            + "; ".join(f"{a.kind}: {mask_numbers(a.text)} ({a.reason})" for a in approvals)
            + ". I told them I would confirm and call back."
        )
    if callback_time:
        parts.append(f"They asked me to call back around: {mask_numbers(callback_time)}.")
    if ivr_path:
        parts.append("Menu keys pressed: " + " ".join(ivr_path) + ".")
    actions = list(dict.fromkeys(next_actions))
    if callback_time:
        actions.append(f"Call back around {mask_numbers(callback_time)}.")
    if approvals:
        actions.append("Ask the user to approve or decline the open items, then call back.")
    if (
        status
        in (
            OutcomeStatus.DROPPED,
            OutcomeStatus.UNRESOLVED,
            OutcomeStatus.VOICEMAIL_NO_MESSAGE,
            OutcomeStatus.UNREACHABLE,
            OutcomeStatus.CUT_OFF,
        )
        and not approvals
    ):
        actions.append("Retry later under the retry rules.")
    return CallOutcome(
        status=status,
        summary=" ".join(parts),
        commitments=commitments,
        needs_user_approval=approvals,
        next_actions=list(dict.fromkeys(actions)),
    )
