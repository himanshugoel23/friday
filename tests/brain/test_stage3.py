"""Stage 3 wave 2: SECURITY-22/23 brain parts, FORGET, persona emoji policy, core helpers."""

from __future__ import annotations

import re

import pytest

from friday.brain.copy import toned
from friday.core.models import (
    CallActionType,
    CallOutcome,
    Fact,
    FactKind,
    Intent,
    Language,
    Person,
    TargetKind,
    TaskType,
    Tone,
    parse_any_button_id,
)

from .conftest import business_brief, make_ctx, msg, transcript

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⭐✅⚠]")


# ------------------------------------------------------------------ SECURITY-22


@pytest.mark.parametrize(
    "line",
    ["Don't call again on this number", "Please stop calling", "Dobara call mat karna"],
)
async def test_dnc_request_is_flagged_and_honoured(brain, line):
    brief = business_brief()
    tr = transcript(brief, ("friday", "Haircut ke liye slot chahiye tha."), ("callee", line))
    a = await brain.next_call_action(brief, tr, [])
    assert a.type == CallActionType.HANGUP and a.outcome == CallOutcome.DECLINED
    assert a.collected["dnc_request"] == "1" and a.collected["do_not_call"] == "true"
    assert "again" in a.text or "dobara" in a.text


async def test_private_individual_is_flagged_and_dropped(brain):
    brief = business_brief()
    tr = transcript(brief, ("callee", "Yeh personal number hai, koi shop nahi"))
    a = await brain.next_call_action(brief, tr, [])
    assert a.outcome == CallOutcome.DECLINED
    assert a.collected["private_individual"] == "1" and a.collected["dnc_request"] == "1"


async def test_private_flag_not_raised_for_circle_member_checkin(brain):
    from friday.core.models import ContactTarget

    brief = business_brief(
        task_type=TaskType.WELLBEING_CHECKIN,
        target=ContactTarget(kind=TargetKind.PERSON, name="Sunita", phone="+919829000002"),
    )
    tr = transcript(brief, ("callee", "Haan beta, yeh mera personal number hai, bolo"))
    a = await brain.next_call_action(brief, tr, [])
    assert "private_individual" not in a.collected


