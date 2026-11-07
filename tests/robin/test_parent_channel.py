# ruff: noqa: E501
"""T07: the parent's WhatsApp channel and inbound route. Tested with FAKES only (fake WhatsApp, fake TTS/STT/converter): nothing real is
sent, and the real Meta send has not been exercised. Phones are invented."""

from __future__ import annotations

import builtins
import json
import logging
from types import SimpleNamespace

import pytest

from friday.chatbot_media.convert import FakeConverter
from friday.core.models import Channel, InboundMessage, Language, MediaBlob, MessageKind
from friday.robin import wiring
from friday.robin.channel import (
    TEMPLATE_MESSAGE,
    TEMPLATE_REOPEN,
    TEMPLATES,
    FakeWhatsApp,
    MemoryWindow,
    ParentInbound,
    WhatsAppParentChannel,
)
from friday.voice.stt.fake import FakeSTT
from friday.voice.tts.fake import build_fake_tts
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE

STRANGER = "+919800000199"  # invented


@pytest.fixture
async def ch(w, container):
    """A REAL WhatsAppParentChannel + ParentInbound over fakes, installed on the hub (replacing the recording fake)."""
    wa, tts, conv, window = FakeWhatsApp(), build_fake_tts(container), FakeConverter(), MemoryWindow()
    stt = FakeSTT()
    channel = WhatsAppParentChannel(wa, tts=lambda: tts, converter=conv, clock=w.clock, window=window)
    w.ctx.parent_channel = channel
    w.hub.parent_route = ParentInbound(w.hub, messaging=lambda: wa, stt=lambda: stt)
    return SimpleNamespace(wa=wa, tts=tts, conv=conv, window=window, channel=channel, stt=stt, w=w)


def voice(ch, words: str, mid: str = "m1", frm: str = PARENT_PHONE, media: str = "MEDIA1") -> InboundMessage:
    ch.wa.media[media] = MediaBlob(data=words.encode(), mime="audio/ogg")  # the fake STT reads the words from the bytes
    return InboundMessage(channel=Channel.WHATSAPP, from_phone=frm, kind=MessageKind.VOICE_NOTE, media_url=media, provider_message_id=mid)


def text_msg(words: str, mid: str = "t1", frm: str = PARENT_PHONE, kind: MessageKind = MessageKind.TEXT) -> InboundMessage:
    return InboundMessage(channel=Channel.WHATSAPP, from_phone=frm, kind=kind, text=words, provider_message_id=mid)


async def parent_of(w):
    fam, parent = await w.family(notified=False)
    return fam, parent


