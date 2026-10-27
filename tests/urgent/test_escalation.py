# ruff: noqa: E501
"""The urgent-call escalation on a fake clock: timing, acknowledge, retries, quiet hours, wrong number,
restart. Fakes only: nothing is dialled and nothing is sent."""

from __future__ import annotations

import asyncio

import pytest

from friday.core.config import Settings
from friday.core.models import ReplyButton
from friday.urgent import copy
from friday.urgent.models import (
    EscalationState,
    EscStatus,
    Policy,
    RingResult,
    UserEscalationConfig,
)
from friday.urgent.policy import Facts, decide, is_emergency, plan
from friday.urgent.service import UrgentEscalation
from tests.urgent.conftest import OTHER_PHONE, USER_PHONE, W, at, make

WEAK = ("urgent word: urgent",)


async def state(w: W, esc_id: str) -> EscalationState:
    st = await w.store.get(w.user.id, esc_id)
    assert st is not None
    return st


# ----------------------------------------------------------------------------- defaults and opening
def test_defaults_are_off_five_minutes_two_calls_five_apart():
    s = Settings(_env_file=None)
    assert s.urgent_escalation_enabled is False
    p = Policy.from_settings(s)
    assert (p.wait_s, p.max_calls, p.spacing_s) == (300, 2, 300)


async def test_env_names(monkeypatch):
    monkeypatch.setenv("FRIDAY_URGENT_ESCALATION_ENABLED", "true")
    monkeypatch.setenv("FRIDAY_URGENT_ESCALATION_MINUTES", "7")
    s = Settings(_env_file=None)
    assert s.urgent_escalation_enabled and s.urgent_escalation_minutes == 7


async def test_no_escalation_without_opt_in_switch_or_when_paused(w: W):
    assert await w.esc.open(w.user.id, "m1", list(WEAK)) is None  # not opted in
    await w.optin()
    w.flags["enabled"] = False
    assert await w.esc.open(w.user.id, "m1", list(WEAK)) is None  # switch off
    w.flags["enabled"], w.flags["paused"] = True, True
    assert await w.esc.open(w.user.id, "m1", list(WEAK)) is None  # kill switch
    w.flags["paused"] = False
    o = await w.esc.open(w.user.id, "m1", list(WEAK))
    assert o is not None and o.created and o.state.wait_s == 300


async def test_opening_twice_is_idempotent(w: W):
    await w.optin()
    a = await w.esc.open(w.user.id, "m1", list(WEAK))
    b = await w.esc.open(w.user.id, "m1", list(WEAK))
    assert a.created and not b.created and a.state.id == b.state.id


# ----------------------------------------------------------------------------- timing on a fake clock
async def test_nothing_before_five_minutes_then_one_call_then_one_more_five_later_then_stop(w: W):
    await w.optin()
    st = await w.alert(reasons=WEAK)
    assert (await w.go(seconds=299))["called"] == 0 and not w.caller.calls
    out = await w.go(seconds=1)  # exactly 5:00 after the alert
    assert out["called"] == 1 and len(w.caller.calls) == 1
    first = w.caller.calls[0]
    assert first.number == USER_PHONE and first.line_key == "ring.urgent" and first.dedupe_key == f"{st.id}:1"
    assert (await w.go(seconds=299))["called"] == 0  # the second call is 5 min after the first
    assert (await w.go(seconds=1))["called"] == 1 and len(w.caller.calls) == 2
    done = await state(w, st.id)
    assert done.status == EscStatus.EXHAUSTED and done.calls_made == 2
    assert (await w.go(minutes=30))["called"] == 0 and len(w.caller.calls) == 2  # never a third
    final = [t for _u, t, _b in w.sent if "2 time" in t or "2 baar" in t]
    assert final, "the user is told the calls did not reach them"


async def test_the_timer_runs_from_the_moment_the_alert_was_sent(w: W):
    await w.optin()
    o = await w.esc.open(w.user.id, "m1", list(WEAK))
    w.clock.advance(seconds=100)  # the send took a while
    await w.esc.confirm_alert(o.state, True)
    st = await state(w, o.state.id)
    assert st.alert_ok and st.alert_sent_at == w.clock.now()
    assert (await w.go(seconds=299))["called"] == 0
    assert (await w.go(seconds=1))["called"] == 1


