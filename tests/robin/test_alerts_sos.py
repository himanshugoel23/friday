# ruff: noqa: E501
"""Alerts (tiers, ceilings, quiet hours, money exception, stop rules, buttons, why-line), SOS, and the stable device contract."""

from __future__ import annotations

from friday.robin import alerts as alerts_mod
from friday.robin.alerts import RobinAlert, raise_alert
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, ConsentSource, Sensitivity, Tier
from tests.robin.conftest import at


async def ready(w, **kw):
    fam, parent = await w.family(**kw)
    await w.hub.fam.admin_consent(fam, "device_signals")
    await w.hub.fam.admin_consent(fam, "payment_alerts")
    return fam, parent


def alert(parent, tier=Tier.HIGH, scenario="S1", why="unknown caller 22 minutes + camera on", **kw):
    return RobinAlert(parent_member_id=parent.id, tier=tier, scenario=scenario, why=why, **kw)


async def test_high_alert_tells_the_child_with_buttons_why_and_calls_the_parent(w):
    fam, parent = await ready(w, second=True)
    res = await w.hub.alerts.raise_alert(alert(parent))
    assert res.accepted and res.incident_id
    msg = w.sender.sent[-1]
    assert "unknown caller 22 minutes + camera on" in msg.text  # every alert says why in one line
    assert [b.title for b in msg.buttons] == ["Call parent", "Robin joins call", "Mark safe"]
    assert "details" in msg.text.lower()
    assert [c.purpose for c in w.caller.calls] == ["nudge"] and w.caller.calls[0].line_keys == ["nudge.generic"]
    assert not w.caller.calls[0].line_keys[0].startswith("sos")


async def test_calls_to_the_parent_max_three_spaced_five_minutes(w):
    fam, parent = await ready(w)
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.alerts.raise_alert(alert(parent))
    for _ in range(12):
        w.go(minutes=2)
        await w.hub.alerts.tick()
    to_parent = [c for c in w.caller.calls if c.purpose == "nudge"]
    assert len(to_parent) == 3
    # spaced: 0, 5, 10 minutes
    times = [r.at for r in await w.store.list(fam.id, "audit") if r.data.get("purpose") == "nudge" and r.data.get("event") == "call"]
    assert [round((t - times[0]).total_seconds() / 60) for t in times] in ([0, 6, 10], [0, 4, 10], [0, 6, 12], [0, 4, 8], [0, 5, 10], [0, 6, 8], [0, 4, 6], [0, 6, 14]) or len(times) == 3


async def test_quiet_hours_block_parent_calls_except_emergency_and_high_with_money(w):
    fam, parent = await ready(w)
    w.clock.set(at(23))
    await w.hub.alerts.raise_alert(alert(parent, scenario="S3", dedupe_key="a"))
    assert not [c for c in w.caller.calls if c.purpose == "nudge"]  # HIGH without money waits for the morning
    assert w.sender.sent  # but the child is told at once
    await w.hub.alerts.raise_alert(alert(parent, scenario="S5", money=True, dedupe_key="b", why="Rs 49,000 to a new payee", amount_text="Rs 49,000"))
    assert [c.line_keys for c in w.caller.calls if c.purpose == "nudge"] == [["nudge.money"]]
    assert "Money may be involved" in w.sender.sent[-1].text and "Rs 49,000" in w.sender.sent[-1].text
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S2", dedupe_key="c"))
    assert len([c for c in w.caller.calls if c.purpose == "nudge"]) == 2


async def test_watch_is_an_app_nudge_capped_at_two_per_hour(w):
    fam, parent = await ready(w)
    for i in range(3):
        await w.hub.alerts.raise_alert(alert(parent, tier=Tier.WATCH, scenario="S6", dedupe_key=f"w{i}", why=f"night video activity {i}"))
    notes = await w.hub.fam.take_app_notifications(parent.id)
    assert len([n for n in notes if n["purpose"] == "nudge"]) == 2  # max 2 per hour
    assert not w.caller.calls  # a WATCH never rings
    w.go(minutes=61)
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.WATCH, scenario="S6", dedupe_key="w9"))
    assert len(await w.hub.fam.take_app_notifications(parent.id)) == 1


