"""AI-1: LLM clients."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from friday.brain.fake_llm import FakeLLM, build_fake_llm, minimal_instance
from friday.brain.llm import AnthropicLLM, attachment_block, build_anthropic_llm, estimate_cost_inr
from friday.brain.schemas import CallActionOut, InterpretOut, strict_schema
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.interfaces import LLMClient, LLMMessage, ProviderError
from friday.core.models import MediaBlob


def test_both_clients_satisfy_protocol(brain_settings):
    c = Container(brain_settings)
    assert isinstance(build_fake_llm(c), LLMClient)
    assert isinstance(AnthropicLLM(api_key="test", client=SimpleNamespace()), LLMClient)


def test_container_resolves_fake_without_key(brain_settings):
    c = Container(brain_settings)
    assert c.provider_for("llm") == "fake"
    assert isinstance(c.llm, FakeLLM)


async def test_fake_is_deterministic_and_records_calls():
    llm = FakeLLM()
    kw = dict(system="s", messages=[LLMMessage(role="user", content="hello")], purpose="x")
    a = await llm.complete(**kw)
    b = await llm.complete(**kw)
    assert a.text == b.text
    assert len(llm.calls) == 2 and llm.calls[0].purpose == "x"


async def test_fake_unknown_purpose_with_schema_returns_valid_minimal_object():
    llm = FakeLLM()
    schema = strict_schema(CallActionOut)
    r = await llm.complete(system="s", messages=[LLMMessage(role="user", content="hi")],
                           purpose="something_new", json_schema=schema)
    data = json.loads(r.text)
    assert set(data) == set(schema["properties"])
    CallActionOut.model_validate(data)


async def test_fake_script_and_failure_injection():
    llm = FakeLLM()
    llm.script("interpret", '{"intent": "help"}')
    r = await llm.complete(system="", messages=[LLMMessage(role="user", content="x")],
                           purpose="interpret")
    assert json.loads(r.text) == {"intent": "help"}
    llm.fail_purposes.add("interpret")
    with pytest.raises(ProviderError):
        await llm.complete(system="", messages=[LLMMessage(role="user", content="x")],
                           purpose="interpret")


def test_strict_schema_shape():
    schema = strict_schema(InterpretOut)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for d in schema["$defs"].values():
        if d.get("type") == "object":
            assert d["additionalProperties"] is False
    text = json.dumps(schema)
    assert '"default"' not in text and '"title"' not in text
    assert minimal_instance(schema)["intent"] == schema["$defs"]["Intent"]["enum"][0]


class _StubMessages:
    def __init__(self, response=None, exc=None):
        self.kwargs = None
        self.response = response
        self.exc = exc

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


class _StubClient:
    def __init__(self, response=None, exc=None):
        self.messages = _StubMessages(response, exc)
        self.beta = SimpleNamespace(messages=_StubMessages(response, exc))

    def with_options(self, **_kw):
        return self


def _response(text='{"ok": true}', stop="end_turn", model="claude-haiku-5-5"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           model=model, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


async def test_anthropic_request_shape_structured_output_and_effort():
    client = _StubClient(_response())
    llm = AnthropicLLM(api_key="k", client=client)
    r = await llm.complete(system="sys", messages=[LLMMessage(role="user", content="hi")],
                           purpose="call_turn", model="claude-haiku-5-5", effort="low",
                           json_schema={"type": "object"}, max_tokens=300)
    kw = client.messages.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema",
                                                                "schema": {"type": "object"}}}
    assert "temperature" not in kw and "thinking" not in kw
    assert r.text == '{"ok": true}' and r.input_tokens == 100
    assert llm.usage["call_turn"].calls == 1 and llm.usage["call_turn"].cost_inr > 0


async def test_anthropic_opus_uses_server_side_fallback():
    client = _StubClient(_response(model="claude-opus-5-5"))
    llm = AnthropicLLM(api_key="k", client=client)
    await llm.complete(system="s", messages=[LLMMessage(role="user", content="hi")])
    kw = client.beta.messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]


async def test_anthropic_attachments_become_content_blocks():
    client = _StubClient(_response())
    llm = AnthropicLLM(api_key="k", client=client)
    img = MediaBlob(data=b"\x89PNG", mime="image/png", filename="menu.png")
    await llm.complete(system="s", messages=[LLMMessage(role="user", content="read")],
                       model="claude-haiku-5-5", attachments=[img])
    content = client.messages.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1] == {"type": "text", "text": "read"}
    assert attachment_block(MediaBlob(data=b"%PDF", mime="application/pdf"))["type"] == \
        "document"
    with pytest.raises(ProviderError):
        attachment_block(MediaBlob(data=b"x", mime="video/mp4"))


async def test_anthropic_refusal_and_errors_become_provider_errors():
    llm = AnthropicLLM(api_key="k", client=_StubClient(_response(stop="refusal")))
    with pytest.raises(ProviderError) as e:
        await llm.complete(system="s", messages=[LLMMessage(role="user", content="x")],
                           model="claude-haiku-5-5")
    assert not e.value.retryable
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.APIConnectionError(request=req)
    llm = AnthropicLLM(api_key="k", client=_StubClient(exc=exc))
    with pytest.raises(ProviderError) as e:
        await llm.complete(system="s", messages=[LLMMessage(role="user", content="x")],
                           model="claude-haiku-5-5")
    assert e.value.retryable


def test_cost_estimate_and_factory(brain_settings):
    assert estimate_cost_inr("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(8.4)
    s = brain_settings.model_copy(update={"anthropic_api_key": None})
    llm = build_anthropic_llm(Container(s))
    assert llm.default_model == "claude-opus-5-5" and llm.fast_model == "claude-haiku-5-5"


@pytest.mark.live
async def test_live_anthropic_structured_output():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    llm = build_anthropic_llm(Container(Settings()))
    r = await llm.complete(
        system="Reply with JSON.", messages=[LLMMessage(role="user", content="Say ok")],
        model="claude-haiku-5-5", max_tokens=100,
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                     "required": ["ok"], "additionalProperties": False})
    assert "ok" in json.loads(r.text)
