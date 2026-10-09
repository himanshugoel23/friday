"""Inbound front-door flows end to end (simulator telephony, fake LLM, real engine)."""

from __future__ import annotations

import asyncio
import re

import pytest

from friday.core.models import (
    CallerKind,
    CallOutcome,
    ConsentKind,
    Intent,
    Interpretation,
    TaskStatus,
    UserStatus,
)
from tests.e2e.harness import Friday, friday_lines
from tests.frontdoor.conftest import (
    LOOKS_ASK,
    OWN,
    OWN2,
    STRANGER,
    E,
    H,
    ScriptedLeg,
    ring,
    said,
    sim_call,
    start_friday,
)

URBAN = "+918040001013"  # a simworld business that rings Friday back


# ------------------------------------------------------------------ known user
async def test_known_user_is_greeted_by_name_and_the_request_becomes_a_real_task():
    f = await Friday.start(sarvam_caller_ids=["+918065354620"])
    try:
        rahul = await f.user("+919811100001", "Rahul")
        summary, leg = await sim_call(
            f, rahul.phone, ["", LOOKS_ASK, "haan", "nahi bas"]
        )
        lines = said(leg)
        assert "ai assistant" in lines[0].lower()  # the fixed disclosure is the first thing said
        assert "Rahul" in lines[1]  # greeted by name, asked how to help
        assert any("Shuru karun?" in x for x in lines)  # read back before acting
        assert any("call back" in x for x in lines)  # an honest, built promise
        assert summary.kind == CallerKind.USER and summary.llm_turns == 1
        # the REAL task exists with the caller as requester; nothing was committed (approval rule)
        tasks = await rahul.tasks()
        assert len(tasks) == 1 and tasks[0].requester_user_id == (await rahul.user_row()).id
        assert tasks[0].status == TaskStatus.AWAITING_APPROVAL
        for call in await rahul.calls(tasks[0]):
            assert "committed" not in call.collected
        assert leg.ended  # Friday hung up after the goodbye
    finally:
        await f.close()


async def test_result_callback_after_the_task_needs_the_callers_approval():
    f = await Friday.start(sarvam_caller_ids=["+918065354620"])
    try:
        rahul = await f.user("+919811100001", "Rahul")
        await sim_call(f, rahul.phone, ["", LOOKS_ASK, "haan", "nahi bas"])
        await f.settle()
        await f.rt.front_door.results.wait_idle()  # the call-back rings in the background
        placed = [c for c in f.rt.front_door.results.calls if c["placed"]]
        assert [c["stage"] for c in placed] == ["offer"]
        cb = next(x for x in reversed(f.c.telephony.legs) if not x.inbound and x.spoken)
        text = " ".join(t for t, _ in cb.spoken)
        assert "ai assistant" in text.lower() and "Nothing is confirmed" in text.replace(
            "Abhi kuch confirm nahi hua hai", "Nothing is confirmed"
        )
        assert "booked" not in text.replace("have not booked", "")  # never claims a booking
    finally:
        await f.close()


async def test_are_you_a_bot_is_answered_honestly_without_the_llm():
    f = await Friday.start()
    try:
        rahul = await f.user("+919811100001", "Rahul")
        summary, leg = await sim_call(f, rahul.phone, ["", "kya aap ek bot ho?", "nahi bas"])
        assert any("AI assistant" in x and "insaan nahi" in x for x in said(leg))
        assert summary.llm_turns == 0  # a fixed answer, not a model call
        _s2, leg2 = await sim_call(f, rahul.phone, ["", "who are you? what can you do?", "bye"],
                                   lang=E)
        assert any("personal assistant" in x.lower() for x in said(leg2)[2:])
    finally:
        await f.close()


