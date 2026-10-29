# ruff: noqa: E501
"""The step runner on fakes only: scripted fake grocery pages + scripted model + fake OTP channel + real browser-agent loop."""

from __future__ import annotations

import logging
import re

from friday.steps import validate
from friday.steps.planner import StepPlanner
from friday.steps.store import JsonPlanStore
from friday.steps.types import Status, Step, StepPlan, StepType
from tests.browser_agent.fakes import A
from tests.steps.world import (
    CODE,
    LOGIN_ENTER,
    LOGIN_ENTER_BAD,
    LOGIN_REQ,
    OPEN_FREE,
    OPEN_WALL,
    READ_NONE,
    READ_OK,
    SEARCH_BAD_AREA,
    SEARCH_OK,
    SEARCH_WALL,
    Z,
    make_world,
    pages,
)

ASK = "price of atta on zepto"


def step_lines(w) -> list[str]:  # noqa: ANN001
    return [s for s in w.sent if re.match(r"Step \d+ of \d+:", s)]


# ----------------------------------------------------------------------------- plan before the browser
async def test_price_check_plan_is_explicit_and_built_before_the_browser():
    plan = await StepPlanner().plan("price of aashirvaad atta 5 kg on zepto")
    assert plan is not None and plan.playbook == "price_check" and plan.source == "data"
    assert [s.type for s in plan.steps] == [StepType.OPEN_SITE, StepType.NEED_AREA, StepType.NEED_LOGIN, StepType.SEARCH, StepType.READ_RESULTS,
                                            StepType.MATCH_VARIANT, StepType.COMPARE_AND_SUGGEST, StepType.REPORT]
    assert plan.domains[0] == "zepto.com" and plan.start_url == "https://zepto.com/"
    assert plan.slots["category"] == "atta" and plan.slots["pack"] == "5 kg" and plan.slots["brand"] == "aashirvaad"
    assert validate.problems(plan) == []


async def test_other_playbooks_plan_and_need_a_site():
    p = StepPlanner()
    cancel = await p.plan("cancel my netflix subscription")
    assert cancel is not None and [s.type for s in cancel.steps] == [StepType.OPEN_SITE, StepType.NEED_LOGIN, StepType.NAVIGATE, StepType.READ_STATUS, StepType.ACT_CONFIRMED, StepType.REPORT]
    form = await p.plan("fill out the application form on https://forms.example.com/apply")
    assert form is not None and form.playbook == "fill_form_preview" and StepType.FILL_PREVIEW in [s.type for s in form.steps]
    track = await p.plan("track my order on zepto")
    assert track is not None and track.playbook == "track_order"
    assert await p.plan("cancel my subscription") is None  # no site: the old flow asks which one
    assert await p.plan("what is the capital of France") is None


def test_validation_rejects_payment_sign_unknown_and_bad_shapes():
    base = dict(playbook="llm", goal="g", domains=["zepto.com"], start_url="https://zepto.com/")
    ok = [Step(type=StepType.OPEN_SITE), Step(type=StepType.REPORT)]
    assert validate.is_valid(StepPlan(steps=ok, **base))
    for bad_text in ("pay the bill", "go to checkout", "enter card details", "place order now", "e-sign the form", "create an account", "UPI payment"):
        steps = [Step(type=StepType.OPEN_SITE), Step(type=StepType.NAVIGATE, args={"target": bad_text}), Step(type=StepType.REPORT)]
        assert validate.problems(StepPlan(steps=steps, **base)), bad_text
    assert validate.problems(StepPlan(steps=[Step(type=StepType.NAVIGATE), Step(type=StepType.REPORT)], **base))  # must start with open_site
    assert validate.problems(StepPlan(steps=[Step(type=StepType.OPEN_SITE)], **base))  # must end with report
    assert validate.problems(StepPlan(steps=ok, **{**base, "domains": ["uidai.gov.in"]}))  # bank/ID hosts are never opened
    assert validate.parse_steps({"steps": [{"type": "pay_now"}]}) is None  # unknown step type: the closed schema refuses it
    assert validate.parse_steps({"steps": [{"type": "open_site", "args": {"a": 3}}]}) is None
    assert not [t for t in StepType if t.value in ("pay", "payment", "checkout", "sign", "create_account")]


