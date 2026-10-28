# ruff: noqa: E501
"""Approach planner: decision table, policy guard, wording rule. Offline, no model, no network."""

from __future__ import annotations

import json

import pytest

from friday.core.interfaces import LLMResponse
from friday.planner import signals as sg
from friday.planner import wording
from friday.planner.agents.ask import AskAgent, AskInput
from friday.planner.agents.call import CallAgent, CallPlanInput
from friday.planner.planner import ApproachPlanner, LLMDecider, apply_policy
from friday.planner.types import Approach, ApproachDecision, PlannerContext, Reason, ReasonCode

A = Approach


def ctx(text: str, connectors: frozenset[str] = frozenset()) -> PlannerContext:
    return PlannerContext(text=text, connectors=connectors)


async def plan(text: str, connectors: frozenset[str] = frozenset(), llm: LLMDecider | None = None) -> ApproachDecision:
    return await ApproachPlanner(llm_decider=llm).plan(ctx(text, connectors))


TABLE = [
    ("check the price of 5 kg Aashirwad atta on Zepto", frozenset(), A.WEB_LOOKUP),
    ("zepto pe aashirvaad atta 5kg kitne ka hai", frozenset(), A.WEB_LOOKUP),
    ("is the iPhone 16 in stock on Amazon", frozenset(), A.WEB_LOOKUP),
    ("what are the opening hours of Sarojini market", frozenset(), A.WEB_LOOKUP),
    ("find me a plumber tonight", frozenset(), A.CALL_VENDORS),
    ("mujhe kal ek electrician chahiye", frozenset(), A.CALL_VENDORS),
    ("book an appointment for a haircut", frozenset(), A.CALL_VENDORS),
    ("call them and ask if the shop is open", frozenset(), A.CALL_VENDORS),
    ("what is the capital of France", frozenset(), A.ANSWER),
    ("explain how a heat pump works", frozenset(), A.ANSWER),
    ("order pizza", frozenset(), A.ASK),  # no connector: ASK, never a silent call
    ("order pizza", frozenset({"browser"}), A.APP_OR_CONNECTOR),
    ("order biryani from zomato", frozenset({"browser"}), A.APP_OR_CONNECTOR),
    ("hmm", frozenset(), A.ANSWER),  # unknown: the answer path (the brain), never a call
]


@pytest.mark.parametrize(("text", "connectors", "want"), TABLE)
async def test_decision_table(text, connectors, want):
    d = await plan(text, connectors)
    assert d.approach == want, (text, d)
    assert d.reason.code in set(ReasonCode)


async def test_price_query_carries_query_retailer_and_reason():
    d = await plan("check the price of 5 kg Aashirwad atta on Zepto")
    assert d.retailer == "zepto" and "aashirwad" in d.query.lower()
    assert d.reason.code == ReasonCode.LIVE_PUBLIC_DATA and not d.call_in_plan


def test_pincode_signal():
    assert sg.pincode_in("zepto 560001 atta") == "560001"
    assert sg.pincode_in("order 12345") is None


# ------------------------------------------------------------------ policy guard
def call_decision(source="llm", confidence=0.9) -> ApproachDecision:
    return ApproachDecision(approach=A.CALL_VENDORS, reason=Reason(code=ReasonCode.LOCAL_HUMAN_NEEDED), confidence=confidence, source=source)


def test_guard_never_calls_when_a_lookup_can_answer():
    d = apply_policy(call_decision(), ctx("price of amul butter 500g on blinkit"))
    assert d.approach == A.WEB_LOOKUP and d.overridden_from == A.CALL_VENDORS
    assert d.reason.code == ReasonCode.GUARD_LOOKUP_FIRST and d.query


def test_guard_allows_a_call_when_the_user_asked_for_one():
    d = apply_policy(call_decision(), ctx("call karke pooch lo ki dukaan khuli hai ya nahi, price bhi"))
    assert d.approach == A.CALL_VENDORS


def test_guard_app_without_connector_is_lookup_or_ask():
    app = ApproachDecision(approach=A.APP_OR_CONNECTOR, reason=Reason(code=ReasonCode.ORDER_VIA_APP), confidence=0.9, source="llm")
    assert apply_policy(app, ctx("order pizza")).approach == A.ASK
    assert apply_policy(app, ctx("price of pizza on zomato")).approach == A.WEB_LOOKUP
    assert apply_policy(app, ctx("order pizza", frozenset({"browser"}))).approach == A.APP_OR_CONNECTOR


