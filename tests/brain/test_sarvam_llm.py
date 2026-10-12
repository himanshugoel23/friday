"""Sarvam call-turn model + the router that sends only call turns to it (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from friday.brain.sarvam_llm import RoutedLLM, SarvamLLM, route_call_turns
from friday.core.config import Settings
from friday.core.interfaces import LLMMessage, LLMResponse, ProviderError

SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}, "price_inr": {"type": ["integer", "null"]}},
    "required": ["intent", "price_inr"],
    "additionalProperties": False,
}


def reply(text, status=200):
    body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    return httpx.Response(status, json=body)


async def test_sends_the_sarvam_model_schema_and_key_and_returns_the_json():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("api-subscription-key")
        seen["body"] = json.loads(req.content)
        return reply('{"intent":"YES"}')

    llm = SarvamLLM("K", transport=httpx.MockTransport(handler))
    msgs = [LLMMessage(role="user", content="haan ji")]
    r = await llm.complete(system="rules", messages=msgs, purpose="call_turn",
                           model="gpt-5.4-mini", max_tokens=60, json_schema=SCHEMA)
    assert json.loads(r.text) == {"intent": "YES"} and r.model == "sarvam-105b-conversations"
    b = seen["body"]
    assert seen["url"].endswith("/v1/chat/completions") and seen["key"] == "K"
    assert b["model"] == "sarvam-105b-conversations"  # never the OpenAI model name
    assert b["max_tokens"] >= 160 and b["temperature"] == 0
    assert b["response_format"]["json_schema"]["schema"]["required"] == ["intent"]
    assert "OMIT" in b["messages"][0]["content"]


async def test_one_repair_retry_when_the_json_is_wrong():
    answers = iter(['not json at all', '{"intent":"NO"}'])
    llm = SarvamLLM("K", transport=httpx.MockTransport(lambda r: reply(next(answers))))
    r = await llm.complete(system="s", messages=[LLMMessage(role="user", content="x")],
                           purpose="call_turn", json_schema=SCHEMA)
    assert json.loads(r.text)["intent"] == "NO" and llm.repairs == 1


async def test_http_error_becomes_a_provider_error():
    llm = SarvamLLM("K", transport=httpx.MockTransport(lambda r: httpx.Response(503, text="x")))
    with pytest.raises(ProviderError):
        await llm.complete(system="s", messages=[LLMMessage(role="user", content="x")],
                           purpose="call_turn", json_schema=SCHEMA)


class _Fake:
    def __init__(self, text="primary", fail=False):
        self.text, self.fail, self.calls = text, fail, []

    async def complete(self, *, purpose="general", **kw):
        self.calls.append(purpose)
        if self.fail:
            raise ProviderError("x", "down")
        return LLMResponse(text=self.text, model="m")


async def test_router_sends_only_call_turns_to_the_fast_model_and_falls_back():
    primary, fast = _Fake("primary"), _Fake("fast")
    r = RoutedLLM(primary, fast, frozenset({"call_turn"}))
    assert (await r.complete(purpose="call_turn", system="s", messages=[])).text == "fast"
    assert (await r.complete(purpose="interpret", system="s", messages=[])).text == "primary"
    assert fast.calls == ["call_turn"] and primary.calls == ["interpret"]
    r2 = RoutedLLM(_Fake("primary"), _Fake(fail=True), frozenset({"call_turn"}))
    assert (await r2.complete(purpose="call_turn", system="s", messages=[])).text == "primary"
    assert r2.fallbacks == 1


def test_switch_is_off_by_default_and_needs_the_key():
    base = _Fake()
    assert route_call_turns(base, Settings()) is base
    assert route_call_turns(base, Settings(llm_call_turn_provider="sarvam")) is base  # no key
    s = Settings(llm_call_turn_provider="sarvam", sarvam_api_key="k")
    routed = route_call_turns(base, s)
    assert isinstance(routed, RoutedLLM) and routed.primary is base
    assert routed.fast.model == "sarvam-105b-conversations"