async def test_known_user_cannot_delete_or_read_sensitive_things_by_voice(monkeypatch):
    f = await Friday.start()
    try:
        rahul = await f.user("+919811100001", "Rahul")
        user = await rahul.user_row()
        assert user.pin_hash  # a real account behind a PIN
        _s, leg = await sim_call(f, rahul.phone, ["", "delete everything", "bye"], lang=E)
        assert any("PIN" in x and "WhatsApp" in x for x in said(leg))
        assert (await f.c.repos.users.get_by_phone(rahul.phone)).status == UserStatus.ACTIVE

        async def wants_memory(ctx, msg):
            return Interpretation(intent=Intent.QUERY_MEMORY, reply="Your dentist is Dr Mehta")

        monkeypatch.setattr(f.c.brain, "interpret", wants_memory)
        _s, leg = await sim_call(f, rahul.phone, ["", "what is my dentist's number", "bye"], lang=E)
        lines = said(leg)
        assert any("never take a PIN" in x for x in lines)
        assert not any("Mehta" in x for x in lines)  # nothing from memory is read out
    finally:
        await f.close()


async def test_a_secret_said_on_the_call_never_reaches_the_brain_or_the_transcript():
    f = await Friday.start()
    try:
        rahul = await f.user("+919811100001", "Rahul")
        calls: list[str] = []
        real = f.c.brain.interpret

        async def spy(ctx, msg):
            calls.append(msg.text or "")
            return await real(ctx, msg)

        f.c.brain.interpret = spy
        _s, leg = await sim_call(f, rahul.phone, ["", "mera pin 4 8 2 6 hai", "bye"], lang=E)
        assert not calls
        assert any("do not say any PIN" in x or "PIN, OTP" in x for x in said(leg))
        assert not any("4 8 2 6" in x for x in said(leg))
        summary = f.rt.front_door.history[-1]
        assert summary.llm_turns == 0
    finally:
        await f.close()


# ------------------------------------------------------------------ voice onboarding
async def test_new_allow_listed_caller_is_onboarded_by_voice_without_a_pin(pilot):
    summary, leg = await sim_call(
        pilot, OWN, [LOOKS_ASK, "Asha", "haan", "haan", "nahi bas"]
    )
    lines = said(leg)
    # the disclosure and an open question, NOT a form: the name is not asked up front
    assert "ai assistant" in lines[0].lower() and "naam" not in lines[0].lower()
    assert "kya karna hai" in lines[0].lower()
    assert not any(re.search(r"\bpin\b", x, re.I) for x in lines)  # a PIN is never asked for
    assert summary.onboarded and summary.kind == CallerKind.UNKNOWN
    user = await pilot.c.repos.users.get_by_phone(OWN)
    assert user is not None and user.pin_hash is None
    assert user.status == UserStatus.ONBOARDING  # the PIN is set later, on WhatsApp
    profile = await pilot.c.repos.profiles.get(user.id)
    assert profile.name == "Asha"
    assert await pilot.c.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY)
    assert len(await pilot.c.repos.tasks.list_for_user(user.id)) == 1  # first request done


async def test_declining_consent_stores_nothing(pilot):
    summary, leg = await sim_call(pilot, OWN, [LOOKS_ASK, "Asha", "nahi"])
    assert await pilot.c.repos.users.get_by_phone(OWN) is None
    assert any("saved anything" in x or "save nahi kiya" in x for x in said(leg))
    assert summary.end_reason == "consent declined"


async def test_delete_everything_before_consent_leaves_nothing_behind(pilot):
    _s, leg = await sim_call(
        pilot, OWN, ["I need a haircut tomorrow", "Asha", "delete everything"], lang=E
    )
    assert await pilot.c.repos.users.get_by_phone(OWN) is None
    assert any("Nothing about you is stored" in x or "kuch bhi store nahi" in x
               for x in said(leg))


async def test_delete_everything_right_after_voice_onboarding_erases_the_account(pilot):
    _s, leg = await sim_call(
        pilot, OWN, ["I need a haircut tomorrow", "Asha", "haan", "delete everything"], lang=E
    )
    user = await pilot.c.repos.users.get_by_phone(OWN)
    assert user is None or user.status == UserStatus.DELETED
    assert any("deleted everything" in x or "delete kar diya" in x for x in said(leg))
    assert (await pilot.c.repos.profiles.get(user.id) if user else None) is None


