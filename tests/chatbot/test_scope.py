"""The off-topic redirect, the wishlist and `friday chatbot wishlist`."""

from __future__ import annotations

import argparse

import pytest

from friday.chatbot import copy
from friday.chatbot.cli import add_parser, run
from friday.chatbot.scope import is_out_of_scope, mask_numbers
from friday.db import Database

OUT = [
    "What is the capital of France",
    "who is the prime minister of India",
    "bhai ek joke sunao",
    "tell me a joke",
    "meaning of serendipity",
    "write me a poem about the rain",
    "aaj ka cricket score kya hai",
    "mera rashifal batao",
    "bitcoin price today",
    "translate this to french",
    "2 + 2 kitna",
    "paneer butter masala recipe",
    "mausam kaisa hai",
]
IN = [
    "mummy ko call karo ki main late hoon",
    "kal 2 baje interview hai",
    "which card for Zomato 640",
    "meri bijli ka bill 25 ko due hai",
    "plumber chahiye kal subah",
    "who is calling me",
    "haircut book karo",
    "weather for my trip to Goa next week",
    "remind me to pay rent",
    "hi",
    "ok",
    "kuch bhi",
    "",
]


@pytest.mark.parametrize("text", OUT)
def test_clear_general_knowledge_asks_are_out_of_scope(text):
    assert is_out_of_scope(text)


@pytest.mark.parametrize("text", IN)
def test_anything_about_the_users_world_or_unclear_is_left_to_the_flows(text):
    assert not is_out_of_scope(text)


def test_numbers_links_and_emails_are_masked_before_storage():
    out = mask_numbers(
        "call 98765 43210 or mail a.b@example.com, card 4111 1111 1111 1111 "
        "https://x.example/y otp 123456"
    )
    assert "98765" not in out and "4111" not in out and "123456" not in out
    assert "@" not in out and "http" not in out
    assert out.count("<number>") >= 3 and "<email>" in out and "<link>" in out
    assert len(mask_numbers("x" * 500)) <= 200


async def test_an_off_topic_question_gets_the_polite_redirect_and_is_kept_for_review(chat):
    await chat.onboard()
    chat.channel.clear()
    out = await chat.say("What is the capital of France")
    assert len(out) == 1
    assert copy.line("offtopic", "hinglish") == out[0].text
    assert "kaam ke liye" in (out[0].text or "")
    assert chat.brain.seen == []  # the brain never answered a general-knowledge question
    items = await chat.c.repos.chatbot.inbox_list("wishlist")
    assert [i.text for i in items] == ["What is the capital of France"]


async def test_numbers_in_a_wishlist_entry_are_masked(chat):
    await chat.onboard()
    await chat.say("who is the prime minister of India 9876543210")
    items = await chat.c.repos.chatbot.inbox_list("wishlist")
    assert items and "9876543210" not in items[0].text and "<number>" in items[0].text


async def test_asking_the_same_thing_twice_stores_it_once(chat):
    await chat.onboard()
    await chat.say("tell me a joke")
    await chat.say("tell me a joke")
    assert len(await chat.c.repos.chatbot.inbox_list("wishlist")) == 1


async def test_a_real_task_is_never_redirected(chat):
    await chat.onboard()
    await chat.say("kal subah plumber chahiye")
    assert chat.brain.seen[-1] == "kal subah plumber chahiye"
    assert await chat.c.repos.chatbot.inbox_list("wishlist") == []


async def test_wishlist_only_mode_stores_but_lets_the_brain_answer(make_chat):
    chat = await make_chat(chatbot_offtopic="wishlist_only")
    try:
        await chat.onboard()
        await chat.say("tell me a joke")
        assert chat.brain.seen[-1] == "tell me a joke"
        assert len(await chat.c.repos.chatbot.inbox_list("wishlist")) == 1
    finally:
        await chat.c.aclose()


async def test_off_mode_does_nothing_special(make_chat):
    chat = await make_chat(chatbot_offtopic="off")
    try:
        await chat.onboard()
        await chat.say("tell me a joke")
        assert chat.brain.seen[-1] == "tell me a joke"
        assert await chat.c.repos.chatbot.inbox_list("wishlist") == []
    finally:
        await chat.c.aclose()


async def test_the_redirect_follows_the_users_language(make_chat):
    chat = await make_chat()
    try:
        await chat.say("Hello, I need some help please")
        await chat.tap("Yes, okay")
        await chat.say("Asha")
        await chat.tap("English")
        await chat.say("skip")
        out = await chat.say("tell me a joke")
        assert "I'm here for your tasks" in (out[-1].text or "")
    finally:
        await chat.c.aclose()


async def test_the_wishlist_is_erased_with_the_user(chat):
    await chat.onboard()
    await chat.say("tell me a joke")
    await chat.say("delete everything")
    await chat.say("DELETE")
    assert await chat.c.repos.chatbot.inbox_list("wishlist") == []


# ---------------------------------------------------------------- friday chatbot wishlist
def parse(*argv: str) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    add_parser(p.add_subparsers(dest="cmd", required=True))
    return p.parse_args(["chatbot", *argv])


async def test_the_wishlist_command_prints_what_testers_asked(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/w.db"
    db = Database(url)
    await db.create_all()
    from friday.core.models import User, UserStatus
    from friday.db.repositories.chatbot import ChatbotRepo
    from friday.db.repositories.users import UserRepo

    u = await UserRepo(db).add(User(phone="+919800000001", status=UserStatus.ACTIVE))
    repo = ChatbotRepo(db)
    await repo.inbox_add("wishlist", "tell me a joke", user_id=u.id)
    await repo.inbox_add("wishlist", "tell me a joke", user_id=u.id)
    await repo.inbox_add("wishlist", "cricket score", user_id=u.id, lang="en")
    await repo.inbox_add("support", "kuch galat hai", user_id=u.id)
    await db.dispose()

    import asyncio

    lines: list[str] = []
    rc = await asyncio.to_thread(run, parse("wishlist"), url, lines.append)
    assert rc == 0
    text = "\n".join(lines)
    assert "3 wishlist entries (2 different)" in text
    assert "cricket score" in text and "2x  tell me a joke" in text
    assert "kuch galat hai" not in text
    lines.clear()
    await asyncio.to_thread(run, parse("wishlist", "--support"), url, lines.append)
    assert "kuch galat hai" in "\n".join(lines)
    lines.clear()
    await asyncio.to_thread(run, parse("status"), url, lines.append)
    assert "waitlist" in "\n".join(lines)


async def test_an_empty_wishlist_says_so(tmp_path):
    import asyncio

    url = f"sqlite+aiosqlite:///{tmp_path}/e.db"
    db = Database(url)
    await db.create_all()
    await db.dispose()
    lines: list[str] = []
    assert await asyncio.to_thread(run, parse("wishlist"), url, lines.append) == 0
    assert lines == ["no wishlist entries yet"]


def test_the_command_is_registered_in_the_main_cli(capsys):
    from friday.cli import main

    assert main(["chatbot", "templates", "check"]) == 0
    assert "OK" in capsys.readouterr().out