async def test_a_failed_alert_still_escalates_from_the_opening_time(w: W):
    await w.optin()
    o = await w.esc.open(w.user.id, "m1", list(WEAK))
    w.clock.advance(seconds=60)
    await w.esc.confirm_alert(o.state, False)
    st = await state(w, o.state.id)
    assert not st.alert_ok
    assert (await w.go(seconds=239))["called"] == 0
    assert (await w.go(seconds=1))["called"] == 1  # 5 min after OPENING, not after the failed send


async def test_per_user_override_minutes_calls_spacing_and_clamps(w: W):
    await w.optin(minutes=3, max_calls=1, spacing_minutes=2)
    st = await w.alert()
    assert (st.wait_s, st.max_calls, st.spacing_s) == (180, 1, 120)
    assert (await w.go(seconds=179))["called"] == 0
    assert (await w.go(seconds=1))["called"] == 1
    assert (await state(w, st.id)).status == EscStatus.EXHAUSTED
    assert (await w.go(minutes=10))["called"] == 0
    p = plan(UserEscalationConfig(minutes=1, spacing_minutes=999, max_calls=99), Policy())
    assert (p.wait_s, p.spacing_s, p.max_calls) == (120, 1800, 3)  # never an instant call, never > 3


async def test_changing_the_setting_does_not_move_a_running_timer(w: W):
    await w.optin()
    st = await w.alert()
    await w.optin(minutes=40)  # user changes it after the alert
    assert (await state(w, st.id)).wait_s == 300
    assert (await w.go(minutes=5))["called"] == 1


# ----------------------------------------------------------------------------- acknowledge and stop
async def test_acknowledge_cancels_before_the_call(w: W):
    await w.optin()
    st = await w.alert()
    await w.go(minutes=2)
    reply = await w.esc.on_button(w.user.id, f"urg:{st.id}:ack")
    assert reply is not None and "acknowledged" in reply[0].lower() or "acknowledge" in reply[0].lower()
    assert (await state(w, st.id)).status == EscStatus.ACKED
    assert (await w.go(minutes=30))["called"] == 0 and not w.caller.calls


async def test_acknowledge_after_the_first_call_stops_the_second(w: W):
    await w.optin()
    st = await w.alert()
    await w.go(minutes=5)
    assert len(w.caller.calls) == 1
    await w.esc.on_button(w.user.id, f"urg:{st.id}:ack")
    await w.go(minutes=30)
    assert len(w.caller.calls) == 1 and (await state(w, st.id)).status == EscStatus.ACKED


async def test_acknowledge_while_the_phone_is_ringing_is_recorded_not_overwritten():
    w = make()
    await w.optin()
    st = await w.alert()
    # the user taps Acknowledge in the same instant the first call is being placed
    w.caller.hook = lambda rec: asyncio.get_event_loop().create_task(w.esc.on_button(w.user.id, f"urg:{st.id}:ack"))
    await w.go(minutes=5)
    await asyncio.sleep(0)
    await w.go(minutes=10)
    done = await state(w, st.id)
    assert done.status == EscStatus.ACKED and len(w.caller.calls) == 1


async def test_double_tap_and_stale_and_other_users_button(w: W):
    await w.optin()
    st = await w.alert()
    a = await w.esc.on_button(w.user.id, f"urg:{st.id}:ack")
    b = await w.esc.on_button(w.user.id, f"urg:{st.id}:ack")
    assert a[0] == b[0]  # idempotent
    assert (await w.esc.on_button("someone-else", f"urg:{st.id}:ack"))[0] == copy.t("reply.stale", "hinglish")
    assert (await w.esc.on_button(w.user.id, "urg:nope:ack"))[0] == copy.t("reply.stale", "hinglish")
    assert await w.esc.on_button(w.user.id, "rcp:x:ack") is None  # not ours
    assert await w.esc.on_button(w.user.id, f"urg:{st.id}:other") is None


async def test_ack_of_another_users_escalation_does_not_stop_mine(w: W):
    await w.optin()
    st = await w.alert()
    await w.esc.on_button("intruder", f"urg:{st.id}:ack")
    assert (await state(w, st.id)).status == EscStatus.PENDING


