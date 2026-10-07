"""Business call-backs, missed calls and business replies (BRIEF E30-35)."""

from __future__ import annotations

from datetime import timedelta

from friday.core.events import Event
from friday.core.models import (
    Business,
    CallOutcome,
    CallResult,
    ContactTarget,
    DialStatus,
    TargetKind,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
    User,
    UserStatus,
)
from friday.db.repositories import InboundKind, MatchStatus

BIZ = "+919845000001"
FRIDAY_A = "+918000000001"
FRIDAY_B = "+918000000002"


async def _setup(repos, *, goal="Haircut Saturday", name="Rahul Sharma") -> tuple[User, Task]:
    user = await repos.users.get_by_phone("+919800000301") or await repos.users.add(
        User(phone="+919800000301", status=UserStatus.ACTIVE)
    )
    task = await repos.tasks.add(
        Task(
            requester_user_id=user.id,
            type=TaskType.BOOKING,
            status=TaskStatus.AWAITING_APPROVAL,
            spec=TaskSpec(type=TaskType.BOOKING, goal=goal, on_behalf_of=name, business_phone=BIZ),
            target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks", phone=BIZ),
        )
    )
    return user, task


async def test_call_memory_recorded_by_save_call_and_sticky_number(wired, clock):
    repos = wired.repos
    user, task = await _setup(repos)
    result = CallResult(
        task_id=task.id,
        provider="simulator",
        to_phone=BIZ,
        dial_status=DialStatus.NO_ANSWER,
        outcome=CallOutcome.NO_ANSWER,
        started_at=clock.now(),
    )
    await repos.tasks.save_call(result)
    mem = await repos.calls.for_task(task.id)
    assert len(mem) == 1 and mem[0].business_phone == BIZ and mem[0].user_id == user.id
    assert mem[0].outcome == CallOutcome.NO_ANSWER and mem[0].friday_number is None
    # engine/voice records the caller ID afterwards (same row, by call_id)
    await repos.calls.record_outbound(
        task_id=task.id,
        user_id=user.id,
        business_phone=BIZ,
        friday_number=FRIDAY_A,
        call_id=result.call_id,
    )
    mem = await repos.calls.for_task(task.id)
    assert len(mem) == 1 and mem[0].friday_number == FRIDAY_A
    assert await repos.calls.sticky_number(BIZ) == FRIDAY_A
    assert await repos.calls.choose_number(BIZ, [FRIDAY_B, FRIDAY_A]) == FRIDAY_A
    assert await repos.calls.choose_number("+919845999999", [FRIDAY_A, FRIDAY_B]) in (
        FRIDAY_A,
        FRIDAY_B,
    )
    # re-saving the call keeps the caller id
    await repos.tasks.save_call(result.model_copy(update={"outcome": CallOutcome.PENDING_APPROVAL}))
    mem = await repos.calls.for_task(task.id)
    assert mem[0].friday_number == FRIDAY_A and mem[0].outcome == CallOutcome.PENDING_APPROVAL


async def test_match_matched_ambiguous_unmatched_completed(wired, clock):
    repos = wired.repos
    user, t1 = await _setup(repos)
    await repos.calls.record_outbound(
        task_id=t1.id, user_id=user.id, business_phone=BIZ, friday_number=FRIDAY_A, call_id="c1"
    )
    m = await repos.calls.match(BIZ, friday_number=FRIDAY_A)
    assert m.status == MatchStatus.MATCHED and m.task_id == t1.id and m.user_id == user.id

    _, t2 = await _setup(repos, goal="Facial Sunday")
    clock.advance(60)
    await repos.calls.record_outbound(
        task_id=t2.id, user_id=user.id, business_phone=BIZ, friday_number=FRIDAY_B, call_id="c2"
    )
    amb = await repos.calls.match(BIZ)
    assert amb.status == MatchStatus.AMBIGUOUS and amb.task_id is None and amb.user_id is None
    assert {c.task_id for c in amb.candidates} == {t1.id, t2.id}
    # the dialled Friday number disambiguates
    assert (await repos.calls.match(BIZ, friday_number=FRIDAY_B)).task_id == t2.id

    await repos.tasks.set_status(t1.id, TaskStatus.COMPLETED)
    await repos.tasks.set_status(t2.id, TaskStatus.COMPLETED)
    done = await repos.calls.match(BIZ)
    assert done.status == MatchStatus.MATCHED and done.completed_only and done.task_id == t2.id

    assert (await repos.calls.match("+919811999999")).status == MatchStatus.UNMATCHED
    clock.advance(timedelta(days=31).total_seconds())
    assert (await repos.calls.match(BIZ)).status == MatchStatus.UNMATCHED  # outside window


