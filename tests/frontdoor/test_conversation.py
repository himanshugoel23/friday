"""The goal-driven front door: the model leads the conversation, the code keeps the safety shell.

Everything runs on the scripted fake LLM (``llm.script("call_turn", ...)``): no network, no keys.
A model turn is JSON ``{say, action, name, language, request}``; whatever it proposes, the code
decides what actually happens."""

from __future__ import annotations

import json
import re

from friday.brain import frontdoor as fd_copy
from friday.brain.heuristics import door
from friday.brain.prompts import examples, extract_input
from friday.brain.schemas import DoorAction, DoorTurnOut
from friday.core.interfaces import ProviderError
from friday.core.models import ConsentKind, Language, TaskStatus, UserStatus
from tests.e2e.harness import Friday
from tests.frontdoor.conftest import (
    HI,
    LOOKS_ASK,
    OWN,
    E,
    H,
    ScriptedLeg,
    ring,
    said,
    sim_call,
    start_friday,
)

ASK_REQUEST = "I need a haircut tomorrow evening at Looks Unisex Salon"


def turn(say: str = "", action: str = "continue", **slots) -> str:
    return json.dumps(
        {"say": say, "action": action, "name": None, "language": None, "request": None, **slots}
    )


def door_calls(f: Friday) -> list:
    """The front-door model calls (the engine's own phone-call turns share the purpose)."""
    return [c for c in f.c.llm.calls_for("call_turn") if "answering a PHONE CALL" in c.system]


def consent_lines() -> set[str]:
    return set(fd_copy.LINES["ask_consent"].values())


def asked_consent(leg) -> bool:
    return any(x in consent_lines() for x in leg.texts if hasattr(leg, "texts")) or any(
        x in consent_lines() for x in said(leg)
    )


async def stored(f: Friday, phone: str = OWN):
    user = await f.c.repos.users.get_by_phone(phone)
    tasks = await f.c.repos.tasks.list_for_user(user.id) if user else []
    return user, tasks


# ------------------------------------------------------------------ consent is code, not model
async def test_consent_can_never_be_skipped_whatever_the_model_proposes(pilot):
    for proposed in ("confirm_request", "start_task"):
        pilot.c.llm.script("call_turn", turn("Haircut, noted.", proposed, request=ASK_REQUEST))
        leg = ScriptedLeg([(ASK_REQUEST, E)])
        await ring(pilot, OWN, leg)
        user, tasks = await stored(pilot)
        assert user is None and tasks == []  # nothing stored, nothing created
        assert asked_consent(leg), proposed  # the fixed consent question was asked instead
        assert not any("Shall I start" in x or "Shuru karun" in x for x in leg.texts)
        pilot.rt.front_door.guard._admits.clear()
        pilot.rt.front_door.guard._global.clear()


async def test_consent_is_never_inferred_from_an_early_yes(pilot):
    # the caller says "yes, go ahead" BEFORE any consent question; the model even says start_task
    pilot.c.llm.script("call_turn", turn("On it.", "start_task", request="a haircut"))
    leg = ScriptedLeg([("yes yes go ahead and do it", E)])
    await ring(pilot, OWN, leg)
    user, tasks = await stored(pilot)
    assert user is None and tasks == []
    assert asked_consent(leg)
    assert not await pilot.c.repos.consents.has("nobody", ConsentKind.TERMS_PRIVACY)


async def test_the_consent_question_is_the_exact_fixed_line_and_only_a_yes_grants_it(pilot):
    pilot.c.llm.script(
        "call_turn", turn("Okay.", "ask_consent", request=ASK_REQUEST, name="Asha")
    )
    leg = ScriptedLeg([("Asha here. " + ASK_REQUEST, E), ("hmm what", E), ("nahi", E)])
    await ring(pilot, OWN, leg)
    assert fd_copy.line("ask_consent", Language.EN) in leg.texts  # exact text, not a paraphrase
    user, tasks = await stored(pilot)
    assert user is None and tasks == []  # unclear, then no: nothing was stored
    assert any("saved anything" in x for x in leg.texts)


