"""Contact cards, typed numbers, location pins."""

from __future__ import annotations

import pytest

from friday.calls.contacts import ContactBook
from friday.calls.numbers import NumberHasher
from friday.chatbot.commands import mask_last2, split_phone
from friday.core.models import LocationPin, MessageKind
from tests.chatbot.conftest import MUMMY, TESTER


@pytest.fixture
async def user_chat(chat):
    await chat.onboard()
    chat.channel.clear()
    return chat


def card(chat, name: str, number: str | None):
    msg = chat.channel.make_inbound(TESTER, "x")
    return msg.model_copy(
        update={"kind": MessageKind.CONTACT, "contact_phone": number, "text": name}
    )


def pin(chat, lat=18.52, lng=73.85, name=None):
    msg = chat.channel.make_inbound(TESTER, "x")
    return msg.model_copy(
        update={
            "kind": MessageKind.LOCATION,
            "location": LocationPin(lat=lat, lng=lng, name=name),
            "text": None,
        }
    )


async def book(chat) -> ContactBook:
    return ContactBook(chat.c.repos.consumer_contacts, NumberHasher(), chat.clock)


# ---------------------------------------------------------------- masking helper
def test_the_last_two_digits_are_masked():
    assert mask_last2("+919811100077") == "+91 98111 000XX"
    assert "77" not in mask_last2("+919811100077")


# ---------------------------------------------------------------- shared contact card
async def test_a_shared_card_asks_for_a_nickname_once_then_saves_and_confirms_masked(user_chat):
    out = await user_chat.send(card(user_chat, "Sunita Devi", MUMMY))
    assert len(out) == 1
    assert "Sunita Devi" in (out[0].text or "") and "bulaun" in (out[0].text or "")
    assert [b.title for b in out[0].buttons] == ["Mummy", "Papa", "Skip"]
    out = await user_chat.say("mummy")
    assert len(out) == 1
    text = out[0].text or ""
    assert "+91 98111 000XX" in text and MUMMY[-2:] not in text.replace("98111", "")
    found = await (await book(user_chat)).resolve((await user_chat.user()).id, "mummy")
    assert found.status == "found" and found.contact.name == "Sunita Devi"
    assert found.contact.relationship == "mother" and found.contact.number == MUMMY
    # a nickname is asked only once: the same card again just updates the entry
    await user_chat.send(card(user_chat, "Sunita Devi", MUMMY))
    await user_chat.say("mummy")
    assert (
        len(await user_chat.c.repos.consumer_contacts.list_for_user((await user_chat.user()).id))
        == 1
    )


async def test_tapping_a_nickname_button_works(user_chat):
    await user_chat.send(card(user_chat, "Ramesh", MUMMY))
    out = await user_chat.tap("Papa")
    assert "Papa" in (out[0].text or "")
    found = await (await book(user_chat)).resolve((await user_chat.user()).id, "papa")
    assert found.status == "found"


async def test_skipping_the_nickname_still_saves_the_contact_by_name(user_chat):
    await user_chat.send(card(user_chat, "Anil Kumar", MUMMY))
    out = await user_chat.tap("Skip")
    assert "Anil Kumar" in (out[0].text or "")
    assert (
        await (await book(user_chat)).resolve((await user_chat.user()).id, "anil")
    ).status == "found"


async def test_a_card_without_a_usable_number_is_refused_politely(user_chat):
    out = await user_chat.send(card(user_chat, "Nobody", None))
    assert "sahi nahi" in (out[0].text or "")
    out = await user_chat.send(card(user_chat, "Police", "+91112"))
    assert "112" in (out[0].text or "")
    assert (
        await user_chat.c.repos.consumer_contacts.list_for_user((await user_chat.user()).id) == []
    )


async def test_a_reply_that_is_not_a_nickname_drops_the_question_and_goes_on(user_chat):
    await user_chat.send(card(user_chat, "Ramesh", MUMMY))
    await user_chat.say("kal subah 9 baje meeting hai, yaad rakhna")
    assert user_chat.brain.seen[-1].startswith("kal subah 9 baje")
    assert (
        await user_chat.c.repos.consumer_contacts.list_for_user((await user_chat.user()).id) == []
    )


async def test_an_old_nickname_question_expires(user_chat):
    await user_chat.send(card(user_chat, "Ramesh", MUMMY))
    user_chat.clock.advance(hours=2)
    await user_chat.say("bhaiya")
    assert user_chat.brain.seen[-1] == "bhaiya"  # not taken as the nickname any more
    assert (
        await user_chat.c.repos.consumer_contacts.list_for_user((await user_chat.user()).id) == []
    )


# ---------------------------------------------------------------- typed numbers
@pytest.mark.parametrize(
    ("text", "number", "rest"),
    [
        ("9811100077", "9811100077", ""),
        ("98111 00077", "98111 00077", ""),
        ("+91 98111 00077", "+91 98111 00077", ""),
        ("mummy 9811100077", "9811100077", "mummy"),
        ("yeh papa ka number hai 9811100077", "9811100077", "papa"),
    ],
)
def test_split_phone_finds_a_number_with_an_optional_label(text, number, rest):
    assert split_phone(text) == (number, rest)


