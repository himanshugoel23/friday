# ruff: noqa: E501
"""The agent team: PM -> specialists over A2A, small vs big tasks, sub-PM failure, budget, food agents. Fakes only."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import TaskBudget
from friday.a2a.client import A2AClient, A2AClientError
from friday.core.clock import FakeClock
from friday.core.config import Settings
from friday.planner.web import RawWebResult, WebItem, WebSource
from friday.team.food import is_food_clause, parse_food
from friday.team.knowledge import KnowledgeStore
from friday.team.pm import decompose, group_goals, is_big, merge_reply
from friday.team.wiring import build_team

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
ZOM = "https://www.zomato.com/ncr/butter-chicken-house-sonipat"
ZOM2 = "https://www.zomato.com/ncr/dhaba-express-sonipat"
SWG = "https://www.swiggy.com/restaurants/punjabi-tadka-sonipat-123"


def food_result(url=ZOM, price=349.0, text="Rs 349", extra=True):
    items = [WebItem(title="Butter Chicken House", price_text=text, price_inr=price, url=url, rating="4.2", delivery_time="35 min", offer="20% OFF")]
    if extra:
        items.append(WebItem(title="Fancy Place", price_text="Rs 650", price_inr=650.0, url=url))  # above the cap
        items.append(WebItem(title="Menu not shown", url=url))  # no price printed
        items.append(WebItem(title="Elsewhere", price_text="Rs 100", price_inr=100.0, url="https://example.com/x"))  # wrong domain
    return RawWebResult(summary="Options.", items=items, sources=[WebSource(url=url, title="page")])


class Router:
    """Fake web search that answers by the site named in the query."""

    def __init__(self, **by_site):
        self.by_site, self.calls = by_site, []

    async def search(self, query, *, timeout_s, hint=None):  # noqa: ANN001, ANN201
        self.calls.append(query)
        for site, res in self.by_site.items():
            if site in query.lower():
                if isinstance(res, Exception):
                    raise res
                return res
        return RawWebResult()


def team(tmp_path: Path, provider, **sw):
    s = Settings(_env_file=None, team_knowledge_dir=str(tmp_path), **sw)
    return build_team(s, FakeClock(NOW), provider=provider, store=KnowledgeStore(tmp_path), audit=A2AAudit())


def ok_router():
    return Router(zomato=food_result(), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False))


# ---------------------------------------------------------------- parsing and decomposition
def test_parse_food_request():
    r = parse_food("butter chicken near me under 400", "Sonipat")
    assert (r.dish, r.area, r.max_price_inr, r.site) == ("butter chicken", "Sonipat", 400, None)
    r = parse_food("find biryani on swiggy near Model Town below Rs 250", None)
    assert (r.dish, r.area, r.max_price_inr, r.site) == ("biryani", "Model Town", 250, "swiggy")
    assert parse_food("pizza 300 ke andar", "X").max_price_inr == 300
    assert is_food_clause("butter chicken near me under 400") and not is_food_clause("price of atta on zepto")


def test_decompose_and_size_rule():
    g1 = decompose("butter chicken near me under 400")
    assert len(g1) == 1 and g1[0].domain == "food" and not is_big(g1, 3)
    g2 = decompose("butter chicken near me under 400 on zomato and price of 5 kg atta on zepto")
    assert [g.domain for g in g2] == ["food", "web"] and not is_big(g2, 3)
    g3 = decompose("butter chicken near me under 400 on zomato, biryani under 300 on swiggy and price of 5 kg atta on zepto")
    assert [g.domain for g in g3] == ["food", "food", "web"] and is_big(g3, 3)
    assert [g.site for g in g3[:2]] == ["zomato", "swiggy"]
    mod = decompose("order butter chicken near me under 400 with extra raita")
    assert len(mod) == 1 and "raita" in mod[0].text  # a modifier joins the goal before it
    mixed = decompose("butter chicken near me under 400 and find me a plumber tonight")
    assert [g.domain for g in mixed] == ["food", "other"] and not mixed[1].team_supported


def test_sub_pm_cap_overflow_joins_last():
    goals = decompose("; ".join(f"biryani under {100 + i} on swiggy" for i in range(6)))
    groups = group_goals(goals, 4)
    assert len(groups) == 4 and [len(g) for g in groups] == [1, 1, 1, 3]


# ---------------------------------------------------------------- small task: PM -> Zomato over A2A
async def test_pm_delegates_butter_chicken_to_zomato_via_a2a_only(tmp_path):
    router = ok_router()
    t = team(tmp_path, router)
    out = await t.pm.run("butter chicken near me under 400 on zomato", default_area="Sonipat", lang="en")
    assert not out.big and out.sub_pms == 0 and out.results[0].status == "done"
    site = out.results[0].sites[0]
    assert site["site"] == "zomato" and site["kb_version"] == 1 and site["kb_status"] == "unverified"
    names = [o["name"] for o in site["options"]]
    assert names == ["Butter Chicken House", "Menu not shown"]  # cap 400 applied; over-cap and off-domain dropped
    assert site["options"][0]["price_inr"] == 349.0 and site["options"][1]["price_inr"] is None
    assert all(o["deep_link"].startswith("https://www.zomato.com/") for o in site["options"]) and site["over_cap"] == 1
    assert "sonipat" in router.calls[0].lower() and "zomato" in router.calls[0].lower() and len(router.calls) == 1
    # every hop is an audited A2A message: request + response, pm -> zomato, depth 1
    recs = t.audit.for_root(out.root_task_id)
    assert [(r["dir"], r["from"], r["to"], r["depth"]) for r in recs] == [("request", "pm", "zomato", 1), ("response", "zomato", "pm", 1)]
    assert recs[1]["state"] == "completed"
    reply = merge_reply(out, "en")
    assert "Rs 349" in reply and "4.2*" in reply and ZOM in reply and "price not shown" in reply
    assert "as of 28 Oct 14:30 IST" in reply  # 09:00 UTC
    assert "can't place orders or pay" in reply and "not verified yet" in reply  # honest about unverified knowledge
    assert out.budget["cost_inr"] == pytest.approx(1.0) and out.budget["steps"] == 1


async def test_no_site_named_asks_both_agents_and_mixed_failure_is_partial(tmp_path):
    t = team(tmp_path, Router(zomato=food_result(extra=False), swiggy=RuntimeError("boom")))
    out = await t.pm.run("butter chicken near me under 400", default_area="Sonipat", lang="en")
    assert out.results[0].status == "done" and len(out.results[0].sites) == 1  # swiggy failed, zomato answered
    assert {c["agent"] for c in out.children} == {"zomato", "swiggy"}


async def test_unknown_area_is_input_required_then_the_same_task_continues(tmp_path):
    router = Router(zomato=food_result(extra=False))
    t = team(tmp_path, router)
    out = await t.pm.run("butter chicken under 400 on zomato", default_area=None, lang="en")
    r = out.results[0]
    assert r.status == "input_required" and r.question == "which_area" and r.pending and not router.calls
    assert "Which area" in merge_reply(out, "en")
    done = await t.pm.resume(r.pending, "Sonipat", r.goal, out.root_task_id)
    assert done.status == "done" and done.sites[0]["area"] == "Sonipat"
    assert r.pending[0][1] in {rec["task"] for rec in t.audit.records if rec["dir"] == "response"}  # same task id


async def test_no_cited_domain_page_means_no_result_not_an_invented_one(tmp_path):
    bad = RawWebResult(summary="x", items=[WebItem(title="A", price_text="Rs 100", price_inr=100.0, url="https://blog.example/a")],
                       sources=[WebSource(url="https://blog.example/a")])
    t = team(tmp_path, Router(zomato=bad))
    out = await t.pm.run("butter chicken near me on zomato", default_area="Sonipat", lang="en")
    s = out.results[0].sites[0]
    assert s["status"] == "no_result" and s["options"] == []
    text = merge_reply(out, "en")
    assert "could not find reliable Zomato options" in text and "Rs 100" not in text


async def test_printed_price_that_disagrees_with_its_number_is_dropped(tmp_path):
    res = food_result(price=199.0, text="Rs 349", extra=False)
    t = team(tmp_path, Router(zomato=res))
    out = await t.pm.run("butter chicken near me under 400 on zomato", default_area="Sonipat", lang="en")
    o = out.results[0].sites[0]["options"][0]
    assert o["price_inr"] is None  # 199 vs "Rs 349": not trusted, never shown as a number


# ---------------------------------------------------------------- big task: lead PM + sub-PMs
BIG = "butter chicken near me under 400 on zomato, biryani under 300 on swiggy and price of 5 kg atta on zepto"


def web_ok():
    return RawWebResult(summary="Atta 5 kg is Rs 289.", items=[WebItem(title="Atta", price_text="Rs 289", url="https://zepto.example/a")],
                        sources=[WebSource(url="https://zepto.example/a")])


class Mixed(Router):
    def __init__(self, web=None, **kw):
        super().__init__(**kw)
        self.web = web

    async def search(self, query, *, timeout_s, hint=None):  # noqa: ANN001, ANN201
        if "zomato" not in query.lower() and "swiggy" not in query.lower():
            self.calls.append(query)
            if isinstance(self.web, Exception):
                raise self.web
            return self.web
        return await super().search(query, timeout_s=timeout_s, hint=hint)


async def test_three_part_request_spawns_sub_pms_one_task_with_child_ids(tmp_path):
    t = team(tmp_path, Mixed(web_ok(), zomato=food_result(extra=False), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False)))
    out = await t.pm.run(BIG, default_area="Sonipat", lang="en")
    assert out.big and out.sub_pms == 3 and [r.status for r in out.results] == ["done"] * 3
    assert [r.group for r in out.results] == [1, 2, 3]
    recs = t.audit.for_root(out.root_task_id)
    lead_calls = [r for r in recs if r["from"] == "lead-pm" and r["dir"] == "request"]
    sub_calls = [r for r in recs if r["from"].startswith("subpm-") and r["dir"] == "request"]
    assert {r["to"] for r in lead_calls} == {"subpm-1", "subpm-2", "subpm-3"} and all(r["depth"] == 1 for r in lead_calls)
    assert len(sub_calls) == 3 and all(r["depth"] == 2 for r in sub_calls)  # depth max 2
    assert not [r for r in recs if r["from"].startswith("subpm-") and r["to"].startswith("subpm-")]  # no sub-PM -> sub-PM
    assert not [r for r in recs if r["to"] == "lead-pm" and r["from"] in ("zomato", "swiggy", "web_lookup")]  # specialists never talk to the lead
    kids = {c["agent"] for c in out.children}
    assert {"subpm-1", "subpm-2", "subpm-3", "zomato", "swiggy", "web_lookup"} <= kids
    assert len({c["task"] for c in out.children}) == len(out.children)  # distinct child task ids
    reply = merge_reply(out, "en")  # ONE reply from the lead
    assert reply.count("Part ") == 3 and "Rs 289" in reply and "Zomato" in reply and "Swiggy" in reply
    assert out.budget["steps"] == 6  # 3 lead->sub-PM + 3 sub-PM->specialist (shared budget)


async def test_sub_pm_cannot_reach_a_peer_or_go_deeper(tmp_path):
    t = team(tmp_path, ok_router())
    from friday.a2a.transport import InProcessTransport

    spec_only = InProcessTransport(t.servers)
    assert "subpm-1" not in spec_only.agents()  # a sub-PM's transport has specialists only
    deep = A2AClient(spec_only, name="x", depth=2)  # a third level
    with pytest.raises(A2AClientError) as e:
        await deep.send("zomato", data={"dish": "pizza", "area": "Sonipat"})
    assert e.value.code == -32010


async def test_failed_sub_project_is_reported_up_and_lead_continues_with_partial_result(tmp_path):
    t = team(tmp_path, Mixed(RuntimeError("web down"), zomato=food_result(extra=False), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False)))
    out = await t.pm.run(BIG, default_area="Sonipat", lang="en")
    st = {r.goal.domain + str(r.goal.id): r.status for r in out.results}
    assert st == {"food1": "done", "food2": "done", "web3": "failed"} and out.partial
    reply = merge_reply(out, "en")
    assert "Rs 349" in reply and "could not finish this part" in reply and "Part 3" in reply


async def test_every_part_failing_gives_one_plain_sorry(tmp_path):
    t = team(tmp_path, Mixed(RuntimeError("x"), zomato=RuntimeError("x"), swiggy=RuntimeError("x")))
    out = await t.pm.run(BIG, default_area="Sonipat", lang="en")
    assert all(r.status == "failed" for r in out.results)
    assert merge_reply(out, "en").startswith("I could not get a reliable answer")


async def test_budget_steps_exhaustion_stops_cleanly_with_partial_result(tmp_path):
    t = team(tmp_path, Mixed(web_ok(), zomato=food_result(extra=False), swiggy=food_result(SWG, 299.0, "Rs 299", extra=False)),
             team_budget_steps=4)
    out = await t.pm.run(BIG, default_area="Sonipat", lang="en")
    assert out.budget_exhausted == "steps" and out.budget["steps"] == 4
    done = [r for r in out.results if r.status == "done"]
    assert done and len(done) < 3 and all(r.status in ("done", "skipped", "failed") for r in out.results)
    assert "stopped early" in merge_reply(out, "en")


async def test_budget_cost_exhaustion_and_seconds(tmp_path):
    t = team(tmp_path, ok_router(), team_budget_cost_inr=1.0)
    out = await t.pm.run("butter chicken under 400 on zomato; biryani under 300 on swiggy; pizza under 200 on zomato", default_area="Sonipat", lang="en")
    assert out.budget_exhausted == "cost" and out.budget["cost_inr"] >= 1.0
    clock = [0.0]
    t2 = team(tmp_path / "b", ok_router())

    def late() -> TaskBudget:
        b = TaskBudget(10, 5.0, 5.0, clock=lambda: clock[0])
        clock[0] = 99.0  # time is already up before the first request
        return b

    t2.pm.budget_factory = late
    out2 = await t2.pm.run("butter chicken near me on zomato", default_area="Sonipat", lang="en")
    assert out2.budget_exhausted == "seconds" and out2.results[0].status == "skipped"


async def test_small_two_goal_request_uses_one_pm_and_other_goals_are_left_for_the_old_chain(tmp_path):
    t = team(tmp_path, Mixed(web_ok(), zomato=food_result(extra=False)))
    out = await t.pm.run("butter chicken near me under 400 on zomato and find me a plumber tonight", default_area="Sonipat", lang="en")
    assert not out.big and out.sub_pms == 0 and out.remaining_text.startswith("find me a plumber")
    assert "plumber" in merge_reply(out, "en")


# ---------------------------------------------------------------- structure: agents are isolated behind A2A
def test_pm_module_never_imports_the_specialists():
    src = (Path(__file__).parents[2] / "friday" / "team" / "pm.py").read_text()
    for banned in ("SiteAgent", "WebLookupSpecialist", "from friday.team.food import SiteAgent", "KnowledgeStore"):
        assert banned not in src
    food = (Path(__file__).parents[2] / "friday" / "team" / "food.py").read_text()
    assert not re.search(r"^from friday\.team\.pm|^import friday\.team\.pm", food, re.M)
