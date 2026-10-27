# ruff: noqa: E501
"""Fixtures: the receptionist store in memory AND on the real encrypted SQL tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.models import User, UserStatus
from friday.receptionist.store import (
    MemoryReceptionistStore,
    ReceptionistStore,
    SqlReceptionistStore,
)

NOW = datetime(2026, 10, 22, 21, 30, tzinfo=IST)


@dataclass
class World:
    store: ReceptionistStore
    u1: str
    u2: str
    kind: str
    clock: FakeClock
    container: object = None


@pytest.fixture(params=["memory", "sql"])
async def world(request, settings):
    clock = FakeClock(NOW)
    if request.param == "memory":
        yield World(MemoryReceptionistStore(clock), "u-one", "u-two", "memory", clock)
        return
    from friday.core.container import Container
    from friday.db import Database

    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    a = await c.repos.users.add(User(phone="+919800000301", status=UserStatus.ACTIVE))
    b = await c.repos.users.add(User(phone="+919800000302", status=UserStatus.ACTIVE))
    yield World(SqlReceptionistStore(db, clock), a.id, b.id, "sql", clock, c)
    await db.dispose()
