"""A whole consumer-beta world, offline: container + SQLite + simulator WhatsApp + the real task
engine and proactive engine + the W1/W2/W3/W4/Google stack, with a simulated callee line.

Nothing here touches a network or a real number (all numbers are invented).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.api.runtime import Runtime
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import (
    Language,
    MessageKind,
    OutboundMessage,
    Profile,
    User,
    UserStatus,
)
from friday.db import Database
from friday.integration.sim import PersonaTelephony
from friday.integration.wiring import attach, build_stack
from friday.savings.config import SavingsConfig
from tests.api.conftest import FakeBrain, StubGeocoder, StubSTT
from tests.google.fake_google import FakeGoogle, settings_overrides

USER_PHONE = "+919800000001"
MUMMY = "+919000000001"
PAPA = "+919000000002"
SIS = "+919000000003"
STRANGER = "+919000000004"
SCHOOL = "+919000000005"

CARD_CHAT = "card"


def settings_with(google_extra: dict | None = None, **switches: bool) -> Settings:
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
        **(google_extra or {}),
        **switches,
    )


@dataclass
class World:
    c: Container
    runtime: Runtime
    channel: SimulatorChannel
    clock: FakeClock
    user: User
    phone: str
    telephony: PersonaTelephony
    brain: FakeBrain
    fake_google: FakeGoogle | None = None

    # ------------------------------------------------------------------ talking
    async def say(self, text: str) -> list[OutboundMessage]:
        """The user types ``text`` (a digit taps the last message's button); returns the replies."""
        before = len(self.channel.messages_to(self.phone))
        msg = self.channel.make_inbound(self.phone, text)
        await self.runtime.handle(msg)
        return self.channel.messages_to(self.phone)[before:]

    async def tap(self, title_part: str) -> list[OutboundMessage]:
        """Tap the button of the last message whose title contains ``title_part``."""
        last = self.channel.last_to(self.phone)
        assert last is not None and last.buttons, "the last message has no buttons"
        idx = next(
            i for i, b in enumerate(last.buttons, start=1) if title_part.lower() in b.title.lower()
        )
        return await self.say(str(idx))

    def texts(self) -> list[str]:
        return [m.text or "" for m in self.channel.messages_to(self.phone)]

    def all_out(self) -> str:
        return "\n".join(
            f"{m.text or ''} {' '.join(b.title for b in m.buttons)}"
            for m in self.channel.messages_to(self.phone)
        )

    def transcript(self) -> str:
        return "\n".join(self.channel.render(m) for m in self.channel.messages_to(self.phone))

    # ------------------------------------------------------------------ time and jobs
    async def run_jobs(self) -> None:
        await self.c.get("task_engine").drain()

    async def advance(self, **delta: float) -> None:
        self.clock.advance(**delta)

    def at(self, hour: int, minute: int = 0, day: int = 5) -> datetime:
        return datetime(2026, 1, day, hour, minute, tzinfo=IST)

    def set_time(self, when: datetime) -> None:
        self.clock.set(when)

    async def tick(self) -> list:
        return await self.c.get("proactive").tick()

    @property
    def consumer(self):  # noqa: ANN201
        return self.c.get("consumer")


async def make_world(
    *,
    calls: bool = True,
    savings: bool = True,
    lifestate: bool = True,
    google: bool = False,
    clock: FakeClock | None = None,
    hour: int = 10,
    savings_example_rules: bool = True,
    telephony: PersonaTelephony | None = None,
    name: str | None = "Rahul",
) -> World:
    fake = FakeGoogle() if google else None
    if fake is not None:
        fake.add_account("alice", "alice.example@gmail.com")
    settings = settings_with(
        settings_overrides() if google else None,
        consumer_calls_enabled=calls,
        savings_enabled=savings,
        lifestate_enabled=lifestate,
        google_enabled=google,
    )
    clk = clock or FakeClock(datetime(2026, 1, 5, hour, 0, tzinfo=IST))
    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clk)
    c.override_db(db)
    channel = SimulatorChannel(clk, dict(settings.whatsapp_templates))
    c.override("messaging", channel)
    c.override("sms", FakeSMS(dict(settings.sms_dlt_templates), clk))
    brain = FakeBrain()
    c.override("brain", brain)
    c.override("geocoder", StubGeocoder())
    c.override("stt", StubSTT())
    sim = telephony or PersonaTelephony()
    # the same stack the container builds, plus a simulated line instead of the refusing default
    router = build_stack(
        settings=settings,
        clock=clk,
        repos=c.repos,
        send=_sender(c),
        queue=c.get("job_queue"),
        locks=None,
        telephony=sim,
        savings_config=SavingsConfig(allow_example_rules=savings_example_rules),
        http_factory=fake.client_factory() if fake else None,
    )
    if router is not None:
        c.override("consumer", router)
    else:
        c.override("consumer", None)
    runtime = Runtime(c, fast_pin_hash=True)
    if router is not None:
        attach(router, task_engine=c.get("task_engine"), proactive=c.get("proactive"))
    user = await c.repos.users.add(User(phone=USER_PHONE, status=UserStatus.ACTIVE))
    await c.repos.profiles.save(
        Profile(user_id=user.id, name=name, language=Language.HINGLISH, morning_briefing=True)
    )
    w = World(c, runtime, channel, clk, user, USER_PHONE, sim, brain, fake)
    w._db = db  # type: ignore[attr-defined]
    return w


def _sender(c: Container):  # noqa: ANN202
    async def send(user_id: str, text: str, buttons) -> None:  # noqa: ANN001
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    return send


async def close_world(w: World) -> None:
    await w.c.aclose()


@pytest.fixture
async def world() -> AsyncIterator[World]:
    w = await make_world()
    try:
        yield w
    finally:
        await close_world(w)


@pytest.fixture
async def off_world() -> AsyncIterator[World]:
    """Every consumer switch off: production behaviour as before."""
    w = await make_world(calls=False, savings=False, lifestate=False, google=False)
    try:
        yield w
    finally:
        await close_world(w)


async def add_contact(w: World, name: str, number: str, **kw) -> None:  # noqa: ANN003
    kw.setdefault("confirmed", True)
    await w.consumer.calls.contacts.add(w.user.id, name, number, **kw)


@pytest.fixture(autouse=True)
def _quiet_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="friday")


__all__ = [
    "CARD_CHAT",
    "MUMMY",
    "PAPA",
    "SCHOOL",
    "SIS",
    "STRANGER",
    "USER_PHONE",
    "World",
    "add_contact",
    "close_world",
    "make_world",
    "MessageKind",
]
