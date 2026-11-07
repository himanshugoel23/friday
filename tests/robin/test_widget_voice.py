# ruff: noqa: E501
"""T09: the widget's press-to-talk and SOS, end to end through the REAL device API over the real family package. Tested with FAKES only
(fake STT = the "audio" is the words, fake TTS, ASGI client, recording sender): nothing real is sent or dialled. Phones are invented."""

from __future__ import annotations

import builtins
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from friday.robin import alerts as alerts_mod
from friday.robin.models import ConsentSource, FamilyStatus
from friday.robin.wiring import _DeviceConsent, build_device_ports
from friday.robindevice.api import RateLimiter, mount_robin_device
from friday.robindevice.replyaudio import ReplyAudioStore
from friday.robindevice.service import DeviceService
from friday.voice.stt.fake import FakeSTT
from friday.voice.tts.fake import build_fake_tts
from tests.robin.conftest import PARENT_PHONE
from tests.robin.test_sos_before_active import bare_family

BASE = "https://robin-server.invalid"


@dataclass
class Rig:
    w: Any
    client: httpx.AsyncClient
    service: DeviceService
    stt: FakeSTT
    tts: Any
    ports: dict[str, Any]
    token: str
    fam: Any
    parent: Any

    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def say(self, words: str, mime: str = "audio/ogg") -> httpx.Response:
        """Press-to-talk: the fake STT reads the 'audio' as the words themselves."""
        return await self.client.post("/robin/device/voice", content=words.encode(), headers={**self.h(), "Content-Type": mime, "X-Duration-S": "3"})

    async def incidents(self) -> list[Any]:
        return await self.w.store.list(self.fam.id, "incident")


