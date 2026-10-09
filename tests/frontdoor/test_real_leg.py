"""The front door over the REAL Sarvam/Vobiz leg (media-stream framing, VAD, STT/TTS cache) with
stub speech vendors and mocked Vobiz REST. Proves the pieces fit: the inbound event no longer blocks
the receive loop, fixed lines come from the TTS cache, hang-up goes through the Vobiz API."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx

from friday.core.models import Language, Transcription
from friday.voice.telephony.sarvam import SarvamTelephony
from friday.voice.tts.cache import cached
from tests.frontdoor.conftest import FRIDAY_NUMBER, OWN, start_friday
from tests.voice.test_twilio import StubTTS, speech_frames


class ScriptSTT:
    name = "script"
    supported_languages = frozenset(Language)

    def __init__(self, texts):
        self.texts = list(texts)

    async def transcribe(self, audio, *, language_hint=None):
        text = self.texts.pop(0) if self.texts else "bye"
        return Transcription(text=text, language=Language.HINGLISH, confidence=0.9)


async def wait_for(cond, seconds=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while not cond():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.01)


async def test_a_new_allow_listed_caller_over_the_real_vobiz_leg():
    f = await start_friday("pilot", (OWN,))
    rest: list[httpx.Request] = []
    tts = cached(StubTTS(), None)
    sar = SarvamTelephony(
        auth_id="MA123", auth_token="tok", caller_ids=[FRIDAY_NUMBER],
        public_base_url="https://friday.example.in", secret="s3cret",
        stt=ScriptSTT(["Asha", "Hindi", "haan", "nahi bas"]), tts=tts, bus=f.c.bus,
        transport=httpx.MockTransport(lambda r: (rest.append(r), httpx.Response(204))[1]),
        inbound_claim_timeout_s=30,
    )
    f.c.override("telephony", sar)
    try:
        await f.rt.front_door.prerender()  # fixed lines go into the cache before the call
        warmed = tts.misses
        assert warmed > 10

        await sar.answer_xml({"CallUUID": "in-1", "From": OWN, "To": FRIDAY_NUMBER}, None)
        leg = sar.by_sid["in-1"]
        sent: list[dict] = []
        state: dict = {}

        async def send(text):
            msg = json.loads(text)
            sent.append(msg)
            if msg["event"] == "checkpoint":  # Vobiz echoes playedStream when audio was played
                await sar.handle_stream_message(
                    {"event": "playedStream", "name": msg["name"]}, send, state
                )

        # the start message returns at once although the whole call runs from its event
        await asyncio.wait_for(
            sar.handle_stream_message(
                {"event": "start", "start": {"callId": "in-1", "streamId": "s-1",
                                             "mediaFormat": {"encoding": "audio/x-mulaw",
                                                             "sampleRate": 8000}}},
                send, state, key=leg.key),
            timeout=2,
        )

        async def caller_says():
            n = len([m for m in sent if m["event"] == "checkpoint"])
            for frame in speech_frames():
                await sar.handle_stream_message(
                    {"event": "media", "media": {"payload": base64.b64encode(frame).decode()}},
                    send, state)
            await wait_for(lambda: len([m for m in sent if m["event"] == "checkpoint"]) > n)

        await wait_for(lambda: any(m["event"] == "checkpoint" for m in sent))  # the greeting
        for _ in range(4):
            if leg.ended:
                break
            await caller_says()
        await wait_for(lambda: f.rt.front_door.history, seconds=10)
        s = f.rt.front_door.history[-1]
        assert s.onboarded and s.outcome == "success" and s.end_reason == "caller finished"
        assert any(r.method == "DELETE" and r.url.path.endswith("/Call/in-1/") for r in rest)
        # greeting and goodbye are pre-rendered (cache hits); the rest of this call was new text
        # (the name lines, and the consent question in Hindi, warmed only for the default language)
        assert tts.hits >= 2 and tts.misses - warmed <= 4
        user = await f.c.repos.users.get_by_phone(OWN)
        assert user is not None
    finally:
        await sar.aclose()
        await f.close()
