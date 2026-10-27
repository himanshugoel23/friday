"""With every switch OFF (the default) behaviour is identical to before the latency work."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from friday.brain.fake_llm import FakeLLM
from friday.brain.service import FridayBrain, compact_transcript
from friday.core.config import Settings
from friday.core.models import CallActionType, Speaker, Transcript
from friday.playbooks.engine import PlaybookPolicy
from friday.voice.session import build_scripted_policy
from tests.latency.test_speculative import CountingUnderstander
from tests.playbooks.conftest import drive, make_brief

# replies that exercise rules-sure, rules-unsure (model), hold, price, refusal and stop paths
SCRIPT = [
    "Haan boliye", "haan toh phir", "arre wo toh theek hai lekin dekhte hain", "ek second",
    "400 rupaye lagega", "parking hai kya", "achha toh phir kya karna hai aapko",
    "advance dena padega", "dobara call mat karna",
]


def test_every_silent_switch_defaults_to_on_since_the_offline_checks_pass():
    s = Settings(_env_file=None)  # 2026-10-23: founder decision, silent latency switches ON
    assert (s.voice_speculative_understanding, s.llm_stream_to_tts, s.intent_classifier) == (
        True, True, True)


def test_the_scripted_policy_is_built_without_the_extras_when_switched_off():
    s = Settings(_env_file=None, intent_classifier=False, voice_speculative_understanding=False)
    c = SimpleNamespace(settings=s, brain=None, clock=None)
    policy = build_scripted_policy(c)  # type: ignore[arg-type]
    pp = policy.playbook_policy
    assert pp.classifier is None and pp.speculative is False


def test_the_scripted_policy_wires_the_switches_when_they_are_on():
    s = Settings(_env_file=None, intent_classifier=True, intent_classifier_threshold=0.95,
                 voice_speculative_understanding=True)
    pp = build_scripted_policy(SimpleNamespace(settings=s, brain=None, clock=None)).playbook_policy  # type: ignore[arg-type]
    assert pp.speculative is True and pp.classifier_threshold == 0.95
    assert pp.classifier is not None  # the gate-passed model shipped in the repo


def test_classifier_switch_on_without_a_valid_model_means_no_classifier(tmp_path, monkeypatch):
    from friday.playbooks import classifier as clf

    monkeypatch.setattr(clf, "MODEL_PATH", tmp_path / "none.json")
    monkeypatch.setattr(clf, "VERSION_PATH", tmp_path / "none.version.json")
    s = Settings(_env_file=None, intent_classifier=True)
    pp = build_scripted_policy(SimpleNamespace(settings=s, brain=None, clock=None)).playbook_policy  # type: ignore[arg-type]
    assert pp.classifier is None  # falls back to rules + model


async def _run(policy: PlaybookPolicy) -> list[tuple[str, str | None]]:
    run = await drive(list(SCRIPT), policy=policy, brief=make_brief())
    return [(a.type.value, a.text) for a in run.actions]


@pytest.mark.parametrize("mode", ["auto", "always", "never"])
async def test_scripted_calls_are_identical_with_the_switches_off(mode):
    und_a, und_b = CountingUnderstander(), CountingUnderstander()
    plain = PlaybookPolicy(understander=und_a, llm_mode=mode)
    explicit = PlaybookPolicy(understander=und_b, llm_mode=mode, classifier=None,
                              speculative=False)
    assert await _run(plain) == await _run(explicit)
    assert und_a.calls == und_b.calls  # the same model calls, on the same replies
    assert not plain.stats and not explicit.stats  # no latency feature recorded anything


async def test_the_model_is_asked_exactly_as_often_as_before_when_off():
    und = CountingUnderstander()
    run = await drive(["Haan boliye", "haan toh phir"], policy=PlaybookPolicy(understander=und),
                      brief=make_brief())
    assert und.calls == ["haan toh phir"] and run.state.llm_calls == 1


async def test_the_dry_run_personas_match_the_stored_baseline():
    from friday.playbooks.dryrun import find_regressions, load_baseline, run_dryrun

    report = await run_dryrun("salon_booking")
    assert find_regressions(report, load_baseline("salon_booking")) == []


def test_the_brain_has_no_streaming_client_by_default():
    brain = FridayBrain(FakeLLM(), Settings(_env_file=None))
    assert brain.streaming_llm is None


async def test_the_free_form_turn_is_unchanged_by_the_payload_refactor():
    from tests.latency.test_streaming import _brief, _transcript

    brain = FridayBrain(FakeLLM(), Settings(_env_file=None, mode="simulator", env="test"))
    brief, tr = _brief(), _transcript("Hello, main Friday.")
    expect: dict[str, Any] = {
        **compact_transcript(brief, tr),
        "answers": [],
        "speakable": sorted(lang.value for lang in brain.speakable) if brain.speakable else None,
        "transcript_full": tr.model_dump(mode="json", exclude_none=True),  # the fake LLM needs it
    }
    assert brain._call_turn_payload(brief, tr, []) == expect
    action = await brain.next_call_action(brief, tr, [])
    assert action.type in set(CallActionType)  # still answers through the ordinary path


async def test_streamed_entry_point_with_the_switch_off_is_the_ordinary_call():
    from tests.latency.test_streaming import _brief, _transcript

    brain = FridayBrain(FakeLLM(), Settings(_env_file=None, mode="simulator", env="test"))
    brief, tr = _brief(), _transcript("Hello, main Friday.")
    spoken: list[str] = []

    async def speak(s: str) -> None:
        spoken.append(s)

    turn = await brain.next_call_action_streamed(brief, tr, [], speak=speak)
    plain = await brain.next_call_action(brief, tr, [])
    assert spoken == [] and turn.fell_back
    assert (turn.action.type, turn.action.text) == (plain.type, plain.text)


async def test_leg_and_session_do_nothing_extra_by_default():
    from tests.voice.test_vobiz_turns import _frames, _leg_with_counting_stt, _silence_frames

    leg, stt = await _leg_with_counting_stt()
    for f in _frames(1.0, 0.9) + _silence_frames(1.3):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    seg = await asyncio.wait_for(leg._segments.get(), 1)
    t = await leg._transcribe(seg)
    assert t is not None and stt.calls == 1
    assert leg.early_text_hook is None and leg.early_cancel_hook is None and leg._spec_task is None


def test_policy_without_switches_ignores_speculation_calls():
    pol = PlaybookPolicy()
    brief = make_brief()
    tr = Transcript()
    tr.add(Speaker.FRIDAY, "x")
    assert pol.speculate(brief, tr, "haan toh phir") is False
    assert pol.cancel_speculation(tr) is False
