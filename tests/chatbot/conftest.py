"""A chat world for the pilot chatbot: container + SQLite + simulator WhatsApp + the real inbound
pipeline with FRIDAY_CHATBOT_ONBOARDING on. Offline; every number is invented."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime

import pytest

from friday.api.inbound import InboundPipeline
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import InboundMessage, OutboundMessage
from friday.db import Database
from tests.api.conftest import FakeBrain, FakeEngine, StubGeocoder, StubSTT

TESTER = "+919811100001"
TESTER2 = "+919811100002"
STRANGER = "+919811100003"
FOUNDER = "+919811100009"
MUMMY = "+919811100077"


def make_settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "mode": "simulator", "env": "test", "database_url": "sqlite+aiosqlite:///:memory:",
        "anthropic_api_key": None, "sarvam_api_key": None, "deepgram_api_key": None,
        "elevenlabs_api_key": None, "google_places_api_key": None,
        "chatbot_onboarding": True, "pilot": True,
        "pilot_allowed_numbers": [TESTER, TESTER2],
        "savings_enabled": False, "lifestate_enabled": False, "consumer_calls_enabled": False,
    }  # fmt: skip
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@dataclass
class Chat:
    c: Container
    pipeline: InboundPipeline
    channel: SimulatorChannel
    clock: FakeClock
    brain: FakeBrain
    settings: Settings
    phone: str = TESTER

    async def send(self, msg: InboundMessage) -> list[OutboundMessage]:
        before = len(self.channel.messages_to(msg.from_phone))
        await self.pipeline.handle(msg)
        return self.channel.messages_to(msg.from_phone)[before:]

    async def say(self, text: str, phone: str | None = None) -> list[OutboundMessage]:
        """Type ``text`` (a digit taps that button / row of the last message)."""
        phone = phone or self.phone
        return await self.send(self.channel.make_inbound(phone, text))

    async def tap(self, title_part: str, phone: str | None = None) -> list[OutboundMessage]:
        phone = phone or self.phone
        last = self.channel.last_to(phone)
        assert last is not None
        choices = [(b.id, b.title) for b in last.buttons]
        if last.list_menu:
            choices += [(r.id, r.title) for r in last.list_menu.rows]
        idx = next(i for i, (_, t) in enumerate(choices, 1) if title_part.lower() in t.lower())
        return await self.say(str(idx), phone)

    async def tap_id(self, button_id: str, phone: str | None = None) -> list[OutboundMessage]:
        from friday.core.models import MessageKind

        phone = phone or self.phone
        msg = self.channel.make_inbound(phone, "x")
        msg = msg.model_copy(
            update={"kind": MessageKind.BUTTON_REPLY, "button_id": button_id, "text": button_id}
        )
        return await self.send(msg)

    def texts(self, phone: str | None = None) -> list[str]:
        return [m.text or "" for m in self.channel.messages_to(phone or self.phone)]

    def all_out(self, phone: str | None = None) -> str:
        return "\n".join(
            self.channel.render(m) for m in self.channel.messages_to(phone or self.phone)
        )

    async def user(self, phone: str | None = None):  # noqa: ANN201
        return await self.c.repos.users.get_by_phone(phone or self.phone)

    async def onboard(self, name: str = "Rahul", phone: str | None = None) -> None:
        """Run the whole first-run flow for ``phone`` (consent, name, Hinglish, city, a win)."""
        phone = phone or self.phone
        await self.say("hi", phone)
        await self.tap("Haan", phone)
        await self.say(name, phone)
        await self.tap("Hinglish", phone)
        await self.say("Pune", phone)


async def build_chat(**over: object) -> Chat:
    settings = make_settings(**over)
    clock = FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))
    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    channel = SimulatorChannel(clock, dict(settings.whatsapp_templates))
    brain = FakeBrain()
    c.override("messaging", channel)
    c.override("sms", FakeSMS(dict(settings.sms_dlt_templates), clock))
    c.override("brain", brain)
    c.override("task_engine", FakeEngine())
    c.override("geocoder", StubGeocoder())
    c.override("stt", StubSTT())
    pipeline = InboundPipeline(c, fast_pin_hash=True)
    return Chat(c, pipeline, channel, clock, brain, settings)


@pytest.fixture
async def chat() -> AsyncIterator[Chat]:
    w = await build_chat()
    try:
        yield w
    finally:
        await w.c.aclose()


@pytest.fixture
def make_chat() -> Callable[..., object]:
    return build_chat
