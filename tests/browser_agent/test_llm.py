# ruff: noqa: E501
"""The model adapter with a FAKE LLM client: strict schema, cost estimate from tokens, answers only for asked keys."""

from __future__ import annotations

import json

import pytest

from friday.brain.schemas import strict_schema
from friday.browser_agent.llm import OpenAIBrowserLLM
from friday.browser_agent.types import Action, AskField
from friday.core.interfaces import LLMResponse


class FakeClient:
    def __init__(self, text: str, tin: int = 1500, tout: int = 80) -> None:
        self.text, self.tin, self.tout, self.calls = text, tin, tout, []

    async def complete(self, **kw):  # noqa: ANN003, ANN201
        self.calls.append(kw)
        return LLMResponse(text=self.text, model="fake", input_tokens=self.tin, output_tokens=self.tout)


def test_action_schema_is_strict_and_closed():
    sch = strict_schema(Action)
    assert sch["additionalProperties"] is False
    assert set(sch["required"]) == set(Action.model_fields)
    assert sch["properties"]["tool"]["enum"] == ["goto", "click", "fill", "select", "upload", "press", "wait", "extract", "screenshot_proof", "ask_user", "request_confirmation", "finish", "give_up"]


async def test_decide_parses_strict_json_and_estimates_cost_from_tokens():
    act = {k: None for k in Action.model_fields}
    act.update(tool="fill", note="name field", target="e3", value_source="fact:full_name")
    c = FakeClient(json.dumps(act))
    llm = OpenAIBrowserLLM(c, in_inr_per_1k=0.05, out_inr_per_1k=0.2)
    a, cost = await llm.decide(system="s", user="u")
    assert a.tool == "fill" and a.value_source == "fact:full_name" and abs(cost - (1.5 * 0.05 + 0.08 * 0.2)) < 1e-9
    assert c.calls[0]["json_schema"]["additionalProperties"] is False and c.calls[0]["purpose"] == "browser_agent"


async def test_invalid_model_output_raises_and_the_loop_counts_it_as_a_refusal():
    llm = OpenAIBrowserLLM(FakeClient('{"tool":"pay_now"}'))
    with pytest.raises(ValueError):  # pydantic ValidationError: there is no pay tool to choose
        await llm.decide(system="s", user="u")


async def test_parse_answers_returns_only_asked_keys():
    c = FakeClient(json.dumps({"keys": ["email", "evil"], "values": ["a@b.c", "x"]}))
    llm = OpenAIBrowserLLM(c)
    got, _ = await llm.parse_answers(fields=[AskField(key="email", label="Email")], reply="my mail is a@b.c")
    assert got == {"email": "a@b.c"}
