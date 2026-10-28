# ruff: noqa: E501
"""Typed contracts of the approach planner (docs/APPROACH_PLANNER.md)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Approach(StrEnum):
    ANSWER = "answer"  # from knowledge / memory, no tool
    WEB_LOOKUP = "web_lookup"  # prices, availability, timings, reviews, facts from public web pages
    APP_OR_CONNECTOR = "app_or_connector"  # order / book through an enabled connector or browser flow
    CALL_VENDORS = "call_vendors"  # the existing flow: a human at a local business must be asked
    ASK = "ask"  # ONE clarifying question, only when truly needed
    DECLINE = "decline"


class ReasonCode(StrEnum):
    KNOWLEDGE = "knowledge"  # general knowledge, no tool needed
    LIVE_PUBLIC_DATA = "live_public_data"  # price / stock / timing visible on public pages
    ORDER_VIA_APP = "order_via_app"  # an order that an enabled connector can place
    LOCAL_HUMAN_NEEDED = "local_human_needed"  # only a person at a local business can answer
    MISSING_INFO = "missing_info"
    NOT_ALLOWED = "not_allowed"
    UNSURE = "unsure"
    # set only by the deterministic guard when it overrides the first choice
    GUARD_LOOKUP_FIRST = "guard_lookup_first"
    GUARD_NO_CONNECTOR = "guard_no_connector"
    GUARD_UNSURE = "guard_unsure"
    GUARD_NO_LOCAL_SIGNAL = "guard_no_local_signal"


class Reason(BaseModel):
    code: ReasonCode
    text: str = Field(default="", max_length=160)


class ApproachDecision(BaseModel):
    approach: Approach
    reason: Reason
    confidence: float = 0.5
    query: str | None = None  # WEB_LOOKUP: what to search for
    retailer: str | None = None  # WEB_LOOKUP / APP: named store or app, lower-case
    question: str | None = None  # ASK: the one question (call-free unless a call is planned)
    source: Literal["heuristic", "llm", "guard"] = "heuristic"
    overridden_from: Approach | None = None  # set by the guard

    @property
    def call_in_plan(self) -> bool:
        return self.approach == Approach.CALL_VENDORS


class PlannerContext(BaseModel):
    text: str
    lang: str = "hinglish"
    connectors: frozenset[str] = frozenset()  # enabled connector / browser flows, e.g. {"browser"}
    pincode: str | None = None


class PlannerLLMOut(BaseModel):
    """The closed JSON schema the LLM decider must answer with."""

    approach: Approach
    reason_code: Literal[
        "knowledge", "live_public_data", "order_via_app", "local_human_needed",
        "missing_info", "not_allowed", "unsure",
    ]  # fmt: skip
    reason: str
    confidence: float
    query: str | None
    retailer: str | None
    question: str | None
