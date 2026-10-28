# ruff: noqa: E501
"""The planner in the live message path (real pipeline over fakes, fake web provider, no network)."""

from __future__ import annotations

import asyncio

from friday.planner import signals as sg
from friday.planner.gateway import PlannerGateway
from friday.planner.web import FakeWebSearch, RawWebResult, WebItem, WebSource

ZEPTO = "check the price of 5 kg Aashirwad atta on Zepto"
GOOD = RawWebResult(
    summary="Aashirvaad Atta 5 kg is listed at Rs 289 on Zepto.",
    items=[WebItem(title="Aashirvaad Atta 5 kg", price_text="Rs 289", store="Zepto", url="https://zepto.example/atta")],
    sources=[WebSource(url="https://zepto.example/atta", title="Zepto")],
)


def texts(msgs) -> list[str]:  # noqa: ANN001
    return [m.text or "" for m in msgs]


def english(w) -> None:  # noqa: ANN001
    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    w.runtime.pipeline._reply_lang = lang


async def world(media_world, provider, **kw):  # noqa: ANN001, ANN201
    w = await media_world(approach_planner_enabled=True, **kw)
    english(w)
    gw = w.runtime.pipeline.planner
    assert isinstance(gw, PlannerGateway)
    gw.web.provider = provider
    return w, gw


async def test_switch_off_builds_nothing_and_old_flow_runs(media_world):
    w = await media_world()
    assert w.runtime.pipeline.planner is None
    await w.say(ZEPTO)
    assert w.brain.seen[-1] == ZEPTO


async def test_zepto_price_gets_a_sourced_web_answer_and_never_reaches_calls(media_world):
    p = FakeWebSearch(GOOD)
    w, _ = await world(media_world, p)
    out = await w.say(ZEPTO)
    body = "\n".join(texts(out))
    assert p.calls and "https://zepto.example/atta" in body and "Rs 289" in body
    assert "not the Zepto app" in body or "Zepto app" in body  # the web-vs-app caveat
    assert "pincode" in body.lower()
    assert not sg.mentions_call(body)
    assert ZEPTO not in w.brain.seen  # the vendor-call pipeline / brain never saw it
    assert await w.c.repos.tasks.list_for_user(w.user.id) == []


async def test_pincode_reply_reruns_the_lookup_with_the_pincode(media_world):
    p = FakeWebSearch(GOOD)
    w, _ = await world(media_world, p)
    await w.say(ZEPTO)
    await w.say("560001")
    assert len(p.calls) == 2 and "560001" in p.calls[1]
    assert "560001" not in w.brain.seen


async def test_plumber_tonight_continues_into_the_existing_flow_with_a_call_plan(media_world):
    w, _ = await world(media_world, FakeWebSearch(GOOD))
    await w.say("find me a plumber tonight")
    assert w.brain.seen[-1] == "find me a plumber tonight"  # not intercepted: the old chain (consent, allow-list) owns calls


async def test_order_pizza_without_connector_asks_one_call_free_question(media_world):
    p = FakeWebSearch(GOOD)
    w, _ = await world(media_world, p)
    out = await w.say("order pizza")
    body = "\n".join(texts(out))
    assert "can't place orders inside apps" in body and not sg.mentions_call(body)
    assert "order pizza" not in w.brain.seen and not p.calls


async def test_knowledge_question_goes_to_the_brain(media_world):
    w, _ = await world(media_world, FakeWebSearch(GOOD))
    await w.say("what is the capital of France")
    assert w.brain.seen[-1] == "what is the capital of France"


async def test_slow_lookup_sends_one_ack_naming_the_approach_then_the_result(media_world):
    async def slow() -> RawWebResult:
        await asyncio.sleep(0.3)
        return GOOD

    w, gw = await world(media_world, FakeWebSearch(slow))
    gw.ack_after_s = 0.05
    out = texts(await w.say(ZEPTO))
    assert len(out) == 2 and "Zepto" in out[0] and "checking" in out[0].lower()
    assert not sg.mentions_call(out[0]) and "https://zepto.example/atta" in out[1]


async def test_fast_lookup_sends_no_ack(media_world):
    w, _ = await world(media_world, FakeWebSearch(GOOD))
    assert len(await w.say(ZEPTO)) == 1


async def test_timeout_tells_the_user_plainly_and_yes_retries(media_world):
    async def hang() -> RawWebResult:
        await asyncio.sleep(30)
        return GOOD

    p = FakeWebSearch(hang, GOOD)
    w, gw = await world(media_world, p)
    gw.web.timeout_s = 0.2
    out = "\n".join(texts(await w.say(ZEPTO)))
    assert "too long" in out and "Zepto" in out and not sg.mentions_call(out)
    again = "\n".join(texts(await w.say("yes")))
    assert "https://zepto.example/atta" in again and len(p.calls) == 2


async def test_missing_provider_says_so_and_never_hangs(media_world):
    w = await media_world(approach_planner_enabled=True)  # no OPENAI key in the test world
    english(w)
    out = "\n".join(texts(await w.say(ZEPTO)))
    assert "can't look things up" in out and not sg.mentions_call(out)


async def test_slow_call_flow_gets_a_vendor_ack_only_because_a_call_is_planned(media_world):
    w, gw = await world(media_world, FakeWebSearch(GOOD))
    gw.ack_after_s = 0.01
    orig = w.runtime.pipeline._after_planner

    async def slow_rest(user, msg):  # noqa: ANN001, ANN202
        await asyncio.sleep(0.1)
        await orig(user, msg)

    w.runtime.pipeline._after_planner = slow_rest
    # the pipeline captured the bound method at call time through self._after_planner
    out = texts(await w.say("find me a plumber tonight"))
    assert any("vendors" in t for t in out)
    assert sum(1 for t in out if "vendors" in t) == 1  # exactly one ack
    out2 = texts(await w.say("what is the capital of France"))
    assert sum(1 for t in out2 if "thinking" in t or "soch" in t) == 1 and not any("vendors" in t for t in out2)
