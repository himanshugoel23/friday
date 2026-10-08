"""Onboarding through the real pipeline: consent gate, PIN, language, optional circle/places."""

from __future__ import annotations

from friday.core.models import ConsentKind, Language, UserStatus
from tests.e2e.conftest import RAHUL
from tests.e2e.harness import PIN


async def test_full_onboarding_consent_pin_language(friday):
    u = friday.person(RAHUL)
    await u.say("hi")
    await u.say("Rahul")
    await u.say("Bengaluru")
    await u.say("Hinglish")
    await u.say("casual")
    row = await u.user_row()
    assert row.status == UserStatus.ONBOARDING  # nothing is stored/consented yet
    consent_ask = u.last()
    assert "AI" in consent_ask and "delete everything" in consent_ask.lower()
    assert not await friday.c.repos.consents.has(row.id, ConsentKind.TERMS_PRIVACY)

    await u.say("I agree")
    assert await friday.c.repos.consents.has(row.id, ConsentKind.TERMS_PRIVACY)
    assert "PIN" in u.last()

    await u.say(PIN)
    await u.say(PIN)
    assert "PIN saved" in u.last()
    await u.say("skip")  # circle
    await u.say("skip")  # places
    await u.say("later")  # first task
    row = await u.user_row()
    assert row.status == UserStatus.ACTIVE
    profile = await friday.c.repos.profiles.get(row.id)
    assert profile.name == "Rahul" and profile.city == "Bengaluru"
    assert profile.language == Language.HINGLISH
    # the PIN is never echoed back and never stored in clear
    assert all(PIN not in t for t in u.texts())
    assert PIN not in (row.pin_hash or "")


async def test_consent_refusal_blocks_everything(friday):
    u = friday.person(RAHUL)
    for line in ["hi", "Rahul", "Bengaluru", "Hinglish", "casual"]:
        await u.say(line)
    await u.say("Not now")
    row = await u.user_row()
    assert row.status == UserStatus.ONBOARDING
    assert not await friday.c.repos.consents.has(row.id, ConsentKind.TERMS_PRIVACY)
    assert "PIN" not in u.last()
    # still no way around it: a task request does not create a task before consent
    await u.say("Looks Unisex Salon mein haircut book karo")
    assert await u.tasks() == []
    assert (await u.user_row()).status == UserStatus.ONBOARDING


async def test_pin_mismatch_and_weak_pin_are_rejected(friday):
    u = friday.person(RAHUL)
    for line in ["hi", "Rahul", "Bengaluru", "Hinglish", "casual", "I agree"]:
        await u.say(line)
    await u.say("1234")  # trivially weak
    row = await u.user_row()
    assert not row.pin_hash
    await u.say("4826")
    await u.say("4827")  # mismatch
    row = await u.user_row()
    assert row.status == UserStatus.ONBOARDING and not row.pin_hash
    await u.say("4826")
    await u.say("4826")
    assert (await u.user_row()).pin_hash


async def test_optional_circle_and_places_are_saved(friday):
    u = friday.person(RAHUL)
    for line in ["hi", "Rahul", "Bengaluru", "Hinglish", "casual", "I agree", PIN, PIN]:
        await u.say(line)
    await u.say("mere papa Suresh, +91 98111 11111, Hindi, Delhi")
    await u.say("home: Indiranagar, office: Bellandur")
    await u.say("later")
    row = await u.user_row()
    assert row.status == UserStatus.ACTIVE
    people = await friday.c.repos.people.list_for_owner(row.id)
    assert any(p.name == "Suresh" and p.phone == "+919811111111" for p in people), people
    places = await friday.c.repos.places.list_for_owner(row.id)
    assert {p.label.lower() for p in places} >= {"home", "office"}, places
    # circle members are NOT messaged without their own opt-in
    assert friday.channel.messages_to("+919811111111") == []
