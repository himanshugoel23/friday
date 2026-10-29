# ruff: noqa: E501
"""The agent in the real pipeline over fakes: planner entry, chat replies, delete-everything, A2A specialist, doctor, switches."""

from __future__ import annotations

import json
from pathlib import Path

from friday.a2a.audit import A2AAudit
from friday.a2a.client import A2AClient
from friday.a2a.types import TaskState
from friday.browser_agent.a2a_agent import BROWSER_SKILL
from friday.browser_agent.gateway import BrowserAgentGateway, domains_from_text
from friday.browser_agent.wiring import build_agent
from friday.planner import signals as sg
from tests.browser_agent.fakes import A, FakeBrowser, FakePageSpec, FakeProvider, ScriptedLLM

NF = "https://netflix.com/"
NF_PAGES = {
    NF: FakePageSpec("Account", "Your plan: Standard. Next bill 5 Nov.", [{"name": "Cancel membership", "role": "link", "goes_to": NF + "cancel"}]),
    NF + "cancel": FakePageSpec("Cancel", "Your plan ends on 5 Nov if you cancel.", [{"name": "Finish cancellation", "role": "button", "submit": True, "goes_to": NF + "done", "submit_marks": True}]),
    NF + "done": FakePageSpec("Cancelled", "Your membership is cancelled."),
}
CANCEL_SCRIPT = [A("click", target="e1"), A("request_confirmation", summary="Cancel your Netflix membership. It ends on 5 Nov and you lose access then."),
                 A("click", target="e1"), A("finish", result="Netflix membership cancelled, ends 5 Nov.")]


def texts(msgs) -> list[str]:  # noqa: ANN001
    return [m.text or "" for m in msgs]


async def world(media_world, tmp_path: Path, script=None, pages=None, **kw):  # noqa: ANN001, ANN201
    w = await media_world(approach_planner_enabled=True, browser_agent_enabled=True, browser_agent_dir=str(tmp_path), **kw)

    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    pipe = w.runtime.pipeline
    pipe._reply_lang = lang
    browser = FakeBrowser(pages or NF_PAGES)
    llm = ScriptedLLM(script if script is not None else list(CANCEL_SCRIPT))
    gw = build_agent(pipe, provider=FakeProvider(browser), llm=llm)
    assert isinstance(gw, BrowserAgentGateway)
    gw.sync = True
    pipe.browser_agent = gw
    return w, gw, browser, llm


def test_site_and_task_signals():
    assert sg.browser_task("cancel my Netflix subscription")
    assert sg.browser_task("apply for this job https://jobs.example.com/x")
    assert sg.browser_task("download my October bill from example-telecom.com")
    assert sg.browser_task("check my booking status")
    assert not sg.browser_task("check the price of atta on zepto")
    assert not sg.browser_task("what is the capital of France")
    assert domains_from_text("cancel my Netflix subscription") == (["netflix.com"], "https://netflix.com/")
    assert domains_from_text("read prices on https://shop.example.in/phones?x=1")[0] == ["shop.example.in"]
    assert domains_from_text("do it on example.com")[0] == ["example.com"]
    assert domains_from_text("cancel my subscription")[0] == []


async def test_switch_off_builds_nothing_and_old_flow_runs(media_world):
    w = await media_world(approach_planner_enabled=True)
    assert w.runtime.pipeline.browser_agent is None
    await w.say("cancel my Netflix subscription")
    assert w.runtime.pipeline.planner.connectors() == frozenset()  # no browser-agent connector: the planner behaves as before


async def test_cancel_subscription_end_to_end_with_confirmation_and_proof(media_world, tmp_path):
    w, gw, browser, llm = await world(media_world, tmp_path)
    out = texts(await w.say("cancel my Netflix subscription"))
    body = "\n".join(out)
    assert "On it" in body and "netflix.com" in body
    assert "Reply YES to go ahead" in body and "ends on 5 Nov" in body
    assert browser.submitted is False
    assert "cancel my Netflix subscription" not in w.brain.seen  # the old chain / brain never saw it
    out2 = "\n".join(texts(await w.say("yes")))
    assert browser.submitted is True and "Done: Netflix membership cancelled" in out2 and "Proof saved" in out2
    proofs = list(tmp_path.glob("proofs/*/*.json"))
    assert len(proofs) == 1 and "netflix.com/done" in json.loads(proofs[0].read_text())["where"]
    # a later unrelated message is not swallowed
    await w.say("what is the capital of France")
    assert w.brain.seen[-1] == "what is the capital of France"