class FakePlanLLM:
    def __init__(self, *raws) -> None:  # noqa: ANN002
        self.raws, self.calls = list(raws), []

    async def propose(self, **kw):  # noqa: ANN003, ANN201
        self.calls.append(kw)
        return self.raws.pop(0) if self.raws else {"steps": []}


async def test_llm_fallback_must_emit_the_closed_schema_and_never_a_payment_step():
    text = "download my October bill from example-telecom.com"
    good = {"steps": [{"type": "open_site", "title": "open", "args": {}}, {"type": "navigate", "title": "bills", "args": {"target": "billing history"}},
                      {"type": "read_status", "title": "latest", "args": {}}, {"type": "report", "title": "tell", "args": {}}]}
    plan = await StepPlanner(FakePlanLLM(good)).plan(text)
    assert plan is not None and plan.source == "llm" and plan.domains == ["example-telecom.com"]
    pay = {"steps": [{"type": "open_site"}, {"type": "navigate", "args": {"target": "pay the bill with my card"}}, {"type": "report"}]}
    assert await StepPlanner(FakePlanLLM(pay)).plan(text) is None
    assert await StepPlanner(FakePlanLLM({"steps": [{"type": "make_payment"}]})).plan(text) is None
    assert await StepPlanner(FakePlanLLM({"steps": "nope"})).plan(text) is None
    assert await StepPlanner(None).plan(text) is None
    assert await StepPlanner(FakePlanLLM(good)).plan("what is the capital of France") is None  # no site from the user's words: no plan


# ----------------------------------------------------------------------------- the atta example end to end
async def test_atta_price_area_saved_no_question_main_variants_suggestions_and_recommendation():
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_OK, saved={"home": "560034"})
    assert await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.DONE and st.area == "560034"
    assert w.browser.typed() == ["560034", "atta"]  # the saved area reached the site's location box; nothing else typed
    lines = step_lines(w)
    assert [re.sub(r"\d+ of \d+", "N", s) for s in lines][:1] == ["Step N: opening zepto.com"]
    assert lines[0].startswith("Step 1 of 4:") and lines[1].startswith("Step 2 of 4:") and lines[-1].startswith("Step 4 of 4:")
    assert not any("area" in s.lower() and "?" in s for s in w.sent)  # saved place: the area is never asked
    assert not [r for r in st.records if r.type == "need_area" and r.state == "done"] and [r.note for r in st.records if r.type == "need_area"] == ["area known"]
    assert [r.note for r in st.records if r.type == "need_login"] == ["no login wall"]
    report = w.last()
    assert "atta on Zepto (560034)" in report and "Main variants:" in report
    assert report.count("Rs 262") == 1 and "Pillsbury Chakki Fresh Atta" in report and "/kg" in report
    assert "Other popular atta brands:" in report and "My pick:" in report and "lowest price per kg" in report  # friday/shopping compare + recommend, reused
    assert "Proof: 2 screenshot(s) saved" in report
    assert st.records[-1].type == "report" and all(r.state in ("done", "skipped") for r in st.records)


async def test_area_unknown_asks_once_at_that_step_then_continues_after_the_answer():
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_OK)
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_USER and st.awaiting.kind == "area" and st.idx == 1
    assert w.last().startswith("Step 2 of 5:") and "Home or PG?" in w.last() and w.last().count("?") == 1
    assert w.browser.typed() == []  # nothing was typed before the answer
    asked_before = len(w.sent)
    assert await w.runner.handle_reply("u1", "PG, Koramangala 560034")
    assert w.plan().status == Status.DONE and w.plan().area == "560034"
    assert w.browser.typed()[0] == "560034"
    assert len(w.sent) > asked_before and w.users.saved["pg"] == "560034"  # the answer is saved as a place for next time


