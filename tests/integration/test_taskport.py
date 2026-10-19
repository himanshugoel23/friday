"""The TaskPort over the task engine's durable queue, and the periodic call jobs."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from friday.calls.models import CallOutcome, CallStatus, OutcomeStatus
from friday.calls.stores import RecordingRecord  # noqa: F401
from friday.core.scale import JobStatus
from friday.integration.taskport import JOB_CONSUMER_CALL, QueueTaskPort
from tests.integration.conftest import MUMMY, World, add_contact, make_world

LATE = "mummy ko phone karke bata do ki main late hoon"


async def _approved(w: World, persona: str = "friendly_elder"):  # noqa: ANN202
    w.telephony.assign(MUMMY, persona)
    await add_contact(w, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    await w.say(LATE)
    await w.tap("Approve")
    (req,) = await w.c.repos.consumer_calls.list_for_user(w.user.id)
    return req


def _jobs(w: World):  # noqa: ANN202
    return [j for j in w.c.get("job_queue").jobs.values() if j.kind == JOB_CONSUMER_CALL]


async def test_same_key_is_one_job_and_the_same_task_id(world: World):
    req = await _approved(world)
    port: QueueTaskPort = world.consumer.extras["task_port"]
    first = await port.create(key=f"callreq:{req.id}:1", request=req, run_at=world.clock.now())
    second = await port.create(key=f"callreq:{req.id}:1", request=req, run_at=world.clock.now())
    assert first == second
    assert len(_jobs(world)) == 1
    job = _jobs(world)[0]
    assert job.payload["request_id"] == req.id
    assert MUMMY not in str(job.payload) and "mummy" not in str(job.payload).lower()  # ids only


async def test_the_engine_job_calls_execute_once_and_acks(world: World, monkeypatch):
    req = await _approved(world)
    orch = world.consumer.calls.orchestrator
    seen: list[str] = []
    real = orch.execute

    async def spy(request_id: str):  # noqa: ANN202
        seen.append(request_id)
        return await real(request_id)

    monkeypatch.setattr(orch, "execute", spy)
    # the registered handler holds the original bound method, so register a fresh one
    from friday.integration.taskport import job_handler

    world.c.get("task_engine").register_job_handler(JOB_CONSUMER_CALL, job_handler(orch))
    await world.run_jobs()
    assert seen == [req.id]
    assert all(j.status == JobStatus.DONE for j in _jobs(world))
    assert world.telephony.dialled == [MUMMY]


async def test_a_job_for_a_cancelled_request_dials_nothing(world: World):
    req = await _approved(world)
    await world.consumer.calls.orchestrator.cancel(req.id)
    await world.run_jobs()
    assert world.telephony.dialled == []
    got = await world.c.repos.consumer_calls.get_request(req.id)
    assert got is not None and got.status == CallStatus.CANCELLED


async def test_a_job_that_is_not_due_yet_waits_for_its_time(world: World):
    world.telephony.assign(MUMMY, "friendly_elder")
    await add_contact(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    await world.say("mummy ko 5 pm pe phone karke bata do ki main late hoon")
    await world.tap("Approve")
    await world.run_jobs()
    assert world.telephony.dialled == []  # 10:00 now, asked for 17:00
    world.set_time(world.at(17, 1))
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]


async def test_engine_without_the_switch_does_not_consume_the_kind():
    w = await make_world(calls=False, savings=False, lifestate=False)
    try:
        assert JOB_CONSUMER_CALL not in w.c.get("task_engine")._kinds()
    finally:
        await w.c.aclose()


async def test_engine_consumes_the_kind_when_attached(world: World):
    assert JOB_CONSUMER_CALL in world.c.get("task_engine")._kinds()


# ------------------------------------------------------------------------ periodic jobs
async def test_run_due_is_a_safety_net_for_a_lost_job(world: World):
    req = await _approved(world)
    world.c.get("job_queue").jobs.clear()  # the engine job was lost
    jobs = world.consumer.calls.jobs
    assert (await jobs.tick())["run_due"] == 0  # not overdue yet: the engine's job gets its chance
    await world.advance(minutes=3)
    done = await jobs.tick()
    assert done["run_due"] == 1 and world.telephony.dialled == [MUMMY]
    got = await world.c.repos.consumer_calls.get_request(req.id)
    assert got is not None and got.status == CallStatus.COMPLETED
    assert (await jobs.tick())["run_due"] == 0  # and never a second dial


async def test_recover_stale_closes_a_call_stuck_in_calling_and_tells_the_user(world: World):
    req = await _approved(world)
    store = world.c.repos.consumer_calls
    from sqlalchemy import update

    from friday.calls.dbmodel import CallRequestRow

    async with world.c.db.session() as s:  # a worker died 20 minutes into a call
        await s.execute(
            update(CallRequestRow)
            .where(CallRequestRow.id == req.id)
            .values(status="calling", attempts=1, updated_at=world.clock.now())
        )
    await world.advance(minutes=20)
    done = await world.consumer.calls.jobs.tick()
    assert done["recover_stale"] == 1
    got = await store.get_request(req.id)
    assert got is not None and got.status == CallStatus.FAILED
    assert "technical dikkat" in world.all_out()
    assert world.telephony.dialled == []  # closed, never redialled blindly


async def test_purge_expired_deletes_old_recordings_and_keeps_new_ones(world: World):
    req = await _approved(world)
    store = world.c.repos.consumer_calls
    jobs = world.consumer.calls.jobs
    deleted: list[str] = []

    async def deleter(ref: str) -> bool:
        deleted.append(ref)
        return True

    jobs.recordings.deleter = deleter
    old = world.clock.now() - timedelta(days=40)
    new = world.clock.now() - timedelta(days=2)
    await store.add_outcome(
        world.user.id,
        CallOutcome(request_id=req.id, attempt=1, status=OutcomeStatus.COMPLETED,
                    recording_ref="obj://old", started_at=old),
        None,
    )  # fmt: skip
    await store.add_outcome(
        world.user.id,
        CallOutcome(request_id=req.id, attempt=2, status=OutcomeStatus.COMPLETED,
                    recording_ref="obj://new", started_at=new),
        None,
    )  # fmt: skip
    done = await jobs.tick()
    assert done["purge_expired"] == 1 and deleted == ["obj://old"]
    await world.advance(hours=1)
    assert (await jobs.tick())["purge_expired"] == 0  # swept at most every few hours


async def test_the_runtime_loop_runs_the_periodic_pass(world: World, monkeypatch):
    seen = {"n": 0}
    real = world.consumer.periodic

    async def counting() -> dict:
        seen["n"] += 1
        return await real()

    monkeypatch.setattr(world.consumer, "periodic", counting)
    task = asyncio.create_task(world.consumer.loop(0.01))
    await asyncio.sleep(0.08)
    task.cancel()
    assert seen["n"] >= 2