# ============================================================================ outbound
async def test_voice_note_in_window_is_tts_upload_send_audio(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    assert await ch.channel.send_voice_note(parent, "Namaste Papa", "hinglish") is True
    assert ch.tts.calls[0][0] == "Namaste Papa" and ch.tts.calls[0][1] == Language.HINGLISH
    (data, mime), = ch.wa.uploads
    assert data.startswith(b"OggS") and mime == "audio/ogg; codecs=opus"
    assert ch.wa.audios == [(PARENT_PHONE, "FAKEMEDIA1")] and ch.wa.sent == []


async def test_voice_is_spoken_in_the_parents_language(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    await ch.channel.send_voice_note(parent, "नमस्ते", "hi")
    await ch.channel.send_voice_note(parent, "Hello", "en")
    assert [c[1] for c in ch.tts.calls] == [Language.HI, Language.EN]


async def test_outside_the_24h_window_the_template_is_used_once_for_voice_plus_text(w, ch):
    fam, parent = await parent_of(w)  # nothing inbound yet: window closed
    assert await ch.channel.send_voice_note(parent, "Namaste Papa", "hinglish") is True
    assert await ch.channel.send_text(parent, "Namaste Papa") is True  # the same line as text: not a second template
    assert ch.wa.audios == [] and ch.wa.uploads == [] and ch.tts.calls == []
    (m,) = ch.wa.sent
    assert m.template is not None and m.template.key == TEMPLATE_MESSAGE and m.template.params == ["Namaste Papa"] and m.text is None
    assert m.to_phone == PARENT_PHONE and m.template.language == "en"


async def test_window_closes_after_24_hours_and_opens_on_inbound(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    assert await ch.channel.in_window(PARENT_PHONE)
    w.go(hours=23)
    assert await ch.channel.in_window(PARENT_PHONE)
    w.go(hours=2)
    assert not await ch.channel.in_window(PARENT_PHONE)
    await ch.channel.send_text(parent, "Ek line")
    assert ch.wa.sent[-1].template is not None
    await ch.channel.note_inbound(PARENT_PHONE)
    await ch.channel.send_text(parent, "Doosri line")
    assert ch.wa.sent[-1].template is None and ch.wa.sent[-1].text == "Doosri line"


async def test_meta_window_error_falls_back_to_the_template(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    ch.wa.send_error = "131047: re-engagement message"
    assert await ch.channel.send_text(parent, "Ek line") is False  # the template is also rejected by this fake: False, not an exception
    ch.wa.send_error = None
    ch.wa.sent.clear()
    # first call rejected with 131047, then the template goes through
    calls = {"n": 0}
    real = ch.wa.send

    async def flaky(msg):
        calls["n"] += 1
        if calls["n"] == 1:
            ch.wa.send_error = "131047: re-engagement message"
        else:
            ch.wa.send_error = None
        return await real(msg)

    ch.wa.send = flaky
    assert await ch.channel.send_text(parent, "Teesri line") is True
    assert ch.wa.sent[-1].template is not None and ch.wa.sent[-1].template.params == ["Teesri line"]


async def test_reopen_template_parameters(w, ch):
    fam, parent = await parent_of(w)
    assert await ch.channel.reopen(parent, "Papa", "Asha") is True
    t = ch.wa.sent[-1].template
    assert t.key == TEMPLATE_REOPEN and t.params == ["Papa", "Asha"]
    assert len(TEMPLATES[TEMPLATE_REOPEN]) == 2 and len(TEMPLATES[TEMPLATE_MESSAGE]) == 1


async def test_unknown_template_name_is_refused(w, ch):
    fam, parent = await parent_of(w)
    assert await ch.channel.send_template(parent, "not_registered", {"x": "y"}) is False
    assert ch.wa.sent == []


async def test_send_failure_returns_false_never_raises(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    ch.wa.fail_send = True
    assert await ch.channel.send_text(parent, "x") is False
    assert await ch.channel.send_voice_note(parent, "x", "en") is False
    ch.wa.fail_send, ch.wa.fail_upload = False, True
    assert await ch.channel.send_voice_note(parent, "x", "en") is False


async def test_no_tts_or_no_ffmpeg_means_no_voice_note(w, ch):
    fam, parent = await parent_of(w)
    await ch.channel.note_inbound(PARENT_PHONE)
    ch.conv.present = False
    assert await ch.channel.send_voice_note(parent, "x", "en") is False
    ch.conv.present = True
    ch.channel._tts = lambda: None
    assert await ch.channel.send_voice_note(parent, "x", "en") is False


async def test_send_failure_falls_to_the_outbox_and_is_not_lost(w, ch):
    fam, parent = await w.family(notified=False)
    ch.wa.fail_send = True
    assert await w.hub.intro.notify_parent(fam) is True
    pending = await w.store.list(fam.id, "pending")
    assert len(pending) == 1 and pending[0].status == "queued" and pending[0].data["purpose"] == "notify"  # waits in the app outbox for the T08 drain


# ============================================================================ inbound
async def test_unknown_number_is_not_a_parent(w, ch):
    await parent_of(w)
    assert await w.hub.parent_inbound(text_msg("stop", frm=STRANGER)) is False
    assert await w.hub.parent_inbound(voice(ch, "Robin band karo", frm=STRANGER)) is False
    assert ch.wa.deleted == [] and ch.wa.sent == [] and ch.wa.audios == []
    assert (await w.store.get_member((await w.hub.parent(await w.hub.family(w.child_user.id))).id)).paused is False


async def test_the_childs_own_number_is_not_a_parent(w, ch):
    await parent_of(w)
    assert await w.hub.parent_inbound(text_msg("stop", frm=CHILD_PHONE)) is False


async def test_voice_note_band_karo_pauses_the_family_and_the_audio_is_not_retained(w, ch, monkeypatch, caplog):
    fam, parent = await parent_of(w)
    writes: list[str] = []
    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **k):  # noqa: ANN001, ANN002, ANN003
        if any(c in str(mode) for c in "wax+"):
            writes.append(str(file))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    from pathlib import Path

    for name in ("write_bytes", "write_text"):
        monkeypatch.setattr(Path, name, lambda self, *a, _n=name, **k: writes.append(f"{_n}:{self}"))
    import tempfile

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda *a, **k: writes.append("tempfile"))
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: writes.append("mkstemp"))
    caplog.set_level(logging.DEBUG, logger="friday")

    assert await w.hub.parent_inbound(voice(ch, "Robin band karo")) is True

    assert (await w.store.get_member(parent.id)).paused is True  # "Robin band karo" paused the family
    assert ch.wa.deleted == ["MEDIA1"]  # the provider's copy is deleted too
    assert writes == []  # no file was written while the audio was in our hands
    audio = b"Robin band karo"
    for kind in ("audit", "pending", "incident", "intro"):  # nothing in the database holds the audio or the words
        for r in await w.store.list(fam.id, kind):
            assert audio not in json.dumps(r.data, default=str).encode()
    assert "band karo" not in caplog.text.lower() and PARENT_PHONE not in caplog.text and PARENT_PHONE[3:] not in caplog.text
    assert ch.wa.audios  # and the parent got the 'paused' acknowledgement as a voice note, in their language
    assert ch.tts.calls and "ruk gayi" in ch.tts.calls[-1][0]


async def test_audio_bytes_are_not_kept_on_the_route_object(w, ch):
    await parent_of(w)
    await w.hub.parent_inbound(voice(ch, "madad karo"))
    route = w.hub.parent_route
    assert not any(isinstance(v, (bytes, bytearray, MediaBlob)) for v in vars(route).values())


async def test_provider_retry_is_handled_once(w, ch):
    fam, parent = await parent_of(w)
    from friday.core.scale import MemoryCache

    cache = MemoryCache(w.clock)
    w.hub.parent_route.cache = lambda: cache
    await w.hub.parent_inbound(voice(ch, "madad karo", mid="same"))
    sos1 = len(await w.store.list(fam.id, "incident"))
    await w.hub.parent_inbound(voice(ch, "madad karo", mid="same"))
    assert len(await w.store.list(fam.id, "incident")) == sos1 >= 1


async def test_typed_stop_still_stops(w, ch):
    fam, parent = await parent_of(w)
    assert await w.hub.parent_inbound(text_msg("stop")) is True
    assert (await w.store.get_member(parent.id)).paused is True


async def test_help_in_a_voice_note_raises_the_sos(w, ch):
    fam, parent = await parent_of(w)
    await w.hub.parent_inbound(voice(ch, "madad karo"))
    assert any(r.kind == "incident" for r in [*await w.store.list(fam.id, "incident")])


class RecordingIntake:
    def __init__(self, say: str | None = None) -> None:
        self.seen: list[tuple[str, str | None]] = []
        self.say = say

    async def handle(self, *, family, parent, msg, text):  # noqa: ANN001
        self.seen.append((msg.kind.value, text))
        return self.say


async def test_text_and_forwarded_content_go_to_the_t13_stub_not_the_assistant(w, ch):
    fam, parent = await parent_of(w)
    intake = RecordingIntake()
    w.hub.parent_route.scam = intake
    brain_calls: list[object] = []

    async def no_chat(*a, **k):  # noqa: ANN002, ANN003
        brain_calls.append(1)
        return False

    w.hub.handle = no_chat  # the child's chat entry: must never be used for a parent
    await w.hub.parent_inbound(text_msg("Congratulations you won a lottery click http://x.example", mid="a"))
    await w.hub.parent_inbound(InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.IMAGE, media_url="IMG1", provider_message_id="b"))
    assert [k for k, _ in intake.seen] == ["text", "image"] and brain_calls == []
    assert not (await w.store.get_member(parent.id)).paused


async def test_a_plain_greeting_gets_the_short_hello_and_stores_nothing(w, ch):
    fam, parent = await parent_of(w)  # T13 replaced the stub: real content is judged (tests/robin/test_scam_forward.py), a greeting is not
    await w.hub.parent_inbound(text_msg("hello namaste", mid="c"))
    assert ch.tts.calls and "Robin" in ch.tts.calls[-1][0]  # the existing PENDING 'inbound.hello' line, brand via {brand}
    assert "namaste" not in json.dumps([r.data for k in ("audit", "pending", "incident") for r in await w.store.list(fam.id, k)], default=str)


async def test_unreadable_voice_note_gets_hello_never_silence(w, ch):
    fam, parent = await parent_of(w)
    msg = voice(ch, "", media="EMPTY")
    await w.hub.parent_inbound(msg)
    assert ch.tts.calls and ch.wa.deleted == ["EMPTY"]


async def test_no_channel_configured_reply_waits_in_the_outbox(w):
    fam, parent = await parent_of(w)
    w.ctx.parent_channel = None
    wa = FakeWhatsApp()
    wa.media["M"] = MediaBlob(data=b"kuch bhi", mime="audio/ogg")
    w.hub.parent_route = ParentInbound(w.hub, messaging=lambda: wa, stt=lambda: FakeSTT())
    await w.hub.parent_inbound(InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.VOICE_NOTE, media_url="M"))
    pending = await w.store.list(fam.id, "pending")
    assert len(pending) == 1 and pending[0].data["purpose"] == "reply"


