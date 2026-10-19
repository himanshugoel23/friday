"""Scheduler glue: idempotency, gate before every dial, retries, callbacks, buttons, group rules."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.calls.models import (
    CalleeKind,
    CallOutcome,
    CallStatus,
    NextAction,
    OutcomeStatus,
)
from friday.calls.orchestrator import Member
from friday.calls.report import ACT_PREFIX
from friday.calls.settings import CallsSettings
from friday.calls.understand import RequestUnderstander
from tests.calls.conftest import MUMMY, PLUMBER, RAJ, World, build_world

U = RequestUnderstander()


async def approved(world: World, text="mummy ko call karke bata do ki main late hoon", mid="m1"):
    await world.contacts.add(world.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True)
    reply = await world.intake.handle(world.user, text, message_id=mid, user_display_name="Rahul")
    btn = next(b.id for b in reply.buttons if b.title == "Approve")
    await world.orch.handle_button(world.user.id, btn)
    return reply.request_id


async def test_submit_twice_creates_one_task_and_one_dial(world: World):
    rid = await approved(world)
    again = await world.orch.submit(rid)
    assert not again.created and len(world.tasks.tasks) == 1
    await world.orch.run_due()
    await world.orch.run_due()
    assert len(world.engine.dials) == 1


async def test_task_key_is_per_request_and_attempt(world: World):
    rid = await approved(world)
    assert list(world.tasks.by_key) == [f"callreq:{rid}:1"]
    world.engine.on("Mummy", CallOutcome(request_id="x", status=OutcomeStatus.BUSY))
    await world.orch.run_due()
    assert f"callreq:{rid}:2" in world.tasks.by_key


async def test_execute_of_a_not_due_or_unscheduled_request_does_nothing(world: World):
    rid = await approved(world)
    world.clock.set(world.at(7))  # before it was scheduled? scheduled for 'now' (11:00)
    req = await world.store.get_request(rid)
    req.next_attempt_at = world.at(12)
    await world.store.save_request(req)
    world.clock.set(world.at(11, 30))
    assert await world.orch.execute(rid) is None and world.engine.dials == []
    await world.orch.cancel(rid)
    world.clock.set(world.at(13))
    assert await world.orch.execute(rid) is None


async def test_gate_runs_again_right_before_the_dial(world: World):
    rid = await approved(world)
    await world.dnc.add(MUMMY, "opt_out_call")  # another user's call got an opt-out meanwhile
    await world.orch.run_due()
    assert world.engine.dials == []
    req = await world.store.get_request(rid)
    assert req.status == CallStatus.DENIED
    assert "nahi karungi" in world.notifier.sent[-1].text


async def test_kill_switch_between_approval_and_dial():
    from friday.core.config import Settings

    core = Settings(_env_file=None)
    w = build_world(core=core)
    await approved(w)
    core.paused = True
    await w.orch.run_due()
    assert w.engine.dials == []


async def test_edit_after_approval_requires_a_new_approval_before_any_dial(world: World):
    rid = await approved(world)
    await world.orch.apply_edit(rid, goal="bata do ki main kal aaunga")
    req = await world.store.get_request(rid)
    assert req.status == CallStatus.AWAITING_APPROVAL
    await world.orch.run_due()
    assert world.engine.dials == []
    new = world.notifier.sent[-1]
    assert "kal aaunga" in new.text
    await world.orch.handle_button(
        world.user.id, next(b.id for b in new.buttons if b.title == "Approve")
    )
    await world.orch.run_due()
    assert len(world.engine.dials) == 1
    assert world.engine.dials[0].brief.goal == "bata do ki main kal aaunga"


async def test_old_approve_button_after_edit_is_stale(world: World):
    rid = await approved(world)
    old_buttons = world.notifier.sent  # first prompt isn't recorded by intake; rebuild it
    brief = await world.store.get_brief(rid)
    old_btn = f"callap:{rid}:approve:{brief.content_hash()[:8]}"
    await world.orch.apply_edit(rid, goal="kuch aur")
    res = await world.orch.handle_button(world.user.id, old_btn)
    assert res.action == "stale"
    assert not (await world.store.get_brief(rid)).is_approved_as_is()
    assert old_buttons is not None


async def test_buttons_of_another_user_do_nothing(world: World):
    rid = await approved(world)
    brief = await world.store.get_brief(rid)
    res = await world.orch.handle_button(
        "somebody-else", f"callap:{rid}:cancel:{brief.content_hash()[:8]}"
    )
    assert not res.handled
    res = await world.orch.handle_button(
        "somebody-else", f"{ACT_PREFIX}:{rid}:{NextAction.STOP_CALLING}"
    )
    assert not res.handled and not await world.dnc.is_blocked(MUMMY)


async def test_cancel_button_cancels_and_cancels_the_task(world: World):
    await world.contacts.add(world.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True)
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="m1"
    )
    await world.orch.handle_button(
        world.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    brief = await world.store.get_brief(reply.request_id)
    await world.orch.handle_button(
        world.user.id, f"callap:{reply.request_id}:cancel:{brief.content_hash()[:8]}"
    )
    assert (await world.store.get_request(reply.request_id)).status == CallStatus.CANCELLED
    assert all(t.cancelled for t in world.tasks.tasks.values())
    await world.orch.run_due()
    assert world.engine.dials == []


async def test_callback_later_uses_the_time_the_callee_gave(world: World):
    rid = await approved(world)
    world.engine.on(
        "Mummy",
        CallOutcome(
            request_id="x", status=OutcomeStatus.CALLBACK_LATER, summary="baad mein",
            callback_at=world.at(15, 0),
        ),
        CallOutcome(request_id="x", status=OutcomeStatus.COMPLETED, summary="ok"),
    )  # fmt: skip
    await world.orch.run_due()
    req = await world.store.get_request(rid)
    assert req.next_attempt_at == world.at(15, 5)  # their time + the policy grace of 5 minutes
    assert (
        "baad mein" in world.notifier.sent[-1].text
        or "call karungi" in world.notifier.sent[-1].text
    )
    world.clock.set(world.at(15, 5))
    await world.orch.run_due()
    assert (await world.store.get_request(rid)).status == CallStatus.COMPLETED


async def test_retry_is_moved_into_the_calling_window():
    w = build_world(hour=18)  # 18:00: +1h would be 19:00 = closed for a plumber
    await w.contacts.add(w.user.id, "Plumber", PLUMBER, confirmed=True, relationship="plumber")
    w.engine.on("Plumber", CallOutcome(request_id="x", status=OutcomeStatus.NO_ANSWER))
    reply = await w.intake.handle(
        w.user, "plumber ko call karo kal aane ke liye Rs 500", message_id="p1"
    )
    await w.orch.handle_button(w.user.id, next(b.id for b in reply.buttons if b.title == "Approve"))
    await w.orch.run_due()
    req = await w.store.get_request(reply.request_id)
    assert req.next_attempt_at == w.at(9, day=6)


async def test_engine_crash_is_a_failed_attempt_and_is_retried(world: World):
    rid = await approved(world)

    def boom(brief, callee):
        raise RuntimeError("provider down")

    world.engine.on("Mummy", boom, CallOutcome(request_id="x", status=OutcomeStatus.COMPLETED))
    await world.orch.run_due()
    req = await world.store.get_request(rid)
    assert req.status == CallStatus.SCHEDULED and req.attempts == 1
    assert req.next_attempt_at == world.clock.now() + timedelta(minutes=5)  # failed_delay_min


async def test_repeat_button_reuses_the_approved_plan_but_not_the_gate_bypass(world: World):
    rid = await approved(world)
    await world.orch.run_due()
    res = await world.orch.handle_button(
        world.user.id, f"{ACT_PREFIX}:{rid}:{NextAction.CALL_AGAIN}"
    )
    assert res.handled
    mine = await world.store.list_for_user(world.user.id)
    assert len(mine) == 2
    new = next(r for r in mine if r.id != rid)
    assert new.callback_of == rid and new.status == CallStatus.SCHEDULED
    await world.orch.run_due()
    assert len(world.engine.dials) == 2
    # and a do-not-call mark stops a repeat as well
    await world.dnc.add(MUMMY, "opt_out_call")
    await world.orch.handle_button(world.user.id, f"{ACT_PREFIX}:{rid}:{NextAction.CALL_AGAIN}")
    await world.orch.run_due()
    assert len(world.engine.dials) == 2


async def test_stop_calling_button_adds_to_the_registry(world: World):
    rid = await approved(world)
    await world.orch.run_due()
    await world.orch.handle_button(world.user.id, f"{ACT_PREFIX}:{rid}:{NextAction.STOP_CALLING}")
    assert await world.dnc.is_blocked(MUMMY)
    assert "dobara call nahi karungi" in world.notifier.sent[-1].text


async def test_user_cap_denies_and_tells_the_user():
    w = build_world(settings=CallsSettings(daily_call_cap=1))
    rid = await approved(w)
    await w.orch.run_due()
    reply = await w.intake.handle(
        w.user, "mummy ko call karke bata do ki main der se aaunga", message_id="m2"
    )
    res = await w.orch.handle_button(
        w.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    assert res.status == CallStatus.DENIED and "limit" in w.notifier.sent[-1].text
    assert rid


async def test_strike_for_abuse_and_ban_after_three(world: World):
    for i in range(3):
        r = await world.intake.handle(
            world.user, "usko dhamki dene ke liye call karo", message_id=f"t{i}"
        )
        assert r.refused and "dhamki" in r.text
    assert await world.store.strikes(world.user.id) == 3
    await world.contacts.add(world.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True)
    reply = await world.intake.handle(
        world.user, "mummy ko call karke bata do ki main late hoon", message_id="ok1"
    )
    res = await world.orch.handle_button(
        world.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    assert res.status == CallStatus.DENIED  # banned: even a harmless call is refused
    assert world.engine.dials == []


# ------------------------------------------------------------------ group rules


async def _group(world: World, names=("Raj", "Amit")):
    nums = {"Raj": "+919000000005", "Amit": "+919000000006", "Neha": "+919000000007"}
    for n in names:
        await world.contacts.add(world.user.id, n, nums[n], relationship="friend", confirmed=True)
    reply = await world.intake.handle(
        world.user, f"sabko party ke liye call karo: {', '.join(names)}", message_id="g1"
    )
    return reply


async def test_group_children_are_gated_individually(world: World):
    await world.dnc.add("+919000000006", "opt_out_call")  # Amit opted out earlier
    reply = await _group(world)
    await world.orch.handle_button(
        world.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    await world.orch.run_due()
    assert [d.callee.name for d in world.engine.dials] == ["Raj"]
    parent = await world.store.get_request(reply.request_id)
    assert parent.status == CallStatus.COMPLETED  # Amit was denied, Raj answered: collected
    final = world.notifier.sent[-1].text
    assert "Raj" in final and "Amit: call nahi ki gayi" in final


async def test_group_parent_not_approved_means_no_children_called(world: World):
    reply = await _group(world)
    res = await world.orch.submit_group(reply.request_id)
    assert res.status == CallStatus.AWAITING_APPROVAL
    await world.orch.run_due()
    assert world.engine.dials == []


async def test_group_size_limit():
    w = build_world(settings=CallsSettings(group_max_members=2))
    nums = ["+919000000005", "+919000000006", "+919000000007"]
    for n, num in zip(("Raj", "Amit", "Neha"), nums, strict=True):
        await w.contacts.add(w.user.id, n, num, confirmed=True)
    reply = await w.intake.handle(
        w.user, "sabko party ke liye call karo: Raj, Amit, Neha", message_id="g1"
    )
    res = await w.orch.handle_button(
        w.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    assert res.status == CallStatus.DENIED and "itne logon" in w.notifier.sent[-1].text
    assert w.engine.dials == []


async def test_group_submit_is_idempotent(world: World):
    reply = await _group(world)
    btn = next(b.id for b in reply.buttons if b.title == "Approve")
    await world.orch.handle_button(world.user.id, btn)
    await world.orch.submit_group(reply.request_id)
    await world.orch.submit_group(reply.request_id)
    await world.orch.run_due()
    assert len(world.engine.dials) == 2
    assert len(await world.store.children(reply.request_id)) == 2


async def test_create_group_directly_dedupes_by_message(world: World):
    d = (await U.understand("sabko party ke liye call karo: Raj, Amit")).draft
    members = [Member("Raj", RAJ, True), Member("Amit", "+919000000006", True)]
    a = await world.orch.create_group(d, user=world.user, message_id="gm", members=members)
    b = await world.orch.create_group(d, user=world.user, message_id="gm", members=members)
    assert a[0].id == b[0].id and {k.id for k in a[2]} == {k.id for k in b[2]}
    assert all(k.callee_kind == CalleeKind.FAMILY_FRIEND for k in a[2])


@pytest.mark.parametrize("n", [1, 2])
async def test_no_answer_children_do_not_block_other_members(world: World, n):
    reply = await _group(world)
    world.engine.on("Raj", CallOutcome(request_id="x", status=OutcomeStatus.NO_ANSWER))
    await world.orch.handle_button(
        world.user.id, next(b.id for b in reply.buttons if b.title == "Approve")
    )
    await world.orch.run_due()
    assert {d.callee.name for d in world.engine.dials} == {"Raj", "Amit"}
