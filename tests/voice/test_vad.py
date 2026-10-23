# ruff: noqa: E501
"""Voice-activity backends: the energy rule behind the interface is identical to the old segmenter,
the Silero backend (optional extra `vad`) loads, falls back and handles 8 kHz telephony frames."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

import pytest

from friday.core.config import Settings
from friday.voice.audio import pcm16_to_ulaw, rms, tone
from friday.voice.telephony.media import FRAME_MS, Segment, UtteranceSegmenter
from friday.voice.vad import VadFrame, VadModel, build_vad
from friday.voice.vad import silero as silero_mod
from tests.voice.test_vobiz_turns import _frames, _leg, _silence_frames

needs_ort = pytest.mark.skipif(not silero_mod.available(), reason="optional extra `vad` not installed")


# ----------------------------------------------------------------------------- the OLD segmenter
@dataclass
class LegacySegmenter:
    """Verbatim copy of ``UtteranceSegmenter`` before the VAD interface (the reference)."""

    sample_rate: int = 8000
    min_threshold: float = 450.0
    noise_multiplier: float = 3.0
    start_frames: int = 3
    end_silence_ms: int = 700
    short_end_silence_ms: int = 0
    short_utterance_ms: int = 1500
    max_continuous_ms: int = 6000
    noise_floor: float = 200.0
    _buf: bytearray = field(default_factory=bytearray)
    _voiced_run: int = 0
    _silence_ms: int = 0
    _active: bool = False
    _pre: list = field(default_factory=list)

    @property
    def threshold(self) -> float:
        return max(self.min_threshold, self.noise_floor * self.noise_multiplier)

    def feed_pcm16(self, pcm: bytes) -> list[Segment]:
        out: list[Segment] = []
        level = rms(pcm)
        loud = level >= self.threshold
        if not loud and not self._active:
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * level
        if not self._active:
            self._pre = (self._pre + [pcm])[-self.start_frames :]
            self._voiced_run = self._voiced_run + 1 if loud else 0
            if self._voiced_run >= self.start_frames:
                self._active = True
                self._buf = bytearray(b"".join(self._pre))
                self._silence_ms = 0
            return out
        self._buf += pcm
        self._silence_ms = 0 if loud else self._silence_ms + FRAME_MS
        dur_ms = len(self._buf) // 2 * 1000 // self.sample_rate
        end_ms = self.end_silence_ms
        if self.short_end_silence_ms and dur_ms - self._silence_ms <= self.short_utterance_ms:
            end_ms = min(end_ms, self.short_end_silence_ms)
        if self._silence_ms >= end_ms:
            out.append(self._emit(forced=False))
        elif dur_ms >= self.max_continuous_ms:
            out.append(self._emit(forced=True))
            self._active = True
        return out

    def _emit(self, *, forced: bool) -> Segment:
        pcm = bytes(self._buf)
        self._buf = bytearray()
        self._active = forced
        self._voiced_run = 0
        self._silence_ms = 0
        self._pre = []
        return Segment(pcm, self.sample_rate, len(pcm) / 2 / self.sample_rate, forced)


def _noise(rng: random.Random, amp: int) -> bytes:
    import struct

    return struct.pack("<160h", *(rng.randint(-amp, amp) for _ in range(160)))


def _random_frames(seed: int, n: int = 4000) -> list[bytes]:
    """Silence, line noise of changing level, tones (speech stand-in), bursts, a long drone."""
    rng = random.Random(seed)
    frames: list[bytes] = []
    while len(frames) < n:
        kind = rng.choice(("silence", "noise", "tone", "tone", "burst", "drone"))
        length = rng.randint(2, 90) if kind != "drone" else rng.randint(300, 420)
        for _ in range(length):
            if kind == "silence":
                frames.append(b"\x00\x00" * 160)
            elif kind == "noise":
                frames.append(_noise(rng, rng.choice((20, 100, 300, 600, 1200))))
            elif kind == "burst":
                frames.append(_noise(rng, rng.choice((200, 4000))))
            else:
                amp = rng.choice((0.05, 0.2, 0.6, 0.9)) if kind == "tone" else 0.5
                frames.append(tone(rng.choice((220, 440, 880)), 0.02, 8000, amp))
    return frames


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
@pytest.mark.parametrize("cfg", [
    {}, {"end_silence_ms": 900, "short_end_silence_ms": 650, "max_continuous_ms": 20000},
    {"min_threshold": 200.0, "noise_multiplier": 2.0, "start_frames": 2, "end_silence_ms": 400},
])
def test_energy_rule_behind_the_interface_is_identical_to_the_old_segmenter(seed, cfg):
    new, old = UtteranceSegmenter(**cfg), LegacySegmenter(**cfg)
    emitted = 0
    for i, f in enumerate(_random_frames(seed)):
        a, b = new.feed_pcm16(f), old.feed_pcm16(f)
        assert [(s.pcm16, s.duration_s, s.forced_cut) for s in a] == [
            (s.pcm16, s.duration_s, s.forced_cut) for s in b], f"frame {i}"
        assert new.threshold == old.threshold, f"threshold at frame {i}"
        assert (new._active, new._silence_ms, new._voiced_run) == (
            old._active, old._silence_ms, old._voiced_run)
        emitted += len(a)
    assert emitted >= 3  # the sequences really exercise open / close / forced cuts


def test_energy_is_the_default_everywhere():
    assert UtteranceSegmenter().vad is None and UtteranceSegmenter().backend == "energy"
    assert Settings(_env_file=None).voice_vad_backend == "silero"  # auto fallback to energy
    assert build_vad("energy") is None and build_vad("anything-else") is None


async def test_the_default_leg_uses_the_energy_rule_and_matches_the_old_segmenter():
    leg, _ = await _leg()
    assert leg._segmenter.vad is None and leg.eot is None
    old = LegacySegmenter(end_silence_ms=900, short_end_silence_ms=650, max_continuous_ms=20000)
    expected: list[Segment] = []
    from friday.voice.audio import ulaw_to_pcm16

    for payload in _frames(1.2, 0.9) + _silence_frames(1.0) + _frames(0.5, 0.2) + _silence_frames(1.2):
        import base64

        leg.on_media(payload)
        pcm = ulaw_to_pcm16(base64.b64decode(payload))
        for i in range(0, len(pcm) - 319, 320):
            expected += old.feed_pcm16(pcm[i : i + 320])
    got = []
    while not leg._segments.empty():
        got.append(leg._segments.get_nowait())
    assert len(got) == len(expected) == 2
    assert [(s.pcm16, s.forced_cut) for s in got] == [(s.pcm16, s.forced_cut) for s in expected]


# ----------------------------------------------------------------------------- a stand-in neural VAD
class ScriptedVad(VadModel):
    """Probability per frame from a list; hysteresis like Silero's."""

    name = "scripted"
    pre_roll_frames = 4

    def __init__(self, probs, start=0.5, stop=0.35):
        self.probs, self.start, self.stop, self.i, self._on = list(probs), start, stop, 0, False
        self.resets = 0

    def process(self, pcm16, sample_rate=8000):
        p = self.probs[min(self.i, len(self.probs) - 1)]
        self.i += 1
        self._on = p >= (self.stop if self._on else self.start)
        return VadFrame(self._on, p, rms(pcm16))

    def reset(self):
        self.resets += 1


