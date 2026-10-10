"""Sarvam streaming TTS: parser, SarvamTTS.synthesize_stream, and the Vobiz leg speak path.

No network: httpx.MockTransport with streaming bodies."""

from __future__ import annotations

import asyncio
import base64
import json
import struct

import httpx
import pytest

from friday.core.config import Settings
from friday.core.interfaces import ProviderError
from friday.core.models import Language, OutboundCallRequest
from friday.voice.audio import pcm16_to_wav, tone, wav_to_pcm16
from friday.voice.langs import VoiceCatalog
from friday.voice.telephony.sarvam import SarvamTelephony
from friday.voice.tts.cache import CachedTTS
from friday.voice.tts.sarvam import SarvamTTS, TTSStreamError, WavStreamParser

from .test_twilio import StubSTT

PCM = tone(300, 1.0, 8000)  # 16000 bytes of 8 kHz PCM16
LINE = "Haan ji, bataiye kya chahiye aapko. Main abhi dekh leti hoon ek second."


def wav_header(rate=8000, size=0xFFFFFFFF, riff=0xFFFFFFFF) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (
        b"RIFF" + struct.pack("<I", riff) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
        + b"data" + struct.pack("<I", size)
    )  # fmt: skip


def slices(data: bytes, n: int) -> list[bytes]:
    return [data[i : i + n] for i in range(0, len(data), n)]


def make_tts(handler, *, streaming=True, **kw) -> SarvamTTS:
    cat = VoiceCatalog("sarvam", Settings(_env_file=None), {}, "ritu")
    return SarvamTTS(
        "k", cat, transport=httpx.MockTransport(handler), dict_id="dict-1",
        streaming=streaming, **kw,
    )  # fmt: skip


def rest_reply(req: httpx.Request) -> httpx.Response:
    wav = base64.b64encode(pcm16_to_wav(PCM, 8000)).decode()
    return httpx.Response(200, json={"audios": [wav]})


# ------------------------------------------------------------------ WAV parser
def test_parser_known_length_header_split_across_chunks():
    data = wav_header(size=len(PCM), riff=36 + len(PCM)) + PCM
    p = WavStreamParser()
    out = b"".join(p.feed(c) for c in slices(data, 7))  # header split mid-field
    assert out == PCM and p.rate == 8000


def test_parser_unknown_length_zero_and_ffff():
    for size in (0, 0xFFFFFFFF):
        p = WavStreamParser()
        out = b"".join(p.feed(c) for c in slices(wav_header(size=size, riff=0) + PCM, 1000))
        assert out == PCM


def test_parser_never_splits_a_sample_and_skips_extra_chunks():
    hdr = wav_header()
    extra = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\x00"  # odd-size chunk is padded
    data = hdr[:36] + extra + hdr[36:] + PCM
    p = WavStreamParser()
    out = b"".join(p.feed(c) for c in slices(data, 3))
    assert out == PCM


def test_parser_rejects_non_wav_and_stereo():
    with pytest.raises(ValueError):
        WavStreamParser().feed(b"ID3\x00" * 8)
    fmt = struct.pack("<HHIIHH", 1, 2, 8000, 32000, 4, 16)
    stereo = b"RIFF" + b"\0" * 4 + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
    with pytest.raises(ValueError):
        WavStreamParser().feed(stereo + b"data" + b"\0" * 4 + b"\0\0\0\0")


# ------------------------------------------------------------------ SarvamTTS.synthesize_stream
async def test_stream_yields_chunks_before_the_stream_ends():
    gate = asyncio.Event()

    async def body():
        yield wav_header() + PCM[:4000]
        await gate.wait()  # the vendor is still making the rest
        yield PCM[4000:]

    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, content=body())

    tts = make_tts(handler)
    agen = tts.synthesize_stream(LINE, Language.HINGLISH)
    first = await asyncio.wait_for(agen.__anext__(), 2)  # arrives while the stream is open
    assert first == PCM[:4000] and not gate.is_set()
    gate.set()
    rest = b"".join([c async for c in agen])
    assert first + rest == PCM
    assert seen[0].url.path == "/text-to-speech/stream"
    await tts.aclose()


async def test_stream_payload_matches_rest_payload_plus_wav_codec():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/stream"):
            return httpx.Response(200, content=wav_header() + PCM)
        return rest_reply(req)

    tts = make_tts(handler)
    voice = tts.voice_for(Language.HINGLISH)
    pcm = b"".join([c async for c in tts.synthesize_stream("Umm " + LINE, Language.HINGLISH)])
    await tts.synthesize("Umm " + LINE, Language.HINGLISH)
    stream_body, rest_body = (json.loads(r.content) for r in seen)
    assert stream_body.pop("output_audio_codec") == "wav"
    assert stream_body == rest_body == tts.payload(LINE, Language.HINGLISH, voice)
    assert stream_body["dict_id"] == "dict-1" and stream_body["speaker"] == "ritu"
    assert stream_body["pace"] == voice.speaking_rate and stream_body["speech_sample_rate"] == 8000
    assert seen[0].headers["api-subscription-key"] == "k" and pcm == PCM