@pytest.mark.parametrize("action", ["callback", "ignore", "block"])
async def test_using_any_receptionist_button_counts_as_seen(w: W, action):
    await w.optin()
    st = await w.alert()
    assert await w.esc.user_acted(w.user.id, "m1", action) == 1
    assert (await state(w, st.id)).status == EscStatus.ACKED
    assert (await w.go(minutes=30))["called"] == 0


async def test_the_user_ringing_friday_stops_it_but_nobody_else_can(w: W):
    await w.optin()
    st = await w.alert()
    assert await w.esc.note_inbound_call(OTHER_PHONE) == 0
    assert await w.esc.note_inbound_call(None) == 0
    assert (await state(w, st.id)).status == EscStatus.PENDING
    await w.go(minutes=5)  # first call placed
    assert await w.esc.note_inbound_call(USER_PHONE) == 1  # the user rings back
    await w.go(minutes=30)
    done = await state(w, st.id)
    assert done.status == EscStatus.STOPPED and done.stop_reason == "user_called" and len(w.caller.calls) == 1


async def test_an_answered_call_ends_the_escalation():
    w = make(results=(RingResult.ANSWERED,))
    await w.optin()
    st = await w.alert()
    out = await w.go(minutes=5)
    assert out["answered"] == 1
    await w.go(minutes=30)
    assert len(w.caller.calls) == 1 and (await state(w, st.id)).status == EscStatus.ANSWERED


@pytest.mark.parametrize("res", [RingResult.NO_ANSWER, RingResult.BUSY, RingResult.VOICEMAIL, RingResult.FAILED])
async def test_every_unanswered_outcome_retries_then_stops(res):
    w = make(results=(res,))
    await w.optin()
    await w.alert()
    await w.go(minutes=5)
    await w.go(minutes=5)
    await w.go(minutes=60)
    assert len(w.caller.calls) == 2


async def test_a_dial_that_raises_counts_as_an_attempt():
    w = make()
    await w.optin()
    st = await w.alert()

    def boom(_rec):
        raise RuntimeError("carrier down")

    w.caller.hook = boom
    await w.go(minutes=5)
    after = await state(w, st.id)
    assert after.calls_made == 1 and after.last_call_result == "failed" and after.status == EscStatus.PENDING


# ----------------------------------------------------------------------------- quiet hours
def test_only_true_emergencies_count_as_emergencies():
    assert is_emergency(["urgent word: accident"])
    assert is_emergency(["urgent word: hospital"]) is False  # urgent, not necessarily life or death
    assert is_emergency(["urgent word: urgent"]) is False
    assert is_emergency(["urgent contact"]) is False
    assert is_emergency(["known contact + urgent word: urgent"]) is False
    assert is_emergency(["urgent word: accident"], source="llm") is False  # a model never overrides quiet hours
    assert is_emergency(["model: accident"], source="llm") is False
    assert is_emergency(["urgent word: एक्सीडेंट"])


async def test_quiet_hours_no_call_for_an_ordinary_urgent_call():
    w = make(hour=23)  # 23:00 IST, inside the default quiet hours 22:00 to 08:00
    await w.optin()
    st = await w.alert(reasons=WEAK)
    assert not st.emergency
    out = await w.go(minutes=5)
    assert out["called"] == 0 and out["cancelled"] == 1
    done = await state(w, st.id)
    assert done.status == EscStatus.CANCELLED and done.stop_reason == "quiet_hours"
    assert not w.caller.calls


async def test_a_true_emergency_may_ring_in_quiet_hours_and_outside_the_calling_window():
    w = make(hour=23)
    await w.optin()
    st = await w.alert()  # "urgent word: accident"
    assert st.emergency
    assert (await w.go(minutes=5))["called"] == 1
    assert w.caller.calls[0].line_key == "ring.emergency"
    assert "night" in copy.t("alert.hint.emergency", "en", minutes=5)


async def test_a_user_can_forbid_even_emergency_calls_at_night():
    w = make(hour=3)
    await w.optin(emergency_in_quiet_hours=False)
    await w.alert()
    out = await w.go(minutes=5)
    assert out["called"] == 0 and not w.caller.calls