async def test_inbound_call_and_missed_call_go_to_engine(wired, pipeline, engine):
    repos = wired.repos
    user, task = await _setup(repos)
    await repos.calls.record_outbound(
        task_id=task.id, user_id=user.id, business_phone=BIZ, friday_number=FRIDAY_A, call_id="c1"
    )
    cb = pipeline.callbacks
    match, contact = await cb.on_inbound_call(
        "98450 00001", FRIDAY_A, answered=True, provider_ref="CA1"
    )
    assert match.status == MatchStatus.MATCHED
    assert engine.calls[-1][0] == "handle_business_callback"
    stored = await repos.calls.get_inbound(contact.id)
    assert stored.kind == InboundKind.CALL and stored.handled and stored.task_id == task.id

    match, contact = await cb.on_inbound_call(BIZ, None, answered=False)
    assert engine.calls[-1][0] == "handle_missed_call"
    assert (await repos.calls.inbound_for_task(task.id))[-1].kind == InboundKind.MISSED_CALL

    ctx = await cb.safe_context(match)
    assert ctx == {"on_behalf_of": "Rahul", "about": "Haircut Saturday"}
    greeting = cb.greeting(ctx)
    assert "AI assistant" in greeting and "Rahul" in greeting and "Sharma" not in greeting


async def test_unmatched_caller_gets_no_details(wired, pipeline, engine):
    repos = wired.repos
    await _setup(repos)
    match, contact = await pipeline.callbacks.on_inbound_call(
        "+919811000000", FRIDAY_A, answered=True, call_id="sim-call-7"
    )
    assert match.status == MatchStatus.UNMATCHED and match.user_id is None and not match.candidates
    name, (m, c) = engine.calls[-1]
    assert name == "handle_unknown_caller" and c.call_id == "sim-call-7"
    stored = await repos.calls.get_inbound(contact.id)
    assert stored.user_id is None and stored.task_id is None and stored.handled
    ctx = await pipeline.callbacks.safe_context(match)
    assert ctx == {}
    assert "Rahul" not in pipeline.callbacks.greeting(ctx)
    # an unmatched MISSED call goes to handle_missed_call (engine just logs it)
    await pipeline.callbacks.on_inbound_call("+919811000000", None, answered=False)
    assert engine.calls[-1][0] == "handle_missed_call"
    assert engine.calls[-1][1][0].status == MatchStatus.UNMATCHED


async def test_ambiguous_caller_gets_no_details(wired, pipeline):
    repos = wired.repos
    user, t1 = await _setup(repos)
    _, t2 = await _setup(repos, goal="Facial")
    for i, t in enumerate((t1, t2)):
        await repos.calls.record_outbound(
            task_id=t.id, user_id=user.id, business_phone=BIZ, call_id=f"c{i}"
        )
    match, _ = await pipeline.callbacks.on_inbound_call(BIZ, None, answered=True)
    assert match.status == MatchStatus.AMBIGUOUS
    assert await pipeline.callbacks.safe_context(match) == {}


