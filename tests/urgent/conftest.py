# ruff: noqa: E501
"""Fixtures: the escalation on a fake clock, the real CallGate, a fake dialler. Nothing is dialled."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.models import ReplyButton, User, UserStatus
from friday.receptionist.models import ReceptionistConfig
from friday.urgent.gate import OwnNumberGate
from friday.urgent.models import Policy, RingResult, UserEscalationConfig
from friday.urgent.ports import FakeOwnNumberCaller
from friday.urgent.service import UrgentEscalation
from friday.urgent.store import EscalationStore, MemoryEscalationStore
from tests.calls.conftest import build_world

USER_PHONE = "+919800000001"  # the user's own number (invented)
OTHER_PHONE = "+919800000777"  # someone else's (invented)


def at(hour: int, minute: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=IST)


class Users:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get(self, user_id: str) -> User | None:
        return self.user if user_id == self.user.id else None

    async def get_by_phone(self, phone: str) -> User | None:
        return self.user if phone == self.user.phone else None


@dataclass
class W:
    esc: UrgentEscalation
    store: EscalationStore
    caller: FakeOwnNumberCaller
    clock: FakeClock
    user: User
    sent: list[tuple[str, str, list[ReplyButton]]] = field(default_factory=list)
    flags: dict = field(default_factory=lambda: {"enabled": True, "paused": False})
    rcp: ReceptionistConfig = field(default_factory=lambda: ReceptionistConfig(enabled=True, user_name="Asha"))

    async def optin(self, **over) -> None:
        cfg = UserEscalationConfig(opted_in=True, number=self.user.phone, **over)
        await self.store.save_config(self.user.id, cfg)

    async def alert(self, message_id: str = "m1", reasons=("urgent word: accident",), source: str = "rules"):
        """Open + 'send' the WhatsApp alert, the way the receptionist does."""
        o = await self.esc.open(self.user.id, message_id, list(reasons), source)
        assert o is not None
        await self.esc.confirm_alert(o.state, True)
        return (await self.store.get(self.user.id, o.state.id))

    async def go(self, **seconds) -> dict:
        self.clock.advance(**seconds)
        return await self.esc.tick()


def make(*, results=(RingResult.NO_ANSWER,), store: EscalationStore | None = None, core: Settings | None = None,
         hour: int = 11, policy: Policy | None = None, phone: str = USER_PHONE, hook=None) -> W:  # fmt: skip
    cw = build_world(core=core, hour=hour, user=User(phone=phone, status=UserStatus.ACTIVE))
    clock = FakeClock(at(hour))
    store = store or MemoryEscalationStore(clock)
    caller = FakeOwnNumberCaller(*results, hook=hook)
    sent: list = []

    async def send(uid, text, buttons):
        sent.append((uid, text, list(buttons)))

    flags = {"enabled": True, "paused": False}
    w = W(None, store, caller, clock, cw.user, sent, flags)  # type: ignore[arg-type]

    async def rcp_config(_uid):
        return w.rcp

    w.esc = UrgentEscalation(
        store, send, caller, clock, users=Users(cw.user), gate=OwnNumberGate(cw.gate, cw.hasher, core),
        policy=policy or Policy(), enabled=lambda: flags["enabled"], paused=lambda: flags["paused"],
        rcp_config=rcp_config,
    )  # fmt: skip
    return w


@pytest.fixture
def w() -> W:
    return make()
