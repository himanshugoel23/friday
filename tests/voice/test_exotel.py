"""Exotel (primary India provider): recorded-style payloads, mocked REST, no network."""

from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import Event, EventBus
from friday.core.interfaces import CallEnded, CallLeg, TelephonyProvider
from friday.core.models import AudioClass, DialStatus, Language, OutboundCallRequest
from friday.voice.audio import silence
from friday.voice.http import build_router
from friday.voice.telephony.exotel import ExotelTelephony, exotel_token, validate_exotel_token

from .test_twilio import StubSTT, StubTTS, speech_frames

BASE = "https://friday.example.in"
SECRET = "s3cret"


class Recorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(
            200, json={"Call": {"Sid": f"exo{len(self.requests):04d}", "Status": "in-progress"}}
        )

    def form(self, i=-1):
        return {k: v[0] for k, v in parse_qs(self.requests[i].content.decode()).items()}


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def ebus():
    return EventBus()


@pytest.fixture
def exo(rec, ebus):
    return ExotelTelephony(
        sid="friday1",
        api_key="key",
        api_token="tok",
        caller_ids=["+918047110001", "+918047110002"],
        voicebot_app_id="12345",
        public_base_url=BASE,
        secret=SECRET,
        stt=StubSTT(),
        tts=StubTTS(),
        bus=ebus,
        transport=httpx.MockTransport(rec),
        inbound_claim_timeout_s=0.05,
        inbound_stream_wait_s=0.05,
    )


def ulaw_to_slin_frames():
    from friday.voice.audio import ulaw_to_pcm16

    pcm = b"".join(ulaw_to_pcm16(f) for f in speech_frames())
    return [pcm[i : i + 3200] for i in range(0, len(pcm), 3200)]


async def start(exo, sent, state, *, call_sid, closed=None, frm=None, to=None):
    async def send(text):
        msg = json.loads(text)
        sent.append(msg)
        if msg["event"] == "mark":
            await exo.handle_stream_message(
                {"event": "mark", "stream_sid": "st1", "mark": msg["mark"]}, send, state
            )

    async def close():
        if closed is not None:
            closed.append(True)

    # Voicebot "start" message (recorded shape)
    await exo.handle_stream_message(
        {
            "event": "start",
            "sequence_number": 1,
            "stream_sid": "st1",
            "start": {
                "stream_sid": "st1",
                "call_sid": call_sid,
                "account_sid": "friday1",
                "from": frm or "+918040000001",
                "to": to or "+918047110001",
                "custom_parameters": {},
                "media_format": {"encoding": "raw/slin", "sample_rate": "8000"},
            },
        },
        send,
        state,
        close=close,
    )
    return send


def test_token_auth():
    t = exotel_token(SECRET, "abc")
    assert validate_exotel_token(SECRET, "abc", t)
    assert not validate_exotel_token(SECRET, "abd", t) and not validate_exotel_token(
        SECRET, "abc", None
    )


async def test_place_call_connect_api_and_sticky_exophone(exo, rec):
    assert isinstance(exo, TelephonyProvider)
    leg = await exo.place_call(
        OutboundCallRequest(to_phone="+918040000001", task_id="t", ring_timeout_s=25)
    )
    assert isinstance(leg, CallLeg) and leg.provider_call_id == "exo0001"
    req = rec.requests[-1]
    assert req.url.host == "api.in.exotel.com"
    assert req.url.path == "/v1/Accounts/friday1/Calls/connect.json"
    f = rec.form()
    assert f["From"] == "+918040000001" and f["CallerId"] in exo.caller_ids
    assert f["Url"] == "http://my.exotel.com/friday1/exoml/start_voice/12345"
    assert f["StatusCallbackEvents[0]"] == "terminal" and f["Record"] == "true"
    assert "token=" in f["StatusCallback"] and f["CustomField"] == leg.key
    leg2 = await exo.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t2"))
    assert leg2.from_number == leg.from_number
    await exo.place_call(
        OutboundCallRequest(
            to_phone="+918040000001", task_id="t3", metadata={"from_number": "+918047110002"}
        )
    )
    assert rec.form()["CallerId"] == "+918047110002"


