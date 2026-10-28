# ruff: noqa: E501
"""ANSWER agent. One job: answer from knowledge or memory, no tool.

The port is the existing brain turn (persona, memory, guardrails): when no direct port is given the
agent reports ``handled=False`` and the request simply continues to the brain. A direct port
(an LLM callable) can be plugged in later; the output is still checked by the wording guard.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from friday.planner import wording
from friday.planner.types import Approach


class AnswerInput(BaseModel):
    text: str
    lang: str = "hinglish"


class AnswerOutput(BaseModel):
    handled: bool
    text: str | None = None


AnswerPort = Callable[[AnswerInput], Awaitable[str | None]]


class AnswerAgent:
    def __init__(self, port: AnswerPort | None = None) -> None:
        self.port = port

    async def run(self, inp: AnswerInput) -> AnswerOutput:
        if self.port is None:
            return AnswerOutput(handled=False)  # the brain answers
        text = await self.port(inp)
        if not text:
            return AnswerOutput(handled=False)
        return AnswerOutput(handled=True, text=wording.guard_text(text, call_in_plan=False, fallback=""))


APPROACH = Approach.ANSWER
