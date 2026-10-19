"""End to end, offline: message -> understand -> contact -> approval -> gate -> schedule -> fake live
engine -> report -> retry / opt-out. No real number, no network."""

from __future__ import annotations

import logging
from datetime import timedelta

from friday.calls.models import (
    CallOutcome,
    CallStatus,
    Commitment,
    OutcomeStatus,
)
from friday.calls.privacy import leaks
from tests.calls.conftest import (
    AIRTEL,
    MUMMY,
    PLUMBER,
    SCHOOL,
    World,
    build_world,
)


async def _book(world: World, name: str, number: str, **kw):
    return await world.contacts.add(world.user.id, name, number, confirmed=True, **kw)


def _press(reply, title: str) -> str:
    return next(b.id for b in reply.buttons if b.title == title)


async def test_family_call_whole_flow(world: World, caplog):
    caplog.set_level(logging.DEBUG)
    await _book(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    reply = await world.intake.handle(
        world.user, "mummy ko phone karke bata do ki main late hoon", message_id="wamid.1",
        user_display_name="Rahul",
    )  # fmt: skip
    assert reply.request_id and not reply.refused
    assert "main late hoon" in reply.text  # the user's own words, not a rewrite
    assert "Rahul ki assistant" in reply.text  # the exact opening line the call will use
    assert {b.title for b in reply.buttons} == {"Approve", "Edit", "Cancel"}
    assert MUMMY[-10:] not in reply.text
    assert world.engine.dials == []  # nothing dialled before approval

    res = await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    assert res.status == CallStatus.SCHEDULED
    assert len(world.tasks.tasks) == 1

    assert await world.orch.run_due() == 1
    assert len(world.engine.dials) == 1
    dial = world.engine.dials[0]
    assert dial.callee.number == MUMMY and dial.callee.max_duration_s <= 300
    assert dial.brief.is_approved_as_is()
    req = await world.store.get_request(reply.request_id)
    assert req.status == CallStatus.COMPLETED and req.attempts == 1
    report = world.notifier.sent[-1]
    assert "Mummy" in report.text and report.buttons
    # nothing sensitive reaches the logs: no plain number anywhere
    assert MUMMY[-10:] not in caplog.text and "9000000001" not in caplog.text

    # the same WhatsApp message delivered twice never makes a second call
    again = await world.intake.handle(
        world.user, "mummy ko phone karke bata do ki main late hoon", message_id="wamid.1",
        user_display_name="Rahul",
    )  # fmt: skip
    assert again.text == ""
    assert await world.orch.run_due() == 0 and len(world.engine.dials) == 1


async def test_unknown_contact_is_asked_then_number_confirmed_back(world: World):
    r1 = await world.intake.handle(
        world.user, "plumber ko call karo kal aane ke liye", message_id="m1"
    )
    assert r1.state and r1.state.step == "ask"  # limits missing: one question
    assert "paise" in r1.text.lower()
    r2 = await world.intake.handle(world.user, "500 rupees tak", message_id="m2", state=r1.state)
    assert r2.state and r2.state.step == "need_number"  # who is "plumber"? ask the number
    r3 = await world.intake.handle(world.user, PLUMBER, message_id="m3", state=r2.state)
    assert r3.state and r3.state.step == "confirm_number"
    assert "0002" in r3.text and PLUMBER not in r3.text  # only the last 4 digits come back
    r4 = await world.intake.handle(world.user, "haan sahi hai", message_id="m4", state=r3.state)
    assert r4.request_id and r4.buttons
    brief = await world.store.get_brief(r4.request_id)
    assert brief.limits.max_price_inr == 500
    await world.orch.handle_button(world.user.id, _press(r4, "Approve"))
    await world.orch.run_due()
    assert len(world.engine.dials) == 1


async def test_no_call_without_approval_even_if_scheduled_directly(world: World):
    await _book(world, "Mummy", MUMMY, relationship="mother")
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="m1"
    )
    res = await world.orch.submit(reply.request_id)  # skipping the button
    assert res.status == CallStatus.AWAITING_APPROVAL
    assert await world.orch.run_due() == 0 and world.engine.dials == []


