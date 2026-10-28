# ruff: noqa: E501
"""The chain in the live message path (real pipeline over fakes): QU -> team -> planner/old chain."""

from __future__ import annotations

from friday.core.models import Person, Profile
from friday.planner.web import RawWebResult, WebItem, WebSource
from friday.team.gateway import TeamGateway
from tests.team.test_team import SWG, ZOM, Mixed, food_result, web_ok

QUERY = "butter chicken near me under 400"


def english(w) -> None:  # noqa: ANN001
    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    w.runtime.pipeline._reply_lang = lang


async def world(media_world, tmp_path, provider, *, city="Sonipat", **kw):  # noqa: ANN001, ANN201
    kw.setdefault("query_understanding_enabled", True)
    kw.setdefault("agent_team_enabled", True)
    w = await media_world(team_knowledge_dir=str(tmp_path), **kw)
    english(w)
    await w.c.repos.profiles.save(Profile(user_id=w.user.id, name="Himanshu", city=city))
    gw = w.runtime.pipeline.team
    assert isinstance(gw, TeamGateway)
    if gw.pm is not None:
        for srv in gw.team.servers.values():
            h = srv.handler
            if hasattr(h, "provider"):
                h.provider = provider
            if hasattr(h, "agent"):
                h.agent.provider = provider
    return w, gw


def body(msgs) -> str:  # noqa: ANN001
    return "\n".join(m.text or "" for m in msgs)


async def test_switches_off_build_nothing_and_the_old_flow_runs(media_world):
    w = await media_world()
    assert w.runtime.pipeline.team is None
    await w.say(QUERY)
    assert w.brain.seen[-1] == QUERY


async def test_butter_chicken_with_a_misspelt_home_town_end_to_end(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False))
    w, _ = await world(media_world, tmp_path, router)
    out = await w.say("pls butter chicken near Soneepat under 400")
    text = body(out)
    assert "Sonipat" in router.calls[0] and "Soneepat" not in router.calls[0] and "pls" not in router.calls[0].lower()
    assert ZOM in text and SWG in text and "Rs 349" in text and "Rs 299" in text
    assert "can't place orders or pay" in text
    assert w.brain.seen == []  # the old chain never saw it
    assert await w.c.repos.tasks.list_for_user(w.user.id) == []  # no call task was created
    recs = w.runtime.pipeline.team.team.audit.records
    assert {r["to"] for r in recs if r["dir"] == "request"} == {"zomato", "swiggy"}


async def test_near_me_uses_the_home_town_from_the_profile(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False))
    w, _ = await world(media_world, tmp_path, router)
    await w.say(QUERY + " on zomato")
    assert len(router.calls) == 1 and "Sonipat" in router.calls[0]


async def test_unknown_area_asks_one_question_and_the_next_message_answers_it(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False))
    w, _ = await world(media_world, tmp_path, router, city=None)
    out = await w.say(QUERY + " on zomato")
    assert "Which area" in body(out) and not router.calls
    out = await w.say("Model Town")
    assert "Model Town" in router.calls[0] and ZOM in body(out)


async def test_low_confidence_name_asks_before_changing_anything_then_yes_continues(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False))
    w, _ = await world(media_world, tmp_path, router)
    await w.c.repos.people.upsert(Person(owner_user_id=w.user.id, name="Priya Sharma"))
    out = await w.say("order butter chicken for priyaa sharma near me under 400 on zomato")
    assert "Did you mean Priya Sharma" in body(out) and not router.calls
    out = await w.say("yes")
    assert ZOM in body(out) and router.calls


async def test_no_keeps_the_users_own_spelling_and_does_not_ask_again(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False))
    w, _ = await world(media_world, tmp_path, router)
    await w.c.repos.people.upsert(Person(owner_user_id=w.user.id, name="Priya Sharma"))
    await w.say("order butter chicken for priyaa sharma near me under 400 on zomato")
    out = await w.say("no")
    assert "Did you mean" not in body(out) and router.calls


async def test_three_part_request_gets_one_merged_reply(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False))
    w, _ = await world(media_world, tmp_path, router)
    out = await w.say("butter chicken near me under 400 on zomato, biryani under 300 on swiggy and price of 5 kg atta on zepto")
    texts = [m.text for m in out if m.text]
    big = [t for t in texts if "Part 1" in t]
    assert len(big) == 1 and "Part 3" in big[0] and "Rs 289" in big[0]  # ONE reply holding all three parts
    last = w.runtime.pipeline.team.team.audit.records
    assert any(r["from"] == "lead-pm" for r in last) and any(r["from"].startswith("subpm-") for r in last)


async def test_rest_of_a_mixed_request_continues_in_the_old_chain(media_world, tmp_path):
    router = Mixed(web_ok(), zomato=food_result(extra=False))
    w, _ = await world(media_world, tmp_path, router)
    out = await w.say("butter chicken near me under 400 on zomato and find me a plumber tonight")
    assert ZOM in body(out) and "plumber" in body(out)
    assert w.brain.seen[-1] == "find me a plumber tonight"  # the remainder reached the old chain (calls keep their consent)


async def test_user_dictionary_commands_through_the_pipeline(media_world, tmp_path):
    w, _ = await world(media_world, tmp_path, Mixed(web_ok()))
    assert "Saved: Sonipat" in body(await w.say("add place Sonipat"))
    assert "Sonipat (place)" in body(await w.say("my words"))
    assert "deleted (1)" in body(await w.say("forget all my words"))
    assert "no saved words" in body(await w.say("my words"))


async def test_query_understanding_alone_rewrites_and_the_team_stays_off(media_world, tmp_path):
    w = await media_world(team_knowledge_dir=str(tmp_path), query_understanding_enabled=True)
    english(w)
    await w.c.repos.profiles.save(Profile(user_id=w.user.id, name="Himanshu", city="Sonipat"))
    assert w.runtime.pipeline.team.pm is None
    await w.say("pls tell me about Soneepat weather")
    assert w.brain.seen[-1] == "please tell me about Sonipat weather"


async def test_secrets_pass_through_untouched(media_world, tmp_path):
    w, _ = await world(media_world, tmp_path, Mixed(web_ok()))
    await w.say("my otp is 482913 soneepat")
    assert "Sonipat" not in (w.brain.seen[-1] if w.brain.seen else "")


async def test_web_price_alone_stays_with_the_planner(media_world, tmp_path):
    from friday.planner.web import FakeWebSearch

    w, _ = await world(media_world, tmp_path, Mixed(web_ok()), approach_planner_enabled=True)
    gw = w.runtime.pipeline.planner
    gw.web.provider = FakeWebSearch(RawWebResult(summary="Rs 289", items=[WebItem(title="Atta", price_text="Rs 289")],
                                                 sources=[WebSource(url="https://z.example/a")]))
    out = await w.say("check the price of 5 kg Aashirwad atta on Zepto")
    assert "Rs 289" in body(out) and "Part 1" not in body(out)
