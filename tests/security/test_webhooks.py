"""Red team: forged webhooks (WhatsApp Cloud API, Twilio voice), media-stream
hijack, inbound flooding. Any unauthenticated webhook = anyone can impersonate any
user ("I'm +91 98..., delete everything" still needs the PIN, but "call my ex 20
times" does not)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from friday.channels.whatsapp import sign, verify_signature, verify_subscription
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import InboundMessage
from tests.security.conftest import ALICE_PHONE, make_active_user

APP_SECRET = "wa-app-secret-for-tests"
BODY = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()


# ------------------------------------------------------------------ WhatsApp (unit)


def test_whatsapp_signature_accepts_only_exact_hmac() -> None:
    good = sign(BODY, APP_SECRET)
    assert verify_signature(BODY, good, APP_SECRET)
    assert not verify_signature(BODY, None, APP_SECRET)
    assert not verify_signature(BODY, "", APP_SECRET)
    assert not verify_signature(BODY, good.removeprefix("sha256="), APP_SECRET)  # no prefix
    assert not verify_signature(BODY, "sha1=" + good[7:], APP_SECRET)
    assert not verify_signature(BODY + b" ", good, APP_SECRET)  # tampered body
    assert not verify_signature(BODY, sign(BODY, "other-secret"), APP_SECRET)
    assert not verify_signature(BODY, good.upper(), APP_SECRET)


def test_whatsapp_subscription_handshake_needs_token() -> None:
    assert verify_subscription("subscribe", "tok", "123", "tok") == "123"
    assert verify_subscription("subscribe", "wrong", "123", "tok") is None
    assert verify_subscription("unsubscribe", "tok", "123", "tok") is None
    assert verify_subscription("subscribe", None, "123", "tok") is None


# ------------------------------------------------------------------ WhatsApp (app)


def _app(settings: Settings, clock, bus, db):
    from friday.api.app import create_app
    from friday.channels.simulator import SimulatorChannel
    from friday.channels.sms import FakeSMS

    c = Container(settings, clock=clock, bus=bus)
    c.override_db(db)
    c.override("messaging", SimulatorChannel(clock, {}))
    c.override("sms", FakeSMS({}, clock))
    return create_app(c, background=False, fast_pin_hash=True)


async def _post(app, body: bytes, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://friday.test") as client:
        return await client.post("/webhooks/whatsapp", content=body, headers=headers)


@pytest.mark.parametrize(
    "header",
    [None, "sha256=deadbeef", "sha256=" + "0" * 64, "garbage"],
)
async def test_whatsapp_webhook_rejects_bad_signature(settings, clock, bus, db, header) -> None:
    app = _app(
        settings.model_copy(update={"whatsapp_app_secret": SecretStr(APP_SECRET)}), clock, bus, db
    )
    headers = {"content-type": "application/json"}
    if header:
        headers["x-hub-signature-256"] = header
    resp = await _post(app, BODY, headers)
    assert resp.status_code == 401


async def test_whatsapp_webhook_accepts_valid_signature(settings, clock, bus, db) -> None:
    app = _app(
        settings.model_copy(update={"whatsapp_app_secret": SecretStr(APP_SECRET)}), clock, bus, db
    )
    resp = await _post(
        app,
        BODY,
        {"x-hub-signature-256": sign(BODY, APP_SECRET), "content-type": "application/json"},
    )
    assert resp.status_code == 200


async def test_whatsapp_webhook_refuses_unsigned_in_live_mode(settings, clock, bus, db) -> None:
    live = settings.model_copy(update={"mode": "live", "whatsapp_app_secret": None})
    app = _app(live, clock, bus, db)
    resp = await _post(app, BODY, {"content-type": "application/json"})
    assert resp.status_code == 401


def test_live_mode_rejects_default_verify_token(settings) -> None:
    live = settings.model_copy(update={"mode": "live"})
    assert any("VERIFY_TOKEN" in p for p in live.live_problems())


# ------------------------------------------------------------------ Twilio


def _twilio():
    return pytest.importorskip("friday.voice.telephony.twilio")


def test_twilio_signature_validation() -> None:
    tw = _twilio()
    url = "https://friday.example.in/voice/twilio/status?key=abc"
    params = {"CallSid": "CA123", "CallStatus": "completed", "From": "+918040000001"}
    sig = tw.sign_twilio("token", url, params)
    assert tw.validate_twilio_signature("token", url, params, sig)
    assert not tw.validate_twilio_signature("token", url, params, None)
    assert not tw.validate_twilio_signature("other", url, params, sig)
    assert not tw.validate_twilio_signature("token", url, {**params, "CallStatus": "x"}, sig)
    assert not tw.validate_twilio_signature("token", url.replace("abc", "abd"), params, sig)
    assert not tw.validate_twilio_signature("token", url, params, sig[:-2] + "==")


async def test_media_stream_needs_per_call_secret() -> None:
    tw = _twilio()
    from friday.voice.stt.fake import FakeSTT

    tel = tw.TwilioTelephony(
        account_sid="AC1",
        auth_token="t",
        from_number="+918000000000",
        public_base_url="https://friday.example.in",
        stt=FakeSTT(),
        tts=None,
    )  # type: ignore[arg-type]
    leg = tw.TwilioCallLeg(
        tel, key="secret-key-123", to_phone="+918040000001", from_number="+918000000000"
    )
    tel.legs[leg.key] = leg
    tel.by_sid["CA_KNOWN"] = leg
    state: dict = {}

    async def send(_t: str) -> None:
        return None

    start = {
        "event": "start",
        "streamSid": "MZ1",
        "start": {"callSid": "CA_KNOWN", "customParameters": {}},
    }
    try:
        await tel.handle_stream_message(start, send, state)
        assert "leg" not in state  # attacker without the key must not get the call audio
    finally:
        if state.get("leg") is not None:
            state["leg"].on_stream_stop()


# ------------------------------------------------------------------ flooding


async def test_inbound_flood_is_throttled(repos, clock, pipeline, fake_brain) -> None:
    await make_active_user(repos, clock, ALICE_PHONE)
    for i in range(60):
        await pipeline.handle(
            InboundMessage(
                channel="simulator", from_phone=ALICE_PHONE, text=f"call this number again {i}"
            )
        )
    assert len(fake_brain.seen) <= 30


def test_recordings_route_absent_in_live(settings) -> None:
    """SECURITY-19: /recordings and /sim/* exist only with the simulator telephony."""
    http = pytest.importorskip("friday.voice.http")
    from friday.core.container import Container

    def paths(cfg) -> set[str]:
        return {getattr(r, "path", "") for r in http.build_router(Container(cfg)).routes}

    assert "/recordings/{name}" in paths(settings)
    live = settings.model_copy(update={"mode": "live"})
    p = paths(live)
    assert "/recordings/{name}" not in p
    assert not any(x.startswith("/sim") for x in p)


async def test_media_stream_rejects_wrong_token_and_second_start() -> None:
    tw = _twilio()
    from friday.voice.stt.fake import FakeSTT

    tel = tw.TwilioTelephony(
        account_sid="AC1",
        auth_token="t",
        from_number="+918000000000",
        public_base_url="https://friday.example.in",
        stt=FakeSTT(),
        tts=None,
    )  # type: ignore[arg-type]
    leg = tw.TwilioCallLeg(tel, key="k-1", to_phone="+918040001", from_number="+918000000000")
    tel.legs[leg.key] = leg

    async def send(_t: str) -> None:
        return None

    def start(token: str) -> dict:
        return {
            "event": "start",
            "streamSid": "MZ1",
            "start": {"callSid": "CA1", "customParameters": {"key": leg.key, "token": token}},
        }

    bad: dict = {}
    await tel.handle_stream_message(start("0" * 64), send, bad)
    assert "leg" not in bad
    good: dict = {}
    await tel.handle_stream_message(start(tel.stream_token(leg.key)), send, good)
    assert good["leg"] is leg
    again: dict = {}
    await tel.handle_stream_message(start(tel.stream_token(leg.key)), send, again)
    assert "leg" not in again  # a second start for an attached leg is refused
    leg.on_stream_stop()