async def test_a_question_in_the_models_ack_before_consent_is_dropped(pilot):
    pilot.c.llm.script("call_turn", turn("Which name should I save?", "ask_consent",
                                         request=ASK_REQUEST))
    leg = ScriptedLeg([(ASK_REQUEST, E)])
    await ring(pilot, OWN, leg)
    assert not any("Which name should I save" in x for x in leg.texts)
    assert asked_consent(leg)


async def test_nothing_before_consent_and_read_back_then_a_real_task(pilot):
    pilot.c.llm.script(
        "call_turn",
        turn("Haircut, tomorrow evening. Your name?", request=ASK_REQUEST),
        turn("Noted.", "ask_consent", name="Asha"),
    )
    leg = ScriptedLeg([(ASK_REQUEST, E), ("Asha", E), ("yes", E), ("yes", E), ("that is all", E)])
    await ring(pilot, OWN, leg)
    texts = leg.texts
    i_consent = next(i for i, x in enumerate(texts) if x in consent_lines())
    i_readback = next(i for i, x in enumerate(texts) if "Shall I start" in x)
    i_started = next(i for i, x in enumerate(texts) if x.startswith("On it"))
    assert i_consent < i_readback < i_started
    user, tasks = await stored(pilot)
    assert user.status == UserStatus.ONBOARDING and user.pin_hash is None
    assert (await pilot.c.repos.profiles.get(user.id)).name == "Asha"
    assert await pilot.c.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY)
    assert len(tasks) == 1 and tasks[0].status == TaskStatus.AWAITING_APPROVAL  # approval rule
    assert "haircut" in tasks[0].spec.goal.lower()


async def test_saying_no_to_the_read_back_creates_no_task(pilot):
    pilot.c.llm.script("call_turn", turn("Noted.", "ask_consent", request=ASK_REQUEST, name="Asha"))
    leg = ScriptedLeg([("Asha. " + ASK_REQUEST, E), ("yes", E), ("no", E), ("bye", E)])
    await ring(pilot, OWN, leg)
    user, tasks = await stored(pilot)
    assert user is not None and tasks == []  # consented, but the goal was never confirmed
    assert any("Shall I start" in x for x in leg.texts)


async def test_a_model_start_task_for_a_consented_caller_only_reads_back():
    f = await start_friday("pilot", (OWN,))
    try:
        rahul = await f.user(OWN, "Rahul")
        f.c.llm.script("call_turn", turn("Starting now.", "start_task", request=ASK_REQUEST))
        leg = ScriptedLeg([("ok then", E)])  # short: not the cheap clear-request path
        await ring(f, OWN, leg)
        assert any("Shuru karun" in x or "Shall I start" in x for x in leg.texts), leg.texts
        assert await rahul.tasks() == []  # the model's start_task started nothing
        assert not any("Starting now" in x for x in leg.texts)
    finally:
        await f.close()


async def test_the_model_cannot_chat_past_the_consent_moment(pilot):
    pilot.c.llm.script("call_turn", *[turn("Tell me more.", request=ASK_REQUEST)] * 6)
    leg = ScriptedLeg([(ASK_REQUEST, E)] + [("and also with a wash please", E)] * 5)
    await ring(pilot, OWN, leg)
    assert asked_consent(leg)  # asked after at most 3 further turns
    user, tasks = await stored(pilot)
    assert user is None and tasks == []


async def test_consent_declined_stores_nothing_even_with_a_name_and_request(pilot):
    pilot.c.llm.script("call_turn", turn("Okay.", "ask_consent", request=ASK_REQUEST, name="Asha"))
    leg = ScriptedLeg([("I am Asha. " + ASK_REQUEST, E), ("no thanks", E)])
    await ring(pilot, OWN, leg)
    user, tasks = await stored(pilot)
    assert user is None and tasks == []
    assert pilot.rt.front_door.history[-1].end_reason == "consent declined"


