"""Quality-loop fixtures: the offline app (fake LLM, in-memory SQLite, fake clock)."""

from __future__ import annotations

import pytest

from friday.core.models import (
    CallDirection,
    CallerKind,
    CallOutcome,
    CallResult,
    Consent,
    ConsentKind,
    DialStatus,
    Language,
    Profile,
    Speaker,
    User,
    UserStatus,
)
from friday.quality.store import TranscriptStore
from friday.voice.frontdoor import FrontDoorSummary
from tests.e2e.harness import Friday

PHONE = "+919811100001"


@pytest.fixture
async def app():
    f = await Friday.start()
    yield f
    await f.close()


@pytest.fixture
def store(app) -> TranscriptStore:
    return TranscriptStore.from_container(app.c)


async def make_user(app, phone: str = PHONE, name: str = "Rahul", *, consent: bool = True,
                    status: UserStatus = UserStatus.ACTIVE) -> User:
    repos = app.c.repos
    user = await repos.users.add(User(phone=phone, status=status))
    await repos.profiles.save(Profile(user_id=user.id, name=name))
    if consent:
        await repos.consents.add(
            Consent(user_id=user.id, kind=ConsentKind.TERMS_PRIVACY, granted=True,
                    recorded_at=app.c.clock.now())
        )
    return user


def make_call(phone: str = PHONE, turns: list[tuple[str, str]] | None = None,
              call_id: str = "call-1", **collected: str) -> tuple[FrontDoorSummary, CallResult]:
    turns = turns if turns is not None else [
        ("friday", "Hello, this is Friday, an AI assistant."),
        ("callee", "haircut book karo kal"),
        ("friday", "Book a haircut tomorrow. Shuru karun?"),
    ]
    result = CallResult(
        task_id=f"frontdoor-{call_id}", provider="scripted", direction=CallDirection.INBOUND,
        to_phone=phone, dial_status=DialStatus.ANSWERED, outcome=CallOutcome.SUCCESS,
        collected=dict(collected),
    )
    for who, text in turns:
        result.transcript.add(
            Speaker.FRIDAY if who == "friday" else Speaker.CALLEE, text, language=Language.HINGLISH
        )
    summary = FrontDoorSummary(
        call_id=call_id, caller="+91******0001", kind=CallerKind.USER, route="serve",
        outcome=CallOutcome.SUCCESS.value, turns=len(turns),
    )
    return summary, result

