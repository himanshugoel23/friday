"""NP-3 (engine x caller-ID pool) and S-7 (durable queue: restart-safe, replicas)."""

import asyncio
from datetime import timedelta

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import CallOutcome, NumberStatus
from friday.core.models import TaskStatus as S
from friday.core.scale import JobStatus, MemoryJobQueue
from friday.tasks.engine import TaskEngine
from friday.tasks.number_pool import Pool
from friday.tasks.policy import TaskPolicy
from tests.tasks.conftest import LOOKS, booking
from tests.tasks.fakes import offer_then_confirm, outcome

BLR = "+918069110001"
PUNE = "+912069110002"


def with_pool(env, *numbers, **kw):
    s = Settings(_env_file=None, friday_numbers=list(numbers or (BLR, PUNE)), **kw)
    pool = Pool(s, clock=env.clock, bus=env.bus)
    env.container.override("number_pool", pool)
    return pool


async def test_call_uses_pool_number_records_outcome_and_releases(env):
    pool = with_pool(env)
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    assert t.status == S.AWAITING_APPROVAL
    brief = env.runner.briefs[0]
    assert brief.from_number == BLR and not brief.number_changed  # local presence (Bengaluru)
    assert env.runner.from_numbers[0] == BLR
    health = await pool.health(BLR)
    assert health.calls == 1 and health.answered == 1
    assert not pool._usage_for(BLR).inflight  # released after the call


async def test_sticky_then_new_number_line_after_retirement(env):
    pool = with_pool(env, number_min_gap_s=0)
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    await pool.set_status(BLR, NumberStatus.RETIRED, reason="test")
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    confirm = env.runner.briefs[-1]
    assert confirm.from_number == PUNE and confirm.number_changed


async def test_no_free_number_schedules_instead_of_dialling(env):
    pool = with_pool(env, BLR)
    await pool.set_status(BLR, NumberStatus.COOLING, reason="test")
    t = await env.task(booking())
    assert t.status == S.SCHEDULED and env.runner.briefs == []
    assert t.next_attempt_at == env.clock.now() + timedelta(minutes=15)


async def test_pacing_not_before_respected(env):
    with_pool(env, BLR, number_max_concurrent=5)
    env.runner.default = outcome(CallOutcome.PENDING_APPROVAL)
    await env.task(booking())
    t2 = await env.task(booking(phone="+918040000003", name="CoolCare"))
    assert t2.status == S.SCHEDULED  # min gap 45s on the only number: no burst
    assert t2.next_attempt_at == env.clock.now() + timedelta(seconds=45)
    await env.advance_and_tick(seconds=45)
    assert (await env.get(t2.id)).status == S.AWAITING_APPROVAL


async def test_dnc_request_blocks_whole_pool_and_never_retries(env):
    pool = with_pool(env)
    env.runner.script(LOOKS, outcome(CallOutcome.HUNG_UP, collected={"do_not_call": "true"}))
    t = await env.task(booking())
    assert t.status == S.FAILED and "asked not to be called" in t.result.summary
    assert await pool.is_blocked(LOOKS)
    t2 = await env.task(booking())
    assert t2.status == S.FAILED and len(env.runner.briefs) == 1
    assert "call.blocked_dnc" in env.repos.audit.actions()


# ---------------------------------------------------------------------------- S-7


async def test_restart_mid_call_never_redials(env):
    """Worker dies mid-call (no ack): the lease expires, another worker claims the
    call.place job and must NOT dial the business again."""
    env.runner.gate = asyncio.Event()
    t = await env.engine.create_task(env.user.id, booking())
    for _ in range(50):
        await asyncio.sleep(0)
    assert env.runner.active == 1
    await env.engine.aclose()  # crash: handler cancelled, job left CLAIMED
    env.runner.gate.set()
    queue = env.container.job_queue
    job = next(j for j in queue.jobs.values() if j.kind == "call.place")
    assert job.status == JobStatus.CLAIMED
    env.runner.active = 0
    engine2 = TaskEngine(env.container, policy=TaskPolicy())
    env.container.override("task_engine", engine2)
    env.clock.advance(seconds=env.container.settings.queue_visibility_timeout_s + 1)
    await engine2.tick()
    await engine2.drain()
    t = await env.get(t.id)
    assert len(env.runner.briefs) == 1  # no duplicate call
    assert t.status == S.SCHEDULED and t.last_outcome == CallOutcome.FAILED  # normal retry
    assert queue.jobs[job.id].status == JobStatus.DONE
    await engine2.aclose()


