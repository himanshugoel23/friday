"""SECURITY-21/22: Friday must not become a harassment tool - private numbers need a
"is it a business?" confirmation, per-target caps across all users, DNC pool-wide."""

from __future__ import annotations

import pytest

pytest.importorskip("friday.tasks.engine")

from friday.core.models import CallOutcome, TaskStatus, User  # noqa: E402
from tests.tasks.conftest import LOOKS, booking, env, env_settings  # noqa: E402, F401
from tests.tasks.fakes import outcome  # noqa: E402

PRIVATE = "+919812345678"


async def test_private_number_requires_confirmation(env):  # noqa: F811
    t = await env.task(booking(phone=PRIVATE, name="Someone"))
    assert t.status == TaskStatus.AWAITING_APPROVAL and env.runner.briefs == []
    assert "Is +919812345678 a business?" in env.texts()[-1]
    assert "target.private_number_check" in env.repos.audit.actions()
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    assert len(env.runner.briefs) == 1
    assert "task.approved" in env.repos.audit.actions()


async def test_same_private_number_capped_across_users(env):  # noqa: F811
    env.runner.default = outcome(CallOutcome.PENDING_APPROVAL)
    for i in range(4):
        user = User(phone=f"+91981111110{i}")
        await env.repos.users.add(user)
        t = await env.engine.create_task(user.id, booking(phone=PRIVATE, name="Someone"))
        await env.engine.drain()
        await env.engine.approve(t.id, True)  # each user says "yes, a business"
        await env.engine.drain()
    assert len(env.runner.briefs) == 3  # 4th call to the same private number: held
    held = [t for t in env.repos.tasks.items.values() if t.status == TaskStatus.SCHEDULED]
    assert len(held) == 1 and "call.target_cap" in env.repos.audit.actions()


async def test_dnc_number_never_redialled(env):  # noqa: F811
    env.runner.script(LOOKS, outcome(CallOutcome.HUNG_UP, collected={"dnc_request": "1"}))
    first = await env.task(booking())
    assert first.status == TaskStatus.FAILED
    other = User(phone="+919811111199")
    await env.repos.users.add(other)
    again = await env.engine.create_task(other.id, booking())
    await env.engine.drain()
    assert (await env.get(again.id)).status == TaskStatus.FAILED
    assert len(env.runner.briefs) == 1  # never redialled, for any user
    assert await env.engine.pool.is_blocked(LOOKS)


async def test_verified_business_not_capped_by_target_limit(env):  # noqa: F811
    env.runner.default = outcome(CallOutcome.PENDING_APPROVAL)
    for _ in range(4):
        await env.task(
            booking(phone="+918040000003", name="CoolCare AC Services", location_text="Indiranagar")
        )
    from friday.core.models import Business

    biz = await env.repos.businesses.get_by_phone("+918040000003")
    biz.directory_place_id = "sim-cool-ac"
    await env.repos.businesses.upsert(Business(**biz.model_dump()))
    t = await env.task(booking(phone="+918040000003", name="CoolCare AC Services"))
    assert t.status == TaskStatus.AWAITING_APPROVAL