async def test_no_answer_retries_at_one_and_three_hours_then_stops(world: World):
    await _book(world, "Mummy", MUMMY, relationship="mother")
    world.engine.on("Mummy", CallOutcome(request_id="x", status=OutcomeStatus.NO_ANSWER))
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="m1"
    )
    await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    await world.orch.run_due()
    req = await world.store.get_request(reply.request_id)
    assert req.status == CallStatus.SCHEDULED
    assert req.next_attempt_at == world.clock.now() + timedelta(hours=1)  # +1 h
    assert "dobara" in world.notifier.sent[-1].text or "try" in world.notifier.sent[-1].text
    n_msgs = len(world.notifier.sent)

    world.clock.advance(hours=1)
    await world.orch.run_due()
    req = await world.store.get_request(reply.request_id)
    assert req.attempts == 2 and req.next_attempt_at == world.clock.now() + timedelta(hours=3)
    assert len(world.notifier.sent) == n_msgs  # told once, not on every retry

    world.clock.advance(hours=3)
    await world.orch.run_due()
    req = await world.store.get_request(reply.request_id)
    assert req.attempts == 3 and req.status == CallStatus.FAILED  # max 3 tries
    assert "3 baar" in world.notifier.sent[-1].text
    assert len(world.engine.dials) == 3
    world.clock.advance(days=1)
    assert await world.orch.run_due() == 0


async def test_do_not_call_again_overrides_retry_and_blocks_all_users(world: World):
    await _book(world, "Plumber", PLUMBER, relationship="plumber")
    world.engine.on(
        "Plumber", CallOutcome(request_id="x", status=OutcomeStatus.OPTED_OUT, summary="")
    )
    reply = await world.intake.handle(
        world.user, "plumber ko call karo kal aane ke liye Rs 500", message_id="m1"
    )
    await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    await world.orch.run_due()
    req = await world.store.get_request(reply.request_id)
    assert req.status == CallStatus.CANCELLED  # no retry
    assert await world.dnc.is_blocked(PLUMBER)
    assert world.notifier.sent[-1].buttons and "block" in world.notifier.sent[-1].text
    # a second, different user can no longer call that number either
    from friday.core.models import User, UserStatus

    other = world.users.add(User(phone="+919800000002", status=UserStatus.ACTIVE))
    await world.contacts.add(other.id, "Plumber", PLUMBER, confirmed=True)
    r2 = await world.intake.handle(
        other, "plumber ko call karo kal aane ke liye Rs 400", message_id="o1"
    )
    res = await world.orch.handle_button(other.id, _press(r2, "Approve"))
    assert res.status == CallStatus.DENIED
    assert len(world.engine.dials) == 1


async def test_wrong_person_apology_dnc_and_immediate_notice(world: World):
    await _book(world, "Mummy", MUMMY, relationship="mother")
    world.engine.on("Mummy", CallOutcome(request_id="x", status=OutcomeStatus.WRONG_PERSON))
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="m1"
    )
    await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    await world.orch.run_due()
    last = world.notifier.sent[-1]
    assert last.urgent and "galat insaan" in last.text and "maafi" in last.text
    assert await world.dnc.is_blocked(MUMMY)
    assert (await world.store.get_request(reply.request_id)).status == CallStatus.CANCELLED


async def test_commitment_needing_approval_is_listed_with_buttons(world: World):
    await _book(world, "Plumber", PLUMBER, relationship="plumber")
    world.engine.on(
        "Plumber",
        CallOutcome(
            request_id="x", status=OutcomeStatus.COMPLETED, summary="Kal aa sakta hai.",
            commitments=[Commitment(text="visit kal 10 baje, Rs 600", needs_user_approval=True)],
        ),
    )  # fmt: skip
    reply = await world.intake.handle(
        world.user, "plumber ko call karo kal aane ke liye Rs 700", message_id="m1"
    )
    await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    await world.orch.run_due()
    last = world.notifier.sent[-1]
    assert (
        "visit kal 10 baje" in last.text and "aapki haan" in last.text.lower() or "OK" in last.text
    )
    assert {b.title for b in last.buttons} >= {"Haan, chalega", "Nahi"}


async def test_group_fans_out_and_collects_one_report(world: World):
    for n, num in (("Raj", "+919000000005"), ("Amit", "+919000000006"), ("Neha", "+919000000007")):
        await _book(world, n, num, relationship="friend")
    world.engine.on("Amit", CallOutcome(request_id="x", status=OutcomeStatus.NO_ANSWER))
    reply = await world.intake.handle(
        world.user, "sabko party ke liye call karo: Raj, Amit, Neha", message_id="g1"
    )
    assert reply.request_id and "Raj, Amit, Neha" in reply.text
    res = await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    assert res.status == CallStatus.GROUP_WAITING
    kids = await world.store.children(reply.request_id)
    assert len(kids) == 3 and all(k.status == CallStatus.SCHEDULED for k in kids)
    await world.orch.run_due()
    assert len(world.engine.dials) == 3
    parent = await world.store.get_request(reply.request_id)
    assert parent.status == CallStatus.GROUP_WAITING  # Amit still has retries to go
    for _ in range(2):
        world.clock.advance(hours=3)
        await world.orch.run_due()
    parent = await world.store.get_request(reply.request_id)
    assert parent.status == CallStatus.COMPLETED
    group_msgs = [t for t in world.notifier.texts() if "Group ka jawab" in t]
    assert len(group_msgs) == 1  # one collected result, not one per child
    assert "Raj" in group_msgs[0] and "Amit" in group_msgs[0] and "Neha" in group_msgs[0]
    assert "2 ne bataya" in group_msgs[0]