async def test_stream_resamples_other_rates():
    pcm16k = tone(300, 0.5, 16000)
    tts = make_tts(lambda r: httpx.Response(200, content=wav_header(16000) + pcm16k))
    out = b"".join([c async for c in tts.synthesize_stream("Namaste ji", Language.HINGLISH)])
    assert abs(len(out) - len(pcm16k) // 2) <= 4


async def test_stream_http_error_raises_with_full_resume_text():
    tts = make_tts(lambda r: httpx.Response(402, json={"error": "no credits"}))
    with pytest.raises(TTSStreamError) as ei:
        async for _ in tts.synthesize_stream(LINE, Language.HINGLISH):
            pass
    assert ei.value.resume_text == LINE and not ei.value.audio_started
    assert isinstance(ei.value, ProviderError)


async def test_stream_failure_mid_chunk_resumes_after_the_failed_chunk():
    first, second = "A" * 300 + ".", "B" * 300 + "."

    class Cut(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield wav_header() + PCM[:2000]
            raise httpx.ReadError("boom")

    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, stream=Cut())

    tts = make_tts(handler)
    got = []
    with pytest.raises(TTSStreamError) as ei:
        async for c in tts.synthesize_stream(f"{first} {second}", Language.HINGLISH):
            got.append(c)
    assert got == [PCM[:2000]] and ei.value.audio_started
    assert ei.value.resume_text == second  # chunk 1 was started: only the rest is left


# ------------------------------------------------------------------ the Vobiz leg
async def make_leg(handler, *, streaming=True):
    inner = make_tts(handler, streaming=streaming)
    tts = CachedTTS(inner)
    tel = SarvamTelephony(
        auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
        public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=tts,
        transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"request_uuid": "u1"})),
    )  # fmt: skip
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    sent: list[dict] = []

    async def send(m: str) -> None:
        sent.append(json.loads(m))

    leg._send = send
    leg.stream_sid = "s1"
    leg.set_media_format({"encoding": "audio/x-mulaw", "sampleRate": 8000})

    async def release():
        while True:
            await asyncio.sleep(0.01)
            for ev in leg._marks.values():
                ev.set()

    leg._releaser = asyncio.ensure_future(release())
    return leg, sent, tts


def plays(sent):
    return [m for m in sent if m["event"] == "playAudio"]


async def test_leg_sends_first_chunk_before_the_stream_finishes_and_fills_cache(caplog):
    gate = asyncio.Event()
    n_stream = n_rest = 0

    async def body():
        yield wav_header() + PCM[:3200]
        await gate.wait()
        yield PCM[3200:]

    def handler(req):
        nonlocal n_stream, n_rest
        if req.url.path.endswith("/stream"):
            n_stream += 1
            return httpx.Response(200, content=body())
        n_rest += 1
        return rest_reply(req)

    leg, sent, tts = await make_leg(handler)
    caplog.set_level("INFO")
    task = asyncio.ensure_future(leg.speak(LINE, Language.HINGLISH))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if plays(sent):
            break
    assert plays(sent) and not task.done()  # audio is on the line, the vendor has not finished
    assert not any(m["event"] == "checkpoint" for m in sent)
    gate.set()
    await asyncio.wait_for(task, 3)
    leg._releaser.cancel()
    assert sent[-1]["event"] == "checkpoint" and not leg._playing
    assert n_stream >= 1 and n_rest == 0  # no double synthesis
    assert leg.last_tts_ms is not None and leg.tts_billed_chars > 0
    assert any("tts stream first-audio" in r.message and "cached=False" in r.message
               for r in caplog.records)  # fmt: skip
    # the streamed sentences are now cached under the normal key (8 kHz): instant next time
    from friday.voice.telephony.sarvam import split_sentences

    for p in split_sentences(LINE):
        clip = await tts.lookup(p, Language.HINGLISH)
        assert clip is not None and wav_to_pcm16(clip.data)[1] == 8000


async def test_cached_line_is_replayed_without_calling_the_vendor():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/stream"):
            return httpx.Response(200, content=wav_header() + PCM)
        return rest_reply(req)

    leg, sent, tts = await make_leg(handler)
    await asyncio.wait_for(leg.speak("Namaste ji.", Language.HINGLISH), 3)
    n = len(calls)
    assert n == 1 and calls[0].endswith("/stream")
    await asyncio.wait_for(leg.speak("Namaste ji.", Language.HINGLISH), 3)  # cache hit
    leg._releaser.cancel()
    assert len(calls) == n


