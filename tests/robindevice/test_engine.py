"""Engine behaviour around the scenarios: ceilings, cooldowns, quiet hours, feedback, shadow week, rules file,
call-pattern wiring, brand, wording inventory."""

from __future__ import annotations

import copy as pycopy

import pytest
import yaml

from friday.robindevice import copy as C
from friday.robindevice.brand import brand_name
from friday.robindevice.engine import format_inr, known_predicates
from friday.robindevice.rules import DEFAULT_PATH, RulesError, load, parse

from .conftest import ev, ist_ms

B = "/robin/device"


async def sig(rig, token, *events):
    r = await rig.client.post(f"{B}/signals", headers=rig.h(token), json={"events": list(events)})
    assert r.status_code == 200, r.text
    return r.json()


def remote(rig, app="anydesk"):
    return ev("remote_access_app_opened", rig.clock.ms, app=app)


def debit(rig, paise=5_000_000, kind="new"):
    return ev("payment_notification", rig.clock.ms, app="gpay", direction="debit", amount_paise=paise, payee_kind=kind)


# ----------------------------------------------------------------------------- rules file


def test_shipped_rules_load_and_are_flagged_unverified():
    r = load(known_predicates=known_predicates())
    assert r.version == 1 and r.unverified is True
    assert {s.id for s in r.scenarios} >= {"S1", "S2", "S3", "S4", "S4P", "S5", "S6", "S7", "S8"}
    assert r.defaults["shadow_days"] == 7 and r.defaults["nudges_per_hour"] == 2
    assert set(r.sensitivity) == {"calm", "balanced", "careful"}


def test_rules_reject_bad_files():
    good = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    for mutate in (
        lambda d: d["scenarios"][0]["signals"][0].update(predicate="nope"),
        lambda d: d["scenarios"][0]["tiers"][0].update(tier="EMERGENCY"),
        lambda d: d["scenarios"].append(pycopy.deepcopy(d["scenarios"][0])),
        lambda d: d["scenarios"][0]["signals"][0].update(weight="heavy"),
        lambda d: d.pop("sensitivity"),
        lambda d: d["scenarios"][0].update(tiers=[]),
    ):
        d = pycopy.deepcopy(good)
        mutate(d)
        with pytest.raises(RulesError):
            parse(d, known_predicates=known_predicates())
    with pytest.raises(RulesError):
        parse([], known_predicates=known_predicates())


def test_format_inr():
    assert format_inr(5_000_000) == "Rs 50,000"
    assert format_inr(12_345_600) == "Rs 1,23,456"
    assert format_inr(99_900) == "Rs 999"


# ----------------------------------------------------------------------------- ceilings and cooldowns


async def test_parent_nudge_ceiling_two_per_hour_child_still_told(rig):
    t = await rig.pair()
    for app in ("anydesk", "teamviewer", "rustdesk", "airdroid"):  # each is its own tier-HIGH 'opened' signal
        rig.service.store.peek("p1").fired.clear()  # defeat cooldown to test the ceiling alone
        await sig(rig, t, remote(rig, app))
        rig.clock.advance(minutes=5)
    st = rig.service.store.peek("p1")
    assert len(st.prompts) == 2
    assert st.counters["nudge_skipped:ceiling"] >= 1
    assert len([a for a in rig.alerts.calls if a["scenario"] == "S2"]) >= 3  # the child is not capped by the nudge ceiling
    rig.clock.advance(hours=1)
    st.fired.clear()
    await sig(rig, t, remote(rig, "rustdesk"))
    assert len(st.prompts) == 3  # an hour later nudges are allowed again


async def test_cooldown_blocks_repeat_but_higher_tier_escalates(rig):
    t = await rig.pair()
    await sig(rig, t, ev("remote_access_app_installed", rig.clock.ms, app="anydesk"))
    assert [a["tier"] for a in rig.alerts.of("p1")] == ["WATCH"]
    rig.clock.advance(minutes=1)
    await sig(rig, t, ev("remote_access_app_installed", rig.clock.ms, app="anydesk"))
    assert len(rig.alerts.of("p1")) == 1  # same tier inside the cooldown
    rig.clock.advance(minutes=1)
    await sig(rig, t, remote(rig))
    assert [a["tier"] for a in rig.alerts.of("p1")] == ["WATCH", "HIGH"]  # escalation passes
    assert rig.service.store.peek("p1").counters["skipped:cooldown"] >= 1


