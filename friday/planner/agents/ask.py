# ruff: noqa: E501
"""ASK agent. One job: produce ONE clarifying question for the user, call-free unless a call is planned."""

from __future__ import annotations

from pydantic import BaseModel

from friday.planner import wording
from friday.planner.types import Approach, ReasonCode


class AskInput(BaseModel):
    reason_code: ReasonCode
    proposed: str | None = None  # a model-written question; used only if it passes the wording guard
    lang: str = "hinglish"
    call_in_plan: bool = False


class AskOutput(BaseModel):
    question: str


class AskAgent:
    def run(self, inp: AskInput) -> AskOutput:
        if inp.reason_code == ReasonCode.GUARD_NO_CONNECTOR:
            fallback = wording.line("ask_no_connector", inp.lang)
        elif inp.reason_code == ReasonCode.GUARD_NO_LOCAL_SIGNAL:
            fallback = wording.line("ask_unsure_call", inp.lang)
        else:
            fallback = wording.line("ask_generic", inp.lang)
        # an ordinary clarifying question is not in a call plan, whatever the model wrote
        return AskOutput(
            question=wording.guard_text(inp.proposed, call_in_plan=inp.call_in_plan, fallback=fallback)
        )


APPROACH = Approach.ASK
