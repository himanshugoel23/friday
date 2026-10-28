# ruff: noqa: E501
"""Friday Web channel: pipeline wiring, identity, tokens, no Meta send, limits, consent, PWA, admin."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from friday.api.app import create_app
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.models import Channel, OutboundMessage, ReplyButton
from friday.pause import set_paused
from friday.webchat.channel import WebChannel
from friday.webchat.config import WebConfig
from friday.webchat.guard import GuardedTelephony
from tests.webchat.conftest import ADMIN_TOKEN, FOUNDER, OUTSIDER, WIFE, make_web


# ------------------------------------------------------------------ off by default / refusals
def test_switch_is_off_by_default_and_changes_nothing(wired, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert WebConfig(_env_file=None).channel_enabled is False
    app = create_app(wired, background=False, fast_pin_hash=True, web_config=WebConfig(_env_file=None))
    with TestClient(app) as client:
        assert client.get("/web/anything-at-all-0123456789/").status_code == 404
    assert isinstance(wired.messaging, SimulatorChannel)


def test_refuses_without_pilot_profile(wired, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wired.settings.profile = "default"
    cfg = WebConfig(_env_file=None, channel_enabled=True, dir=str(tmp_path / "web"))
    app = create_app(wired, background=False, fast_pin_hash=True, web_config=cfg)
    with TestClient(app) as client:
        assert client.get("/web/x/").status_code == 404
    assert isinstance(wired.messaging, SimulatorChannel)  # nothing was swapped


def test_refuses_a_redirect_that_is_not_allow_listed(wired, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wired.settings.profile = "pilot"
    wired.settings.pilot_allowed_numbers = [FOUNDER]
    wired.settings.vendor_call_redirect_to = OUTSIDER
    cfg = WebConfig(_env_file=None, channel_enabled=True, dir=str(tmp_path / "web"))
    create_app(wired, background=False, fast_pin_hash=True, web_config=cfg)
    assert isinstance(wired.messaging, SimulatorChannel)


# ------------------------------------------------------------------ identity and tokens
def test_invite_needs_an_allow_listed_number(web):
    from friday.webchat.registry import InviteRefused

    with pytest.raises(InviteRefused):
        web.registry.invite("Stranger", OUTSIDER, allowed={FOUNDER, WIFE})
    t, _ = web.registry.invite("Wife", WIFE, allowed={FOUNDER, WIFE})  # FRIDAY_CHATBOT_TESTERS counts
    assert t.phone == WIFE


def test_token_required_on_every_call(web):
    bad = "x" * 32
    for method, path in (
        ("get", "/config"), ("get", "/state"), ("post", "/consent"), ("post", "/send"),
        ("post", "/tap"), ("post", "/location"), ("post", "/voice-note"), ("post", "/file"),
        ("post", "/feedback"), ("get", "/media/web-media:1"),
    ):
        r = getattr(web.client, method)(web.url(path, bad))
        assert r.status_code == 404, path
    for path in ("/", "/manifest.webmanifest", "/sw.js", "/icon-192.png"):
        assert web.client.get(f"/web/{bad}{path}").status_code == 404, path
        assert web.client.get(f"/web/{web.token}{path}").status_code == 200, path


def test_expired_and_revoked_links_are_404(web, wired):
    assert web.client.get(web.url("/state")).status_code == 200
    wired.clock.advance(days=31)
    assert web.client.get(web.url("/state")).status_code == 404  # expired
    wired.clock.advance(days=-31)
    assert web.client.get(web.url("/state")).status_code == 200
    web.registry.revoke(web.tester.id)
    assert web.client.get(web.url("/state")).status_code == 404  # revoked


def test_number_removed_from_allow_list_stops_the_link(web, wired):
    wired.settings.pilot_allowed_numbers = []
    wired.settings.chatbot_testers = []
    assert web.client.get(web.url("/state")).status_code == 404


def test_one_tester_never_sees_anothers_chat(web, wired):
    web.consent()
    web.say("hello")
    _, tok2 = web.registry.invite("Wife", WIFE, allowed={FOUNDER, WIFE}, now=wired.clock.now())
    assert web.client.post(web.url("/consent", tok2)).status_code == 200
    assert web.client.get(web.url("/state", tok2)).json()["entries"] == []


# ------------------------------------------------------------------ consent
def test_consent_first_one_line(web):
    cfg = web.client.get(web.url("/config")).json()
    assert cfg["consent"]["required"] is True
    assert cfg["consent"]["text"] == "AI assistant, test mode. Calls go only to your own number."
    r = web.client.post(web.url("/send"), json={"phone": "me", "text": "hi"})
    assert r.status_code == 403
    web.consent()
    assert web.client.get(web.url("/config")).json()["consent"]["required"] is False


# ------------------------------------------------------------------ the real pipeline behind it
def test_message_goes_through_the_inbound_pipeline_and_reply_arrives(web, brain):
    web.consent()
    snap = web.say("hello")
    outs = [e for e in snap["entries"] if e["dir"] == "out"]
    assert [e["text"] for e in outs] == ["ask name"]  # the same onboarding the WhatsApp path gives
    assert snap["entries"][0]["dir"] == "in" and snap["entries"][0]["status"] == "read"
    snap = web.say("Rahul")
    assert [e["text"] for e in snap["entries"] if e["dir"] == "out"][-1] == "city?"
    assert brain.seen[:2] == [None, "Rahul"] or "Rahul" in brain.seen


async def test_same_dedupe_as_the_webhook(web):
    from friday.core.models import InboundMessage

    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=FOUNDER, text="hi", provider_message_id="web.in.dupe")
    rt = web.app.state.web.runtime
    assert await rt.accept_inbound(msg) is True
    assert await rt.accept_inbound(msg.model_copy()) is False


def test_outbound_goes_through_the_notifier_that_logs_whatsapp_messages(web, wired):
    # every reply is sent by Notifier.send -> _deliver -> _log(messages repo), exactly as for WhatsApp;
    # the web channel is only the transport underneath it
    assert wired.notifier.messaging is wired.messaging
    assert isinstance(wired.notifier.messaging, WebChannel)
    web.consent()
    web.say("hello")
    assert wired.messaging.sent_count == 1


def test_buttons_and_lists_round_trip(web, wired):
    import asyncio

    from friday.core.models import ListMenu, ListRow

    web.consent()
    ch = wired.messaging
    msg = OutboundMessage(
        channel=Channel.WHATSAPP, to_phone=FOUNDER, text="Pick one",
        buttons=[ReplyButton(id="b1", title="Yes"), ReplyButton(id="b2", title="No")],
    )
    lst = OutboundMessage(
        channel=Channel.WHATSAPP, to_phone=FOUNDER, text="Menu",
        list_menu=ListMenu(button="Open", rows=[ListRow(id="r1", title="One")]),
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ch.send(msg))
        loop.run_until_complete(ch.send(lst))
    finally:
        loop.close()
    entries = web.client.get(web.url("/state")).json()["entries"]
    assert entries[0]["buttons"][0] == {"id": "b1", "title": "Yes"}
    assert entries[1]["list"]["sections"][0]["items"][0]["id"] == "r1"
    r = web.client.post(web.url("/tap"), json={"message_id": msg.id, "button_id": "nope"})
    assert r.status_code == 422
    r = web.client.post(web.url("/tap"), json={"message_id": msg.id, "button_id": "b1"})
    assert r.status_code == 200
    assert any(e["dir"] == "in" and e["button_id"] == "b1" for e in r.json()["entries"])
    r = web.client.post(web.url("/tap"), json={"message_id": lst.id, "button_id": "r1"})
    assert r.status_code == 200


def test_voice_note_upload_goes_through_the_speech_path(web, brain):
    web.consent()
    web.say("hello")  # starts onboarding
    r = web.client.post(web.url("/voice-note"), files={"file": ("v", b"my name is Asha", "audio/webm;codecs=opus")})
    assert r.status_code == 200, r.text
    assert "my name is Asha" in brain.seen  # StubSTT decoded the stored upload via the channel's fetch_media
    bad = web.client.post(web.url("/voice-note"), files={"file": ("v", b"x", "text/plain")})
    assert bad.status_code == 415


def test_document_and_photo_upload(web):
    web.consent()
    ok = web.client.post(web.url("/file"), files={"file": ("bill.pdf", b"%PDF-1.4", "application/pdf")})
    assert ok.status_code == 200
    assert web.client.post(web.url("/file"), files={"file": ("a.exe", b"MZ", "application/x-msdownload")}).status_code == 415
    assert web.client.post(web.url("/location"), json={"lat": 28.4, "lng": 77.0}).status_code == 200
    assert web.client.post(web.url("/location"), json={"lat": 128.4, "lng": 77.0}).status_code == 422


# ------------------------------------------------------------------ no Meta / WhatsApp send
def test_channel_swapped_in_and_no_http_possible(web, wired, monkeypatch):
    assert isinstance(wired.messaging, WebChannel) and isinstance(wired.sms, FakeSMS)
    import sys

    src = open(sys.modules[WebChannel.__module__].__file__, encoding="utf-8").read()
    assert "httpx" not in src and "graph.facebook" not in src and "whatsapp import" not in src

    def boom(*a, **k):
        raise AssertionError("a network request was made")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    web.consent()
    web.say("hello")
    web.say("Rahul")


async def test_web_channel_refuses_non_testers(web, wired):
    ch = wired.messaging
    r = await ch.send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=OUTSIDER, text="hi"))
    assert r.ok is False and r.error == "web_channel_testers_only"
    r = await ch.send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=WIFE, text="hi"))
    assert r.ok is False  # in the allow-list but no invite yet
    r = await ch.send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=FOUNDER, text="hi"))
    assert r.ok is True


# ------------------------------------------------------------------ kill switch, rate limit
def test_kill_switch_stops_messages(web, wired):
    web.consent()
    set_paused(wired.settings, True)
    assert web.client.post(web.url("/send"), json={"text": "hi"}).status_code == 503
    set_paused(wired.settings, False)
    assert web.client.post(web.url("/send"), json={"text": "hi"}).status_code == 200


def test_rate_limit_per_tester(wired, tmp_path, monkeypatch):
    w = make_web(wired, tmp_path, monkeypatch, messages_per_min=2)
    try:
        w.consent()
        codes = [w.client.post(w.url("/send"), json={"text": f"m{i}"}).status_code for i in range(3)]
        assert codes == [200, 200, 429]
    finally:
        w.client.__exit__(None, None, None)


# ------------------------------------------------------------------ calls only to the tester's own number
class FakeTel:
    name = "fake"

    def __init__(self):
        self.placed = []

    async def place_call(self, request):
        self.placed.append(request)
        return "leg"

    def capabilities(self):
        return frozenset({"outbound"})


def _req(to, secs=120, task="t1"):
    from friday.core.models import OutboundCallRequest

    return OutboundCallRequest(to_phone=to, task_id=task, max_duration_s=secs)


def _guarded(web, requester=None):
    inner = FakeTel()
    return inner, GuardedTelephony(inner, web.app.state.web.guard, requester)


async def test_calls_only_to_a_testers_own_number(web):
    inner, g = _guarded(web)
    assert await g.place_call(_req(FOUNDER)) == "leg"
    for other in (OUTSIDER, WIFE, "+911112223334"):  # a business, a not-invited allow-listed number, anyone
        with pytest.raises(Exception, match="not dialled"):
            await g.place_call(_req(other))
    assert [r.to_phone for r in inner.placed] == [FOUNDER]
    assert g.capabilities() == frozenset({"outbound"})  # delegation


async def test_vendor_call_is_rewritten_to_the_requesters_own_phone(web, wired):
    _, tok = web.registry.invite("Wife", WIFE, allowed={FOUNDER, WIFE}, now=wired.clock.now())
    wife = web.registry.by_phone(WIFE)

    async def requester(req):
        return wife

    inner, g = _guarded(web, requester)
    await g.place_call(_req("+911234500000"))  # a real business number
    assert [r.to_phone for r in inner.placed] == [WIFE]


async def test_kill_switch_blocks_calls(web, wired):
    inner, g = _guarded(web)
    set_paused(wired.settings, True)
    with pytest.raises(Exception, match="kill switch"):
        await g.place_call(_req(FOUNDER))
    assert inner.placed == []


async def test_call_and_spend_caps(wired, tmp_path, monkeypatch):
    w = make_web(wired, tmp_path, monkeypatch, max_calls_per_day=2)
    try:
        inner, g = _guarded(w)
        await g.place_call(_req(FOUNDER))
        await g.place_call(_req(FOUNDER))
        with pytest.raises(Exception, match="cap"):
            await g.place_call(_req(FOUNDER))
        assert len(inner.placed) == 2
    finally:
        w.client.__exit__(None, None, None)
    w2 = make_web(wired, tmp_path / "b", monkeypatch, max_spend_inr=1.0)
    try:
        inner, g = _guarded(w2)
        with pytest.raises(Exception, match="spend"):
            await g.place_call(_req(FOUNDER, secs=180))
    finally:
        w2.client.__exit__(None, None, None)
    w3 = make_web(wired, tmp_path / "c", monkeypatch, global_max_spend_inr=1.0)
    try:
        inner, g = _guarded(w3)
        with pytest.raises(Exception, match="all-testers"):
            await g.place_call(_req(FOUNDER))
    finally:
        w3.client.__exit__(None, None, None)


async def test_caps_default_to_unlimited(web):
    assert (web.cfg.max_calls_per_day, web.cfg.max_spend_inr, web.cfg.global_max_spend_inr) == (0, 0, 0)
    inner, g = _guarded(web)
    for _ in range(30):
        await g.place_call(_req(FOUNDER))
    assert len(inner.placed) == 30


async def test_call_length_is_clamped(web):
    inner, g = _guarded(web)
    await g.place_call(_req(FOUNDER, secs=900))
    assert inner.placed[0].max_duration_s == web.cfg.max_call_seconds


def test_telephony_component_is_guarded(web, wired):
    assert isinstance(wired.telephony, GuardedTelephony)


# ------------------------------------------------------------------ page, PWA, feedback, admin
STRINGS_NEVER_IN_THE_DEFAULT_PAGE = ("SIMULATOR", "Fake WhatsApp", "fake calls", "Fake clock", "Switches", "devbar", "webstatus", "<!--DEV-->")


def test_default_page_has_no_banner_or_extra_text(web):
    html = web.client.get(f"/web/{web.token}/").text
    for s in STRINGS_NEVER_IN_THE_DEFAULT_PAGE:
        assert s not in html, s
    assert f"/web/{web.token}/api" in html and "__API_BASE__" not in html
    assert 'rel="manifest"' in html and "apple-touch-icon" in html and "serviceWorker" in html
    assert 'name="viewport"' in html and "viewport-fit=cover" in html


def test_dev_flag_adds_only_a_tiny_status_line(web):
    html = web.client.get(f"/web/{web.token}/?dev=1").text
    assert 'id="webstatus"' in html and "Founder" in html and FOUNDER not in html
    for s in ("SIMULATOR", "Fake clock", "Switches", 'id="side"'):
        assert s not in html


def test_headers_noindex_and_manifest_and_icons(web):
    r = web.client.get(f"/web/{web.token}/")
    assert "noindex" in r.headers["x-robots-tag"] and r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    m = web.client.get(f"/web/{web.token}/manifest.webmanifest").json()
    assert m["display"] == "standalone" and m["start_url"] == f"/web/{web.token}/"
    for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        body = web.client.get(f"/web/{web.token}/{name}").content
        assert body.startswith(b"\x89PNG")
    p = web.client.get("/web/privacy")
    assert p.status_code == 200 and "noindex" in p.text and "noindex" in p.headers["x-robots-tag"]


def test_the_phone_number_is_only_ever_shown_masked(web):
    cfg = web.client.get(web.url("/config")).text
    state = web.client.get(web.url("/state")).text
    assert FOUNDER not in cfg + state and FOUNDER[-2:] in cfg


def test_feedback_is_stored_for_the_admin_view(web):
    web.consent()
    snap = web.say("hello")
    mid = next(e["id"] for e in snap["entries"] if e["dir"] == "out")
    assert web.client.post(web.url("/feedback"), json={"message_id": mid, "kind": "wrong", "note": "too slow"}).status_code == 200
    assert web.client.post(web.url("/feedback"), json={"message_id": mid, "kind": "bogus"}).status_code == 422
    assert web.client.post(web.url("/feedback"), json={"message_id": "nope", "kind": "up"}).status_code == 422
    fb = web.registry.feedback()
    assert fb[-1]["kind"] == "wrong" and fb[-1]["tester"] == "Founder" and fb[-1]["note"] == "too slow"
    ov = web.client.get(f"/web/admin/{ADMIN_TOKEN}/api/overview").json()
    assert ov["feedback"][0]["kind"] == "wrong" and ov["caps"]["calls_per_day"] == "unlimited"
    assert web.client.get(web.url("/state")).json()["entries"][-1]["mark"] == "wrong"


def test_admin_page_needs_its_own_token(web, wired, tmp_path, monkeypatch):
    assert web.client.get(f"/web/admin/{ADMIN_TOKEN}/").status_code == 200
    assert web.client.get("/web/admin/wrong-token-0123456789/").status_code == 404
    assert web.client.get(f"/web/admin/{web.token}/api/overview").status_code == 404  # a tester token is not admin
    r = web.client.post(f"/web/admin/{ADMIN_TOKEN}/api/invite", json={"name": "Wife", "phone": WIFE})
    assert r.status_code == 200 and "/web/" in r.json()["link"] and FOUNDER not in r.text
    r = web.client.post(f"/web/admin/{ADMIN_TOKEN}/api/invite", json={"name": "X", "phone": OUTSIDER})
    assert r.status_code == 422
    assert web.client.post(f"/web/admin/{ADMIN_TOKEN}/api/revoke", json={"ref": "Wife"}).status_code == 200
    assert web.registry.by_phone(WIFE) is None


def test_admin_page_is_off_without_a_token(wired, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wired.settings.profile = "pilot"
    wired.settings.pilot_allowed_numbers = [FOUNDER]
    cfg = WebConfig(_env_file=None, channel_enabled=True, dir=str(tmp_path / "web"))
    app = create_app(wired, background=False, fast_pin_hash=True, web_config=cfg)
    with TestClient(app) as client:
        assert client.get("/web/admin/anything-0123456789abc/").status_code == 404


def test_guarded_telephony_still_exposes_the_provider_to_the_voice_webhooks():
    # Regression: Vobiz got 404 on /voice/sarvam/answer because the guard wrapper hid SarvamTelephony.
    from friday.webchat.guard import GuardedTelephony

    class Provider:
        pass

    class Other:
        pass

    inner = Provider()
    wrapped = GuardedTelephony(inner, guard=None)  # type: ignore[arg-type]
    assert wrapped.find(Provider) is inner
    assert wrapped.find(Other) is None
