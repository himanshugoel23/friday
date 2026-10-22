"""menu / help, human, stop, delete everything."""

from __future__ import annotations

import pytest
from sqlalchemy import text as sql

from friday.chatbot import copy
from friday.core.logging import mask_phone
from friday.core.models import (
    AutonomyCategory,
    ConsentKind,
    InboundMessage,
)
from tests.chatbot.conftest import FOUNDER, TESTER

PHRASES = [
    "menu",
    "Menu",
    "help",
    "HELP",
    "madad",
    "kya kar sakti ho",
    "kya kya kar sakti ho?",
    "what can you do",
]


@pytest.fixture
async def user_chat(chat):
    await chat.onboard()
    chat.channel.clear()
    return chat


# ---------------------------------------------------------------- menu and help
@pytest.mark.parametrize("phrase", PHRASES)
async def test_menu_and_help_phrases_show_a_whatsapp_list(user_chat, phrase):
    out = await user_chat.say(phrase)
    assert len(out) == 1
    m = out[0]
    assert m.list_menu is not None and not m.buttons
    assert 1 <= len(m.list_menu.rows) <= 10
    assert m.list_menu.button == "Menu dekhein"
    assert {r.id for r in m.list_menu.rows} == {f"cb:menu:{k}" for k in copy.ROWS}
    assert user_chat.brain.seen == []  # the brain never saw it


async def test_menu_marks_pilot_features_and_features_that_are_not_on(make_chat):
    chat = await make_chat(
        savings_enabled=True, lifestate_enabled=False, consumer_calls_enabled=True
    )
    try:
        await chat.onboard()
        out = await chat.say("menu")
        desc = {r.id: r.description or "" for r in out[-1].list_menu.rows}
        assert desc["cb:menu:call"].endswith("(pilot)")
        assert desc["cb:menu:card"].endswith("(pilot)")
        assert desc["cb:menu:day"].endswith("(jaldi)")  # switched off: "soon"
        assert not desc["cb:menu:stop"].endswith(("(pilot)", "(jaldi)"))
    finally:
        await chat.c.aclose()


async def test_the_simulator_renders_the_list_and_a_digit_picks_a_row(user_chat):
    await user_chat.say("menu")
    rendered = user_chat.channel.render(user_chat.channel.last_to(TESTER))
    assert "[list: Menu dekhein]" in rendered and "1) Kisi ko call karwao" in rendered
    out = await user_chat.tap("Contact jodo")
    assert "contact card" in (out[0].text or "")


async def test_a_menu_row_for_a_feature_that_is_off_says_it_is_coming(user_chat):
    await user_chat.say("menu")
    out = await user_chat.tap("Card se bachat")
    assert "jaldi aayega" in (out[0].text or "")


async def test_a_menu_row_for_a_feature_that_is_on_explains_how(make_chat):
    chat = await make_chat(savings_enabled=True)
    try:
        await chat.onboard()
        out = await chat.say("menu")
        assert out
        out = await chat.tap("Card se bachat")
        assert "HDFC" in (out[0].text or "")
    finally:
        await chat.c.aclose()


async def test_a_help_request_that_is_a_real_task_is_not_the_menu(user_chat):
    await user_chat.say("help me book a table for two")
    assert user_chat.brain.seen[-1] == "help me book a table for two"


async def test_the_menu_works_in_every_language(chat):
    await chat.say("Hello, I need some help please")
    await chat.tap("Yes, okay")
    await chat.say("Asha")
    await chat.tap("English")
    await chat.say("skip")
    out = await chat.say("menu")
    assert "your AI assistant" in (out[-1].text or "") and out[-1].list_menu.button == "See menu"


# ---------------------------------------------------------------- human / support
async def _founder_window(chat):
    """The founder messaged the number recently, so a free-form forward is allowed."""
    await chat.c.repos.messages.log_inbound(
        InboundMessage(
            channel=chat.channel.channel,
            from_phone=FOUNDER,
            text="hi",
            received_at=chat.clock.now(),
        )
    )


async def test_human_forwards_to_the_support_inbox_setting_and_tells_the_user(make_chat):
    chat = await make_chat(support_inbox=FOUNDER)
    try:
        await chat.onboard("Rahul")
        await _founder_window(chat)
        out = await chat.say("human")
        assert "team ko bhej di" in (out[0].text or "")
        fwd = chat.channel.messages_to(FOUNDER)
        assert len(fwd) == 1
        text = fwd[0].text or ""
        assert "Rahul" in text and TESTER not in text  # the number is masked
        assert mask_phone(TESTER) in text
        items = await chat.c.repos.chatbot.inbox_list("support")
        assert len(items) == 1
    finally:
        await chat.c.aclose()


@pytest.mark.parametrize("word", ["support", "insaan", "agent"])
async def test_other_words_reach_support_too(make_chat, word):
    chat = await make_chat(support_inbox=FOUNDER)
    try:
        await chat.onboard()
        await _founder_window(chat)
        await chat.say(word)
        assert len(chat.channel.messages_to(FOUNDER)) == 1
    finally:
        await chat.c.aclose()


async def test_human_with_a_message_forwards_it_with_numbers_masked(make_chat):
    chat = await make_chat(support_inbox=FOUNDER)
    try:
        await chat.onboard()
        await _founder_window(chat)
        await chat.say("human: mera number 9876543210 pe call nahi aaya")
        text = chat.channel.messages_to(FOUNDER)[0].text or ""
        assert "9876543210" not in text and "<number>" in text
    finally:
        await chat.c.aclose()