async def test_onboarding_copes_with_noise_and_a_language_in_the_middle(pilot):
    leg = ScriptedLeg(
        [("???", E), ("my name is Priya Nair", E), ("I need a haircut tomorrow evening", E),
         ("yes I agree", E), ("who are you exactly please", E), ("bye", E)]
    )
    await ring(pilot, OWN, leg)
    user = await pilot.c.repos.users.get_by_phone(OWN)
    assert (await pilot.c.repos.profiles.get(user.id)).name == "Priya Nair"
    assert any("Say yes to agree" in x or "haan boliye" in x or "हाँ बोलिए" in x for x in leg.texts)
    assert any("AI personal assistant" in x or "AI पर्सनल" in x for x in leg.texts)


# ------------------------------------------------------------------ pilot honesty
async def test_pilot_refuses_real_business_calls_honestly_and_creates_nothing():
    f = await start_friday("pilot", (OWN,), pilot_block_business_calls=True)
    try:
        summary, leg = await sim_call(
            f, OWN, [LOOKS_ASK, "Asha", "haan", "nahi bas"]
        )
        assert any("cannot phone real businesses yet" in x or "asli businesses ko call nahi" in x
                   for x in said(leg))
        user = await f.c.repos.users.get_by_phone(OWN)
        assert await f.c.repos.tasks.list_for_user(user.id) == []
        assert not [x for x in f.c.telephony.legs if not x.inbound]  # nobody was phoned
        assert not any("call back" in x for x in said(leg))  # and nothing was promised
        assert summary.tasks == []
    finally:
        await f.close()


async def test_the_engine_itself_refuses_to_dial_a_real_business_in_the_pilot():
    from friday.core.models import TaskSpec, TaskType
    from friday.tasks.engine import PILOT_NO_REAL_CALLS

    f = await start_friday("pilot", (OWN,), pilot_block_business_calls=True)
    try:
        await sim_call(f, OWN, ["haircut book karna hai kal", "Asha", "haan", "bye"])
        user = await f.c.repos.users.get_by_phone(OWN)
        spec = TaskSpec(type=TaskType.ENQUIRY, goal="Ask Looks about hours",
                        business_name="Looks Unisex Salon", business_phone="+918040000001")
        task = await f.engine.create_task(user.id, spec)
        await f.settle()
        task = await f.c.repos.tasks.get(task.id)
        assert task.status == TaskStatus.FAILED
        assert task.result.summary == PILOT_NO_REAL_CALLS
        assert not [x for x in f.c.telephony.legs if not x.inbound]
        # a number on the allow-list is the one exception (the founder's own phone)
        assert not f.c.settings.pilot_dial_blocked(OWN)
    finally:
        await f.close()


# ------------------------------------------------------------------ who is served
async def test_non_allow_listed_caller_hears_one_fixed_message_and_costs_nothing(pilot):
    asked: list[str] = []
    real = pilot.c.brain.interpret

    async def spy(ctx, msg):  # pragma: no cover - must not be called
        asked.append(msg.text or "")
        return await real(ctx, msg)

    pilot.c.brain.interpret = spy
    summary, leg = await sim_call(pilot, STRANGER, ["hello", "book a table"])
    lines = said(leg)
    assert len(lines) == 1 and "ai assistant" in lines[0].lower()
    assert "private test" in lines[0] or "private" in lines[0].lower()
    assert summary.route == "reject" and summary.llm_turns == 0 and not asked
    assert await pilot.c.repos.users.get_by_phone(STRANGER) is None
    assert pilot.c.repos.users is not None and summary.cost_inr_est == 0.0
    assert leg.ended


async def test_repeat_rejected_caller_is_dropped_without_a_word(pilot):
    outcomes = []
    for _ in range(6):
        _s, leg = await sim_call(pilot, STRANGER, [])
        outcomes.append(len(said(leg)))
    assert outcomes[:3] == [1, 1, 1] and outcomes[-1] == 0  # fixed message, then silence