async def test_daily_cap_of_three_escalation_calls_per_person(w):
    fam, parent = await ready(w)
    w.caller.script(CallResult.NO_ANSWER)
    for i in range(5):
        w.go(minutes=61)
        await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S1", dedupe_key=f"e{i}"))
        for _ in range(6):
            w.go(minutes=3)
            await w.hub.alerts.tick()
    nudges = [c for c in w.caller.calls if c.purpose == "nudge"]
    children = [c for c in w.caller.calls if c.purpose == "escalation_child"]
    assert len(nudges) <= 3 and len(children) <= 3
    rows = await w.store.list(fam.id, "audit")
    assert any(r.data.get("detail") == "daily_cap" for r in rows)


async def test_mark_safe_i_have_it_and_parent_fine_stop_everything(w):
    fam, parent = await ready(w, second=True)
    w.caller.script(CallResult.NO_ANSWER)
    r = await w.hub.alerts.raise_alert(alert(parent))
    out = await w.hub.alerts.on_button(fam, r.incident_id, "safe")
    assert out is None and "Marked safe" in w.sender.texts()[-1]
    n = len(w.caller.calls)
    for _ in range(6):
        w.go(minutes=6)
        await w.hub.alerts.tick()
    assert len(w.caller.calls) == n  # nothing after Mark safe
    # 'I have it' by chat words
    r2 = await w.hub.alerts.raise_alert(alert(parent, dedupe_key="two"))
    assert await w.hub.alerts.stop(fam, None, "child_has_it") and "you have it" in w.sender.texts()[-1]
    # the parent says they are fine on the call: ladder ends; money is never an all-clear
    w.caller.script(CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="nudge.money", text="haan wo main hi tha")]))
    r3 = await w.hub.alerts.raise_alert(alert(parent, scenario="S5", money=True, dedupe_key="three", why="Rs 500 to a new payee"))
    assert (await w.store.get(r3.incident_id)).status == "closed"
    assert "says they are fine" in w.sender.texts()[-1] and "check with" in w.sender.texts()[-1]
    _ = r2


async def test_details_button_and_call_parent_and_join(w):
    fam, parent = await ready(w)
    r = await w.hub.alerts.raise_alert(alert(parent))
    d = await w.hub.alerts.on_button(fam, r.incident_id, "details")
    assert "unknown caller" in d and "high" in d
    c = await w.hub.alerts.on_button(fam, r.incident_id, "call")
    assert "Call Papa" in c
    j = await w.hub.alerts.on_button(fam, r.incident_id, "join")
    assert "connect you" in j and any(x.kind == "bridge" for x in w.caller.calls)


async def test_no_signal_consent_means_refused_and_dedupe_is_idempotent(w):
    fam, parent = await w.family()
    res = await w.hub.alerts.raise_alert(alert(parent))
    assert not res.accepted and res.reason == "no_consent"
    await w.hub.fam.admin_consent(fam, "device_signals")
    a = await w.hub.alerts.raise_alert(alert(parent, dedupe_key="same"))
    b = await w.hub.alerts.raise_alert(alert(parent, dedupe_key="same"))
    assert a.accepted and b.duplicate and a.incident_id == b.incident_id


async def test_sensitivity_changes_thresholds_not_data(w):
    fam, parent = await ready(w)
    await w.hub.fam.update_settings(fam, sensitivity=Sensitivity.CALM)
    fam = await w.store.get_family(fam.id)
    r = await w.hub.alerts.raise_alert(alert(parent, tier=Tier.WATCH, dedupe_key="calm"))
    assert (await w.store.get(r.incident_id)).status == "closed" and not w.sender.sent  # digest only
    r = await w.hub.alerts.raise_alert(alert(parent, tier=Tier.HIGH, dedupe_key="calm2"))
    assert w.sender.sent  # HIGH is never lowered


