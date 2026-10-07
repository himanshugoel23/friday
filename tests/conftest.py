"""Shared fixtures. Engineers: add module-specific fixtures in tests/<module>/conftest.py.

* ``settings``   - simulator mode, in-memory SQLite, no .env, no keys
* ``clock``      - FakeClock at Mon 2026-01-05 10:00 IST
* ``bus``        - fresh EventBus
* ``db``         - Database with all tables created (in-memory, per test)
* ``container``  - Container wired with the above
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import EventBus
from friday.db import Database


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings.database_url)
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
async def container(
    settings: Settings, clock: FakeClock, bus: EventBus, db: Database
) -> AsyncIterator[Container]:
    c = Container(settings, clock=clock, bus=bus)
    c.override_db(db)
    try:
        yield c
    finally:
        await c.aclose()