async def test_area_reply_that_is_not_an_area_is_asked_again_then_stops_plainly():
    w = make_world(pages(), OPEN_FREE)
    await w.runner.start("u1", ASK, "en")
    for _ in range(3):
        await w.runner.handle_reply("u1", "hmm ok")
    assert w.plan().status == Status.BLOCKED
    assert "I stopped at step" in w.last() and "Nothing was submitted or changed." in w.last()


async def test_site_that_does_not_accept_the_area_asks_for_another_one_and_searches_again():
    w = make_world(pages(), OPEN_FREE, SEARCH_BAD_AREA, SEARCH_OK, READ_OK, saved={"home": "999999"})
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_USER and "did not accept" in w.last() and st.idx == 3
    await w.runner.handle_reply("u1", "560034")
    assert w.plan().status == Status.DONE and w.browser.typed().count("560034") == 1


async def test_variant_given_shows_that_one_only_and_variant_not_seen_says_so():
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_OK, saved={"home": "560034"})
    await w.runner.start("u1", "price of aashirvaad atta 5 kg on zepto", "en")
    rep = w.last()
    assert "Your variant (aashirvaad 5 kg):" in rep and "1. Aashirvaad Select Whole Wheat Atta 5 kg: Rs 289" in rep and "Rs 540" not in rep and "Pillsbury Chakki Fresh Atta 5 kg: Rs 262" not in rep.split("Other popular")[0]
    w2 = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_OK, saved={"home": "560034"})
    await w2.runner.start("u1", "price of annapurna atta on zepto", "en")
    rep2 = w2.last()
    assert "I could not see annapurna" in rep2 and "Main variants" not in rep2 and "1. " in rep2 and "My pick:" in rep2


# ----------------------------------------------------------------------------- login wall, OTP
def no_secret_anywhere(w, caplog=None) -> None:  # noqa: ANN001
    blobs = [*w.sent, *(p.model_dump_json() for p in w.plans._all()), *w.rig.llm.prompts, repr(w.audit), repr(w.rig.log.events if hasattr(w.rig.log, "events") else w.rig.log)]
    if caplog is not None:
        blobs.append(caplog.text)
    for b in blobs:
        assert CODE not in b


async def test_login_wall_asks_otp_on_same_number_then_enters_it_once_and_continues(caplog):
    caplog.set_level(logging.DEBUG)
    w = make_world(pages(login_wall=True), OPEN_WALL, LOGIN_REQ, LOGIN_ENTER, SEARCH_OK, READ_OK, saved={"home": "560034"})
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_OTP and st.login_wall
    ask = next(s for s in w.sent if "OTP" in s)
    assert "number ending 42" in ask and "Send it here and I will enter it" in ask and "Zepto" in ask and PHONE_NOT_IN(ask)
    assert w.otp.armed == [("u1", "zepto", st.id)]  # the guarded chat path is armed for this user, this site, this plan
    assert w.browser.typed() == ["+919800000042"]  # only the phone number was typed so far
    # a bare code in chat is not ours (the guarded flow stores it, redacts the transcript); a "done" with no code yet is a nudge
    assert await w.runner.handle_reply("u1", CODE) is False and await w.runner.handle_reply("u1", f"my otp is {CODE}") is False
    assert await w.runner.handle_reply("u1", "sent") and "waiting for the OTP" in w.last()
    n = len(w.browser.log)
    w.otp.send(st.id)  # the guarded flow stored the code
    assert await w.runner.tick() == 1
    assert len(w.browser.log) > n and CODE in w.browser.typed()  # typed into the page's code field and nowhere else
    st = w.plan()
    assert st.status == Status.DONE and st.logged_in
    assert not w.otp.ready(st.id) and st.id in w.otp.wiped  # single use
    assert w.otp.take_otp(st.id) is None
    assert [r.state for r in st.records if r.type == "need_login"] == ["done"]
    assert any(s.startswith("Step 2 of") and "OTP" in s for s in w.sent)
    no_secret_anywhere(w, caplog)


