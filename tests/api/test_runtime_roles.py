"""Process roles: each role starts the right loops (ARCHITECTURE §10.3)."""

from __future__ import annotations

import asyncio

import pytest

from friday.api.runtime import Runtime
from friday.core.clock import FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.voice.worker import VoiceWorker


def _runtime(roles: list[str]) -> Runtime:
    settings = Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        roles=roles,
    )
    return Runtime(Container(settings, clock=FakeClock()), fast_pin_hash=True)


def _names(rt: Runtime) -> set[str]:
    return {t.get_name() for t in rt._tasks}


@pytest.fixture
async def started():
    runtimes: list[Runtime] = []

    async def go(roles: list[str]) -> Runtime:
        rt = _runtime(roles)
        runtimes.append(rt)
        await rt.start(background=True)
        return rt

    yield go
    for rt in runtimes:
        await rt.stop()
        await rt.c.aclose()


async def test_voice_role_runs_the_voice_worker_not_the_engine_claim(started):
    rt = await started(["voice"])
    assert any(isinstance(x, VoiceWorker) for x in rt._started)
    assert "friday-worker" not in _names(rt)  # no inbound.message loop on a voice node
    assert rt.c.task_engine.claim_calls is False
    assert rt.c.task_engine._kinds() == ()  # engine consumes nothing here


async def test_task_role_keeps_engine_claiming_everything_it_owns(started):
    rt = await started(["task"])
    assert "friday-worker" in _names(rt)
    assert not any(isinstance(x, VoiceWorker) for x in rt._started)
    assert rt.c.task_engine.claim_calls is True
    assert rt.c.task_engine in rt._started


async def test_all_roles_voice_worker_owns_calls(started):
    rt = await started(["api", "task", "voice", "proactive", "batch"])
    assert any(isinstance(x, VoiceWorker) for x in rt._started)
    assert rt.c.task_engine.claim_calls is False
    assert "call.place" not in rt.c.task_engine._kinds()
    assert {"friday-worker", "friday-retention"} <= _names(rt)


async def test_api_role_has_no_background_loops(started):
    rt = await started(["api"])
    assert rt._tasks == [] and rt._started == []


async def test_proactive_role_runs_retention_daily_once(started):
    rt = _runtime(["proactive"])
    calls: list[tuple] = []

    async def fake_run(now, recording_days=30, preconsent_days=7):
        calls.append((now, recording_days, preconsent_days))
        return {}

    rt.c.repos.retention.run = fake_run  # type: ignore[method-assign]
    try:
        await rt.start(background=True)
        await asyncio.sleep(0.2)  # retention loop + proactive tick both try; once per IST day
        assert len(calls) == 1
        assert "friday-retention" in _names(rt)
    finally:
        await rt.stop()
        await rt.c.aclose()