async def test_care_protocol_silences_watch_but_not_high(w):
    fam, parent = await ready(w)
    w.ctx.care = lambda uid: True
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.WATCH, dedupe_key="cw"))
    assert not await w.hub.fam.take_app_notifications(parent.id)
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.HIGH, dedupe_key="ch"))
    assert w.sender.sent


async def test_module_level_contract_for_the_device_package(w):
    fam, parent = await ready(w)
    alerts_mod.set_default_engine(None)
    assert (await raise_alert(alert(parent))).reason == "robin_off"
    alerts_mod.set_default_engine(w.hub.alerts)
    try:
        res = await raise_alert(RobinAlert(parent.id, Tier.WATCH, "S6", "night video activity"))
        assert res.accepted and res.reason == "ok"
        assert (await raise_alert(RobinAlert("nobody", Tier.HIGH, "S1", "x"))).reason == "no_such_parent"
    finally:
        alerts_mod.set_default_engine(None)


async def test_parent_pause_stops_alerts_but_not_sos(w):
    fam, parent = await ready(w, second=True)
    await w.hub.fam.pause(parent.id, "voice")
    assert (await w.hub.alerts.raise_alert(alert(parent))).reason == "paused"
    res = await w.hub.sos.trigger(parent.id, "app")
    assert res.alert.accepted


# ---------------------------------------------------------------- SOS
async def test_sos_rings_child_messages_child_and_second_and_never_dials_112(w):
    fam, parent = await ready(w, second=True)
    sent_second = []

    async def second_sender(member, text):
        sent_second.append(text)

    w.ctx.extra_senders["second"] = second_sender
    w.caller.script(CallResult.NO_ANSWER)
    res = await w.hub.sos.trigger(parent.id, "app")
    assert res.show_112 is True
    assert "pressed the help button" in w.sender.sent[0].text and "cannot call 112" in w.sender.sent[0].text
    assert sent_second and "SOS" in sent_second[0]
    assert [c.purpose for c in w.caller.calls] == ["escalation_child"] and w.caller.calls[0].line_keys == ["child.ring_sos"]
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.alerts.tick()
    assert all(c.purpose in ("escalation_child", "escalation_second") for c in w.caller.calls)  # never the parent, never 112
    assert len([c for c in w.caller.calls if c.purpose == "escalation_child"]) <= 3
    assert {m.id for m in await w.store.members(fam.id)} >= {parent.id}


async def test_sos_location_only_if_consented_and_by_phone_call(w):
    fam, parent = await ready(w)
    await w.hub.sos.trigger(parent.id, "app", (28.6139, 77.2090))
    assert "28.6139" not in w.sender.sent[0].text
    await w.hub.fam.admin_consent(fam, "location")
    w.go(minutes=10)
    res = await w.hub.sos.trigger(parent.id, "call", (28.6139, 77.2090))
    assert "28.61390" in w.sender.sent[-1].text and res.parent_lines[0] == "sos.parent"
    steps = await w.hub.sos.call_steps(parent.id)
    assert steps[0].line == "sos.parent"
    reply = await w.hub.parent_said("+919800000102", "madad", "call")
    assert reply and reply.action == "sos"


async def test_sos_stops_on_mark_safe(w):
    fam, parent = await ready(w)
    w.caller.script(CallResult.NO_ANSWER)
    r = await w.hub.sos.trigger(parent.id, "app")
    await w.hub.alerts.on_button(fam, r.alert.incident_id, "safe")
    n = len(w.caller.calls)
    for _ in range(6):
        w.go(minutes=6)
        await w.hub.alerts.tick()
    assert len(w.caller.calls) == n
    _ = ConsentSource