def _quiet() -> bytes:
    return b"\x00\x00" * 160


def test_a_probability_backend_drives_the_segmenter_with_hysteresis_and_padding():
    # 6 quiet frames, 30 speech frames (one dip to 0.4: above the stop bar, so no break), silence
    probs = [0.02] * 6 + [0.9] * 14 + [0.4] + [0.9] * 15 + [0.05] * 60
    seg = UtteranceSegmenter(end_silence_ms=400, vad=ScriptedVad(probs))
    out: list[Segment] = []
    for _ in range(len(probs)):
        out += seg.feed_pcm16(_quiet())  # loudness is irrelevant: only the backend decides
    assert len(out) == 1
    # padding: the 4 pre-roll frames before speech plus the speech plus the 400 ms close wait
    frames = len(out[0].pcm16) // 320
    assert frames >= 4 + 30 + 20 - 3
    assert seg.vad.resets >= 1  # state cleared after the utterance


def test_a_dip_below_the_stop_probability_ends_speech_and_min_frames_still_apply():
    seg = UtteranceSegmenter(end_silence_ms=200, vad=ScriptedVad([0.9, 0.9] + [0.05] * 30))
    out = []
    for _ in range(32):
        out += seg.feed_pcm16(_quiet())
    assert out == []  # two speech frames are fewer than start_frames: a click, not an utterance


