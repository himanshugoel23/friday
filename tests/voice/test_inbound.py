"""BRIEF E30-37: inbound call-backs, missed calls, sticky caller ID, retry personas."""

from __future__ import annotations

from friday.core.events import Event
from friday.core.models import CallDirection, CallOutcome, DialStatus, OutboundCallRequest, Speaker

from .conftest import FROSTY, LOOKS, ScriptedPolicy, hangup, make_brief, no_answer_user, say

URBAN_TRIM = "+918040001013"
LIFELINE = "+918040001014"
QUICKFIX = "+918040001010"
BAKERY = "+918040001011"
TAILOR = "+918040001012"
TAILOR_ALT = "+919845001012"


def collect(bus):
    seen: list[Event] = []

    async def rec(e):
        seen.append(e)

    bus.subscribe(Event, rec)
    return seen


def named(seen, name):
    return [e for e in seen if type(e).__name__ == name]


async def dial(sim, phone, **kw):
    leg = await sim.place_call(OutboundCallRequest(to_phone=phone, task_id="t-1", **kw))
    return leg, await leg.wait_for_answer(30)


async def test_sticky_caller_id_and_explicit_from_number(sim):
    a, _ = await dial(sim, LOOKS)
    b, _ = await dial(sim, LOOKS)
    assert a.from_number == b.from_number and a.from_number in sim.friday_numbers
    c, _ = await dial(sim, LOOKS, metadata={"from_number": "+918069110003"})
    assert c.from_number == "+918069110003"
    sim.caller_id_selector = lambda to, req: "+918069110002"
    d, _ = await dial(sim, FROSTY)
    assert d.from_number == "+918069110002"


async def test_runner_records_from_number(make_runner):
    result = await make_runner(ScriptedPolicy([hangup(CallOutcome.PARTIAL)])).run(
        make_brief(), no_answer_user, from_number="+918069110002"
    )
    assert result.from_number == "+918069110002"


async def test_busy_vs_no_answer_distinct(sim):
    assert (await dial(sim, BAKERY))[1] == DialStatus.BUSY
    assert (await dial(sim, TAILOR))[1] == DialStatus.NO_ANSWER


async def test_no_answer_first_n_attempts_then_answers(sim):
    statuses = [(await dial(sim, QUICKFIX))[1] for _ in range(3)]
    assert statuses == [DialStatus.NO_ANSWER, DialStatus.NO_ANSWER, DialStatus.ANSWERED]


async def test_primary_never_answers_alternate_works(sim, make_runner):
    assert (await dial(sim, TAILOR))[1] == DialStatus.NO_ANSWER
    leg, status = await dial(sim, TAILOR_ALT)
    assert status == DialStatus.ANSWERED
    greeting = await leg.listen(5)
    assert "Perfect Fit" in greeting.text
    # through the runner too: target the alternate number directly
    policy = ScriptedPolicy([say("Blouse ready hai kya?"), hangup(CallOutcome.SUCCESS)])
    result = await make_runner(policy).run(make_brief(TAILOR_ALT, "Perfect Fit"), no_answer_user)
    assert result.outcome == CallOutcome.SUCCESS


async def test_late_callback_after_outbound(sim, fclock, vbus, make_runner):
    seen = collect(vbus)
    # Friday reaches Urban Trim via its alternate route? No: primary rings out, but the
    # business notices the missed call and calls back 30 min later (E31/E37).
    sim.world.by_phone(URBAN_TRIM).persona.answer = "answers"  # first call answered
    policy = ScriptedPolicy(
        [say("Kal 5pm haircut ka slot hai?"), hangup(CallOutcome.PENDING_APPROVAL)]
    )
    first = await make_runner(policy).run(make_brief(URBAN_TRIM, "Urban Trim"), no_answer_user)
    sim.world.by_phone(URBAN_TRIM).persona.answer = "no_answer"
    assert await sim.deliver_due_inbound() == []  # not due yet
    fclock.advance(1801)
    ids = await sim.deliver_due_inbound()
    assert len(ids) == 1
    ev = named(seen, "InboundCallReceived")[0]
    assert ev.from_phone == URBAN_TRIM and ev.to_number == first.from_number
    assert ev.provider_call_id == ids[0]
    leg = sim.take_inbound(ev.provider_call_id)
    assert leg is not None and sim.take_inbound(ev.provider_call_id) is None

    # Backend B call order: run_inbound(leg, brief, ask_user, notify_user)
    policy = ScriptedPolicy(
        [
            say(
                "Rahul ki requirement ab poori ho gayi hai, isliye is baar zaroorat nahi hai. "
                "Dhanyavaad!"
            ),
            hangup(CallOutcome.DECLINED, None),
        ]
    )
    result = await make_runner(policy).run_inbound(
        leg,
        make_brief(URBAN_TRIM, "Urban Trim"),
        no_answer_user,
        None,
        context="Aapne humein call kiya tha haircut ke baare mein.",
    )
    assert result.direction == CallDirection.INBOUND
    assert result.dial_status == DialStatus.ANSWERED
    first_friday = next(t for t in result.transcript.turns if t.speaker == Speaker.FRIDAY)
    assert first_friday.text.startswith("Hi, main Friday hoon, ek AI assistant.")
    assert "Rahul" in first_friday.text and "haircut" in first_friday.text
    assert result.outcome == CallOutcome.DECLINED
    assert result.from_number == first.from_number


async def test_inbound_brief_first_order_and_run_kwarg(sim, make_runner):
    cid = await sim.simulate_inbound_call(LOOKS, "+918069110001")
    leg = sim.take_inbound(cid)
    policy = ScriptedPolicy([hangup(CallOutcome.PARTIAL, "Thank you, I'll update Rahul.")])
    runner = make_runner(policy)
    result = await runner.run(make_brief(), no_answer_user, inbound_leg=leg)
    assert result.direction == CallDirection.INBOUND
    # the caller's greeting is heard after Friday's disclosure
    assert result.transcript.turns[0].speaker == Speaker.FRIDAY


async def test_missed_call_after_outbound(sim, fclock, vbus, make_runner):
    seen = collect(vbus)
    policy = ScriptedPolicy([say("Insulin glargine available hai?"), hangup(CallOutcome.SUCCESS)])
    await make_runner(policy).run(make_brief(LIFELINE, "Lifeline Medicos"), no_answer_user)
    fclock.advance(601)
    assert await sim.deliver_due_inbound() == []
    missed = named(seen, "MissedCallReceived")
    assert len(missed) == 1 and missed[0].from_phone == LIFELINE
    assert missed[0].to_number in sim.friday_numbers and missed[0].ring_seconds > 0
    assert not named(seen, "InboundCallReceived")


async def test_unknown_inbound_caller(sim, vbus):
    seen = collect(vbus)
    cid = await sim.simulate_inbound_call("+919700000000")
    assert cid and named(seen, "InboundCallReceived")[0].business_id is None
    leg = sim.take_inbound(cid)
    assert (await leg.listen(5)).text  # default party says something


async def test_simulated_missed_call_api(sim, vbus):
    seen = collect(vbus)
    assert await sim.simulate_inbound_call(LOOKS, answered=False, ring_s=3) is None
    ev = named(seen, "MissedCallReceived")[0]
    assert ev.reason == "short_ring" and ev.provider == "simulator"