async def test_login_wall_found_only_when_searching_goes_back_to_login_once():
    w = make_world(pages(), OPEN_FREE, SEARCH_WALL, LOGIN_REQ, LOGIN_ENTER, SEARCH_OK, READ_OK, saved={"home": "560034"})
    w.browser.pages[Z] = pages(login_wall=True)[Z]  # the home page turns out to be a login screen
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_OTP and st.login_wall
    w.otp.send(st.id)
    await w.runner.tick()
    assert w.plan().status == Status.DONE and w.plan().logged_in


async def test_already_logged_in_skips_the_otp_step():
    w = make_world(pages(), OPEN_WALL, SEARCH_OK, READ_OK, saved={"home": "560034"})
    plan = await w.runner.planner.plan(ASK)
    from friday.steps.store import new_plan_id
    from friday.steps.types import PlanState

    st = PlanState(id=new_plan_id(), user_id="u1", lang="en", plan=plan, area="560034", logged_in=True, login_wall=True)
    assert w.runner._skip(st, plan.steps[2]) == "already logged in"


async def test_no_otp_arrives_offers_one_resend_then_gives_up_plainly():
    w = make_world(pages(login_wall=True), OPEN_WALL, LOGIN_REQ, LOGIN_REQ, saved={"home": "560034"})
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_OTP
    w.rig.clock.advance(seconds=200)
    assert await w.runner.tick() == 0  # still inside the 5 minutes
    w.rig.clock.advance(seconds=150)
    assert await w.runner.tick() == 1
    assert w.plan().status == Status.WAITING_USER and "send it again" in w.last()
    assert await w.runner.handle_reply("u1", "maybe") and "YES or NO" in w.last()
    await w.runner.handle_reply("u1", "yes")
    assert w.plan().status == Status.WAITING_OTP and w.plan().resends == 1
    w.rig.clock.advance(seconds=400)
    await w.runner.tick()
    st = w.plan()
    assert st.status == Status.BLOCKED and "OTP never arrived" in w.last() and "Nothing was submitted or changed." in w.last()  # only ONE resend is offered


async def test_wrong_code_asks_for_the_newest_one_once_then_stops():
    w = make_world(pages(login_wall=True), OPEN_WALL, LOGIN_REQ, LOGIN_ENTER_BAD, LOGIN_ENTER_BAD, saved={"home": "560034"})
    await w.runner.start("u1", ASK, "en")
    sid = w.plan().id
    w.otp.send(sid)
    await w.runner.tick()
    assert w.plan().status == Status.WAITING_OTP and "did not work" in w.last()
    w.otp.send(sid)
    await w.runner.tick()
    assert w.plan().status == Status.BLOCKED and "login" in w.last()


async def test_login_cannot_be_taken_safely_stops_with_a_plain_message():
    w = make_world(pages(login_wall=True), OPEN_WALL, saved={"home": "560034"}, otp=False)
    await w.runner.start("u1", ASK, "en")
    assert w.plan().status == Status.BLOCKED and "I cannot take a login code safely here" in w.last()
    assert "I stopped at step" in w.last() and "open zepto.com" in w.last() and "Nothing was submitted or changed." in w.last()


# ----------------------------------------------------------------------------- stops and the policy layer
async def test_blocked_site_stops_with_a_plain_message_and_offers_public_web_prices():
    w = make_world(pages(captcha=True), [A("finish", result="never reached")], saved={"home": "560034"}, fallback=True)
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.WAITING_USER and st.awaiting.kind == "fallback"
    assert "I stopped at step 1" in w.last() and "blocking automatic browsing" in w.last() and "compare public web prices for atta" in w.last()
    await w.runner.handle_reply("u1", "yes")
    assert w.last() == "FALLBACK:web-prices-for-atta" and w.plan().status == Status.BLOCKED


