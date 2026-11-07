# ruff: noqa: E501
"""T07: the pipeline's single early hook. A Robin PARENT's WhatsApp message goes to Robin's parent route (voice note -> STT -> ``parent_said``)
and NEVER to the general assistant, the Friday menu, onboarding or the chat log; every other number takes the old path. Real container +
InboundPipeline + RobinHub on SQLite with fakes (fake STT, simulator media, FakeParentChannel); nothing real is sent. Phones are invented."""

from __future__ import annotations

import pytest

from friday.core.models import InboundMessage, MessageKind
from tests.e2e.robin.harness import PARENT, PARENT_OTHER, RobinWorld

STRANGER_VOICE = "+919800000188"  # invented


@pytest.fixture
async def world():
    w = await RobinWorld.start()
    await w.setup_family()
    w.channel.voice_notes.clear()
    w.channel.texts.clear()
    yield w
    await w.close()


def _inbound(w: RobinWorld, phone: str, kind: MessageKind, *, text: str | None = None, media: str | None = None) -> InboundMessage:
    return InboundMessage(channel=w.f.channel.channel, from_phone=phone, kind=kind, text=text, media_url=media, provider_message_id=f"wa.{w.next_id()}.{phone[-4:]}", received_at=w.clock.now())


async def send(w: RobinWorld, msg: InboundMessage) -> None:
    w.clock.advance(seconds=15)
    await w.f.rt.handle(msg, raise_errors=True)
    await w.f.settle()


async def parent_voice(w: RobinWorld, words: str, phone: str = PARENT) -> None:
    media = w.f.channel.put_media(words.encode(), "audio/ogg")  # the fake STT reads the words from the bytes
    await send(w, _inbound(w, phone, MessageKind.VOICE_NOTE, media=media))


async def test_parent_voice_note_robin_band_karo_pauses_the_family(world):
    w = world
    await parent_voice(w, "Robin band karo")
    parent = await w.parent()
    assert parent.paused is True
    assert any("ruk gayi" in t for _, t, _ in w.channel.voice_notes)  # acknowledged as a voice note, in the parent's language


async def test_parent_never_reaches_the_general_assistant_or_the_menu(world):
    w = world
    sim = w.f.channel
    before = len(sim.messages_to(PARENT))
    await send(w, _inbound(w, PARENT, MessageKind.TEXT, text="what is the weather and show me the menu"))
    await send(w, _inbound(w, PARENT, MessageKind.IMAGE, media=sim.put_media(b"\x89PNG-fake", "image/png")))
    await parent_voice(w, "kuch aur poochna hai")
    assert len(sim.messages_to(PARENT)) == before  # the Friday channel sent the parent nothing (their replies go through Robin's parent channel)
    assert await w.f.c.repos.users.get_by_phone(PARENT) is None  # not onboarded, not a Friday user
    assert await w.f.c.repos.messages.last_inbound_from(PARENT) is None  # not in the chat log either
    assert w.channel.voice_notes, "the parent still gets Robin's short hello as a voice note"


async def test_unknown_number_takes_the_old_path_not_the_parent_route(world):
    w = world
    sim = w.f.channel
    media = sim.put_media(b"Robin band karo", "audio/ogg")
    await send(w, _inbound(w, STRANGER_VOICE, MessageKind.VOICE_NOTE, media=media))
    assert (await w.parent()).paused is False
    assert w.channel.voice_notes == [] and w.channel.texts == []
    assert sim.messages_to(STRANGER_VOICE), "an unknown sender still gets the normal onboarding answer"


async def test_second_phone_that_is_not_a_member_is_not_a_parent(world):
    w = world
    await send(w, _inbound(w, PARENT_OTHER, MessageKind.TEXT, text="stop"))
    assert (await w.parent()).paused is False


async def test_the_child_still_reaches_the_assistant_and_robin_commands(world):
    w = world
    out = await w.child_says("what is on")
    assert out, "the child's chat is unchanged"


async def test_typed_stop_from_the_parent_stops(world):
    w = world
    await send(w, _inbound(w, PARENT, MessageKind.TEXT, text="stop"))
    assert (await w.parent()).paused is True


async def test_parent_sos_by_voice_raises_the_alert_to_the_child(world):
    w = world
    await parent_voice(w, "madad karo")
    assert any(r.kind == "incident" for r in await w.store.list((await w.family()).id, "incident"))
    assert w.child_texts()


async def test_switches_off_build_no_parent_channel_and_route_still_protects(world):
    w = world
    assert w.settings.robin_parent_whatsapp_enabled is False
    assert w.hub.parent_route is not None
