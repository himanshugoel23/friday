# ruff: noqa: E501
"""The device API ports backed by the family package: alerts reach the child, consent is the family's, the phone can only withdraw."""

from __future__ import annotations

from friday.robin import alerts as alerts_mod
from friday.robin.models import ConsentSource
from friday.robin.wiring import (
    DEVICE_TO_FAMILY_CONSENT,
    _DeviceAlerts,
    _DeviceConsent,
    _DeviceParents,
)
from friday.robindevice.ports import CONSENT_ITEMS as DEVICE_ITEMS


async def test_every_device_consent_item_maps_to_a_family_item(w):
    from friday.robin.models import CONSENT_ITEMS as FAMILY_ITEMS

    assert set(DEVICE_TO_FAMILY_CONSENT) == set(DEVICE_ITEMS)
    assert set(DEVICE_TO_FAMILY_CONSENT.values()) <= set(FAMILY_ITEMS)


async def test_consent_is_read_from_the_family_and_the_phone_can_only_withdraw(w):
    _, parent = await w.family()
    port = _DeviceConsent(w.hub)
    assert not await port.has(parent.id, "calls")  # the admin has not granted device signals
    await w.hub.fam.give_consent(parent.id, "device_signals", ConsentSource.ADMIN_CHAT)
    assert await port.has(parent.id, "calls") and await port.has(parent.id, "camera")
    await port.set(parent.id, "calls", True, "app")  # a grant from the phone is ignored
    assert await port.has(parent.id, "calls")
    await port.set(parent.id, "calls", False, "app")  # a withdrawal is honoured
    assert not await port.has(parent.id, "calls")
    assert not await port.has("nobody", "calls") and not await port.has(parent.id, "bogus")


async def test_a_paused_parent_has_no_sensitive_consent(w):
    _, parent = await w.family()
    await w.hub.fam.give_consent(parent.id, "device_signals", ConsentSource.ADMIN_CHAT)
    parent.paused = True
    await w.store.save_member(parent, (await w.store.get_family(parent.family_id)).owner_user_id)
    assert not await _DeviceConsent(w.hub).has(parent.id, "calls")


async def test_parent_lookup_gives_the_language(w):
    _, parent = await w.family()
    info = await _DeviceParents(w.hub).get(parent.id)
    assert info is not None and info.language == "hinglish" and await _DeviceParents(w.hub).get("nobody") is None


async def test_a_device_alert_reaches_the_family_engine(w, monkeypatch):
    _, parent = await w.family()
    seen = []

    async def fake_raise(alert):
        seen.append(alert)
        return alerts_mod.AlertResult(True, "ok")

    monkeypatch.setattr(alerts_mod, "raise_alert", fake_raise)
    await _DeviceAlerts(w.hub).raise_alert(parent.id, "HIGH", "S1", "unknown caller 22 minutes + camera on", {"money": True, "signals": ["pattern_s1"]})
    assert seen and seen[0].parent_member_id == parent.id and seen[0].tier == "HIGH" and seen[0].money and seen[0].signals == ("pattern_s1",)


async def test_care_gate_uses_the_container_care_component(w):
    from friday.robin.wiring import _care_gate

    class Svc:
        def __init__(self, active):
            self.active = active

        async def is_active(self, user_id):
            return self.active

    class C:
        def __init__(self, svc):
            self.svc = svc

        def get(self, name):
            if self.svc is None:
                raise KeyError(name)
            return self.svc

    assert await _care_gate(C(Svc(True)))("u1") is True
    assert await _care_gate(C(Svc(False)))("u1") is False
    assert await _care_gate(C(None))("u1") is False  # care module absent: inactive, never blocks