async def test_no_site_named_asks_which_website_then_continues(media_world, tmp_path):
    w, gw, browser, llm = await world(media_world, tmp_path, script=[A("finish", result="read it")])
    out = "\n".join(texts(await w.say("cancel my gym subscription")))
    assert "Which website" in out and llm.prompts == []
    out2 = "\n".join(texts(await w.say("it is netflix.com")))
    assert "On it" in out2 and "Done: read it" in out2
    assert "ALLOWED DOMAINS (fixed): netflix.com" in llm.prompts[0]


async def test_stop_cancels_a_waiting_run_and_a_login_code_is_left_to_the_otp_guard(media_world, tmp_path):
    w, gw, browser, llm = await world(media_world, tmp_path)
    await w.say("cancel my Netflix subscription")  # now waiting for a yes
    out = "\n".join(texts(await w.say("stop")))
    assert "stopped" in out.lower() and browser.submitted is False
    assert gw.agent.store.active_for(w.user.id) is None


async def test_a_secret_in_a_reply_is_refused_and_not_stored(media_world, tmp_path):
    w, gw, browser, llm = await world(media_world, tmp_path)
    await w.say("cancel my Netflix subscription")
    out = "\n".join(texts(await w.say("my card is 4111 1111 1111 1111 go ahead")))
    assert "did not save" in out and browser.submitted is False
    assert gw.agent.store.active_for(w.user.id) is not None


async def test_delete_everything_erases_runs_proofs_and_files(media_world, tmp_path):
    w, gw, browser, llm = await world(media_world, tmp_path)
    await w.say("cancel my Netflix subscription")
    await w.say("yes")
    assert list(tmp_path.glob("proofs/*/*"))
    await gw.forget_user(w.user.id)
    assert not list(tmp_path.glob("proofs/*/*")) and not list(tmp_path.glob("runs/*.json"))


async def test_planner_only_routes_browser_tasks_when_the_agent_is_on(media_world, tmp_path):
    w = await media_world(approach_planner_enabled=True)
    pg = w.runtime.pipeline.planner
    assert "browser_agent" not in pg.connectors()
    w2, gw, _, _ = await world(media_world, tmp_path)
    assert "browser_agent" in w2.runtime.pipeline.planner.connectors()


async def test_a2a_specialist_runs_a_task_and_continues_with_the_answer(media_world, tmp_path):
    from friday.team.wiring import build_team

    w, gw, browser, llm = await world(media_world, tmp_path)
    team = build_team(w.c.settings, w.clock, browser_agent=gw.agent)
    assert "browser_agent" in team.transport.servers
    assert "browser_agent" not in team.servers  # in-process only: never served over HTTP
    client = A2AClient(team.transport, name="pm", depth=0, audit=A2AAudit())
    assert "browser_agent" in await client.agents_with_skill(BROWSER_SKILL)
    t = await client.delegate("browser_agent", data={"goal": "cancel my Netflix subscription", "domains": ["netflix.com"], "user_id": w.user.id, "start_url": NF, "lang": "en"})
    assert t.state == TaskState.INPUT_REQUIRED and "YES" in t.status_text()
    t2 = await client.delegate("browser_agent", text="yes", task_id=t.id)
    assert t2.state == TaskState.COMPLETED and t2.result_data()["status"] == "done" and browser.submitted
    # missing input is asked for, not guessed
    t3 = await client.delegate("browser_agent", data={"goal": "x"})
    assert t3.state == TaskState.INPUT_REQUIRED


def test_doctor_lines_and_switch_names(tmp_path):
    from friday.browser_agent.doctor import check
    from friday.core.config import Settings

    s = Settings(_env_file=None, mode="simulator", env="test", database_url="sqlite+aiosqlite:///:memory:")
    assert s.browser_agent_enabled is False and s.job_apply_enabled is False  # default OFF
    lines = check(s)
    assert lines[0][0] == "ok" and "off" in lines[0][1] and "no pay / sign / account-creation tool" in lines[0][1]
    s2 = Settings(_env_file=None, mode="simulator", env="test", database_url="sqlite+aiosqlite:///:memory:", job_apply_enabled=True)
    assert any(st == "warn" and "browser agent is off" in m for st, m in check(s2))
    script = Path(__file__).parents[2] / "deploy" / "enable-web-test.sh"
    txt = script.read_text()
    assert '"FRIDAY_BROWSER_AGENT_ENABLED", "FRIDAY_JOB_APPLY_ENABLED"' in txt
