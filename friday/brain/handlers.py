"""``purpose`` -> deterministic handler(payload) -> wire model.

These are the fake LLM's "brain" and the real path's fallback when the LLM fails
(timeout, refusal, invalid JSON). Payloads are the exact JSON the brain puts in
``<input>`` for the real model, so both paths see identical requests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from friday.core.models import (
    CallBrief,
    CallResult,
    ConversationContext,
    InboundMessage,
    Language,
    NudgeCandidate,
    Quote,
    Task,
    Transcript,
    UserAnswer,
)

from .heuristics import business, door, media, nudges, policy, translate
from .heuristics.interpret import interpret
from .heuristics.references import resolve
from .inbound import InboundCallBrief
from .reports import compare_text, summary_text
from .schemas import TranslateOut


def load_brief(data: dict[str, Any]) -> CallBrief:
    if data.get("inbound") is not None or data.get("direction"):
        return InboundCallBrief.model_validate(data)
    return CallBrief.model_validate(data)


def h_interpret(p: dict[str, Any]) -> BaseModel:
    return interpret(
        ConversationContext.model_validate(p["ctx"]), InboundMessage.model_validate(p["message"])
    )


def h_resolve(p: dict[str, Any]) -> BaseModel:
    return resolve(ConversationContext.model_validate(p["ctx"]), p.get("text") or "")


def h_call_turn(p: dict[str, Any]) -> BaseModel:
    if p.get("door") is not None:  # the inbound front door's conversational turn
        return door.next_turn(p)
    if p.get("playbook") is not None:  # a scripted call: classify the salon's reply (offline)
        from friday.playbooks.understand import LLMUnderstanding, heuristic_from_payload

        return LLMUnderstanding(
            **heuristic_from_payload(p).model_dump(exclude={"confident"})
        )
    speak = p.get("speakable")
    if p.get("transcript_full"):
        transcript = Transcript.model_validate(p["transcript_full"])
    else:  # compact form: list of the last N turns
        transcript = Transcript.model_validate({"turns": p.get("transcript") or []})
    return policy.next_action(
        load_brief(p["brief"]),
        transcript,
        [UserAnswer.model_validate(a) for a in p.get("answers", [])],
        frozenset(Language(x) for x in speak) if speak else None,
    )


def h_summarize(p: dict[str, Any]) -> BaseModel:
    return summary_text(
        ConversationContext.model_validate(p["ctx"]),
        Task.model_validate(p["task"]),
        CallResult.model_validate(p["result"]),
    )


def h_compare(p: dict[str, Any]) -> BaseModel:
    return compare_text(
        ConversationContext.model_validate(p["ctx"]),
        Task.model_validate(p["parent"]),
        [Quote.model_validate(q) for q in p.get("ranked", [])],
    )


def h_nudge(p: dict[str, Any]) -> BaseModel:
    return nudges.judge(
        ConversationContext.model_validate(p["ctx"]), NudgeCandidate.model_validate(p["candidate"])
    )


def h_extract(p: dict[str, Any]) -> BaseModel:
    return media.extract(p)


def h_translate(p: dict[str, Any]) -> BaseModel:
    src = p.get("source")
    return TranslateOut(
        text=translate.translate(
            p.get("text") or "", Language(p["target"]), Language(src) if src else None
        )
    )


def h_sim_business(p: dict[str, Any]) -> BaseModel:
    return business.reply(p.get("business") or {}, p.get("transcript") or [])


def h_shortlist_reasons(p: dict[str, Any]) -> BaseModel:
    from .schemas import ReasonOut, ReasonsOut

    return ReasonsOut(
        reasons=[
            ReasonOut(index=i, reason=item.get("default_reason", ""))
            for i, item in enumerate(p.get("items", []))
        ]
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], BaseModel]] = {
    "interpret": h_interpret,
    "resolve_references": h_resolve,
    "call_turn": h_call_turn,
    "summarize": h_summarize,
    "compare": h_compare,
    "judge_nudge": h_nudge,
    "extract": h_extract,
    "translate": h_translate,
    "sim_business": h_sim_business,
    "shortlist_reasons": h_shortlist_reasons,
}