async def test_blocked_without_a_fallback_offers_the_manual_page_and_says_nothing_changed():
    w = make_world(pages(captcha=True), [A("finish", result="never reached")], saved={"home": "560034"})
    await w.runner.start("u1", ASK, "en")
    assert w.plan().status == Status.BLOCKED and "open zepto.com" in w.last() and "Nothing was submitted or changed." in w.last()


async def test_payment_step_is_a_hard_stop_in_the_policy_layer_with_no_fallback_offer():
    w = make_world(pages(payment_on_results=True), OPEN_FREE, SEARCH_OK, saved={"home": "560034"}, fallback=True)
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.BLOCKED and "never pay" in w.last() and "compare public" not in w.last()
    assert w.browser.typed() == ["560034", "atta"]


async def test_unreadable_results_retry_once_with_a_hint_then_stop():
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_NONE, READ_OK, saved={"home": "560034"})
    await w.runner.start("u1", ASK, "en")
    assert w.plan().status == Status.DONE and w.plan().replans == 1
    assert any("second try" in p for p in w.rig.llm.prompts)
    w2 = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_NONE, READ_NONE, READ_NONE, saved={"home": "560034"})
    await w2.runner.start("u1", ASK, "en")
    assert w2.plan().status == Status.BLOCKED and "could not see a price" in w2.last()


async def test_replan_with_the_model_replaces_the_tail_in_the_closed_schema_only():
    tail = {"steps": [{"type": "read_results", "title": "again", "args": {}}, {"type": "match_variant"}, {"type": "report"}]}
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_NONE, READ_OK, saved={"home": "560034"}, planner_llm=FakePlanLLM(tail))
    await w.runner.start("u1", ASK, "en")
    st = w.plan()
    assert st.status == Status.DONE and st.plan.source == "llm" and [s.type for s in st.plan.steps][-3:] == [StepType.READ_RESULTS, StepType.MATCH_VARIANT, StepType.REPORT]
    bad = {"steps": [{"type": "read_results"}, {"type": "navigate", "args": {"target": "checkout and pay"}}, {"type": "report"}]}
    w2 = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_NONE, READ_OK, saved={"home": "560034"}, planner_llm=FakePlanLLM(bad))
    await w2.runner.start("u1", ASK, "en")
    assert w2.plan().plan.source == "data"  # the invalid model plan was refused; the data plan retried the step


async def test_cancel_and_stop():
    w = make_world(pages(), OPEN_FREE)
    await w.runner.start("u1", ASK, "en")
    assert await w.runner.handle_reply("u1", "stop")
    assert w.plan().status == Status.CANCELLED and "Nothing was submitted" in w.last()
    assert await w.runner.handle_reply("u1", "hello") is False  # nothing open any more


# ----------------------------------------------------------------------------- restart / resume
async def test_restart_resumes_a_plan_that_waits_for_the_user_and_one_that_was_interrupted(tmp_path):
    store = JsonPlanStore(tmp_path)
    w = make_world(pages(), OPEN_FREE, SEARCH_OK, READ_OK, plans=store)
    await w.runner.start("u1", ASK, "en")
    pid = w.plan().id
    assert w.plan().status == Status.WAITING_USER
    # new process: new runner, new browser, same plan files on disk
    w2 = make_world(pages(), SEARCH_OK, READ_OK, plans=JsonPlanStore(tmp_path))
    assert w2.runner.has_open("u1")
    await w2.runner.handle_reply("u1", "Home 560034")
    done = w2.plans.load(pid)
    assert done.status == Status.DONE and done.area == "560034"
    assert [r.type for r in done.records][0] == "open_site"  # the first step was not repeated
    assert not any("STEP: open and look" in p for p in w2.rig.llm.prompts)  # no second 'open the site' step
    # a process that died in the middle: status RUNNING at a saved step
    w3 = make_world(pages(), SEARCH_OK, READ_OK)
    plan = await w3.runner.planner.plan(ASK)
    from friday.steps.store import new_plan_id
    from friday.steps.types import PlanState

    st = PlanState(id=new_plan_id(), user_id="u1", lang="en", plan=plan, area="560034", idx=3, created_at=w3.runner._iso(), updated_at=w3.runner._iso())
    w3.plans.save(st)
    w3.rig.clock.advance(seconds=30)
    assert await w3.runner.tick() == 1
    assert w3.plans.load(st.id).status == Status.DONE


