"""AI-9 onboarding_turn, AI-10 judge_nudge."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.core.models import (
    AutonomyCategory,
    LocationPin,
    MessageKind,
    NudgeCandidate,
    NudgeKind,
    OnboardingStep,
    TaskType,
    Urgency,
    parse_button_id,
)

from .conftest import NOW, msg

S = OnboardingStep


async def test_every_step_has_an_opening_prompt(brain, ctx):
    for step in S:
        turn = await brain.onboarding_turn(ctx, step, None)
        assert turn.reply and turn.next_step == step


@pytest.mark.parametrize(("step", "text", "next_step", "field", "value"), [
    (S.INVITE_CODE, "fri-7kq2mx", S.NAME, "invite_code", "FRI-7KQ2MX"),
    (S.NAME, "Ankit Sharma", S.CITY, "name", "Ankit Sharma"),
    (S.NAME, "mera naam Ankit hai", S.CITY, "name", "Ankit"),
    (S.CITY, "blr", S.LANGUAGE, "city", "Bengaluru"),
    (S.CITY, "Jaipur", S.LANGUAGE, "city", "Jaipur"),
    (S.LANGUAGE, "Hinglish", S.TONE, "language", "hinglish"),
    (S.TONE, "formal please", S.CONSENT, "tone", "formal"),
])
async def test_steps_extract_and_advance(brain, ctx, step, text, next_step, field, value):
    turn = await brain.onboarding_turn(ctx, step, msg(text))
    assert turn.next_step == next_step
    got = turn.invite_code if field == "invite_code" else turn.profile_updates[field]
    assert str(getattr(got, "value", got)) == value


async def test_invalid_invite_code_reasks(brain, ctx):
    turn = await brain.onboarding_turn(ctx, S.INVITE_CODE, msg("hi"))
    assert turn.next_step == S.INVITE_CODE and turn.invite_code is None


async def test_consent_only_on_explicit_agreement(brain, ctx):
    for text in ("ok", "haan", "sure whatever", "yes"):
        turn = await brain.onboarding_turn(ctx, S.CONSENT, msg(text))
        assert turn.consent_given is None and turn.next_step == S.CONSENT
    for text in ("I agree", "haan, agree", "मैं सहमत हूँ"):
        turn = await brain.onboarding_turn(ctx, S.CONSENT, msg(text))
        assert turn.consent_given is True and turn.next_step == S.PIN
    turn = await brain.onboarding_turn(ctx, S.CONSENT, msg(button_id="ob:consent:yes",
                                                            kind=MessageKind.BUTTON_REPLY))
    assert turn.consent_given is True
    refused = await brain.onboarding_turn(ctx, S.CONSENT, msg("not now"))
    assert refused.consent_given is False and refused.next_step == S.CONSENT


@pytest.mark.parametrize("pin", ["1234", "0000", "12345", "12a4", "2580"])
async def test_invalid_or_weak_pin_rejected(brain, ctx, pin):
    turn = await brain.onboarding_turn(ctx, S.PIN, msg(pin))
    assert turn.pin is None and turn.next_step == S.PIN and pin not in turn.reply


async def test_valid_pin_extracted_never_echoed(brain, ctx):
    turn = await brain.onboarding_turn(ctx, S.PIN, msg("7391"))
    assert turn.pin == "7391" and "7391" not in turn.reply and turn.next_step == S.CIRCLE


async def test_circle_places_skip_and_add(brain, ctx):
    skip = await brain.onboarding_turn(ctx, S.CIRCLE, msg(button_id="ob:skip",
                                                          kind=MessageKind.BUTTON_REPLY))
    assert skip.next_step == S.PLACES and not skip.people
    add = await brain.onboarding_turn(ctx, S.CIRCLE, msg("my dad Ramesh, +91 98290 12345, "
                                                         "Hindi"))
    p = add.people[0]
    assert p.name == "Ramesh" and p.relation == "father" and p.phone == "+919829012345"
    assert p.owner_user_id == ctx.user.id
    places = await brain.onboarding_turn(ctx, S.PLACES, msg("home: Indiranagar, office: "
                                                            "Bellandur"))
    assert [pl.label for pl in places.places] == ["Home", "Office"]
    pin = await brain.onboarding_turn(ctx, S.PLACES, msg(kind=MessageKind.LOCATION,
                                                         location=LocationPin(lat=1, lng=2)))
    assert pin.places[0].label == "Home" and pin.next_step == S.FIRST_TASK


async def test_first_task(brain, ctx):
    turn = await brain.onboarding_turn(ctx, S.FIRST_TASK, msg("Dentist appointment Saturday "
                                                              "morning at Smile Dental"))
    assert turn.next_step == S.DONE and turn.first_task.type == TaskType.HEALTHCARE
    later = await brain.onboarding_turn(ctx, S.FIRST_TASK, msg("later"))
    assert later.next_step == S.DONE and later.first_task is None


# ------------------------------------------------------------------ nudges


def _cand(kind, **kw) -> NudgeCandidate:
    data = dict(user_id="u1", kind=kind, category=AutonomyCategory.ROUTINES,
                reason="haircut", due_at=NOW + timedelta(hours=2), dedupe_key=f"k:{kind}")
    data.update(kw)
    return NudgeCandidate(**data)


@pytest.mark.parametrize("kind", list(NudgeKind))
async def test_each_kind_offers_an_action(brain, ctx, kind):
    d = await brain.judge_nudge(ctx, _cand(kind, data={"business_name": "Looks Salon",
                                                       "what": "haircut", "items": ["x"]}))
    assert d.send and d.text and 1 <= len(d.buttons) <= 3
    for b in d.buttons:
        kind_, nid, _action = parse_button_id(b.id)
        assert kind_ == "n" and nid == brain.nudge_id_for(_cand(kind)) and len(b.title) <= 20
    assert d.template.key == "nudge" and d.template.params[0] == "Ankit"


async def test_pattern_nudge_proposes_delegated_task(brain, ctx):
    d = await brain.judge_nudge(ctx, _cand(NudgeKind.PATTERN, data={
        "business_name": "Looks Salon", "business_phone": "+918040000001", "what": "haircut",
        "weeks": 4, "usual_slot": "Sat 11 AM", "usual_price": 600}))
    t = d.proposed_task
    assert t.type == TaskType.BOOKING and t.business_phone == "+918040000001"
    assert t.delegation.granted and t.delegation.max_price_inr == 600


async def test_stale_or_ignored_nudges_not_sent(brain, ctx):
    stale = _cand(NudgeKind.TASK_REMINDER, due_at=NOW - timedelta(hours=1))
    assert not (await brain.judge_nudge(ctx, stale)).send
    ignored = _cand(NudgeKind.PATTERN, data={"ignored_streak": 3})
    assert not (await brain.judge_nudge(ctx, ignored)).send


async def test_wellbeing_alert_always_sent(brain, ctx):
    d = await brain.judge_nudge(ctx, _cand(NudgeKind.WELLBEING_ALERT, urgency=Urgency.SAFETY,
                                           data={"alert": "dizzy since morning",
                                                 "already_done": True}))
    assert d.send and "112" in d.text


async def test_nudges_are_rule_first(brain, fake_llm, ctx):
    await brain.judge_nudge(ctx, _cand(NudgeKind.FOLLOW_UP))
    assert not fake_llm.calls_for("judge_nudge")
    await brain.judge_nudge(ctx, _cand(NudgeKind.FOLLOW_UP, data={"personalize": True}))
    assert fake_llm.calls_for("judge_nudge")[-1].model == "claude-haiku-5-5"
