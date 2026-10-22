"""First run: intro, consent, name, language, city, one first win; resumable, skippable, gated."""

from __future__ import annotations

import pytest
from sqlalchemy import text as sql

from friday.chatbot import copy
from friday.chatbot.composer import has_full_statement, has_statement
from friday.core.models import ConsentKind, Language, UserStatus
from tests.chatbot.conftest import FOUNDER, STRANGER, TESTER, TESTER2


async def count(chat, table: str) -> int:
    async with chat.c.repos.db.session() as s:
        return int((await s.execute(sql(f"select count(*) from {table}"))).scalar_one())


# ---------------------------------------------------------------- the intro
async def test_hi_from_a_tester_gets_one_intro_with_three_consent_buttons(chat):
    out = await chat.say("hi")
    assert len(out) == 1
    m = out[0]
    assert [b.title for b in m.buttons] == ["Haan, theek hai", "Details", "Nahi"]
    assert [b.id for b in m.buttons] == ["cb:consent:yes", "cb:consent:details", "cb:consent:no"]
    assert has_full_statement(m.text or "") == []  # assistant, never payments/OTP/PIN, own data
    assert "AI assistant" in (m.text or "")


async def test_nothing_about_the_person_is_stored_before_they_agree(chat):
    await chat.say("hi")
    assert await chat.user() is None
    assert await count(chat, "users") == 0
    assert await count(chat, "messages") == 0  # the intro and their "hi" are not logged
    assert await count(chat, "profiles") == 0
    # the only trace is the step they are on, keyed by a hash of the number
    async with chat.c.repos.db.session() as s:
        cols = (await s.execute(sql("select * from chatbot_sessions"))).keys()
        assert "phone" not in set(cols)
    assert await chat.c.repos.chatbot.count_sessions() == {"consent": 1}


async def test_details_explains_and_asks_again(chat):
    await chat.say("hi")
    out = await chat.tap("Details")
    assert len(out) == 1 and has_statement(out[0].text or "") == []
    assert [b.title for b in out[0].buttons] == ["Haan, theek hai", "Nahi"]
    assert await chat.user() is None


async def test_a_message_that_is_not_an_answer_gets_a_short_reprompt_not_the_intro_again(chat):
    first = (await chat.say("hi"))[0]
    out = await chat.say("kuch bhi")
    assert len(out) == 1
    assert out[0].text != first.text  # never the same message twice in a row
    assert [b.title for b in out[0].buttons] == ["Haan, theek hai", "Details", "Nahi"]


# ---------------------------------------------------------------- consent
async def test_agreeing_creates_the_user_and_an_auditable_consent_record(chat):
    await chat.say("hi")
    out = await chat.tap("Haan")
    user = await chat.user()
    assert user is not None and user.status == UserStatus.ACTIVE
    consents = await chat.c.repos.consents.list_for_user(user.id)
    assert len(consents) == 1
    c = consents[0]
    assert c.kind == ConsentKind.TERMS_PRIVACY and c.granted is True
    assert c.policy_version == copy.WORDING_VERSION  # the wording version
    assert "lang=hinglish" in (c.evidence_text or "")  # the language
    assert f"wording={copy.WORDING_VERSION}" in (c.evidence_text or "")
    assert c.recorded_at == chat.clock.now()  # the timestamp
    assert (await chat.c.repos.profiles.get_or_default(user.id)).language == Language.HINGLISH
    audit = await chat.c.repos.audit.list_for_user(user.id, limit=20)
    assert "consent.granted" in {a.action for a in audit}
    assert out[0].buttons[0].title == "Skip" and "bulaun" in (
        out[0].text or ""
    )  # asks the name next


async def test_typing_haan_also_agrees(chat):
    await chat.say("namaste")
    await chat.say("haan theek hai")
    assert await chat.user() is not None
    assert (await chat.c.repos.consents.list_for_user((await chat.user()).id))[0].granted


async def test_nahi_ends_politely_and_stores_nothing_but_the_refusal(chat):
    await chat.say("hi")
    out = await chat.tap("Nahi")
    assert len(out) == 1 and not out[0].buttons
    assert await chat.user() is None
    for table in ("users", "profiles", "consents", "messages", "people", "places"):
        assert await count(chat, table) == 0, table
    assert await chat.c.repos.chatbot.count_sessions() == {"refused": 1}
    # a message right after the refusal is not answered; a greeting starts again
    assert await chat.say("ok bye") == []
    again = await chat.say("hi")
    assert len(again) == 1 and again[0].buttons[0].title == "Haan, theek hai"


async def test_after_the_cool_down_any_message_starts_again(chat):
    await chat.say("hi")
    await chat.tap("Nahi")
    chat.clock.advance(hours=2)
    out = await chat.say("kuch poochna tha")
    assert len(out) == 1 and out[0].buttons[0].title == "Haan, theek hai"


