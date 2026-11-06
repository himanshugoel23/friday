# ruff: noqa: E501
"""SOS from the parent's phone: it ALWAYS reaches the child (even before setup is finished); with an unreachable child the AI emergency desk only writes a
DRY-RUN record (no call to 112 or anyone official, nothing dialled). Tested with fakes."""

from __future__ import annotations

from friday.robin.authority import DryRunAuthorityCaller
from friday.robin.models import CallResult
from tests.e2e.robin.harness import RobinWorld, line


async def desk_world(**settings) -> RobinWorld:
    """Active family with a second contact, the desk's consent, the parent's name and address, the phone paired. Authority switch ON (dry-run default)."""
    w = await RobinWorld.start(device=True, robin_authority_calls_enabled=True, **settings)
    w.script_calls(CallResult.ANSWERED)
    from tests.e2e.robin.harness import SECOND

    async def second_sender(member, text):
        return None

    w.hub.ctx.extra_senders["second"] = second_sender
    await w.setup_family(second=SECOND)
    await w.child_says("enable authority calls")
    await w.child_says("parent name Ramesh Verma")
    await w.child_says("address 12 Test Lane, Pune")
    parent = await w.parent()
    await w.device.pair(parent.id)
    return w


def authority_calls(w: RobinWorld) -> DryRunAuthorityCaller:
    caller = w.hub.authority.caller
    assert isinstance(caller, DryRunAuthorityCaller) and caller.live is False
    return caller


# ---------------------------------------------------------------------------- SOS before the family is ACTIVE
async def test_sos_before_setup_is_finished_still_tells_and_rings_the_child(dworld):
    w = dworld
    await w.child_says("set up Robin for my father")
    await w.child_says("+919800000102")  # the parent exists; no language, no consent, no notice: the family is still ONBOARDING
    parent = await w.parent()
    assert (await w.family()).status.value == "onboarding"
    await w.device.pair(parent.id)
    w.script_calls(CallResult.NO_ANSWER)
    n = len(w.child_texts())

    r = await w.device.sos()
    assert r.status_code == 200 and r.json()["ok"] is True

    fresh = w.child_texts()[n:]
    assert len(fresh) == 1 and fresh[0].startswith("SOS: Papa pressed the help button")  # one WhatsApp, at once
    assert [c.purpose for c in w.calls(role="child")] == ["escalation_child"]  # and a ring, even though the child has not said 'yes' to calls yet
    await w.advance(minutes=5)
    await w.advance(minutes=5)
    await w.advance(hours=1)
    assert [c.purpose for c in w.calls(role="child")] == ["escalation_child"] * 3  # 3 rings, then it stops
    assert w.calls(role="parent") == [] and w.calls(role="second_contact") == []  # nobody else is touched before consent
    assert [c.line_keys for c in w.calls(role="child")] == [["child.ring_sos"]] * 3
    assert await w.authority_records() == [] and authority_calls(w).logged == []
    assert w.f.c.telephony.legs == []  # nothing reached the (simulated) phone network
    assert w.channel.texts == [] and w.channel.voice_notes == []  # the parent was not messaged either


