"""Voice test helpers: brief builder, scripted/stub call policies, simulator fixtures."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from friday.core.clock import FakeClock
from friday.core.config import Settings
from friday.core.events import EventBus
from friday.core.models import (
    CallAction,
    CallActionType,
    CallBrief,
    ContactTarget,
    Language,
    TargetKind,
    TaskType,
    Transcript,
    UserAnswer,
)
from friday.simworld import load_world
from friday.voice.session import CallRunner
from friday.voice.simulator import SimulatedTelephony

LOOKS = "+918040000001"
SHARMA = "+912040000002"
COOLCARE = "+918040000003"
FROSTY = "+918040000004"
SPICE = "+918040000008"
AIRTEL = "+911800000121"
HAVELI = "+912940000011"
PLUMBER = "+918040000012"
LAKEVIEW = "+912940000010"
USER_PHONE = "+919812345678"


def make_brief(phone: str = LOOKS, name: str = "Looks Unisex Salon", **kw) -> CallBrief:
    data = dict(
        task_id=kw.pop("task_id", "task-0001abcd"),
        requester_user_id="user-1",
        task_type=kw.pop("task_type", TaskType.BOOKING),
        goal=kw.pop("goal", "Book a men's haircut tomorrow evening"),
        target=ContactTarget(kind=kw.pop("target_kind", TargetKind.BUSINESS), name=name, phone=phone),
        on_behalf_of="Rahul",
        user_phone=kw.pop("user_phone", USER_PHONE),
    )
    data.update(kw)
    return CallBrief(**data)


Rule = Callable[[CallBrief, Transcript, Sequence[UserAnswer]], CallAction | None]


class ScriptedPolicy:
    """Returns ``actions`` in order (then HANGUP PARTIAL). Records every call."""

    def __init__(self, actions: Sequence[CallAction | Rule]) -> None:
        self.actions = list(actions)
        self.calls: list[Transcript] = []

    async def next_call_action(self, brief, transcript, answers) -> CallAction:
        self.calls.append(transcript.model_copy(deep=True))
        while self.actions:
            nxt = self.actions.pop(0)
            if isinstance(nxt, CallAction):
                return nxt
            out = nxt(brief, transcript, answers)
            if out is not None:
                return out
        return CallAction(type=CallActionType.HANGUP, text="Thank you, bye.", outcome=None)


def say(text: str, lang: Language = Language.HINGLISH, **kw) -> CallAction:
    return CallAction(type=CallActionType.SAY, text=text, language=lang, **kw)


def hangup(outcome, text: str | None = "Dhanyavaad, bye.", **kw) -> CallAction:
    return CallAction(type=CallActionType.HANGUP, text=text, outcome=outcome, **kw)


@pytest.fixture
def vsettings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        media_dir=str(tmp_path / "media"),
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
    )


@pytest.fixture
def fclock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vbus() -> EventBus:
    return EventBus()


@pytest.fixture
def sim(vsettings, fclock, vbus) -> SimulatedTelephony:
    return SimulatedTelephony(
        world=load_world(), clock=fclock, seed=7, media_dir=vsettings.media_dir, bus=vbus
    )


@pytest.fixture
def make_runner(sim, vsettings, fclock, vbus):
    def _make(policy, translator=None, telephony=None) -> CallRunner:
        return CallRunner(
            telephony=telephony or sim, policy=policy, translator=translator,
            settings=vsettings, clock=fclock, bus=vbus,
        )

    return _make


async def no_answer_user(q):
    return None
