# ruff: noqa: E501
"""Regression set: every persona x every language must pass every safety invariant."""

from __future__ import annotations

import types

import pytest

from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped
from friday.liveagent.sarvam_adapter import SarvamLegPort
from friday.liveagent.simulation import PERSONAS, play, render_table, run_all
from friday.liveagent.simulation.runner import LANGS


def test_coverage_of_the_regression_set() -> None:
    assert len(PERSONAS) >= 15 and len(LANGS) == 3
    assert len({p.id for p in PERSONAS}) == len(PERSONAS)
    kinds = {p.kind.value for p in PERSONAS}
    assert {"family_elder", "friend", "provider", "customer_care", "official", "unknown"} <= kinds


@pytest.mark.parametrize("lang", list(LANGS), ids=lambda x: x.value)
@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.id)
async def test_persona(persona, lang) -> None:
    r = await play(persona, lang)
    assert r.passed, r.failures


async def test_table_is_written() -> None:
    results = await run_all(PERSONAS[:3])
    table = render_table(results)
    assert "persona | lang | status" in table and "9/9 passed" in table


async def test_llm_policy_with_a_bad_model_passes_the_same_personas() -> None:
    from friday.liveagent.moves import LLMMovePolicy

    class Chaos:
        async def propose(self, payload):
            return {
                "move": "answer_from_brief",
                "variant": "fact",
                "slots": {"fact": "Rs 85000 per month"},
            }

    for p in PERSONAS[:12]:
        r = await play(p, CallLanguage.HINGLISH, policy=LLMMovePolicy(Chaos()))
        assert r.passed, (p.id, r.failures)


# ------------------------------------------------------------------ Sarvam adapter


class CallEnded(Exception):  # same class name as friday.core.interfaces.CallEnded
    pass


class FakeLeg:
    def __init__(self):
        self.said = []
        self.keys = []
        self.ended = False

    async def speak(self, text, language):
        if self.ended:
            raise CallEnded()
        self.said.append((text, language.value))

    async def listen(self, timeout_s):
        if self.ended:
            raise CallEnded()
        return types.SimpleNamespace(
            text="haan ji",
            language=None,
            confidence=0.9,
            audio_class=types.SimpleNamespace(value="human"),
            duration_s=1.5,
        )

    async def send_dtmf(self, digits):
        self.keys.append(digits)

    async def hangup(self):
        self.ended = True


async def test_sarvam_adapter_maps_types_and_the_end_signal() -> None:
    leg = FakeLeg()
    port = SarvamLegPort(leg)
    await port.speak("Hello", CallLanguage.HINGLISH)
    u = await port.listen(3)
    assert u.text == "haan ji" and u.audio_class == "human" and u.confidence == 0.9
    await port.send_dtmf("2")
    assert leg.keys == ["2"] and leg.said == [("Hello", "hinglish")]
    await port.hangup()
    with pytest.raises(CallDropped):
        await port.listen(1)
    with pytest.raises(CallDropped):
        await port.speak("x", CallLanguage.EN)