def test_guard_low_confidence_call_or_app_becomes_ask():
    d = apply_policy(call_decision(confidence=0.3), ctx("find me a plumber"))
    assert d.approach == A.ASK and d.reason.code == ReasonCode.GUARD_UNSURE


def test_guard_llm_call_without_any_local_signal_becomes_ask():
    d = apply_policy(call_decision(confidence=0.6), ctx("sort out my thing please"))
    assert d.approach == A.ASK and d.reason.code == ReasonCode.GUARD_NO_LOCAL_SIGNAL


def test_guard_keeps_a_confident_local_call():
    assert apply_policy(call_decision(confidence=0.9), ctx("need an electrician tonight")).approach == A.CALL_VENDORS


class FakeLLM:
    def __init__(self, payload: dict | str | Exception) -> None:
        self.payload, self.calls = payload, 0

    async def complete(self, **kw):  # noqa: ANN003, ANN201
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(text=text, model="fake")


def llm_out(approach: str, **kw) -> dict:
    return {"approach": approach, "reason_code": "unsure", "reason": "x", "confidence": 0.9, "query": None, "retailer": None, "question": None, **kw}


async def test_llm_pick_of_call_for_a_price_question_is_overridden_by_the_guard():
    fake = FakeLLM(llm_out("call_vendors", reason_code="local_human_needed"))
    text = "sasta sa atta batao zepto par"
    d = apply_policy(await LLMDecider(fake).decide(ctx(text)), ctx(text))
    assert d.approach == A.WEB_LOOKUP and d.source == "guard"


async def test_confident_heuristic_does_not_spend_an_llm_call():
    fake = FakeLLM(llm_out("answer"))
    d = await plan("how much is a litre of amul milk on blinkit", llm=LLMDecider(fake))
    assert d.approach == A.WEB_LOOKUP and fake.calls == 0


@pytest.mark.parametrize("payload", ["not json", {"approach": "teleport"}, RuntimeError("down")])
async def test_llm_failure_falls_back_to_the_deterministic_decider(payload):
    d = await plan("mujhe kuch chahiye", llm=LLMDecider(FakeLLM(payload)))
    assert d.approach == A.ANSWER and d.source == "heuristic"


def test_llm_question_cannot_mention_calls_without_a_call_plan():
    out = AskAgent().run(AskInput(reason_code=ReasonCode.UNSURE, proposed="Shall I call the shop for you?", call_in_plan=False))
    assert not sg.mentions_call(out.question)
    ok = AskAgent().run(AskInput(reason_code=ReasonCode.UNSURE, proposed="Which area are you in?", call_in_plan=False))
    assert ok.question == "Which area are you in?"


def test_call_agent_only_plans_calls():
    assert CallAgent().run(CallPlanInput(decision=call_decision())).call_in_plan
    web = call_decision().model_copy(update={"approach": A.WEB_LOOKUP})
    with pytest.raises(ValueError):
        CallAgent().run(CallPlanInput(decision=web))


# ------------------------------------------------------------------ wording
CALL_LINES = {"ack_call", "needs_info_call"}


@pytest.mark.parametrize("lang", ["en", "hinglish"])
def test_no_line_mentions_calling_unless_it_is_a_call_line(lang):
    kw = {"where": "Zepto", "store": "Zepto", "time": "10:00", "missing": "area"}
    for key in wording.LINES:
        text = wording.line(key, lang, **kw)
        if key not in CALL_LINES:
            assert not sg.mentions_call(text), (key, text)
    assert sg.mentions_call(wording.line("needs_info_call", lang, missing="area"))


@pytest.mark.parametrize("approach", [A.ANSWER, A.WEB_LOOKUP, A.APP_OR_CONNECTOR, A.ASK, A.DECLINE])
def test_ack_names_the_approach_and_never_says_call(approach):
    for lang in ("en", "hinglish"):
        assert not sg.mentions_call(wording.ack_line(approach, "zepto", lang))
    assert "Zepto" in wording.ack_line(A.WEB_LOOKUP, "zepto", "en")


def test_before_i_call_only_with_a_call_in_the_plan():
    assert wording.needs_info_line(["service type"], call_in_plan=True) == "Before I call, I need: service type"
    no_call = wording.needs_info_line(["service type"], call_in_plan=False)
    assert "call" not in no_call.lower() and "service type" in no_call
