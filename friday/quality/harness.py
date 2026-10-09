"""Run one scripted caller through the REAL front door, offline.

Same wiring as the end-to-end tests (Runtime + brain + task engine + simulated telephony on
in-memory SQLite and a fake clock), but a scripted caller leg instead of the simulator party,
so every Friday sentence is captured exactly. Default: the FAKE llm, fake STT/TTS, no network,
no keys, ``.env`` never read. ``live=True`` keeps the simulated telephony but lets the brain use
the real LLM key from the environment (``friday eval --live`` only; never used in tests).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.interfaces import CallEnded
from friday.core.models import (
    AudioClass,
    CallResult,
    ConsentKind,
    DialStatus,
    Language,
    Speaker,
    Transcription,
)
from friday.quality.scenarios import Scenario, Utterance

FRIDAY_NUMBER = "+918065354620"
CALLER = "+919812345678"
START = datetime(2026, 1, 5, 11, 0, tzinfo=IST)  # Monday 11:00 IST
ONBOARDING = ["hi", "{name}", "Bengaluru", "Hinglish", "casual", "I agree", "4826", "4826",
              "skip", "skip", "later"]
_LANG = {"en": Language.EN, "hinglish": Language.HINGLISH, "hi": Language.HI}
_ids = itertools.count(1)


class ScriptedLeg:
    """A caller whose every utterance, silence or hang-up is scripted explicitly."""

    provider = "scripted"

    def __init__(self, script: list[Utterance]) -> None:
        self.script = list(script)
        self.provider_call_id = f"QEV{next(_ids):05d}"
        self.from_number = FRIDAY_NUMBER
        self.spoken: list[tuple[str, Language]] = []
        self.hung_up = False

    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        return DialStatus.ANSWERED

    async def speak(self, text: str, language: Language) -> None:
        if self.hung_up:
            raise CallEnded()
        self.spoken.append((text, language))

    async def listen(self, timeout_s: float) -> Transcription | None:
        if self.hung_up or not self.script:
            raise CallEnded()
        item = self.script.pop(0)
        if item.kind == "silence":
            return None
        if item.kind == "hangup":
            raise CallEnded()
        return Transcription(
            text=item.text, language=_LANG.get(item.lang, Language.HINGLISH),
            audio_class=AudioClass.HUMAN,
        )

    async def send_dtmf(self, digits: str) -> None:  # pragma: no cover
        raise AssertionError("the front door never presses keys")

    async def hangup(self) -> None:
        self.hung_up = True

    async def recording_url(self) -> str | None:
        return None


@dataclass
class CallOutcomeData:
    """Everything the checks look at after one scenario call."""

    scenario: Scenario
    result: CallResult | None = None
    summary: Any = None
    user_exists: bool = False
    consented: bool = False
    tasks: int = 0
    error: str | None = None
    friday: list[str] = field(default_factory=list)
    callee: list[tuple[str, str | None]] = field(default_factory=list)  # (text, language)

    @property
    def ok(self) -> bool:
        return self.error is None and self.result is not None


def eval_settings(*, live: bool = False, **over: Any) -> Settings:
    """Offline by default: fake LLM, no provider keys, ``.env`` NOT read."""
    base: dict[str, Any] = dict(
        mode="simulator", env="test", database_url="sqlite+aiosqlite:///:memory:",
        invite_only=False, profile="pilot", pilot_allowed_numbers=[CALLER],
        sarvam_caller_ids=[FRIDAY_NUMBER], call_record=False,
    )
    if live:
        s = Settings(**base, **over)  # type: ignore[arg-type]  # environment + .env as usual
        return s
    base |= dict(
        _env_file=None, llm_provider="fake", anthropic_api_key=None, openai_api_key=None,
        sarvam_api_key=None, deepgram_api_key=None, elevenlabs_api_key=None,
        google_places_api_key=None,
    )
    base.update(over)
    return Settings(**base)


async def run_scenario(scenario: Scenario, *, live: bool = False) -> CallOutcomeData:
    from friday.api.runtime import Runtime
    from friday.core.container import Container
    from friday.voice.frontdoor import FrontDoorCallFinished

    data = CallOutcomeData(scenario=scenario)
    clock = FakeClock(START)
    c = Container(eval_settings(live=live), clock=clock)
    rt = None
    try:
        await c.db.create_all()
        rt = Runtime(c, fast_pin_hash=True)
        await rt.start(background=False)
        finished: list[FrontDoorCallFinished] = []

        async def on_finished(ev: FrontDoorCallFinished) -> None:
            finished.append(ev)

        c.bus.subscribe(FrontDoorCallFinished, on_finished)
        if scenario.caller == "returning":
            await _onboard(c, rt, scenario.name)
        leg = ScriptedLeg(scenario.script)
        c.telephony.inbound_legs[leg.provider_call_id] = leg
        await rt.callbacks.on_inbound_call(
            CALLER, FRIDAY_NUMBER, answered=True,
            provider_ref=leg.provider_call_id, call_id=leg.provider_call_id,
        )
        await asyncio.wait_for(c.task_engine.drain(), timeout=30)
        if not finished:
            data.error = "the front door did not finish the call"
            return data
        data.summary, data.result = finished[-1].summary, finished[-1].result
        if data.result is not None:
            for t in data.result.transcript.turns:
                if t.speaker == Speaker.FRIDAY:
                    data.friday.append(t.text)
                elif t.speaker == Speaker.CALLEE:
                    data.callee.append((t.text, t.language.value if t.language else None))
        await _read_state(c, data)
    except Exception as e:  # noqa: BLE001 - a crashed scenario is a failed scenario
        data.error = f"{type(e).__name__}: {e}"[:300]
    finally:
        if rt is not None:
            with contextlib.suppress(Exception):
                await rt.stop()
        await c.aclose()
    return data


async def _onboard(c: Any, rt: Any, name: str) -> None:
    """An already-onboarded, consented user (the same WhatsApp flow the tests use)."""
    ch = c.messaging
    for line in ONBOARDING:
        await rt.handle(ch.make_inbound(CALLER, line.format(name=name)), raise_errors=True)
        await c.task_engine.drain()


async def _read_state(c: Any, data: CallOutcomeData) -> None:
    user = await c.repos.users.get_by_phone(CALLER)
    data.user_exists = user is not None
    if user is not None:
        data.consented = await c.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY)
        data.tasks = len(list(await c.repos.tasks.list_for_user(user.id)))
