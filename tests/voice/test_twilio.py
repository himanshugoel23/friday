"""V-4: Twilio provider with recorded webhook payloads + mocked REST (no network)."""

from __future__ import annotations

import asyncio
import json
import math
import random
from array import array
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import Event, EventBus
from friday.core.interfaces import CallEnded, CallLeg, ProviderError, TelephonyProvider
from friday.core.models import (
    AudioClass,
    AudioClip,
    DialStatus,
    Language,
    OutboundCallRequest,
    Transcription,
    VoiceProfile,
)
from friday.voice.audio import pcm16_to_ulaw, pcm16_to_wav, silence, tone
from friday.voice.http import build_router
from friday.voice.telephony.twilio import (
    TwilioTelephony,
    sign_twilio,
    validate_twilio_signature,
)

BASE = "https://friday.example.in"
TOKEN = "test-auth-token"


class StubSTT:
    name = "stub"
    supported_languages = frozenset(Language)

    def __init__(self, text="Hello, Looks salon, boliye"):
        self.text = text
        self.calls = 0

    async def transcribe(self, audio, *, language_hint=None):
        self.calls += 1
        return Transcription(text=self.text, language=Language.HINGLISH, confidence=0.9)


class StubTTS:
    name = "stub"
    supported_languages = frozenset(Language)

    def voice_for(self, language):
        return VoiceProfile(provider="stub", voice_id="v", language=language)

    async def synthesize(self, text, language, *, voice=None):
        return AudioClip(
            data=pcm16_to_wav(tone(440, 0.1, 16000), 16000), mime="audio/wav", sample_rate=16000
        )


class Recorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.n = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.n += 1
        return httpx.Response(201, json={"sid": f"CA{self.n:032d}"})

    def form(self, i=-1) -> dict[str, list[str]]:
        return parse_qs(self.requests[i].content.decode())


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def tbus():
    return EventBus()


@pytest.fixture
def tel(rec, tbus):
    return TwilioTelephony(
        account_sid="ACtest",
        auth_token=TOKEN,
        from_number="+918069110001",
        public_base_url=BASE,
        stt=StubSTT(),
        tts=StubTTS(),
        bus=tbus,
        friday_numbers=["+918069110001", "+918069110002"],
        transport=httpx.MockTransport(rec),
        inbound_claim_timeout_s=0.05,
    )


def speech_frames(seconds=1.0):
    rnd = random.Random(3)
    out = array("h")
    for i in range(int(8000 * seconds)):
        t = i / 8000
        env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        out.append(
            int(9000 * env * (rnd.random() * 2 - 1) + 6000 * env * math.sin(2 * math.pi * 180 * t))
        )
    ulaw = pcm16_to_ulaw(out.tobytes() + silence(1.0))
    return [ulaw[i : i + 160] for i in range(0, len(ulaw), 160)]


async def start_stream(tel, leg, sent, state, role=None):
    async def send(text):
        msg = json.loads(text)
        sent.append(msg)
        if msg["event"] == "mark":  # Twilio echoes marks when playback finishes
            await tel.handle_stream_message({"event": "mark", "mark": msg["mark"]}, send, state)

    params = tel.stream_params(leg.key)
    if role:
        params["role"] = role
    await tel.handle_stream_message(
        {
            "event": "start",
            "streamSid": "MZ1",
            "start": {"callSid": leg.provider_call_id, "customParameters": params},
        },
        send,
        state,
    )
    return send


def test_signature_validation():
    params = {"CallSid": "CA123", "CallStatus": "in-progress", "From": "+918040000001"}
    url = f"{BASE}/voice/twilio/status?key=abc"
    sig = sign_twilio(TOKEN, url, params)
    assert validate_twilio_signature(TOKEN, url, params, sig)
    assert not validate_twilio_signature(TOKEN, url, {**params, "CallStatus": "completed"}, sig)
    assert not validate_twilio_signature("other", url, params, sig)
    assert not validate_twilio_signature(TOKEN, url, params, None)