async def test_a_stale_consent_button_from_an_existing_user_is_ignored_quietly(chat):
    await chat.onboard()
    before = len(chat.channel.messages_to(TESTER))
    out = await chat.tap_id("cb:consent:details")
    assert len(out) == 1 and len(chat.channel.messages_to(TESTER)) == before + 1
    assert chat.brain.seen == [] or chat.brain.seen[-1] != "cb:consent:details"


# ---------------------------------------------------------------- the steps
async def test_the_whole_flow_with_a_first_win(make_chat):
    chat = await make_chat(savings_enabled=True, lifestate_enabled=True)
    try:
        await chat.say("hi")
        await chat.tap("Haan")
        out = await chat.say("mera naam Rahul hai")
        assert "Rahul" in (out[0].text or "")
        assert [b.title for b in out[0].buttons] == ["Hinglish", "हिंदी", "English"]
        out = await chat.tap("Hinglish")
        assert "shehar" in (out[0].text or "")
        out = await chat.say("Pune")
        assert "Pune" in (out[0].text or "")
        assert [b.title for b in out[0].buttons] == ["Card jodo", "Mera din"]  # calls are off
        out = await chat.tap("Card jodo")
        assert "HDFC" in (out[0].text or "")
        assert has_statement(out[-1].text or "") == []  # the closing message restates the rules
        user = await chat.user()
        profile = await chat.c.repos.profiles.get_or_default(user.id)
        assert (profile.name, profile.city) == ("Rahul", "Pune")
        assert await chat.c.repos.chatbot.count_sessions() == {"done": 1}
    finally:
        await chat.c.aclose()


async def test_every_step_message_obeys_the_chat_rules(make_chat):
    chat = await make_chat(
        savings_enabled=True, lifestate_enabled=True, consumer_calls_enabled=True
    )
    try:
        await chat.onboard()
        await chat.tap("Kisi ko call")
        for m in chat.channel.messages_to(TESTER):
            assert len(m.buttons) <= 3 and all(len(b.title) <= 20 for b in m.buttons)
            assert (m.text or "").count("?") <= 1
            assert len((m.text or "").split("\n")) <= 7
        texts = chat.texts()
        assert all(a != b for a, b in zip(texts, texts[1:], strict=False))  # no repeat in a row
    finally:
        await chat.c.aclose()