async def test_business_callback_path_is_unchanged_by_the_front_door():
    f = await Friday.start()  # default profile: the front door is on, business calls go the old way
    try:
        rahul = await f.user("+919811100001", "Rahul")
        await rahul.say("Urban Trim Salon +918040001013 mein haircut book karo kal shaam")
        mem = await f.c.repos.calls.recent_for_phone(
            URBAN, since=f.clock.now().replace(year=2025), limit=5
        )
        await f.c.telephony.simulate_inbound_call(URBAN, mem[0].friday_number, answered=True)
        await f.settle()
        assert f.rt.front_door.history == []  # never routed to the front door
        from friday.core.models import CallDirection

        inbound = [
            c for c in await rahul.calls(await rahul.task()) if c.direction == CallDirection.INBOUND
        ]
        assert inbound and "ai assistant" in friday_lines(inbound[0])[0].lower()
        assert "Rahul" in friday_lines(inbound[0])[0]
    finally:
        await f.close()


async def test_unknown_caller_outside_the_pilot_keeps_the_take_a_message_path():
    f = await Friday.start()  # default profile, front_door_open_signup off
    try:
        await f.c.telephony.simulate_inbound_call("+919845099999", answered=True)
        await f.settle()
        assert f.rt.front_door.history == []
    finally:
        await f.close()


async def test_open_signup_lets_an_unknown_caller_onboard_outside_the_pilot():
    f = await Friday.start(frontdoor_open_signup=True)
    try:
        summary, _leg = await sim_call(f, "+919845099999", [LOOKS_ASK, "Ravi", "nahi"])
        assert summary.kind == CallerKind.UNKNOWN and summary.route == "serve"
    finally:
        await f.close()


async def test_hidden_caller_id_is_refused_cheaply(pilot):
    leg = ScriptedLeg([])
    pilot.c.telephony.inbound_legs[leg.provider_call_id] = leg
    await pilot.rt.callbacks._from_event(
        type("Ev", (), {"from_phone": "anonymous", "to_number": None,
                        "provider_call_id": leg.provider_call_id})(),
        answered=True,
    )
    assert len(leg.texts) == 1 and leg.hung_up


# ------------------------------------------------------------------ limits
async def test_silence_ends_the_call_politely(pilot):
    leg = ScriptedLeg(["Asha", None, None, None, None])  # then nothing
    await ring(pilot, OWN, leg)
    # name given, then three silent turns in a row
    assert any("Main yahin hoon" in x for x in leg.texts)
    assert "awaaz nahi aa rahi" in leg.texts[-1] and leg.hung_up
    assert pilot.rt.front_door.history[-1].end_reason == "silence"
    assert await pilot.c.repos.users.get_by_phone(OWN) is None  # nothing stored without consent


async def test_per_caller_rate_limit(pilot):
    pilot.c.settings.frontdoor_per_caller_per_hour = 2
    for _ in range(2):
        await ring(pilot, OWN, ScriptedLeg(["Asha", "English", "nahi"]))
    leg = ScriptedLeg(["hello"])
    await ring(pilot, OWN, leg)
    assert len(leg.texts) == 1 and "kai baar call kar chuke" in leg.texts[0]
    assert pilot.rt.front_door.history[-1].route == "reject"


async def test_global_rate_limit(pilot):
    f = await start_friday("pilot", (OWN, OWN2), frontdoor_global_per_hour=1)
    try:
        await ring(f, OWN, ScriptedLeg(["Asha", "English", "nahi"]))
        leg = ScriptedLeg(["hello"])
        await ring(f, OWN2, leg)
        assert len(leg.texts) == 1 and "kisi aur ki madad" in leg.texts[0]
    finally:
        await f.close()


async def test_one_live_call_at_a_time():
    f = await start_friday("pilot", (OWN, OWN2))
    try:
        first = ScriptedLeg(["Asha"])
        first.gate = asyncio.Event()
        running = asyncio.create_task(ring(f, OWN, first))
        await asyncio.wait_for(first.entered.wait(), 2)
        second = ScriptedLeg(["hello"])
        await ring(f, OWN2, second)
        assert len(second.texts) == 1 and "kisi aur ki madad" in second.texts[0]
        assert not first.hung_up  # the live call is untouched
        first.gate.set()
        await asyncio.wait_for(running, 5)
    finally:
        await f.close()