def test_a_failing_backend_falls_back_to_the_energy_rule_for_good(caplog):
    class Boom(VadModel):
        name = "boom"

        def process(self, pcm16, sample_rate=8000):
            raise RuntimeError("model exploded")

    seg = UtteranceSegmenter(end_silence_ms=300, vad=Boom())
    out = []
    loud = tone(440, 0.02, 8000, 0.9)
    with caplog.at_level("WARNING"):
        for _ in range(15):
            out += seg.feed_pcm16(loud)
        for _ in range(20):
            out += seg.feed_pcm16(_quiet())
    assert seg.vad is None and seg._vad_failed and seg.backend == "energy"
    assert len(out) == 1  # the call went on with the energy rule
    assert any("using the energy rule" in r.message for r in caplog.records)


async def test_barge_in_needs_both_the_loudness_gate_and_the_stricter_probability():
    async def attempt(prob: float, amp: float) -> bool:
        leg, _ = await _leg()
        leg.barge_in_prob = 0.75
        leg._playing = True
        for _ in range(12):
            fr = VadFrame(True, prob, 4000.0 * amp)
            leg._watch_for_barge_in(tone(440, 0.02, 8000, amp), fr)
        await asyncio.sleep(0)
        return leg._barged

    assert await attempt(0.95, 0.9) is True  # loud and surely speech
    assert await attempt(0.6, 0.9) is False  # speech by the start bar, below the barge-in bar
    assert await attempt(0.95, 0.01) is False  # her own faint echo: the loudness gate still holds


async def test_energy_barge_in_is_unchanged_without_a_probability():
    leg, sent = await _leg()
    leg._playing = True
    for f in _frames(0.6, 0.9):
        leg.on_media(f)
    await asyncio.sleep(0)
    assert leg._barged and any(m.get("event") == "clearAudio" for m in sent)


# ----------------------------------------------------------------------------- fallback to energy
def test_silero_missing_runtime_falls_back(monkeypatch, caplog):
    monkeypatch.setattr(silero_mod, "available", lambda: False)
    silero_mod._reset_for_tests()
    with caplog.at_level("WARNING"):
        assert build_vad("silero") is None
    assert any("silero VAD unavailable" in r.message for r in caplog.records)
    silero_mod._reset_for_tests()


def test_silero_model_with_the_wrong_hash_is_refused(monkeypatch, tmp_path):
    bad = tmp_path / "silero_vad.onnx"
    bad.write_bytes(b"not the model")
    silero_mod._reset_for_tests()
    monkeypatch.setattr(silero_mod, "MODEL_PATH", bad)
    monkeypatch.setattr(silero_mod, "available", lambda: True)
    with pytest.raises(RuntimeError, match="sha256"):
        silero_mod.load_session(bad)
    silero_mod._reset_for_tests()


async def test_a_leg_asked_for_silero_that_cannot_load_keeps_the_energy_rule(monkeypatch):
    monkeypatch.setattr(silero_mod, "available", lambda: False)
    silero_mod._reset_for_tests()
    import httpx

    from friday.core.models import OutboundCallRequest
    from friday.voice.telephony.sarvam import SarvamTelephony
    from tests.voice.test_twilio import StubSTT, StubTTS

    tel = SarvamTelephony(
        auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
        public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=StubTTS(),
        transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"request_uuid": "u1"})),
        vad={"backend": "silero"},
    )
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    assert leg._segmenter.vad is None and leg._segmenter.backend == "energy"
    silero_mod._reset_for_tests()


