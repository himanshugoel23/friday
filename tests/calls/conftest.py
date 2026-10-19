"""Fixtures for the consumer-call flow: everything in memory, fakes only, invented numbers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.calls.approval import ApprovalService
from friday.calls.contacts import ContactBook, MemoryContactStore
from friday.calls.dnc import DncRegistry, MemoryDncStore
from friday.calls.fakes import (
    FakeLiveCallEngine,
    FakeOpeningLineProvider,
    FakeTaskPort,
    RecordingNotifier,
)
from friday.calls.flow import CallIntake
from friday.calls.gate import CallGate
from friday.calls.numbers import NumberHasher
from friday.calls.orchestrator import CallOrchestrator
from friday.calls.settings import CallsSettings
from friday.calls.stores import MemoryCallStore
from friday.calls.understand import RequestUnderstander
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.crypto import FieldCipher, LocalKeyProvider
from friday.core.models import User, UserStatus

MUMMY = "+919000000001"
PLUMBER = "+919000000002"
AIRTEL = "+919000000003"
SCHOOL = "+919000000004"
RAJ = "+919000000005"
AMIT = "+919000000006"
NEHA = "+919000000007"
USER_PHONE = "+919800000001"


def make_cipher(seed: bytes = b"a") -> FieldCipher:
    return FieldCipher(
        LocalKeyProvider({"t1": seed * 32}, index_key=seed * 32),
    )


class Users:
    def __init__(self) -> None:
        self.rows: dict[str, User] = {}

    def add(self, user: User) -> User:
        self.rows[user.id] = user
        return user

    async def get(self, user_id: str) -> User | None:
        return self.rows.get(user_id)


@dataclass
class World:
    clock: FakeClock
    cipher: FieldCipher
    hasher: NumberHasher
    store: MemoryCallStore
    dnc: DncRegistry
    dnc_store: MemoryDncStore
    contacts: ContactBook
    gate: CallGate
    approval: ApprovalService
    engine: FakeLiveCallEngine
    notifier: RecordingNotifier
    tasks: FakeTaskPort
    users: Users
    orch: CallOrchestrator
    intake: CallIntake
    user: User
    settings: CallsSettings

    def at(self, hour: int, minute: int = 0, day: int = 5) -> datetime:
        return datetime(2026, 1, day, hour, minute, tzinfo=IST)


def build_world(
    *, settings: CallsSettings | None = None, core: Settings | None = None, hour: int = 11
) -> World:
    clock = FakeClock(datetime(2026, 1, 5, hour, 0, tzinfo=IST))  # Monday
    cipher = make_cipher()
    hasher = NumberHasher(cipher)
    cs = settings or CallsSettings()
    store = MemoryCallStore()
    dnc_store = MemoryDncStore()
    dnc = DncRegistry(dnc_store, hasher, clock)
    users = Users()
    user = users.add(User(phone=USER_PHONE, status=UserStatus.ACTIVE))
    gate = CallGate(store=store, dnc=dnc, hasher=hasher, settings=cs, core_settings=core)
    approval = ApprovalService(FakeOpeningLineProvider(), clock)
    engine, notifier, tasks = FakeLiveCallEngine(), RecordingNotifier(), FakeTaskPort()
    orch = CallOrchestrator(
        store=store, gate=gate, approval=approval, dnc=dnc, hasher=hasher, engine=engine,
        notifier=notifier, tasks=tasks, users=users, clock=clock, settings=cs,
    )  # fmt: skip
    book = ContactBook(MemoryContactStore(), hasher, clock)
    intake = CallIntake(
        understander=RequestUnderstander(), contacts=book, orchestrator=orch, approval=approval
    )
    return World(
        clock, cipher, hasher, store, dnc, dnc_store, book, gate, approval, engine, notifier,
        tasks, users, orch, intake, user, cs,
    )  # fmt: skip


@pytest.fixture
def world() -> World:
    return build_world()


@pytest.fixture
def evening_world() -> World:
    return build_world(hour=21)  # 21:00 IST, outside business hours, inside family hours
