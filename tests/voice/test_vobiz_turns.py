"""Vobiz leg turn-taking: barge-in, echo ignored, long speech not chopped."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx

from friday.core.models import OutboundCallRequest
from friday.voice.audio import pcm16_to_ulaw, tone
from friday.voice.telephony.sarvam import SarvamTelephony

from .test_twilio import StubSTT, StubTTS


async def _leg():
    tel = SarvamTelephony(
        auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
        public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=StubTTS(),
        transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"request_uuid": "u1"})),
    )  # fmt: skip
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    sent: list[dict] = []

    async def send(m: str) -> None:
        sent.append(json.loads(m))

    leg._send = send
    leg.stream_sid = "s1"
    leg.set_media_format({"encoding": "audio/x-mulaw", "sampleRate": 8000})
    return leg, sent


def _frames(seconds: float, amp: float) -> list[str]:
    pcm = tone(440, seconds, 8000, amp)  # type: ignore[call-arg]
    ulaw = pcm16_to_ulaw(pcm)
    n = 160  # 20 ms of 8 kHz mu-law
    return [base64.b64encode(ulaw[i : i + n]).decode() for i in range(0, len(ulaw) - n + 1, n)]


async def test_caller_speaking_over_friday_stops_her_voice():
    leg, sent = await _leg()
    leg._playing = True
    for f in _frames(0.6, 0.9):
        leg.on_media(f)
    await asyncio.sleep(0)
    assert leg._barged and any(m.get("event") == "clearAudio" for m in sent)


async def test_quiet_echo_while_she_talks_is_ignored():
    leg, sent = await _leg()
    leg._playing = True
    for f in _frames(0.6, 0.02):
        leg.on_media(f)
    assert not leg._barged and leg._segments.empty()


async def test_long_human_speech_is_not_cut_at_six_seconds():
    leg, _ = await _leg()
    for f in _frames(8.0, 0.9):
        leg.on_media(f)
    assert leg._segments.empty()  # still one open utterance, waiting for the pause