def test_the_pinned_model_file_and_licence_ship_in_the_repo():
    import hashlib
    from pathlib import Path

    d = Path(silero_mod.MODEL_PATH).parent
    assert hashlib.sha256((d / "silero_vad.onnx").read_bytes()).hexdigest() == silero_mod.MODEL_SHA256
    lic = (d / "LICENSE-silero-vad.txt").read_text()
    assert lic.startswith("MIT License") and "Silero Team" in lic
    assert silero_mod.MODEL_URL.endswith("silero_vad.onnx") and "v5.1.2" in silero_mod.MODEL_URL


# ----------------------------------------------------------------------------- the real model
@needs_ort
def test_silero_runs_on_8khz_frames_of_20ms_in_256_sample_windows():
    v = silero_mod.SileroVad()
    assert v._window == 256 and v._ctx_n == 32 and v.sample_rate == 8000
    for _ in range(8):  # 8 frames x 160 samples = 1280 samples = exactly 5 windows
        fr = v.process(b"\x00\x00" * 160, 8000)
        assert fr.prob is not None and 0.0 <= fr.prob <= 1.0
    assert v.runs == 5
    assert v.process(b"\x00\x00" * 100, 8000).prob is not None  # odd sizes are buffered
    with pytest.raises(ValueError):
        v.process(b"\x00\x00" * 160, 16000)
    with pytest.raises(ValueError):
        silero_mod.SileroVad(sample_rate=44100)


@needs_ort
def test_silero_16khz_uses_512_sample_windows():
    v = silero_mod.SileroVad(sample_rate=16000)
    assert v._window == 512 and v._ctx_n == 64
    for _ in range(4):
        v.process(b"\x00\x00" * 320, 16000)
    assert v.runs == 2


@needs_ort
def test_silero_is_deterministic_stateful_and_resets():
    rng = random.Random(5)
    frames = [_noise(rng, 800) for _ in range(40)]
    a, b = silero_mod.SileroVad(), silero_mod.SileroVad()
    pa = [a.process(f).prob for f in frames]
    pb = [b.process(f).prob for f in frames]
    assert pa == pb
    a.reset()
    assert [a.process(f).prob for f in frames] == pa  # reset = a fresh start


@needs_ort
def test_silero_calls_silence_and_hum_non_speech():
    v = silero_mod.SileroVad()
    hum = tone((50, 100, 150), 2.0, 8000, 0.3)
    probs = [v.process(hum[i : i + 320]).prob for i in range(0, len(hum) - 319, 320)]
    assert max(probs[10:]) < 0.5  # a mains hum is not a voice
    v.reset()
    assert all(v.process(b"\x00\x00" * 160).speech is False for _ in range(30))


@needs_ort
async def test_a_leg_configured_for_silero_decodes_mulaw_and_feeds_the_model():
    import httpx

    from friday.core.models import OutboundCallRequest
    from friday.voice.telephony.sarvam import SarvamTelephony
    from tests.voice.test_twilio import StubSTT, StubTTS

    tel = SarvamTelephony(
        auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
        public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=StubTTS(),
        transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"request_uuid": "u1"})),
        vad={"backend": "silero", "start_prob": 0.5, "stop_prob": 0.35, "barge_prob": 0.8},
    )
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    leg.set_media_format({"encoding": "audio/x-mulaw", "sampleRate": 8000})
    assert leg._segmenter.backend == "silero" and leg.barge_in_prob == 0.8
    for f in _silence_frames(0.5) + _frames(0.3, 0.5):
        leg.on_media(f)
    assert leg._segmenter.vad.runs > 10  # every frame reached the model, 8 kHz windows
    assert leg._segmenter.vad is not None and leg._segmenter.sample_rate == 8000
    _ = pcm16_to_ulaw


@needs_ort
def test_the_offline_evaluation_runs_end_to_end_on_synthetic_stand_ins():
    from friday.voice.vad import evaluate

    s = evaluate.run(None, quick=True)
    assert s["speech_source"] == "synthetic tones" and s["cells"]
    assert s["silero_frames_per_second"] > 0 and s["energy_frames_per_second"] > 0
    assert 0.0 <= s["silero_overall"]["false_trigger_rate"] <= 1.0
    text = evaluate.format_report(s)
    assert "SYNTHETIC evidence only" in text and "CPU silero" in text
