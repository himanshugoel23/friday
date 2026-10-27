# ruff: noqa: E501
"""Fixtures: refunds switched on, fakes only, invented vendors and numbers. Each service test runs
over the in-memory store AND the SQL repository."""

from __future__ import annotations

from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.models import User
from friday.db.repositories import make_repositories
from friday.refunds.fakes import FakeRefundSender, FakeRefundTaskPort
from friday.refunds.models import RefundCase
from friday.refunds.ports import KnownNumber
from friday.refunds.resolver import StaticNumberSource
from friday.refunds.service import RefundService
from friday.refunds.store import MemoryRefundStore

EXAMPLE_NUMBER = "+919800000777"  # invented


def at(day: int, hh: int = 10, mm: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hh, mm, tzinfo=IST)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(at(10, 10))  # Tue 10 Nov 2026, 10:00 IST


@pytest.fixture
def rsettings(settings: Settings) -> Settings:
    return settings.model_copy(update={"refunds_enabled": True, "refund_chase_calls": True})


@pytest.fixture
def repos(db, clock):
    return make_repositories(db, clock, "test-secret")


@pytest.fixture(params=["memory", "sql"])
def store(request, repos):
    return MemoryRefundStore() if request.param == "memory" else repos.refunds


@pytest.fixture
async def alice(repos) -> User:
    return await repos.users.add(User(phone="+919800000401"))


@pytest.fixture
async def bob(repos) -> User:
    return await repos.users.add(User(phone="+919800000402"))


@pytest.fixture
def sender() -> FakeRefundSender:
    return FakeRefundSender()


@pytest.fixture
def taskport() -> FakeRefundTaskPort:
    return FakeRefundTaskPort()


@pytest.fixture
def numbers() -> StaticNumberSource:
    return StaticNumberSource()


@pytest.fixture
def svc(rsettings, store, clock, sender, taskport, numbers) -> RefundService:
    return RefundService(
        rsettings, store, clock, sender=sender, tasks=taskport, sources=[numbers]
    )


def known(number: str = EXAMPLE_NUMBER, source: str = "vendor_record") -> KnownNumber:
    return KnownNumber(number, source, "Exampleair")


async def open_case(svc: RefundService, user_id: str, vendor: str = "Exampleair", amount: int = 450000):
    await svc.open_by_user(user_id, vendor, amount_paise=amount)
    (case,) = [c for c in await svc.store.list_cases(user_id) if c.vendor_name == vendor]
    return case


def sent_times(sender: FakeRefundSender) -> int:
    return len(sender.sent)


__all__ = ["EXAMPLE_NUMBER", "RefundCase", "at", "known", "open_case"]
