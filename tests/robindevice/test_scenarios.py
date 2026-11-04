"""Scenarios S1-S8 (and S4P) from tests/robindevice/scenarios.yaml, each in LIVE and in SHADOW mode."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from friday.core.clock import IST
from friday.robindevice.ports import TIER_RANK
from friday.robindevice.store import Event

from .conftest import MIN, ev

CASES = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text(encoding="utf-8"))["cases"]
CONTROL = {"at", "sweep", "external", "call_pattern", "call_id_cp"}


def _start_ms(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=IST).timestamp() * 1000)


async def _play(rig: Any, case: dict[str, Any], *, shadow: bool) -> Any:
    start = _start_ms(case["start"])
    rig.clock.ms = start
    token = await rig.pair(shadow_days=7 if shadow else 0, tags=frozenset(case["tags"]) if "tags" in case else None)
    if "sensitivity" in case:
        rig.service.set_policy("p1", sensitivity=case["sensitivity"])
    st = rig.service.store.peek("p1")
    for step in sorted(case["steps"], key=lambda s: s["at"]):
        rig.clock.ms = start + step["at"] * MIN
        if step.get("sweep"):
            await rig.service.sweep()
        elif "external" in step:
            rig.service.note_external("p1", step["external"])
        elif "call_pattern" in step:
            st.events.append(Event(f"cp-{step['at']}", "call_pattern", rig.clock.ms,
                                   {"call_id": step.get("call_id", "c1"), "tier": step["call_pattern"], "score": 9,
                                    "cue_ids": ["authority", "secrecy_isolation"]}))
            await rig.service._run(st)
        else:
            fields = {k: v for k, v in step.items() if k not in CONTROL and k != "type"}
            r = await rig.client.post("/robin/device/signals", headers=rig.h(token),
                                      json={"events": [ev(step["type"], rig.clock.ms, **fields)]})
            assert r.status_code == 200 and r.json()["invalid"] == 0, r.text
    return st


def _top(st: Any, scenario: str) -> str | None:
    tiers = [f["tier"] for f in st.findings if f["scenario"] == scenario]
    return max(tiers, key=lambda t: TIER_RANK[t]) if tiers else None


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_live(rig, case):
    st = await _play(rig, case, shadow=False)
    sc = case["scenario"]
    assert _top(st, sc) == case["logged"]
    if "alerts" in case:
        got = [a["tier"] for a in rig.alerts.of("p1") if a["scenario"] == sc]
        assert got == case["alerts"]
        for a in rig.alerts.of("p1"):  # the 'why' line is built from signal types only
            assert a["why"] and "{" not in a["why"]
    if "prompt" in case:
        keys = [p.key for p in st.prompts.values() if p.scenario == sc]
        assert (case["prompt"] in keys) if case["prompt"] else not keys
    if case.get("prompt_deferred"):
        assert all(p.not_before_ms > rig.clock.ms for p in st.prompts.values())
        assert await rig.service.pending_prompts(st) == []  # nothing shown at night


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_shadow_logs_but_never_alerts(rig, case):
    st = await _play(rig, case, shadow=True)
    sc = case["scenario"]
    assert rig.alerts.calls == [], "shadow mode must not alert"
    assert st.prompts == {}, "shadow mode must not nudge the parent"
    assert _top(st, sc) == case["logged"]
    if case["logged"]:
        assert any(f["shadow"] and f["scenario"] == sc for f in st.findings)
        assert st.counters.get(f"shadow:{sc}:{case['logged']}", 0) >= 1
        assert rig.service.shadow_report("p1")["per_scenario"][sc][case["logged"]] >= 1


def test_cases_cover_all_scenarios():
    assert {c["scenario"] for c in CASES} >= {"S1", "S2", "S3", "S4", "S4P", "S5", "S6", "S7", "S8"}


async def test_s5_alert_details_are_amount_direction_time_payee_only(rig):
    case = next(c for c in CASES if c["id"] == "s5_large_new_payee_debit")
    await _play(rig, case, shadow=False)
    (a,) = [x for x in rig.alerts.of("p1") if x["scenario"] == "S5"]
    assert set(a["details"]) == {"amount_paise", "direction", "ts_ms", "payee_kind"}
    assert a["details"]["amount_paise"] == 5_000_000 and a["details"]["payee_kind"] == "new"
    assert "50,000" in a["why"] and "new payee" in a["why"]


async def test_s1_why_string_matches_the_spec_style(rig):
    case = next(c for c in CASES if c["id"] == "s1_digital_arrest_progression")
    await _play(rig, case, shadow=False)
    whys = [a["why"] for a in rig.alerts.of("p1") if a["scenario"] == "S1"]
    assert "unknown caller 20 minutes + camera on" in whys[-1]
