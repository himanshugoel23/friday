# ruff: noqa: E501
"""Fixtures: Robin on a fake clock, SQLite tables, a fake dialler and a recording sender. Nothing is dialled or sent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.models import User, UserStatus
from friday.robin.context import Ctx
from friday.robin.gate import AllowAllGate
from friday.robin.models import ConsentSource, Family, Member
from friday.robin.ports import FakeParentCaller, FakeParentChannel, RecordingSender
from friday.robin.store import RobinStore
from friday.robin.wiring import RobinHub

CHILD_PHONE = "+919800000101"  # invented
PARENT_PHONE = "+919800000102"
SECOND_PHONE = "+919800000103"


def at(hour: int, minute: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=IST)


@dataclass
class W:
    hub: RobinHub
    ctx: Ctx
    store: RobinStore
    clock: FakeClock
    caller: FakeParentCaller
    sender: RecordingSender
    channel: FakeParentChannel
    child_user: User
    settings: object

    async def family(self, *, consent: bool = True, notified: bool = True, second: bool = False, checkin: str = "09:00") -> tuple[Family, Member]:
        fam = await self.hub.fam.create_family(self.child_user, parent_label="Papa", child_name="Asha", child_language="en")
        parent = await self.hub.fam.add_parent(fam, PARENT_PHONE, language="hinglish")
        assert isinstance(parent, Member)
        child = await self.ctx.child(fam)
        child.call_ok = True
        await self.store.save_member(child, fam.owner_user_id)
        if second:
            await self.hub.fam.set_second_contact(fam, SECOND_PHONE, "Uncle")
        await self.hub.fam.update_settings(fam, checkin_time=checkin)
        if consent:
            for item in ("daily_checkin_calls", "medicine_reminders", "scam_check", "share_summary_with_child"):
                await self.hub.fam.give_consent(parent.id, item, ConsentSource.ADMIN_CHAT)
        if notified:
            await self.hub.intro.notify_parent(fam)
        fam = await self.store.get_family(fam.id)
        return fam, parent

    def go(self, **delta: float) -> None:
        self.clock.advance(**delta)


@pytest.fixture
async def w(container, settings, clock):
    settings.brand_name = "Robin"
    clock.set(at(10))
    child = await container.repos.users.add(User(phone=CHILD_PHONE, status=UserStatus.ACTIVE))
    store = RobinStore(container.repos.db, clock)
    caller, sender, channel = FakeParentCaller(), RecordingSender(), FakeParentChannel()
    ctx = Ctx(store=store, clock=clock, send=sender, caller=caller, gate=AllowAllGate(), users=container.repos.users, settings=settings, parent_channel=channel)
    hub = RobinHub(ctx)
    yield W(hub, ctx, store, clock, caller, sender, channel, child, settings)
