"""OpenAI (GPT) client + provider selection, offline (stubbed SDK client)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from friday.brain.openai_llm import (
    OpenAILLM,
    attachment_part,
    build_openai_llm,
    estimate_cost_inr,
    schema_error,
)
from friday.brain.prompts import CACHE_BREAK
from friday.brain.schemas import CallActionOut, strict_schema
from friday.core.config import DEFAULT_OPENAI_PRICES_USD_PER_MTOK, Settings
from friday.core.container import Container
from friday.core.interfaces import LLMClient, LLMMessage, ProviderError
from friday.core.models import MediaBlob

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}


def _resp(text='{"ok": true}', finish="stop", refusal=None, cached=0, model="gpt-5.4-mini"):
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(finish_reason=finish,
                                 message=SimpleNamespace(content=text, refusal=refusal))],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=50,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
                              completion_tokens_details=SimpleNamespace(reasoning_tokens=10)),
    )


class _Stub:
    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **_kw):
        return self

    async def _create(self, **kw):
        self.calls.append(kw)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


def _llm(stub, **kw):
    return OpenAILLM(api_key="k", client=stub, **kw)


async def _go(llm, **kw):
    kw.setdefault("purpose", "interpret")
    return await llm.complete(system="rules", messages=[LLMMessage(role="user", content="hi")],
                              model="gpt-5.4-mini", **kw)


def test_satisfies_protocol():
    assert isinstance(_llm(_Stub()), LLMClient)


async def test_request_shape_structured_output_and_effort():
    stub = _Stub(_resp(cached=600))
    llm = _llm(stub, reasoning_effort={"call_turn": "low"})
    r = await _go(llm, purpose="call_turn", max_tokens=400, json_schema=SCHEMA)
    kw = stub.calls[0]
    assert kw["max_completion_tokens"] == 400 + 256 and kw["reasoning_effort"] == "low"
    assert "temperature" not in kw and "max_tokens" not in kw
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert kw["prompt_cache_key"] == "friday:call_turn"
    assert json.loads(r.text) == {"ok": True} and r.input_tokens == 1000
    t = llm.usage["call_turn"]
    assert t.cache_read_tokens == 600 and t.input_tokens == 400 and t.cost_inr > 0


async def test_non_reasoning_model_gets_no_effort_and_cache_break_is_stripped():
    stub = _Stub(_resp(model="gpt-4.1"))
    llm = _llm(stub, default_reasoning_effort="low")
    await llm.complete(system=f"static{CACHE_BREAK}stable",
                       messages=[LLMMessage(role="user", content="x")], model="gpt-4.1")
    kw = stub.calls[0]
    assert "reasoning_effort" not in kw and kw["max_completion_tokens"] == 1024
    assert "FRIDAY_CACHE_BREAK" not in kw["messages"][0]["content"]


async def test_provider_notes_are_additive_and_before_stable_data():
    stub = _Stub(_resp())
    llm = _llm(stub)
    await llm.complete(system=f"RULES{CACHE_BREAK}STABLE", purpose="interpret",
                       model="gpt-5.4-mini", messages=[LLMMessage(role="user", content="x")],
                       json_schema=SCHEMA)
    sys_text = stub.calls[0]["messages"][0]["content"]
    assert sys_text.startswith("RULES")
    assert sys_text.index("Provider notes") < sys_text.index("STABLE")
    assert "healthcare" in sys_text  # interpret-only disambiguation


async def test_repair_retry_then_success_and_then_failure():
    stub = _Stub(_resp('{"nope": 1}'), _resp('{"ok": true}'))
    llm = _llm(stub)
    r = await _go(llm, json_schema=SCHEMA)
    assert json.loads(r.text) == {"ok": True} and llm.repairs == 1 and len(stub.calls) == 2
    assert stub.calls[1]["messages"][-1]["role"] == "user"
    bad = _llm(_Stub(_resp("not json"), _resp("still not")))
    with pytest.raises(ProviderError):
        await _go(bad, json_schema=SCHEMA)


async def test_refusal_truncation_and_errors_become_provider_errors():
    with pytest.raises(ProviderError):
        await _go(_llm(_Stub(_resp(text="", refusal="no"))), json_schema=SCHEMA)
    with pytest.raises(ProviderError) as ei:
        await _go(_llm(_Stub(_resp(text='{"ok', finish="length"))), json_schema=SCHEMA)
    assert ei.value.retryable
    with pytest.raises(ProviderError, match="authentication"):
        await _go(_llm(_Stub(_status_error(openai.AuthenticationError, 401))))
    with pytest.raises(ProviderError, match="bad request"):
        await _go(_llm(_Stub(_status_error(openai.BadRequestError, 400))))


async def test_retries_429_then_succeeds_and_gives_up_on_5xx(monkeypatch):
    async def nosleep(_s):
        return None

    monkeypatch.setattr("friday.brain.openai_llm.asyncio.sleep", nosleep)
    stub = _Stub(_status_error(openai.RateLimitError, 429), _resp())
    r = await _go(_llm(stub))
    assert r.text and len(stub.calls) == 2
    stub = _Stub(*[_status_error(openai.InternalServerError, 503)] * 3)
    with pytest.raises(ProviderError) as ei:
        await _go(_llm(stub, max_retries=2))
    assert ei.value.retryable and len(stub.calls) == 3


async def test_call_turn_budget_stops_retries(monkeypatch):
    stub = _Stub(_status_error(openai.InternalServerError, 503), _resp())
    with pytest.raises(ProviderError):  # budget 0.3 s < backoff + margin -> no useful retry
        await _go(_llm(stub, call_turn_timeout_s=0.3), purpose="call_turn")
    assert len(stub.calls) == 1


async def test_attachments_image_pdf_text_and_unsupported():
    stub = _Stub(_resp())
    img = MediaBlob(data=b"\x89PNG", mime="image/png")
    pdf = MediaBlob(data=b"%PDF", mime="application/pdf")
    await _go(_llm(stub), attachments=[img, pdf])
    parts = stub.calls[0]["messages"][1]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png")
    assert parts[1]["type"] == "file" and parts[-1] == {"type": "text", "text": "hi"}
    assert attachment_part(MediaBlob(data=b"a b", mime="text/plain"))["type"] == "text"
    with pytest.raises(ProviderError):
        attachment_part(MediaBlob(data=b"x", mime="application/zip"))


def test_cost_estimate_uses_cached_price_and_longest_prefix():
    p = DEFAULT_OPENAI_PRICES_USD_PER_MTOK
    full = estimate_cost_inr("gpt-5.4-mini", 1_000_000, 0, prices=p)
    cached = estimate_cost_inr("gpt-5.4-mini", 1_000_000, 0, 1_000_000, prices=p)
    assert full == pytest.approx(0.75 * 84) and cached == pytest.approx(0.075 * 84)
    assert estimate_cost_inr("gpt-5.4-nano-x", 1_000_000, 0, prices=p) == pytest.approx(0.2 * 84)


def test_schema_error_never_leaks_values():
    s = strict_schema(CallActionOut)
    assert schema_error({"type": "say"}, s) is not None
    assert "secret" not in (schema_error({"type": "secret-value"}, s) or "")


# ------------------------------------------------------------------ settings / provider selection
def _s(**kw):
    kw.setdefault("anthropic_api_key", None)
    kw.setdefault("openai_api_key", None)
    return Settings(_env_file=None, env="test", **kw)


def test_auto_resolution_order():
    assert _s().resolve_llm() == "fake"
    assert _s(openai_api_key="o").resolve_llm() == "openai"
    assert _s(openai_api_key="o", anthropic_api_key="a").resolve_llm() == "anthropic"
    assert _s(openai_api_key="o", llm_provider="fake").resolve_llm() == "fake"
    assert _s(mode="live").resolve_llm() == "anthropic"  # reports the missing key, never the fake


def test_routing_follows_provider_and_claude_defaults_unchanged():
    g = _s(openai_api_key="o")
    assert g.model_for("interpret") == "gpt-5.4-mini" and g.model_for("call_turn") == "gpt-5.4-mini"
    assert g.model_for("interpret", escalate=True) == "gpt-5.4"
    assert g.openai_reasoning_effort["call_turn"] == "low"
    c = _s()
    assert c.model_for("call_turn") == "claude-sonnet-5-5"
    assert c.model_for("x") == "claude-haiku-5-5"


def test_live_problems_accept_either_key():
    base = dict(mode="live", profile="pilot", public_base_url="https://x.example.com")
    names = [p for p in _s(**base).live_problems() if "ANTHROPIC" in p or "OPENAI" in p]
    assert names and "OPENAI_API_KEY" in names[0]
    assert not [p for p in _s(openai_api_key="o", **base).live_problems() if "_API_KEY" in p
                and ("OPENAI" in p or "ANTHROPIC" in p)]
    pinned = _s(llm_provider="openai", **base).live_problems()
    assert "missing OPENAI_API_KEY" in pinned


def test_container_builds_openai_client():
    c = Container(_s(openai_api_key="sk-test-not-real", llm_provider="openai"))
    assert c.provider_for("llm") == "openai"
    llm = build_openai_llm(c)
    assert isinstance(llm, OpenAILLM) and llm.call_turn_timeout_s == 8.0
