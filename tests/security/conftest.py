"""Red-team fixtures (owner: Security Engineer).

Self-contained on purpose: other teams' fixtures change under us, so this suite
builds its own fake brain / engine / repos on top of the root ``tests/conftest.py``
fixtures (settings, clock, bus, db, container). No network, simulator paths only.

Failing security expectations are marked ``xfail(strict=True, reason="SECURITY-<n>")``
and map 1:1 to entries in ``docs/SECURITY_FIXES.md``. When a fix lands the xfail
turns into XPASS -> strict failure -> remove the marker (the test now guards it).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from friday.core.models import (
    CallBrief,
    ContactTarget,
    ConversationContext,
    InboundMessage,
    Intent,
    Interpretation,
    OnboardingStep,
    OnboardingTurn,
    TargetKind,
    TaskType,
    User,
    UserStatus,
)

PIN = "4826"
SECRET = "test-secret-key-for-security-suite"

ALICE_PHONE = "+919800000201"
BOB_PHONE = "+919800000202"
DAD_PHONE = "+919811111111"
SALON_PHONE = "+918040000001"

# Sensitive markers we plant and later hunt for (DB rows, logs, briefs, speech).
DAD_NOTES = "diabetic, takes insulin 20 units, BP 160/100"
HOME_ADDRESS = "Flat 402, Shanti Apartments, 12 MG Road, Kothrud, Pune"
ACCOUNT_NO = "300012345678"


class FakeBrain:
    """Scripted brain: pops Interpretations (or callables) and records what it saw."""

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
        return OnboardingTurn(reply="ok", next_step=step)


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        async def rec(*args: Any, **_kw: Any) -> None:
            self.calls.append((name, args))

        return rec

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


@pytest.fixture
def sec_settings(settings):
    return settings.model_copy(
        update={"secret_key": settings.secret_key.__class__(SECRET), "invite_only": False}
    )


@pytest.fixture
def fake_brain() -> FakeBrain:
    return FakeBrain()


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
async def wired(sec_settings, clock, bus, db, fake_brain, fake_engine):
    from friday.channels.simulator import SimulatorChannel
    from friday.channels.sms import FakeSMS
    from friday.core.container import Container

    c = Container(sec_settings, clock=clock, bus=bus)
    c.override_db(db)
    c.override("messaging", SimulatorChannel(clock, dict(sec_settings.whatsapp_templates)))
    c.override("sms", FakeSMS(dict(sec_settings.sms_dlt_templates), clock))
    c.override("brain", fake_brain)
    c.override("task_engine", fake_engine)
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
def repos(wired):
    return wired.repos


@pytest.fixture
def channel(wired):
    return wired.messaging


@pytest.fixture
def pipeline(wired):
    from friday.api.inbound import InboundPipeline

    return InboundPipeline(wired, fast_pin_hash=True)


async def make_active_user(
    repos, clock, phone: str, *, pin: str | None = PIN, name: str = "Rahul Verma"
) -> User:
    """An ACTIVE, onboarded user (optionally with a PIN) without running onboarding."""
    from friday.api.security import PinHasher
    from friday.core.models import Consent, ConsentKind, Profile

    now = clock.now()
    user = User(
        phone=phone,
        status=UserStatus.ACTIVE,
        onboarding_step=OnboardingStep.DONE,
        pin_hash=PinHasher(SECRET, fast=True).hash(pin) if pin else None,
        created_at=now,
        updated_at=now,
    )
    await repos.users.add(user)
    await repos.profiles.save(Profile(user_id=user.id, name=name, city="Pune"))
    await repos.consents.add(
        Consent(user_id=user.id, kind=ConsentKind.TERMS_PRIVACY, granted=True, recorded_at=now)
    )
    return user


def booking_brief(**kw: Any) -> CallBrief:
    data: dict[str, Any] = dict(
        task_id="task-sec-0001",
        requester_user_id="user-sec-1",
        task_type=TaskType.BOOKING,
        goal="Book a men's haircut tomorrow evening",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon", phone=SALON_PHONE),
        on_behalf_of="Rahul Verma",
    )
    data.update(kw)
    return CallBrief(**data)


async def say(pipeline, channel, phone: str, text: str) -> list[str]:
    """Send one simulator line; return the rendered replies."""
    before = len(channel.messages_to(phone))
    await pipeline.handle(channel.make_inbound(phone, text))
    return [channel.render(m) for m in channel.messages_to(phone)[before:]]
