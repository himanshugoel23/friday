"""The Devanagari switch inside the real inbound pipeline (simulated WhatsApp, fakes only)."""

from __future__ import annotations

from friday.core.models import Direction


async def test_switch_off_devanagari_reaches_the_brain_untouched(media_world) -> None:
    w = await media_world()
    assert w.c.settings.devanagari_input is False
    assert w.c.get("notifier").outbound_hook is None
    await w.say("कल 2 बजे इंटरव्यू है")
    assert w.brain.seen[-1] == "कल 2 बजे इंटरव्यू है"
    assert "interview" not in w.all_out().lower()  # nothing was captured


async def test_switch_on_an_event_in_devanagari_is_captured(media_world) -> None:
    w = await media_world(devanagari_input=True)
    out = await w.say("कल 2 बजे इंटरव्यू है")
    assert w.brain.seen == []  # the life-state capture took it, like "kal 2 baje interview hai"
    assert out
    events = await w.consumer.life.store.events_between(w.user.id, w.at(0), w.at(23, day=31))
    assert len(events) == 1


async def test_switch_on_matches_the_roman_message_reply_for_reply(media_world) -> None:
    deva = await media_world(devanagari_input=True)
    roman = await media_world()
    a = await deva.say("कल 2 बजे interview है")
    b = await roman.say("kal 2 baje interview hai")
    assert [m.text for m in a] == [m.text for m in b]
    assert [m.buttons for m in a] == [m.buttons for m in b]


async def test_switch_on_card_question_and_wallet(media_world) -> None:
    w = await media_world(devanagari_input=True)
    out = await w.say("मेरे पास एचडीएफसी रीगालिया है")
    assert w.brain.seen == [] and out
    assert "hdfc" in w.all_out().lower()
    out2 = await w.say("कौन सा कार्ड ज़ोमैटो पर 640")
    assert w.brain.seen == [] and out2


async def test_switch_on_memory_and_mute_words(media_world) -> None:
    w = await media_world(devanagari_input=True)
    await w.say("कल 2 बजे इंटरव्यू है")
    out = await w.say("तुम्हें क्या याद है")
    assert out and w.brain.seen == []
    out = await w.say("मत पूछो")
    assert out and w.brain.seen == []


async def test_the_log_keeps_what_the_user_wrote(media_world) -> None:
    w = await media_world(devanagari_input=True)
    await w.say("कल 2 बजे इंटरव्यू है")
    log = await w.c.repos.messages.list_for_user(w.user.id)
    inbound = [m for m in log if m.direction == Direction.INBOUND]
    assert inbound[-1].text == "कल 2 बजे इंटरव्यू है"


async def test_unmatched_devanagari_reaches_the_brain_as_roman(media_world) -> None:
    w = await media_world(devanagari_input=True)
    await w.say("मौसम कैसा है")
    assert w.brain.seen[-1] == "mausam kaisa hai"


async def test_devanagari_digits_in_a_bill_reach_the_savings_engine_as_ascii(media_world) -> None:
    w = await media_world(devanagari_input=True)
    await w.say("बिजली का बिल १५ तारीख को")
    assert w.brain.seen == []  # a bill with a due day, understood by the savings engine
