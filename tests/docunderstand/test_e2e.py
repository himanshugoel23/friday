"""A photo or PDF in the whole simulated world (fakes only): switch, hook, buttons, bills."""

from __future__ import annotations

from friday.chatbot_media.wiring import build_docs
from friday.core.config import Settings
from friday.core.models import Channel, InboundMessage, MessageKind
from friday.docunderstand import copy
from friday.docunderstand.ports import FakeVision
from tests.docunderstand import samples as S


def attach_fake(w, vision=None):  # noqa: ANN001, ANN201
    vision = vision or FakeVision()
    w.runtime.pipeline._docs_in = build_docs(w.c, w.runtime.pipeline, vision=vision)  # noqa: SLF001
    return vision


async def send_file(w, payload: dict, mime: str = "image/jpeg", caption: str | None = None):  # noqa: ANN001, ANN201
    media = w.channel.put_media(S.sample(payload, mime), mime, "file")
    kind = MessageKind.DOCUMENT if mime == "application/pdf" else MessageKind.IMAGE
    before = len(w.channel.messages_to(w.phone))
    await w.runtime.handle(
        InboundMessage(
            channel=Channel.SIMULATOR,
            from_phone=w.phone,
            kind=kind,
            media_url=media,
            media_mime=mime,
            text=caption,
        )  # fmt: skip
    )
    return w.channel.messages_to(w.phone)[before:]


def test_the_switch_defaults_to_off():
    s = Settings(_env_file=None)
    assert s.docs_enabled is False and s.docs_vision_provider == "none"
    assert s.docs_enabled_users == []


async def test_switch_off_nothing_is_read_and_no_doc_buttons(media_world) -> None:
    w = await media_world()
    assert w.runtime.pipeline._docs_hook() is None  # noqa: SLF001
    out = await send_file(w, S.FLIGHT)
    assert not any(b.id.startswith("doc:") for m in out for b in m.buttons)
    assert await w.c.repos.documents.latest_open(w.user.id) is None


async def test_switch_on_a_photo_is_read_and_confirmed(media_world) -> None:
    w = await media_world(docs_enabled=True)
    vision = attach_fake(w)
    out = await send_file(w, S.FLIGHT)
    assert len(vision.calls) == 1
    assert len(out) == 1 and out[0].text.startswith("Yeh flight ticket lag raha hai:")
    assert [b.title for b in out[0].buttons] == ["Haan, sahi hai", "Galat hai", "Rehne do"]
    assert w.brain.seen == []  # a document never reaches the brain
    assert await w.c.repos.documents.list_confirmed(w.user.id) == []
    done = await w.tap("sahi hai")
    assert [m.text for m in done] == [copy.t("saved", "hinglish")]
    (doc,) = await w.c.repos.documents.list_confirmed(w.user.id)
    assert doc.values()["flight_no"] == "6E 123"
    assert w.brain.seen == []


async def test_fix_by_typing_then_confirm(media_world) -> None:
    w = await media_world(docs_enabled=True)
    attach_fake(w)
    await send_file(w, S.HOTEL, "application/pdf")
    ask = await w.tap("galat")
    assert "naam: sahi value" in ask[0].text
    shown = await w.say("hotel: Test Palms Beach Resort")
    assert "Test Palms Beach Resort" in shown[0].text
    await w.tap("sahi hai")
    (doc,) = await w.c.repos.documents.list_confirmed(w.user.id)
    assert doc.values()["property_name"] == "Test Palms Beach Resort"


async def test_a_bill_becomes_a_tracked_bill_only_after_confirmation(media_world) -> None:
    w = await media_world(docs_enabled=True)
    attach_fake(w)
    bills = w.consumer.savings.bills
    await send_file(w, S.BILL)
    assert await bills.list_for_user(w.user.id) == []
    done = await w.tap("sahi hai")
    assert done[0].text == copy.t("saved.bill", "hinglish")
    (bill,) = await bills.list_for_user(w.user.id)
    assert bill.amount_paise == 124000 and bill.due_date.isoformat() == "2026-12-25"
    assert bill.confirmed and bill.biller == "Test Power Ltd"


async def test_aadhaar_photo_is_refused_and_nothing_is_stored(media_world) -> None:
    w = await media_world(docs_enabled=True)
    attach_fake(w)
    out = await send_file(w, S.AADHAAR)
    assert out[0].text == copy.t("refuse.gov_id", "hinglish")
    assert await w.c.repos.documents.latest_open(w.user.id) is None


async def test_default_provider_says_cannot_read_files(media_world) -> None:
    w = await media_world(docs_enabled=True)  # provider "none": no attach_fake
    out = await send_file(w, S.FLIGHT)
    assert out[0].text == copy.t("refuse.unavailable", "hinglish")


async def test_typed_text_still_goes_to_the_normal_flow(media_world) -> None:
    plain = await media_world()
    on = await media_world(docs_enabled=True)
    attach_fake(on)
    a = await plain.say("kal 2 baje interview hai")
    b = await on.say("kal 2 baje interview hai")
    assert [(m.text, m.buttons) for m in a] == [(m.text, m.buttons) for m in b]


async def test_user_allow_list_leaves_other_users_on_the_old_path(media_world) -> None:
    w = await media_world(docs_enabled=True, docs_enabled_users=["someone-else"])
    vision = attach_fake(w)
    out = await send_file(w, S.FLIGHT)
    assert vision.calls == [] and not any(b.id.startswith("doc:") for m in out for b in m.buttons)
