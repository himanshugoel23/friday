"""Sarvam/Vobiz telephony (mode a: media stream, our policy owns every turn) + routing."""

from __future__ import annotations

import asyncio
import base64
import json

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
    CallMode,
    CallOutcome,
    DialStatus,
    Language,
    OutboundCallRequest,
    TaskType,
)
from friday.voice.http import build_router
from friday.voice.telephony.routing import RoutedTelephony, build_routed_telephony, satisfies
from friday.voice.telephony.sarvam import CAPABILITIES, SarvamTelephony, sarvam_token

from .conftest import ScriptedPolicy, hangup, make_brief, no_answer_user
from .test_twilio import StubSTT, StubTTS, speech_frames

BASE = "https://friday.example.in"
SECRET = "s3cret"


class Recorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/Call/"):
            return httpx.Response(
                201,
                json={
                    "api_id": "a",
                    "message": "call fired",
                    "request_uuid": f"uuid-{len(self.requests)}",
                },
            )
        if request.url.path.endswith("/Record/"):
            return httpx.Response(202, json={"url": "https://media.vobiz.ai/rec/abc.mp3"})
        return httpx.Response(202, json={})

    def body(self, i=-1):
        return json.loads(self.requests[i].content or b"{}")


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def sbus():
    return EventBus()


@pytest.fixture
def sar(rec, sbus):
    return SarvamTelephony(
        auth_id="MA123",
        auth_token="tok",
        caller_ids=["+918031110001", "+918031110002"],
        public_base_url=BASE,
        secret=SECRET,
        stt=StubSTT(),
        tts=StubTTS(),
        bus=sbus,
        transport=httpx.MockTransport(rec),
        inbound_claim_timeout_s=0.05,
    )


async def start(sar, leg, sent, state, *, call_id=None):
    async def send(text):
        msg = json.loads(text)
        sent.append(msg)
        if msg["event"] == "checkpoint":  # Vobiz echoes "playedStream" when played
            await sar.handle_stream_message(
                {"event": "playedStream", "name": msg["name"]}, send, state
            )

    await sar.handle_stream_message(
        {
            "event": "start",
            "sequenceNumber": 0,
            "start": {
                "callId": call_id or leg.provider_call_id,
                "streamId": "s-1",
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
            },
        },
        send,
        state,
        key=leg.key if leg else None,
    )
    return send


def test_capability_matrix():
    assert {"dtmf", "media_stream", "inbound", "missed_call", "recording"} <= CAPABILITIES
    assert "bridge_transfer" not in CAPABILITIES  # unverified: off until tested
    assert "bridge_conference" not in CAPABILITIES and "custom_llm_turns" not in CAPABILITIES
    assert not satisfies(CAPABILITIES, {"dtmf", "bridge"})
    assert satisfies(CAPABILITIES | {"bridge_transfer"}, {"dtmf", "bridge"})
    assert not satisfies(frozenset({"outbound"}), {"bridge"})


async def test_place_call_payload_sticky_and_answer_xml(sar, rec):
    assert isinstance(sar, TelephonyProvider)
    leg = await sar.place_call(
        OutboundCallRequest(to_phone="+918040000001", task_id="t", ring_timeout_s=25)
    )
    assert isinstance(leg, CallLeg) and leg.provider_call_id == "uuid-1"
    req = rec.requests[-1]
    assert req.url.path == "/api/v1/Account/MA123/Call/"
    b = rec.body()
    assert (
        b["to"] == "918040000001" and "+" + b["from"] in sar.caller_ids and b["ring_timeout"] == 25
    )
    assert "token=" in b["answer_url"] and "/voice/sarvam/hangup" in b["hangup_url"]
    xml = await sar.answer_xml({"CallUUID": "call-1"}, leg.key)
    assert 'bidirectional="true"' in xml and "wss://friday.example.in/voice/sarvam/media" in xml
    await asyncio.sleep(0)  # recording started via REST
    assert any(r.url.path.endswith("/Record/") for r in rec.requests)
    leg2 = await sar.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t2"))
    assert leg2.from_number == leg.from_number