async def test_barge_in_stops_streaming_mid_line_and_leaves_cache_empty():
    closed = asyncio.Event()

    async def body():
        try:
            yield wav_header() + PCM[:3200]
            await asyncio.sleep(30)  # vendor still going
            yield PCM[3200:]
        finally:
            closed.set()  # the HTTP request was cancelled / closed

    leg, sent, tts = await make_leg(lambda req: httpx.Response(200, content=body()))
    task = asyncio.ensure_future(leg.speak("Haan ji bataiye kya chahiye.", Language.HINGLISH))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if plays(sent):
            break
    n_plays = len(plays(sent))
    leg._barged = True  # the caller spoke over her
    await asyncio.wait_for(task, 2)
    leg._releaser.cancel()
    await asyncio.wait_for(closed.wait(), 2)
    assert len(plays(sent)) == n_plays and not leg._playing
    assert await tts.lookup("Haan ji bataiye kya chahiye.", Language.HINGLISH) is None


async def test_fallback_to_rest_when_stream_fails_before_audio(caplog):
    paths = []

    def handler(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/stream"):
            return httpx.Response(500, json={"error": "x"})
        return rest_reply(req)

    leg, sent, tts = await make_leg(handler)
    caplog.set_level("WARNING")
    await asyncio.wait_for(leg.speak("Haan ji bataiye kya chahiye.", Language.HINGLISH), 3)
    leg._releaser.cancel()
    assert paths == ["/text-to-speech/stream", "/text-to-speech"]
    assert plays(sent) and sent[-1]["event"] == "checkpoint"
    assert any("falling back to REST" in r.message for r in caplog.records)
    assert leg.tts_billed_chars == len("Haan ji bataiye kya chahiye.")  # REST only


async def test_fallback_mid_stream_speaks_the_remaining_text_by_rest():
    text = "A" * 450 + "B" * 350  # one sentence, two vendor chunks (450-char limit)
    second = "B" * 350
    rest_texts = []

    class Cut(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield wav_header() + PCM[:2000]
            raise httpx.ReadError("boom")

    def handler(req):
        if req.url.path.endswith("/stream"):
            return httpx.Response(200, stream=Cut())
        rest_texts.append(json.loads(req.content)["text"])
        return rest_reply(req)

    leg, sent, tts = await make_leg(handler)
    await asyncio.wait_for(leg.speak(text, Language.HINGLISH), 3)
    leg._releaser.cancel()
    assert rest_texts == [second]
    assert sent[-1]["event"] == "checkpoint"
    assert await tts.lookup(text, Language.HINGLISH) is None  # partial: not cached


async def test_streaming_switched_off_uses_rest_only():
    paths = []

    def handler(req):
        paths.append(req.url.path)
        return rest_reply(req)

    leg, sent, tts = await make_leg(handler, streaming=False)
    await asyncio.wait_for(leg.speak(LINE, Language.HINGLISH), 3)
    leg._releaser.cancel()
    assert paths and set(paths) == {"/text-to-speech"}
    assert sent[-1]["event"] == "checkpoint"


def test_setting_defaults_on_and_can_be_switched_off(monkeypatch):
    assert Settings(_env_file=None).sarvam_tts_streaming is True
    monkeypatch.setenv("FRIDAY_SARVAM_TTS_STREAMING", "false")
    assert Settings(_env_file=None).sarvam_tts_streaming is False


async def test_temperature_in_rest_and_stream_payload_and_cache_key():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        if req.url.path.endswith("/stream"):
            return httpx.Response(200, content=wav_header() + PCM)
        return rest_reply(req)

    tts = make_tts(handler, temperature=0.9)
    await tts.synthesize("Namaste ji", Language.HINGLISH)
    _ = [c async for c in tts.synthesize_stream("Namaste ji", Language.HINGLISH)]
    assert [b["temperature"] for b in seen] == [0.9, 0.9]
    voice = tts.voice_for(Language.HINGLISH)
    k09 = CachedTTS(tts)._key("hi", Language.HINGLISH, voice)
    tts.temperature = 0.6
    assert CachedTTS(tts)._key("hi", Language.HINGLISH, voice) != k09
    tts.temperature = None
    assert CachedTTS(tts)._key("hi", Language.HINGLISH, voice) != k09


def test_temperature_setting_default_and_range(monkeypatch):
    from pydantic import ValidationError

    assert Settings(_env_file=None).sarvam_tts_temperature == 0.9
    monkeypatch.setenv("FRIDAY_SARVAM_TTS_TEMPERATURE", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
