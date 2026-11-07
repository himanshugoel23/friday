# ruff: noqa: E501
"""Founder decision (2026-11-07): SOS and EMERGENCY are exempt from the 3-a-day per-person escalation call cap; every incident keeps its own
ceiling of 3 rings per person. HIGH keeps the daily cap. Tested with fakes (fake dialler, recording sender); nothing is dialled."""

from __future__ import annotations

from friday.robin.context import INCIDENT_CALL_CAP
from friday.robin.models import CallOutcome, CallResult, Step, Tier
from friday.robin.store import Record
from tests.robin.test_alerts_sos import alert, ready


async def _fill_todays_cap(w, fam, child, n=3):
    """n ordinary escalation rings to the child today (as if earlier HIGH alerts had used the day's cap)."""
    w.caller.script(CallResult.NO_ANSWER)
    for i in range(n):
        out = await w.ctx.call(fam, child, "escalation_child", [Step(line="child.ring", slots=await w.ctx.slots(fam))], dedupe_key=f"fill:{i}", security=True, incident_id=f"old{i}")
        assert out.result != CallResult.REFUSED
    assert await w.ctx.calls_today(fam, child) == n


async def test_a_normal_high_call_is_refused_after_three_a_day(w):
    fam, parent = await ready(w)
    child = await w.ctx.child(fam)
    await _fill_todays_cap(w, fam, child)
    out = await w.ctx.call(fam, child, "escalation_child", [Step(line="child.ring", slots=await w.ctx.slots(fam))], dedupe_key="high4", security=True, incident_id="inc-high")
    assert out.result == CallResult.REFUSED and out.detail == "daily_cap"


async def test_sos_still_rings_the_child_after_the_daily_cap_is_used_up(w):
    fam, parent = await ready(w)
    child = await w.ctx.child(fam)
    await _fill_todays_cap(w, fam, child)
    before = len(w.caller.calls)
    res = await w.hub.sos.trigger(parent.id, "app")
    assert res.alert.accepted
    sos_calls = w.caller.calls[before:]
    assert [c.purpose for c in sos_calls] == ["escalation_child"] and sos_calls[0].line_keys == ["child.ring_sos"]  # not refused by daily_cap
    rows = await w.store.list(fam.id, "audit")
    assert not any(r.data.get("detail") == "daily_cap" for r in rows if r.data.get("incident_id") == res.alert.incident_id)


async def test_an_emergency_incident_rings_the_child_after_the_cap_but_never_more_than_three_times(w):
    fam, parent = await ready(w, second=True)
    child = await w.ctx.child(fam)
    await _fill_todays_cap(w, fam, child)
    before = len(w.caller.calls)
    w.caller.script(CallResult.NO_ANSWER)
    r = await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S1", dedupe_key="em1"))
    for _ in range(10):
        w.go(minutes=3)
        await w.hub.alerts.tick()
    rings = [c for c in w.caller.calls[before:] if c.purpose == "escalation_child"]
    assert len(rings) == INCIDENT_CALL_CAP == 3  # the per-incident ceiling stays
    audit = await w.store.list(fam.id, "audit")
    assert not any(a.data.get("detail") == "daily_cap" for a in audit if a.data.get("incident_id") == r.incident_id)


async def test_the_per_incident_ceiling_is_enforced_in_the_one_gated_dial_itself(w):
    fam, parent = await ready(w)
    child = await w.ctx.child(fam)
    w.caller.script(CallResult.NO_ANSWER)
    steps = [Step(line="child.ring_sos", slots=await w.ctx.slots(fam))]
    for i in range(INCIDENT_CALL_CAP):
        out = await w.ctx.call(fam, child, "escalation_child", steps, dedupe_key=f"x:{i}", sos=True, incident_id="inc-1")
        assert out.result == CallResult.NO_ANSWER
    out = await w.ctx.call(fam, child, "escalation_child", steps, dedupe_key="x:4", sos=True, incident_id="inc-1")
    assert out.result == CallResult.REFUSED and out.detail == "incident_cap"
    other = await w.ctx.call(fam, child, "escalation_child", steps, dedupe_key="y:1", sos=True, incident_id="inc-2")  # a NEW incident has its own three rings
    assert other.result == CallResult.NO_ANSWER


async def test_exempt_rings_do_not_use_up_the_days_cap_of_other_alerts(w):
    fam, parent = await ready(w)
    child = await w.ctx.child(fam)
    w.caller.script(CallResult.NO_ANSWER)
    for i in range(3):
        await w.ctx.call(fam, child, "escalation_child", [Step(line="child.ring_sos", slots=await w.ctx.slots(fam))], dedupe_key=f"s:{i}", sos=True, incident_id="inc-s")
    assert await w.ctx.calls_today(fam, child) == 0  # SOS rings are exempt, they are not counted against the day
    out = await w.ctx.call(fam, child, "escalation_child", [Step(line="child.ring", slots=await w.ctx.slots(fam))], dedupe_key="h1", security=True, incident_id="inc-h")
    assert out.result == CallResult.NO_ANSWER


async def test_the_parent_pause_and_kill_switch_still_beat_the_exemption(w):
    fam, parent = await ready(w)
    child = await w.ctx.child(fam)
    steps = [Step(line="child.ring_sos", slots=await w.ctx.slots(fam))]
    w.ctx.paused = lambda: True
    out = await w.ctx.call(fam, child, "escalation_child", steps, dedupe_key="k1", sos=True, incident_id="inc-k")
    assert out.result == CallResult.REFUSED and out.detail == "kill_switch"
    _ = CallOutcome, Record
