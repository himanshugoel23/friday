"""The Vobiz call leg hands early transcripts to the session ONLY when the hooks are set."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from friday.core.config import Settings
from friday.voice.session import _Session
from tests.voice.test_vobiz_turns import _frames, _leg_with_counting_stt, _silence_frames


async def test_hooks_default_to_none_and_the_leg_behaves_as_before():
    leg, stt = await _leg_with_counting_stt()
    assert leg.early_text_hook is None and leg.early_cancel_hook is None
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    assert stt.calls == 1 and leg._early_text == ""  # early transcription as before, no extras


async def test_early_transcript_is_handed_over_while_the_pause_is_still_running():
    leg, stt = await _leg_with_counting_stt()
    texts: list[str] = []
    leg.early_text_hook = texts.append
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    assert texts == ["haan bataiye"]  # before the 900 ms wait is over: nothing committed yet
    assert leg._segments.empty()
    for f in _silence_frames(0.7):
        leg.on_media(f)
    seg = await asyncio.wait_for(leg._segments.get(), 1)
    t = await leg._transcribe(seg)
    assert t is not None and t.text == "haan bataiye" and stt.calls == 1
    assert leg._early_text == ""  # the commit consumed the guess


async def test_caller_continuing_to_speak_cancels_the_guess():
    leg, _stt = await _leg_with_counting_stt()
    texts: list[str] = []
    cancels: list[str] = []
    leg.early_text_hook, leg.early_cancel_hook = texts.append, cancels.append
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    for f in _frames(0.3, 0.9):
        leg.on_media(f)
    assert texts == ["haan bataiye"] and cancels == ["caller kept talking"]


async def test_barge_in_while_friday_speaks_cancels_the_guess():
    leg, _stt = await _leg_with_counting_stt()
    cancels: list[str] = []
    leg.early_text_hook, leg.early_cancel_hook = (lambda t: None), cancels.append
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    leg._playing = True  # Friday started talking
    for f in _frames(0.2, 0.9):
        leg.on_media(f)
    assert cancels and cancels[0].startswith("friday speaking")


async def test_a_failing_hook_never_breaks_the_call_leg():
    leg, _stt = await _leg_with_counting_stt()

    def boom(_t: str) -> None:
        raise RuntimeError("policy exploded")

    leg.early_text_hook = boom
    for f in _frames(1.0, 0.9) + _silence_frames(1.2):
        leg.on_media(f)
    await asyncio.sleep(0.05)
    seg = await asyncio.wait_for(leg._segments.get(), 1)
    assert (await leg._transcribe(seg)) is not None


def _fake_session(on: bool, policy: object) -> SimpleNamespace:
    return SimpleNamespace(
        settings=Settings(_env_file=None, voice_speculative_understanding=on),
        r=SimpleNamespace(policy=policy),
        brief=object(),
        transcript=object(),
    )


async def test_session_attaches_hooks_only_with_the_switch_on():
    leg, _ = await _leg_with_counting_stt()
    policy = SimpleNamespace(speculate=lambda *a: True, cancel_speculation=lambda *a: True)
    off = _fake_session(False, policy)
    _Session._attach_speculation(off, leg)  # type: ignore[arg-type]
    assert leg.early_text_hook is None and leg.early_cancel_hook is None

    on = _fake_session(True, policy)
    on._speculate = lambda t: None
    on._cancel_speculation = lambda r: None
    _Session._attach_speculation(on, leg)  # type: ignore[arg-type]
    assert leg.early_text_hook is on._speculate and leg.early_cancel_hook is on._cancel_speculation


async def test_session_skips_policies_without_speculation_support():
    leg, _ = await _leg_with_counting_stt()
    on = _fake_session(True, object())  # e.g. the free-form brain policy
    _Session._attach_speculation(on, leg)  # type: ignore[arg-type]
    assert leg.early_text_hook is None


def test_all_three_switches_default_off():
    s = Settings(_env_file=None)
    assert s.voice_speculative_understanding is False
    assert s.llm_stream_to_tts is False
    assert s.intent_classifier is False
    assert 0.5 <= s.intent_classifier_threshold <= 1.0


# --------------------------------------------------------------------------- streaming partials
async def test_a_stable_streaming_partial_starts_speculation_even_for_long_speech():
    from tests.voice.test_stream_stt import _speak_then_pause, _stream_leg

    leg = await _stream_leg()
    texts: list[str] = []
    leg.early_text_hook = texts.append
    _speak_then_pause(leg)
    long_text = "haan ji main ye kehna chahta tha ki aap kal subah aa jaiye"
    leg._stt_partial(long_text, "hi-IN", 0)
    await asyncio.sleep(0.2)
    assert texts == [long_text]
    assert leg._utterances.empty()  # not committed: only the final may commit long speech


async def test_a_changed_partial_cancels_the_earlier_guess():
    from tests.voice.test_stream_stt import _speak_then_pause, _stream_leg

    leg = await _stream_leg()
    texts, cancels = [], []
    leg.early_text_hook, leg.early_cancel_hook = texts.append, cancels.append
    _speak_then_pause(leg)
    first = "haan ji main ye kehna chahta tha ki aap kal"  # long: waits for the final
    leg._stt_partial(first, "hi-IN", 0)
    await asyncio.sleep(0.3)
    leg._stt_partial(first + " subah aa jaiye", "hi-IN", 0)
    assert texts == [first] and cancels == ["partial changed"]


async def test_streaming_without_hooks_is_unchanged():
    from tests.voice.test_stream_stt import _speak_then_pause, _stream_leg

    leg = await _stream_leg()
    _speak_then_pause(leg)
    leg._stt_partial("haan ji bataiye", "hi-IN", 0)
    await asyncio.sleep(0.2)
    assert leg._utterances.get_nowait().text == "haan ji bataiye"
