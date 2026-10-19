"""Fixtures: a store (in-memory AND the real encrypted SQL repo), two users, a fake sender."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.models import User, UserStatus
from friday.lifestate.store import LifeStore, MemoryLifeStore

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=IST)  # a Monday, 3 pm


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def lclock() -> FakeClock:
    return FakeClock(NOW)


@dataclass
class World:
    store: LifeStore
    u1: str
    u2: str
    kind: str
    container: object = None


@pytest.fixture(params=["memory", "sql"])
async def world(request, settings, lclock):
    if request.param == "memory":
        yield World(MemoryLifeStore(), "u-one", "u-two", "memory")
        return
    from friday.core.container import Container
    from friday.db import Database

    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=lclock)
    c.override_db(db)
    a = await c.repos.users.add(User(phone="+919800000201", status=UserStatus.ACTIVE))
    b = await c.repos.users.add(User(phone="+919800000202", status=UserStatus.ACTIVE))
    yield World(c.repos.life, a.id, b.id, "sql", c)
    await c.aclose()
    await db.dispose()


@dataclass
class FakeSender:
    sent: list[tuple[str, str, str]] = field(default_factory=list)  # (user, text, channel)
    ok: bool = True

    async def send(self, user_id, text, *, channel="text", dedupe_key=None) -> bool:
        if not self.ok:
            return False
        self.sent.append((user_id, text, channel))
        return True


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()
