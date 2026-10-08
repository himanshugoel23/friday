"""E2E fixtures: the real app on a throw-away SQLite file + FakeClock, simulator everything."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from tests.e2e.harness import Friday

RAHUL = "+919811100001"
PRIYA = "+919811100002"
PAPA = "+911140001016"  # the simworld's "Suresh Verma (Papa)" persona
MUMMY = "+912040001015"  # the simworld's "Sunita Kulkarni (Mummy)" persona


async def _start(tmp_path, template: Path | None = None) -> Friday:
    if template is not None:
        shutil.copy(template, tmp_path / "e2e.db")
    return await Friday.start(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e.db",
        media_dir=str(tmp_path / "media"),
        create_tables=template is None,
        first_message_id=1 if template is None else 10_000_000,
    )


@pytest.fixture(scope="session")
def onboarded_template(tmp_path_factory) -> Path:
    """A database with Rahul (Bengaluru) and Priya (Pune) already onboarded, built once and
    copied per test (onboarding itself is covered by test_onboarding.py)."""
    folder = tmp_path_factory.mktemp("e2e-template")

    async def build() -> None:
        f = await Friday.start(
            database_url=f"sqlite+aiosqlite:///{folder}/e2e.db", media_dir=str(folder / "media")
        )
        await f.onboard(RAHUL, "Rahul", "Bengaluru")
        await f.onboard(PRIYA, "Priya", "Pune")
        await f.close()

    asyncio.run(build())
    return folder / "e2e.db"


@pytest.fixture
async def fresh_friday(tmp_path, monkeypatch):
    """An empty app (no users) - for the onboarding flow itself."""
    f = await _start(tmp_path)
    yield f
    await f.close()


@pytest.fixture
async def friday(tmp_path, monkeypatch, onboarded_template):
    """A running app with Rahul and Priya onboarded."""
    f = await _start(tmp_path, onboarded_template)
    yield f
    await f.close()


@pytest.fixture
async def raw_friday(tmp_path, onboarded_template):
    """Same app as `friday` (kept for the BUG-2 real-repository regression)."""
    f = await _start(tmp_path, onboarded_template)
    yield f
    await f.close()


@pytest.fixture
def rahul(friday):
    """Onboarded Bengaluru user."""
    return friday.person(RAHUL)


@pytest.fixture
def priya(friday):
    """Onboarded Pune user."""
    return friday.person(PRIYA)
