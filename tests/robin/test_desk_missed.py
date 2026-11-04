# ruff: noqa: E501
"""Missed calls in both directions (urgent: keep ringing), and the AI emergency desk's authority module (dry-run only; no real 112 is ever placed
or simulated: only the script that WOULD be spoken is logged)."""

from __future__ import annotations

from friday.calls.numbers import canonical
from friday.robin.alerts import RobinAlert
from friday.robin.authority import AuthorityService, DryRunAuthorityCaller
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, Tier
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE, at

NO = CallOutcome(result=CallResult.NO_ANSWER)


def said(who: str, urgent: str | None = None):
    out = [AnswerRaw(line="missed.ask_who", text=who)]
    if urgent is not None:
        out.append(AnswerRaw(line="missed.ask_urgent", text=urgent))
    return out


async def desk(w, *, second=False, authority=True, dry=True, name="Ramesh Kumar", address="12 Park Road, Delhi"):
    fam, parent = await w.family(second=second, checkin="21:30")
    parent.name, parent.address = name, address
    await w.store.save_member(parent, fam.owner_user_id)
    await w.hub.fam.admin_consent(fam, "device_signals")
    await w.hub.fam.admin_consent(fam, "payment_alerts")
    if authority:
        await w.hub.fam.admin_consent(fam, "authority_calls")
    w.settings.robin_authority_calls_enabled = authority
    w.settings.robin_authority_dry_run = dry
    w.hub.authority.caller = DryRunAuthorityCaller()
    return fam, parent


# ---------------------------------------------------------------- missed calls
async def test_child_calls_parent_who_misses_it_parent_gets_text_and_voice_note(w):
    fam, parent = await w.family()
    steps = await w.hub.missed.steps_for(fam)
    assert [s.line for s in steps] == ["missed.ask_who", "missed.ask_urgent"]
    res = await w.hub.on_missed_call(PARENT_PHONE, CHILD_PHONE, said("kal ghar aaunga, khana mat banana", "nahi"))
    assert res and not res.urgent and res.incident_id is None
    assert w.channel.texts and "kal ghar aaunga" in w.channel.texts[-1][1] and w.channel.voice_notes[-1][2] == "hinglish"
    assert "Asha" in w.channel.texts[-1][1] and not w.caller.calls


async def test_parent_calls_child_who_misses_it_child_gets_whatsapp(w):
    fam, parent = await w.family()
    res = await w.hub.on_missed_call(CHILD_PHONE, PARENT_PHONE, said("sabzi leni thi", "no"))
    assert res and res.missed_role == "child"
    assert "Papa called you but you missed it" in w.sender.texts()[-1] and "sabzi leni thi" in w.sender.texts()[-1]
    assert await w.hub.on_missed_call("+919811111111", CHILD_PHONE, said("x")) is None  # not a family number


async def test_urgent_missed_call_rings_every_3_minutes_max_6_tries_even_in_quiet_hours(w):
    fam, parent = await w.family()
    w.clock.set(at(23, 30))  # quiet hours do not apply to an emergency
    w.caller.script(NO)
    res = await w.hub.on_missed_call(PARENT_PHONE, CHILD_PHONE, said("papa ko gir gaya, jaldi call karo", "haan"))
    assert res.urgent and res.incident_id
    assert "ZAROORI" in w.channel.texts[-1][1] and "papa ko gir gaya" in w.channel.texts[-1][1]
    for _ in range(40):
        w.go(minutes=1)
        await w.hub.tick()
    rings = [c for c in w.caller.calls if c.purpose == "emergency_ring"]
    assert len(rings) == 6 and rings[0].line_keys == ["missed.emergency_ring"]
    times = [r.at for r in await w.store.list(fam.id, "audit") if r.data.get("purpose") == "emergency_ring" and r.data.get("event") == "call"]
    assert [round((t - times[0]).total_seconds() / 60) for t in times] == [0, 3, 6, 9, 12, 15]


async def test_urgent_ringing_stops_on_pickup_ack_and_i_am_fine(w):
    fam, parent = await w.family(checkin="21:30")
    w.caller.script(NO, NO, CallOutcome(result=CallResult.ANSWERED))
    r = await w.hub.on_missed_call(PARENT_PHONE, CHILD_PHONE, said("urgent", "yes"))
    for _ in range(30):
        w.go(minutes=1)
        await w.hub.tick()
    assert len([c for c in w.caller.calls if c.purpose == "emergency_ring"]) == 3  # picked up on the third try: stop
    assert r.incident_id
    # parent says "I am fine" -> stops
    w.go(minutes=5)
    w.caller.script(NO)
    r2 = await w.hub.on_missed_call(PARENT_PHONE, CHILD_PHONE, said("emergency", "haan"))
    n = len([c for c in w.caller.calls if c.purpose == "emergency_ring"])
    assert (await w.hub.parent_said(PARENT_PHONE, "main theek hoon", "text")).action == "fine"
    for _ in range(20):
        w.go(minutes=1)
        await w.hub.tick()
    assert len([c for c in w.caller.calls if c.purpose == "emergency_ring"]) == n
    assert (await w.store.get(r2.incident_id)).status == "closed"


