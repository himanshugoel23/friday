from __future__ import annotations

from datetime import datetime

import pytest

from friday.brain.fake_llm import FakeLLM
from friday.brain.service import FridayBrain
from friday.core.clock import IST
from friday.core.config import Settings
from friday.core.models import (
    Business,
    CallBrief,
    Channel,
    ContactTarget,
    ConversationContext,
    InboundMessage,
    Language,
    OnboardingStep,
    Person,
    PersonConsent,
    Place,
    Profile,
    TargetKind,
    TaskType,
    Tone,
    Transcript,
    User,
    UserStatus,
)

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=IST)  # Wed 7 Oct 2026, 10:00 IST


@pytest.fixture(autouse=True)
def _no_llm_keys_in_env(monkeypatch):
    """Offline tests must resolve ``auto`` to the fake whatever the developer exported."""
    for k in ("OPENAI_API_KEY", "FRIDAY_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def brain_settings() -> Settings:
    return Settings(_env_file=None, mode="simulator", env="test", anthropic_api_key=None,
                    openai_api_key=None)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def brain(fake_llm: FakeLLM, brain_settings: Settings) -> FridayBrain:
    return FridayBrain(fake_llm, brain_settings)


def make_ctx(*, language: Language = Language.HINGLISH, tone: Tone = Tone.FRIENDLY,
             people: list[Person] | None = None, places: list[Place] | None = None,
             **kw) -> ConversationContext:
    user = User(id="u1", phone="+919800000001", status=UserStatus.ACTIVE,
                onboarding_step=OnboardingStep.DONE)
    profile = Profile(user_id=user.id, name="Ankit Sharma", city="Bengaluru", language=language,
                      tone=tone)
    return ConversationContext(user=user, profile=profile, now=NOW, people=people or [],
                               places=places or [], **kw)


@pytest.fixture
def ctx() -> ConversationContext:
    return make_ctx()


@pytest.fixture
def family_ctx() -> ConversationContext:
    dad = Person(id="p_dad", owner_user_id="u1", name="Suresh Verma", relation="father",
                 aliases=["dad"], phone="+919829000001", language=Language.HI,
                 notes="diabetic, prefers morning appointments",
                 contact_consent=PersonConsent.OPTED_IN, checkin_consent=PersonConsent.OPTED_IN)
    mom = Person(id="p_mom", owner_user_id="u1", name="Sunita Verma", relation="mother",
                 aliases=["mummy"], phone="+919829000002", language=Language.MR)
    priya = Person(id="p_priya", owner_user_id="u1", name="Priya", relation="friend")
    home = Place(id="pl_home", owner_user_id="u1", label="Home",
                 address_text="12, 4th Cross, Indiranagar", city="Bengaluru")
    office = Place(id="pl_office", owner_user_id="u1", label="Office",
                   address_text="Embassy Tech Village, Bellandur", city="Bengaluru")
    parents = Place(id="pl_parents", owner_user_id="u1", label="Mom & Dad's home",
                    address_text="Kothrud, Pune", city="Pune", person_id="p_dad")
    priya_home = Place(id="pl_priya", owner_user_id="u1", label="Priya's place",
                       address_text="HSR Layout", person_id="p_priya")
    return make_ctx(people=[dad, mom, priya], places=[home, office, parents, priya_home])


def msg(text: str | None = None, **kw) -> InboundMessage:
    return InboundMessage(channel=Channel.SIMULATOR, from_phone="+919800000001", text=text, **kw)


def business_brief(task_type: TaskType = TaskType.BOOKING, **kw) -> CallBrief:
    data = dict(task_id="t1", requester_user_id="u1", task_type=task_type,
                goal="Book a haircut for Ankit Sharma, Sat 10 Oct, 10 AM-12 PM",
                target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon",
                                     phone="+918040000001"),
                on_behalf_of="Ankit Sharma")
    data.update(kw)
    return CallBrief(**data)


def looks_business() -> Business:
    return Business(id="b_looks", name="Looks Unisex Salon", phone="+918040000001",
                    category="salon")


def transcript(brief: CallBrief, *turns: tuple[str, str], disclosure: bool = True) -> Transcript:
    from friday.core.models import Speaker

    tr = Transcript()
    if disclosure:
        tr.add(Speaker.FRIDAY, brief.disclosure(), at=NOW)
    for speaker, text in turns:
        tr.add(Speaker(speaker), text, at=NOW)
    return tr
