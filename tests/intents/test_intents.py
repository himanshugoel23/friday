# ruff: noqa: E501
"""Proactive intents in the live path (real pipeline over fakes, no network)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date

import pytest

import tests.integration.conftest as ic
from friday.chatbot.composer import Composer
from friday.core.models import ReplyButton
from friday.intents import gateway as gw
from friday.intents.gateway import IntentGateway, unglue

Factory = Callable[..., Awaitable[ic.World]]
GMAIL = "Mera gmail check krna"
REFUSAL = "isme main madad nahi kar sakti"


@pytest.fixture(autouse=True)
def _quiet(caplog: pytest.LogCaptureFixture):  # noqa: ANN202
    caplog.set_level(logging.DEBUG, logger="friday")
    yield


@pytest.fixture
async def make(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Factory]:
    made: list[ic.World] = []
    orig = ic.settings_with

    async def factory(
        *, google: bool = False, no_client_id: bool = False, **extra: object
    ) -> ic.World:
        def with_extra(google_extra: dict | None = None, **sw: bool):  # noqa: ANN202
            g = dict(google_extra or {})
            if no_client_id:
                g["google_oauth_client_id"] = None
            return orig(g, **sw, **extra)

        monkeypatch.setattr(ic, "settings_with", with_extra)
        w = await ic.make_world(calls=True, savings=True, lifestate=True, google=google)
        made.append(w)
        return w

    try:
        yield factory
    finally:
        for w in made:
            await ic.close_world(w)


def body(out) -> str:  # noqa: ANN001
    return "\n".join(m.text or "" for m in out)


def check(out) -> None:  # noqa: ANN001
    """Every reply obeys the chat rules (one question, button limits) and is never a bare refusal."""
    for m in out:
        problems = Composer().check(m.text or "", list(m.buttons), kind="assist")
        assert not problems, problems
        assert REFUSAL not in (m.text or "")


def spy(w) -> list[str]:  # noqa: ANN001
    """Texts that continue into the rest of the chain (the message the old flows would see)."""
    seen: list[str] = []

    async def rest(user, msg):  # noqa: ANN001, ANN202
        seen.append(msg.text or "")

    w.runtime.pipeline._team_or_after = rest
    return seen


def english(w) -> None:  # noqa: ANN001
    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    w.runtime.pipeline._reply_lang = lang


# ---------------------------------------------------------------------- the founder's three phrases
async def test_switch_off_builds_nothing_and_old_flow_runs(make):
    w = await make()
    assert w.runtime.pipeline.intents is None
    out = await w.say("interview hainkal")
    assert "Reminder lagao" not in w.all_out() and "Prep points" not in w.all_out()
    assert not [m for m in out if m.buttons]


async def test_gmail_not_configured_is_honest_and_offers_paste(make):
    w = await make(proactive_intents_enabled=True)  # no Google connector at all
    out = await w.say(GMAIL)
    t = body(out)
    check(out)
    assert "set up nahi" in t and "paste" in t and "http" not in t
    assert GMAIL not in w.brain.seen


async def test_gmail_client_id_missing_never_promises_a_link(make):
    w = await make(
        proactive_intents_enabled=True, google=True, no_client_id=True, google_gmail_enabled=True
    )
    out = await w.say(GMAIL)
    t = body(out)
    check(out)
    assert "http" not in t and "set up nahi" in t


async def test_gmail_configured_gives_a_real_connect_link_and_paste_fallback(make):
    w = await make(proactive_intents_enabled=True, google=True, google_gmail_enabled=True)
    out = await w.say(GMAIL)
    t = body(out)
    check(out)
    assert "connect karna hoga" in t and "/google/consent/" in t and "paste" in t


async def test_gmail_configured_but_gmail_scope_off_says_so_without_a_link(make):
    w = await make(proactive_intents_enabled=True, google=True, google_gmail_enabled=False)
    out = await w.say(GMAIL)
    assert "chalu nahi" in body(out) and "http" not in body(out)
    check(out)


async def test_gmail_in_english(make):
    w = await make(proactive_intents_enabled=True)
    english(w)
    out = await w.say("please check my gmail")
    assert "can't read your Gmail" in body(out) and "paste the email text" in body(out)


async def test_connect_gmail_still_goes_to_the_existing_google_flow(make):
    w = await make(proactive_intents_enabled=True, google=True, google_gmail_enabled=True)
    out = await w.say("gmail connect karo")
    assert "link" in body(out).lower() and "pehle aapka Gmail connect" not in body(out)


async def test_interview_hainkal_proposes_next_steps_with_buttons(make):
    w = await make(proactive_intents_enabled=True)
    out = await w.say("interview hainkal")
    check(out)
    assert len(out) == 1 and "kya help chahte" not in body(out)
    assert "Interview kal hai" in body(out)
    assert [b.title for b in out[0].buttons] == ["Reminder lagao", "Prep points", "Abhi nahi"]
    assert body(out).count("?") == 1
    assert "interview hainkal" not in w.brain.seen


async def test_founder_sequence_gmail_then_kal_then_interview(make):
    w = await make(proactive_intents_enabled=True)
    check(await w.say(GMAIL))
    out = await w.say("Kal")
    check(out)
    assert (
        "Kal ke baare mein aap kya chahte" not in body(out)
        and "kal" in body(out).lower()
        and "paste" in body(out)
    )
    out = await w.say("interview hainkal")
    assert "Interview kal hai" in body(out)


# ---------------------------------------------------------------------- fragments
async def test_unglue_splits_merged_typos():
    assert unglue("interview hainkal") == "interview hain kal"
    assert unglue("kalhai meeting") == "kal hai meeting"
    assert unglue("normal text") == "normal text"


async def test_bare_interview_asks_the_date_once_and_kal_fills_it(make):
    w = await make(proactive_intents_enabled=True)
    out = await w.say("interview hai")
    check(out)
    assert [b.title for b in out[0].buttons] == ["Aaj", "Kal", "Parso"] and body(out).count(
        "?"
    ) == 1
    out = await w.say("Kal")
    assert "Interview kal hai" in body(out) and len(out) == 1
    assert "interview hai" not in w.brain.seen and "Kal" not in w.brain.seen


async def test_date_button_fills_the_slot(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("exam hai")
    out = await w.tap("Parso")
    assert "Exam parso hai" in body(out)


async def test_kal_without_any_open_intent_is_left_to_the_old_flow(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("Kal")
    assert w.brain.seen[-1] == "Kal"


async def test_fragment_uses_the_query_agent_when_present(make):
    w = await make(proactive_intents_enabled=True)

    class QU:
        async def understand(self, user_id, text, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
            class R:
                instruction = "interview kal hai" if text == "intrvu kl" else text

            return R()

    w.runtime.pipeline.team = type("T", (), {"qu": QU()})()
    out = await w.say("intrvu kl")
    assert "Interview kal hai" in body(out)


# ---------------------------------------------------------------------- playbooks
@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("mera interview aaj hai", "Interview aaj hai"),
        ("birthday kal hai", "Birthday kal hai"),
        ("trip kal hai", "Trip kal hai"),
        ("bijli bill due kal", "Bill kal due hai"),
        ("exam parso hai", "Exam parso hai"),
        ("meeting aaj hai", "Meeting aaj hai"),
    ],
)
async def test_each_playbook_offers_one_question_and_two_or_three_buttons(make, text, needle):
    w = await make(proactive_intents_enabled=True)
    out = await w.say(text)
    check(out)
    assert needle in body(out) and body(out).count("?") == 1
    assert 2 <= len(out[0].buttons) <= 3


async def test_own_birthday_gets_a_greeting_and_a_dinner_offer(make):
    w = await make(proactive_intents_enabled=True)
    out = await w.say("aaj mera birthday hai")
    assert "Happy birthday" in body(out)
    check(out)
    out = await w.tap("Jagah")
    assert w.brain.seen[-1].startswith("Find a good restaurant for a birthday dinner today")


async def test_question_about_a_topic_is_not_hijacked(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("interview mein kya poochte hain?")
    assert w.brain.seen[-1] == "interview mein kya poochte hain?"


async def test_remind_saves_a_date_fact(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("interview hainkal")
    out = await w.tap("Reminder")
    assert "kal yaad dila" in body(out)
    facts = await w.c.repos.facts.list_for_user(w.user.id)
    due = w.clock.now().date()
    assert [(f.value, f.due_on) for f in facts if f.key.startswith("interview_")] == [
        ("Interview", date.fromordinal(due.toordinal() + 1))
    ]


async def test_prep_asks_one_question_then_hands_the_answer_to_the_normal_chain(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("interview hainkal")
    out = await w.tap("Prep")
    check(out)
    assert "company" in body(out) and body(out).count("?") == 1
    seen = spy(w)
    await w.say("Infosys, backend developer")
    assert (
        seen[-1]
        == "Help me prepare for a job interview. Company and role: Infosys, backend developer"
    )


async def test_not_now_closes_politely(make):
    w = await make(proactive_intents_enabled=True)
    await w.say("interview hainkal")
    out = await w.tap("Abhi nahi")
    assert "Theek hai" in body(out)


async def test_english_playbook(make):
    w = await make(proactive_intents_enabled=True)
    english(w)
    out = await w.say("I have an interview tomorrow")
    assert "Interview tomorrow, all the best" in body(out)
    assert [b.title for b in out[0].buttons] == ["Remind me", "Prep points", "Not now"]


async def test_app_order_is_honest_and_offers_web_prices(make):
    w = await make(proactive_intents_enabled=True)
    out = await w.say("zepto se atta order karo")
    assert "order nahi laga sakti" in body(out) and "daam" in body(out)
    check(out)
    await w.say("price of atta on zepto")
    assert w.brain.seen[-1] == "price of atta on zepto"  # a price question is not intercepted


async def test_pasted_long_text_is_never_intercepted(make):
    w = await make(proactive_intents_enabled=True)
    long = "gmail se aaya: " + "interview " * 40
    long = long.strip()
    seen = spy(w)
    await w.say(long)
    assert seen == [long]


async def test_every_wording_line_obeys_the_composer_rules():
    """Static check of the whole table: one question, length, button titles, both languages."""
    lines = []
    for pb in gw._DATA["playbooks"].values():
        for k in ("offer", "offer_own", "prep_ask", "ask_date_free"):
            if k in pb:
                lines += list(pb[k].values())
    for cap in gw._DATA["capabilities"].values():
        for k in ("static", "fragment", "connected", "not_configured", "scope_off"):
            if k in cap and cap[k]:
                lines += [
                    v.format(paste=cap.get("paste", {}).get("en", ""), when="kal", link="https://x")
                    for v in cap[k].values()
                ]
    for text in lines:
        text = text.format(when="kal") if "{when}" in text else text
        assert Composer().check(text, kind="assist") == [], text
    for pb in gw._DATA["playbooks"].values():
        for lang in ("en", "hinglish"):
            titles = [
                gw._line(gw._DATA["common"]["buttons"][k], lang) for k in ("remind_me", "not_now")
            ]
            titles += [gw._line(pb[k], lang) for k in ("prep_button", "own_button") if k in pb]
            btns = [ReplyButton(id=f"x{i}", title=t) for i, t in enumerate(titles[:3])]
            assert Composer().check("ok", btns, kind="assist") == []


def test_gateway_class_is_exported():
    assert IntentGateway.__name__ == "IntentGateway"
