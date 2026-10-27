# ruff: noqa: E501
"""The escalation wired into the receptionist: the alert gets an Acknowledge button, the timer starts,
buttons stop it, the real app wiring builds it (switch off = nothing). Fakes only."""

from __future__ import annotations

import asyncio

from friday.core.config import Settings
from friday.core.events import InboundCallReceived
from friday.receptionist import sim
from friday.receptionist.models import MessageStatus, ReceptionistConfig
from friday.urgent.gate import OwnNumberGate
from friday.urgent.models import EscStatus, Policy, RingResult, UserEscalationConfig
from friday.urgent.ports import FakeOwnNumberCaller
from friday.urgent.service import UrgentEscalation
from friday.urgent.store import MemoryEscalationStore
from tests.calls.conftest import build_world
from tests.e2e.harness import Friday
from tests.frontdoor.conftest import FRIDAY_NUMBER, OWN, ScriptedLeg, start_friday
from tests.urgent.conftest import Users

U = sim.USER_ID


async def sim_world(*, results=(RingResult.NO_ANSWER,), opted_in=True, enabled=True):
    """The receptionist simulator world with the escalation attached (store, clock and sends shared)."""
    w = await sim.make_world()
    cw = build_world()
    user = cw.user.model_copy(update={"id": U, "phone": sim.USER_PHONE})
    esc_store = MemoryEscalationStore(w.clock)
    caller = FakeOwnNumberCaller(*results)
    esc = UrgentEscalation(
        esc_store, w.service.send, caller, w.clock, users=Users(user), gate=OwnNumberGate(cw.gate, cw.hasher),
        policy=Policy(), enabled=lambda: enabled, rcp_config=w.store.get_config,
    )  # fmt: skip
    if opted_in:
        await esc_store.save_config(U, UserEscalationConfig(opted_in=True, number=sim.USER_PHONE))
    w.service.escalation = esc
    return w, esc, esc_store, caller


def urgent_caller():
    return next(c for c in sim.callers() if c.id == "urgent-accident-hinglish")


async def test_an_urgent_call_gets_acknowledge_hint_and_a_running_timer():
    w, esc, store, caller = await sim_world()
    r = await sim.run_caller(w, urgent_caller())
    assert r.pushes == 1
    uid, text, buttons = w.sent[-1]
    assert [b.title for b in buttons] == ["Acknowledge", "Call back", "Ignore"]
    assert all(len(b.title) <= 20 for b in buttons) and buttons[0].id.startswith("urg:")
    assert "Acknowledge" in text and "minute" in text
    msg = (await w.store.list_messages(U))[0]
    assert msg.status == MessageStatus.NOTIFIED
    st = await store.by_message(U, msg.id)
    assert st.emergency and st.alert_ok and st.alert_sent_at == w.clock.now()  # 'accident'
    assert st.next_action_at == st.alert_sent_at.replace() + (st.next_action_at - st.alert_sent_at)
    assert (st.next_action_at - st.alert_sent_at).total_seconds() == 300


async def test_no_acknowledge_in_five_minutes_rings_the_users_own_number_even_after_21_30():
    w, esc, store, caller = await sim_world()  # the simulator clock starts at 21:30 IST
    await sim.run_caller(w, urgent_caller())
    w.clock.advance(minutes=5)
    out = await esc.tick()
    assert out["called"] == 1 and caller.calls[0].number == sim.USER_PHONE
    assert caller.calls[0].line_key == "ring.emergency"  # a true emergency may ring in quiet hours


async def test_tapping_acknowledge_through_the_button_stops_the_call():
    w, esc, store, caller = await sim_world()
    await sim.run_caller(w, urgent_caller())
    ack = w.sent[-1][2][0].id
    text, _ = await esc.on_button(U, ack)
    assert "acknowledged" in text.lower() or "acknowledge" in text.lower()
    w.clock.advance(minutes=30)
    assert (await esc.tick())["called"] == 0 and not caller.calls


async def test_the_existing_buttons_on_the_alert_also_stop_it():
    for action in ("callback", "ignore"):
        w, esc, store, caller = await sim_world()
        await sim.run_caller(w, urgent_caller())
        m = (await w.store.list_messages(U))[0]
        await w.service.on_button(U, f"rcp:{m.id}:{action}")
        w.clock.advance(minutes=30)
        assert (await esc.tick())["called"] == 0 and not caller.calls, action


async def test_without_opt_in_or_switch_the_alert_is_exactly_the_old_three_buttons():
    for kw in ({"opted_in": False}, {"enabled": False}):
        w, esc, store, caller = await sim_world(**kw)
        await sim.run_caller(w, urgent_caller())
        _uid, text, buttons = w.sent[-1]
        assert [b.title for b in buttons] == ["Call back", "Ignore", "Block"]
        assert "Acknowledge" not in text and await store.open_for_user(U) == []


async def test_a_normal_call_never_opens_an_escalation():
    w, esc, store, caller = await sim_world()
    await sim.run_caller(w, next(c for c in sim.callers() if c.id == "doctor-clinic"))
    assert await store.open_for_user(U) == []