async def test_stream_answer_speak_listen_dtmf_hangup(exo):
    leg = await exo.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    sent, state, closed = [], {}, []
    send = await start(exo, sent, state, call_sid=leg.provider_call_id, closed=closed)
    assert await leg.wait_for_answer(5) == DialStatus.ANSWERED
    await leg.speak("Namaste", Language.HINGLISH)
    media = [m for m in sent if m["event"] == "media"]
    assert media and all(len(base64.b64decode(m["media"]["payload"])) % 320 == 0 for m in media)
    assert media[0]["stream_sid"] == "st1"
    for chunk in ulaw_to_slin_frames() + [silence(1.0)]:
        await exo.handle_stream_message(
            {"event": "media", "media": {"payload": base64.b64encode(chunk).decode()}}, send, state
        )
    t = await leg.listen(5)
    assert t and t.audio_class == AudioClass.HUMAN and t.text.startswith("Hello")
    n = len(sent)
    await leg.send_dtmf("9")
    assert len(sent) > n
    await leg.hangup()
    assert closed == [True]
    with pytest.raises(CallEnded):
        await leg.listen(1)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"Status": "busy", "EventType": "terminal"}, DialStatus.BUSY),
        ({"Status": "no-answer", "EventType": "terminal"}, DialStatus.NO_ANSWER),
        ({"Status": "failed", "EventType": "terminal"}, DialStatus.FAILED),
        ({"Status": "completed", "EventType": "terminal"}, DialStatus.NO_ANSWER),  # never streamed
    ],
)
async def test_status_callbacks_map_to_dial_status(exo, payload, expected):
    leg = await exo.place_call(OutboundCallRequest(to_phone="+918040000004", task_id="t"))
    await exo.handle_status({"CallSid": leg.provider_call_id, **payload})
    assert await leg.wait_for_answer(1) == expected


async def test_recording_url_from_terminal_callback(exo):
    leg = await exo.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await start(exo, [], {}, call_sid=leg.provider_call_id)
    await exo.handle_status(
        {
            "CallSid": leg.provider_call_id,
            "Status": "completed",
            "EventType": "terminal",
            "RecordingUrl": "https://recordings.exotel.com/friday1/abc.mp3",
        },
        leg.key,
    )
    assert await leg.recording_url() == "https://recordings.exotel.com/friday1/abc.mp3"


async def test_bridge_is_transfer_via_connect_two_numbers(exo, rec):
    leg = await exo.place_call(OutboundCallRequest(to_phone="+911800000121", task_id="t"))
    closed = []
    await start(exo, [], {}, call_sid=leg.provider_call_id, closed=closed)
    await leg.wait_for_answer(5)
    user = await leg.add_participant("+919812345678", announce="whisper")
    f = rec.form()
    assert (
        f["From"] == "+919812345678"
        and f["To"] == "+911800000121"
        and f["CallerId"] == leg.from_number
    )
    await exo.handle_status(
        {"CallSid": user.provider_call_id, "Status": "in-progress", "EventType": "answered"}
    )
    assert await user.wait_for_answer(5) == DialStatus.ANSWERED
    await leg.leave()
    assert closed == [True] and leg.left


