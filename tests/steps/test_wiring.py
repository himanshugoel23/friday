# ruff: noqa: E501
"""The step runner in the real pipeline over fakes: planner entry, chat replies, switch off = nothing changes, delete-everything, settings."""

from __future__ import annotations

from pathlib import Path

from friday.browser_agent.wiring import build_agent
from friday.core.config import Settings
from friday.core.models import Place
from friday.shopping import places
from friday.shopping.agent import ShoppingAgent
from friday.steps.gateway import StepGateway
from friday.steps.wiring import build_steps
from tests.browser_agent.fakes import FakeBrowser, FakeProvider, ScriptedLLM
from tests.shopping.helpers import BIGBASKET, INSTAMART, SiteFake
from tests.steps.world import OPEN_FREE, READ_OK, SEARCH_OK, pages


def texts(msgs) -> list[str]:  # noqa: ANN001
    return [m.text or "" for m in msgs]


async def world(media_world, tmp_path: Path, *, steps: bool, script=None):  # noqa: ANN001, ANN201
    w = await media_world(approach_planner_enabled=True, shopping_assistant_enabled=True, browser_agent_enabled=True, browser_agent_dir=str(tmp_path),
                          browser_steps_enabled=steps, browser_steps_dir=str(tmp_path / "steps"))

    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    pipe = w.runtime.pipeline
    pipe._reply_lang = lang
    browser = FakeBrowser(pages())
    llm = ScriptedLLM(script if script is not None else [*OPEN_FREE, *SEARCH_OK, *READ_OK])
    gw = build_agent(pipe, provider=FakeProvider(browser), llm=llm)
    gw.sync = True
    pipe.browser_agent = gw
    pipe.planner.shopping.agent = ShoppingAgent(SiteFake({"bigbasket": BIGBASKET, "instamart": INSTAMART}), now=pipe.clock.now)
    pipe.browser_steps = build_steps(pipe)
    pipe.planner.steps = pipe.browser_steps
    return w, pipe, browser


def test_switch_is_off_by_default_and_named_in_the_web_test_script():
    assert Settings().browser_steps_enabled is False
    script = (Path(__file__).parents[2] / "deploy" / "enable-web-test.sh").read_text()
    assert "FRIDAY_BROWSER_STEPS_ENABLED" in script.split("FEATURES_ON = [")[1].split("]")[0]


async def test_switch_on_price_of_atta_runs_as_steps_asks_the_area_once_and_saves_it(media_world, tmp_path):
    w, pipe, browser = await world(media_world, tmp_path, steps=True)
    assert isinstance(pipe.browser_steps, StepGateway)
    out = texts(await w.say("price of atta on zepto"))
    assert out[0].startswith("Step 1 of 5:") and any(o.startswith("Step 2 of 5:") and "Home or PG?" in o for o in out)
    assert browser.typed() == []
    out = texts(await w.say("PG, Koramangala 560034"))
    assert "My pick:" in out[-1] and "Other popular atta brands" in out[-1]
    assert browser.typed()[0] == "560034"
    saved = await places.saved_places(w.c.repos, w.user.id, include_office=False)
    assert [(p.kind, p.pincode) for p in saved] == [("pg", "560034")]
    assert not pipe.browser_steps.runner.has_open(w.user.id)


async def test_saved_place_means_no_area_question(media_world, tmp_path):
    w, pipe, browser = await world(media_world, tmp_path, steps=True)
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Home", address_text="Koramangala 560034"))
    out = texts(await w.say("price of atta on zepto"))
    assert not any("Home or PG" in o for o in out) and "My pick:" in out[-1] and browser.typed()[0] == "560034"


async def test_switch_off_nothing_changes_the_old_shopping_flow_answers(media_world, tmp_path):
    w, pipe, browser = await world(media_world, tmp_path, steps=False)
    assert pipe.browser_steps is None and pipe.planner.steps is None
    out = texts(await w.say("price of atta on zepto"))
    assert out and not any(o.startswith("Step ") for o in out) and "Checking Zepto" in out[0]
    assert browser.log == []  # the browser was never touched


async def test_delete_everything_erases_open_plans(media_world, tmp_path):
    w, pipe, _ = await world(media_world, tmp_path, steps=True)
    await w.say("price of atta on zepto")
    assert pipe.browser_steps.runner.has_open(w.user.id)
    await pipe.browser_steps.forget_user(w.user.id)
    assert not pipe.browser_steps.runner.has_open(w.user.id) and pipe.browser_steps.runner.store.list_open() == []


async def test_without_the_browser_agent_the_steps_stay_off(media_world, tmp_path):
    w = await media_world(approach_planner_enabled=True, browser_steps_enabled=True, browser_steps_dir=str(tmp_path))
    assert w.runtime.pipeline.browser_steps is None
