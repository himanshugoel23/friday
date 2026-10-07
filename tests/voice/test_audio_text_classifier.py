"""V-5 classifier, V-6 voice notes, audio + text helpers, V-9 latency maths."""

from __future__ import annotations

import math
import random
from array import array

import pytest

from friday.core.interfaces import AudioClassifier
from friday.core.models import AudioClass, AudioClip, Language, MediaBlob
from friday.voice.audio import (
    build_opus_ogg,
    dtmf_pcm16,
    ogg_crc,
    parse_opus_ogg,
    pcm16_to_ulaw,
    pcm16_to_wav,
    resample_pcm16,
    silence,
    tone,
    ulaw_to_pcm16,
    wav_to_pcm16,
)
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.latency import LatencyRecorder, percentile
from friday.voice.stt.fake import FakeSTT
from friday.voice.telephony.media import UtteranceSegmenter
from friday.voice.text import detect_language, mask_digits, redact_secrets, strip_fillers
from friday.voice.voicenote import MAX_VOICE_NOTE_S, prepare_voice_note, transcribe_voice_note


def speech(seconds=2.0, sr=8000):
    rnd = random.Random(1)
    out = array("h")
    for i in range(int(sr * seconds)):
        t = i / sr
        env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        out.append(
            int(
                12000 * env * (rnd.random() * 2 - 1) * 0.5
                + 6000 * env * math.sin(2 * math.pi * 180 * t)
            )
        )
    return out.tobytes()


def wav(pcm, sr=8000):
    return AudioClip(data=pcm16_to_wav(pcm, sr), mime="audio/wav", sample_rate=sr)


@pytest.mark.parametrize(
    ("pcm", "cls"),
    [
        (silence(2.0), AudioClass.SILENCE),
        (tone(1000, 0.5) + silence(1.0), AudioClass.VOICEMAIL),  # answering-machine beep
        (tone((262, 330, 392), 4.0), AudioClass.HOLD_MUSIC),
        (speech(), AudioClass.HUMAN),
    ],
)
async def test_classifier_acoustics(pcm, cls):
    c = HeuristicAudioClassifier()
    assert isinstance(c, AudioClassifier)
    assert (await c.classify(wav(pcm))).audio_class == cls


async def test_classifier_mulaw_input():
    c = HeuristicAudioClassifier()
    clip = AudioClip(
        data=pcm16_to_ulaw(tone((262, 330, 392), 3.0)), mime="audio/x-mulaw", sample_rate=8000
    )
    assert (await c.classify(clip)).audio_class == AudioClass.HOLD_MUSIC


@pytest.mark.parametrize(
    ("text", "cls"),
    [
        ("Your call is important to us. Please stay on the line.", AudioClass.QUEUE_ANNOUNCEMENT),
        (
            "All our executives are busy. Estimated wait time is 5 minutes",
            AudioClass.QUEUE_ANNOUNCEMENT,
        ),
        ("कृपया लाइन पर बने रहें", AudioClass.QUEUE_ANNOUNCEMENT),
        ("For prepaid press 1, for broadband press 3", AudioClass.IVR_PROMPT),
        ("Hindi ke liye 2 dabaye", AudioClass.IVR_PROMPT),
        ("Please leave a message after the beep", AudioClass.VOICEMAIL),
        ("The number you are calling is switched off", AudioClass.VOICEMAIL),
        ("Hello, Looks salon, boliye", None),
    ],
)
async def test_classifier_keywords(text, cls):
    c = HeuristicAudioClassifier()
    got = c.classify_text(text)
    assert (got.audio_class if got else None) == cls
    combined = await c.combine(wav(speech()), text)
    assert combined.audio_class == (cls or AudioClass.HUMAN)


async def test_classifier_on_fake_text_clip():
    c = HeuristicAudioClassifier()
    clip = AudioClip(data=b"press 9 to talk to an executive", mime="text/plain")
    assert (await c.classify(clip)).audio_class == AudioClass.IVR_PROMPT


def test_mulaw_roundtrip_and_resample():
    pcm = tone(440, 0.2, 8000)
    back = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    assert len(back) == len(pcm)
    a, b = array("h"), array("h")
    a.frombytes(pcm)
    b.frombytes(back)
    assert max(abs(x - y) for x, y in zip(a, b, strict=True)) < 1200  # companding error
    up = resample_pcm16(pcm, 8000, 16000)
    assert abs(len(up) - 2 * len(pcm)) <= 2
    data, rate = wav_to_pcm16(pcm16_to_wav(up, 16000))
    assert rate == 16000 and data == up


def test_dtmf():
    pcm = dtmf_pcm16("1w#")
    assert len(pcm) > 0.5 * 8000 * 2
    with pytest.raises(ValueError):
        dtmf_pcm16("x")


