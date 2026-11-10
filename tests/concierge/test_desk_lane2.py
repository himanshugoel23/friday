# ruff: noqa: E501
"""Lane 2 minimum: handoff record, roster/on-call, page -> secondary -> 'did not answer', 'human joined' stops the AI re-ringing,
hand back, false alarm reason, second-person review. Plus the masked bridge (C7). Tested with fakes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.concierge import humanport
from friday.concierge.desk import HandoffCard, Shift
from friday.concierge.service import BadState, Denied
from tests.concierge.conftest import PARENT_NUMBER, T0


def card(iid="inc1", **kw):
    base = dict(incident_id=iid, parent_id="par1", family_id="fam1", language="hinglish", tier="high", why="Unknown caller 22 minutes + camera on",
                signals=(("pattern_s1", "2026-11-10T09:00:00"),), ai_actions=("rang_parent", "rang_child"), rung=(("parent", "no_answer"), ("child", "answered")), consent_items=("desk_may_call_112",))
    base.update(kw)
    return HandoffCard(**base)


async def roster(rig, primary="e1", secondary="e2"):
    await rig.desk.set_shift(rig.staff("lead1"), Shift("s1", T0 - timedelta(hours=1), T0 + timedelta(hours=8), primary, secondary))


async def test_roster_needs_a_lead_and_lane_2_people(rig):
    s = Shift("s1", T0, T0 + timedelta(hours=8), "e1", "e2")
    with pytest.raises(Denied):
        await rig.desk.set_shift(rig.staff("e1"), s)
    with pytest.raises(BadState):
        await rig.desk.set_shift(rig.staff("lead1"), Shift("s2", T0, T0 + timedelta(hours=8), "c1", "e2"))  # concierge-only
    with pytest.raises(BadState):
        await rig.desk.set_shift(rig.staff("lead1"), Shift("s3", T0, T0 + timedelta(hours=8), "e1", "e1"))
    await rig.desk.set_shift(rig.staff("lead1"), s)
    assert await rig.desk.on_call(T0 + timedelta(hours=1)) == ("e1", "e2")
    assert await rig.desk.on_call(T0 + timedelta(hours=9)) is None


async def test_handoff_pages_the_primary_and_is_idempotent(rig):
    await roster(rig)
    h = await rig.desk.receive(card())
    assert h.status == "paged" and rig.pager.paged == [("e1", "inc1")]
    await rig.desk.receive(card())
    assert rig.pager.paged == [("e1", "inc1")]  # same incident: not paged twice
    view = await rig.desk.view(rig.staff("e1"), "inc1")
    assert view.card["consent_items"] == ["desk_may_call_112"] and view.card["rung"][1] == ["child", "answered"]
    with pytest.raises(Denied):
        await rig.desk.view(rig.staff("c1"), "inc1")  # concierge-only staff cannot see lane 2


async def test_no_ack_pages_the_secondary_then_logs_desk_did_not_answer(rig):
    await roster(rig)
    await rig.desk.receive(card())
    rig.clock.advance(seconds=179)
    assert await rig.desk.tick() == 0
    rig.clock.advance(seconds=2)
    assert await rig.desk.tick() == 1 and rig.pager.paged[-1] == ("e2", "inc1")
    rig.clock.advance(seconds=181)
    assert await rig.desk.tick() == 1
    h = await rig.desk.view(rig.staff("e1"), "inc1")
    assert h.status == "unanswered" and [c for _t, c in h.log] == ["primary_paged", "secondary_paged", "desk_did_not_answer"]
    assert [e.action for e in await rig.audit.entries()][-1] == "desk_no_answer"
    assert not await rig.desk.is_human_joined("inc1")  # the family ladder continues alone
    await rig.desk.join(rig.staff("e2"), "inc1")  # a late person can still join
    assert await rig.desk.is_human_joined("inc1")


async def test_outside_the_roster_robin_works_alone_and_says_so(rig):
    h = await rig.desk.receive(card())
    assert h.status == "no_desk" and rig.pager.paged == [] and h.log[0][1] == "no_one_on_call"


async def test_ack_in_time_stops_the_secondary_page(rig):
    await roster(rig)
    await rig.desk.receive(card())
    await rig.desk.ack(rig.staff("e1"), "inc1")
    rig.clock.advance(minutes=10)
    assert await rig.desk.tick() == 0 and len(rig.pager.paged) == 1


async def test_human_joined_stops_the_ai_and_hand_back_resumes_it(rig):
    await roster(rig)
    humanport.register_human_joined(rig.desk.is_human_joined)
    try:
        await rig.desk.receive(card())
        assert not await humanport.human_joined("inc1")
        await rig.desk.join(rig.staff("e1"), "inc1")
        assert await humanport.human_joined("inc1") and not await humanport.human_joined("other")
        with pytest.raises(Denied):
            await rig.desk.hand_back(rig.staff("e2"), "inc1")  # only the person on the line
        await rig.desk.hand_back(rig.staff("e1"), "inc1")
        assert not await humanport.human_joined("inc1")
        await rig.desk.join(rig.staff("e1"), "inc1")
        await rig.desk.close(rig.staff("e1"), "inc1", "resolved")
        assert not await humanport.human_joined("inc1")
    finally:
        humanport.register_human_joined(None)


async def test_joined_survives_another_replica(rig):
    await roster(rig)
    await rig.desk.receive(card())
    await rig.desk.join(rig.staff("e1"), "inc1")
    from friday.concierge.desk import DeskService

    other = DeskService(store=rig.store, audit=rig.audit, clock=rig.clock, directory=rig.directory, pager=rig.pager)
    assert await other.is_human_joined("inc1")


async def test_nothing_registered_means_robin_is_unchanged():
    humanport.register_human_joined(None)
    assert await humanport.human_joined("anything") is False

    async def boom(_i: str) -> bool:
        raise RuntimeError("db down")

    humanport.register_human_joined(boom)
    try:
        assert await humanport.human_joined("x") is False  # a failing lookup never breaks the AI ladder
    finally:
        humanport.register_human_joined(None)


async def test_false_alarm_needs_a_reason_counts_per_week_and_review_needs_a_second_person(rig):
    await roster(rig)
    await rig.desk.receive(card())
    await rig.desk.join(rig.staff("e1"), "inc1")
    with pytest.raises(BadState):
        await rig.desk.close(rig.staff("e1"), "inc1", "false_alarm", "because")
    with pytest.raises(BadState):
        await rig.desk.close(rig.staff("e1"), "inc1", "false_alarm")
    await rig.desk.close(rig.staff("e1"), "inc1", "false_alarm", "accidental_press")
    assert await rig.desk.false_alarms("par1") == {"accidental_press": 1}
    with pytest.raises(Denied):
        await rig.desk.review(rig.staff("e1"), "inc1")  # not the person who handled it
    assert await rig.desk.reviews_overdue() == []
    rig.clock.advance(hours=25)
    assert await rig.desk.reviews_overdue() == ["inc1"]
    await rig.desk.review(rig.staff("lead1"), "inc1")
    assert await rig.desk.reviews_overdue() == []
    assert await rig.desk.false_alarms("par1", days=7) == {"accidental_press": 1}
    rig.clock.advance(days=8)
    assert await rig.desk.false_alarms("par1") == {}


async def test_lane_2_audit_has_ids_and_counts_only(rig):
    await roster(rig)
    await rig.desk.receive(card())
    await rig.desk.join(rig.staff("e1"), "inc1")
    blob = repr([(e.action, e.target_id, e.counts) for e in await rig.audit.entries()])
    assert "Unknown caller" not in blob and "camera" not in blob
    assert await rig.audit.verify() is None


# ---------------------------------------------------------------- C7 masked contact
async def test_contact_goes_through_the_bridge_and_staff_never_get_a_number(rig):
    r = (await rig.service.intake("par1", {"summary": "Call the pharmacy and confirm the order", "category": "medicine"})).request_id
    s = rig.staff("c1")
    await rig.service.claim(s, r)
    link = await rig.service.contact(s, r, "parent")
    assert link.masked_label.startswith("Parent via Robin line") and PARENT_NUMBER not in repr(link)
    shown = repr(link) + repr(await rig.service.view(s, r)) + repr([e.__dict__ for e in await rig.audit.entries()])
    assert PARENT_NUMBER not in shown and "9800000555" not in shown
    assert await rig.service.end_contact(s, r, link.link_id) and rig.bridge.ended == [link.link_id]
    with pytest.raises(Denied):
        await rig.service.contact(rig.staff("c2"), r, "parent")  # not their request
    with pytest.raises(Denied):
        await rig.service.contact(s, r, "the neighbour")  # only parent or child
    rig.bridge.refuse = True
    with pytest.raises(BadState):
        await rig.service.contact(s, r, "child")
    assert "contact_refused" in [e.action for e in await rig.audit.entries()]


def test_mask_phone():
    from friday.concierge.ports import mask_phone

    assert mask_phone(PARENT_NUMBER) == "+91 ••••• ••555" and mask_phone("12") == "••••••" and mask_phone(None) == "••••••"