# ============================================================================ care protocol on the parent's words
async def test_parent_distress_goes_to_the_care_path_and_the_child_is_told_with_consent(w, ch, caplog):
    fam, parent = await parent_of(w)
    caplog.set_level(logging.DEBUG, logger="friday")
    await w.hub.parent_inbound(voice(ch, "I want to die", mid="care1"))
    assert ch.tts.calls  # the care line (the care protocol's own copy) was spoken to the parent
    assert any("distress" in t.lower() or "pareshan" in t.lower() for t in w.sender.texts())  # the child was told, once consent allows
    assert any(r.data.get("event") == "parent_distress" for r in await w.store.list(fam.id, "audit"))
    assert "want to die" not in caplog.text.lower()
    assert "want to die" not in json.dumps([r.data for k in ("audit", "pending", "incident") for r in await w.store.list(fam.id, k)], default=str).lower()


async def test_parent_distress_without_sharing_consent_is_not_passed_on(w, ch):
    fam, parent = await parent_of(w)
    await w.hub.fam.withdraw_consent(parent.id, "share_summary_with_child", tell_child=False, actor="user", source="test")
    await w.hub.parent_inbound(voice(ch, "I want to die", mid="care2"))
    assert w.sender.texts() == []
    assert ch.tts.calls  # the parent still gets the care line


