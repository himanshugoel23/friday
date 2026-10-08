"""V-3: STT/TTS fakes + Sarvam / Deepgram / ElevenLabs over mocked HTTP."""

from __future__ import annotations

import base64
import json
import os

import httpx
import pytest

from friday.core.config import Settings
from friday.core.interfaces import ProviderError, STTProvider, TTSProvider
from friday.core.models import AudioClip, Language
from friday.voice.audio import pcm16_to_wav, tone, wav_to_pcm16
from friday.voice.langs import VoiceCatalog
from friday.voice.stt.deepgram import DeepgramSTT
from friday.voice.stt.fake import FakeSTT
from friday.voice.stt.sarvam import SarvamSTT
from friday.voice.tts.elevenlabs import DEFAULT_FEMALE_VOICE_ID, ElevenLabsTTS
from friday.voice.tts.fake import FakeTTS, build_fake_tts
from friday.voice.tts.sarvam import (
    DEFAULT_FEMALE_SPEAKER,
    SarvamTTS,
    build_sarvam_tts,
    chunk_text,
    is_female_speaker,
)

WAV = AudioClip(data=pcm16_to_wav(tone(300, 0.2, 16000), 16000), mime="audio/wav")


def mock(handler):
    calls: list[httpx.Request] = []

    def _h(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return handler(req)

    return httpx.MockTransport(_h), calls


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Hello, I need a haircut appointment", Language.EN),
        ("Haan ji, kal shaam 6 baje ka slot hai kya?", Language.HINGLISH),
        ("नमस्ते, कल का अपॉइंटमेंट चाहिए", Language.HI),
        ("नमस्कार, उद्या भेटायला मिळेल का? आहे", Language.MR),
        ("ಹೌದು, ಹೇಳಿ", Language.KN),
        ("ஆமா, சொல்லுங்க", Language.TA),
    ],
)
async def test_fake_stt_detects_language(text, lang):
    stt = FakeSTT()
    assert isinstance(stt, STTProvider)
    t = await stt.transcribe(AudioClip(data=text.encode(), mime="audio/ogg"))
    assert t.text == text and t.language == lang


async def test_fake_stt_empty_and_identical_output():
    stt = FakeSTT()
    empty = await stt.transcribe(AudioClip(data=b"", mime="audio/ogg"), language_hint=Language.HI)
    assert empty.text == "" and empty.language == Language.HI and empty.confidence == 0
    a = await stt.transcribe(AudioClip(data=b"kal milte hain"))
    b = await stt.transcribe(AudioClip(data=b"kal milte hain"))
    assert a == b


async def test_fake_tts_strips_fillers_and_is_female(settings):
    from friday.core.container import Container

    tts = build_fake_tts(Container(settings))
    assert isinstance(tts, TTSProvider)
    clip = await tts.synthesize("Umm, main... uh, check karti hoon [sighs]", Language.HINGLISH)
    assert clip.data.decode() == "main. check karti hoon"
    v = tts.voice_for(Language.HI)
    assert v.gender == "female" and v.style == "calm" and v.language == Language.HI


def test_voice_overrides_from_settings():
    s = Settings(_env_file=None, tts_voices={"hi": "vidya", "*": "anushka"})
    cat = VoiceCatalog("sarvam", s, {}, "ritu")
    assert cat.voice_id(Language.HI) == "vidya"
    assert cat.voice_id(Language.HINGLISH) == "vidya"  # Hinglish falls back to the Hindi voice
    assert cat.voice_id(Language.TA) == "anushka"


async def test_sarvam_stt_request_and_detected_language():
    transport, calls = mock(
        lambda r: httpx.Response(
            200,
            json={
                "transcript": "Haan ji, kal ka slot hai",
                "language_code": "hi-IN",
                "language_probability": 0.93,
            },
        )
    )
    stt = SarvamSTT("sk-test", transport=transport)
    t = await stt.transcribe(WAV)
    req = calls[0]
    assert req.url.path == "/speech-to-text" and req.headers["api-subscription-key"] == "sk-test"
    body = req.content.decode(errors="replace")
    assert 'name="language_code"' in body and "unknown" in body and 'filename="audio.wav"' in body
    assert t.language == Language.HINGLISH  # Roman-script Hindi
    assert t.confidence == 0.93
    # saaras:v4 is the documented default; saarika:v2.5 is gone. mode is saaras:v3-only.
    assert 'name="model"' in body and "saaras:v4" in body and 'name="mode"' not in body
    t2 = await SarvamSTT(
        "k",
        transport=mock(
            lambda r: httpx.Response(200, json={"transcript": "ಹೌದು", "language_code": "kn-IN"})
        )[0],
    ).transcribe(WAV)
    assert t2.language == Language.KN