async def test_sos_with_no_consent_at_all_and_with_a_paused_robin_still_reaches_the_child(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    parent = await w.parent()
    await w.device.pair(parent.id)
    await w.parent_says("Robin, band karo")  # the parent stopped everything
    w.script_calls(CallResult.NO_ANSWER)
    n = len(w.child_texts())
    r = await w.device.sos()
    assert r.status_code == 200
    assert any(t.startswith("SOS:") for t in w.child_texts()[n:])
    assert len(w.calls(role="child")) == 1


async def test_a_second_press_inside_five_minutes_is_the_same_incident(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    await w.device.pair((await w.parent()).id)
    w.script_calls(CallResult.NO_ANSWER)
    await w.device.sos()
    n = len(w.child_texts())
    await w.advance(minutes=1)
    await w.device.sos()
    assert len(w.child_texts()) == n and len(await w.incidents()) == 1


# ---------------------------------------------------------------------------- the desk: dry-run only
async def test_sos_with_an_unreachable_child_writes_only_a_dry_run_authority_record():
    w = await desk_world()
    try:
        w.script_calls(CallResult.NO_ANSWER)
        await w.device.sos()
        for _ in range(4):  # 0, 5, 10, 15 minutes: child rings x3, second contact x1, then the desk step
            await w.advance(minutes=5)
        await w.advance(minutes=5)

        (inc,) = await w.incidents()
        assert inc.data["scenario"] == "sos" and inc.data["tier"] == "emergency"
        assert [s["action"] for s in inc.data["steps"]] == ["wa_child", "wa_second", "call_child", "call_child", "call_second", "call_child", "authority"]
        # exactly one DRY-RUN record, for 112, and nothing was dialled anywhere
        (rec,) = await w.authority_records()
        assert rec.status == "dry_run"
        logged = authority_calls(w).logged
        assert len(logged) == 1 and logged[0]["kind"] == "112" and logged[0]["bridge_with"] is None
        assert "Ramesh Verma" in logged[0]["script"] and "12 Test Lane" in logged[0]["script"]  # what it WOULD say, for the founder to read
        assert w.f.c.telephony.legs == []
        members = {m.id: m.role.value for m in await w.store.members((await w.family()).id)}
        assert all(c.member_id in members for c in w.caller.calls), "the fake phone was only ever asked to ring family members"
        authority_rows = [r.data for r in await w.audit_rows() if r.data["event"] == "authority"]
        assert any("DRY RUN (nothing dialled)" in r["text"] for r in authority_rows) and all(r.get("dry_run", True) for r in authority_rows)
        assert any("112" in t and "dry" in t.lower() for t in w.child_texts()), "the child is told what the desk would have done, and that it was a dry run"

        # caps: 3 rings per person per incident; the parent was rung once (the 60-second 'I am fine' window), nobody more than 3 times
        assert len(w.calls(role="child")) == 3 and len(w.calls(role="second_contact")) == 1
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1
        for who in ("child", "second_contact"):
            assert len(w.calls(role=who)) <= 3
        n = len([c for c in w.caller.calls if c.purpose != "checkin"])
        await w.advance(hours=3)
        assert len([c for c in w.caller.calls if c.purpose != "checkin"]) == n and len(authority_calls(w).logged) == 1  # one authority record per incident, ever
    finally:
        await w.close()


async def test_child_who_picks_up_stops_the_desk_before_it_acts():
    w = await desk_world()
    try:
        w.script_calls(CallResult.ANSWERED)  # the child answers the first ring
        await w.device.sos()
        await w.advance(minutes=5)
        await w.advance(minutes=30)
        assert authority_calls(w).logged == []
        refusals = [r.data["text"] for r in await w.audit_rows() if r.data["event"] == "authority"]
        assert refusals == [] or all("did not contact" in t for t in refusals)
        assert len(w.calls(role="child")) == 1  # answered: no more rings
    finally:
        await w.close()


async def test_mark_safe_cancels_a_running_countdown():
    w = await desk_world(robin_authority_countdown_s=120)
    try:
        w.script_calls(CallResult.NO_ANSWER, CallResult.NO_ANSWER, CallResult.NO_ANSWER, CallResult.NO_ANSWER, CallResult.ANSWERED)
        w.caller.answers = {"authority.countdown": "nahi"}  # the parent picks up the countdown call but does not say 'I am fine'
        await w.device.sos()
        for _ in range(3):
            await w.advance(minutes=5)
        (rec,) = await w.authority_records()
        assert rec.status == "countdown"  # waiting for the window to end
        assert authority_calls(w).logged == []
        await w.tap("safe")  # the child says it is handled
        (rec,) = await w.authority_records()
        assert rec.status == "cancelled"
        await w.advance(minutes=10)
        assert authority_calls(w).logged == []
    finally:
        await w.close()


async def test_switch_off_means_no_record_and_dry_run_off_without_an_adapter_refuses():
    for settings, why in (({}, "switch_off"), ({"robin_authority_dry_run": False}, "no_live_adapter")):
        w = await RobinWorld.start(device=True, **{"robin_authority_calls_enabled": why == "no_live_adapter", **settings})
        try:
            w.script_calls(CallResult.ANSWERED)
            await w.setup_family()
            await w.child_says("enable authority calls")
            await w.child_says("parent name Ramesh Verma")
            await w.child_says("address 12 Test Lane, Pune")
            await w.device.pair((await w.parent()).id)
            w.script_calls(CallResult.NO_ANSWER)
            await w.device.sos()
            for _ in range(5):
                await w.advance(minutes=5)
            assert authority_calls(w).logged == [], why
            assert why in [r.data.get("why") for r in await w.audit_rows() if r.data["event"] == "authority"], why
            assert w.f.c.telephony.legs == []
        finally:
            await w.close()


async def test_the_line_the_child_reads_on_sos_is_the_fixed_line(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    await w.device.pair((await w.parent()).id)
    await w.device.sos()
    assert any(line("sos.child", loc="") in t for t in w.child_texts())