async def test_stop_wins_over_care(w, ch):
    fam, parent = await parent_of(w)
    await w.hub.parent_inbound(voice(ch, "band karo", mid="s1"))
    assert (await w.store.get_member(parent.id)).paused is True


# ============================================================================ wiring: ctx.parent_channel only when configured
def _container(*, switch: bool, cloud: bool, token: bool = True, pnid: bool = True):
    s = SimpleNamespace(
        robin_parent_whatsapp_enabled=switch, resolve_whatsapp=lambda: "cloud" if cloud else "simulator",
        whatsapp_access_token="x" if token else None, whatsapp_phone_number_id="123" if pnid else None, whatsapp_session_window_h=24,
    )
    wa = FakeWhatsApp()
    comps = {"messaging": wa, "cache": SimpleNamespace(), "tts": object()}
    return SimpleNamespace(settings=s, clock=None, get=lambda n: comps[n])


def test_parent_channel_is_built_only_when_the_switch_and_the_cloud_channel_are_configured():
    assert wiring.build_parent_channel(_container(switch=False, cloud=True)) is None  # switch default OFF
    assert wiring.build_parent_channel(_container(switch=True, cloud=False)) is None  # simulator / not configured
    assert wiring.build_parent_channel(_container(switch=True, cloud=True, token=False)) is None
    assert wiring.build_parent_channel(_container(switch=True, cloud=True, pnid=False)) is None
    assert isinstance(wiring.build_parent_channel(_container(switch=True, cloud=True)), WhatsAppParentChannel)


def test_switch_defaults_off(settings):
    assert settings.robin_parent_whatsapp_enabled is False


def test_template_names_are_documented():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "ROBIN_FAMILY_CORE.md").read_text()
    for name in TEMPLATES:
        assert name in doc
    assert "PENDING" in doc


async def test_delete_media_calls_the_graph_delete_endpoint():
    import httpx

    from friday.channels.whatsapp import WhatsAppCloudChannel

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"success": True})

    wa = WhatsAppCloudChannel(access_token="TOKEN", phone_number_id="PNID", transport=httpx.MockTransport(handler))
    assert await wa.delete_media("MEDIA9") is True
    assert await wa.delete_media("../bad id") is False  # never builds a path from garbage
    assert [r.method for r in seen] == ["DELETE"] and seen[0].url.path.endswith("/MEDIA9")
    await wa.aclose()
