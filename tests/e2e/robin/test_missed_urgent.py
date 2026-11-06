# ruff: noqa: E501
"""A missed call that the caller says is URGENT: the missed person gets the message with the context and Robin keeps ringing them, every 3 minutes, at most 6
tries, until they pick up, say they are fine, or the child says 'I have it' (tested with fakes). Either direction: parent missed, or child missed."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import IST
from friday.robin.models import AnswerRaw, CallResult
from tests.e2e.robin.harness import CHILD, PARENT, RobinWorld


def answers(who: str, urgent: str) -> list[AnswerRaw]:
    return [AnswerRaw(line="missed.ask_who", text=who), AnswerRaw(line="missed.ask_urgent", text=urgent)]


async def ringing_world(**kw) -> tuple[RobinWorld, list[datetime]]:
    w = await RobinWorld.start(**kw)
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    times: list[datetime] = []
    w.caller.hook = lambda rec: times.append(w.clock.now()) if rec.purpose == "emergency_ring" else None
    return w, times


async def test_urgent_missed_call_to_the_parent_rings_every_three_minutes_up_to_six_times():
    w, times = await ringing_world()
    try:
        w.script_calls(CallResult.NO_ANSWER)
        n_note = len(w.channel.texts)
        res = await w.hub.on_missed_call(PARENT, CHILD, answers("beta ne kaha doctor ke paas jaldi chalna hai", "yes"))
        assert res is not None and res.urgent and res.missed_role == "parent"

        # the message to the parent: text + voice note, with the context, once
        assert len(w.channel.texts) == n_note + 1 and len(w.channel.voice_notes) == 2
        assert "doctor ke paas" in w.channel.texts[-1][1]
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1  # the first ring is immediate

        for _ in range(5):
            await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 6
        assert [b - a for a, b in zip(times, times[1:], strict=False)] == [timedelta(minutes=3)] * 5
        await w.advance(minutes=3)
        await w.advance(hours=1)
        rings = [c for c in w.caller.calls if c.purpose == "emergency_ring"]
        assert len(rings) == 6, "the cap is 6 tries"
        assert all(c.line_keys == ["missed.emergency_ring"] for c in rings)
        (inc,) = [i for i in await w.incidents() if i.data["scenario"] == "missed_urgent"]
        assert inc.status == "exhausted"
        assert w.channel.templates == [] and len(w.channel.texts) == n_note + 1  # the message was sent once, not once per ring
    finally:
        await w.close()


async def test_pickup_stops_the_ringing():
    w, _ = await ringing_world()
    try:
        w.script_calls(CallResult.NO_ANSWER, CallResult.NO_ANSWER, CallResult.ANSWERED)
        await w.hub.on_missed_call(PARENT, CHILD, answers("urgent bank ka kaam", "haan"))
        for _ in range(6):
            await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 3  # 3rd try was picked up: no more
        (inc,) = [i for i in await w.incidents() if i.data["scenario"] == "missed_urgent"]
        assert inc.data["reached"] is True
        assert "alert_closed" in [r.data["event"] for r in await w.audit_rows()]
    finally:
        await w.close()


async def test_parent_saying_they_are_fine_stops_the_ringing():
    w, _ = await ringing_world()
    try:
        w.script_calls(CallResult.NO_ANSWER)
        await w.hub.on_missed_call(PARENT, CHILD, answers("kaam hai", "yes"))
        await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 2
        reply = await w.parent_says("main theek hoon, bol do")
        assert reply is not None and reply.action == "fine"
        await w.advance(minutes=3)
        await w.advance(minutes=30)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 2
        (inc,) = [i for i in await w.incidents() if i.data["scenario"] == "missed_urgent"]
        assert inc.status == "closed" and inc.data["closed_by"] == "parent_fine"
    finally:
        await w.close()


async def test_not_urgent_means_a_message_and_no_ringing():
    w, _ = await ringing_world()
    try:
        w.script_calls(CallResult.NO_ANSWER)
        n = len(w.channel.texts)
        res = await w.hub.on_missed_call(PARENT, CHILD, answers("sabzi wale ka hisaab", "nahi"))
        assert res is not None and not res.urgent and res.incident_id is None
        assert len(w.channel.texts) == n + 1
        await w.advance(minutes=10)
        assert w.calls(purpose="emergency_ring") == []
    finally:
        await w.close()


async def test_urgent_missed_call_at_night_still_rings_the_parent():
    """23:00: quiet hours and outside the calling window; an urgent missed call is allowed to ring."""
    w, _ = await ringing_world(now=datetime(2026, 1, 5, 21, 0, tzinfo=IST))
    try:
        w.script_calls(CallResult.NO_ANSWER)
        w.clock.set(datetime(2026, 1, 5, 23, 0, tzinfo=IST))
        await w.hub.on_missed_call(PARENT, CHILD, answers("urgent hai", "yes"))
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1
        await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 2
    finally:
        await w.close()


async def test_urgent_missed_call_to_the_child_tells_the_child_and_rings_the_child():
    w, _ = await ringing_world()
    try:
        w.script_calls(CallResult.NO_ANSWER)
        n = len(w.child_texts())
        res = await w.hub.on_missed_call(CHILD, PARENT, answers("mujhe dard ho raha hai, jaldi aao", "yes"))
        assert res is not None and res.urgent and res.missed_role == "child"
        fresh = w.child_texts()[n:]
        assert len(fresh) == 1 and "Papa" in fresh[0] and "dard" in fresh[0]  # the child gets who called, when and what was said
        assert len(w.calls(role="child", purpose="emergency_ring")) == 1
        await w.child_says("I have it")
        await w.advance(minutes=3)
        await w.advance(minutes=30)
        assert len(w.calls(role="child", purpose="emergency_ring")) == 1  # 'I have it' stops the ringing
        assert w.calls(role="parent", purpose="emergency_ring") == []
    finally:
        await w.close()


async def test_danger_words_mark_the_incident_physical_and_the_desk_stays_dry():
    w = await RobinWorld.start(robin_authority_calls_enabled=True)
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        w.script_calls(CallResult.NO_ANSWER)
        res = await w.hub.on_missed_call(PARENT, CHILD, answers("Mama ka accident ho gaya, ambulance chahiye", "yes"))
        assert res is not None and res.urgent
        for _ in range(7):
            await w.advance(minutes=3)
        (inc,) = [i for i in await w.incidents() if i.data["scenario"] == "missed_urgent"]
        assert inc.data["category"] == "physical" and "danger_words" in inc.data["signals"]
        assert [s["action"] for s in inc.data["steps"]][-1] == "authority"
        assert len(w.calls(role="parent", purpose="emergency_ring")) >= 6
        # the desk's preconditions (the child's consent to authority calls, a name and an address) are missing: it refuses, dials nothing
        assert w.hub.authority.caller.logged == [] and w.f.c.telephony.legs == []
        whys = [r.data.get("why") for r in await w.audit_rows() if r.data["event"] == "authority"]
        assert whys and set(whys) <= {"no_consent", "not_confirmed", "no_name_or_address"}
    finally:
        await w.close()