async def test_urgent_when_the_child_misses_the_parents_call(w):
    fam, parent = await w.family()
    w.caller.script(NO)
    res = await w.hub.on_missed_call(CHILD_PHONE, PARENT_PHONE, said("mujhe chakkar aa raha hai ambulance", None))
    assert res.urgent  # a strong danger word is enough
    assert "every 3 minutes" in w.sender.texts()[-1]
    assert w.caller.calls[0].role == "child" and w.caller.calls[0].purpose == "emergency_ring"
    assert await w.hub.alerts.stop(fam, None, "child_has_it")


# ---------------------------------------------------------------- authority module (dry run only)
async def test_everything_off_by_default(w):
    fam, parent = await w.family()
    assert w.settings.robin_authority_calls_enabled is False and w.settings.robin_authority_dry_run is True
    await w.hub.fam.admin_consent(fam, "device_signals")
    r = await w.hub.sos.trigger(parent.id, "app")
    for _ in range(10):
        w.go(minutes=3)
        await w.hub.tick()
    assert r.alert.accepted and not w.hub.authority.caller.logged
    rows = await w.store.list(fam.id, "audit")
    assert any("switch_off" in x.data["text"] for x in rows if x.data["event"] == "authority")


async def test_sos_with_unreachable_child_and_unresponsive_parent_reaches_the_dry_run_after_all_preconditions(w):
    fam, parent = await desk(w)
    w.caller.script(NO)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    log = w.hub.authority.caller.logged
    assert len(log) == 1 and log[0]["kind"] == "112" and log[0]["bridge_with"] is None
    s = log[0]["script"]
    assert "Ramesh Kumar" in s and "12 Park Road, Delhi" in s and "+919800000101" in s and "automatic call" in s  # name, address, callback, calm fixed script
    assert "DRY RUN" in w.sender.texts()[-1]
    assert any("DRY RUN (nothing dialled)" in r.data["text"] for r in await w.store.list(fam.id, "audit"))
    # the telephony fake only ever rang family numbers: no authority number was dialled or simulated
    assert {c.role for c in w.caller.calls} <= {"child", "parent", "second_contact"}
    for _ in range(10):
        w.go(minutes=3)
        await w.hub.tick()
    assert len(w.hub.authority.caller.logged) == 1  # hard cap: one authority call per incident
    assert canonical("112") is None and canonical("1930") is None  # the CallGate keeps refusing emergency numbers


async def test_parent_saying_fine_in_the_countdown_cancels(w):
    fam, parent = await desk(w)
    fine = CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="authority.countdown", text="main theek hoon")])
    w.caller.script(NO, NO, NO, fine)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    assert not w.hub.authority.caller.logged
    assert any("cancelled" in r.data["text"] for r in await w.store.list(fam.id, "audit") if r.data["event"] == "authority")


async def test_a_parent_on_the_line_gets_the_60_second_window_and_mark_safe_cancels(w):
    fam, parent = await desk(w)
    on_line = CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="authority.countdown", text="")])
    w.caller.script(NO, NO, NO, on_line)
    r = await w.hub.sos.trigger(parent.id, "app")
    for _ in range(4):
        w.go(minutes=5)
        await w.hub.alerts.tick()
    auth = await w.store.by_key(fam.id, "pending", f"auth:{r.alert.incident_id}"[:64])
    assert auth and auth.status == "countdown" and not w.hub.authority.caller.logged
    assert any("authority.countdown" in c.line_keys[0] for c in w.caller.calls)
    assert "60 seconds" in " ".join(w.sender.texts())
    await w.hub.alerts.on_button(fam, r.alert.incident_id, "safe")  # Mark safe during the window
    w.go(seconds=70)
    await w.hub.authority.tick()
    assert not w.hub.authority.caller.logged