async def test_stream_turns_dtmf_recording_hangup(sar, rec):
    leg = await sar.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await sar.answer_xml({"CallUUID": leg.provider_call_id}, leg.key)
    sent, state = [], {}
    send = await start(sar, leg, sent, state)
    assert await leg.wait_for_answer(5) == DialStatus.ANSWERED
    await leg.speak("Namaste", Language.HINGLISH)
    assert any(m["event"] == "playAudio" for m in sent) and sent[-1]["event"] == "checkpoint"
    for f in speech_frames():
        await sar.handle_stream_message(
            {"event": "media", "media": {"payload": base64.b64encode(f).decode()}}, send, state
        )
    t = await leg.listen(5)
    assert t and t.audio_class == AudioClass.HUMAN
    await leg.send_dtmf("2")
    dt = rec.requests[-1]
    assert (
        dt.url.path.endswith(f"/Call/{leg.provider_call_id}/DTMF/") and rec.body()["digits"] == "2"
    )
    await asyncio.sleep(0)
    assert await leg.recording_url() == "https://media.vobiz.ai/rec/abc.mp3"
    await leg.hangup()
    assert rec.requests[-1].method == "DELETE"
    with pytest.raises(CallEnded):
        await leg.listen(1)


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        ("USER_BUSY", DialStatus.BUSY),
        ("NO_ANSWER", DialStatus.NO_ANSWER),
        ("UNALLOCATED_NUMBER", DialStatus.FAILED),
    ],
)
async def test_hangup_causes(sar, cause, expected):
    leg = await sar.place_call(OutboundCallRequest(to_phone="+918040000004", task_id="t"))
    await sar.handle_hangup({"RequestUUID": leg.provider_call_id, "HangupCause": cause}, None)
    assert await leg.wait_for_answer(1) == expected


async def test_machine_detection_voicemail(sar):
    leg = await sar.place_call(OutboundCallRequest(to_phone="+918040000004", task_id="t"))
    await sar.handle_machine({"Machine": "true"}, leg.key)
    assert await leg.wait_for_answer(1) == DialStatus.VOICEMAIL


async def test_bridge_is_transfer(sar, rec):
    leg = await sar.place_call(OutboundCallRequest(to_phone="+911800000121", task_id="t"))
    await sar.answer_xml({"CallUUID": leg.provider_call_id}, leg.key)
    await start(sar, leg, [], {})
    await leg.wait_for_answer(5)
    user = await leg.add_participant("+919812345678", announce="Connecting you to Airtel")
    b = rec.body()
    assert b["legs"] == "aleg" and "/voice/sarvam/transfer" in b["aleg_url"]
    xml = sar.transfer_xml({"to": "+919812345678", "caller": leg.from_number, "say": "Connecting"})
    assert "<Dial" in xml and "919812345678" in xml
    await sar.handle_transfer_status({}, user.key)
    assert await user.wait_for_answer(5) == DialStatus.ANSWERED


async def test_inbound_and_missed(sar, sbus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    sbus.subscribe(Event, on)
    await sar.answer_xml({"CallUUID": "in-1", "From": "+918040000001", "To": "+918031110001"}, None)
    await start(sar, sar.by_sid["in-1"], [], {}, call_id="in-1")
    ev = [e for e in seen if type(e).__name__ == "InboundCallReceived"][0]
    assert ev.from_phone == "+918040000001" and ev.to_number == "+918031110001"
    assert sar.take_inbound("in-1") is not None
    await sar.answer_xml({"CallUUID": "in-2", "From": "+918040000012", "To": "+918031110002"}, None)
    await sar.handle_hangup(
        {"CallUUID": "in-2", "HangupCause": "ORIGINATOR_CANCEL", "Duration": "4"}, None
    )
    missed = [e for e in seen if type(e).__name__ == "MissedCallReceived"]
    assert missed and missed[0].provider_call_id == "in-2" and missed[0].ring_seconds == 4


def test_router_sarvam_endpoints_and_auth(sar):
    c = Container(Settings(_env_file=None, public_base_url=BASE))
    c.override("telephony", RoutedTelephony([sar]))  # works behind the router too
    app = FastAPI()
    app.include_router(build_router(c), prefix="/voice")
    client = TestClient(app)
    assert client.post("/voice/sarvam/inbound?token=bad", data={"CallUUID": "x"}).status_code == 403
    tok = sarvam_token(SECRET, "inbound")
    r = client.post(
        f"/voice/sarvam/inbound?token={tok}",
        data={"CallUUID": "x", "From": "+918040000001", "To": "+918031110001"},
    )
    assert r.status_code == 200 and "<Stream" in r.text
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/voice/sarvam/media?token=bad") as ws,
    ):
        ws.receive_text()
    assert client.post("/voice/twilio/status", data={}).status_code == 404