async def test_max_duration_hangs_up_politely_in_the_pilot():
    f = await start_friday("pilot", (OWN,))
    try:
        # every Friday line takes 100 virtual seconds: the 180 s pilot cap hits after two turns
        leg = ScriptedLeg(["Asha", "English", "haan", "who are you", "who are you"] + ["hi"] * 10,
                          clock=f.clock, speak_s=100.0)
        await ring(f, OWN, leg)
        assert "time limit" in leg.texts[-1]
        s = f.rt.front_door.history[-1]
        assert s.end_reason == "max duration" and s.outcome == CallOutcome.PARTIAL.value
        assert s.duration_s <= 180 + 2 * 100  # stops at the next turn boundary, never runs on
    finally:
        await f.close()


async def test_spend_cap_stops_serving_new_callers():
    f = await start_friday("pilot", (OWN, OWN2), frontdoor_spend_cap_inr=1.0)
    try:
        long_call = ScriptedLeg(["Asha", "English", "nahi"], clock=f.clock, speak_s=60.0)
        await ring(f, OWN, long_call)
        assert f.rt.front_door.guard.spend_inr >= 1.0
        leg = ScriptedLeg(["hello"])
        await ring(f, OWN2, leg)
        assert len(leg.texts) == 1 and "nahi le sakti" in leg.texts[0]
    finally:
        await f.close()


async def test_pause_switch_does_not_stop_answering_but_new_tasks_are_not_started(tmp_path):
    from friday.pause import install_pause_guard, set_paused

    f = await Friday.start(pause_file=str(tmp_path / "PAUSED"))
    try:
        install_pause_guard(f.c)
        rahul = await f.user("+919811100001", "Rahul")
        set_paused(f.c.settings, True)
        summary, leg = await sim_call(f, rahul.phone, ["", LOOKS_ASK, "haan", "nahi bas"])
        assert summary.route == "serve" and any("Rahul" in x for x in said(leg))
        assert not [x for x in f.c.telephony.legs if not x.inbound]  # no outbound call while paused
    finally:
        await f.close()


# ------------------------------------------------------------------ language
async def test_mirrors_the_callers_language_turn_by_turn():
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")
        leg = ScriptedLeg(
            [("who are you exactly, please tell me", E),
             ("aap kaun ho bhai ye batao mujhe", H),
             ("what can you do for me today", E),
             ("bye", E)]
        )
        await ring(f, "+919811100001", leg)
        caps = [x for x in leg.texts if "personal assistant" in x.lower()]
        assert len(caps) == 3
        assert caps[0].startswith("I am Friday") and caps[1].startswith("Main Friday hoon")
        assert caps[2].startswith("I am Friday")
        # a one-word 'haan' does not flip the language by itself
        leg2 = ScriptedLeg(
            [("who are you exactly, please tell me", E), ("haan", H), ("who are you", E),
             ("bye", E)]
        )
        await ring(f, "+919811100001", leg2)
        caps2 = [x for x in leg2.texts if "personal assistant" in x.lower()]
        assert all(x.startswith("I am Friday") for x in caps2)
    finally:
        await f.close()


# ------------------------------------------------------------------ misc policy
async def test_approvals_cannot_be_given_on_a_call(monkeypatch):
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")

        async def approve(ctx, msg):
            return Interpretation(intent=Intent.APPROVE)

        monkeypatch.setattr(f.c.brain, "interpret", approve)
        leg = ScriptedLeg([("haan book kar do isko abhi", H), ("bye", E)])
        await ring(f, "+919811100001", leg)
        assert any("Approval main abhi call par nahi le sakti" in x for x in leg.texts)
    finally:
        await f.close()


async def test_a_broken_brain_ends_the_call_honestly_not_silently(monkeypatch):
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")

        async def broken(ctx, msg):
            raise RuntimeError("llm down")

        monkeypatch.setattr(f.c.brain, "interpret", broken)
        leg = ScriptedLeg([("book a haircut for tomorrow evening", E)] * 4)
        await ring(f, "+919811100001", leg)
        assert any("having trouble" in x for x in leg.texts) and leg.hung_up
        assert f.rt.front_door.history[-1].outcome == CallOutcome.FAILED.value
    finally:
        await f.close()