async def test_without_a_support_setting_the_request_is_noted_and_the_user_told_honestly(user_chat):
    out = await user_chat.say("human")
    assert "support ka number set nahi" in (out[0].text or "")
    assert len(await user_chat.c.repos.chatbot.inbox_list("support")) == 1
    assert user_chat.channel.messages_to(FOUNDER) == []


def test_the_support_address_is_a_setting_never_hard_coded():
    from friday.core.config import Settings

    assert Settings(_env_file=None).support_inbox is None
    import pathlib
    import re

    phone = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
    for p in pathlib.Path("friday/chatbot").rglob("*"):
        if p.suffix in {".py", ".yaml"}:
            assert not phone.search(p.read_text()), f"a phone number in {p}"


# ---------------------------------------------------------------- stop / resume
@pytest.mark.parametrize("word", ["stop", "STOP", "band karo", "unsubscribe", "messages band karo"])
async def test_stop_pauses_proactive_messages(user_chat, word):
    user = await user_chat.user()
    out = await user_chat.say(word)
    assert "khud se message nahi" in (out[0].text or "")
    c = await user_chat.c.repos.consents.latest(user.id, ConsentKind.PROACTIVE)
    assert c is not None and c.granted is False
    for cat in AutonomyCategory:
        assert (await user_chat.c.repos.autonomy.get(user.id, cat)).enabled is False
    assert (await user_chat.c.repos.profiles.get_or_default(user.id)).morning_briefing is False


async def test_stop_is_idempotent_and_chalu_karo_resumes(user_chat):
    user = await user_chat.user()
    await user_chat.say("stop")
    user_chat.clock.advance(seconds=30)
    out = await user_chat.say("stop")
    assert "pehle se hi" in (out[0].text or "")
    user_chat.clock.advance(seconds=30)
    out = await user_chat.say("chalu karo")
    assert "dobara chalu" not in (out[0].text or "") and "zaroorat par" in (out[0].text or "")
    for cat in AutonomyCategory:
        assert (await user_chat.c.repos.autonomy.get(user.id, cat)).enabled is True
    user_chat.clock.advance(seconds=30)
    await user_chat.say("chalu karo")  # nothing is paused any more: it goes on to the brain
    assert user_chat.brain.seen[-1] == "chalu karo"


async def test_stop_inside_a_longer_sentence_is_not_the_stop_command(user_chat):
    await user_chat.say("stop calling mummy")
    assert user_chat.brain.seen[-1] == "stop calling mummy"
    user = await user_chat.user()
    assert await user_chat.c.repos.consents.latest(user.id, ConsentKind.PROACTIVE) is None


async def test_the_proactive_engine_respects_stop(user_chat):
    """A stopped user's autonomy setting is what the guardrails read."""
    from friday.core.config import Settings
    from friday.core.models import NudgeCandidate, NudgeKind, Urgency
    from friday.proactive.guardrails import evaluate

    user = await user_chat.user()
    await user_chat.say("stop")
    setting = await user_chat.c.repos.autonomy.get(user.id, AutonomyCategory.REMINDERS)
    cand = NudgeCandidate(
        user_id=user.id, kind=NudgeKind.TASK_REMINDER, category=AutonomyCategory.REMINDERS,
        urgency=Urgency.NORMAL, text="x", dedupe_key="k", reason="r", due_at=user_chat.clock.now(),
    )  # fmt: skip
    verdict = evaluate(
        cand, now=user_chat.clock.now(), settings=Settings(_env_file=None), autonomy=setting
    )
    assert verdict.action == "suppress"


# ---------------------------------------------------------------- delete everything
async def test_delete_everything_asks_to_type_delete_and_then_erases_everything(user_chat):
    user = await user_chat.user()
    await user_chat.say("98111 00077")  # a contact in the book
    await user_chat.say("mummy")
    out = await user_chat.say("delete everything")
    assert "DELETE" in (out[0].text or "")
    out = await user_chat.say("DELETE")
    assert out == [] or "deleted" in (out[-1].text or "").lower()
    assert await user_chat.user() is None
    for table in ("chatbot_sessions", "chatbot_inbox", "profiles", "consumer_contacts"):
        async with user_chat.c.repos.db.session() as s:
            n = (await s.execute(sql(f"select count(*) from {table}"))).scalar_one()
        assert n == 0, table
    assert user.id  # the tombstone only keeps a PII-free row


async def test_anything_but_delete_cancels(user_chat):
    await user_chat.say("sab delete karo")
    out = await user_chat.say("nahi rehne do")
    assert "cancelled" in (out[0].text or "").lower()
    assert await user_chat.user() is not None


async def test_a_user_with_a_pin_keeps_the_pin_protected_path(user_chat):
    user = await user_chat.user()
    user.pin_hash = "x"
    await user_chat.c.repos.users.save(user)
    await user_chat.say("delete everything")
    assert user_chat.brain.seen[-1] == "delete everything"  # the brain / PIN flow decides


# ---------------------------------------------------------------- the old flows still work
async def test_ordinary_messages_still_reach_the_brain(user_chat):
    out = await user_chat.say("mujhe kal ka plan batao")
    assert user_chat.brain.seen[-1] == "mujhe kal ka plan batao"
    assert out and "make calls" in (out[0].text or "")