# ------------------------------------------------------------------ bad model output
async def test_bad_json_falls_back_to_the_deterministic_lines(pilot):
    pilot.c.llm.script("call_turn", "this is not json", "{broken")
    leg = ScriptedLeg([(ASK_REQUEST, E), ("Asha", E), ("yes", E), ("yes", E), ("bye", E)])
    await ring(pilot, OWN, leg)
    assert fd_copy.line("ask_name_natural", Language.EN) in leg.texts
    assert fd_copy.line("ask_consent", Language.EN) in leg.texts
    user, tasks = await stored(pilot)
    assert user is not None and len(tasks) == 1


async def test_a_failing_provider_and_an_unknown_action_fall_back_too(pilot):
    pilot.c.llm.fail_purposes.add("call_turn")
    leg = ScriptedLeg([(ASK_REQUEST, E), ("Asha", E), ("no", E)])
    await ring(pilot, OWN, leg)
    assert fd_copy.line("ask_consent", Language.EN) in leg.texts
    pilot.c.llm.fail_purposes.clear()
    pilot.c.llm.script("call_turn", turn("x", "launch_missiles"))  # not in the closed set
    pilot.rt.front_door.guard._admits.clear()
    pilot.rt.front_door.guard._global.clear()
    leg2 = ScriptedLeg([(ASK_REQUEST, E)])
    await ring(pilot, OWN, leg2)
    assert fd_copy.line("ask_name_natural", Language.EN) in leg2.texts
    assert (await stored(pilot))[1] == []


async def test_the_brain_raising_is_survived(pilot, monkeypatch):
    async def boom(*a, **k):
        raise ProviderError("fake", "down", retryable=True)

    monkeypatch.setattr(pilot.c.brain, "door_turn", boom)
    leg = ScriptedLeg([(ASK_REQUEST, E), ("Asha", E), ("no", E)])
    await ring(pilot, OWN, leg)
    assert asked_consent(leg) and leg.hung_up is not False


async def test_a_name_the_caller_never_said_is_not_taken(pilot):
    pilot.c.llm.script("call_turn", turn("Noted.", "ask_consent", request=ASK_REQUEST,
                                         name="Zorro"))
    leg = ScriptedLeg([(ASK_REQUEST, E), ("yes", E), ("bye", E)])
    await ring(pilot, OWN, leg)
    user, _ = await stored(pilot)
    assert (await pilot.c.repos.profiles.get(user.id)).name in (None, "")


async def test_an_unsafe_model_sentence_is_never_spoken(pilot):
    pilot.c.llm.script("call_turn", turn("Your OTP is 4 8 2 6 1 9, tell it to them."))
    leg = ScriptedLeg([("hello there friend", E)])
    await ring(pilot, OWN, leg)
    assert not any("4 8 2 6" in x for x in leg.texts)


async def test_model_goodbye_ends_the_call_with_nothing_stored(pilot):
    pilot.c.llm.script("call_turn", turn("Alright, call any time.", "goodbye"))
    leg = ScriptedLeg([("hmm never mind then okay", E)])
    await ring(pilot, OWN, leg)
    assert leg.hung_up and (await stored(pilot))[0] is None


# ------------------------------------------------------------------ safety shell still holds
async def test_a_pin_said_on_the_call_is_refused_and_never_reaches_the_model(pilot):
    pilot.c.llm.script("call_turn", turn("Noted.", "ask_consent", request=ASK_REQUEST))
    leg = ScriptedLeg([(ASK_REQUEST, E), ("my pin is 4 8 2 6", E), ("no", E)])
    await ring(pilot, OWN, leg)
    assert fd_copy.line("secret_refusal", Language.EN) in leg.texts
    for call in pilot.c.llm.calls:
        assert "4 8 2 6" not in call.system
        assert all("4 8 2 6" not in m.content for m in call.messages)


