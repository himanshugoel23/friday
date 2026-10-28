"""TTS health: breaker, backoff, log-once, call refusal, mid-call failure, doctor line."""

from __future__ import annotations

import logging

import pytest

from friday.core.interfaces import ProviderError
from friday.core.models import CallOutcome, DialStatus, Language
from friday.voice.tts.cache import CachedTTS
from friday.voice.tts.fake import build_fake_tts
from friday.voice.tts.health import (
    TTS_FAILED,
    TTS_UNAVAILABLE,
    TTS_UNAVAILABLE_LINE,
    TTSHealth,
    TTSUnavailable,
    classify,
    get_health,
    read_snapshot,
)

from .conftest import LOOKS, ScriptedPolicy, make_brief, no_answer_user, say

QUOTA = "[sarvam] HTTP 402 insufficient_quota_error No credits available"
RATE = "[sarvam] HTTP 429 rate limit exceeded"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FlakyTTS:
    """Fake vendor: raises the queued error text, else succeeds. Counts vendor calls."""

    name = "sarvam"
    supported_languages = frozenset(Language)

    def __init__(self, fail: str | None = None) -> None:
        self.fail, self.calls = fail, 0
        from friday.core.models import VoiceProfile

        self._v = VoiceProfile(voice_id="v", language=Language.EN, provider="sarvam")

    def voice_for(self, language):
        return self._v

    async def synthesize(self, text, language, *, voice=None):
        from friday.core.models import AudioClip

        self.calls += 1
        if self.fail:
            raise ProviderError("sarvam", self.fail)
        return AudioClip(data=text.encode(), mime="x", sample_rate=8000)


def make(fail=None, **kw):
    clock = Clock()
    health = TTSHealth(now=clock, **kw)
    inner = FlakyTTS(fail)
    return CachedTTS(inner, health=health), inner, health, clock


def test_classify():
    assert classify(QUOTA) == "quota"
    assert classify(RATE) == "rate"
    assert classify("[sarvam] HTTP 503 bad gateway") == "server"
    assert classify("[sarvam] HTTP 400 bad text") is None


async def test_402_opens_breaker_at_once_and_stops_the_storm():
    tts, inner, health, _ = make(QUOTA)
    lines = [f"line {i}" for i in range(10)]
    await tts.prerender(lines, Language.EN)
    assert inner.calls == 1 and health.unavailable()  # one vendor call, not ten
    for _ in range(5):  # the retry storm: more prerenders while open make NO vendor call
        await tts.prerender(lines, Language.EN)
    assert inner.calls == 1


async def test_429_needs_repeats_then_opens():
    tts, inner, health, _ = make(RATE)
    await tts.prerender(["a", "b"], Language.EN)
    assert not health.unavailable() and inner.calls == 2
    await tts.prerender(["c", "d"], Language.EN)
    assert health.unavailable() and inner.calls == 3  # third consecutive 429 opened it


async def test_backoff_is_exponential_and_probe_is_single():
    tts, inner, health, clock = make(RATE, threshold=1, base_s=5.0, max_s=100.0)
    await tts.prerender(["a"], Language.EN)
    assert health.open_until - clock.t == 5
    clock.t += 5  # cool-down over: ONE probe goes out
    await tts.prerender(["b"], Language.EN)
    assert inner.calls == 2 and health.open_until - clock.t == 10  # doubled
    assert not health.allow()
    clock.t += 10
    await tts.prerender(["c"], Language.EN)
    assert health.open_until - clock.t == 20


async def test_recovery_resets_and_closes():
    tts, inner, health, clock = make(QUOTA)
    await tts.prerender(["a"], Language.EN)
    assert health.unavailable()
    inner.fail = None
    clock.t += 301
    assert not health.unavailable()
    assert await tts.prerender(["a"], Language.EN) == 1  # probe succeeds
    assert not health.open and health.opens == 0 and health.last_ok_at == clock.t
    await tts.prerender(["x", "y"], Language.EN)
    assert inner.calls == 4


