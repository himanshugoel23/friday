"""Sarvam realtime streaming speech-to-text: the protocol client and the call-leg behaviour."""

from __future__ import annotations

import asyncio
import base64
import json

import websockets

from friday.voice.stt.elevenlabs_stream import ElevenLabsStreamSTT
from friday.voice.stt.sarvam_stream import SarvamStreamSTT, StreamSTTConfig
from friday.voice.stt.stream import make_stream_stt

from .test_vobiz_turns import _frames, _leg, _silence_frames


# --------------------------------------------------------------------------- protocol client
async def _server(handler):
    srv = await websockets.serve(handler, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    return srv, f"ws://127.0.0.1:{port}/speech-to-text-realtime/ws"


async def test_client_speaks_the_protocol_and_reports_partials_and_finals():
    got: dict = {}

    async def handler(ws):
        got["path"] = ws.request.path
        got["key"] = ws.request.headers.get("Api-Subscription-Key")
        await ws.send(json.dumps({"event": "session.begin", "request_id": "r1"}))
        msg = json.loads(await ws.recv())
        got["audio"] = base64.b64decode(msg["audio"])
        await ws.send(json.dumps({"event": "transcript.partial", "text": "haan", "utterance_idx": 0,
                                  "language": "hi-IN"}))
        await ws.send(json.dumps({"event": "transcript.final", "text": "haan ji.",
                                  "utterance_idx": 0, "language": "hi-IN",
                                  "language_confidence": "0.9"}))
        await asyncio.sleep(0.2)

    srv, url = await _server(handler)
    seen: list = []
    try:
        cfg = StreamSTTConfig(api_key="K", url=url, silence_ms=350)
        c = SarvamStreamSTT(
            cfg,
            on_partial=lambda t, lang, i: seen.append(("p", t, lang, i)),
            on_final=lambda t, lang, conf, i: seen.append(("f", t, lang, conf, i)),
        )
        assert await c.start() and c.healthy and c.request_id == "r1"
        c.feed(b"\xff" * 160)
        await asyncio.sleep(0.15)
        await c.aclose()
    finally:
        srv.close()
    assert got["key"] == "K" and got["audio"] == b"\xff" * 160
    assert "language_code=hi-IN" in got["path"] and "encoding=mulaw" in got["path"]
    assert "sample_rate=8000" in got["path"] and "silence_duration_ms=350" in got["path"]
    assert seen == [("p", "haan", "hi-IN", 0), ("f", "haan ji.", "hi-IN", 0.9, 0)]


async def test_client_never_raises_and_turns_unhealthy_on_failure():
    cfg = StreamSTTConfig(api_key="K", url="ws://127.0.0.1:9/none", connect_timeout_s=0.5)
    c = SarvamStreamSTT(cfg)
    assert await c.start() is False and not c.healthy
    c.feed(b"x")  # harmless


async def test_a_dropped_connection_marks_the_stream_unhealthy():
    async def handler(ws):
        await ws.send(json.dumps({"event": "session.begin", "request_id": "r"}))
        await ws.close()

    srv, url = await _server(handler)
    try:
        c = SarvamStreamSTT(StreamSTTConfig(api_key="K", url=url))
        assert await c.start()
        await asyncio.sleep(0.3)
        assert not c.healthy
        await c.aclose()
    finally:
        srv.close()


# --------------------------------------------------------------------------- the call leg
class _FakeStream:
    def __init__(self, stable_ms=60, max_words=6):
        self.cfg = StreamSTTConfig(api_key="K", stable_ms=stable_ms, max_words=max_words)
        self.healthy = True
        self.fed = 0

    def feed(self, b):
        self.fed += len(b)

    async def aclose(self):
        self.healthy = False


async def _stream_leg(**kw):
    leg, _ = await _leg()
    leg._sstt = _FakeStream(**kw)
    leg._sstt_ready_t = 0.0
    return leg


def _speak_then_pause(leg, pause_s=0.3):
    for f in _frames(1.0, 0.9) + _silence_frames(pause_s):
        leg.on_media(f)


async def test_audio_is_forwarded_to_the_stream():
    leg = await _stream_leg()
    for f in _frames(0.2, 0.9):
        leg.on_media(f)
    assert leg._sstt.fed > 0


async def test_short_stable_partial_is_acted_on_before_the_server_finishes():
    leg = await _stream_leg()
    _speak_then_pause(leg)
    leg._stt_partial("haan ji bataiye", "hi-IN", 0)
    await asyncio.sleep(0.2)
    t = leg._utterances.get_nowait()
    assert t.text == "haan ji bataiye" and t.language is not None
    leg._stt_final("haan ji, bataiye.", "hi-IN", 0.9, 0)  # the late final is the same utterance
    assert leg._utterances.empty()


async def test_long_partial_waits_for_the_final():
    leg = await _stream_leg()
    _speak_then_pause(leg)
    leg._stt_partial("haan ji main ye kehna chahta tha ki aap kal subah aa jaiye", "hi-IN", 0)
    await asyncio.sleep(0.2)
    assert leg._utterances.empty()
    leg._stt_final("haan ji main ye kehna chahta tha ki aap kal subah aa jaiye.", "hi-IN", None, 0)
    assert leg._utterances.get_nowait().text.endswith("aa jaiye.")


async def test_partial_is_not_committed_while_the_caller_is_still_talking():
    leg = await _stream_leg()
    for f in _frames(1.0, 0.9):
        leg.on_media(f)  # no pause yet
    leg._stt_partial("haan ji", "hi-IN", 0)
    await asyncio.sleep(0.2)
    assert leg._utterances.empty()


async def test_her_own_voice_coming_back_is_not_taken_as_the_caller():
    leg = await _stream_leg()
    leg._playing = True
    leg._stt_final("main friday baat kar rahi hoon.", "hi-IN", None, 0)
    assert leg._utterances.empty()


async def test_segments_are_left_to_the_stream_only_while_it_is_healthy():
    leg = await _stream_leg()
    for f in _frames(1.0, 0.9) + _silence_frames(1.0):
        leg.on_media(f)
    seg = await asyncio.wait_for(leg._segments.get(), 1)
    leg._sstt_ready_t = -5.0  # the stream was ready long before this speech began
    assert await leg._transcribe(seg) is None  # the words come from the stream
    leg._sstt.healthy = False  # stream died: the normal per-utterance path takes over
    assert not leg._stream_handles(seg)


async def test_speech_that_began_before_the_stream_was_ready_uses_the_normal_path():
    import time

    leg = await _stream_leg()
    leg._sstt_ready_t = time.perf_counter()  # just became ready
    for f in _frames(0.5, 0.9) + _silence_frames(1.0):
        leg.on_media(f)
    seg = await asyncio.wait_for(leg._segments.get(), 1)
    assert not leg._stream_handles(seg)


async def test_elevenlabs_client_speaks_its_protocol():
    got: dict = {}

    async def handler(ws):
        got["path"] = ws.request.path
        got["key"] = ws.request.headers.get("xi-api-key")
        hello = {"message_type": "session_started", "session_id": "s1", "config": {}}
        await ws.send(json.dumps(hello))
        msg = json.loads(await ws.recv())
        got["msg"] = msg
        await ws.send(json.dumps({"message_type": "partial_transcript", "text": "haan ji"}))
        await ws.send(json.dumps({"message_type": "committed_transcript", "text": "haan ji."}))
        await ws.send(json.dumps({"message_type": "partial_transcript", "text": "theek hai"}))
        await asyncio.sleep(0.2)

    srv = await websockets.serve(handler, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    seen: list = []
    try:
        cfg = StreamSTTConfig(api_key="XK", provider="elevenlabs", url=f"ws://127.0.0.1:{port}",
                              silence_ms=300)
        c = make_stream_stt(
            cfg,
            on_partial=lambda t, lang, i: seen.append(("p", t, i)),
            on_final=lambda t, lang, conf, i: seen.append(("f", t, i)),
        )
        assert isinstance(c, ElevenLabsStreamSTT)
        assert await c.start() and c.healthy and c.request_id == "s1"
        c.feed(b"\xff" * 160)
        await asyncio.sleep(0.15)
        await c.aclose()
    finally:
        srv.close()
    assert got["key"] == "XK" and got["msg"]["message_type"] == "input_audio_chunk"
    assert base64.b64decode(got["msg"]["audio_base_64"]) == b"\xff" * 160
    assert got["msg"]["sample_rate"] == 8000
    for part in ("model_id=scribe_v2_realtime", "audio_format=ulaw_8000", "language_code=hi",
                 "commit_strategy=vad", "vad_silence_threshold_secs=0.30"):
        assert part in got["path"]
    # utterance numbering: the commit closes utterance 0, the next partial belongs to 1
    assert seen == [("p", "haan ji", 0), ("f", "haan ji.", 0), ("p", "theek hai", 1)]


def test_factory_defaults_to_sarvam_and_settings_pick_the_provider():
    from friday.core.config import Settings
    from friday.voice.telephony.sarvam import _stream_stt_config

    assert isinstance(make_stream_stt(StreamSTTConfig(api_key="K")), SarvamStreamSTT)
    s = Settings(voice_stream_stt=True, elevenlabs_api_key="e", sarvam_api_key="s")
    assert _stream_stt_config(s).provider == "elevenlabs"
    s = Settings(voice_stream_stt=True, sarvam_api_key="s")
    assert _stream_stt_config(s).provider == "sarvam"
    assert _stream_stt_config(Settings(voice_stream_stt=True)) is None
    assert _stream_stt_config(Settings()) is None