async def test_a_broken_escalation_never_breaks_the_alert():
    w, esc, store, caller = await sim_world()

    async def boom(*a, **k):
        raise RuntimeError("db down")

    esc.open = boom  # type: ignore[method-assign]
    r = await sim.run_caller(w, urgent_caller())
    assert r.pushes == 1 and [b.title for b in w.sent[-1][2]] == ["Call back", "Ignore", "Block"]


async def test_a_failed_whatsapp_send_still_starts_the_timer_from_opening():
    w, esc, store, caller = await sim_world()
    real = w.service.send

    async def failing(uid, text, buttons):
        raise RuntimeError("whatsapp down")

    w.service.send = failing
    await sim.run_caller(w, urgent_caller())
    w.service.send = real
    m = (await w.store.list_messages(U))[0]
    st = await store.by_message(U, m.id)
    assert not st.alert_ok
    w.clock.advance(minutes=5)
    assert (await esc.tick())["called"] == 1


# ----------------------------------------------------------------------------- the real app wiring
async def test_switch_off_means_no_component_and_the_receptionist_is_unchanged():
    f = await Friday.start()
    try:
        assert f.c.get("urgent_escalation") is None
        assert Settings(_env_file=None).urgent_escalation_enabled is False
    finally:
        await f.close()


async def test_receptionist_off_means_no_escalation_either():
    f = await start_friday("default", (OWN,), urgent_escalation_enabled=True)
    try:
        assert f.rt.callbacks.receptionist() is None  # nothing to escalate from
    finally:
        await f.close()


async def test_in_the_real_app_opt_in_alert_ack_and_call_back():
    from friday.core.models import ReplyButton  # noqa: F401

    phone = "+919811100001"
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_redirect_fields=["Diversion"],
        urgent_escalation_enabled=True,
    )  # fmt: skip
    try:
        user = await f.user(phone, "Rahul")
        rcp = f.rt.callbacks.receptionist()
        urgent = f.c.get("urgent_escalation")
        assert urgent is not None and rcp.urgent is urgent and rcp.service.escalation is urgent
        uid = (await f.c.repos.users.get_by_phone(phone)).id
        await rcp.service.store.save_config(uid, ReceptionistConfig(enabled=True, user_name="Rahul"))
        fake = FakeOwnNumberCaller()
        urgent.caller = fake
        # the user switches it on in WhatsApp
        await user.say("urgent call on")
        cfg = await urgent.store.get_config(uid)
        assert cfg is not None and cfg.opted_in and cfg.number == phone
        # an urgent forwarded call
        leg = ScriptedLeg(["Main Suman bol rahi hoon, accident ho gaya hai, jaldi call karo", "haan sahi hai"])
        f.c.telephony.inbound_legs[leg.provider_call_id] = leg
        before = len(f.channel.messages_to(phone))
        await f.c.bus.publish(
            InboundCallReceived(from_phone="+919100000015", to_number=FRIDAY_NUMBER,
                                provider_call_id=leg.provider_call_id, provider="test",
                                redirecting=f"<sip:{phone}@vobiz.example>;reason=no-answer")
        )  # fmt: skip
        await f.settle()
        await asyncio.sleep(0)
        out = f.channel.messages_to(phone)[before:]
        alert = out[-1]
        assert alert.buttons[0].title == "Acknowledge" and "URGENT" in (alert.text or "")
        open_ = await urgent.store.open_for_user(uid)
        assert len(open_) == 1
        # the user rings Friday from their own phone: the escalation stops, no call is made
        await f.c.bus.publish(
            InboundCallReceived(from_phone=phone, to_number=FRIDAY_NUMBER, provider_call_id="X1", provider="test")
        )  # fmt: skip
        await f.settle()
        assert (await urgent.store.get(uid, open_[0].id)).status == EscStatus.STOPPED
        f.c.clock.advance(minutes=30)
        assert (await urgent.tick())["called"] == 0 and not fake.calls
    finally:
        await f.close()


async def test_the_runtime_starts_the_escalation_loop_next_to_the_receptionist_loop():
    from friday.api.runtime import Runtime
    from friday.core.clock import FakeClock
    from friday.core.container import Container

    def build(**kw):
        settings = Settings(
            _env_file=None, mode="simulator", env="test", database_url="sqlite+aiosqlite:///:memory:",
            roles=["task"], receptionist_enabled=True, **kw,
        )  # fmt: skip
        return Runtime(Container(settings, clock=FakeClock()), fast_pin_hash=True)

    for on in (True, False):
        rt = build(urgent_escalation_enabled=on)
        await rt.start(background=True)
        try:
            names = {t.get_name() for t in rt._tasks}
            assert "friday-receptionist" in names
            assert ("friday-urgent-escalation" in names) is on
        finally:
            # not rt.stop(): cancelling the receptionist loop mid-query on in-memory SQLite can hang
            # (pre-existing, unrelated to this feature); cancel the tasks and give them a moment
            for t in rt._tasks:
                t.cancel()
            await asyncio.wait(rt._tasks, timeout=1)
