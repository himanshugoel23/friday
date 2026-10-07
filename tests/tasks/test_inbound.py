"""BRIEF E.30-37: call memory + sticky caller-ID, business call-backs, missed calls,
business messages, late call-backs after the task resolved."""

from friday.core.models import (
    Business,
    CallOutcome,
    Channel,
    InboundMessage,
    InteractionKind,
    NumberVerdict,
    TaskSpec,
    TaskType,
)
from friday.core.models import (
    TaskStatus as S,
)
from friday.tasks.engine import ROLE_CALLBACK, ROLE_CLOSE_LOOP, role_of
from friday.tasks.events import BusinessContactLogged
from tests.tasks.conftest import CHILL, COOL, FROSTY, LOOKS, RAJU, booking
from tests.tasks.fakes import offer_then_confirm, outcome, quote, result

LEG = object()


async def offered(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    return await env.task(booking())


async def test_call_memory_sticky_caller_id(env):
    env.runner.default = outcome(CallOutcome.BUSY)
    t = await env.task(booking())
    await env.advance_and_tick(minutes=5)
    mems = [m for m in env.repos.calls.memory if m.task_id == t.id]
    assert len(mems) == 2 and len({m.friday_number for m in mems}) == 1
    assert mems[0].friday_number in env.engine.caller_ids
    assert all(m.business_phone == LOOKS and m.outcome == CallOutcome.BUSY for m in mems)


async def test_callback_resumes_task_with_context_and_approval_rule(env):
    t = await offered(env)
    match = await env.repos.calls.match(LOOKS)
    plan = await env.engine.handle_business_callback(match, None, leg=LEG)
    assert plan.action == "resume" and plan.verified
    leg, brief = env.runner.inbound[0]
    assert leg is LEG
    assert any("We called you earlier on behalf of Rahul" in c for c in brief.constraints)
    assert brief.approved_terms is None and not brief.can_commit([])  # approval rule intact
    t = await env.get(t.id)
    assert t.status == S.AWAITING_APPROVAL  # new offer -> asked again
    assert (S.AWAITING_APPROVAL, S.CALLING) in env.transitions


async def test_callback_on_approved_queued_task_confirms(env):
    t = await offered(env)
    t.approved_terms = "6pm ₹400"
    t.status = S.SCHEDULED
    t.next_attempt_at = env.clock.now()
    await env.repos.tasks.save(t)
    await env.engine.handle_business_callback(await env.repos.calls.match(LOOKS), None, leg=LEG)
    assert env.runner.inbound[0][1].can_commit([])
    assert (await env.get(t.id)).status == S.COMPLETED


async def test_ambiguous_open_tasks_policy_asks_which(env):
    t1 = await offered(env)
    t2 = await offered(env)
    match = await env.repos.calls.match(LOOKS)
    assert match.status == "ambiguous"

    async def picks_second(brief, ask, notify):
        return result(
            brief,
            CallOutcome.PENDING_APPROVAL,
            quotes=[quote("Looks", 380)],
            collected={"task_id": t1.id, "summary": "about the 1st"},
        )

    env.runner.scripts[LOOKS] = [picks_second]
    plan = await env.engine.handle_business_callback(match, None, leg=LEG)
    assert plan.action == "choose_task" and set(plan.task_ids) == {t1.id, t2.id}
    brief = env.runner.inbound[0][1]
    assert any("ask which one" in c and t1.id in c for c in brief.constraints)
    assert (await env.get(t1.id)).result.summary == "about the 1st"
    t2 = await env.get(t2.id)
    assert t2.status == S.AWAITING_APPROVAL and t2.result.needs_approval  # restored


async def test_unknown_caller_takes_message_reveals_nothing(env):
    events = []

    async def on(ev):
        events.append(ev)

    env.bus.subscribe(BusinessContactLogged, on)
    plan = await env.engine.on_inbound_call("+919700000000", "+918069110001", leg=LEG)
    assert plan.action == "take_message"
    brief = env.runner.inbound[0][1]
    assert brief.requester_user_id == "" and not brief.shareable_details
    assert "Do not reveal" in brief.goal
    assert events and events[0].kind == "message_taken"
    assert env.notifier.sent == []


async def test_unverified_caller_gets_no_details_and_is_flagged(env):
    t = await offered(env)
    biz = await env.repos.businesses.get_by_phone(LOOKS)
    biz.verification = NumberVerdict.SUSPICIOUS
    await env.repos.businesses.upsert(biz)
    plan = await env.engine.handle_business_callback(
        await env.repos.calls.match(LOOKS), None, leg=LEG
    )
    assert not plan.verified
    brief = env.runner.inbound[0][1]
    assert brief.shareable_details == {} and any("unverified" in c for c in brief.constraints)
    assert "inbound.caller_mismatch" in env.repos.audit.actions()
    # an unverified missed call is never auto-called back
    n = len(env.runner.briefs)
    plan = await env.engine.handle_missed_call(await env.repos.calls.match(LOOKS))
    await env.engine.drain()
    assert plan.action == "logged" and len(env.runner.briefs) == n
    assert "haven't called back" in env.texts()[-1]
    _ = t


async def test_missed_call_on_open_task_calls_back_now_and_notifies_after_n(env):
    env.runner.script(RAJU, outcome(CallOutcome.NO_ANSWER), offer_then_confirm("Raju", 300))
    t = await env.task(booking(phone=RAJU, name="Raju Plumbing Works"))
    assert t.status == S.SCHEDULED
    env.repos.calls.add_missed(t.id, 3)
    plan = await env.engine.on_missed_call(RAJU)
    await env.engine.drain()
    assert plan.action == "callback_scheduled"
    assert (await env.get(t.id)).status == S.AWAITING_APPROVAL  # called back right away
    assert any("tried to reach me 3 times" in x for x in env.texts())


async def test_missed_call_unmatched_logged(env):
    plan = await env.engine.on_missed_call("+919700000001")
    assert plan.action == "logged" and env.notifier.sent == []


async def test_late_missed_call_about_existing_booking(env):
    t = await offered(env)
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED
    plan = await env.engine.handle_missed_call(await env.repos.calls.match(LOOKS))
    await env.engine.drain()
    assert plan.action == "about_booking"
    child = env.repos.tasks.items[plan.task_ids[1]]
    assert role_of(child) == ROLE_CALLBACK and child.type == TaskType.RECONFIRM
    assert any("tried to reach me" in x for x in env.texts())
    assert child.status == S.AWAITING_APPROVAL  # any change goes back to the user


async def discovery_booked_with_chill(env):
    for p, amt in ((COOL, 699), (FROSTY, 599), (CHILL, 550)):
        env.runner.script(p, offer_then_confirm(p, amt))
    spec = TaskSpec(
        type=TaskType.DISCOVERY,
        goal="AC service",
        discovery_query="AC repair",
        location_text="Indiranagar Bengaluru",
    )
    t = await env.task(spec)
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    await env.engine.choose(t.id, 0)
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED
    return t


async def test_fulfilled_elsewhere_closes_loop_once_quietly(env):
    await discovery_booked_with_chill(env)
    texts_before = len(env.texts())
    env.runner.scripts[COOL] = [outcome(CallOutcome.SUCCESS, collected={"summary": "ok"})]
    plan = await env.engine.handle_missed_call(await env.repos.calls.match(COOL))
    await env.engine.drain()
    assert plan.action == "close_loop"
    child = env.repos.tasks.items[plan.task_ids[1]]
    assert role_of(child) == ROLE_CLOSE_LOOP and child.status == S.COMPLETED
    brief = env.runner.briefs[-1]
    assert not brief.can_commit([]) and "close the loop" in brief.goal
    assert len(env.texts()) == texts_before  # user not bothered
    assert InteractionKind.NOTE in env.repos.businesses.kinds()
    cool_task = env.repos.tasks.items[plan.task_ids[0]]
    assert "loop closed" in cool_task.result.details["late_contact"]
    again = await env.engine.handle_missed_call(await env.repos.calls.match(COOL))
    assert again.action == "logged"  # once only


async def test_materially_better_late_offer_mentioned_once(env):
    await discovery_booked_with_chill(env)

    async def cheaper(brief, ask, notify):
        return result(brief, CallOutcome.PENDING_APPROVAL, quotes=[quote("CoolCare", 400)])

    env.runner.scripts[COOL] = [cheaper]
    await env.engine.handle_business_callback(await env.repos.calls.match(COOL), None, leg=LEG)
    better = [x for x in env.texts() if "offered ₹400" in x]
    assert len(better) == 1 and "without penalty" in better[0] and "won't change" in better[0]
    await env.engine.handle_business_callback(await env.repos.calls.match(COOL), None, leg=LEG)
    assert len([x for x in env.texts() if "offered ₹400" in x]) == 1


async def test_failed_task_reopens_on_missed_call(env):
    env.runner.default = outcome(CallOutcome.NO_ANSWER)
    env.engine.policy.max_attempts = 1
    t = await env.task(booking(phone=RAJU, name="Raju Plumbing Works"))
    assert t.status == S.FAILED
    env.runner.scripts[RAJU] = [offer_then_confirm("Raju", 300)]
    plan = await env.engine.handle_missed_call(await env.repos.calls.match(RAJU))
    await env.engine.drain()
    assert plan.action == "reopen"
    child = env.repos.tasks.items[plan.task_ids[1]]
    assert child.status == S.AWAITING_APPROVAL and child.type == TaskType.BOOKING


async def test_business_messages(env):
    events = []

    async def on(ev):
        events.append(ev)

    env.bus.subscribe(BusinessContactLogged, on)
    t = await offered(env)
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=LOOKS, text="6pm is gone, 7pm ok?")
    plan = await env.engine.handle_business_message(msg, await env.repos.calls.match(LOOKS))
    assert plan.action == "relayed" and '"6pm is gone, 7pm ok?"' in env.texts()[-1]
    # unmatched sender: logged for ops only
    other = InboundMessage(channel=Channel.SMS, from_phone="+919700000002", text="hi")
    assert (await env.engine.handle_business_message(other)).action == "logged"
    assert events[-1].kind == "message_unmatched"
    # resolved need: noted in the summary, user not pinged
    await env.engine.cancel(t.id)
    n = len(env.texts())
    plan = await env.engine.handle_business_message(msg, await env.repos.calls.match(LOOKS))
    assert plan.action == "close_loop" and len(env.texts()) == n
    # flagged sender: logged only
    await env.repos.businesses.upsert(
        Business(name="Looks", phone=LOOKS, verification=NumberVerdict.SCAM)
    )
    t2 = await offered(env)
    plan = await env.engine.handle_business_message(msg, await env.repos.calls.match(LOOKS))
    assert plan.action == "logged" and not plan.verified
    _ = t2
