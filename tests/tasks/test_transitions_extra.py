"""Transitions not naturally hit by the scenario files: confirmation call-back
edge cases, approvals after the window closes, cancellation from every state."""

import asyncio
from datetime import datetime

from friday.core.clock import IST, to_ist
from friday.core.models import (
    CallOutcome,
    MidCallQuestion,
    Task,
    TaskSpec,
    TaskStatus as S,
    TaskType,
    UserAnswer,
)
from friday.core.events import MidCallQuestionAsked
from tests.tasks.conftest import LOOKS, booking
from tests.tasks.fakes import offer_then_confirm, outcome, result


async def offered(env, *confirm_scripts):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400), *confirm_scripts)
    return await env.task(booking())


async def test_approval_after_window_closes_queues_confirmation(env):
    t = await offered(env)
    env.clock.set(datetime(2026, 1, 5, 21, 0, tzinfo=IST))
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.SCHEDULED and t.approved_terms
    assert to_ist(t.next_attempt_at).strftime("%d %H:%M") == "06 09:30"  # next call window
    env.clock.set(t.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED
    assert env.runner.briefs[-1].can_commit([])


async def test_confirmation_call_slot_lost_fails_and_busy_retries(env):
    t = await offered(env, outcome(CallOutcome.BUSY), outcome(CallOutcome.DECLINED))
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.SCHEDULED and t.approved_terms  # busy on the call-back
    await env.advance_and_tick(minutes=5)
    assert (await env.get(t.id)).status == S.FAILED


async def test_question_during_confirmation_call(env):
    async def asks(brief, ask_user, notify):
        ans = await ask_user(MidCallQuestion(task_id=brief.task_id, text="Name on booking?",
                                             options=["Rahul"], timeout_s=5))
        return result(brief, CallOutcome.SUCCESS, collected={"summary": f"booked for {ans.text}"})

    async def answer(ev):
        asyncio.ensure_future(env.engine.handle_answer(
            UserAnswer(question_id=ev.question.id, text="Rahul", option_index=0)))

    env.bus.subscribe(MidCallQuestionAsked, answer)
    t = await offered(env, asks)
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED and t.result.summary == "booked for Rahul"
    assert (S.CONFIRMATION_CALLBACK, S.AWAITING_USER) in env.transitions
    assert (S.AWAITING_USER, S.CONFIRMATION_CALLBACK) in env.transitions


async def test_cancel_while_awaiting_user(env):
    async def asks(brief, ask_user, notify):
        await ask_user(MidCallQuestion(task_id=brief.task_id, text="?", options=["a"], timeout_s=5))
        return result(brief, CallOutcome.CANCELLED)

    async def cancel(ev):
        asyncio.ensure_future(env.engine.cancel(ev.question.task_id))

    env.bus.subscribe(MidCallQuestionAsked, cancel)
    env.runner.script(LOOKS, asks)
    t = await env.task(booking())
    assert (await env.get(t.id)).status == S.CANCELLED
    assert (S.AWAITING_USER, S.CANCELLED) in env.transitions


async def test_cancel_created_needs_info_planning_discovering(env):
    created = Task(requester_user_id=env.user.id, type=TaskType.BOOKING, spec=booking())
    await env.repos.tasks.add(created)
    assert (await env.engine.cancel(created.id)).status == S.CANCELLED

    spec = booking(phone=None, name=None)
    t = await env.task(spec)
    assert t.status == S.NEEDS_INFO
    assert (await env.engine.cancel(t.id)).status == S.CANCELLED

    gate = asyncio.Event()
    verifier = env.container.get("number_verifier")
    real = verifier.verify

    async def slow_verify(*a, **k):
        await gate.wait()
        return await real(*a, **k)

    verifier.verify = slow_verify
    p = await env.engine.create_task(env.user.id, booking(phone="+919800000001", name="X"))
    for _ in range(20):
        await asyncio.sleep(0)
    assert (await env.get(p.id)).status == S.PLANNING
    await env.engine.cancel(p.id)
    gate.set()
    await env.engine.drain()
    assert (await env.get(p.id)).status == S.CANCELLED and not env.runner.briefs

    dgate = asyncio.Event()
    directory = env.container.get("directory")
    real_search = directory.search

    async def slow_search(*a, **k):
        await dgate.wait()
        return await real_search(*a, **k)

    directory.search = slow_search
    d = await env.engine.create_task(env.user.id, TaskSpec(
        type=TaskType.DISCOVERY, goal="AC", discovery_query="AC repair", location_text="Indiranagar"))
    for _ in range(20):
        await asyncio.sleep(0)
    assert (await env.get(d.id)).status == S.DISCOVERING
    await env.engine.cancel(d.id)
    dgate.set()
    await env.engine.drain()
    assert (await env.get(d.id)).status == S.CANCELLED
    for pair in [(S.CREATED, S.CANCELLED), (S.NEEDS_INFO, S.CANCELLED),
                 (S.PLANNING, S.CANCELLED), (S.DISCOVERING, S.CANCELLED)]:
        assert pair in env.transitions


async def test_missed_call_while_awaiting_approval_calls_back(env):
    t = await offered(env)
    plan = await env.engine.handle_missed_call(await env.repos.calls.match(LOOKS))
    await env.engine.drain()
    assert plan.action == "callback_scheduled"
    assert (S.AWAITING_APPROVAL, S.SCHEDULED) in env.transitions
    assert (await env.get(t.id)).status == S.AWAITING_APPROVAL  # new offer, asked again