async def test_sarvam_stt_keyterms_only_on_v4():
    transport, calls = mock(
        lambda r: httpx.Response(200, json={"transcript": "x", "language_code": "en-IN"})
    )
    await SarvamSTT("k", keyterms=["Airtel", "New Delhi"], transport=transport).transcribe(WAV)
    body = calls[0].content.decode(errors="replace")
    assert 'name="keyterms"' in body and '["Airtel", "New Delhi"]' in body
    transport, calls = mock(
        lambda r: httpx.Response(200, json={"transcript": "x", "language_code": "en-IN"})
    )
    await SarvamSTT("k", model="saaras:v3", keyterms=["Airtel"], transport=transport).transcribe(
        WAV
    )
    assert 'name="keyterms"' not in calls[0].content.decode(errors="replace")


async def test_sarvam_tts_payload_female_and_chunking():
    wav = base64.b64encode(pcm16_to_wav(tone(300, 0.1, 8000), 8000)).decode()
    transport, calls = mock(lambda r: httpx.Response(200, json={"audios": [wav]}))
    s = Settings(_env_file=None, sarvam_tts_speaker="rohan")  # male v3 -> must fall back
    tts = SarvamTTS("k", VoiceCatalog("sarvam", s, {}, "rohan"), transport=transport)
    voice = tts.voice_for(Language.TA)
    assert voice.voice_id == DEFAULT_FEMALE_SPEAKER and voice.gender == "female"
    long = "Namaste. " * 80
    clip = await tts.synthesize("Umm " + long, Language.HI)
    payloads = [json.loads(c.content) for c in calls]
    assert len(payloads) > 1 and all(len(p["text"]) <= 450 for p in payloads)
    p0 = payloads[0]
    assert p0["target_language_code"] == "hi-IN" and p0["speaker"] == DEFAULT_FEMALE_SPEAKER
    # bulbul:v2 is deprecated (HTTP 400); v3 has no pitch / loudness / enable_preprocessing.
    assert p0["model"] == "bulbul:v3" and p0["speech_sample_rate"] == 8000
    assert not ({"pitch", "loudness", "enable_preprocessing"} & p0.keys())
    assert 0.5 <= p0["pace"] <= 2.0
    assert not p0["text"].lower().startswith("umm")
    pcm, rate = wav_to_pcm16(clip.data)
    assert rate == 8000 and len(pcm) > 0
    assert tts.payload("x", Language.OR, voice)["target_language_code"] == "od-IN"


def test_legacy_v2_default_speaker_falls_back_to_v3_female():
    # The core Settings default is still the bulbul:v2 name "anushka".
    from friday.core.container import Container

    s = Settings(_env_file=None, sarvam_api_key="k")
    assert s.sarvam_tts_speaker == "anushka"
    tts = build_sarvam_tts(Container(s))
    assert tts.model == "bulbul:v3"
    assert tts.voice_for(Language.HI).voice_id == DEFAULT_FEMALE_SPEAKER
    assert not is_female_speaker("anushka") and not is_female_speaker("rohan")
    assert is_female_speaker("priya") and is_female_speaker("Ritu".lower())


def test_model_and_speaker_configurable(monkeypatch):
    from friday.core.container import Container

    monkeypatch.setenv("FRIDAY_SARVAM_TTS_MODEL", "bulbul:v4-flash")
    s = Settings(_env_file=None, sarvam_api_key="k", sarvam_tts_speaker="priya")
    assert build_sarvam_tts(Container(s)).model == "bulbul:v4-flash"
    monkeypatch.delenv("FRIDAY_SARVAM_TTS_MODEL")
    tts = build_sarvam_tts(Container(s))
    assert tts.voice_for(Language.EN).voice_id == "priya"


def test_sarvam_tts_tolerates_v4_flash_personas():
    s = Settings(_env_file=None, tts_voices={"ta": "gokul_ta_narration"})  # male persona
    tts = SarvamTTS("k", VoiceCatalog("sarvam", s, {}, "ritu"), model="bulbul:v4-flash")
    en = tts.voice_for(Language.EN)  # v3 short name -> not a valid persona -> default persona
    assert en.voice_id == "simran_en_customer"
    assert tts.payload("hi", Language.EN, en)["model"] == "bulbul:v4-flash"
    assert tts.voice_for(Language.HI).voice_id == "ritu_hi_customer"  # language-matched persona
    assert tts.voice_for(Language.HINGLISH).voice_id == "simran_enhi_customer"
    # no female persona listed for Tamil: that request uses bulbul:v3 with a v3 female speaker
    ta = tts.voice_for(Language.TA)
    assert ta.voice_id == "ritu" and tts.payload("x", Language.TA, ta)["model"] == "bulbul:v3"
    # a configured female persona is kept as-is
    s2 = Settings(_env_file=None, tts_voices={"en": "shalini_en_customer"})
    t2 = SarvamTTS("k", VoiceCatalog("sarvam", s2, {}, "ritu"), model="bulbul:v4-flash")
    assert t2.voice_for(Language.EN).voice_id == "shalini_en_customer"