async def build(w, container, *, family=None, with_tts=True, with_stt=True, llm_switch=False) -> Rig:
    fam, parent = family if family is not None else await w.family()
    stt, tts = FakeSTT(), build_fake_tts(container)
    parts = {"robin": w.hub, **({"stt": stt} if with_stt else {}), **({"tts": tts} if with_tts else {})}

    def get(name: str) -> Any:
        if name not in parts:
            raise KeyError(name)
        return parts[name]

    w.settings.robin_device_scam_llm_enabled = llm_switch
    alerts_mod.set_default_engine(w.hub.alerts)  # what build_robin does; the device alert port raises through it
    ports = build_device_ports(SimpleNamespace(get=get, settings=w.settings))
    assert ports is not None
    service = DeviceService(
        alerts=ports["alerts"], consent=ports["consent"], parents=ports["parents"], voice=ports["voice"], llm=ports.get("llm"),
        reply_audio=ports["reply_audio"], public_base_url=BASE, brand="Robin",
    )
    service.set_policy(parent.id, shadow_days=0)
    app = FastAPI()
    mount_robin_device(app, service, RateLimiter())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    code = await service.create_pairing_code(parent.id)
    r = await client.post("/robin/device/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
    assert r.status_code == 200, r.text
    return Rig(w, client, service, stt, tts, ports, r.json()["device_token"], fam, parent)


@pytest.fixture(autouse=True)
def _reset_default_engine():
    yield
    alerts_mod.set_default_engine(None)


@pytest.fixture
async def rig(w, container):
    r = await build(w, container)
    yield r
    await r.client.aclose()


# ------------------------------------------------------------------ "madad karo" raises an SOS and gets a reply
async def test_madad_karo_replies_in_the_parents_language_and_raises_an_sos(w, rig):
    texts, notes = len(w.channel.texts), len(w.channel.voice_notes)  # the setup intro is already there
    r = await rig.say("madad karo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["reply_text"] == w.ctx.say("widget.sos", "hinglish", parent="Papa", child="Asha")  # Roman Hinglish: this parent's language
    assert "Asha" in body["reply_text"] and "112" in body["reply_text"] and "line par" not in body["reply_text"]
    incs = await rig.incidents()
    assert len(incs) == 1 and incs[0].data["scenario"] == "sos" and incs[0].data["tier"] == "emergency"
    assert w.sender.sent and "Papa" in w.sender.sent[-1].text  # the child is told at once
    assert (len(w.channel.texts), len(w.channel.voice_notes)) == (texts, notes)  # the widget answer is the HTTP reply, not also a WhatsApp message


async def test_a_second_press_inside_the_window_still_reassures_without_a_second_incident(w, rig):
    await rig.say("madad karo")
    r = await rig.say("bachao")
    assert r.json()["reply_text"] == w.ctx.say("widget.sos", "hinglish", parent="Papa", child="Asha")
    assert len(await rig.incidents()) == 1


@pytest.mark.parametrize(("lang", "words", "marker"), [
    ("hi", "मदद करो", "मैंने अभी"),
    ("en", "help me", "I have told"),
    ("hinglish", "Madad karo please", "maine abhi"),
    ("hi", "बचाओ बचाओ", "मैंने अभी"),
])
async def test_hindi_hinglish_english_help_raises_an_sos_with_a_reply_in_the_parents_language(w, container, lang, words, marker):
    fam, parent = await w.family()
    parent.language = lang
    await w.store.save_member(parent, fam.owner_user_id)
    r = await build(w, container, family=(fam, parent))
    try:
        resp = await r.say(words)
        assert resp.status_code == 200 and marker in resp.json()["reply_text"]
        assert len(await r.incidents()) == 1
    finally:
        await r.client.aclose()


async def test_devanagari_words_are_transcribed_and_the_speech_path_hints_the_parents_language(w, rig):
    await rig.say("मदद करो")
    assert rig.stt.calls and rig.stt.calls[-1].mime == "audio/ogg"
    assert len(await rig.incidents()) == 1


async def test_non_ogg_audio_goes_straight_to_the_speech_provider(w, rig):
    r = await rig.say("madad karo", mime="audio/mp4")  # what the Android recorder sends (AAC in MP4)
    assert r.status_code == 200 and len(await rig.incidents()) == 1
    assert rig.stt.calls[-1].mime == "audio/mp4"


# ------------------------------------------------------------------ paused, and before setup
async def test_help_works_while_paused_and_the_reply_still_comes_back(w, rig):
    assert await w.hub.fam.pause(rig.parent.id, "voice")
    assert (await w.store.get_member(rig.parent.id)).paused is True
    assert not await _DeviceConsent(w.hub).has(rig.parent.id, "calls")  # sensitive signals stay off while paused ...
    assert await _DeviceConsent(w.hub).has(rig.parent.id, "voice_messages")  # ... but the parent's own press-to-talk is not one of them
    w.sender.sent.clear()
    r = await rig.say("madad karo")
    assert r.status_code == 200 and "Asha" in r.json()["reply_text"]
    assert len(await rig.incidents()) == 1 and w.sender.sent  # the child was told even though Robin is paused


async def test_help_works_before_setup_is_finished(w, container):
    fam, parent = await bare_family(w)
    await w.hub.fam.give_consent(parent.id, "scam_check", ConsentSource.ADMIN_CHAT)  # the only item that voice needs; nothing else agreed
    await w.hub.fam.set_status(await w.store.get_family(fam.id), FamilyStatus.ONBOARDING)  # setup is not finished
    r = await build(w, container, family=(fam, parent))
    try:
        assert (await w.store.get_family(fam.id)).status == FamilyStatus.ONBOARDING
        resp = await r.say("madad karo")
        assert resp.status_code == 200 and "Asha" in resp.json()["reply_text"]
        assert len(await r.incidents()) == 1
    finally:
        await r.client.aclose()


async def test_security_path_ignores_the_time_of_day(w, rig):
    w.clock.set(w.clock.now().replace(hour=3, minute=10))  # deep quiet hours
    r = await rig.say("madad karo")
    assert r.status_code == 200 and len(await rig.incidents()) == 1


# ------------------------------------------------------------------ no consent, no listening
async def test_no_voice_consent_is_refused_and_nothing_is_listened_to(w, container):
    fam, parent = await w.family(consent=False)
    r = await build(w, container, family=(fam, parent))
    try:
        resp = await r.say("madad karo")
        assert resp.status_code == 403 and resp.json() == {"error": "no_consent"}
        assert r.stt.calls == [] and await r.incidents() == []  # the audio never reached speech-to-text
        assert not r.service.reply_audio or len(r.service.reply_audio) == 0
    finally:
        await r.client.aclose()


async def test_withdrawing_the_consent_on_the_phone_stops_voice(w, rig):
    assert (await rig.say("theek hoon")).status_code == 200
    r = await rig.client.put("/robin/device/consent", headers=rig.h(), json={"items": {"voice_messages": False}})
    assert r.status_code == 200
    assert (await rig.say("madad karo")).status_code == 403


# ------------------------------------------------------------------ the rest of the parent's words go through parent_said
async def test_stop_by_voice_pauses_and_is_confirmed_in_the_parents_language(w, rig):
    r = await rig.say("Robin band karo")
    assert r.status_code == 200 and "ruk gayi" in r.json()["reply_text"]
    assert (await w.store.get_member(rig.parent.id)).paused is True


async def test_i_am_fine_is_acknowledged_and_raises_nothing(w, rig):
    r = await rig.say("main theek hoon")
    assert r.status_code == 200 and r.json()["reply_text"] and await rig.incidents() == []


async def test_small_talk_gets_the_short_hello_and_raises_nothing(w, rig):
    r = await rig.say("aaj mausam accha hai")
    assert r.json()["reply_text"] == w.ctx.say("inbound.hello", "hinglish", parent="Papa", child="Asha")
    assert await rig.incidents() == []


async def test_unintelligible_audio_asks_again_and_never_pretends(w, rig):
    r = await rig.say("")  # not allowed by the API (empty body)
    assert r.status_code == 422
    r = await rig.client.post("/robin/device/voice", content=b"\xff\xfe\x00\x01", headers={**rig.h(), "Content-Type": "audio/ogg", "X-Duration-S": "2"})
    assert r.status_code == 200 and r.json()["reply_text"] == w.ctx.say("widget.unclear", "hinglish")
    assert await rig.incidents() == []


async def test_distress_in_the_widget_goes_to_the_care_path(w, rig):
    r = await rig.say("main marna chahta hoon")
    assert r.status_code == 200 and r.json()["reply_text"]  # a care line, in the parent's language
    assert all(i.data["scenario"] != "sos" for i in await rig.incidents())


async def test_help_that_could_not_reach_the_child_is_never_reported_as_told(w, rig, monkeypatch):
    async def refuse(alert):  # noqa: ANN001
        return alerts_mod.AlertResult(False, "no_child_contact")

    monkeypatch.setattr(w.hub.alerts, "raise_alert", refuse)
    resp = await rig.say("madad karo")
    assert resp.status_code == 200 and resp.json()["reply_text"] == w.ctx.say("widget.sos_failed", "hinglish", child="Asha")
    assert "112" in resp.json()["reply_text"] and "khabar kar di" not in resp.json()["reply_text"]


# ------------------------------------------------------------------ the spoken reply
async def test_reply_audio_is_robins_own_voice_behind_a_one_fetch_expiring_token_url(w, rig):
    body = (await rig.say("madad karo")).json()
    url = body["reply_audio_url"]
    assert url.startswith(f"{BASE}/robin/device/audio/") and url.startswith("https://")
    token = url.rsplit("/", 1)[1]
    assert len(token) >= 40 and "p1" not in url and PARENT_PHONE not in url  # unguessable, carries no id
    got = await rig.client.get(url.removeprefix(BASE))  # no bearer needed: the token is the credential
    assert got.status_code == 200 and got.content.decode() == body["reply_text"]  # the fake TTS speaks the reply text verbatim
    assert got.headers["cache-control"] == "no-store"
    assert (await rig.client.get(url.removeprefix(BASE))).status_code == 404  # deleted after the first fetch
    assert len(rig.service.reply_audio) == 0


async def test_reply_audio_expires_and_a_made_up_token_is_a_plain_404(w, rig):
    clock = [0.0]
    store = ReplyAudioStore(ttl_s=90, clock=lambda: clock[0])
    rig.service.reply_audio = store
    url = (await rig.say("madad karo")).json()["reply_audio_url"]
    clock[0] = 91.0
    assert (await rig.client.get(url.removeprefix(BASE))).status_code == 404
    assert (await rig.client.get("/robin/device/audio/" + "A" * 43)).status_code == 404
    assert (await rig.client.get("/robin/device/audio/short")).status_code == 404
    assert (await rig.client.get("/robin/device/audio/..%2f..%2fetc")).status_code in (404, 405)


async def test_store_is_bounded_and_drops_a_parent_on_erase(w, rig):
    s = ReplyAudioStore(max_clips=3)
    tokens = [s.put("p", b"x", "audio/mpeg") for _ in range(5)]
    assert len(s) == 3 and s.take(tokens[0]) is None and s.take(tokens[4]) is not None
    assert s.put("p", b"", "audio/mpeg") is None and s.put("p", b"x" * 2_000_000, "audio/mpeg") is None
    url = (await rig.say("madad karo")).json()["reply_audio_url"]
    await rig.service.erase_parent(rig.parent.id)
    assert (await rig.client.get(url.removeprefix(BASE))).status_code in (404,)


async def test_without_a_voice_the_reply_is_text_only(w, container):
    r = await build(w, container, with_tts=False)
    try:
        body = (await r.say("madad karo")).json()
        assert body["reply_text"] and body["reply_audio_url"] is None
        assert len(await r.incidents()) == 1  # the SOS never waits for a voice
    finally:
        await r.client.aclose()


async def test_a_failing_voice_never_loses_the_text(w, rig, monkeypatch):
    async def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("tts down")

    monkeypatch.setattr(rig.tts, "synthesize", boom)
    body = (await rig.say("madad karo")).json()
    assert body["reply_text"] and body["reply_audio_url"] is None and len(await rig.incidents()) == 1


async def test_without_speech_to_text_the_parent_is_asked_to_try_again(w, container):
    r = await build(w, container, with_stt=False)
    try:
        body = (await r.say("madad karo")).json()
        assert body["reply_text"] == w.ctx.say("widget.unclear", "hinglish")
    finally:
        await r.client.aclose()


# ------------------------------------------------------------------ audio is never kept; logs have no speech or phone numbers
async def test_audio_is_never_written_to_disk_or_the_database_and_logs_are_pii_free(w, rig, monkeypatch, caplog):
    writes: list[str] = []
    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **k):  # noqa: ANN001, ANN002, ANN003
        if any(c in str(mode) for c in "wax+"):
            writes.append(str(file))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    for name in ("write_bytes", "write_text"):
        monkeypatch.setattr(Path, name, lambda self, *a, _n=name, **k: writes.append(f"{_n}:{self}"))
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda *a, **k: writes.append("tempfile"))
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: writes.append("mkstemp"))
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda *a, **k: writes.append("tempfile"))
    caplog.set_level(logging.DEBUG)

    audio = b"madad karo, mera number 9800000102 hai"
    r = await rig.client.post("/robin/device/voice", content=audio, headers={**rig.h(), "Content-Type": "audio/ogg", "X-Duration-S": "3"})
    assert r.status_code == 200
    assert writes == []
    for kind in ("audit", "pending", "incident", "intro"):
        for rec in await w.store.list(rig.fam.id, kind):
            blob = json.dumps(rec.data, default=str).encode()
            assert audio not in blob and b"madad karo" not in blob.lower().replace(b"reply", b"")
    text = caplog.text.lower()
    assert "madad karo" not in text and "9800000102" not in text and PARENT_PHONE not in text and PARENT_PHONE[3:] not in text
    state = rig.service.store.peek(rig.parent.id)
    assert audio not in json.dumps(vars(state), default=str).encode()  # not in the device state either


