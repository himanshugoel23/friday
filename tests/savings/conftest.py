"""Fixtures: a clock on 2026-10-19 (IST), an in-memory DB, the stores, real user rows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.models import User, UserStatus
from friday.db import Database
from friday.db.repositories import Repositories, make_repositories
from friday.savings.bills import Bill
from friday.savings.commands import SavingsCommands
from friday.savings.config import SavingsConfig
from friday.savings.rules import load_example_rules
from friday.savings.savings_ledger import SavingsLedger
from friday.savings.store import SavingsRepos


@pytest.fixture
def sclock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 19, 10, 0, tzinfo=IST))


@pytest.fixture
async def sdb() -> AsyncIterator[Database]:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def cfg() -> SavingsConfig:
    return SavingsConfig(allow_example_rules=True)


@pytest.fixture
def srepos(sdb: Database, sclock: FakeClock, cfg: SavingsConfig) -> SavingsRepos:
    return SavingsRepos(sdb, sclock, cfg)


@pytest.fixture
def repos(sdb: Database, sclock: FakeClock) -> Repositories:
    return make_repositories(sdb, sclock, "test-secret")


async def _user(repos: Repositories, phone: str) -> str:
    u = await repos.users.add(User(phone=phone, status=UserStatus.ACTIVE))
    return u.id


@pytest.fixture
async def user_id(repos: Repositories) -> str:
    return await _user(repos, "+919800000101")


@pytest.fixture
async def other_user_id(repos: Repositories) -> str:
    return await _user(repos, "+919800000102")


@pytest.fixture
async def commands(srepos: SavingsRepos, sclock: FakeClock, cfg: SavingsConfig) -> SavingsCommands:
    for r in load_example_rules():
        await srepos.rules.upsert(r)
    return SavingsCommands(
        wallet=srepos.wallet,
        rules=srepos.rules,
        bills=srepos.bills,
        ledger=SavingsLedger(srepos.ledger, sclock),
        clock=sclock,
        config=cfg,
    )


@pytest.fixture
def make_bill():
    def _make(user_id: str, **kw) -> Bill:
        from datetime import date

        base = {
            "user_id": user_id,
            "biller": "BSES",
            "due_date": date(2026, 10, 25),
            "confirmed": True,
            "amount_paise": 124000,
        }
        return Bill(**{**base, **kw})

    return _make