async def test_each_payment_is_its_own_incident(rig):
    t = await rig.pair()
    await sig(rig, t, debit(rig))
    rig.clock.advance(minutes=2)
    await sig(rig, t, debit(rig, 3_000_000))
    assert len([a for a in rig.alerts.of("p1") if a["scenario"] == "S5"]) == 2


async def test_per_parent_payment_threshold(rig):
    t = await rig.pair()
    rig.service.set_policy("p1", payment_threshold_paise=100_000)  # Rs 1,000
    await sig(rig, t, debit(rig, 200_000, "known"))
    (a,) = [x for x in rig.alerts.of("p1") if x["scenario"] == "S5"]
    assert a["tier"] == "WATCH"
    with pytest.raises(ValueError):
        rig.service.set_policy("p1", payment_threshold_paise=5)


# ----------------------------------------------------------------------------- quiet hours


async def test_quiet_hours_suppress_nudge_but_not_money_high_or_child(rig):
    rig.clock.ms = ist_ms(2026, 9, 9, 23, 0)
    t = await rig.pair()
    await sig(rig, t, remote(rig))  # S2 HIGH, not money: no 11pm nudge
    st = rig.service.store.peek("p1")
    assert any(a["scenario"] == "S2" for a in rig.alerts.calls) and not st.prompts
    assert st.counters["nudge_skipped:quiet_hours"] == 1
    rig.clock.advance(minutes=1)
    await sig(rig, t, debit(rig))  # money HIGH is allowed at night
    assert [p.key for p in st.prompts.values()] == ["s5_high"]


# ----------------------------------------------------------------------------- feedback


async def test_this_was_fine_trusts_number_and_suppresses_pattern(rig):
    t = await rig.pair()
    h = "a" * 64

    async def call(cid, minutes):
        rig.clock.advance(minutes=1)
        await sig(rig, t, ev("unknown_call_started", rig.clock.ms, call_id=cid, number_class="international", number_hash=h))
        rig.clock.advance(minutes=minutes)
        await sig(rig, t, ev("call_state_offhook", rig.clock.ms, call_id=cid, duration_s=minutes * 60, ongoing=False),
                  ev("camera_in_use_start", rig.clock.ms))
        await sig(rig, t, ev("camera_in_use_stop", rig.clock.ms))

    await call("cA1", 12)
    st = rig.service.store.peek("p1")
    (p,) = [x for x in st.prompts.values() if x.scenario == "S1"]
    r = await rig.client.post(f"{B}/ack", headers=rig.h(t), json={"kind": "this_was_fine", "prompt_id": p.id})
    assert r.status_code == 200 and "remember" in r.json()["message"]
    assert h in st.trusted and st.fine_counts[p.pattern] == 1
    assert any(a["why"] == "parent says this was fine" for a in rig.alerts.of("p1"))
    n = len(rig.alerts.of("p1"))
    rig.clock.advance(hours=3)
    await call("cA2", 15)  # same hashed number: no longer an unknown caller
    assert not [a for a in rig.alerts.of("p1")[n:] if a["scenario"] == "S1"]


async def test_fine_never_teaches_money_or_remote_access(rig):
    t = await rig.pair()
    await sig(rig, t, remote(rig))
    st = rig.service.store.peek("p1")
    (p,) = st.prompts.values()
    await rig.client.post(f"{B}/ack", headers=rig.h(t), json={"kind": "this_was_fine", "prompt_id": p.id})
    assert st.fine_counts == {} and st.trusted == set()
    rig.clock.advance(hours=2)
    await sig(rig, t, remote(rig, "teamviewer"))
    assert len([a for a in rig.alerts.of("p1") if a["tier"] == "HIGH"]) == 2  # still alerts next time


async def test_support_window_downgrades_remote_access(rig):
    t = await rig.pair()
    rig.service.set_policy("p1", support_window_minutes=60)
    await sig(rig, t, remote(rig))
    (a,) = rig.alerts.of("p1")
    assert a["tier"] == "INFO" and rig.service.store.peek("p1").prompts == {}