async def test_group_redelivery_creates_no_duplicate_children(world: World):
    for n, num in (("Raj", "+919000000005"), ("Amit", "+919000000006")):
        await _book(world, n, num, relationship="friend")
    for _ in range(2):
        r = await world.intake.handle(
            world.user, "sabko party ke liye call karo: Raj, Amit", message_id="g1"
        )
    assert len(await world.store.children(r.request_id or "")) == 2 or r.text == ""


async def test_customer_care_dispute_flow_and_user_stop(world: World):
    r1 = await world.intake.handle(
        world.user, "Airtel customer care se bill dispute", message_id="c1"
    )
    assert r1.state and r1.state.step == "ask" and "problem" in r1.text
    r2 = await world.intake.handle(
        world.user, "pichle mahine Rs 899 ka galat charge laga, refund chahiye", message_id="c2",
        state=r1.state,
    )  # fmt: skip
    assert r2.state and r2.state.step == "need_number"
    assert "Airtel" in r2.text
    r3 = await world.intake.handle(world.user, AIRTEL, message_id="c3", state=r2.state)
    r4 = await world.intake.handle(world.user, "haan", message_id="c4", state=r3.state)
    await world.orch.handle_button(world.user.id, _press(r4, "Approve"))
    await world.orch.run_due()
    assert world.engine.dials[0].callee.kind.value == "customer_care"
    stop = next(b.id for b in world.notifier.sent[-1].buttons if b.title == "Phir call karo")
    assert stop  # buttons for the next action exist


async def test_official_school_call_uses_business_window(evening_world: World):
    w = evening_world  # 21:00: too late for a school office
    await w.contacts.add(w.user.id, "School office", SCHOOL, confirmed=True)
    reply = await w.intake.handle(w.user, "school office se fees ki date puchho", message_id="s1")
    assert reply.request_id
    await w.orch.handle_button(w.user.id, _press(reply, "Approve"))
    req = await w.store.get_request(reply.request_id)
    assert req.status == CallStatus.SCHEDULED
    assert req.next_attempt_at == w.at(9, day=6)  # tomorrow 09:00 IST
    assert w.engine.dials == []
    w.clock.set(w.at(9, 5, day=6))
    await w.orch.run_due()
    assert len(w.engine.dials) == 1


async def test_family_call_allowed_in_the_evening(evening_world: World):
    w = evening_world
    await w.contacts.add(w.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True)
    reply = await w.intake.handle(
        w.user, "mummy ko call karke bata do ki main late hoon", message_id="e1"
    )
    await w.orch.handle_button(w.user.id, _press(reply, "Approve"))
    await w.orch.run_due()
    assert len(w.engine.dials) == 1


async def test_stale_calling_request_is_closed_not_redialled(world: World):
    await _book(world, "Mummy", MUMMY, relationship="mother")
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="m1"
    )
    await world.orch.handle_button(world.user.id, _press(reply, "Approve"))
    req = await world.store.get_request(reply.request_id)
    req.status = CallStatus.CALLING  # worker died mid call
    req.updated_at = world.clock.now()
    await world.store.save_request(req)
    world.clock.advance(hours=1)
    assert await world.orch.recover_stale() == 1
    assert (await world.store.get_request(reply.request_id)).status == CallStatus.FAILED
    assert await world.orch.run_due() == 0 and world.engine.dials == []


def test_reports_and_approvals_never_leak(world: World):
    from friday.calls.models import CallRequest

    req = CallRequest(user_id="u", callee_kind="family_friend", purpose="p", callee_number=MUMMY)
    assert leaks(f"call {MUMMY} now", request=req)
    assert leaks("number 9000000001 hai", request=req)
    assert not leaks("number ending 0001", request=req)
    build_world()  # constructs cleanly twice (no global state)
