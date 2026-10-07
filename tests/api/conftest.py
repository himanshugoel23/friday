"""Fixtures for pipeline / API tests: scripted fake brain, recording fake engine,
simulator channel, fake SMS, stub geocoder/STT. No network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from friday.api.inbound import InboundPipeline
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import (
    ConversationContext,
    GeocodeResult,
    GeoPoint,
    InboundMessage,
    Intent,
    Interpretation,
    Language,
    OnboardingStep,
    OnboardingTurn,
    Person,
    Place,
    TaskSpec,
    TaskType,
    Transcription,
)

ADMIN = "+919900000009"


class FakeBrain:
    """Onboarding follows the step order; interpret pops scripted Interpretations
    (or a callable(ctx, msg)) and records everything it saw."""

    def __init__(self) -> None:
        self.script: list[
            Interpretation | Callable[[ConversationContext, InboundMessage], Interpretation]
        ] = []
        self.seen: list[str | None] = []
        self.contexts: list[ConversationContext] = []

    async def interpret(self, ctx: ConversationContext, message: InboundMessage) -> Interpretation:
        self.seen.append(message.text)
        self.contexts.append(ctx)
        if self.script:
            item = self.script.pop(0)
            return item(ctx, message) if callable(item) else item
        return Interpretation(intent=Intent.HELP, reply="I can make calls for you.")

    async def onboarding_turn(
        self, ctx: ConversationContext, step: OnboardingStep, message: InboundMessage | None
    ) -> OnboardingTurn:
        self.seen.append(message.text if message else None)
        self.contexts.append(ctx)
        text = (message.text or "") if message else ""
        if message is None:
            return OnboardingTurn(reply=f"ask {step.value}", next_step=step)
        order = list(OnboardingStep)
        nxt = order[order.index(step) + 1]
        if step == OnboardingStep.NAME:
            return OnboardingTurn(reply="city?", profile_updates={"name": text}, next_step=nxt)
        if step == OnboardingStep.CITY:
            return OnboardingTurn(reply="language?", profile_updates={"city": text}, next_step=nxt)
        if step == OnboardingStep.LANGUAGE:
            return OnboardingTurn(
                reply="tone?", profile_updates={"language": Language.EN}, next_step=nxt
            )
        if step == OnboardingStep.TONE:
            return OnboardingTurn(
                reply="consent? reply I agree", profile_updates={"tone": "formal"}, next_step=nxt
            )
        if step == OnboardingStep.CONSENT:
            agreed = "agree" in text.lower() or "ok" in text.lower()
            return OnboardingTurn(
                reply="PIN please" if agreed else "please agree",
                consent_given=agreed,
                # a sloppy brain that always tries to move on
                next_step=OnboardingStep.PIN,
            )
        if step == OnboardingStep.CIRCLE:
            people = []
            if "dad" in text.lower():
                people = [
                    Person(owner_user_id="x", name="Ramesh", relation="Father", phone="98111 11111")
                ]
            return OnboardingTurn(reply="places?", people=people, next_step=nxt)
        if step == OnboardingStep.PLACES:
            places = [Place(owner_user_id="x", label="Home", address_text=text)] if text else []
            return OnboardingTurn(reply="first task?", places=places, next_step=nxt)
        if step == OnboardingStep.FIRST_TASK:
            return OnboardingTurn(
                reply="On it!",
                first_task=TaskSpec(type=TaskType.BOOKING, goal=text),
                next_step=OnboardingStep.DONE,
            )
        return OnboardingTurn(reply="ok", next_step=nxt)


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _rec(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    async def submit(self, task):  # noqa: ANN001
        self._rec("submit", task)

    async def handle_answer(self, answer):  # noqa: ANN001
        self._rec("handle_answer", answer)

    async def approve(self, task_id, approve):  # noqa: ANN001
        self._rec("approve", task_id, approve)

    async def choose(self, task_id, index):  # noqa: ANN001
        self._rec("choose", task_id, index)

    async def cancel(self, task_id):  # noqa: ANN001
        self._rec("cancel", task_id)

    async def handle_business_callback(self, match, contact):  # noqa: ANN001
        self._rec("handle_business_callback", match, contact)

    async def handle_missed_call(self, match, contact):  # noqa: ANN001
        self._rec("handle_missed_call", match, contact)

    async def handle_unknown_caller(self, match, contact):  # noqa: ANN001
        self._rec("handle_unknown_caller", match, contact)

    async def handle_business_message(self, msg, match):  # noqa: ANN001
        self._rec("handle_business_message", msg, match)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


class StubGeocoder:
    name = "stub"

    async def geocode(self, text, *, near=None, region="in"):  # noqa: ANN001
        return GeocodeResult(
            location=GeoPoint(lat=18.5, lng=73.8), formatted_address=f"{text}, Pune", city="Pune"
        )

    async def resolve_maps_link(self, url):  # noqa: ANN001
        return GeocodeResult(location=GeoPoint(lat=12.9, lng=77.6), formatted_address="Indiranagar")

    async def reverse(self, point):  # noqa: ANN001
        return GeocodeResult(
            location=point, formatted_address="Pinned spot, Bengaluru", city="Bengaluru"
        )


class StubSTT:
    name = "stub"
    supported_languages = frozenset({Language.EN})

    async def transcribe(self, audio, *, language_hint=None):  # noqa: ANN001
        return Transcription(text=audio.data.decode(), language=Language.HINGLISH)


@pytest.fixture
def app_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"admin_phones": [ADMIN], "invite_only": True})


@pytest.fixture
def brain() -> FakeBrain:
    return FakeBrain()


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
async def wired(app_settings, clock, bus, db, brain, engine):
    c = Container(app_settings, clock=clock, bus=bus)
    c.override_db(db)
    channel = SimulatorChannel(clock, dict(app_settings.whatsapp_templates))
    sms = FakeSMS(dict(app_settings.sms_dlt_templates), clock)
    c.override("messaging", channel)
    c.override("sms", sms)
    c.override("brain", brain)
    c.override("task_engine", engine)
    c.override("geocoder", StubGeocoder())
    c.override("stt", StubSTT())
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
def channel(wired) -> SimulatorChannel:
    return wired.messaging


@pytest.fixture
def pipeline(wired) -> InboundPipeline:
    return InboundPipeline(wired, fast_pin_hash=True)
