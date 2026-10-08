"""E2E fixtures: the real app on a throw-away SQLite file + FakeClock, simulator everything."""

from __future__ import annotations

import pytest

from tests.e2e.harness import Friday, shim_task_role

RAHUL = "+919811100001"
PRIYA = "+919811100002"
PAPA = "+911140001016"  # the simworld's "Suresh Verma (Papa)" persona
MUMMY = "+912040001015"  # the simworld's "Sunita Kulkarni (Mummy)" persona


async def _start(tmp_path) -> Friday:
    return await Friday.start(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e.db", media_dir=str(tmp_path / "media")
    )


@pytest.fixture
async def friday(tmp_path, monkeypatch):
    """A running app. ``Task.role`` persistence is shimmed (BUG-2) so downstream behaviour
    of fan-out / recurring / call-back flows can be verified; see harness.shim_task_role."""
    shim_task_role(monkeypatch)
    f = await _start(tmp_path)
    yield f
    await f.close()


@pytest.fixture
async def raw_friday(tmp_path):
    """Same app WITHOUT the BUG-2 shim (used only by tests/e2e/test_bugs.py)."""
    f = await _start(tmp_path)
    yield f
    await f.close()


@pytest.fixture
async def rahul(friday):
    """An onboarded Bengaluru user."""
    return await friday.onboard(RAHUL)
