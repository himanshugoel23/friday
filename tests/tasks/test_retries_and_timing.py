"""E.36 retries, business-hours queue, number vetting, NEEDS_INFO, abuse limit."""

from datetime import datetime, timedelta

from friday.core.clock import IST, to_ist
from friday.core.models import (
    Business,
    CallOutcome,
    Channel,
    NumberVerdict,
    TaskStatus as S,
    approval_button_id,
    question_button_id,
)
from tests.tasks.conftest import LOOKS, RAJU, SCAM, booking
from tests.tasks.fakes import offer_then_confirm, outcome


async def test_no_answer_retry_schedule_notify_once_then_options(env):
    env.runner.default = outcome(CallOutcome.NO_ANSWER)
    t = await env.task(booking(phone=RAJU, name="Raju Plumbing Works"))
    assert t.status == S.SCHEDULED
    assert t.next_attempt_at - env.clock.now() == timedelta(minutes=10)
    assert sum("isn't picking up" in x for x in env.texts()) == 1
    env.clock.set(t.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.attempts == 2 and t.next_attempt_at - env.clock.now() == timedelta(minutes=45)
    assert sum("isn't picking up" in x for x in env.texts()) == 1  # told only once
    env.clock.set(t.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.FAILED and t.attempts == 3
    last = env.notifier.last()
    assert [b.title for b in last.buttons] == ["Later today", "Tomorrow", "Another business"]
    # "Tomorrow" -> a new scheduled retry task at a good window
    qid = last.question_id
    await env.engine.handle_button(env.user.id, question_button_id(qid, 1))
    await env.engine.drain()
    retry = [x for x in env.repos.tasks.items.values() if x.id != t.id][0]
    assert retry.status == S.SCHEDULED and to_ist(retry.next_attempt_at).hour == 10


async def test_final_options_another_business_starts_discovery(env):
    env.runner.default = outcome(CallOutcome.NO_ANSWER)
    env.engine.policy.max_attempts = 1
    t = await env.task(booking(phone=RAJU, name="Raju Plumbing Works", category="plumber",
                               location_text="Indiranagar Bengaluru"))
    assert t.status == S.FAILED
    await env.engine.handle_button(env.user.id, question_button_id(env.notifier.last().question_id, 2))
    await env.engine.drain()
    from friday.core.models import TaskType

    assert env.repos.tasks.by_type(TaskType.DISCOVERY)


async def test_busy_retries_after_5_minutes(env):
    env.runner.script(LOOKS, outcome(CallOutcome.BUSY), offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    assert t.next_attempt_at - env.clock.now() == timedelta(minutes=5)
    assert await env.advance_and_tick(minutes=5) == 1
    assert (await env.get(t.id)).status == S.AWAITING_APPROVAL


async def test_alternate_number_and_whatsapp_request_between_attempts(env):
    await env.repos.businesses.upsert(
        Business(name="Raju Plumbing Works", phone=RAJU, whatsapp_phone="+919845012345")
    )
    env.runner.default = outcome(CallOutcome.NO_ANSWER)
    t = await env.task(booking(phone=RAJU, name="Raju Plumbing Works"))
    assert t.target.phone == "+919845012345"  # next attempt uses the other listed number
    wa = [m for m, _ in env.notifier.sent if m.channel == Channel.WHATSAPP and m.business_id]
    assert wa and wa[0].template.key == "friday_biz_request"


async def test_callback_later_with_time_and_vague(env):
    at = (env.clock.now() + timedelta(hours=6)).isoformat()
    env.runner.script(LOOKS, outcome(CallOutcome.CALLBACK_LATER, collected={"callback_at": at}))
    t = await env.task(booking())
    assert t.next_attempt_at == datetime.fromisoformat(at) + timedelta(minutes=5)
    assert any("asked me to call later" in x for x in env.texts())


async def test_hold_timeout_retries_next_morning(env):
    env.runner.default = outcome(CallOutcome.HOLD_TIMEOUT)
    t = await env.task(booking())
    local = to_ist(t.next_attempt_at)
    assert local.hour == 10 and local.date() == to_ist(env.clock.now()).date() + timedelta(days=1)


async def test_business_hours_queue_and_lunch(env):
    # Monday 13:30 IST: Sharma clinic closed 13:00-17:00 -> queued until 17:05
    env.clock.set(datetime(2026, 1, 5, 13, 30, tzinfo=IST))
    from friday.discovery.simulator import SimulatedDirectory

    hours = await SimulatedDirectory().business_hours("sim-sharma-clinic")
    await env.repos.businesses.upsert(Business(name="Dr. Sharma", phone="+912040000002", hours=hours))
    t = await env.task(booking(phone="+912040000002", name="Dr. Sharma"))
    assert t.status == S.SCHEDULED and to_ist(t.next_attempt_at).strftime("%H:%M") == "17:05"
    assert any("I'll call at" in x for x in env.texts())
    assert await env.advance_and_tick(hours=4) == 1
    assert (await env.get(t.id)).status == S.COMPLETED
    # unknown hours at 13:45 -> after the lunch window (14:30)
    env.clock.set(datetime(2026, 1, 6, 13, 45, tzinfo=IST))
    t2 = await env.task(booking(phone="+919812340000", name="New Place"))
    assert to_ist(t2.next_attempt_at).strftime("%H:%M") == "14:30"


async def test_scam_number_never_called(env):
    t = await env.task(booking(phone=SCAM, name="Airtel Helpline"))
    assert t.status == S.FAILED and env.runner.briefs == []
    assert "known-scam" in env.texts()[-1]


async def test_suspicious_number_needs_go(env):
    await env.repos.businesses.upsert(
        Business(name="Shady", phone="+919812300000", verification=NumberVerdict.SUSPICIOUS)
    )
    t = await env.task(booking(phone="+919812300000", name="Shady", company="Airtel"))
    assert t.status == S.AWAITING_APPROVAL and "Still call?" in env.texts()[-1]
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED and len(env.runner.briefs) == 1


async def test_name_only_resolved_via_directory(env):
    spec = booking(phone=None, name="Looks Unisex Salon", location_text="Indiranagar")
    t = await env.task(spec)
    assert t.target.phone == LOOKS and t.status == S.COMPLETED
    biz = await env.repos.businesses.get_by_phone(LOOKS)
    assert biz.hours is not None and biz.directory_place_id == "sim-looks-salon"


async def test_unknown_business_needs_info(env):
    t = await env.task(booking(phone=None, name=None))
    assert t.status == S.NEEDS_INFO and "number" in env.texts()[-1]


async def test_pre_call_approval_for_proactive_task(env):
    t = await env.engine.create_task(env.user.id, booking(), approved=False)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.AWAITING_APPROVAL and env.runner.briefs == []
    await env.engine.handle_button(env.user.id, approval_button_id(t.id, True))
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED


async def test_abuse_limit_queues_to_tomorrow(env):
    env.engine.settings.abuse_rate_limit_enabled = True
    env.engine.settings.abuse_max_calls_per_day = 1
    await env.task(booking())
    t2 = await env.task(booking())
    assert t2.status == S.SCHEDULED
    assert to_ist(t2.next_attempt_at).date() > to_ist(env.clock.now()).date()
    assert not any("cap" in x.lower() or "limit" in x.lower() for x in env.texts())


async def test_runner_exception_becomes_failed_retry(env):
    async def boom(brief, ask, notify):
        raise RuntimeError("x")

    env.runner.script(LOOKS, boom)
    t = await env.task(booking())
    assert t.status == S.SCHEDULED and t.last_outcome == CallOutcome.FAILED


async def test_brain_failure_fails_task(env):
    async def broken(ctx, task):
        raise RuntimeError("llm down")

    env.brain.build_call_brief = broken
    t = await env.task(booking())
    assert t.status == S.FAILED and "went wrong" in t.result.summary


async def test_worker_start_stop(env):
    env.runner.default = outcome(CallOutcome.BUSY)
    t = await env.task(booking())
    env.clock.advance(minutes=6)
    await env.engine.start(poll_s=0.01)
    import asyncio

    for _ in range(50):
        await asyncio.sleep(0.01)
        if (await env.get(t.id)).attempts == 2:
            break
    await env.engine.stop()
    await env.engine.drain()
    assert (await env.get(t.id)).attempts == 2
