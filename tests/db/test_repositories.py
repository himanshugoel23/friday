"""Round-trip tests: every domain model <-> row through the repositories."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from friday.core.models import (
    AccountIdentifier,
    AuditEntry,
    AutonomyCategory,
    AutonomyLevel,
    AutonomySetting,
    Beneficiary,
    Budget,
    Business,
    BusinessCandidate,
    BusinessHours,
    CallDirection,
    CallOutcome,
    CallResult,
    CareOutcome,
    Channel,
    Consent,
    ConsentKind,
    ContactTarget,
    Delegation,
    DialStatus,
    Fact,
    FactKind,
    FeedbackType,
    GeoPoint,
    HotelBooking,
    HotelBookingMode,
    HotelBookingStatus,
    HotelProperty,
    InboundMessage,
    InteractionKind,
    Invite,
    Language,
    LocationPin,
    MessageKind,
    MidCallQuestion,
    Nudge,
    NudgeFeedback,
    NudgeKind,
    NudgeStatus,
    OpeningPeriod,
    OutboundMessage,
    Person,
    PersonConsent,
    Place,
    PlaceSource,
    Profile,
    QuestionPurpose,
    Quote,
    Recurrence,
    RecurrenceRule,
    ReplyButton,
    SendReceipt,
    ShortlistItem,
    Speaker,
    TargetKind,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
    TemplateRef,
    Tone,
    Transcript,
    User,
    UserAnswer,
    UserStatus,
    VendorInteraction,
)
from friday.db.repositories import Repositories, build_repositories, make_repositories
from friday.db.tables import AccountIdentifierRow, CallTurnRow


@pytest.fixture
def repos(db, clock) -> Repositories:
    return make_repositories(db, clock, "test-secret")


async def _user(repos: Repositories, phone: str = "+919800000001") -> User:
    return await repos.users.add(User(phone=phone))


async def test_factory_builds_bundle(container):
    r = build_repositories(container)
    assert isinstance(r, Repositories)
    assert container.repos is not None


async def test_user_round_trip(repos, clock):
    u = User(phone="+919800000001", status=UserStatus.ACTIVE, last_inbound_at=clock.now())
    await repos.users.add(u)
    got = await repos.users.get(u.id)
    assert got == u
    assert await repos.users.get_by_phone("+919800000001") == u
    u.pin_failed_attempts = 2
    await repos.users.save(u)
    assert (await repos.users.get(u.id)).pin_failed_attempts == 2
    assert [x.id for x in await repos.users.list_active()] == [u.id]


async def test_profile_consent_invite_autonomy(repos, clock):
    u = await _user(repos)
    p = Profile(user_id=u.id, name="Rahul", city="Pune", language=Language.EN, tone=Tone.FORMAL)
    await repos.profiles.save(p)
    assert await repos.profiles.get(u.id) == p
    assert (await repos.profiles.get_or_default("nope")).user_id == "nope"

    c = Consent(user_id=u.id, kind=ConsentKind.TERMS_PRIVACY, granted=True, evidence_text="I agree")
    await repos.consents.add(c)
    assert await repos.consents.latest(u.id, ConsentKind.TERMS_PRIVACY) == c
    assert await repos.consents.has(u.id, ConsentKind.TERMS_PRIVACY)
    assert not await repos.consents.has(u.id, ConsentKind.PROACTIVE)

    inv = Invite(code="FRI-ABC123", created_by_user_id=u.id)
    await repos.invites.add(inv)
    assert await repos.invites.get("FRI-ABC123") == inv
    u2 = await _user(repos, "+919800000002")
    assert (await repos.invites.redeem("FRI-ABC123", u2.id)).redeemed_by_user_id == u2.id
    assert await repos.invites.redeem("FRI-ABC123", u2.id) is None  # single use
    assert await repos.invites.count_by_creator(u.id) == 1

    expired = Invite(code="FRI-OLD000", expires_at=clock.now() - timedelta(days=1))
    await repos.invites.add(expired)
    assert await repos.invites.redeem("FRI-OLD000", u2.id) is None

    a = AutonomySetting(
        user_id=u.id, category=AutonomyCategory.BOOKINGS, level=AutonomyLevel.ACT_WITH_APPROVAL
    )
    await repos.autonomy.upsert(a)
    assert await repos.autonomy.list_for_user(u.id) == [a]
    default = await repos.autonomy.get(u.id, AutonomyCategory.FAMILY)
    assert default.level == AutonomyLevel.SUGGEST


async def test_people_and_places(repos):
    u = await _user(repos)
    dad = Person(
        owner_user_id=u.id,
        name="Ramesh",
        relation="father",
        aliases=["papa"],
        phone="+919811111111",
        language=Language.HI,
        notes="diabetic",
        contact_consent=PersonConsent.OPTED_IN,
    )
    await repos.people.upsert(dad)
    assert await repos.people.get(dad.id) == dad
    assert await repos.people.list_for_owner(u.id) == [dad]
    assert await repos.people.find_by_phone("+919811111111") == [dad]

    home = Place(
        owner_user_id=u.id,
        label="Mom & Dad's home",
        aliases=["ghar"],
        location=GeoPoint(lat=18.5, lng=73.8),
        source=PlaceSource.WA_LOCATION,
        person_id=dad.id,
    )
    await repos.places.upsert(home)
    assert await repos.places.get(home.id) == home
    pin = Place(owner_user_id=u.id, label="current", ephemeral=True)
    await repos.places.upsert(pin)
    assert await repos.places.list_for_owner(u.id) == [home]
    assert len(await repos.places.list_for_owner(u.id, include_ephemeral=True)) == 2
    assert await repos.places.delete(pin.id)
    assert await repos.people.delete(dad.id)
    assert await repos.people.get(dad.id) is None


async def test_business_and_vendor_memory(repos, clock):
    u = await _user(repos)
    b = Business(
        name="Looks Salon",
        phone="+918040000001",
        whatsapp_phone="+919840000001",
        category="salon",
        location=GeoPoint(lat=12.9, lng=77.6),
        hours=BusinessHours(periods=[OpeningPeriod(weekday=0, open="10:00", close="20:00")]),
        best_call_times=["after 11am"],
        ivr_notes=["2 then 9"],
        language_hint=Language.KN,
        directory_provider="simulator",
        directory_place_id="sim-1",
        rating=4.5,
        review_count=100,
    )
    await repos.businesses.upsert(b)
    assert await repos.businesses.get(b.id) == b
    assert await repos.businesses.get_by_phone("+918040000001") == b
    assert await repos.businesses.get_by_phone("+919840000001") == b
    assert await repos.businesses.get_by_directory_id("simulator", "sim-1") == b

    vi = VendorInteraction(
        user_id=u.id, business_id=b.id, kind=InteractionKind.PAID, amount_inr=400, rating=5
    )
    await repos.businesses.add_interaction(vi)
    assert await repos.businesses.interactions(u.id) == [vi]
    assert await repos.businesses.interactions(u.id, business_id="x") == []
    assert await repos.businesses.known_for_user(u.id) == [b]


async def test_identifiers_encrypted_at_rest(repos, db):
    u = await _user(repos)
    ident = AccountIdentifier(user_id=u.id, company="Airtel", label="account no", value="1234567890")
    await repos.identifiers.upsert(ident)
    assert await repos.identifiers.list_for_user(u.id) == [ident]
    assert await repos.identifiers.get_many([ident.id]) == [ident]
    async with db.session() as s:
        row = (await s.execute(select(AccountIdentifierRow))).scalar_one()
        assert "1234567890" not in row.value_encrypted
        assert row.last4 == "7890"
    other = make_repositories(db, None, "different-key")
    with pytest.raises(ValueError):
        await other.identifiers.get(ident.id)


async def test_facts_upsert_by_key(repos):
    u = await _user(repos)
    f = Fact(
        user_id=u.id,
        kind=FactKind.DATE,
        key="rent_due",
        value="5th",
        due_on=date(2026, 2, 5),
        recurrence=Recurrence.MONTHLY,
    )
    await repos.facts.upsert(f)
    assert await repos.facts.list_for_user(u.id) == [f]
    f2 = Fact(user_id=u.id, kind=FactKind.DATE, key="rent_due", value="7th", due_on=date(2026, 2, 7))
    await repos.facts.upsert(f2)
    facts = await repos.facts.list_for_user(u.id)
    assert len(facts) == 1 and facts[0].value == "7th" and facts[0].id == f.id
    assert len(await repos.facts.list_due_between(date(2026, 2, 1), date(2026, 2, 10))) == 1
    assert await repos.facts.delete(f.id)


async def test_messages_log_and_turns(repos, clock):
    u = await _user(repos)
    inbound = InboundMessage(
        channel=Channel.WHATSAPP,
        from_phone=u.phone,
        user_id=u.id,
        kind=MessageKind.LOCATION,
        text="here",
        location=LocationPin(lat=1.0, lng=2.0),
        provider_message_id="wamid.1",
        received_at=clock.now(),
    )
    await repos.messages.log_inbound(inbound)
    assert await repos.messages.seen_provider_id("wamid.1")
    clock.advance(5)
    out = OutboundMessage(
        channel=Channel.WHATSAPP,
        to_phone=u.phone,
        user_id=u.id,
        text="Got it",
        buttons=[ReplyButton(id="a:t:yes", title="Yes")],
        template=TemplateRef(key="nudge", params=["x"]),
    )
    await repos.messages.log_outbound(
        out, SendReceipt(message_id=out.id, provider_message_id="wamid.2", sent_at=clock.now())
    )
    stored = await repos.messages.get(out.id)
    assert stored.buttons[0].id == "a:t:yes" and stored.template.key == "nudge"
    turns = await repos.messages.recent_turns(u.id)
    assert [t.text for t in turns] == ["here", "Got it"]
    assert await repos.messages.update_status("wamid.2", ok=False, error="blocked")
    assert not (await repos.messages.get(out.id)).ok
    assert (await repos.messages.last_inbound_from(u.phone)).id == inbound.id


def _task(user_id: str, **kw) -> Task:
    spec = TaskSpec(
        type=TaskType.BOOKING,
        goal="Haircut",
        business_phone="+918040000001",
        budget=Budget(max_inr=800),
        delegation=Delegation(granted=True, max_price_inr=800),
    )
    return Task(requester_user_id=user_id, type=TaskType.BOOKING, spec=spec, **kw)


async def test_task_round_trip_and_queries(repos, clock):
    u = await _user(repos)
    dad = await repos.people.upsert(Person(owner_user_id=u.id, name="Dad"))
    cand = BusinessCandidate(provider="simulator", place_id="p1", name="Looks")
    t = _task(
        u.id,
        beneficiary=Beneficiary(person_id=dad.id),
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks", phone="+918040000001"),
        candidate=cand,
        shortlist=[ShortlistItem(candidate=cand, rank=1, reason="good")],
        delegation=Delegation(granted=True, max_price_inr=800),
        result=TaskResult(success=True, summary="done", quotes=[Quote(business_name="L", price_text="₹1")]),
        status=TaskStatus.SCHEDULED,
        next_attempt_at=clock.now(),
    )
    await repos.tasks.add(t)
    got = await repos.tasks.get(t.id)
    assert got == t
    assert [x.id for x in await repos.tasks.list_due(clock.now())] == [t.id]
    assert await repos.tasks.list_due(clock.now() - timedelta(seconds=1)) == []

    child = _task(u.id, parent_task_id=t.id)
    await repos.tasks.add(child)
    assert [x.id for x in await repos.tasks.list_children(t.id)] == [child.id]
    await repos.tasks.set_status(child.id, TaskStatus.COMPLETED)
    assert [x.id for x in await repos.tasks.list_for_user(u.id, open_only=True)] == [t.id]

    rec = _task(
        u.id,
        recurrence=RecurrenceRule(freq=Recurrence.WEEKLY, next_run_at=clock.now()),
        status=TaskStatus.SCHEDULED,
    )
    await repos.tasks.add(rec)
    due = {x.id for x in await repos.tasks.list_due(clock.now())}
    assert rec.id in due
    assert len(await repos.tasks.list_open()) == 2


async def test_save_call_round_trip_and_cost(repos, clock):
    u = await _user(repos)
    t = _task(u.id)
    await repos.tasks.add(t)
    q = MidCallQuestion(task_id=t.id, text="4 or 6?", options=["4pm", "6pm"],
                        purpose=QuestionPurpose.CHOOSE_OPTION, asked_at=clock.now())
    await repos.tasks.add_question(q)
    assert (await repos.tasks.open_question_for_user(u.id)).id == q.id
    ans = UserAnswer(question_id=q.id, text="6pm", option_index=1, answered_at=clock.now())
    assert await repos.tasks.answer_question(ans)
    assert not await repos.tasks.answer_question(ans)
    assert await repos.tasks.open_question_for_user(u.id) is None

    transcript = Transcript()
    transcript.add(Speaker.FRIDAY, "Hi", at=clock.now(), language=Language.HINGLISH)
    transcript.add(Speaker.CALLEE, "Haan", at=clock.now(), language=Language.HI, confidence=0.9)
    result = CallResult(
        task_id=t.id,
        provider="simulator",
        direction=CallDirection.OUTBOUND,
        to_phone="+918040000001",
        dial_status=DialStatus.ANSWERED,
        outcome=CallOutcome.PENDING_APPROVAL,
        transcript=transcript,
        collected={"slot": "6pm"},
        quotes=[Quote(business_name="Looks", amount_inr=400, price_text="₹400", task_id=t.id)],
        questions=[q],
        answers=[ans],
        languages_heard=[Language.HI],
        care=CareOutcome(ticket_number="SR1"),
        cost_inr_est=6.5,
        started_at=clock.now(),
        answered_at=clock.now(),
        ended_at=clock.now() + timedelta(seconds=60),
    )
    await repos.tasks.save_call(result)
    await repos.tasks.save_call(result)  # idempotent
    got = await repos.tasks.get_call(result.call_id)
    assert got.transcript == result.transcript
    assert got.quotes[0].amount_inr == 400 and got.quotes[0].call_id == result.call_id
    assert got.answers[0].text == "6pm"
    assert got.care.ticket_number == "SR1"
    assert got.outcome == CallOutcome.PENDING_APPROVAL
    assert len(await repos.tasks.list_calls(t.id)) == 1
    assert len(await repos.tasks.quotes_for_task(t.id)) == 1
    start = clock.now() - timedelta(days=1)
    assert await repos.costs.total_between(u.id, start, clock.now() + timedelta(days=1)) == 6.5
    async with repos.db.session() as s:
        assert len((await s.execute(select(CallTurnRow))).scalars().all()) == 2


async def test_hotel_booking_round_trip(repos):
    u = await _user(repos)
    t = _task(u.id)
    await repos.tasks.add(t)
    hb = HotelBooking(
        task_id=t.id,
        provider="simulator",
        mode=HotelBookingMode.DIRECT_HOLD,
        status=HotelBookingStatus.HELD,
        property=HotelProperty(provider="simulator", property_id="h1", name="Lake View"),
        check_in=date(2026, 3, 1),
        check_out=date(2026, 3, 3),
    )
    await repos.tasks.save_hotel_booking(hb, user_id=u.id)
    assert await repos.tasks.get_hotel_booking(hb.id) == hb
    assert await repos.tasks.hotel_bookings_checking_in(date(2026, 3, 1)) == [hb]


async def test_nudges(repos, clock):
    u = await _user(repos)
    n = Nudge(
        user_id=u.id,
        kind=NudgeKind.PATTERN,
        category=AutonomyCategory.ROUTINES,
        dedupe_key="pattern:haircut",
        buttons=[ReplyButton(id="n:x:yes", title="Book")],
        proposed_task=TaskSpec(type=TaskType.BOOKING, goal="haircut"),
    )
    await repos.nudges.add(n)
    assert await repos.nudges.get(n.id) == n
    assert await repos.nudges.exists(u.id, "pattern:haircut")
    n.status = NudgeStatus.SENT
    n.sent_at = clock.now()
    await repos.nudges.save(n)
    assert await repos.nudges.count_sent_between(
        u.id, clock.now() - timedelta(hours=1), clock.now() + timedelta(hours=1)
    ) == 1
    fb = NudgeFeedback(nudge_id=n.id, user_id=u.id, type=FeedbackType.IGNORED)
    await repos.nudges.add_feedback(fb)
    assert await repos.nudges.feedback_for_user(u.id) == [fb]
    n.status = NudgeStatus.IGNORED
    await repos.nudges.save(n)
    assert await repos.nudges.consecutive_ignored(u.id, NudgeKind.PATTERN) == 1


async def test_audit_and_purge(repos, clock):
    u = await _user(repos)
    await repos.profiles.save(Profile(user_id=u.id, name="Rahul"))
    dad = await repos.people.upsert(Person(owner_user_id=u.id, name="Dad"))
    await repos.places.upsert(Place(owner_user_id=u.id, label="Home", person_id=dad.id))
    await repos.facts.upsert(Fact(user_id=u.id, kind=FactKind.GENERAL, key="k", value="v"))
    await repos.tasks.add(_task(u.id))
    await repos.identifiers.upsert(AccountIdentifier(user_id=u.id, label="acct", value="99999999"))
    await repos.messages.log_inbound(
        InboundMessage(channel=Channel.SIMULATOR, from_phone=u.phone, user_id=u.id, text="hi")
    )
    await repos.invites.add(Invite(code="FRI-UNUSED", created_by_user_id=u.id))
    await repos.audit.add(AuditEntry(user_id=u.id, actor="user", action="x", detail={"name": "R"}))
    await repos.costs.record(u.id, 2.0, kind="llm")

    counts = await repos.purger.purge_user(u.id)
    assert counts["tasks"] == 1 and counts["people"] == 1
    tomb = await repos.users.get(u.id)
    assert tomb.status == UserStatus.DELETED and tomb.phone.startswith("del:")
    assert await repos.users.get_by_phone("+919800000001") is None
    assert await repos.profiles.get(u.id) is None
    assert await repos.people.list_for_owner(u.id) == []
    assert await repos.facts.list_for_user(u.id) == []
    assert await repos.tasks.list_for_user(u.id) == []
    assert await repos.identifiers.list_for_user(u.id) == []
    assert await repos.messages.list_for_user(u.id) == []
    assert await repos.invites.get("FRI-UNUSED") is None
    audit = await repos.audit.list_for_user(u.id)
    assert audit and audit[0].detail == {}
    # the phone can sign up again
    await _user(repos)
