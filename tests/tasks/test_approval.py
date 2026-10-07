"""Founder approval rule: PENDING_APPROVAL -> AWAITING_APPROVAL -> CONFIRMATION_CALLBACK,
relay a different choice, decline, delegation pass-through, mid-call questions."""

import asyncio

from friday.core.events import MidCallQuestionAsked
from friday.core.models import (
    CallOutcome,
    Delegation,
    InteractionKind,
    MidCallQuestion,
    QuestionPurpose,
    TaskStatus as S,
    UserAnswer,
    approval_button_id,
    question_button_id,
)
from tests.tasks.conftest import LOOKS, booking
from tests.tasks.fakes import offer_then_confirm, outcome, result


async def test_default_callback_flow(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    assert t.status == S.AWAITING_APPROVAL and t.last_outcome == CallOutcome.PENDING_APPROVAL
    first = env.runner.briefs[0]
    assert first.approved_terms is None and not first.delegation.granted
    assert not first.can_commit([])  # never confirm on the first call
    q = t.result.needs_approval
    assert q.purpose == QuestionPurpose.APPROVE_BOOKING and q.options[-1] == "None"
    msg = env.notifier.last()
    assert [b.id for b in msg.buttons] == [question_button_id(q.id, i) for i in range(len(q.options))]
    assert msg.template is not None  # template fallback for outside the 24h window

    assert await env.engine.handle_button(env.user.id, question_button_id(q.id, 1))
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED
    second = env.runner.briefs[1]
    assert second.approved_terms.startswith("6pm") and second.can_commit([])
    assert [p for p in env.transitions if p[1] == S.CONFIRMATION_CALLBACK]
    # vendor memory + business touch + report
    kinds = env.repos.businesses.kinds()
    assert InteractionKind.QUOTED in kinds and InteractionKind.BOOKED in kinds
    assert any(m.template and m.template.key == "business_booking_confirmed"
               for m in env.notifier.to_business())
    assert "Booked Looks" in env.texts()[-1]
    assert len(env.repos.tasks.calls) == 2
    assert {m.friday_number for m in env.repos.calls.memory} == {"+918069110002"} or len(
        {m.friday_number for m in env.repos.calls.memory}) == 1  # sticky caller-ID


async def test_approval_via_a_button_and_handle_answer(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    await env.engine.handle_button(env.user.id, approval_button_id(t.id, True))
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED
    assert env.runner.briefs[-1].approved_terms.startswith("4pm")
    # foreign user can't approve
    assert not await env.engine.handle_button("someone-else", approval_button_id(t.id, True))


async def test_relay_different_choice_then_new_offer(env):
    async def sunday_only(brief, ask, notify):
        return result(brief, CallOutcome.PENDING_APPROVAL, collected={"summary": "Sunday 11am ok?"})

    env.runner.script(LOOKS, offer_then_confirm("Looks", 400), sunday_only)
    t = await env.task(booking())
    q = t.result.needs_approval
    await env.engine.handle_answer(UserAnswer(question_id=q.id, text="neither, ask for Sunday"))
    await env.engine.drain()
    assert env.runner.briefs[1].approved_terms == "User asked instead: neither, ask for Sunday"
    t = await env.get(t.id)
    assert t.status == S.AWAITING_APPROVAL  # new offer goes back through the call-back route
    assert (S.CONFIRMATION_CALLBACK, S.AWAITING_APPROVAL) in env.transitions


async def test_decline_cancels_and_tells_business(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    q = t.result.needs_approval
    await env.engine.handle_button(env.user.id, question_button_id(q.id, len(q.options) - 1))
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.CANCELLED
    assert any(m.template.key == "business_booking_declined" for m in env.notifier.to_business())
    assert len(env.runner.briefs) == 1


async def test_approve_false_rejects(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    await env.engine.approve(t.id, False)
    assert (await env.get(t.id)).status == S.CANCELLED


async def test_delegation_pass_through_confirms_on_call(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    d = Delegation(granted=True, max_price_inr=800, scope=["slot"], user_words="any slot, you decide")
    t = await env.task(booking(delegation=d))
    assert t.status == S.COMPLETED and len(env.runner.briefs) == 1
    brief = env.runner.briefs[0]
    assert brief.delegation.granted and brief.delegation.max_price_inr == 800
    assert InteractionKind.BOOKED in env.repos.businesses.kinds()


async def test_engine_overrides_brain_invented_authority(env):
    env.brain.inject_delegation = True  # a buggy brain must not grant authority
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    assert not env.runner.briefs[0].delegation.granted
    assert env.runner.briefs[0].approved_terms is None
    assert t.status == S.AWAITING_APPROVAL


async def test_mid_call_question_answered(env):
    async def asks(brief, ask_user, notify):
        q = MidCallQuestion(task_id=brief.task_id, text="Male or female stylist?",
                            options=["Male", "Female"], timeout_s=5)
        ans = await ask_user(q)
        return result(brief, CallOutcome.PENDING_APPROVAL, collected={"summary": f"ok {ans.text}"})

    async def answer_it(ev: MidCallQuestionAsked):
        async def later():
            assert env.engine.pending_question(env.user.id).id == ev.question.id
            t = await env.get(ev.question.task_id)
            assert t.status == S.AWAITING_USER
            await env.engine.handle_button(env.user.id, question_button_id(ev.question.id, 1))

        asyncio.ensure_future(later())

    env.bus.subscribe(MidCallQuestionAsked, answer_it)
    env.runner.script(LOOKS, asks)
    t = await env.task(booking())
    assert t.result.summary == "ok Female"
    assert (S.CALLING, S.AWAITING_USER) in env.transitions
    assert (S.AWAITING_USER, S.CALLING) in env.transitions
    assert env.engine.pending_question(env.user.id) is None


async def test_mid_call_question_timeout(env):
    seen = {}

    async def asks(brief, ask_user, notify):
        q = MidCallQuestion(task_id=brief.task_id, text="?", options=["a"], timeout_s=0)
        seen["answer"] = await ask_user(q)
        await notify("still holding")
        return result(brief, CallOutcome.USER_TIMEOUT)

    env.runner.script(LOOKS, asks)
    t = await env.task(booking())
    assert seen["answer"] is None
    assert t.status == S.FAILED
    assert any("still holding" in x for x in env.texts())


async def test_user_timeout_with_quote_goes_callback_route(env):
    env.runner.script(LOOKS, outcome(CallOutcome.USER_TIMEOUT, quotes=[]))
    from tests.tasks.fakes import quote

    env.runner.scripts[LOOKS] = [outcome(CallOutcome.USER_TIMEOUT, quotes=[quote("Looks", 400)])]
    t = await env.task(booking())
    assert t.status == S.AWAITING_APPROVAL


async def test_cancel_during_call(env):
    env.runner.gate = asyncio.Event()
    t = await env.engine.create_task(env.user.id, booking())
    for _ in range(20):
        await asyncio.sleep(0)
    assert (await env.get(t.id)).status == S.CALLING
    await env.engine.cancel(t.id)
    env.runner.gate.set()
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.CANCELLED
    assert "Cancelled." in env.texts()


async def test_polite_cancel_uses_runner_cancel(env):
    cancelled = []
    env.runner.gate = asyncio.Event()

    def polite(task_id):
        cancelled.append(task_id)
        env.runner.gate.set()

    env.runner.cancel = polite
    env.runner.default = outcome(CallOutcome.CANCELLED)
    t = await env.engine.create_task(env.user.id, booking())
    for _ in range(20):
        await asyncio.sleep(0)
    await env.engine.cancel(t.id)
    await env.engine.drain()
    assert cancelled == [t.id] and (await env.get(t.id)).status == S.CANCELLED


async def test_submit_preexisting_task_and_update_spec(env):
    from friday.core.models import Task

    spec = booking(phone=None, name=None)
    spec.missing = ["business_phone"]
    task = Task(requester_user_id=env.user.id, type=spec.type, spec=spec)
    await env.repos.tasks.add(task)  # the inbound pipeline persists first
    await env.engine.submit(task)
    await env.engine.drain()
    assert (await env.get(task.id)).status == S.NEEDS_INFO
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    await env.engine.update_spec(task.id, booking())
    await env.engine.drain()
    assert (await env.get(task.id)).status == S.AWAITING_APPROVAL
    assert (S.NEEDS_INFO, S.PLANNING) in env.transitions
