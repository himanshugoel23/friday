# ruff: noqa: E501
"""T08: the parent's app outbox (``pending`` records, status ``queued``) drains through the parent channel exactly once: de-duplicated, the
24 h window re-opened first when it is closed, a failed send put back, a pause holds it. Plus the dedicated 'could not hear that' line.
Fakes only: nothing is sent."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from friday.chatbot_media.convert import FakeConverter
from friday.core.models import Channel, InboundMessage, MediaBlob, MessageKind
from friday.robin import lines
from friday.robin.channel import FakeWhatsApp, MemoryWindow, ParentInbound, WhatsAppParentChannel
from friday.robin.store import Record
from friday.voice.stt.fake import FakeSTT
from friday.voice.tts.fake import build_fake_tts
from tests.robin.conftest import PARENT_PHONE


async def queue(w, fam, parent, text, purpose="reply", at=None):
    rec = Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=at or w.clock.now(), data={"member_id": parent.id, "line": "x", "purpose": purpose, "text": text, "incident_id": None})
    out, _ = await w.store.put(rec)
    return out


async def statuses(w, fam):
    return sorted(r.status for r in await w.store.list(fam.id, "pending") if r.data.get("text") or r.status in ("sent", "queued"))


async def test_queued_lines_drain_once_and_only_once(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "line one")
    await queue(w, fam, parent, "line two")
    assert await w.hub.outbox.drain_member(fam, parent) == 2
    assert [t for _, t in w.channel.texts] == ["line one", "line two"]
    assert await w.hub.outbox.drain_member(fam, parent) == 0  # nothing left
    assert await w.hub.tick() >= 0
    assert [t for _, t in w.channel.texts].count("line one") == 1 and [t for _, t in w.channel.texts].count("line two") == 1  # the scheduler tick did not send them again (it only sent the monthly reminder)
    assert all(r.status == "sent" for r in await w.store.list(fam.id, "pending") if r.data.get("text"))


async def test_the_tick_drains_when_a_channel_exists_and_the_consent_notice_is_the_first_thing_sent(w):
    w.channel.fail = True  # setup happened while the parent's WhatsApp was down: the notice waits in the outbox
    fam, parent = await w.family(notified=True)
    queued = [r for r in await w.store.list(fam.id, "pending", status="queued") if r.data.get("purpose") == "notify"]
    assert len(queued) == 1
    w.channel.fail = False
    await w.hub.tick()
    assert any("set up" in t.lower() or "assistant" in t.lower() for _, t in w.channel.texts)
    assert not [r for r in await w.store.list(fam.id, "pending", status="queued") if r.data.get("purpose") == "notify"]


async def test_duplicate_lines_are_sent_once_and_a_line_already_delivered_is_not_repeated(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "same words")
    await queue(w, fam, parent, "same words")  # the same line queued twice in one batch
    await queue(w, fam, parent, "other words")
    assert await w.hub.outbox.drain_member(fam, parent) == 2
    assert [t for _, t in w.channel.texts] == ["same words", "other words"]
    st = [r.status for r in await w.store.list(fam.id, "pending") if r.data.get("member_id") == parent.id]
    assert sorted(st) == ["deduped", "sent", "sent"]
    w.go(minutes=20)
    await queue(w, fam, parent, "same words")  # delivered a moment ago
    assert await w.hub.outbox.drain_member(fam, parent) == 0
    assert [t for _, t in w.channel.texts].count("same words") == 1
    w.go(hours=3)
    await queue(w, fam, parent, "same words")  # hours later it is news again
    assert await w.hub.outbox.drain_member(fam, parent) == 1


async def test_a_line_the_device_already_took_is_not_sent_again(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "for the app")
    taken = await w.hub.fam.take_app_notifications(parent.id)  # the phone app pulled it first
    assert [n["text"] for n in taken] == ["for the app"]
    assert await w.hub.outbox.drain_member(fam, parent) == 0 and w.channel.texts == []


async def test_closed_window_reopens_first_then_the_queued_lines_follow(w):
    fam, parent = await w.family(notified=False)
    w.channel.window_open = False
    await queue(w, fam, parent, "first")
    await queue(w, fam, parent, "second")
    assert await w.hub.outbox.drain_member(fam, parent) == 2
    assert w.channel.log[0] == "reopen" and w.channel.reopens == [(parent.id, "Papa", "Asha")]  # the 'say anything' template goes before any line
    assert [t[2]["line"] for t in w.channel.templates if t[1] == "robin_parent_message"][:1] == ["first"]
    await queue(w, fam, parent, "third")
    w.go(hours=1)
    await w.hub.outbox.drain_member(fam, parent)
    assert len(w.channel.reopens) == 1  # not again within 12 hours
    w.go(hours=13)
    await queue(w, fam, parent, "fourth")
    await w.hub.outbox.drain_member(fam, parent)
    assert len(w.channel.reopens) == 2


async def test_open_window_needs_no_reopen(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "hello")
    await w.hub.outbox.drain_member(fam, parent)
    assert w.channel.reopens == [] and w.channel.log.count("reopen") == 0


async def test_a_failed_send_goes_back_to_queued_and_is_retried_in_order(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "one")
    await queue(w, fam, parent, "two")
    w.channel.fail = True
    assert await w.hub.outbox.drain_member(fam, parent) == 0
    assert [r.status for r in await w.store.list(fam.id, "pending")] == ["queued", "queued"]
    w.channel.fail = False
    assert await w.hub.outbox.drain_member(fam, parent) == 2
    assert [t for _, t in w.channel.texts] == ["one", "two"]


async def test_the_parents_pause_holds_the_outbox_and_stale_good_morning_expires(w):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "while paused")
    await w.hub.fam.pause(parent.id, "voice")
    assert await w.hub.outbox.tick() == 0 and w.channel.texts == []
    await w.hub.fam.resume(parent.id, "voice")
    await queue(w, fam, parent, "old good morning", purpose="good_morning", at=w.clock.now() - timedelta(days=3))
    parent = await w.store.get_member(parent.id)
    assert await w.hub.outbox.drain_member(fam, parent) == 1  # "while paused" goes now; the three-day-old good morning is dropped
    assert [t for _, t in w.channel.texts] == ["while paused"]
    assert "expired" in [r.status for r in await w.store.list(fam.id, "pending")]


async def test_no_channel_means_the_outbox_simply_waits(w):
    fam, parent = await w.family(notified=False)
    w.ctx.parent_channel = None
    await queue(w, fam, parent, "waits")
    assert await w.hub.outbox.tick() == 0
    assert [r.status for r in await w.store.list(fam.id, "pending") if r.data.get("text")] == ["queued"]


# ============================================================================ the parent writes: the window opens and the outbox drains
@pytest.fixture
async def real(w, container):
    wa, tts, window, stt = FakeWhatsApp(), build_fake_tts(container), MemoryWindow(), FakeSTT()
    channel = WhatsAppParentChannel(wa, tts=lambda: tts, converter=FakeConverter(), clock=w.clock, window=window)
    w.ctx.parent_channel = channel
    w.hub.parent_route = ParentInbound(w.hub, messaging=lambda: wa, stt=lambda: stt)
    return SimpleNamespace(wa=wa, channel=channel, w=w)


async def test_when_the_parent_writes_the_waiting_lines_follow_their_reply_exactly_once(w, real):
    fam, parent = await w.family(notified=False)
    await queue(w, fam, parent, "waiting line")
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.TEXT, text="hello", provider_message_id="m1")
    assert await w.hub.parent_inbound(msg) is True
    sent = [m.text for m in real.wa.sent]
    assert sent.count("waiting line") == 1
    msg2 = InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.TEXT, text="hello again", provider_message_id="m2")
    await w.hub.parent_inbound(msg2)
    assert [m.text for m in real.wa.sent].count("waiting line") == 1


# ============================================================================ 'could not hear that'
def test_the_unclear_line_is_pending_branded_and_in_three_languages():
    langs = lines.SPOKEN["inbound.unclear"]
    assert set(langs) == {"en", "hinglish", "hi"} and lines.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert all("{brand}" in t and "Robin" not in t for t in langs.values())
    assert "again" in langs["en"] and "could not hear" in langs["en"]
    assert "Robin" in lines.say("inbound.unclear", "en", brand="Robin", parent="Papa")


async def test_an_unreadable_voice_note_gets_the_could_not_hear_line_not_hello(w, real):
    fam, parent = await w.family(notified=False)
    real.wa.media["M1"] = MediaBlob(data=b"", mime="audio/ogg")  # the fake STT hears nothing
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.VOICE_NOTE, media_url="M1", provider_message_id="v1")
    assert await w.hub.parent_inbound(msg) is True
    expect = lines.say("inbound.unclear", parent.language, brand="Robin", **await w.ctx.slots(fam))
    assert expect in [m.text for m in real.wa.sent] and expect != lines.say("inbound.hello", parent.language, brand="Robin", **await w.ctx.slots(fam))
    assert not any("Say 'help'" in m.text or "madad chahiye" in m.text.lower() for m in real.wa.sent)  # hello was not used


async def test_the_unclear_line_waits_in_the_outbox_when_the_send_fails(w, real):
    fam, parent = await w.family(notified=False)
    real.wa.fail_send = True
    real.wa.media["M1"] = MediaBlob(data=b"", mime="audio/ogg")
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.VOICE_NOTE, media_url="M1", provider_message_id="v2")
    await w.hub.parent_inbound(msg)
    q = [r for r in await w.store.list(fam.id, "pending", status="queued") if r.data.get("member_id") == parent.id]
    assert [r.data["line"] for r in q] == ["inbound.unclear"]