@pytest.mark.parametrize(
    "text",
    [
        "4111 1111 1111 1111",
        "12345",
        "kal 2 baje 9811100077 pe call karna wala hai kya",
        "OTP 123456",
    ],
)
def test_split_phone_ignores_cards_short_numbers_and_sentences(text):
    assert split_phone(text) is None


async def test_a_typed_number_is_accepted_and_confirmed_back(user_chat):
    out = await user_chat.say("98111 00077")
    assert "kiska" in (out[0].text or "")
    out = await user_chat.say("mummy")
    assert "+91 98111 000XX" in (out[0].text or "")
    found = await (await book(user_chat)).resolve((await user_chat.user()).id, "mummy")
    assert found.status == "found" and found.contact.number == MUMMY


async def test_a_number_with_its_label_is_saved_at_once(user_chat):
    out = await user_chat.say("bhaiya 9811100077")
    assert len(out) == 1 and "Bhaiya" in (out[0].text or "") and "XX" in (out[0].text or "")
    assert (
        await (await book(user_chat)).resolve((await user_chat.user()).id, "bhaiya")
    ).status == "found"


async def test_an_emergency_number_is_never_saved(user_chat):
    out = await user_chat.say("police 100")
    assert user_chat.brain.seen[-1] == "police 100"  # too short to be a phone number: brain
    out = await user_chat.send(card(user_chat, "Ambulance", "108"))
    assert "112" in (out[0].text or "")


async def test_a_card_number_typed_in_chat_is_not_treated_as_a_phone_number(user_chat):
    await user_chat.say("4111 1111 1111 1111")
    assert user_chat.brain.seen[-1] == "4111 1111 1111 1111"
    assert (
        await user_chat.c.repos.consumer_contacts.list_for_user((await user_chat.user()).id) == []
    )


async def test_contacts_belong_to_one_user_only(chat):
    from tests.chatbot.conftest import TESTER2

    await chat.onboard(phone=TESTER)
    await chat.onboard("Asha", phone=TESTER2)
    await chat.say("mummy 9811100077", TESTER)
    other = await chat.user(TESTER2)
    assert await chat.c.repos.consumer_contacts.list_for_user(other.id) == []


# ---------------------------------------------------------------- location pins
async def test_a_pin_asks_which_place_then_saves_it_for_vendor_search(user_chat):
    out = await user_chat.send(pin(user_chat))
    assert "kaunsi" in (out[0].text or "")
    assert [b.title for b in out[0].buttons] == ["Ghar", "Office", "Skip"]
    out = await user_chat.tap("Ghar")
    assert "Home" in (out[0].text or "") and "share nahi" in (out[0].text or "")
    places = await user_chat.c.repos.places.list_for_owner((await user_chat.user()).id)
    assert len(places) == 1
    p = places[0]
    assert p.label == "Home" and "ghar" in p.aliases and p.location is not None
    assert (round(p.location.lat, 2), round(p.location.lng, 2)) == (18.52, 73.85)
    assert p.ephemeral is False and p.owner_user_id == (await user_chat.user()).id


async def test_a_typed_place_name_is_saved_under_that_name(user_chat):
    await user_chat.send(pin(user_chat))
    await user_chat.say("mummy ka ghar")
    places = await user_chat.c.repos.places.list_for_owner((await user_chat.user()).id)
    assert [p.label for p in places] == ["Mummy Ka Ghar"]


async def test_skipping_the_place_question_saves_nothing(user_chat):
    await user_chat.send(pin(user_chat))
    out = await user_chat.tap("Skip")
    assert "save nahi" in (out[0].text or "")
    assert await user_chat.c.repos.places.list_for_owner((await user_chat.user()).id) == []


async def test_office_is_saved_as_office(user_chat):
    await user_chat.send(pin(user_chat))
    await user_chat.tap("Office")
    places = await user_chat.c.repos.places.list_for_owner((await user_chat.user()).id)
    assert [p.label for p in places] == ["Office"]


async def test_a_pin_during_onboarding_gives_the_city_and_then_the_next_step(make_chat):
    chat = await make_chat(savings_enabled=True)
    try:
        await chat.say("hi")
        await chat.tap("Haan")
        await chat.say("Rahul")
        await chat.tap("Hinglish")  # now asked for the city
        out = await chat.send(pin(chat))  # a pin instead of typing it
        assert "kaunsi" in (out[0].text or "")  # which place? (one question at a time)
        user = await chat.user()
        assert (await chat.c.repos.profiles.get_or_default(user.id)).city == "Bengaluru"
        out = await chat.tap("Ghar")
        assert "Home" in (out[0].text or "") and "try karein" in (out[0].text or "")
        assert [b.title for b in out[0].buttons] == ["Card jodo"]
        s = await chat.c.repos.chatbot.session_for_user(user.id)
        assert s is not None and s.step == "win" and s.pending_kind is None
    finally:
        await chat.c.aclose()


async def test_the_place_stays_private_to_its_owner(chat):
    from tests.chatbot.conftest import TESTER2

    await chat.onboard(phone=TESTER)
    await chat.onboard("Asha", phone=TESTER2)
    await chat.send(pin(chat))
    await chat.tap("Ghar")
    assert await chat.c.repos.places.list_for_owner((await chat.user(TESTER2)).id) == []