async def test_place_call_rest_payload_and_sticky_caller_id(tel, rec):
    assert isinstance(tel, TelephonyProvider)
    leg = await tel.place_call(
        OutboundCallRequest(to_phone="+918040000001", task_id="t1", ring_timeout_s=25)
    )
    assert isinstance(leg, CallLeg)
    form = rec.form()
    assert rec.requests[-1].url.path == "/2010-04-01/Accounts/ACtest/Calls.json"
    assert form["To"] == ["+918040000001"] and form["Timeout"] == ["25"]
    assert form["From"][0] in tel.friday_numbers
    assert "wss://friday.example.in/voice/twilio/media" in form["Twiml"][0]
    assert form["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]
    assert form["MachineDetection"] == ["Enable"] and form["Record"] == ["true"]
    assert rec.requests[-1].headers["Authorization"].startswith("Basic ")
    leg2 = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t2"))
    assert leg2.from_number == leg.from_number  # sticky
    leg3 = await tel.place_call(
        OutboundCallRequest(
            to_phone="+918040000001", task_id="t3", metadata={"from_number": "+918069110002"}
        )
    )
    assert rec.form()["From"] == ["+918069110002"] and leg3.from_number == "+918069110002"


async def test_answer_speak_listen_dtmf_hangup(tel, rec):
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t1"))
    await tel.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "ringing"}, leg.key)
    await tel.handle_status(
        {"CallSid": leg.provider_call_id, "CallStatus": "in-progress", "AnsweredBy": "human"},
        leg.key,
    )
    sent, state = [], {}
    send = await start_stream(tel, leg, sent, state)
    assert await leg.wait_for_answer(5) == DialStatus.ANSWERED

    await leg.speak("Namaste", Language.HINGLISH)
    media = [m for m in sent if m["event"] == "media"]
    assert media and all(m["streamSid"] == "MZ1" for m in media)
    assert sent[-1]["event"] == "mark"
    assert leg.last_tts_ms is not None

    for frame in speech_frames():
        import base64

        await tel.handle_stream_message(
            {"event": "media", "media": {"payload": base64.b64encode(frame).decode()}}, send, state
        )
    t = await leg.listen(5)
    assert t is not None and t.text.startswith("Hello") and t.audio_class == AudioClass.HUMAN
    assert leg.last_stt_ms is not None

    before = len(sent)
    await leg.send_dtmf("12#")
    assert len(sent) > before + 5  # tones streamed in-band

    await leg.hangup()
    assert parse_qs(rec.requests[-1].content.decode())["Status"] == ["completed"]
    with pytest.raises(CallEnded):
        await leg.listen(1)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"CallStatus": "busy"}, DialStatus.BUSY),
        ({"CallStatus": "no-answer"}, DialStatus.NO_ANSWER),
        ({"CallStatus": "failed"}, DialStatus.FAILED),
        ({"CallStatus": "in-progress", "AnsweredBy": "machine_end_beep"}, DialStatus.VOICEMAIL),
    ],
)
async def test_dial_outcomes_from_status_callbacks(tel, params, expected):
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000004", task_id="t1"))
    await tel.handle_status({"CallSid": leg.provider_call_id, **params}, None)  # lookup by CallSid
    assert await leg.wait_for_answer(5) == expected


async def test_recording_callback(tel):
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t1"))
    await tel.handle_recording(
        {
            "CallSid": leg.provider_call_id,
            "RecordingStatus": "completed",
            "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE1",
        },
        leg.key,
    )
    assert (
        await leg.recording_url()
        == "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE1.mp3"
    )


async def test_add_participant_conference_and_leave(tel, rec):
    leg = await tel.place_call(OutboundCallRequest(to_phone="+911800000121", task_id="t1"))
    await tel.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "in-progress"}, leg.key)
    await start_stream(tel, leg, [], {})
    await leg.wait_for_answer(5)
    user = await leg.add_participant(
        "+919812345678", announce="Connecting you to Airtel. They need OTP verification."
    )
    update = parse_qs(rec.requests[-2].content.decode())
    assert "<Conference" in update["Twiml"][0] and 'track="inbound_track"' in update["Twiml"][0]
    dial = rec.form()
    assert (
        dial["To"] == ["+919812345678"]
        and "<Say" in dial["Twiml"][0]
        and "OTP verification" in dial["Twiml"][0]
    )
    assert "MachineDetection" not in dial
    with pytest.raises(ProviderError):
        await leg.speak("hello", Language.EN)  # Friday is muted once bridged
    await tel.handle_status(
        {"CallSid": user.provider_call_id, "CallStatus": "in-progress"}, user.key
    )
    await start_stream(tel, user, [], {}, role="monitor")
    assert await user.wait_for_answer(5) == DialStatus.ANSWERED
    n = len(rec.requests)
    await leg.leave()
    assert len(rec.requests) == n  # leaving does not end the bridged call
    with pytest.raises(CallEnded):
        await leg.listen(1)