# ------------------------------------------------------------------ SOS from the button, with and without location
async def test_sos_button_with_location_only_with_consent(w, rig):
    r = await rig.client.post("/robin/device/sos", headers=rig.h(), json={"lat": 28.6, "lon": 77.2})
    assert r.status_code == 200
    inc = (await rig.incidents())[-1]
    assert inc.data["location"] is None  # no `location` consent: dropped
    await w.hub.fam.give_consent(rig.parent.id, "location", ConsentSource.ADMIN_CHAT)
    w.go(minutes=10)  # a new 5-minute bucket: a new incident
    r = await rig.client.post("/robin/device/sos", headers=rig.h(), json={"lat": 28.6, "lon": 77.2})
    assert r.status_code == 200
    located = [i for i in await rig.incidents() if i.data["location"]]
    assert len(located) == 1 and located[0].data["location"] == [28.6, 77.2]


async def test_sos_button_with_location_while_paused_keeps_the_consented_location(w, rig):
    await w.hub.fam.give_consent(rig.parent.id, "location", ConsentSource.ADMIN_CHAT)
    await w.hub.fam.pause(rig.parent.id, "voice")
    r = await rig.client.post("/robin/device/sos", headers=rig.h(), json={"lat": 28.6, "lon": 77.2})
    assert r.status_code == 200
    assert [i.data["location"] for i in await rig.incidents()] == [[28.6, 77.2]]