def test_sarvam_tts_rejects_unsupported_sample_rate():
    with pytest.raises(ValueError):
        cat = VoiceCatalog("sarvam", Settings(_env_file=None), {}, "ritu")
        SarvamTTS("k", cat, sample_rate=11025)


def test_chunk_text_respects_sentences():
    parts = chunk_text("One. Two. Three.", limit=9)
    assert parts == ["One. Two.", "Three."]


async def test_deepgram_params_and_parse():
    transport, calls = mock(
        lambda r: httpx.Response(
            200,
            json={
                "results": {
                    "channels": [
                        {
                            "detected_language": "hi",
                            "alternatives": [
                                {"transcript": "kal shaam ka slot hai kya", "confidence": 0.9}
                            ],
                        }
                    ]
                }
            },
        )
    )
    stt = DeepgramSTT("dg", transport=transport)
    t = await stt.transcribe(WAV, language_hint=Language.HINGLISH)
    q = dict(calls[0].url.params)
    assert q["language"] == "multi" and q["model"] == "nova-3"
    assert calls[0].headers["Authorization"] == "Token dg"
    assert t.language == Language.HINGLISH and t.confidence == 0.9
    await stt.transcribe(WAV, language_hint=Language.TA)
    assert dict(calls[1].url.params)["detect_language"] == "true"


async def test_vendor_errors_normalised():
    transport, _ = mock(lambda r: httpx.Response(401, text="bad key"))
    with pytest.raises(ProviderError) as e:
        await SarvamSTT("x", transport=transport).transcribe(WAV)
    assert not e.value.retryable
    transport, calls = mock(lambda r: httpx.Response(503, text="busy"))
    stt = DeepgramSTT("x", transport=transport)
    stt._http.retries = 0
    with pytest.raises(ProviderError) as e:
        await stt.transcribe(WAV)
    assert e.value.retryable


async def test_elevenlabs_request():
    transport, calls = mock(lambda r: httpx.Response(200, content=tone(300, 0.1, 16000)))
    s = Settings(_env_file=None)
    tts = ElevenLabsTTS(
        "xi", VoiceCatalog("elevenlabs", s, {}, DEFAULT_FEMALE_VOICE_ID), transport=transport
    )
    clip = await tts.synthesize("Hmm, your appointment is confirmed.", Language.HINGLISH)
    req = calls[0]
    assert req.url.path == f"/v1/text-to-speech/{DEFAULT_FEMALE_VOICE_ID}"
    assert dict(req.url.params)["output_format"] == "pcm_16000"
    body = json.loads(req.content)
    assert body["text"] == "your appointment is confirmed." and body["language_code"] == "hi"
    assert body["voice_settings"]["style"] == 0.0
    assert clip.mime == "audio/wav"
    assert Language.KN not in tts.supported_languages


async def test_fake_tts_records_calls():
    tts = FakeTTS(VoiceCatalog("fake", Settings(_env_file=None), {}, "f"))
    await tts.synthesize("Ji, theek hai", Language.HINGLISH)
    assert tts.calls[0][0] == "Ji, theek hai"  # meaningful acknowledgements are kept


@pytest.mark.live
async def test_live_sarvam_roundtrip():  # pragma: no cover
    if not os.environ.get("SARVAM_API_KEY"):
        pytest.skip("SARVAM_API_KEY not set")
    s = Settings()
    tts = SarvamTTS(
        os.environ["SARVAM_API_KEY"], VoiceCatalog("sarvam", s, {}, "ritu"), sample_rate=16000
    )
    clip = await tts.synthesize("Namaste, main Friday hoon.", Language.HINGLISH)
    t = await SarvamSTT(os.environ["SARVAM_API_KEY"]).transcribe(clip)
    assert t.text and t.language in (Language.HI, Language.HINGLISH)


@pytest.mark.live
async def test_live_deepgram_and_elevenlabs():  # pragma: no cover
    if not (os.environ.get("DEEPGRAM_API_KEY") and os.environ.get("ELEVENLABS_API_KEY")):
        pytest.skip("DEEPGRAM_API_KEY / ELEVENLABS_API_KEY not set")
    s = Settings()
    tts = ElevenLabsTTS(
        os.environ["ELEVENLABS_API_KEY"], VoiceCatalog("elevenlabs", s, {}, DEFAULT_FEMALE_VOICE_ID)
    )
    clip = await tts.synthesize("Your appointment is at six pm.", Language.EN)
    t = await DeepgramSTT(os.environ["DEEPGRAM_API_KEY"]).transcribe(
        clip, language_hint=Language.EN
    )
    assert "six" in t.text.lower() or "6" in t.text