async def test_i_am_ok_and_s7_recovery(rig):
    t = await rig.pair()
    st = rig.service.store.peek("p1")
    rig.clock.advance(hours=8)
    await rig.service.sweep()
    assert [a["tier"] for a in rig.alerts.of("p1") if a["scenario"] == "S7"] == ["WATCH"] and st.s7_open
    hb = {"app_version": "1", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}}
    await rig.client.post(f"{B}/heartbeat", headers=rig.h(t), json=hb)
    assert not st.s7_open
    assert [a["why"] for a in rig.alerts.of("p1")][-1] == "phone is active again"
    r = await rig.client.post(f"{B}/ack", headers=rig.h(t), json={"kind": "i_am_ok"})
    assert r.status_code == 200 and rig.alerts.of("p1")[-1]["scenario"] == "ACK"


async def test_s7_battery_low_lowers_the_alarm(rig):
    t = await rig.pair()
    await rig.client.post(f"{B}/heartbeat", headers=rig.h(t),
                          json={"app_version": "1", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}, "battery_low": True})
    rig.clock.advance(hours=7)
    await rig.service.sweep()
    assert not [a for a in rig.alerts.of("p1") if a["scenario"] == "S7"]  # 2 - 1 = 1: below WATCH


# ----------------------------------------------------------------------------- merging


async def test_overlapping_scenarios_send_one_parent_nudge(rig):
    t = await rig.pair()
    await sig(rig, t, ev("unknown_call_started", rig.clock.ms, call_id="c9", number_class="mobile"))
    rig.clock.advance(minutes=1)
    await sig(rig, t, ev("call_state_offhook", rig.clock.ms, call_id="c9", duration_s=60, ongoing=True))
    rig.clock.advance(minutes=1)
    await sig(rig, t, ev("unknown_call_ended", rig.clock.ms, call_id="c9", duration_s=120, answered=True))
    rig.clock.advance(minutes=2)
    await sig(rig, t, ev("payment_app_foreground", rig.clock.ms, app="gpay"))  # S3 and S4 both match
    st = rig.service.store.peek("p1")
    scenarios = {f["scenario"] for f in st.findings}
    assert {"S3", "S4"} <= scenarios
    assert len(st.prompts) == 1 and len([a for a in rig.alerts.of("p1")]) == 1
    assert rig.alerts.of("p1")[0]["details"]["also"] == ["voice_clone_panic"]


# ----------------------------------------------------------------------------- shadow week


async def test_shadow_week_then_live_and_counter_report(rig):
    t = await rig.pair(shadow_days=7)
    await sig(rig, t, remote(rig))
    await sig(rig, t, debit(rig))
    assert rig.alerts.calls == []
    rep = rig.service.shadow_report("p1")
    assert rep["active"] and rep["per_scenario"]["S2"]["HIGH"] == 1 and rep["per_scenario"]["S5"]["HIGH"] == 1
    assert rep["would_alert_child"] == 2 and rep["would_nudge"] == 2 and rep["rules_unverified"] is True
    tr = (await rig.client.get(f"{B}/transparency", headers=rig.h(t))).json()
    assert tr["learning_mode"]["active"] and tr["learning_mode"]["days_left"] >= 7
    rig.clock.advance(hours=24 * 7 + 1)
    await sig(rig, t, remote(rig, "teamviewer"))  # a shadow record never blocks the first live alert
    assert [a["scenario"] for a in rig.alerts.of("p1")] == ["S2"]
    assert not rig.service.shadow_report("p1")["active"]


async def test_shadow_simulates_the_nudge_ceiling(rig):
    t = await rig.pair(shadow_days=7)
    for app in ("anydesk", "teamviewer", "rustdesk"):
        rig.service.store.peek("p1").fired.clear()
        await sig(rig, t, remote(rig, app))
        rig.clock.advance(minutes=1)
    rep = rig.service.shadow_report("p1")
    assert rep["would_nudge"] == 3 and rep["would_nudge_ceiling_blocked"] == 1


# ----------------------------------------------------------------------------- call-pattern wiring


