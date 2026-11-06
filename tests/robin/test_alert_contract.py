# ruff: noqa: E501
"""T01: the device -> family alert contract. The device package speaks UPPERCASE tiers and scenario 'SOS'/'THREAT';
the family engine speaks lowercase `Tier` and 'sos'. Both ends are pinned here (tested with fakes)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from friday.robin import alerts as alerts_mod
from friday.robin.alerts import RobinAlert
from friday.robin.models import Tier, normalise_scenario, parse_tier
from friday.robin.wiring import _DeviceAlerts

RULES = yaml.safe_load(
    (Path(__file__).parents[2] / "friday" / "robindevice" / "scenarios.yaml").read_text(
        encoding="utf-8"
    )
)
COMBOS = sorted({(t["tier"], sc["id"]) for sc in RULES["scenarios"] for t in sc["tiers"]})


@pytest.fixture
def spy(monkeypatch):
    """Capture what the device seam hands to the family engine, then let the real engine run."""
    real = alerts_mod.raise_alert
    seen: list[tuple[RobinAlert, alerts_mod.AlertResult]] = []

    async def wrapped(alert):
        res = await real(alert)
        seen.append((alert, res))
        return res

    monkeypatch.setattr(alerts_mod, "raise_alert", wrapped)
    return seen


async def ready(w, **kw):
    fam, parent = await w.family(**kw)
    await w.hub.fam.admin_consent(fam, "device_signals")
    await w.hub.fam.admin_consent(fam, "payment_alerts")
    alerts_mod.set_default_engine(w.hub.alerts)
    return fam, parent


async def steps_of(w, res):
    return [s["action"] for s in (await w.store.get(res.incident_id)).data["steps"]]


def test_parse_tier_is_case_insensitive_and_never_lowers():
    assert parse_tier("HIGH") == (Tier.HIGH, True)
    assert parse_tier(" emergency ") == (Tier.EMERGENCY, True)
    assert parse_tier(Tier.WATCH) == (Tier.WATCH, True)
    for bad in ("", "URGENT", None, 7, "HIGH!"):
        assert parse_tier(bad) == (Tier.HIGH, False)
    assert (
        normalise_scenario("SOS") == "sos"
        and normalise_scenario("THREAT") == "threat"
        and normalise_scenario(" S5 ") == "S5"
    )


def test_the_combo_table_covers_every_tier_the_device_can_emit():
    assert {t for t, _ in COMBOS} == {
        "INFO",
        "WATCH",
        "HIGH",
    }  # the engine also sends EMERGENCY (SOS), SHARE uses HIGH/WATCH
    assert len(COMBOS) >= 10


@pytest.mark.parametrize(("tier", "scenario"), COMBOS + [("EMERGENCY", "S1")])
async def test_every_device_tier_scenario_gets_the_plan_of_its_tier(w, spy, tier, scenario):
    _, parent = await ready(w)
    await _DeviceAlerts(w.hub).raise_alert(
        parent.id, tier, scenario, "why line", {"dedupe_key": "k1"}
    )
    alert, res = spy[-1]
    assert res.accepted and alert.tier == Tier(tier.lower())
    rec = await w.store.get(res.incident_id)
    assert rec.data["tier"] == tier.lower()
    steps = await steps_of(w, res)
    if tier == "EMERGENCY":
        assert "authority" in steps and "call_child" in steps
    elif tier == "HIGH":
        assert "call_child" in steps and "nudge_parent" in steps
        assert "authority" in steps  # ladder failing for a medical/fraud HIGH
    elif tier == "WATCH":
        assert steps == ["wa_child", "nudge_parent"]  # an app nudge, never a call
    else:
        assert (
            rec.status == "closed" and rec.data["steps"] and not w.caller.calls
        )  # INFO: digest only


async def test_device_sos_is_a_family_sos_even_when_paused_and_without_consent(w, spy):
    fam, parent = await w.family(
        second=True
    )  # active family, but no device_signals and no location consent
    alerts_mod.set_default_engine(w.hub.alerts)
    await w.hub.fam.pause(parent.id, "voice")
    await _DeviceAlerts(w.hub).raise_alert(
        parent.id,
        "EMERGENCY",
        "SOS",
        "SOS button pressed",
        {"location": {"lat": 28.6, "lon": 77.2}},
    )
    alert, res = spy[-1]
    assert (
        alert.scenario == "sos"
        and alert.tier == Tier.EMERGENCY
        and res.accepted
        and res.reason == "ok"
    )
    rec = await w.store.get(res.incident_id)
    assert rec.data["scenario"] == "sos" and "sos_button" in rec.data["signals"]
    assert rec.data["location"] is None  # location consent not given: dropped by the engine
    assert (await steps_of(w, res))[:3] == ["wa_child", "wa_second", "call_child"]
    assert any(c.purpose == "escalation_child" for c in w.caller.calls)  # the child is rung
    assert any("SOS" in t or "sos" in t.lower() for t in w.sender.texts())  # and messaged


async def test_device_sos_location_is_used_only_with_location_consent(w, spy):
    fam, parent = await ready(w)
    await w.hub.fam.admin_consent(fam, "location")
    await _DeviceAlerts(w.hub).raise_alert(
        parent.id,
        "EMERGENCY",
        "SOS",
        "SOS button pressed",
        {"location": {"lat": 28.6139, "lon": 77.209}},
    )
    rec = await w.store.get(spy[-1][1].incident_id)
    assert rec.data["location"] == [28.6139, 77.209]


async def test_device_threat_maps_to_threat(w, spy):
    _, parent = await ready(w)
    await _DeviceAlerts(w.hub).raise_alert(parent.id, "EMERGENCY", "THREAT", "threatened", {})
    assert spy[-1][0].scenario == "threat"
    assert (await w.store.get(spy[-1][1].incident_id)).data["what"] == "threat"


async def test_device_watch_stays_an_app_nudge(w, spy):
    _, parent = await ready(w)
    await _DeviceAlerts(w.hub).raise_alert(parent.id, "WATCH", "S6", "night video activity", {})
    assert await steps_of(w, spy[-1][1]) == ["wa_child", "nudge_parent"]
    assert not [c for c in w.caller.calls if c.purpose == "escalation_child"]


@pytest.mark.parametrize("bad", ["URGENT", "", "high!!", "critical"])
async def test_unknown_tier_string_is_treated_as_high(w, spy, bad):
    _, parent = await ready(w)
    await _DeviceAlerts(w.hub).raise_alert(parent.id, bad, "S1", "x", {})
    assert spy[-1][0].tier == Tier.HIGH
    assert "call_child" in await steps_of(w, spy[-1][1])


async def test_the_engine_itself_is_defensive_for_str_tiers_and_scenarios(w):
    _, parent = await ready(w)
    r1 = await w.hub.alerts.raise_alert(RobinAlert(parent.id, "HIGH", "S1", "x", dedupe_key="a"))  # type: ignore[arg-type]
    r2 = await w.hub.alerts.raise_alert(
        RobinAlert(parent.id, "nonsense", "S1", "x", dedupe_key="b")
    )  # type: ignore[arg-type]
    r3 = await w.hub.alerts.raise_alert(
        RobinAlert(parent.id, "Emergency", "SOS", "x", dedupe_key="c")
    )  # type: ignore[arg-type]
    assert [(await w.store.get(r.incident_id)).data["tier"] for r in (r1, r2, r3)] == [
        "high",
        "high",
        "emergency",
    ]
    assert (await w.store.get(r3.incident_id)).data["scenario"] == "sos"
    assert "call_child" in await steps_of(w, r1) and "call_child" in await steps_of(w, r2)


async def test_dedupe_key_is_still_idempotent_through_the_seam(w, spy):
    _, parent = await ready(w)
    port = _DeviceAlerts(w.hub)
    await port.raise_alert(parent.id, "HIGH", "S1", "x", {"dedupe_key": "same"})
    await port.raise_alert(parent.id, "high", "S1", "x", {"dedupe_key": "same"})
    (_, a), (_, b) = spy[-2], spy[-1]
    assert a.incident_id == b.incident_id and b.duplicate and not a.duplicate