async def test_bus_events_from_voice_are_wired(wired, pipeline, engine, bus):
    repos = wired.repos
    user, task = await _setup(repos)
    await repos.calls.record_outbound(
        task_id=task.id, user_id=user.id, business_phone=BIZ, call_id="c1"
    )
    pipeline.callbacks.subscribe()

    class MissedCallReceived(Event):  # shape the voice side will publish
        from_phone: str
        to_number: str | None = None
        provider_call_id: str | None = None

    await bus.publish(
        MissedCallReceived(from_phone=BIZ, to_number=FRIDAY_A, provider_call_id="CA9")
    )
    assert engine.calls[-1][0] == "handle_missed_call"
    assert engine.calls[-1][1][1].provider_ref == "CA9"
    pipeline.callbacks.unsubscribe()


async def test_business_message_goes_to_engine_not_user_flow(wired, pipeline, channel, engine):
    repos = wired.repos
    user, task = await _setup(repos)
    await repos.calls.record_outbound(
        task_id=task.id, user_id=user.id, business_phone=BIZ, call_id="c1"
    )
    await pipeline.handle(channel.make_inbound(BIZ, "Slot at 6pm is free now"))
    name, (msg, match) = engine.calls[-1]
    assert name == "handle_business_message" and match.task_id == task.id
    assert msg.text == "Slot at 6pm is free now"
    assert await repos.users.get_by_phone(BIZ) is None  # not onboarded as a user
    assert channel.messages_to(BIZ) == []  # nothing (no user details) sent back
    contacts = await repos.calls.inbound_for_task(task.id)
    assert contacts[-1].kind == InboundKind.MESSAGE and contacts[-1].handled

    # a known business with no call memory is still routed as a business
    other = await repos.businesses.upsert(Business(name="Chemist", phone="+919845000002"))
    await pipeline.handle(channel.make_inbound(other.phone, "menu attached"))
    name, (msg, match) = engine.calls[-1]
    assert msg.business_id == other.id and match.status == MatchStatus.UNMATCHED
    assert channel.messages_to(other.phone) == []


async def test_purge_removes_call_memory(wired):
    repos = wired.repos
    user, task = await _setup(repos)
    await repos.calls.record_outbound(
        task_id=task.id, user_id=user.id, business_phone=BIZ, call_id="c1"
    )
    await repos.purger.purge_user(user.id)
    assert (await repos.calls.match(BIZ)).status == MatchStatus.UNMATCHED


async def test_voice_event_field_names_and_call_id(wired, pipeline, engine, bus):
    """Voice's events: ``to_number`` (or ``to_phone``) + ``provider_call_id``/``call_id``."""
    repos = wired.repos
    user, t1 = await _setup(repos)
    _, t2 = await _setup(repos, goal="Facial")
    await repos.calls.record_outbound(
        task_id=t1.id, user_id=user.id, business_phone=BIZ, friday_number=FRIDAY_A, call_id="c1"
    )
    await repos.calls.record_outbound(
        task_id=t2.id, user_id=user.id, business_phone=BIZ, friday_number=FRIDAY_B, call_id="c2"
    )
    pipeline.callbacks.subscribe()

    class InboundCallReceived(Event):  # alternative producer spelling: to_phone + call_id
        from_phone: str
        to_phone: str | None = None
        call_id: str | None = None

    await bus.publish(InboundCallReceived(from_phone=BIZ, to_phone=FRIDAY_B, call_id="CALL-1"))
    name, (match, contact) = engine.calls[-1]
    assert name == "handle_business_callback"
    assert match.friday_number == FRIDAY_B and match.task_id == t2.id  # disambiguated
    assert contact.call_id == "CALL-1" and contact.provider_ref == "CALL-1"

    class VoiceInbound(Event):  # mirrors friday/voice/events.py (no cross-package import)
        from_phone: str
        to_number: str | None = None
        provider_call_id: str | None = None

    VoiceInbound.__name__ = "InboundCallReceived"

    await bus.publish(VoiceInbound(from_phone=BIZ, to_number=FRIDAY_A, provider_call_id="PC-9"))
    name, (match, contact) = engine.calls[-1]
    assert match.task_id == t1.id and contact.call_id == "PC-9"
    stored = await repos.calls.get_inbound(contact.id)
    assert stored.call_id == "PC-9" and stored.friday_number == FRIDAY_A
    pipeline.callbacks.unsubscribe()
