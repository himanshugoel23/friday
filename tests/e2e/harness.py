"""End-to-end harness: the REAL app (Runtime + InboundPipeline + brain on the fake LLM +
task engine + simulated telephony / directory / hotels / geocoder + simulator channel)
on in-memory SQLite and a FakeClock. No network, no keys.

``Friday`` is the little driver the scenarios use:

    f = await Friday.start()
    u = await f.user("+919811100001")        # onboarded, PIN 4826
    await u.say("Looks Unisex Salon mein haircut book karo kal shaam")
    u.last()                                  # last text Friday sent
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from friday.api.runtime import Runtime
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import (
    OutboundMessage,
    Task,
    User,
    UserStatus,
)

PIN = "4826"

_ROLES: dict[str, str | None] = {}


def shim_task_role(monkeypatch: Any) -> None:
    """WORKAROUND for BUG-2 (``Task.role`` has no column in ``tasks``, so fan-out children
    lose their role on a DB round trip and every parallel-quote / stock-hunt / recurring
    flow collapses). Mimics the fix inside the tests only, so the downstream behaviour of
    those flows can still be verified. ``test_bugs.py`` proves the bug without the shim."""
    from friday.db.repositories import tasks as repo

    real_values, real_task = repo._task_values, repo._task

    def values(task):  # noqa: ANN001
        _ROLES[task.id] = task.role
        return real_values(task)

    def build(row):  # noqa: ANN001
        t = real_task(row)
        t.role = _ROLES.get(t.id)
        return t

    monkeypatch.setattr(repo, "_task_values", values)
    monkeypatch.setattr(repo, "_task", build)
START = datetime(2026, 1, 5, 11, 0, tzinfo=IST)  # Mon 11:00 IST: in the call window
ONBOARDING_LINES = ["hi", "Rahul", "Pune", "Hinglish", "casual", "I agree", PIN, PIN, "skip", "skip"]


def make_settings(**over: Any) -> Settings:
    base: dict[str, Any] = dict(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
        invite_only=False,
    )
    base.update(over)
    return Settings(**base)


def plain(m: OutboundMessage) -> str:
    """What the user reads: the free-text body (the template is only the out-of-window
    fallback), plus numbered button titles."""
    body = m.text or (" ".join(m.template.params) if m.template else "")
    if m.buttons:
        body += "\n" + "\n".join(f"{i}) {b.title}" for i, b in enumerate(m.buttons, 1))
    return body


@dataclass
class Party:
    f: Friday
    phone: str

    @property
    def ch(self):
        return self.f.channel

    def msgs(self) -> list[OutboundMessage]:
        return self.ch.messages_to(self.phone)

    def texts(self) -> list[str]:
        return [plain(m) for m in self.msgs()]

    def last(self) -> str:
        m = self.ch.last_to(self.phone)
        return plain(m) if m else ""

    def last_msg(self) -> OutboundMessage | None:
        return self.ch.last_to(self.phone)

    def all_text(self) -> str:
        return "\n".join(self.texts())

    async def say(self, text: str) -> list[str]:
        n = len(self.msgs())
        await self.f.rt.handle(self.ch.make_inbound(self.phone, text), raise_errors=True)
        await self.f.settle()
        return [plain(m) for m in self.msgs()[n:]]

    async def user_row(self) -> User:
        u = await self.f.c.repos.users.get_by_phone(self.phone)
        assert u is not None
        return u

    async def calls(self, task: Task):
        return await self.f.c.repos.tasks.list_calls(task.id)

    async def tasks(self) -> list[Task]:
        u = await self.user_row()
        return list(await self.f.c.repos.tasks.list_for_user(u.id))

    async def task(self, index: int = -1) -> Task:
        ts = sorted(await self.tasks(), key=lambda t: t.created_at)
        return ts[index]


class Friday:
    def __init__(self, c: Container, rt: Runtime, clock: FakeClock) -> None:
        self.c = c
        self.rt = rt
        self.clock = clock
        self.channel = c.messaging
        self.engine = c.task_engine

    @classmethod
    async def start(cls, *, now: datetime = START, **settings: Any) -> Friday:
        clock = FakeClock(now)
        c = Container(make_settings(**settings), clock=clock)
        await c.db.create_all()
        rt = Runtime(c, fast_pin_hash=True)
        await rt.start(background=False)
        return cls(c, rt, clock)

    async def close(self) -> None:
        await self.rt.stop()
        await self.c.aclose()

    async def settle(self) -> None:
        await self.engine.drain()

    async def advance(self, **delta: float) -> None:
        """Move the fake clock, fire due timers, run every due job."""
        self.clock.advance(**delta)
        await self.deliver_inbound()
        await self.engine.tick()
        await self.settle()

    async def deliver_inbound(self) -> list[str]:
        """Deliver scripted business call-backs / missed calls that are now due."""
        tel = self.c.telephony
        ids = await tel.deliver_due_inbound() if hasattr(tel, "deliver_due_inbound") else []
        await self.settle()
        return ids

    def person(self, phone: str) -> Party:
        return Party(self, phone)

    async def user(self, phone: str, name: str = "Rahul", *, language: str = "hinglish") -> Party:
        """Create an ACTIVE, consented user quickly (use onboard() to test the flow itself)."""
        p = Party(self, phone)
        await self.onboard(phone, name=name)
        return p

    async def onboard(self, phone: str, name: str = "Rahul", city: str = "Bengaluru") -> Party:
        p = Party(self, phone)
        for line in ["hi", name, city, "Hinglish", "casual", "I agree", PIN, PIN, "skip", "skip"]:
            await p.say(line)
        await p.say("later")  # first task: later
        u = await p.user_row()
        assert u.status == UserStatus.ACTIVE, u.status
        return p

    async def business_calls(self, phone: str, *, answered: bool = True):
        """A business calls (or missed-calls) Friday's number."""
        match, _contact = await self.rt.callbacks.on_inbound_call(phone, None, answered=answered)
        await self.settle()
        return match

