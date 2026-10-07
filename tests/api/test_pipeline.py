"""Scenario tests for the inbound pipeline with a fake brain + fake engine."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.api.inbound import (
    DELETE_CONFIRM,
    DELETE_DONE,
    PIN_LOOKALIKE,
    PIN_NEEDED,
)
from friday.api.onboarding import (
    INVITE_ASK,
    INVITE_BAD,
    PIN_CONFIRM,
    PIN_MISMATCH,
    PIN_SAVED,
    PIN_WEAK,
    WAITLIST_ACK,
)
from friday.core.models import (
    AccountIdentifier,
    ConsentKind,
    Intent,
    Interpretation,
    Invite,
    MidCallQuestion,
    OnboardingStep,
    Person,
    PersonConsent,
    QuestionPurpose,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
    User,
    UserStatus,
)
from tests.api.conftest import ADMIN

NEW = "+919800000101"
PIN = "4826"


async def say(pipeline, channel, phone: str, text: str) -> list[str]:
    before = len(channel.messages_to(phone))
    await pipeline.handle(channel.make_inbound(phone, text))
    return [channel.render(m) for m in channel.messages_to(phone)[before:]]


async def onboard(pipeline, channel, phone: str = ADMIN) -> User:
    for line in [
        "hi",
        "Rahul",
        "Pune",
        "English",
        "formal",
        "I agree",
        PIN,
        PIN,
        "skip",
        "",
        "book a haircut",
    ]:
        if line:
            await say(pipeline, channel, phone, line)
        else:
            await say(pipeline, channel, phone, "no thanks")
    user = await pipeline.repos.users.get_by_phone(phone)
    assert user.status == UserStatus.ACTIVE
    return user


# ---------------------------------------------------------------------- invites / waitlist


async def test_invite_waitlist_and_redeem(pipeline, channel):
    assert await say(pipeline, channel, NEW, "hello") == [INVITE_ASK]
    assert await say(pipeline, channel, NEW, "I don't have one") == [WAITLIST_ACK]
    user = await pipeline.repos.users.get_by_phone(NEW)
    assert user.status == UserStatus.WAITLISTED
    assert await say(pipeline, channel, NEW, "hello??") == []  # silent while waitlisted
    assert await say(pipeline, channel, NEW, "fri-zzzzzz") == [INVITE_BAD]

    inviter = await pipeline.repos.users.add(User(phone="+919800000555", status=UserStatus.ACTIVE))
    await pipeline.repos.invites.add(Invite(code="FRI-AB12CD", created_by_user_id=inviter.id))
    replies = await say(pipeline, channel, NEW, "my code is FRI ab12cd")
    assert replies == ["ask name"]
    user = await pipeline.repos.users.get_by_phone(NEW)
    assert user.status == UserStatus.ONBOARDING and user.onboarding_step == OnboardingStep.NAME
    assert user.invited_by_user_id == inviter.id
    # single use
    other = "+919800000102"
    await say(pipeline, channel, other, "FRI-AB12CD")
    assert channel.render(channel.last_to(other)) == INVITE_BAD


# ---------------------------------------------------------------------- onboarding


async def test_full_onboarding_consent_pin_never_echoed(pipeline, channel, brain, engine):
    assert await say(pipeline, channel, ADMIN, "hi") == ["ask name"]  # admin skips invite
    await say(pipeline, channel, ADMIN, "Rahul")
    await say(pipeline, channel, ADMIN, "Pune")
    await say(pipeline, channel, ADMIN, "English")
    await say(pipeline, channel, ADMIN, "formal")
    user = await pipeline.repos.users.get_by_phone(ADMIN)
    assert user.onboarding_step == OnboardingStep.CONSENT
    # brain tries to move on without agreement -> clamped at CONSENT
    assert await say(pipeline, channel, ADMIN, "what is this?") == ["please agree"]
    user = await pipeline.repos.users.get_by_phone(ADMIN)
    assert user.onboarding_step == OnboardingStep.CONSENT
    assert not await pipeline.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY)

    replies = await say(pipeline, channel, ADMIN, "I agree")
    assert replies[0].endswith(
        "Please send a 4-digit Friday PIN. I'll ask for it before sensitive things."
    )
    consent = await pipeline.repos.consents.latest(user.id, ConsentKind.TERMS_PRIVACY)
    assert consent.granted and consent.evidence_text == "I agree"

    assert await say(pipeline, channel, ADMIN, "1111") == [PIN_WEAK]
    assert await say(pipeline, channel, ADMIN, PIN) == [PIN_CONFIRM]
    assert await say(pipeline, channel, ADMIN, "1357") == [PIN_MISMATCH]
    await say(pipeline, channel, ADMIN, PIN)
    assert await say(pipeline, channel, ADMIN, PIN) == [f"{PIN_SAVED}\n\nask circle"]
    user = await pipeline.repos.users.get_by_phone(ADMIN)
    assert user.pin_hash and PIN not in user.pin_hash
    assert user.onboarding_step == OnboardingStep.CIRCLE

    await say(pipeline, channel, ADMIN, "my dad, 98111 11111")
    people = await pipeline.repos.people.list_for_owner(user.id)
    assert people[0].phone == "+919811111111" and people[0].relation == "father"
    assert people[0].contact_consent == PersonConsent.NOT_ASKED
    await say(pipeline, channel, ADMIN, "Kothrud")
    places = await pipeline.repos.places.list_for_owner(user.id)
    assert places[0].formatted_address == "Kothrud, Pune" and places[0].location is not None
    assert await say(pipeline, channel, ADMIN, "book a haircut at Looks") == ["On it!"]

    user = await pipeline.repos.users.get_by_phone(ADMIN)
    assert user.status == UserStatus.ACTIVE and user.invites_remaining == 5
    tasks = await pipeline.repos.tasks.list_for_user(user.id)
    assert len(tasks) == 1 and tasks[0].spec.on_behalf_of == "Rahul"
    assert engine.names() == ["submit"]

    # PIN never echoed, never logged, never sent to the brain
    assert all(PIN not in channel.render(m) for m in channel.outbox)
    assert all(
        PIN not in (m.text or "")
        for m in await pipeline.repos.messages.list_for_user(user.id, limit=200)
    )
    assert all(PIN not in (t or "") for t in brain.seen)
    profile = await pipeline.repos.profiles.get(user.id)
    assert profile.name == "Rahul" and profile.city == "Pune"


async def test_no_extra_data_before_consent(pipeline, channel, brain):
    from friday.core.models import OnboardingTurn

    await say(pipeline, channel, ADMIN, "hi")

    async def greedy(ctx, step, message):  # noqa: ANN001
        return OnboardingTurn(
            reply="ok",
            profile_updates={"name": "R", "morning_briefing": True},
            next_step=OnboardingStep.CITY,
        )

    brain.onboarding_turn = greedy
    await say(pipeline, channel, ADMIN, "R")
    user = await pipeline.repos.users.get_by_phone(ADMIN)
    profile = await pipeline.repos.profiles.get(user.id)
    assert profile.name == "R" and profile.morning_briefing is False


# ---------------------------------------------------------------------- active-user dispatch


async def test_new_task_dispatch_and_resolution_checks(pipeline, channel, brain, engine):
    user = await onboard(pipeline, channel)
    dad = (await pipeline.repos.people.list_for_owner(user.id)) or [
        await pipeline.repos.people.upsert(Person(owner_user_id=user.id, name="Dad"))
    ]
    from friday.core.models import ReferenceResolution

    spec = TaskSpec(type=TaskType.HEALTHCARE, goal="Doctor for dad")
    brain.script.append(
        Interpretation(
            intent=Intent.NEW_TASK,
            reply="Calling the clinic",
            task_spec=spec,
            resolution=ReferenceResolution(person_id=dad[0].id, place_id="not-mine"),
        )
    )
    assert await say(pipeline, channel, ADMIN, "book a doctor for papa") == ["Calling the clinic"]
    task = (await pipeline.repos.tasks.list_for_user(user.id))[-1]
    assert task.beneficiary.person_id == dad[0].id and task.place_id is None
    assert engine.calls[-1][0] == "submit"


async def test_abuse_limit_off_by_default_and_neutral_when_on(pipeline, channel, brain, engine):
    user = await onboard(pipeline, channel)
    pipeline.settings.abuse_max_calls_per_day = 1
    brain.script.append(
        Interpretation(
            intent=Intent.NEW_TASK,
            reply="ok",
            task_spec=TaskSpec(type=TaskType.ENQUIRY, goal="open?"),
        )
    )
    assert await say(pipeline, channel, ADMIN, "is it open") == ["ok"]  # limit disabled
    user = await pipeline.repos.users.get(user.id)
    user.rate_limited = True  # ops enables for this user
    await pipeline.repos.users.save(user)
    brain.script.append(
        Interpretation(
            intent=Intent.NEW_TASK,
            reply="ok",
            task_spec=TaskSpec(type=TaskType.ENQUIRY, goal="again"),
        )
    )
    submits = engine.names().count("submit")
    replies = await say(pipeline, channel, ADMIN, "again")
    assert replies[0].startswith("I'm handling a lot right now. I'll pick this up at")
    assert "cap" not in replies[0].lower() and "limit" not in replies[0].lower()
    assert engine.names().count("submit") == submits
    queued = (await pipeline.repos.tasks.list_for_user(user.id))[-1]
    assert queued.status == TaskStatus.SCHEDULED and queued.next_attempt_at > pipeline.clock.now()


async def _task(pipeline, user) -> Task:
    return await pipeline.repos.tasks.add(
        Task(
            requester_user_id=user.id,
            type=TaskType.BOOKING,
            spec=TaskSpec(type=TaskType.BOOKING, goal="haircut"),
        )
    )


async def test_question_and_approval_buttons(pipeline, channel, engine, wired):
    user = await onboard(pipeline, channel)
    task = await _task(pipeline, user)
    q = MidCallQuestion(
        task_id=task.id,
        text="Looks has 4pm or 6pm, ₹400. Book which?",
        options=["4pm", "6pm", "Don't book"],
        purpose=QuestionPurpose.APPROVE_BOOKING,
        asked_at=pipeline.clock.now(),
    )
    await wired.notifier.ask_user(user.id, q)
    await say(pipeline, channel, ADMIN, "2")
    name, (answer,) = engine.calls[-1]
    assert name == "handle_answer" and answer.text == "6pm" and answer.approves
    assert (await pipeline.repos.tasks.get_answer(q.id)).option_index == 1

    q2 = q.model_copy(update={"id": "q2" + "0" * 30})
    await wired.notifier.ask_user(user.id, q2)
    await say(pipeline, channel, ADMIN, "3")
    assert engine.calls[-1][1][0].approves is False

    from friday.core.models import ReplyButton, approval_button_id

    await wired.notifier.notify_user(
        user.id,
        "Call them?",
        buttons=[ReplyButton(id=approval_button_id(task.id, True), title="Yes")],
    )
    await say(pipeline, channel, ADMIN, "1")
    assert engine.calls[-1] == ("approve", (task.id, True))


async def test_free_text_answer_uses_pending_question(pipeline, channel, brain, engine, wired):
    user = await onboard(pipeline, channel)
    task = await _task(pipeline, user)
    q = MidCallQuestion(task_id=task.id, text="Beard trim too?", asked_at=pipeline.clock.now())
    await wired.notifier.ask_user(user.id, q)
    brain.script.append(
        lambda ctx, m: Interpretation(intent=Intent.ANSWER_QUESTION, reply="Got it")
    )
    await say(pipeline, channel, ADMIN, "haan beard bhi")
    assert brain.contexts[-1].pending_question.id == q.id
    assert engine.calls[-1][0] == "handle_answer" and engine.calls[-1][1][0].question_id == q.id


async def test_pin_lookalike_warning_and_redaction(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    n = len(brain.seen)
    assert await say(pipeline, channel, ADMIN, PIN) == [PIN_LOOKALIKE]
    assert len(brain.seen) == n  # never reached the brain
    logged = await pipeline.repos.messages.list_for_user(user.id, limit=200)
    assert all(PIN not in (m.text or "") for m in logged)


async def test_save_identifier_needs_pin_and_is_encrypted(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    ident = AccountIdentifier(
        user_id="whoever", company="Airtel", label="broadband account", value="1234567890"
    )
    brain.script.append(Interpretation(intent=Intent.SAVE_IDENTIFIER, identifier_upsert=ident))
    assert await say(pipeline, channel, ADMIN, "my airtel account is 1234567890") == [PIN_NEEDED]
    assert await pipeline.repos.identifiers.list_for_user(user.id) == []
    replies = await say(pipeline, channel, ADMIN, "0000")
    assert replies[0].startswith("That PIN didn't match")
    replies = await say(pipeline, channel, ADMIN, PIN)
    assert replies == ["Saved broadband account (••••••7890)."]
    saved = await pipeline.repos.identifiers.list_for_user(user.id)
    assert saved[0].value == "1234567890" and saved[0].user_id == user.id


async def test_pin_lockout(pipeline, channel, brain):
    await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    await say(pipeline, channel, ADMIN, "delete everything")
    for _ in range(4):
        await say(pipeline, channel, ADMIN, "0000")
    replies = await say(pipeline, channel, ADMIN, "0000")
    assert "locked" in replies[0]
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    assert "locked" in (await say(pipeline, channel, ADMIN, "delete everything"))[0]
    pipeline.clock.advance(minutes=31)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    assert await say(pipeline, channel, ADMIN, "delete everything") == [PIN_NEEDED]
    assert await say(pipeline, channel, ADMIN, PIN) == [DELETE_CONFIRM]


async def test_delete_everything(pipeline, channel, brain, engine):
    user = await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    assert await say(pipeline, channel, ADMIN, "mera sab data delete karo") == [PIN_NEEDED]
    assert await say(pipeline, channel, ADMIN, PIN) == [DELETE_CONFIRM]
    assert await say(pipeline, channel, ADMIN, "DELETE") == [DELETE_DONE]
    assert "cancel" in engine.names()
    tomb = await pipeline.repos.users.get(user.id)
    assert tomb.status == UserStatus.DELETED and tomb.pin_hash is None
    assert await pipeline.repos.messages.list_for_user(user.id) == []
    assert await pipeline.repos.tasks.list_for_user(user.id) == []
    assert await pipeline.repos.profiles.get(user.id) is None
    assert any(
        a.action == "data.deleted" for a in await pipeline.repos.audit.list_for_user(user.id)
    )
    # coming back = fresh signup (admin phone skips invite)
    assert await say(pipeline, channel, ADMIN, "hi again") == ["ask name"]


async def test_delete_cancelled_without_confirm_word(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    await say(pipeline, channel, ADMIN, "delete my data")
    await say(pipeline, channel, ADMIN, PIN)
    assert (await say(pipeline, channel, ADMIN, "no wait"))[0].startswith("Okay, cancelled")
    assert (await pipeline.repos.users.get(user.id)).status == UserStatus.ACTIVE


async def test_invites_for_regular_user(pipeline, channel, brain):
    user = await pipeline.repos.users.add(
        User(
            phone="+919800000888",
            status=UserStatus.ACTIVE,
            onboarding_step=OnboardingStep.DONE,
            invites_remaining=5,
        )
    )
    brain.script.append(Interpretation(intent=Intent.INVITE, reply="ignored"))
    replies = await say(pipeline, channel, user.phone, "give me invite codes")
    assert replies[0].startswith("Your invite codes")
    assert replies[0].count("FRI-") == 5
    brain.script.append(Interpretation(intent=Intent.INVITE))
    assert (await say(pipeline, channel, user.phone, "invites"))[0].count("FRI-") == 5
    assert (await pipeline.repos.users.get(user.id)).invites_remaining == 0


async def test_voice_note_transcribed_for_brain(pipeline, channel, brain):
    await onboard(pipeline, channel)
    await say(pipeline, channel, ADMIN, "/voice kal shaam haircut book karo")
    assert brain.seen[-1] == "kal shaam haircut book karo"


async def test_location_pin_add_place(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.ADD_PLACE, reply="Saved"))
    await say(pipeline, channel, ADMIN, "/pin 12.97,77.64")
    places = await pipeline.repos.places.list_for_owner(user.id)
    pinned = [p for p in places if p.location and p.location.lat == 12.97]
    assert pinned and pinned[0].formatted_address == "Pinned spot, Bengaluru"


async def test_settings_and_add_person_never_trusts_consent(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    brain.script.append(
        Interpretation(
            intent=Intent.SETTINGS,
            reply="ok",
            profile_updates={"tone": "playful", "user_id": "evil", "language": "klingon"},
        )
    )
    await say(pipeline, channel, ADMIN, "be playful")
    profile = await pipeline.repos.profiles.get(user.id)
    assert profile.tone.value == "playful" and profile.user_id == user.id
    brain.script.append(
        Interpretation(
            intent=Intent.ADD_PERSON,
            person_upsert=Person(
                owner_user_id="someone-else",
                name="Mom",
                phone="9822222222",
                contact_consent=PersonConsent.OPTED_IN,
            ),
        )
    )
    await say(pipeline, channel, ADMIN, "add mom 9822222222")
    mom = [p for p in await pipeline.repos.people.list_for_owner(user.id) if p.name == "Mom"][0]
    assert mom.contact_consent == PersonConsent.NOT_ASKED and mom.phone == "+919822222222"


# ---------------------------------------------------------------------- circle member replies


async def test_circle_member_opt_in_and_relay(pipeline, channel, wired):
    user = await onboard(pipeline, channel)
    dad = await pipeline.repos.people.upsert(
        Person(owner_user_id=user.id, name="Ramesh", phone="+919811110000")
    )
    r = await wired.notifier.request_person_opt_in(dad, requester_name="Rahul", what="doctor visit")
    assert r.ok
    await say(pipeline, channel, dad.phone, "haan")
    dad = await pipeline.repos.people.get(dad.id)
    assert dad.contact_consent == PersonConsent.OPTED_IN
    assert "said yes" in channel.render(channel.last_to(ADMIN))
    assert await pipeline.repos.consents.has(
        user.id, ConsentKind.BENEFICIARY_CONTACT, person_id=dad.id
    )

    await say(pipeline, channel, dad.phone, "delete everything")  # never a command
    assert channel.render(channel.last_to(ADMIN)) == 'Ramesh replied: "delete everything"'
    assert (await pipeline.repos.users.get(user.id)).status == UserStatus.ACTIVE
    assert await pipeline.repos.users.get_by_phone(dad.phone) is None  # not onboarded as a user
    await say(pipeline, channel, dad.phone, "STOP")
    assert (await pipeline.repos.people.get(dad.id)).contact_consent == PersonConsent.OPTED_OUT
    assert channel.messages_to(dad.phone)[-1].template is not None  # only the opt-in went to dad


# ---------------------------------------------------------------------- cost tracking


async def test_cost_alert_once_per_month_and_never_user_facing(pipeline, channel):
    user = await onboard(pipeline, channel)
    sent_before = len(channel.outbox)
    threshold = pipeline.settings.cost_alert_inr_per_user_month
    await pipeline.costs.record(user.id, threshold / 2, kind="call")
    assert await pipeline.costs.month_total(user.id) == pytest.approx(threshold / 2)
    await pipeline.costs.record(user.id, threshold, kind="call")
    assert not await pipeline.costs.check(user.id)  # already alerted this month
    alerts = [
        a for a in await pipeline.repos.audit.list_for_user(user.id) if a.action == "ops.cost_alert"
    ]
    assert len(alerts) == 1
    assert len(channel.outbox) == sent_before
    pipeline.clock.advance(timedelta(days=40).total_seconds())
    assert await pipeline.costs.month_total(user.id) == 0


async def test_nudge_button_delegates_to_proactive(pipeline, channel, wired):
    from friday.core.models import AutonomyCategory, Nudge, NudgeKind, ReplyButton, nudge_button_id

    user = await onboard(pipeline, channel)
    nudge = await pipeline.repos.nudges.add(
        Nudge(
            user_id=user.id,
            kind=NudgeKind.PATTERN,
            category=AutonomyCategory.ROUTINES,
            dedupe_key="p:1",
        )
    )
    seen = []

    class Proactive:
        async def handle_nudge_action(self, n, action):  # noqa: ANN001
            seen.append((n.id, action))

    wired.override("proactive", Proactive())
    await wired.notifier.notify_user(
        user.id,
        "Book usual haircut?",
        buttons=[ReplyButton(id=nudge_button_id(nudge.id, "yes"), title="Book")],
    )
    await say(pipeline, channel, ADMIN, "1")
    assert seen == [(nudge.id, "yes")]


async def test_nudge_button_fallback_without_proactive(pipeline, channel, wired, engine):
    from friday.core.models import (
        AutonomyCategory,
        Nudge,
        NudgeKind,
        NudgeStatus,
        ReplyButton,
        nudge_button_id,
    )

    user = await onboard(pipeline, channel)
    nudge = await pipeline.repos.nudges.add(
        Nudge(
            user_id=user.id,
            kind=NudgeKind.PATTERN,
            category=AutonomyCategory.ROUTINES,
            dedupe_key="p:2",
            proposed_task=TaskSpec(type=TaskType.BOOKING, goal="usual haircut"),
        )
    )
    wired.override("proactive", None)
    await wired.notifier.notify_user(
        user.id, "Book?", buttons=[ReplyButton(id=nudge_button_id(nudge.id, "yes"), title="Book")]
    )
    await say(pipeline, channel, ADMIN, "1")
    assert (await pipeline.repos.nudges.get(nudge.id)).status == NudgeStatus.ACTED
    assert engine.calls[-1][0] == "submit"