async def test_questions_that_go_unanswered_expire_politely():
    w = make_world(pages(), OPEN_FREE)
    await w.runner.start("u1", ASK, "en")
    w.rig.clock.advance(hours=7)
    assert await w.runner.tick() == 1
    assert w.plan().status == Status.EXPIRED and "Nothing was submitted" in w.last()


async def test_busy_browser_is_retried_later_not_lost():
    w = make_world(pages(), saved={"home": "560034"})
    w.rig.provider.busy = "no memory"
    await w.runner.start("u1", ASK, "en")
    assert w.plan().status == Status.WAITING_BUSY and "browser is busy" in w.last()
    w.rig.provider.busy = ""
    w.feed(OPEN_FREE, SEARCH_OK, READ_OK)
    w.rig.clock.advance(seconds=70)
    await w.runner.tick()
    assert w.plan().status == Status.DONE


# ----------------------------------------------------------------------------- the loop inside a step may ask; other playbooks
async def test_irreversible_step_asks_the_user_through_the_loop_and_continues_after_the_answer():
    from tests.browser_agent.fakes import FakePageSpec

    nf = "https://netflix.com/"
    pg = {
        nf: FakePageSpec("Account", "Your plan: Standard. Next bill 5 Nov.", [{"name": "Cancel membership", "role": "link", "goes_to": nf + "cancel"}]),
        nf + "cancel": FakePageSpec("Cancel", "Your plan ends on 5 Nov if you cancel.", [{"name": "Finish cancellation", "role": "button", "submit": True, "goes_to": nf + "done", "submit_marks": True}]),
        nf + "done": FakePageSpec("Cancelled", "Your membership is cancelled."),
    }
    open_s = [A("finish", result="login_wall=no; location_prompt=no; Netflix account page")]
    nav = [A("finish", result="account page")]
    status = [A("finish", result="Standard plan, ends 5 Nov")]
    act = [A("click", target="e1"), A("request_confirmation", summary="Cancel your Netflix membership. It ends on 5 Nov."), A("click", target="e1"), A("finish", result="Membership cancelled, ends 5 Nov.")]
    w = make_world(pg, open_s, nav, status, act, suggest=False)
    await w.runner.start("u1", "cancel my netflix subscription", "en")
    st = w.plan()
    assert st.status == Status.WAITING_AGENT and "Reply YES" in w.last() and not w.browser.submitted
    await w.runner.handle_reply("u1", "yes")
    st = w.plan()
    assert st.status == Status.DONE and w.browser.submitted and "cancelled" in w.last().lower()
    assert [r.type for r in st.records] == ["open_site", "need_login", "navigate", "read_status", "act_confirmed", "report"]
    # saying no at the confirmation ends it and nothing is submitted
    w2 = make_world(pg, open_s, nav, status, act, suggest=False)
    await w2.runner.start("u1", "cancel my netflix subscription", "en")
    await w2.runner.handle_reply("u1", "no")
    assert not w2.browser.submitted and w2.plan().status in (Status.BLOCKED, Status.FAILED, Status.RUNNING, Status.DONE) and not w2.browser.submitted


# ----------------------------------------------------------------------------- helpers
def PHONE_NOT_IN(text: str) -> bool:
    return "9800000042" not in text and "+91" not in text
