import pytest

from friday.proactive.engine import ProactiveEngine
from tests.tasks.conftest import env, env_settings  # noqa: F401 - shared harness


@pytest.fixture
async def pe(env):  # noqa: F811
    engine = ProactiveEngine(env.container)
    env.container.override("proactive", engine)
    yield engine
    await engine.aclose()