async def test_a_model_verdict_is_urgent_but_never_overrides_quiet_hours():
    w = make(hour=2)
    await w.optin()
    st = await w.alert(reasons=("urgent word: accident",), source="llm")
    assert not st.emergency
    assert (await w.go(minutes=5))["called"] == 0


async def test_quiet_hours_starting_between_two_calls_stop_the_second():
    w = make(hour=21)
    w.clock.set(at(21, 20))
    await w.optin()
    await w.alert(reasons=WEAK)  # 21:20, ordinary urgent
    await w.go(minutes=5)  # 21:25 first call (window open until 21:30)
    assert len(w.caller.calls) == 1
    out = await w.go(minutes=5)  # 21:30: outside the calling window -> no
    assert out["called"] == 0 and len(w.caller.calls) == 1


async def test_the_receptionists_own_quiet_hours_setting_is_used():
    from friday.receptionist.models import QuietHours

    w = make(hour=14)
    w.rcp = w.rcp.model_copy(update={"quiet_hours": QuietHours(start_hour=13, end_hour=15)})
    await w.optin()
    await w.alert(reasons=WEAK)
    assert (await w.go(minutes=5))["called"] == 0


# ----------------------------------------------------------------------------- wrong number
async def test_a_number_that_is_not_the_users_own_is_refused_and_never_dialled(w: W):
    await w.store.save_config(w.user.id, UserEscalationConfig(opted_in=True, number=OTHER_PHONE))
    st = await w.alert()
    out = await w.go(minutes=5)
    assert out["refused"] == 1 and not w.caller.calls
    done = await state(w, st.id)
    assert done.status == EscStatus.REFUSED and done.stop_reason == "not_own_number"


async def test_if_the_users_phone_changes_after_opt_in_no_call_goes_to_the_old_number(w: W):
    await w.optin()
    st = await w.alert()
    w.user.phone = "+919800000555"  # the user's number is now different
    await w.go(minutes=5)
    assert not w.caller.calls and (await state(w, st.id)).status == EscStatus.REFUSED


async def test_pilot_allow_list_is_enforced_by_the_gate():
    core = Settings(_env_file=None, pilot_block_business_calls=True, pilot_allowed_numbers=["+919000000001"])
    w = make(core=core)
    await w.optin()
    st = await w.alert()
    out = await w.go(minutes=5)
    assert out["refused"] == 1 and not w.caller.calls
    assert (await state(w, st.id)).stop_reason.startswith("gate:test_allowlist") or "allowlist" in (await state(w, st.id)).stop_reason
    core_ok = Settings(_env_file=None, pilot_block_business_calls=True, pilot_allowed_numbers=[USER_PHONE])
    w2 = make(core=core_ok)
    await w2.optin()
    await w2.alert()
    assert (await w2.go(minutes=5))["called"] == 1 and w2.caller.calls[0].number == USER_PHONE


async def test_the_gate_refuses_any_other_number_on_its_own(w: W):
    res = await w.esc.gate.check(w.user, OTHER_PHONE, emergency=True, now=w.clock.now())
    assert not res.allowed and res.reasons == ("not_own_number",)
    ok = await w.esc.gate.check(w.user, USER_PHONE, emergency=False, now=w.clock.now())
    assert ok.allowed


async def test_emergency_numbers_and_garbage_are_never_dialled(w: W):
    for bad in ("112", "100", "", "abc", "+91123"):
        res = await w.esc.gate.check(w.user, bad, emergency=True, now=w.clock.now())
        assert not res.allowed


async def test_the_call_gate_kill_switch_is_honoured():
    from friday.calls.settings import CallsSettings
    from friday.urgent.gate import OwnNumberGate
    from tests.calls.conftest import build_world

    cw = build_world(settings=CallsSettings(enabled=False))
    w = make()
    res = await OwnNumberGate(cw.gate, cw.hasher).check(w.user, USER_PHONE, emergency=True, now=w.clock.now())
    assert not res.allowed and res.reasons == ("kill_switch",)


async def test_do_not_call_on_the_users_own_number_is_honoured():
    from friday.urgent.gate import OwnNumberGate
    from tests.calls.conftest import build_world

    cw = build_world()
    await cw.dnc.add(USER_PHONE, "user_request")
    w = make()
    res = await OwnNumberGate(cw.gate, cw.hasher).check(w.user, USER_PHONE, emergency=True, now=w.clock.now())
    assert not res.allowed and res.reasons == ("dnc",)


