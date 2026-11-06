# ruff: noqa: E501
"""T03(b): an SOS ALWAYS reaches the child, even when the family is not ACTIVE yet and consent is incomplete.
Every other scenario stays gated (``family_not_active``). Fakes only; nothing is dialled."""

from __future__ import annotations

import logging

from friday.robin.alerts import RobinAlert
from friday.robin.models import CallResult, FamilyStatus, Tier
from friday.robin.wiring import _DeviceAlerts
from tests.robin.conftest import PARENT_PHONE, SECOND_PHONE


async def bare_family(w, *, second: bool = False):
    """Setup started, nothing agreed: ONBOARDING, no consent, the child never said 'yes, ring me', parent not notified."""
    fam = await w.hub.fam.create_family(w.child_user, parent_label="Papa", child_name="Asha", child_language="en")
    parent = await w.hub.fam.add_parent(fam, PARENT_PHONE)
    if second:
        await w.hub.fam.set_second_contact(fam, SECOND_PHONE, "Uncle")
    fam = await w.store.get_family(fam.id)
    assert fam.status == FamilyStatus.ONBOARDING and not (await w.ctx.child(fam)).call_ok
    return fam, parent


def sos(parent, **kw):
    return RobinAlert(parent_member_id=parent.id, tier=Tier.EMERGENCY, scenario="sos", why="Papa pressed the help button", **kw)


async def test_sos_before_the_family_is_active_messages_and_rings_the_child(w):
    fam, parent = await bare_family(w, second=True)
    w.caller.script(CallResult.NO_ANSWER)
    res = await w.hub.alerts.raise_alert(sos(parent))
    assert res.accepted and res.incident_id
    assert "Papa" in w.sender.sent[-1].text and w.sender.sent[-1].buttons  # the child is told at once
    to_child = [c for c in w.caller.calls if c.role == "child"]
    assert len(to_child) == 1 and to_child[0].purpose == "escalation_child" and to_child[0].line_keys == ["child.ring_sos"]
    assert not [c for c in w.caller.calls if c.role != "child"]  # minimal: the parent is not rung, nor the second contact
    for _ in range(8):
        w.go(minutes=3)
        await w.hub.alerts.tick()
    assert len([c for c in w.caller.calls if c.role == "child"]) == 3  # the ladder repeats, capped at 3 rings
    assert not [r for r in await w.store.list(fam.id, "audit") if r.data.get("purpose") == "authority"]
    assert (await w.store.get_family(fam.id)).status == FamilyStatus.ONBOARDING  # an SOS never activates anything


async def test_sos_works_through_the_sos_service_and_the_device_port(w):
    fam, parent = await bare_family(w)
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted and w.sender.sent
    n = len(w.sender.sent)
    from friday.robin import alerts as alerts_mod

    alerts_mod.set_default_engine(w.hub.alerts)
    try:
        await _DeviceAlerts(w.hub).raise_alert(parent.id, "EMERGENCY", "SOS", "SOS button pressed", {"dedupe_key": "other"})
    finally:
        alerts_mod.set_default_engine(None)
    assert len(w.sender.sent) > n


async def test_every_other_scenario_stays_gated_before_active(w):
    fam, parent = await bare_family(w)
    for tier, scenario in ((Tier.HIGH, "S1"), (Tier.EMERGENCY, "threat"), (Tier.WATCH, "S3"), (Tier.HIGH, "checkin_unanswered")):
        res = await w.hub.alerts.raise_alert(RobinAlert(parent.id, tier, scenario, "x"))
        assert not res.accepted and res.reason == "family_not_active", scenario
    assert not w.sender.sent and not w.caller.calls


async def test_sos_with_no_child_contact_logs_a_clear_error(w, caplog):
    fam, parent = await bare_family(w)
    await w.store.delete_member((await w.ctx.child(fam)).id)
    with caplog.at_level(logging.ERROR):
        res = await w.hub.alerts.raise_alert(sos(parent))
    assert not res.accepted and res.reason == "no_child_contact"
    assert any("NO child contact" in r.message for r in caplog.records)
    assert PARENT_PHONE not in caplog.text
    assert any(r.data.get("event") == "sos_failed" for r in await w.store.list(fam.id, "audit"))


async def test_sos_after_onboarding_still_uses_the_full_ladder(w):
    fam, parent = await w.family(second=True)  # ACTIVE
    res = await w.hub.alerts.raise_alert(sos(parent))
    assert res.accepted
    incident = await w.store.get(res.incident_id)
    actions = [s["action"] for s in incident.data["steps"]]
    assert "wa_second" in actions and "authority" in actions  # the full plan is unchanged once the family is active
