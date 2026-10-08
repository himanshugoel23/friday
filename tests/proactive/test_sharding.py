"""S-8: proactive sharded by hash(user_id) % shards; nudge jobs + per-user lock mean two
shards (or two replicas of one shard) never double-nudge."""

import asyncio
from datetime import timedelta

from friday.core.clock import to_ist
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import Fact, FactKind, NudgeStatus, User
from friday.proactive.engine import ProactiveEngine, shard_of


def replica(env, **settings):
    s = Settings(_env_file=None, **settings)
    other = Container(s, clock=env.clock, bus=env.bus)
    for name in ("repos", "brain", "notifier", "job_queue", "lock", "idempotency"):
        other.override(name, env.container.get(name))
    return ProactiveEngine(other)


async def add_users_with_due_facts(env, n):
    users = [env.user]
    for i in range(n - 1):
        u = User(phone=f"+9198222222{i:02d}")
        await env.repos.users.add(u)
        users.append(u)
    day = to_ist(env.clock.now()).date() + timedelta(days=1)
    for u in users:
        await env.repos.facts.upsert(
            Fact(user_id=u.id, kind=FactKind.DATE, key="rent_due", value="rent", due_on=day)
        )
    return users


def test_shard_function_stable():
    assert shard_of("abc", 4) == shard_of("abc", 4)
    assert {shard_of(f"u{i}", 2) for i in range(20)} == {0, 1}


async def test_two_shards_split_users_and_never_double_nudge(env):
    users = await add_users_with_due_facts(env, 8)
    a = replica(env, proactive_shards=2, proactive_shard_index=0)
    b = replica(env, proactive_shards=2, proactive_shard_index=1)
    await asyncio.gather(a.tick(), b.tick())
    evaluated = [j for j in env.container.job_queue.jobs.values() if j.kind == "nudge.evaluate"]
    assert len(evaluated) == len(users)  # each user scheduled by exactly one shard
    sent = env.repos.nudges.by_status(NudgeStatus.SENT)
    assert sorted(n.user_id for n in sent) == sorted(u.id for u in users)  # one each
    assert a.owns(users[0].id) != b.owns(users[0].id)
    await a.aclose()
    await b.aclose()


async def test_two_replicas_same_shard_single_nudge(env):
    await add_users_with_due_facts(env, 3)
    a = replica(env)
    b = replica(env)
    await asyncio.gather(a.tick(), b.tick(), a.tick())
    sent = env.repos.nudges.by_status(NudgeStatus.SENT)
    assert len(sent) == 3 and len({n.dedupe_key + n.user_id for n in sent}) == 3
    assert len(env.notifier.sent) == 3
    await a.aclose()
    await b.aclose()


async def test_cap_exact_under_concurrency(env):
    day = to_ist(env.clock.now()).date() + timedelta(days=1)
    for i in range(6):
        await env.repos.facts.upsert(
            Fact(
                user_id=env.user.id,
                kind=FactKind.DATE,
                key=f"bill_due_{i}",
                value="bill",
                due_on=day,
            )
        )
    a, b = replica(env), replica(env)
    await asyncio.gather(a.tick(), b.tick())
    assert len(env.repos.nudges.by_status(NudgeStatus.SENT)) == 3  # daily cap holds
    await a.aclose()
    await b.aclose()


async def test_any_worker_may_execute_a_scheduled_job(env):
    await add_users_with_due_facts(env, 1)
    a = replica(env, proactive_shards=2, proactive_shard_index=0)
    b = replica(env, proactive_shards=2, proactive_shard_index=1)
    owner, other = (a, b) if a.owns(env.user.id) else (b, a)
    await owner._enqueue("nudge.evaluate", user_id=env.user.id, dedupe="x")
    owner._closed = True  # owner dies before claiming; the other worker executes it
    await other.drain()
    assert len(env.repos.nudges.by_status(NudgeStatus.SENT)) == 1
    await a.aclose()
    await b.aclose()