# ----------------------------------------------------------------------------- kill switch, stale, caps
async def test_kill_switch_stops_a_running_escalation(w: W):
    await w.optin()
    st = await w.alert()
    w.flags["paused"] = True
    out = await w.go(minutes=5)
    assert out["called"] == 0 and (await state(w, st.id)).stop_reason == "kill_switch"
    w.flags["paused"] = False
    assert (await w.go(minutes=30))["called"] == 0  # and it stays stopped


async def test_switching_the_feature_off_stops_a_running_escalation(w: W):
    await w.optin()
    st = await w.alert()
    w.flags["enabled"] = False
    await w.go(minutes=5)
    assert (await state(w, st.id)).stop_reason == "switch_off" and not w.caller.calls


async def test_opting_out_stops_it_too(w: W):
    await w.optin()
    st = await w.alert()
    user = w.user
    assert await w.esc.handle_text(user, "urgent call band")
    assert (await state(w, st.id)).status == EscStatus.CANCELLED
    await w.go(minutes=10)
    assert not w.caller.calls


async def test_a_stale_alert_is_never_rung_about_after_an_outage(w: W):
    await w.optin()
    st = await w.alert()
    out = await w.go(hours=3)  # the server was down for three hours
    assert out["called"] == 0 and (await state(w, st.id)).stop_reason == "stale"


async def test_daily_cap_on_escalations_that_call():
    w = make(policy=Policy(daily_cap=1))
    await w.optin()
    await w.alert("m1")
    await w.go(minutes=5)
    assert len(w.caller.calls) == 1
    await w.alert("m2")
    out = await w.go(minutes=6)  # first escalation's second call is due too
    assert (await w.store.by_message(w.user.id, "m2")).stop_reason == "daily_cap"
    assert out["cancelled"] >= 1


async def test_user_not_active_is_not_rung(w: W):
    from friday.core.models import UserStatus

    await w.optin()
    await w.alert()
    w.user.status = UserStatus.ONBOARDING
    await w.go(minutes=5)
    assert not w.caller.calls


# ----------------------------------------------------------------------------- restart safety
async def test_a_restart_keeps_the_timer(w: W):
    await w.optin()
    st = await w.alert()
    w.clock.advance(minutes=3)
    # the process restarts: a NEW service object over the same store and clock
    esc2 = UrgentEscalation(
        w.store, w.esc.send, w.caller, w.clock, users=w.esc.users, gate=w.esc.gate,
        enabled=lambda: True, rcp_config=w.esc.rcp_config,
    )  # fmt: skip
    assert (await esc2.tick())["called"] == 0
    w.clock.advance(minutes=2)
    assert (await esc2.tick())["called"] == 1
    assert (await state(w, st.id)).calls_made == 1


async def test_two_replicas_ticking_together_dial_once(w: W):
    await w.optin()
    await w.alert()
    esc2 = UrgentEscalation(
        w.store, w.esc.send, w.caller, w.clock, users=w.esc.users, gate=w.esc.gate,
        enabled=lambda: True, rcp_config=w.esc.rcp_config,
    )  # fmt: skip
    w.clock.advance(minutes=5)
    await asyncio.gather(w.esc.tick(), esc2.tick(), w.esc.tick())
    assert len(w.caller.calls) == 1


async def test_a_crash_while_ringing_is_counted_and_never_redialled_at_once(w: W):
    await w.optin()
    st = await w.alert()
    w.clock.advance(minutes=5)
    # the first attempt is claimed (persisted) and the process dies before the result is stored
    assert await w.store.claim(st.id, 0, w.clock.now())
    assert (await w.esc.tick())["called"] == 0  # a worker may still be ringing: leave it alone
    w.clock.advance(seconds=200)
    out = await w.esc.tick()
    assert out["recovered"] == 1 and not w.caller.calls  # recovered as 'unknown', not redialled
    mid = await state(w, st.id)
    assert mid.calls_made == 1 and mid.last_call_result == "unknown" and not mid.in_flight
    w.clock.advance(minutes=5)
    assert (await w.esc.tick())["called"] == 1  # the second (last) call is still made, on schedule
    assert (await state(w, st.id)).calls_made == 2 and len(w.caller.calls) == 1