async def test_skipping_every_step_still_finishes(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    await chat.tap("Skip")  # name
    await chat.say("skip")  # language (typed)
    await chat.say("baad mein")  # city
    assert await chat.c.repos.chatbot.count_sessions() == {"done": 1}
    profile = await chat.c.repos.chatbot.session_for_user((await chat.user()).id)
    assert profile is not None and profile.step == "done"


async def test_the_language_choice_changes_every_later_message(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    await chat.say("Asha")
    out = await chat.tap("हिंदी")
    assert "हिंदी" in (out[0].text or "") and "शहर" in (out[0].text or "")
    user = await chat.user()
    assert (await chat.c.repos.profiles.get_or_default(user.id)).language == Language.HI
    out = await chat.say("menu")
    assert "AI असिस्टेंट" in (out[0].text or "")


async def test_the_first_message_sets_the_language_to_mirror(chat):
    out = await chat.say("Hello, can you help me with my bills please", TESTER)
    assert "I'm Friday" in (out[0].text or "")
    out = await chat.say("मुझे मदद चाहिए", TESTER2)
    assert "मैं Friday" in (out[0].text or "")
    out = await chat.say("hi", "+919811100005")  # not a tester: waitlist, still mirrored
    assert out and "Friday" in (out[0].text or "")


async def test_hinglish_is_the_default_when_the_first_message_says_nothing(chat):
    out = await chat.say("hi")
    assert "Namaste" in (out[0].text or "")


async def test_an_answer_that_is_not_a_name_is_asked_again_then_skipped(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    out = await chat.say("hello")
    assert "Naam samajh nahi aaya" in (out[0].text or "")
    out = await chat.say("12345")  # second miss: skip the step, move on
    assert any("bhasha" in (m.text or "") for m in out)
    s = await chat.c.repos.chatbot.session_for_user((await chat.user()).id)
    assert s is not None and s.step == "language"


async def test_a_real_request_in_the_middle_is_answered_not_swallowed(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    await chat.say("mummy ko call karo ki main late hoon")
    assert chat.brain.seen[-1] == "mummy ko call karo ki main late hoon"  # the old flows got it
    s = await chat.c.repos.chatbot.session_for_user((await chat.user()).id)
    assert s is not None and s.step == "name"  # the question is still open


async def test_a_typed_request_at_the_last_step_finishes_onboarding_and_passes_through(make_chat):
    chat = await make_chat(savings_enabled=True)
    try:
        await chat.onboard()
        await chat.say("papa ko batana ki shaam ko aaunga")
        assert chat.brain.seen[-1] == "papa ko batana ki shaam ko aaunga"
        s = await chat.c.repos.chatbot.session_for_user((await chat.user()).id)
        assert s is not None and s.step == "done"
    finally:
        await chat.c.aclose()


async def test_the_optional_footer_repeats_the_statement_on_each_step(make_chat):
    chat = await make_chat(chatbot_disclosure_every_step=True)
    try:
        await chat.say("hi")
        out = await chat.tap("Haan")
        assert has_statement(out[0].text or "") == []
    finally:
        await chat.c.aclose()


# ---------------------------------------------------------------- resumable
async def test_the_flow_survives_a_restart_and_resumes_where_it_stopped(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    await chat.say("Rahul")  # now at the language question
    from friday.api.inbound import InboundPipeline

    chat.pipeline = InboundPipeline(chat.c, fast_pin_hash=True)  # a fresh process: no memory
    out = await chat.tap("Hinglish")
    assert "shehar" in (out[0].text or "")


async def test_coming_back_later_says_welcome_back_and_asks_the_same_question(chat):
    await chat.say("hi")
    await chat.tap("Haan")
    await chat.say("Rahul")
    chat.clock.advance(hours=30)
    out = await chat.say("hello")
    assert len(out) == 1
    text = out[0].text or ""
    assert "Wapas aaye" in text and "bhasha" in text
    assert [b.title for b in out[0].buttons] == ["Hinglish", "हिंदी", "English"]


async def test_coming_back_before_consent_shows_the_consent_question_again(chat):
    await chat.say("hi")
    chat.clock.advance(days=3)
    out = await chat.say("hello")
    assert len(out) == 1 and [b.title for b in out[0].buttons][0] == "Haan, theek hai"
    assert await chat.user() is None


# ---------------------------------------------------------------- the pilot gate
async def test_a_stranger_is_waitlisted_with_one_polite_reply_and_a_hash_only(chat):
    out = await chat.say("hi", STRANGER)
    assert len(out) == 1 and "waitlist" in (out[0].text or "")
    assert has_statement(out[0].text or "") == []
    assert await chat.say("hello?", STRANGER) == []  # silence after the one reply
    assert await chat.c.repos.chatbot.waitlist_count() == 1
    assert await chat.c.repos.chatbot.waitlist_has(STRANGER)
    assert await chat.user(STRANGER) is None
    assert await count(chat, "users") == 0 and await count(chat, "messages") == 0
    async with chat.c.repos.db.session() as s:
        rows = (await s.execute(sql("select * from chatbot_waitlist"))).mappings().all()
    assert len(rows) == 1 and STRANGER not in str(dict(rows[0])) and rows[0]["hits"] == 2
    assert await chat.c.repos.chatbot.count_sessions() == {}


async def test_a_waitlisted_number_cannot_agree_its_way_in(chat):
    await chat.say("hi", STRANGER)
    await chat.say("haan theek hai", STRANGER)
    assert await chat.user(STRANGER) is None


async def test_the_allow_list_is_pilot_numbers_testers_and_admins(make_chat):
    chat = await make_chat(
        pilot_allowed_numbers=[TESTER], chatbot_testers=[TESTER2], admin_phones=[FOUNDER]
    )
    try:
        for phone in (TESTER, TESTER2, FOUNDER):
            out = await chat.say("hi", phone)
            assert out[0].buttons[0].title == "Haan, theek hai", phone
        out = await chat.say("hi", STRANGER)
        assert "waitlist" in (out[0].text or "")
    finally:
        await chat.c.aclose()


async def test_with_the_pilot_off_and_invite_only_on_the_invite_code_flow_runs_as_before(make_chat):
    chat = await make_chat(pilot=False, invite_only=True)
    try:
        out = await chat.say("hi", STRANGER)
        assert "invite" in (out[0].text or "").lower()
        assert await chat.c.repos.chatbot.count_sessions() == {}
    finally:
        await chat.c.aclose()


async def test_with_the_pilot_off_and_open_sign_up_anyone_gets_the_intro(make_chat):
    chat = await make_chat(pilot=False, invite_only=False)
    try:
        out = await chat.say("hi", STRANGER)
        assert out[0].buttons[0].title == "Haan, theek hai"
    finally:
        await chat.c.aclose()


async def test_with_the_switch_off_nothing_changes_for_a_stranger(make_chat):
    chat = await make_chat(chatbot_onboarding=False, pilot=False, invite_only=True)
    try:
        assert chat.pipeline.chatbot is None
        out = await chat.say("hi", STRANGER)
        assert "invite" in (out[0].text or "").lower()
        assert "cb:consent" not in str([b.id for m in out for b in m.buttons])
    finally:
        await chat.c.aclose()


async def test_a_user_who_deleted_everything_can_start_again(chat):
    await chat.onboard()
    await chat.say("delete everything")
    await chat.say("DELETE")
    assert await chat.user() is None
    out = await chat.say("hi")
    assert out[-1].buttons[0].title == "Haan, theek hai"


@pytest.mark.parametrize("switch", [False, True])
async def test_the_chatbot_component_exists_only_when_switched_on(make_chat, switch):
    chat = await make_chat(chatbot_onboarding=switch)
    try:
        assert (chat.pipeline.chatbot is not None) is switch
    finally:
        await chat.c.aclose()