# ------------------------------------------------------------------ the optional LLM second opinion
async def test_llm_port_is_off_by_default_and_can_only_raise(w, container):
    r = await build(w, container)
    try:
        assert "llm" not in r.ports and r.service.llm is None
    finally:
        await r.client.aclose()
    r = await build(w, container, llm_switch=True)
    try:
        llm = r.ports["llm"]
        assert r.service.llm is llm
        from friday.robindevice import scamcheck

        class Lower:  # a model that tries to LOWER a rule verdict
            async def complete(self, **kw: Any) -> Any:  # noqa: ANN401
                return SimpleNamespace(text=json.dumps({"verdict": "NO_SIGNS_FOUND"}))

        class Raise:
            async def complete(self, **kw: Any) -> Any:  # noqa: ANN401
                return SimpleNamespace(text=json.dumps({"verdict": "SCAM_LIKELY"}))

        risky = "Dear customer your KYC will expire today, click http://bit.ly/x1 and share the OTP now"
        base = scamcheck.check_rules("text", risky, "en").verdict
        assert (await scamcheck.check("text", risky, lang="en", llm=Lower())).verdict == base  # never lower
        calm = "Beta shaam ko chai peene aa jana"
        assert (await scamcheck.check("text", calm, lang="en", llm=Raise())).verdict in ("RISKY", "NO_SIGNS_FOUND", "UNSURE")
        assert (await scamcheck.check("text", calm, lang="en", llm=Raise())).verdict != "SCAM_LIKELY"  # a model alone is capped at RISKY
    finally:
        await r.client.aclose()


def test_the_switch_defaults_off(settings):
    assert settings.robin_device_scam_llm_enabled is False
