"""Reuse the inbound-pipeline fixtures (scripted brain, recording engine, simulator channel)."""

import pytest  # noqa: E402

from friday.care import CareService  # noqa: E402
from friday.core.scale import MemoryCache  # noqa: E402
from friday.proactive.engine import ProactiveEngine  # noqa: E402
from tests.api.conftest import (  # noqa: F401 - fixtures
    app_settings,
    brain,
    channel,
    engine,
    pipeline,
    wired,
)
from tests.tasks.conftest import env, env_settings  # noqa: E402, F401 - shared harness


@pytest.fixture
async def env_pe(env):  # noqa: F811
    sent: list[tuple[str, str]] = []

    async def sender(uid, text):
        sent.append((uid, text))

    care = CareService(MemoryCache(env.clock), env.clock, sender=sender)
    env.container.override("care", care)
    pe = ProactiveEngine(env.container)
    env.container.override("proactive", pe)
    yield env, pe, care, sent
    await pe.aclose()