async def test_inbound_passthru_stream_and_claim(exo, ebus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    ebus.subscribe(Event, on)
    exo.inbound_stream_wait_s = 5
    await exo.handle_passthru(
        {
            "CallSid": "in1",
            "CallFrom": "+918040000001",
            "CallTo": "+918047110001",
            "Direction": "incoming",
        }
    )
    await start(exo, [], {}, call_sid="in1")
    ev = [e for e in seen if type(e).__name__ == "InboundCallReceived"][0]
    assert (
        ev.from_phone == "+918040000001"
        and ev.to_number == "+918047110001"
        and ev.provider_call_id == "in1"
    )
    leg = exo.take_inbound("in1")
    assert leg is not None and leg.inbound and leg.claimed


async def test_inbound_without_passthru_and_unclaimed_message(exo):
    sent = []
    await start(exo, sent, {}, call_sid="in2", frm="+919700000000", to="+918047110002")
    await asyncio.sleep(0.2)
    assert any(m["event"] == "media" for m in sent)  # fixed P1 message played
    assert exo.by_sid["in2"].ended


async def test_missed_call_short_ring_and_terminal(exo, ebus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    ebus.subscribe(Event, on)
    await exo.handle_passthru(
        {"CallSid": "in3", "CallFrom": "+918040000001", "CallTo": "+918047110001"}
    )
    await asyncio.sleep(0.1)  # caller hung up before the Voicebot connected
    await exo.handle_passthru(
        {"CallSid": "in4", "CallFrom": "+918040000012", "CallTo": "+918047110002"}
    )
    await exo.handle_status({"CallSid": "in4", "Status": "completed", "EventType": "terminal"})
    missed = [e for e in seen if type(e).__name__ == "MissedCallReceived"]
    assert {m.provider_call_id for m in missed} == {"in3", "in4"}
    assert all(m.to_number for m in missed)
    await asyncio.sleep(0.1)
    assert len([e for e in seen if type(e).__name__ == "MissedCallReceived"]) == 2  # no duplicates


def _client(exo):
    c = Container(Settings(_env_file=None, public_base_url=BASE))
    c.override("telephony", exo)
    app = FastAPI()
    app.include_router(build_router(c), prefix="/voice")
    return TestClient(app)


def test_router_exotel_auth(exo):
    client = _client(exo)
    key = "k1"
    r = client.post(
        f"/voice/exotel/status?key={key}&token=bad", json={"CallSid": "x", "Status": "busy"}
    )
    assert r.status_code == 403
    r = client.post(
        f"/voice/exotel/status?key={key}&token={exotel_token(SECRET, key)}",
        json={"CallSid": "x", "Status": "busy"},
    )
    assert r.status_code == 204
    tok = exotel_token(SECRET, "exotel")
    assert (
        client.get("/voice/exotel/passthru?CallSid=p1&CallFrom=%2B918040000001").status_code == 403
    )
    r = client.get(
        f"/voice/exotel/passthru?token={tok}&CallSid=p1&CallFrom=%2B918040000001&CallTo=%2B918047110001"
    )
    assert r.status_code == 200 and "p1" in exo.by_sid
    assert exo.passthru_url.endswith(f"token={tok}") and exo.media_ws_url.startswith("wss://")


def test_router_exotel_ws_rejects_bad_token(exo):
    from starlette.websockets import WebSocketDisconnect

    client = _client(exo)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/voice/exotel/media?token=bad") as ws,
    ):
        ws.receive_text()


def test_build_exotel_from_settings(monkeypatch):
    from pydantic import SecretStr

    from friday.voice.telephony.exotel import build_exotel
    from friday.voice.tts.fake import build_fake_tts

    monkeypatch.setenv("EXOTEL_VOICEBOT_APP_ID", "777")
    monkeypatch.setenv("EXOTEL_CALLER_IDS", "+918047110001,+918047110002")
    s = Settings(
        _env_file=None,
        exotel_sid="sid",
        exotel_api_key="k",
        exotel_api_token=SecretStr("t"),
        exotel_caller_id="+918047110003",
    )
    c = Container(s)
    c.override("stt", StubSTT())
    c.override("tts", build_fake_tts(c))
    tel = build_exotel(c)
    assert tel.voicebot_app_id == "777" and len(tel.caller_ids) == 3


@pytest.mark.live
async def test_live_exotel_call():  # pragma: no cover - needs credentials + public URL
    import os

    if not (os.environ.get("EXOTEL_SID") and os.environ.get("FRIDAY_LIVE_TEST_TO")):
        pytest.skip("Exotel credentials / FRIDAY_LIVE_TEST_TO not set")
    from friday.voice.telephony.exotel import build_exotel

    tel = build_exotel(Container(Settings()))
    leg = await tel.place_call(
        OutboundCallRequest(to_phone=os.environ["FRIDAY_LIVE_TEST_TO"], task_id="live")
    )
    assert leg.provider_call_id