async def test_transcript_source_drives_s4p_and_replaces_s4(rig):
    await rig.pair()
    svc = rig.service
    r = await svc.feed_call_turn("p1", "cx1", "caller", "Papa, I had an accident, I am in the hospital", 0,
                                 {"unknown_number": True, "first_contact": True})
    assert r["tier"] in ("NONE", "INFO", "WATCH")
    await svc.feed_call_turn("p1", "cx1", "caller", "Send 50000 rupees urgently, do not tell mummy", 20)
    st = svc.store.peek("p1")
    assert "S4P" in {f["scenario"] for f in st.findings}
    assert any(p.key in ("s4_watch", "s4_high") for p in st.prompts.values())
    text = " ".join(C.PROMPTS["s4_watch"].values()) + " ".join(C.PROMPTS["s4_high"].values())
    assert "safe word" not in text.lower() and "safe-word" not in text.lower()
    assert "accident" not in repr(st.events) and "hospital" not in repr(st.events)  # cues only, no transcript
    assert svc.finish_call("p1", "cx1")["tier"] in ("WATCH", "HIGH")
    assert svc.finish_call("p1", "cx1") is None
    # with a transcript source present the signal-based S4 stays quiet
    rig.clock.advance(minutes=3)
    sigs = [ev("unknown_call_started", rig.clock.ms, call_id="c7", number_class="mobile"),
            ev("unknown_call_ended", rig.clock.ms + 1, call_id="c7", duration_s=90, answered=True)]
    t = await rig.pair("p1")
    await sig(rig, t, *sigs)


async def test_call_pattern_needs_consent(rig):
    await rig.pair(grant=False)
    r = await rig.service.feed_call_turn("p1", "cz", "caller", "I am from the CBI, arrest warrant", 0)
    assert r == {"dropped": "no_consent"}
    assert rig.service.store.peek("p1").events == []


async def test_withdrawing_call_pattern_consent_erases_cues(rig):
    t = await rig.pair()
    await rig.service.feed_call_turn("p1", "cy", "caller", "I am from the CBI, arrest warrant against you, stay on the line", 0)
    assert any(e.type == "call_pattern" for e in rig.service.store.peek("p1").events)
    await rig.client.put(f"{B}/consent", headers=rig.h(t), json={"items": {"call_pattern": False}})
    assert not any(e.type == "call_pattern" for e in rig.service.store.peek("p1").events)


# ----------------------------------------------------------------------------- brand and wording


def test_brand_name_is_defensive(monkeypatch):
    monkeypatch.delenv("FRIDAY_BRAND_NAME", raising=False)
    assert brand_name() == "Friday"
    assert brand_name(object()) == "Friday"
    monkeypatch.setenv("FRIDAY_BRAND_NAME", "Robin")
    assert brand_name() == "Robin"

    class S:
        brand_name = "Rio"

    assert brand_name(S()) == "Rio"


def test_prompt_payload_has_three_languages_and_pending_status(rig):
    from friday.robindevice.engine import ScenarioEngine
    from friday.robindevice.store import Prompt

    eng = ScenarioEngine(rig.service.rules, rig.alerts, rig.consent, rig.parents, brand="Robin")
    p = Prompt("pid123456", "S5", "HIGH", "s5_high", "S5:x", 0, 0, 10, True, {"amount": "Rs 50,000"})
    out = eng.payload(p, "hi")
    assert set(out["text"]) == {"en", "hinglish", "hi"} and "Rs 50,000" in out["text"]["hi"]
    assert out["status"] == "PENDING founder approval" and out["actions"][0]["ack"] == "this_was_fine"
    for text in out["text"].values():
        assert "{" not in text and not text.lower().startswith("this is a scam")


def test_every_line_exists_in_all_three_languages_and_count():
    for name, table in C.lines_by_table().items():
        for key, variants in table.items():
            assert set(variants) == set(C.LANGS), (name, key)
    assert C.pending_line_count() >= 150
    for key, v in C.PROMPTS.items():
        assert any("ऀ" <= ch <= "ॿ" for ch in v["hi"]), key
        for lang in C.LANGS:
            assert "this is a scam" not in v[lang].lower()
