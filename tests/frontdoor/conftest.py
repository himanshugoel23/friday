"""Front-door fixtures: the real app (Runtime + brain on the fake LLM + task engine + simulated
telephony) with an inbound caller scripted either as a simulator ``SimParty`` or a ``ScriptedLeg``.

No network, no keys, no real Vobiz account."""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

import pytest

from friday.core.interfaces import CallEnded
from friday.core.models import AudioClass, DialStatus, Language, Transcription
from friday.voice.simulator import SimParty
from tests.e2e.harness import Friday

OWN = "+919812345678"  # allow-listed in the pilot tests
OWN2 = "+919812345679"
STRANGER = "+919900000099"  # never allow-listed
FRIDAY_NUMBER = "+918065354620"
LOOKS_ASK = "Looks Unisex Salon mein haircut book karo kal shaam"
H, E, HI = Language.HINGLISH, Language.EN, Language.HI

_ids = itertools.count(1)


class ScriptedLeg:
    """A caller whose every utterance (or silence, or hang-up) is scripted explicitly."""

    provider = "scripted"

    def __init__(self, script: list[Any], *, clock: Any = None, speak_s: float = 0.0) -> None:
        self.script = list(script)
        self.clock = clock
        self.speak_s = speak_s
        self.provider_call_id = f"SCR{next(_ids):05d}"
        self.from_number = FRIDAY_NUMBER
        self.spoken: list[tuple[str, Language]] = []
        self.hung_up = False
        self.gate: asyncio.Event | None = None  # block ``listen`` until set (concurrency tests)
        self.entered = asyncio.Event()

    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        return DialStatus.ANSWERED

    async def speak(self, text: str, language: Language) -> None:
        if self.hung_up:
            raise CallEnded()
        self.spoken.append((text, language))
        if self.clock is not None and self.speak_s:
            await self.clock.sleep(self.speak_s)

    async def listen(self, timeout_s: float) -> Transcription | None:
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.hung_up or not self.script:
            raise CallEnded()
        item = self.script.pop(0)
        if item is None:
            return None  # silence
        if item == "HANGUP":
            raise CallEnded()
        text, lang = item if isinstance(item, tuple) else (item, H)
        return Transcription(text=text, language=lang, audio_class=AudioClass.HUMAN)

    async def send_dtmf(self, digits: str) -> None:  # pragma: no cover
        raise AssertionError("the front door never presses keys")

    async def hangup(self) -> None:
        self.hung_up = True

    async def recording_url(self) -> str | None:
        return None

    @property
    def texts(self) -> list[str]:
        return [t for t, _ in self.spoken]


async def start_friday(profile: str = "pilot", allowed: tuple[str, ...] = (OWN,), **over: Any):
    over.setdefault("sarvam_caller_ids", [FRIDAY_NUMBER])
    f = await Friday.start(profile=profile, pilot_allowed_numbers=list(allowed), **over)
    return f


async def ring(f: Friday, phone: str, leg: ScriptedLeg, *, to: str = FRIDAY_NUMBER) -> None:
    """A call from ``phone`` reaches the real answer path with ``leg`` as the answered leg."""
    f.c.telephony.inbound_legs[leg.provider_call_id] = leg
    await f.rt.callbacks.on_inbound_call(
        phone, to, answered=True, provider_ref=leg.provider_call_id, call_id=leg.provider_call_id
    )
    await f.settle()


async def sim_call(
    f: Friday, phone: str, script: list[str], *, lang: Language = H, to: str = FRIDAY_NUMBER
):
    """A call through the simulator's own inbound path (SimParty speaks ``script`` in turn).
    NB the simulator answers every Friday utterance with one script line, so a greeting made
    of two clips (known user: disclosure + personal line) uses a leading ''."""
    f.c.telephony.register_party(phone, SimParty(name="Caller", language=lang, script=script))
    before = len(f.rt.front_door.history)
    await f.c.telephony.simulate_inbound_call(phone, to)
    assert len(f.rt.front_door.history) == before + 1
    leg = next(x for x in reversed(f.c.telephony.legs) if x.inbound)
    await f.settle()  # let the engine run what the call started
    return f.rt.front_door.history[-1], leg


def said(leg: Any) -> list[str]:
    if hasattr(leg, "spoken"):
        return [t for t, _ in leg.spoken]
    return []


@pytest.fixture
async def pilot():
    f = await start_friday("pilot", (OWN,))
    yield f
    await f.close()