async def test_log_once_per_state_change(caplog):
    tts, inner, health, clock = make(QUOTA)
    with caplog.at_level(logging.INFO, logger="friday"):
        for _ in range(20):
            await tts.prerender(["a", "b", "c"], Language.EN)
        assert len([r for r in caplog.records if "breaker" in r.getMessage()]) == 1
        assert not [r for r in caplog.records if "prerender failed" in r.getMessage()]
        inner.fail = None
        clock.t += 400
        await tts.prerender(["a"], Language.EN)
    msgs = [r.getMessage() for r in caplog.records if "tts sarvam" in r.getMessage()]
    assert len(msgs) == 2 and "opened" in msgs[0] and "recovered" in msgs[1]


async def test_cached_line_still_plays_while_open():
    tts, inner, health, _ = make()
    await tts.prerender(["hello"], Language.EN)
    health.record_error("sarvam", QUOTA)
    clip, hit = await tts.synthesize_cached("hello", Language.EN)
    assert hit
    with pytest.raises(TTSUnavailable):
        await tts.synthesize_cached("new line", Language.EN)


def test_state_file_for_doctor(tmp_path):
    h = TTSHealth(path=tmp_path / "v" / "h.json")
    h.record_error("sarvam", QUOTA)
    snap = read_snapshot(tmp_path / "v" / "h.json")
    assert snap["open"] and snap["last_error"]["kind"] == "quota"


async def test_recovery_waiter_fires_once():
    h = TTSHealth()
    got = []

    async def cb():
        got.append(1)

    h.record_error("sarvam", QUOTA)
    h.on_recovery(cb)
    h.record_success()
    h.record_success()
    import asyncio

    await asyncio.sleep(0)
    assert got == [1]


# ---------------------------------------------------------------- the call path
async def test_call_refused_when_tts_down(make_runner, sim):
    get_health().record_error("sarvam", QUOTA)
    placed = []
    orig = sim.place_call

    async def spy(req):
        placed.append(req)
        return await orig(req)

    sim.place_call = spy
    result = await make_runner(ScriptedPolicy([say("hi")])).run(make_brief(LOOKS), no_answer_user)
    assert not placed  # no real dial
    assert result.outcome == CallOutcome.FAILED and result.error == TTS_UNAVAILABLE
    assert result.dial_status == DialStatus.FAILED


async def test_call_goes_ahead_when_breaker_closed(make_runner):
    from friday.core.models import CallOutcome as O

    from .conftest import hangup

    r = await make_runner(ScriptedPolicy([say("hi"), hangup(O.PARTIAL)])).run(
        make_brief(LOOKS), no_answer_user
    )
    assert r.error != TTS_UNAVAILABLE


async def test_tts_dies_mid_call_hangs_up_and_marks_tts_failed(make_runner, sim):
    orig = sim.place_call

    async def place(req):
        leg = await orig(req)
        real, n = leg.speak, 0

        async def speak(text, language):
            nonlocal n
            n += 1
            if n >= 2:  # disclosure goes out, the next line hits the dead vendor
                get_health().record_error("sarvam", QUOTA)
                raise ProviderError("sarvam", QUOTA)
            await real(text, language)

        leg.speak = speak
        return leg

    sim.place_call = place
    result = await make_runner(ScriptedPolicy([say("Slot?"), say("Rate?")])).run(
        make_brief(LOOKS), no_answer_user
    )
    assert result.error == TTS_FAILED and result.outcome == CallOutcome.FAILED


# ---------------------------------------------------------------- engine + doctor
def test_chat_line_text():
    assert TTS_UNAVAILABLE_LINE == (
        "Voice is temporarily unavailable on my side, so I have not called. "
        "I will tell you when it is back."
    )


def test_doctor_line_from_last_errors(tmp_path):
    from friday.core.config import Settings
    from friday.ops import doctor as d

    st = Settings(_env_file=None, env="test", tts_health_file=str(tmp_path / "h.json"))
    s = d.Section("providers")
    d._tts_health_line(s, st)
    assert s.checks[-1].status == d.OK and "no provider errors" in s.checks[-1].message
    h = TTSHealth(path=st.tts_health_file)
    h.record_error("sarvam", QUOTA)
    s = d.Section("providers")
    d._tts_health_line(s, st)
    assert s.checks[-1].status == d.FAIL and "402" in s.checks[-1].message
    h.record_success()
    s = d.Section("providers")
    d._tts_health_line(s, st)
    assert s.checks[-1].status == d.OK and "recovered" in s.checks[-1].message