async def test_a_crash_on_the_last_call_closes_the_escalation(w: W):
    await w.optin(max_calls=1)
    st = await w.alert()
    w.clock.advance(minutes=5)
    assert await w.store.claim(st.id, 0, w.clock.now())
    w.clock.advance(seconds=200)
    await w.esc.tick()
    assert (await state(w, st.id)).status == EscStatus.EXHAUSTED and not w.caller.calls


async def test_replaying_the_same_attempt_to_the_dialler_does_not_ring_twice(w: W):
    await w.optin()
    st = await w.alert()
    kw = dict(user_id=w.user.id, number=USER_PHONE, line_key="ring.urgent", lang="en", user_name="Asha", dedupe_key=f"{st.id}:1")
    await w.caller.ring(**kw)
    await w.caller.ring(**kw)
    assert len(w.caller.calls) == 1


# ----------------------------------------------------------------------------- the user's switch
async def test_whatsapp_commands_on_minutes_status_off(w: W):
    u = w.user
    assert not await w.esc.handle_text(u, "hello")
    assert not await w.esc.handle_text(u, "what is an urgent call")
    assert await w.esc.handle_text(u, "urgent call on")
    cfg = await w.store.get_config(u.id)
    assert cfg.opted_in and cfg.number == USER_PHONE  # the opt-in is bound to the number it came from
    assert await w.esc.handle_text(u, "Urgent call 3 min")
    assert (await w.store.get_config(u.id)).minutes == 3
    assert await w.esc.handle_text(u, "urgent call 1 minute")
    assert (await w.store.get_config(u.id)).minutes == 2  # clamped
    assert await w.esc.handle_text(u, "urgent call status")
    assert "on" in w.sent[-1][1].lower() or "chalu" in w.sent[-1][1].lower()
    assert await w.esc.handle_text(u, "urgent call off")
    assert not (await w.store.get_config(u.id)).opted_in
    w.flags["enabled"] = False
    assert await w.esc.handle_text(u, "urgent call on")
    assert not (await w.store.get_config(u.id)).opted_in  # not available while the switch is off


def test_alert_additions_button_fits_whatsapp(w: W):
    st = EscalationState(id="e1", user_id="u", message_id="m", wait_s=300)
    hint, btns = w.esc.alert_additions(st, "en")
    assert "5 minutes" in hint and btns == [ReplyButton(id="urg:e1:ack", title="Acknowledge")]
    assert len(btns[0].title) <= 20


# ----------------------------------------------------------------------------- the decision function alone
def facts(**over) -> Facts:
    base = dict(switch_on=True, paused=False, user_active=True, opted_in=True, own_number=USER_PHONE,
                cfg_number=USER_PHONE, in_quiet_hours=False, emergency_in_quiet=True, daily_capped=False)  # fmt: skip
    base.update(over)
    return Facts(**base)


def test_decide_table():
    now = at(11, 10)
    st = EscalationState(id="e", user_id="u", message_id="m", next_action_at=at(11, 5))
    pol = Policy()
    assert decide(st, now, facts(), pol).action == "call"
    assert decide(st, at(11, 4), facts(), pol).reason == "not_due"
    assert decide(st, now, facts(paused=True), pol).reason == "kill_switch"
    assert decide(st, now, facts(switch_on=False), pol).reason == "switch_off"
    assert decide(st, now, facts(opted_in=False), pol).reason == "not_opted_in"
    assert decide(st, now, facts(cfg_number=OTHER_PHONE), pol).status == EscStatus.REFUSED
    assert decide(st, now, facts(own_number=None), pol).status == EscStatus.REFUSED
    assert decide(st, now, facts(in_quiet_hours=True), pol).reason == "quiet_hours"
    assert decide(st.model_copy(update={"emergency": True}), now, facts(in_quiet_hours=True), pol).action == "call"
    assert decide(st, now, facts(daily_capped=True), pol).reason == "daily_cap"
    assert decide(st.model_copy(update={"calls_made": 2}), now, facts(), pol).status == EscStatus.EXHAUSTED
    assert decide(st.model_copy(update={"status": EscStatus.ACKED}), now, facts(), pol).action == "wait"
    assert decide(st, at(13, 0), facts(), pol).reason == "stale"
