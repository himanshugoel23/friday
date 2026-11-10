# ruff: noqa: E501
"""T19: the AI emergency flow hands a HandoffCard to the human desk (when mounted) and the Robin tick runs the desk's escalation.
The desk never blocks the AI ladder. Tested with fakes (in-memory desk from tests/concierge, no pager, no call)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.concierge import humanport
from friday.concierge.desk import Shift
from friday.robin.models import CallResult
from tests.concierge.conftest import make_rig


@pytest.fixture(autouse=True)
def _clean_ports():
    yield
    humanport.register_handoff(None)
    humanport.register_tick(None)
    humanport.register_human_joined(None)


async def sos_world(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    parent = await w.parent()
    w.script_calls(CallResult.NO_ANSWER)
    return w, parent


async def roster(rig) -> None:
    now = rig.clock.now()
    await rig.desk.set_shift(rig.staff("lead1"), Shift("s1", now - timedelta(hours=1), now + timedelta(hours=8), "e1", "e2"))


def mount(rig) -> None:
    humanport.register_handoff(rig.desk.receive)
    humanport.register_tick(rig.desk.tick)
    humanport.register_human_joined(rig.desk.is_human_joined)


async def test_sos_hands_a_card_to_the_desk_and_pages_the_primary(dworld):
    w, parent = await sos_world(dworld)
    rig = make_rig()
    await roster(rig)
    mount(rig)
    n = len(w.child_texts())
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted
    assert len(w.child_texts()) > n, "the AI told the child first"
    (inc,) = await w.incidents()
    doc = await rig.store.doc_get("handoff", inc.id)
    assert doc is not None and doc["status"] == "paged" and doc["primary"] == "e1"
    assert rig.pager.paged == [("e1", inc.id)]
    card = doc["card"]
    assert card["tier"] == "emergency" and card["parent_id"] == parent.id and card["language"] == parent.language
    assert any(a.startswith("wa_child") for a in card["ai_actions"])
    blob = repr(card)
    assert "+91" not in blob and "9800" not in blob  # no number on the card


async def test_no_roster_still_records_the_card_and_robin_goes_on_alone(dworld):
    w, parent = await sos_world(dworld)
    rig = make_rig()
    mount(rig)
    await w.hub.widget_sos(parent.id)
    (inc,) = await w.incidents()
    doc = await rig.store.doc_get("handoff", inc.id)
    assert doc["status"] == "no_desk" and rig.pager.paged == []


async def test_desk_off_means_no_handoff_and_nothing_changes(dworld):
    w, parent = await sos_world(dworld)
    assert not humanport.handoff_enabled()
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted
    (inc,) = await w.incidents()
    assert inc.data["tier"] == "emergency"


async def test_a_crashing_desk_never_blocks_the_ai_ladder(dworld):
    w, parent = await sos_world(dworld)

    async def boom(card):
        raise RuntimeError("desk down")

    humanport.register_handoff(boom)
    n = len(w.child_texts())
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted and len(w.child_texts()) > n
    (inc,) = await w.incidents()
    assert any(s["state"] == "done" for s in inc.data["steps"])


async def test_a_hanging_desk_is_cut_off_by_the_timeout(dworld, monkeypatch):
    import asyncio

    w, parent = await sos_world(dworld)

    async def slow(card):
        await asyncio.sleep(30)

    monkeypatch.setattr(humanport, "HANDOFF_TIMEOUT_S", 0.05)
    humanport.register_handoff(slow)
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted


async def test_robin_tick_runs_the_desk_tick_and_unacked_page_goes_to_the_secondary(dworld):
    w, parent = await sos_world(dworld)
    rig = make_rig()
    await roster(rig)
    mount(rig)
    await w.hub.widget_sos(parent.id)
    assert [p[0] for p in rig.pager.paged] == ["e1"]
    rig.clock.advance(seconds=rig.cfg.desk_ack_s + 1)
    await w.hub.tick()  # the Robin scheduler tick, not the desk's own
    assert [p[0] for p in rig.pager.paged] == ["e1", "e2"]


async def test_desk_tick_failure_does_not_stop_the_other_tick_steps(dworld):
    w, _ = await sos_world(dworld)

    async def bad() -> int:
        raise RuntimeError("x")

    humanport.register_tick(bad)
    assert isinstance(await w.hub.tick(), int)
    assert await humanport.desk_tick() == 0