# ------------------------------------------------------------------ routing


class FakeProvider:
    def __init__(self, name, caps, fail=False):
        self.name = name
        self.caps = frozenset(caps)
        self.fail = fail
        self.calls = []

    def capabilities(self):
        return self.caps

    async def place_call(self, request):
        self.calls.append(request)
        if self.fail:
            raise ProviderError(self.name, "down", retryable=True)
        return f"leg:{self.name}"


async def test_routing_priority_capability_and_international():
    sarvam = FakeProvider("sarvam", CAPABILITIES)
    exotel = FakeProvider("exotel", {"outbound", "dtmf", "bridge_transfer", "media_stream"})
    twilio = FakeProvider(
        "twilio", {"outbound", "dtmf", "bridge_conference", "media_stream", "amd"}
    )
    r = RoutedTelephony([sarvam, exotel, twilio], international=twilio)
    req = OutboundCallRequest(to_phone="+918040000001", task_id="t")
    assert await r.place_call(req) == "leg:sarvam"
    assert (
        await r.place_call(req.model_copy(update={"metadata": {"needs": "bridge_conference"}}))
        == "leg:twilio"
    )
    assert await r.place_call(req.model_copy(update={"to_phone": "+14155550100"})) == "leg:twilio"
    sarvam.fail = True
    assert await r.place_call(req) == "leg:exotel"  # per-call fallback on provider error
    exotel.fail = twilio.fail = True
    with pytest.raises(ProviderError):
        await r.place_call(req)


async def test_runner_sets_needs_and_reports_leg_provider(make_runner, sim):
    from .conftest import AIRTEL

    seen = []

    class Spy:
        name = "routed"

        def capabilities(self):
            return sim.capabilities()

        async def place_call(self, request):
            seen.append(request.metadata.get("needs"))
            return await sim.place_call(request)

    policy = ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)])
    brief = make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel")
    result = await make_runner(policy, telephony=Spy()).run(brief, no_answer_user)
    assert seen == ["bridge,dtmf"] and result.provider == "simulator"
    seen.clear()
    await make_runner(ScriptedPolicy([]), telephony=Spy()).run(
        make_brief(mode=CallMode.TRANSLATOR, user_phone=None), no_answer_user
    )
    assert seen == ["media_stream"]


def _route_container(**kw):
    from pydantic import SecretStr

    s = Settings(
        _env_file=None,
        sarvam_telephony_auth_id="MA1",
        sarvam_telephony_auth_token=SecretStr("t"),
        sarvam_caller_ids=["+918031110001"],
        twilio_account_sid="AC",
        twilio_auth_token=SecretStr("t"),
        twilio_from_number="+14155550100",
        **kw,
    )
    c = Container(s)
    c.override("stt", StubSTT())
    c.override("tts", StubTTS())
    return c


def test_default_live_route_is_sarvam_only():
    """Founder decision: no Exotel/Twilio unless explicitly enabled."""
    routed = build_routed_telephony(_route_container(telephony_provider="auto"))
    assert [p.name for p in routed.providers] == ["sarvam"]
    assert routed.international is None


def test_explicit_routed_enables_other_providers():
    c = _route_container(
        telephony_provider="routed", telephony_route=["sarvam", "exotel", "twilio"]
    )
    routed = build_routed_telephony(c)
    assert [p.name for p in routed.providers] == ["sarvam", "twilio"]  # no Exotel creds -> skipped
    assert routed.international is routed.providers[1]
    with pytest.raises(ProviderError):  # route with no configured provider
        build_routed_telephony(c, ["exotel"])


@pytest.mark.live
async def test_live_sarvam_vobiz_call():  # pragma: no cover
    import os

    if not (os.environ.get("SARVAM_TELEPHONY_AUTH_ID") and os.environ.get("FRIDAY_LIVE_TEST_TO")):
        pytest.skip("Sarvam/Vobiz telephony credentials not set")
    from friday.voice.telephony.sarvam import build_sarvam_telephony

    tel = build_sarvam_telephony(Container(Settings()))
    leg = await tel.place_call(
        OutboundCallRequest(to_phone=os.environ["FRIDAY_LIVE_TEST_TO"], task_id="live")
    )
    assert leg.provider_call_id