def test_segmenter_splits_utterances_and_cuts_music():
    seg = UtteranceSegmenter()
    pcm = speech(1.0) + silence(1.0) + speech(0.6) + silence(1.0)
    out = []
    for i in range(0, len(pcm), 320):
        out += seg.feed_pcm16(pcm[i : i + 320])
    assert len(out) == 2 and not out[0].forced_cut
    seg = UtteranceSegmenter()
    music = tone((262, 330, 392), 13.0)
    out = []
    for i in range(0, len(music), 320):
        out += seg.feed_pcm16(music[i : i + 320])
    assert len(out) == 2 and all(s.forced_cut for s in out)


def test_ogg_container_roundtrip():
    data = build_opus_ogg(
        tags={"TRANSCRIPT": "Kal subah 10 baje doctor ka appointment book karo"}, duration_s=4.0
    )
    assert data[:4] == b"OggS"
    info = parse_opus_ogg(data)
    assert info.tags["TRANSCRIPT"].startswith("Kal subah")
    assert info.duration_s == pytest.approx(4.0, abs=0.05)
    # page CRCs are valid: recomputing with the CRC field zeroed matches the stored value
    import struct

    crc = struct.unpack_from("<I", data, 22)[0]
    assert ogg_crc(data[:22] + b"\0\0\0\0" + data[26 : 27 + data[26] + 19]) == crc


async def test_voice_note_ogg_fixture_transcribes_on_fake_path():
    media = MediaBlob(
        data=build_opus_ogg(tags={"TRANSCRIPT": "Papa ke liye doctor book karo"}, duration_s=6),
        mime="audio/ogg; codecs=opus",
    )
    note = prepare_voice_note(media)
    assert (
        note.clip.mime == "audio/ogg"
        and not note.too_long
        and note.duration_s == pytest.approx(6, abs=0.1)
    )
    t = await transcribe_voice_note(FakeSTT(), media)
    assert t.text == "Papa ke liye doctor book karo" and t.language == Language.HINGLISH


async def test_voice_note_simulator_text_and_length_limit():
    t = await transcribe_voice_note(FakeSTT(), MediaBlob(data="नमस्ते".encode(), mime="audio/ogg"))
    assert t.text == "नमस्ते" and t.language == Language.HI
    long = prepare_voice_note(
        MediaBlob(data=build_opus_ogg(duration_s=MAX_VOICE_NOTE_S + 5), mime="audio/ogg")
    )
    assert long.too_long


async def test_voice_note_real_stt_gets_wav_when_ffmpeg_present(monkeypatch):
    import friday.voice.voicenote as vn

    async def fake_ffmpeg(data, sample_rate=16000):
        return pcm16_to_wav(silence(0.1, 16000), 16000)

    monkeypatch.setattr(vn, "ogg_to_wav", fake_ffmpeg)
    seen = []

    class RealishSTT(FakeSTT):
        name = "sarvam"

        async def transcribe(self, audio, *, language_hint=None):
            seen.append(audio.mime)
            return await super().transcribe(audio, language_hint=language_hint)

    await transcribe_voice_note(RealishSTT(), MediaBlob(data=build_opus_ogg(), mime="audio/ogg"))
    assert seen == ["audio/wav"]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Umm, main check karti hoon.", "main check karti hoon."),
        ("Uh... the slot is 6pm, hmm", "the slot is 6pm"),
        ("*sighs* Okay (pause) done", "Okay done"),
        ("Ji, theek hai.", "Ji, theek hai."),
        ("Ummm I er think", "I er think"),
    ],
)
def test_strip_fillers(raw, clean):
    assert strip_fillers(raw) == clean


def test_redact_and_mask():
    assert redact_secrets("Mera OTP 4 8 2 9 1 3 hai") == "Mera OTP [redacted] hai"
    assert redact_secrets("Your ticket is SR123456") == "Your ticket is SR123456"
    assert redact_secrets("The PIN is 4821, thanks") == "The PIN is [redacted], thanks"
    assert mask_digits("9812345678#") == "••••••5678#"
    assert mask_digits("2") == "2"


def test_detect_language_defaults():
    assert detect_language("", default=Language.HI) == Language.HI
    assert detect_language("12345") == Language.EN


def test_latency_percentiles():
    rec = LatencyRecorder()
    for ms in (100, 200, 300, 400, 2000):
        rec.stt(10)
        rec.policy(ms)
        rec.tts(50)
    s = rec.summary()
    assert s["turns"] == 5 and s["p50_ms"] == 360 and s["p95_ms"] == 2060
    assert percentile([], 95) == 0.0