@pytest.mark.parametrize("reply", ["**Done** 😀 https://x.y reply YES", "- one\n- two"])
async def test_brain_text_is_made_speakable(monkeypatch, reply):
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")

        async def chat(ctx, msg):
            return Interpretation(intent=Intent.SMALL_TALK, reply=reply)

        monkeypatch.setattr(f.c.brain, "interpret", chat)
        leg = ScriptedLeg([("how is the weather today in town", E), ("bye", E)])
        await ring(f, "+919811100001", leg)
        spoken = " ".join(leg.texts)
        assert "😀" not in spoken and "http" not in spoken and "**" not in spoken
    finally:
        await f.close()


# ------------------------------------------------------------------ result call-backs
async def test_result_callback_rules_window_allow_list_and_wording():
    from datetime import datetime

    from friday.core.clock import IST
    from friday.core.models import Task, TaskResult, TaskSpec, TaskType

    f = await start_friday("pilot", (OWN,))
    try:
        asha = await f.user(OWN, "Asha")
        user = await asha.user_row()
        spec = TaskSpec(type=TaskType.ENQUIRY, goal="Ask Looks about hours")
        task = Task(requester_user_id=user.id, type=TaskType.ENQUIRY, spec=spec,
                    status=TaskStatus.COMPLETED,
                    result=TaskResult(success=True, summary="Looks is open until 9 PM today."))
        await f.c.repos.tasks.add(task)
        results = f.rt.front_door.results

        f.clock.set(datetime(2026, 1, 5, 23, 30, tzinfo=IST))  # too late to ring anyone
        assert await results.deliver(task.id, user.id, OWN, "final") is False
        assert results.calls[-1]["skipped"].startswith("outside")
        assert not [x for x in f.c.telephony.legs if not x.inbound]

        f.clock.set(datetime(2026, 1, 5, 11, 0, tzinfo=IST))
        assert await results.deliver(task.id, user.id, OWN, "final") is True
        leg = next(x for x in f.c.telephony.legs if not x.inbound)
        text = " ".join(t for t, _ in leg.spoken)
        assert "ai assistant" in text.lower() and "Looks is open until 9 PM today." in text
        assert leg.request.metadata["purpose"] == "result_callback"

        assert not f.rt.front_door.callbacks_possible(STRANGER)  # the pilot allow-list applies
        assert f.rt.front_door.followup_mode(STRANGER) == "none"
    finally:
        await f.close()


# ------------------------------------------------------------------ status, cancel, slow brain
async def test_status_and_cancel_by_voice_use_the_open_task_and_ignore_the_pending_offer():
    f = await Friday.start(sarvam_caller_ids=["+918065354620"])
    try:
        rahul = await f.user("+919811100001", "Rahul")
        await sim_call(f, rahul.phone, ["", LOOKS_ASK, "haan", "nahi bas"])
        task = await rahul.task()
        assert task.status == TaskStatus.AWAITING_APPROVAL  # an offer is waiting on WhatsApp

        _s, leg = await sim_call(f, rahul.phone, ["", "what happened with my request?", "bye"],
                                 lang=E)
        assert any("waiting for your approval" in x for x in said(leg))  # not read as an answer

        _s, leg = await sim_call(f, rahul.phone, ["", "cancel", "haan", "bye"])
        assert any("cancel karun?" in x for x in said(leg))  # read back before cancelling
        assert any("maine isse cancel kar diya" in x for x in said(leg))
        assert (await rahul.task()).status == TaskStatus.CANCELLED
    finally:
        await f.close()


async def test_a_slow_brain_gets_a_cached_one_moment_not_dead_air(monkeypatch):
    import friday.voice.frontdoor as module

    monkeypatch.setattr(module, "HOLD_AFTER_S", 0.01)
    f = await Friday.start()
    try:
        await f.user("+919811100001", "Rahul")
        real = f.c.brain.interpret

        async def slow(ctx, msg):
            await asyncio.sleep(0.1)
            return await real(ctx, msg)

        f.c.brain.interpret = slow
        leg = ScriptedLeg([("Looks Unisex Salon mein haircut book karo kal shaam", H), ("nahi", H),
                           ("bye", E)])
        await ring(f, "+919811100001", leg)
        assert "Ek second." in leg.texts
        assert f.rt.front_door.history[-1].p95_ms >= 100  # the slow turn is in the latency report
    finally:
        await f.close()