async def test_without_a_cancel_the_call_goes_out_when_the_window_ends(w):
    fam, parent = await desk(w)
    on_line = CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="authority.countdown", text="")])
    w.caller.script(NO, NO, NO, on_line)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(3):
        w.go(minutes=5)
        await w.hub.alerts.tick()
    assert not w.hub.authority.caller.logged
    await w.hub.authority.tick()
    assert not w.hub.authority.caller.logged  # still inside the window
    w.go(seconds=61)
    await w.hub.authority.tick()
    assert len(w.hub.authority.caller.logged) == 1


async def test_missing_preconditions_each_refuse(w):
    for kwargs, why in (({"authority": False}, "no_consent"), ({"name": "", "address": ""}, "no_name_or_address")):
        w.hub.authority.caller = DryRunAuthorityCaller()
        fam, parent = await desk(w, **kwargs)
        w.settings.robin_authority_calls_enabled = True  # switch on, but consent / profile missing
        w.caller.script(NO)
        await w.hub.sos.trigger(parent.id, "app")
        for _ in range(8):
            w.go(minutes=3)
            await w.hub.tick()
        assert not w.hub.authority.caller.logged, why
        assert any(why in r.data["text"] for r in await w.store.list(fam.id, "audit") if r.data["event"] == "authority")
        await w.hub.fam.erase(fam)
        w.go(hours=1)


async def test_one_signal_is_not_a_confirmed_emergency_and_parent_yes_is(w):
    fam, parent = await desk(w)
    w.caller.script(CallOutcome(result=CallResult.ANSWERED))  # the child picks up the first call: the ladder did NOT fail
    r = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "medical", "Papa fell and is not answering", category="physical", signals=("device_fall",)))
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    assert not w.hub.authority.caller.logged  # one signal only
    inc = await w.store.get(r.incident_id)
    assert inc.data["child_reached"] is True
    # the parent says yes -> enough on its own
    w.go(minutes=10)
    w.caller.script(NO)
    r2 = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "medical", "Papa says chest pain", category="physical", signals=("parent_said_help",), dedupe_key="m2"))
    assert await w.hub.alerts.confirm_emergency(fam, r2.incident_id, "parent")
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    assert len(w.hub.authority.caller.logged) == 1 and w.hub.authority.caller.logged[0]["kind"] == "112"


async def test_fraud_never_calls_112_it_bridges_the_child_to_1930_and_drafts_the_complaint(w):
    fam, parent = await desk(w)
    w.caller.script(NO)
    r = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S5", "Rs 49,000 sent to a new payee during a call", money=True, amount_text="Rs 49,000", signals=("pattern_s1", "payment_alert")))
    for _ in range(30):
        w.go(minutes=3)
        await w.hub.tick()
    log = w.hub.authority.caller.logged
    assert log and all(x["kind"] == "1930" for x in log) and log[0]["bridge_with"]  # conference with the child; Robin does not speak alone
    assert not any(x["kind"] == "112" for x in log) and len(log) == 1
    complaint = [t for t in w.sender.texts() if "cybercrime.gov.in" in t]
    assert complaint and "Rs 49,000" in complaint[0] and "did not file anything" in complaint[0]
    _ = r


async def test_fraud_without_money_and_distress_never_call(w):
    fam, parent = await desk(w)
    w.caller.script(NO)
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "digital-arrest pattern", signals=("a", "b")))
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "distress", "Papa sounds very low", signals=("a", "b"), dedupe_key="d"))
    for _ in range(30):
        w.go(minutes=3)
        await w.hub.tick()
    assert not w.hub.authority.caller.logged
    assert any("care protocol" in t for t in w.sender.texts())  # distress is handed to the care protocol, nobody official is called


async def test_no_live_adapter_exists_so_dry_run_off_refuses(w):
    fam, parent = await desk(w, dry=False)
    w.caller.script(NO)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    assert not w.hub.authority.caller.logged
    assert any("no_live_adapter" in r.data["text"] for r in await w.store.list(fam.id, "audit") if r.data["event"] == "authority")
    assert isinstance(w.hub.authority, AuthorityService) and w.hub.authority.caller.live is False


async def test_threat_words_raise_an_emergency_for_the_desk(w):
    fam, parent = await desk(w)
    w.caller.script(NO)
    reply = await w.hub.parent_said(PARENT_PHONE, "mujhe dhamki mil rahi hai", "voice_note")
    assert reply and reply.action == "sos"
    inc = (await w.store.list(fam.id, "incident"))[-1]
    assert inc.data["scenario"] == "threat" and inc.data["category"] == "physical" and "parent_said_threat" in inc.data["signals"]
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.tick()
    assert len(w.hub.authority.caller.logged) == 1  # threat + the ladder failing to reach the child = two signals