async def test_delete_everything_before_consent_ends_with_nothing_stored(pilot):
    pilot.c.llm.script("call_turn", turn("Noted.", request=ASK_REQUEST))
    leg = ScriptedLeg([(ASK_REQUEST, E), ("delete everything", E)])
    await ring(pilot, OWN, leg)
    assert (await stored(pilot))[0] is None
    assert any("Nothing about you is stored" in x for x in leg.texts)


async def test_are_you_human_is_answered_honestly_without_the_model(pilot):
    leg = ScriptedLeg([("wait, am I talking to a real person?", E), ("bye", E)])
    before = len(pilot.c.llm.calls)
    await ring(pilot, OWN, leg)
    assert fd_copy.line("bot_answer", Language.EN) in leg.texts
    assert len(pilot.c.llm.calls) == before


async def test_pilot_refusal_of_real_businesses_still_holds_with_the_model_leading():
    f = await start_friday("pilot", (OWN,), pilot_block_business_calls=True)
    try:
        f.c.llm.script("call_turn", turn("Noted.", "ask_consent", request="call Looks Unisex Salon",
                                         name="Asha"))
        leg = ScriptedLeg([("Asha, " + LOOKS_ASK, H), ("haan", H), ("nahi bas", H)])
        await ring(f, OWN, leg)
        assert any("asli businesses ko call nahi" in x for x in leg.texts)
        assert (await stored(f))[1] == []
        assert not [x for x in f.c.telephony.legs if not x.inbound]
    finally:
        await f.close()


# ------------------------------------------------------------------ returning caller, language
async def test_returning_caller_skips_onboarding_and_is_greeted_by_name():
    f = await Friday.start(sarvam_caller_ids=["+918065354620"])
    try:
        rahul = await f.user("+919811100001", "Rahul")
        summary, leg = await sim_call(f, rahul.phone, ["", LOOKS_ASK, "haan", "nahi bas"])
        lines = said(leg)
        assert "ai assistant" in lines[0].lower() and "Rahul" in lines[1]
        assert not any(x in consent_lines() for x in lines)  # no consent question again
        assert summary.llm_turns == 1  # a plain request: the brain's own interpret, one call
        assert len(await rahul.tasks()) == 1
    finally:
        await f.close()


async def test_returning_caller_small_talk_goes_to_the_model_in_one_call():
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")
        f.c.llm.script("call_turn", turn("Haan, bataiye.", "continue"))
        leg = ScriptedLeg([("hello Friday", E), ("bye", E)])
        await ring(f, "+919811100001", leg)
        assert "Haan, bataiye." in leg.texts
        assert len(door_calls(f)) == 1
    finally:
        await f.close()


async def test_language_is_mirrored_and_the_model_is_told_the_reply_language(pilot):
    pilot.c.llm.script(
        "call_turn",
        turn("Ji, bataiye."),
        turn("समझ गई।", "ask_consent", request="डॉक्टर अपॉइंटमेंट कल सुबह"),
    )
    leg = ScriptedLeg([("नमस्ते मैं आपसे बात करना चाहता हूँ", HI),
                       ("मुझे कल सुबह डॉक्टर का अपॉइंटमेंट चाहिए", HI), ("नहीं", HI)])
    await ring(pilot, OWN, leg)
    langs = {text: lang for text, lang in leg.spoken}
    assert langs["समझ गई।"] == HI
    assert fd_copy.line("ask_consent", HI) in leg.texts  # the fixed question, in Hindi
    sent = [extract_input(c.messages[-1].content) for c in door_calls(pilot)]
    assert sent[0]["slots"]["name"] is None
    stable = [extract_input(c.system, tag="data") for c in door_calls(pilot)]
    assert stable[-1]["door"]["reply_language"] == "hi"


