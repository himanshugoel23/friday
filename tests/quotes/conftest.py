# ruff: noqa: E501
"""Fixtures for the WhatsApp quotes flow: the real app (Runtime + pipeline) on the simulator
channel, a fake directory (counts every call), a fake vendor-call port, a fake clock."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from friday.core.clock import IST
from friday.core.events import TaskStatusChanged
from friday.core.models import (
    BusinessCandidate,
    GeoPoint,
    Profile,
    TaskStatus,
    User,
    UserStatus,
    new_id,
)
from friday.quotes.calls import CallReport
from friday.quotes.models import Outcome
from tests.e2e.harness import START, Friday, Party, plain

GURGAON = (28.4244, 77.1068)
BLR = (12.9719, 77.6412)
USER_PHONE = "+919811100001"


def cand(i: int, name: str, *, rating: float | None = 4.4, reviews: int = 300, phone: bool = True,
         dist: float = 1.0, lat: float = 28.4244, lng: float = 77.1068, **kw: Any) -> BusinessCandidate:
    return BusinessCandidate(
        provider="fake", place_id=f"p{i}", name=name, phone=f"+91124500{i:04d}" if phone else None,
        category="salon", address=f"Sector {50 + i}", location=GeoPoint(lat=lat + i * 0.001, lng=lng),
        distance_km=dist, rating=rating, review_count=reviews, **kw,
    )


class FakeDirectory:
    name = "fake"

    def __init__(self, items: list[BusinessCandidate] | None = None) -> None:
        self.items = items if items is not None else []
        self.searches = 0
        self.details_calls = 0
        self.fail = False

    async def search(self, query, location, *, near=None, limit=10, radius_m=None):
        self.searches += 1
        if self.fail:
            from friday.core.interfaces import ProviderError

            raise ProviderError("fake", "boom")
        return [c.model_copy() for c in self.items][:limit]

    async def details(self, place_id, *, lean=False):
        self.details_calls += 1
        return next((c for c in self.items if c.place_id == place_id), None)


class FakeCalls:
    """Stands in for the engine adapter: records placements, results are scripted."""

    def __init__(self, f: Friday) -> None:
        self.f = f
        self.placed: list[dict[str, Any]] = []
        self.reports: dict[str, CallReport] = {}
        self.cancelled: list[str] = []
        self.fail_place = False

    async def place(self, conv, v, *, now, task_id=None):
        if self.fail_place:
            raise RuntimeError("telephony down")
        self.placed.append({"task_id": task_id, "name": v.name, "phone": v.phone, "mode": conv.mode,
                            "kind": "quote"})
        return task_id

    async def place_booking(self, conv, v, *, when_text, ceiling, now, task_id=None):
        self.placed.append({"task_id": task_id, "name": v.name, "phone": v.phone, "mode": "book",
                            "kind": "book", "when": when_text, "ceiling": ceiling})
        return task_id

    @staticmethod
    def check_booking(when_text, ceiling, now):
        from friday.quotes.calls import EngineVendorCalls

        EngineVendorCalls.check_booking(when_text, ceiling, now)

    async def cancel(self, task_id):
        self.cancelled.append(task_id)

    async def report(self, task_id):
        return self.reports.get(task_id, CallReport(finished=False))

    # --- test helpers
    def task_for(self, name: str) -> str:
        return [p for p in self.placed if p["name"] == name][-1]["task_id"]

    def names(self) -> list[str]:
        return [p["name"] for p in self.placed]

    async def finish(self, name: str, outcome: Outcome, price: int | None = None) -> None:
        tid = self.task_for(name)
        self.reports[tid] = CallReport(True, outcome, price_inr=price)
        conv = await self.f.c.repos.users.get_by_phone(USER_PHONE)
        await self.f.c.bus.publish(
            TaskStatusChanged(task_id=tid, user_id=conv.id, old=TaskStatus.CALLING,
                              new=TaskStatus.COMPLETED)
        )


class Chat(Party):
    """A Party with button taps."""

    async def tap(self, title: str) -> list[str]:
        m = self.last_msg()
        assert m is not None and m.buttons, f"no buttons on: {self.last()}"
        b = next((b for b in m.buttons if title.lower() in b.title.lower()), None)
        assert b is not None, f"no button {title!r} in {[x.title for x in m.buttons]}"
        return await self.tap_id(b.id)

    async def tap_id(self, button_id: str, title: str = "") -> list[str]:
        from friday.core.models import InboundMessage, MessageKind

        n = len(self.msgs())
        msg = InboundMessage(
            channel=self.ch.channel, from_phone=self.phone, kind=MessageKind.BUTTON_REPLY,
            button_id=button_id, text=title, provider_message_id=f"tap.{new_id()}",
        )
        await self.f.rt.handle(msg, raise_errors=True)
        await self.f.settle()
        return [plain(m) for m in self.msgs()[n:]]

    async def pin(self, lat: float, lng: float) -> list[str]:
        return await self.say(f"/pin {lat},{lng}")


async def make_user(f: Friday, phone: str = USER_PHONE, name: str = "Rahul", lang: str = "hinglish") -> Chat:
    users = f.c.repos.users
    u = await users.add(User(phone=phone, status=UserStatus.ACTIVE, invites_remaining=0))
    from friday.core.models import Language, OnboardingStep

    u.onboarding_step = OnboardingStep.DONE
    await users.save(u)
    await f.c.repos.profiles.save(Profile(user_id=u.id, name=name, city="Gurgaon",
                                          language=Language(lang)))
    return Chat(f, phone)


@pytest.fixture
async def qf(tmp_path):
    f = await Friday.start(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/q.db", media_dir=str(tmp_path / "media"),
        quotes_flow_enabled=True,
    )
    f.directory = FakeDirectory([
        cand(1, "Glow Salon", rating=4.5, reviews=640, dist=0.8),
        cand(2, "Trendz Studio", rating=4.2, reviews=210, dist=1.5),
        cand(3, "Royal Cuts", rating=4.6, reviews=1200, dist=3.2),
        cand(4, "Shine Parlour", rating=4.0, reviews=95, dist=2.0),
    ])
    f.c.override("directory", f.directory)
    flow = f.rt.pipeline.quotes
    flow._finder = None
    flow.calls = FakeCalls(f)
    f.flow = flow
    f.calls = flow.calls
    yield f
    await f.close()


@pytest.fixture
async def rahul(qf):
    return await make_user(qf)


__all__ = ["BLR", "GURGAON", "START", "IST", "datetime"]