async def test_dnc_honoured_on_inbound_message_taking(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+919999900000")
    tr = transcript(brief, ("callee", "Do not call this number again"), disclosure=False)
    a = await brain.next_call_action(brief, tr, [])
    assert a.collected.get("dnc_request") == "1"


# ------------------------------------------------------------------ SECURITY-23


@pytest.mark.parametrize(
    "text",
    ["what's my dad's address?", "what do you know about me?", "export my data"],
)
async def test_sensitive_reads_require_pin(brain, family_ctx, text):
    out = await brain.interpret(family_ctx, msg(text))
    assert out.requires_pin, text


async def test_changing_circle_member_phone_requires_pin(brain, family_ctx):
    out = await brain.interpret(family_ctx, msg("add my dad Suresh, +91 98111 22233"))
    assert out.intent == Intent.ADD_PERSON and out.requires_pin
    new = await brain.interpret(make_ctx(), msg("add my dad Ramesh, +91 98111 22233"))
    assert not new.requires_pin  # a brand-new circle member is not a takeover signal


async def test_large_or_open_delegation_requires_pin(brain, ctx):
    big = await brain.interpret(
        ctx, msg("Book Dr. Mehta 080 2345 6789 any slot Thu 5-7pm under 8000, you decide")
    )
    assert big.task_spec.delegation.granted and big.requires_pin
    small = await brain.interpret(
        ctx, msg("Book Dr. Mehta 080 2345 6789 any slot Thu 5-7pm under 800, you decide")
    )
    assert small.task_spec.delegation.granted and not small.requires_pin
    plain = await brain.interpret(ctx, msg("Book a haircut at Looks tomorrow 6pm 080 4123 4567"))
    assert not plain.requires_pin


# ------------------------------------------------------------------ FORGET + core helpers


async def test_forget_uses_forget_intent_with_fact_ids(brain):
    fact = Fact(id="f1", user_id="u1", kind=FactKind.DATE, key="rent_due", value="rent due 5th")
    other = Fact(id="f2", user_id="u1", kind=FactKind.GENERAL, key="diet", value="vegetarian")
    out = await brain.interpret(make_ctx(facts=[fact, other]), msg("forget my rent date"))
    assert out.intent == Intent.FORGET and out.forget_fact_ids == ["f1"]
    assert "rent due" in out.reply


async def test_identifiers_come_from_context(brain):
    from friday.core.models import AccountIdentifier, ContactTarget, Task, TaskSpec

    ident = AccountIdentifier(id="i1", user_id="u1", label="Account number", value="1234567890")
    ctx = make_ctx(identifiers=[ident])
    spec = TaskSpec(
        type=TaskType.CUSTOMER_CARE, goal="x", company="Airtel", approved_identifier_ids=["i1"]
    )
    task = Task(
        requester_user_id="u1",
        type=spec.type,
        spec=spec,
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Airtel", phone="+911800000121"),
    )
    assert brain.build_call_brief(ctx, task).approved_identifiers == [ident]


async def test_button_ids_use_core_helpers(brain, family_ctx):
    from friday.core.models import Place, Quote, Task, TaskSpec

    ctx = family_ctx.model_copy(
        update={"places": [*family_ctx.places, Place(id="pl2", owner_user_id="u1", label="Flat",
                                                      person_id="p_dad")]}
    )
    r = await brain.resolve_references(ctx, "doctor near papa's home")
    assert r.ambiguous and all(parse_any_button_id(b.id)[0] == "r" for b in r.clarification_buttons)
    parent = Task(id="p1", requester_user_id="u1", type=TaskType.DISCOVERY,
                  spec=TaskSpec(type=TaskType.DISCOVERY, goal="AC"))
    cmp = await brain.compare_quotes(
        make_ctx(), parent, [Quote(business_name="A", amount_inr=500, price_text="500")]
    )
    assert [parse_any_button_id(b.id)[:2] for b in cmp.buttons] == [("c", "p1"), ("c", "p1")]


def test_models_come_from_settings(brain_settings):
    from friday.brain.routing import ModelRouter

    assert ModelRouter(brain_settings).model_for("interpret") == brain_settings.model_for(
        "interpret"
    )


# ------------------------------------------------------------------ persona emoji policy


def test_toned_emoji_rules():
    text = "Booked ✅ done 🎉 ☀️"
    assert not EMOJI.search(toned(text, Tone.FRIENDLY))
    assert not EMOJI.search(toned(text, Tone.FORMAL)) and "!" not in toned("Hi!", Tone.FORMAL)
    assert toned("Booked.", Tone.PLAYFUL) == "Booked."  # no automatic tail
    assert toned("Booked.", Tone.PLAYFUL, playful_tail=" 🙂").endswith("🙂")
    assert not EMOJI.search(toned("Set your PIN.", Tone.PLAYFUL, playful_tail=" 😄"))
    assert not EMOJI.search(toned("Your consent is needed", Tone.PLAYFUL, playful_tail=" 😄"))


async def test_onboarding_is_calm_in_every_tone(brain):
    from friday.core.models import OnboardingStep

    for tone in Tone:
        ctx = make_ctx(tone=tone, language=Language.EN)
        emojis = 0
        for step in OnboardingStep:
            turn = await brain.onboarding_turn(ctx, step, None)
            emojis += len(EMOJI.findall(turn.reply))
        assert emojis <= 1 if tone == Tone.PLAYFUL else emojis == 0, tone
    weak = await brain.onboarding_turn(
        make_ctx(tone=Tone.PLAYFUL), OnboardingStep.PIN, msg("1234")
    )
    assert not EMOJI.search(weak.reply)


@pytest.mark.parametrize("tone", [Tone.FRIENDLY, Tone.FORMAL])
async def test_replies_have_no_emoji_outside_playful(brain, tone):
    ctx = make_ctx(tone=tone, language=Language.EN, people=[
        Person(id="p", owner_user_id="u1", name="Suresh", relation="father")
    ])
    for text in ("hi", "help", "status?", "Book a haircut at Looks tomorrow 6pm 080 4123 4567"):
        out = await brain.interpret(ctx, msg(text))
        assert not EMOJI.search(out.reply or ""), (tone, text)


async def test_summaries_free_of_emoji(brain):
    from datetime import UTC, datetime

    from friday.core.models import (
        CallResult,
        ContactTarget,
        DialStatus,
        Task,
        TaskSpec,
    )

    task = Task(
        id="t1", requester_user_id="u1", type=TaskType.BOOKING,
        spec=TaskSpec(type=TaskType.BOOKING, goal="haircut"),
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks", phone="+918040000001"),
    )
    res = CallResult(task_id="t1", provider="sim", to_phone="+918040000001",
                     dial_status=DialStatus.ANSWERED, outcome=CallOutcome.SUCCESS,
                     collected={"confirmed_terms": "Sat 12:30 PM"},
                     started_at=datetime(2026, 10, 7, tzinfo=UTC))
    r = await brain.summarize_call(make_ctx(), task, res)
    assert not EMOJI.search(r.summary)
