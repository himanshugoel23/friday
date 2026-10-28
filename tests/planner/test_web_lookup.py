# ruff: noqa: E501
"""Web lookup agent with a fake provider: sources, as-of, caveat, timeout, retry, cache. No network."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from friday.core.interfaces import ProviderError
from friday.planner.agents.web_lookup import WebLookupAgent, WebLookupInput
from friday.planner.web import (
    FakeWebSearch,
    OpenAIWebSearch,
    RawWebResult,
    UnavailableWebSearch,
    WebItem,
    WebSource,
    parse_openai_response,
)

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
GOOD = RawWebResult(
    summary="Aashirvaad Atta 5 kg is listed at Rs 289 on Zepto.",
    items=[WebItem(title="Aashirvaad Atta 5 kg", price_text="Rs 289", price_inr=289, store="Zepto", url="https://zepto.example/atta")],
    sources=[WebSource(url="https://zepto.example/atta", title="Zepto")],
)
INP = WebLookupInput(query="Aashirvaad atta 5 kg price Zepto", retailer="zepto", lang="en")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def agent(provider, **kw) -> WebLookupAgent:
    return WebLookupAgent(provider, now=lambda: NOW, **kw)


async def test_ok_result_has_sources_as_of_and_quick_commerce_caveat():
    a = agent(FakeWebSearch(GOOD))
    out = await a.run(INP)
    assert out.status == "ok" and out.sources[0].url.startswith("https://") and out.as_of == NOW
    assert "not the Zepto app" in out.caveat and "pincode" in out.caveat
    assert out.ask_pincode is True  # no pincode given on a quick-commerce store
    text = a.render(out, "en")
    assert "https://zepto.example/atta" in text and "14:30 IST" in text and "Rs 289" in text
    assert "pincode" in text.lower() and "call" not in text.lower()


async def test_pincode_known_does_not_ask_again():
    out = await agent(FakeWebSearch(GOOD)).run(INP.model_copy(update={"pincode": "560001"}))
    assert out.ask_pincode is False


async def test_non_quick_commerce_gets_the_generic_web_caveat():
    out = await agent(FakeWebSearch(GOOD)).run(WebLookupInput(query="atta 5kg price amazon", retailer="amazon", lang="en"))
    assert out.caveat and "public web pages" in out.caveat and not out.ask_pincode


async def test_no_sources_means_no_answer():
    a = agent(FakeWebSearch(RawWebResult(summary="It costs Rs 100", sources=[])))
    out = await a.run(INP)
    assert out.status == "no_result" and not out.items
    assert "reliable" in a.render(out, "en")


async def test_timeout_is_hard_and_reported_plainly():
    async def hang() -> RawWebResult:
        await asyncio.sleep(30)
        return GOOD

    a = agent(FakeWebSearch(hang), timeout_s=0.2)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    out = await a.run(INP)
    assert out.status == "timeout" and loop.time() - t0 < 2
    msg = a.render(out, "en")
    assert "too long" in msg and "try once more" in msg and "call" not in msg.lower()


async def test_single_retry_at_most_then_unavailable():
    p = FakeWebSearch(ProviderError("web_search", "boom"))
    out = await agent(p).run(INP)
    assert out.status == "unavailable" and len(p.calls) == 2


async def test_one_retry_recovers():
    p = FakeWebSearch(ProviderError("web_search", "boom"), GOOD)
    out = await agent(p).run(INP)
    assert out.status == "ok" and len(p.calls) == 2


async def test_unconfigured_provider_fails_clearly():
    a = agent(UnavailableWebSearch())
    out = await a.run(INP)
    assert out.status == "unavailable"
    assert "can't look things up" in a.render(out, "en")


async def test_cache_hit_within_ttl_then_expiry_and_failures_not_cached():
    mono = Clock()
    p = FakeWebSearch(GOOD)
    a = agent(p, monotonic=mono, cache_ttl_s=300)
    first = await a.run(INP)
    again = await a.run(INP.model_copy(update={"query": "  Aashirvaad ATTA 5 kg price zepto "}))
    assert not first.from_cache and again.from_cache and len(p.calls) == 1
    mono.t += 301
    assert not (await a.run(INP)).from_cache and len(p.calls) == 2
    bad = FakeWebSearch(ProviderError("web_search", "x"))
    b = agent(bad, monotonic=Clock())
    await b.run(INP)
    n = len(bad.calls)
    await b.run(INP)
    assert len(bad.calls) == 2 * n  # an error was not cached


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_openai_response_parsing_keeps_only_cited_urls():
    text = '{"summary": "Rs 289 on Zepto", "items": [{"title": "Atta", "price_text": "Rs 289", "price_inr": 289, "store": "Zepto", "url": "https://a.example/x"}, {"title": "Fake", "price_text": "Rs 1", "url": "https://invented.example"}]}'
    resp = Obj(output=[Obj(type="message", content=[Obj(type="output_text", text=text, annotations=[Obj(type="url_citation", url="https://a.example/x", title="A")])])])
    raw = parse_openai_response(resp)
    assert [s.url for s in raw.sources] == ["https://a.example/x"]
    assert raw.items[0].url == "https://a.example/x" and raw.items[1].url is None


async def test_openai_adapter_uses_the_responses_web_search_tool_and_maps_errors():
    seen = {}

    class R:
        async def create(self, **kw):
            seen.update(kw)
            raise RuntimeError("network")

    p = OpenAIWebSearch("k", model="m", client=Obj(responses=R()))
    with pytest.raises(ProviderError):
        await p.search("q", timeout_s=5)
    assert seen["tools"][0]["type"] == "web_search" and seen["model"] == "m"