async def test_inbound_answered_publishes_and_parks_leg(tel, tbus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    tbus.subscribe(Event, on)
    xml = tel.inbound_twiml({"CallSid": "CAin1", "From": "+918040000001", "To": "+918069110001"})
    assert "<Connect><Stream" in xml
    leg = tel.by_sid["CAin1"]
    await start_stream(tel, leg, [], {})
    ev = [e for e in seen if type(e).__name__ == "InboundCallReceived"][0]
    assert ev.from_phone == "+918040000001" and ev.to_number == "+918069110001"
    assert ev.provider_call_id == "CAin1"
    got = tel.take_inbound("CAin1")
    assert got is leg and got.inbound and await got.wait_for_answer(1) == DialStatus.ANSWERED


async def test_inbound_unclaimed_plays_fixed_message(tel, rec):
    tel.inbound_twiml({"CallSid": "CAin2", "From": "+919700000000", "To": "+918069110001"})
    await start_stream(tel, tel.by_sid["CAin2"], [], {})
    await asyncio.sleep(0.1)
    twiml = rec.form()["Twiml"][0]
    assert "AI assistant" in twiml and "<Hangup/>" in twiml


async def test_inbound_missed_call(tel, tbus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    tbus.subscribe(Event, on)
    tel.inbound_twiml({"CallSid": "CAin3", "From": "+918040000001", "To": "+918069110002"})
    await tel.handle_status(
        {
            "CallSid": "CAin3",
            "CallStatus": "completed",
            "From": "+918040000001",
            "To": "+918069110002",
            "CallDuration": "0",
        },
        None,
    )
    missed = [e for e in seen if type(e).__name__ == "MissedCallReceived"]
    assert missed and missed[0].to_number == "+918069110002"
    assert not [e for e in seen if type(e).__name__ == "InboundCallReceived"]


def _app(tel) -> tuple[TestClient, Container]:
    s = Settings(_env_file=None, public_base_url=BASE)
    c = Container(s)
    c.override("telephony", tel)
    app = FastAPI()
    app.include_router(build_router(c), prefix="/voice")
    return TestClient(app), c


def test_router_rejects_bad_signature_and_accepts_good(tel):
    client, _ = _app(tel)
    params = {"CallSid": "CAx", "CallStatus": "ringing"}
    r = client.post(
        "/voice/twilio/status?key=nope", data=params, headers={"X-Twilio-Signature": "bad"}
    )
    assert r.status_code == 403
    sig = sign_twilio(TOKEN, f"{BASE}/voice/twilio/status?key=nope", params)
    r = client.post(
        "/voice/twilio/status?key=nope", data=params, headers={"X-Twilio-Signature": sig}
    )
    assert r.status_code == 204


def test_router_inbound_twiml(tel):
    client, _ = _app(tel)
    params = {
        "CallSid": "CAr1",
        "From": "+918040000001",
        "To": "+918069110001",
        "CallStatus": "ringing",
    }
    sig = sign_twilio(TOKEN, f"{BASE}/voice/twilio/inbound", params)
    r = client.post("/voice/twilio/inbound", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "wss://friday.example.in/voice/twilio/media" in r.text


def test_router_media_websocket_start_and_stop(tel):
    client, _ = _app(tel)
    tel.inbound_twiml({"CallSid": "CAws", "From": "+918040000001", "To": "+918069110001"})
    leg = tel.by_sid["CAws"]
    leg.claimed = True  # don't start the claim guard
    sig = sign_twilio(TOKEN, tel.media_ws_url, {})
    from starlette.websockets import WebSocketDisconnect

    # SECURITY-18: an unsigned upgrade is refused before accept()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/voice/twilio/media") as bad:
        bad.receive_text()
    with client.websocket_connect("/voice/twilio/media", headers={"X-Twilio-Signature": sig}) as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": "MZws",
                    "start": {
                        "callSid": "CAws",
                        "customParameters": tel.stream_params(leg.key),
                    },
                }
            )
        )
        ws.send_text(json.dumps({"event": "stop"}))
    assert leg.stream_sid == "MZws" and leg.ended


def test_twilio_routes_404_in_simulator_mode(vsettings):
    from friday.core.clock import FakeClock

    c = Container(vsettings, clock=FakeClock())
    app = FastAPI()
    app.include_router(build_router(c), prefix="/voice")
    client = TestClient(app)
    assert client.post("/voice/twilio/status", data={}).status_code == 404
    r = client.post("/voice/sim/inbound", json={"from_phone": "+918040000001", "answered": False})
    assert r.status_code == 200 and r.json()["answered"] is False
    r = client.post("/voice/sim/deliver-due")
    assert r.status_code == 200
    assert client.get("/voice/recordings/..%2Fsecret").status_code == 404


async def test_plivo_stub_raises():
    from friday.voice.telephony.plivo import PlivoTelephony

    with pytest.raises(ProviderError):
        await PlivoTelephony().place_call(
            OutboundCallRequest(to_phone="+918040000001", task_id="t")
        )


@pytest.mark.live
async def test_live_twilio_call():  # pragma: no cover - needs real credentials + public URL
    import os

    s = Settings()
    if not (s.twilio_account_sid and s.twilio_auth_token and os.environ.get("FRIDAY_LIVE_TEST_TO")):
        pytest.skip("Twilio credentials / FRIDAY_LIVE_TEST_TO not set")
    c = Container(s)
    from friday.voice.telephony.twilio import build_twilio

    tel = build_twilio(c)
    leg = await tel.place_call(
        OutboundCallRequest(to_phone=os.environ["FRIDAY_LIVE_TEST_TO"], task_id="live")
    )
    assert leg.provider_call_id
    await leg.hangup()