async def test_lost_step_is_picked_up_after_restart(env):
    await env.engine.aclose()  # engine 1 is down before it processes anything
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    engine1 = TaskEngine(env.container, policy=TaskPolicy())
    engine1._closed = True  # accepts work (enqueue) but never claims: "crashes" at once
    t = await engine1.create_task(env.user.id, booking())
    engine2 = TaskEngine(env.container, policy=TaskPolicy())
    await engine2.drain()
    assert (await env.get(t.id)).status == S.AWAITING_APPROVAL
    await engine2.aclose()


async def test_two_replicas_never_place_the_same_call(env):
    env.runner.gate = asyncio.Event()
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    other = Container(env.container.settings, clock=env.clock, bus=env.bus)
    for name in (
        "repos",
        "brain",
        "call_runner",
        "notifier",
        "directory",
        "geocoder",
        "official_numbers",
        "number_verifier",
        "job_queue",
        "lock",
        "number_pool",
    ):
        other.override(name, env.container.get(name))
    replica = TaskEngine(other, policy=TaskPolicy())
    tasks = [await env.engine.create_task(env.user.id, booking()) for _ in range(3)]
    for _ in range(3):  # both replicas race to claim
        replica._kick()
        env.engine._kick()
        await asyncio.sleep(0)
    env.runner.gate.set()
    await asyncio.gather(env.engine.drain(), replica.drain())
    assert len(env.runner.briefs) == 3  # one call per task, never two
    assert len({b.task_id for b in env.runner.briefs}) == 3
    for t in tasks:
        assert (await env.get(t.id)).status == S.AWAITING_APPROVAL
    await replica.aclose()


async def test_scheduled_retry_fires_exactly_once_across_replicas(env):
    env.runner.script(LOOKS, outcome(CallOutcome.BUSY), offer_then_confirm("Looks", 400))
    t = await env.task(booking())
    assert t.status == S.SCHEDULED
    other = Container(env.container.settings, clock=env.clock, bus=env.bus)
    for name in (
        "repos",
        "brain",
        "call_runner",
        "notifier",
        "job_queue",
        "lock",
        "number_verifier",
        "directory",
        "official_numbers",
    ):
        other.override(name, env.container.get(name))
    replica = TaskEngine(other, policy=TaskPolicy())
    env.clock.advance(minutes=5)
    await asyncio.gather(env.engine.tick(), replica.tick())
    await asyncio.gather(env.engine.drain(), replica.drain())
    assert len(env.runner.briefs) == 2  # first busy call + exactly one retry
    await replica.aclose()


async def test_mid_call_answer_stored_by_another_replica(env):
    from friday.core.models import MidCallQuestion, UserAnswer
    from tests.tasks.fakes import result

    async def asks(brief, ask_user, notify):
        ans = await ask_user(
            MidCallQuestion(task_id=brief.task_id, text="?", options=["a", "b"], timeout_s=5)
        )
        return result(brief, CallOutcome.PENDING_APPROVAL, collected={"summary": ans.text})

    env.runner.script(LOOKS, asks)
    t = await env.engine.create_task(env.user.id, booking())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if env.repos.tasks.questions:
            break
    qid = next(iter(env.repos.tasks.questions))
    # the API replica stores the answer row; this process only sees the DB
    await env.repos.tasks.answer_question(UserAnswer(question_id=qid, text="b", option_index=1))
    await env.engine.drain()
    assert (await env.get(t.id)).result.summary == "b"


def test_queue_is_the_core_memory_queue(env):
    assert isinstance(env.container.job_queue, MemoryJobQueue)
    assert env.engine._kinds() == ("task.step", "task.scheduled", "call.place")


async def test_inbound_on_retired_number_still_routed_then_expires(env):
    from tests.tasks.test_inbound import LEG, offered

    pool = with_pool(env)
    t = await offered(env)
    line = env.runner.briefs[0].from_number
    await pool.set_status(line, NumberStatus.RETIRED, reason="test")
    match = await env.repos.calls.match(LOOKS, friday_number=line)
    plan = await env.engine.handle_business_callback(match, None, leg=LEG)
    assert plan.action == "resume"  # retired numbers keep forwarding call-backs
    env.clock.advance(days=31)
    plan = await env.engine.handle_business_callback(match, None, leg=LEG)
    assert plan.action == "take_message"
    _ = t


async def test_per_user_daily_safety_cap(env, monkeypatch):
    import friday.tasks.engine as eng

    monkeypatch.setattr(eng, "USER_DAILY_CALL_CAP", 2)
    env.runner.default = outcome(CallOutcome.PENDING_APPROVAL)
    for i in range(3):
        await env.task(booking(phone=f"+91804000009{i}", name=f"Shop {i}"))
    held = [t for t in env.repos.tasks.items.values() if t.status == S.SCHEDULED]
    assert len(env.runner.briefs) == 2 and len(held) == 1
    assert "call.user_cap" in env.repos.audit.actions()