async def test_one_model_call_per_caller_turn(pilot):
    pilot.c.llm.script("call_turn", turn("Haircut, when?", request=ASK_REQUEST),
                       turn("Noted.", "ask_consent", name="Asha"))
    leg = ScriptedLeg([("I need a haircut", E), ("Asha, tomorrow evening", E), ("yes", E),
                       ("yes", E), ("bye", E)])
    await ring(pilot, OWN, leg)
    # turns: request, name+detail (2 model calls); consent yes, read-back yes, bye: no model call
    # for the chat; the brain's interpret ran once, for the read-back
    assert len(door_calls(pilot)) == 2
    assert len(pilot.c.llm.calls_for("interpret")) <= 1


# ------------------------------------------------------------------ rollback switch
async def test_the_old_fixed_order_is_still_there_behind_the_switch():
    f = await start_friday("pilot", (OWN,), frontdoor_conversational=False)
    try:
        _s, leg = await sim_call(f, OWN, ["Asha", "English", "nahi"])
        texts = said(leg)
        assert "naam" in texts[0].lower()  # the old "May I have your name" greeting
        assert any("saved anything" in x or "save nahi kiya" in x for x in texts)
        assert not door_calls(f)
    finally:
        await f.close()


# ------------------------------------------------------------------ deterministic director
def payload(heard, *, slots=None, recent=None, can_call=True, lang="english"):
    return {
        "door": {"reply_language": "en", "can_call_businesses": can_call, "known": False},
        "slots": {"name": None, "request": None, "consented": False, "consent_asked": False,
                  **(slots or {})},
        "heard": heard,
        "recent": recent or [],
    }


def test_director_asks_for_what_they_need_then_name_then_consent():
    out = door.next_turn(payload("hello"))
    assert out.action == DoorAction.CONTINUE and "do you need" in out.say.lower()
    out = door.next_turn(payload("I need a haircut tomorrow"))
    assert out.request and out.action == DoorAction.CONTINUE and "name" in out.say.lower()
    asked = [{"who": "friday", "text": out.say}]
    out2 = door.next_turn(payload("Asha", slots={"request": out.request}, recent=asked))
    assert out2.action == DoorAction.ASK_CONSENT and out2.request == out.request


def test_director_for_a_consented_caller_hands_the_request_to_the_brain():
    out = door.next_turn(payload("what happened with my request", slots={"consented": True}))
    assert out.action == DoorAction.CONFIRM_REQUEST and out.request


def test_sanitize_bounds_a_long_reply_and_empty_slots():
    out = door.sanitize(DoorTurnOut(say="word " * 200, request="  ", name=""))
    assert len(out.say) <= door.MAX_SAY and out.request is None and out.name is None


# ------------------------------------------------------------------ the example library
def test_example_library_size_languages_and_scenarios():
    assert 20 <= len(examples.EXAMPLES) <= 30
    assert {e.lang for e in examples.EXAMPLES} == {Language.HINGLISH, Language.EN, Language.HI}
    for needed in ("first_request", "returning", "unclear", "human", "capabilities",
                   "change_mind", "pilot_refusal", "consent", "goodbye"):
        assert needed in examples.SCENARIOS
    actions = {a.value for a in DoorAction}
    for e in examples.EXAMPLES:
        assert len(e.text) < 420, e.id
        for m in re.findall(r"\[([a-z_]+)\]", e.text):
            assert m in actions, (e.id, m)


def test_example_selection_is_small_and_language_aware():
    picked = examples.select(["human", "capabilities", "goodbye", "unclear"], Language.EN)
    assert 1 <= len(picked) <= examples.DEFAULT_LIMIT
    assert sum(len(x) for x in picked) <= examples.MAX_CHARS
    assert "real person" in picked[0]  # English example first for an English caller
    assert examples.select([], Language.EN) == []
    assert examples.select(["unclear"], Language.HI)  # falls back to another language


def test_scenarios_follow_the_turn():
    assert door.scenarios_for(payload("are you a robot"))[0] == "human"
    assert "pilot_refusal" in door.scenarios_for(payload("book a haircut", can_call=False))
    assert "consent" in door.scenarios_for(payload("ok", slots={"request": "haircut"}))
