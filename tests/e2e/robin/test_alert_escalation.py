# ruff: noqa: E501
"""Phone signal -> device API -> family alert engine -> the child (tested with fakes). The device HIGH with money must reach the child at once;
'Mark safe' stops everything; a PAUSED family drops device signals; the care protocol silences non-urgent nudges but never an urgent alert."""

from __future__ import annotations

from friday.robin.models import CallResult
from tests.e2e.robin.harness import line


async def paired_world(dworld):
    """Family set up by the child, phone signals + payment alerts switched on by the child, the parent's phone paired and live."""
    w = dworld
    w.script_calls(CallResult.ANSWERED)  # the introduction call
    await w.setup_family()
    await w.consent_device()
    parent = await w.parent()
    await w.device.pair(parent.id)
    w.script_calls(CallResult.NO_ANSWER)  # the parent does not pick up during the incident
    return w, parent


S5 = dict(app="gpay", direction="debit", amount_paise=5_000_000, payee_kind="new")  # Rs 50,000 to a new payee


async def test_device_high_with_money_reaches_the_child_at_once_with_buttons(dworld):
    w, parent = await paired_world(dworld)
    n = len(w.child_texts())
    r = await w.device.signal(w, "payment_notification", **S5)
    assert r.status_code == 200 and r.json()["invalid"] == 0, r.text

    # same instant, no scheduler tick needed: ONE WhatsApp to the child, with the money note and the three buttons
    fresh = w.child_texts()[n:]
    assert len(fresh) == 1, fresh
    assert fresh[0].startswith(line("alert.head.high", why="x").split(":")[0]) and "Papa" in fresh[0]
    assert line("alert.money_note")[:25] in fresh[0]
    ids = [b.id.split(":")[-1] for b in w.child_buttons()]
    assert ids == ["call", "join", "safe"]
    (inc,) = await w.incidents()
    assert inc.data["tier"] == "high" and inc.data["money"] is True and inc.data["scenario"] == "S5"
    # the parent is nudged straight away too (money overrides quiet hours); one call only so far, none to the child yet
    assert [c.purpose for c in w.caller.calls if c.role == "parent"][-1:] == ["nudge"]
    assert w.calls(role="child") == []


async def test_unattended_device_high_rings_the_child_after_five_minutes_and_stays_within_caps(dworld):
    w, _ = await paired_world(dworld)
    await w.device.signal(w, "payment_notification", **S5)
    await w.advance(minutes=4)
    assert w.calls(role="child") == []
    await w.advance(minutes=1)  # +5 min: the first ring to the child
    assert [c.purpose for c in w.calls(role="child")] == ["escalation_child"]
    await w.advance(minutes=5)
    await w.advance(minutes=5)
    await w.advance(hours=2)
    assert len(w.calls(role="child")) <= 2  # the HIGH plan rings the child twice
    assert len(w.calls(role="parent", purpose="nudge")) <= 3  # 3 calls to the parent per incident at most
    # the engine's own daily ceiling: no person gets more than 3 escalation calls in a day
    rows = [r for r in await w.audit_rows() if r.data.get("event") == "call" and r.data.get("purpose") == "escalation_child"]
    assert len(rows) <= 3
    (inc,) = await w.incidents()
    assert inc.status in ("open", "exhausted") and inc.data["calls"].get("child", 0) <= 3


async def test_mark_safe_stops_the_ladder_and_nothing_more_rings(dworld):
    w, _ = await paired_world(dworld)
    await w.device.signal(w, "payment_notification", **S5)
    n_calls = len(w.caller.calls)
    out = await w.tap("safe")
    assert line("alert.safe") in " ".join(w.child_texts()[-2:]) or any(line("alert.safe") in o for o in out)
    (inc,) = await w.incidents()
    assert inc.status == "closed" and inc.data["closed_by"] == "child_safe"
    await w.advance(minutes=10)
    await w.advance(minutes=30)
    escalation = [c for c in w.caller.calls if c.purpose in ("nudge", "escalation_child", "escalation_second")]
    assert len(escalation) == 1, "no further call about this alert after 'Mark safe' (the one nudge was before the tap)"
    assert w.calls(role="child") == [] and len(w.caller.calls) >= n_calls


async def test_i_have_it_from_the_child_also_stops_it(dworld):
    w, _ = await paired_world(dworld)
    await w.device.signal(w, "payment_notification", **S5)
    await w.child_says("I have it")
    (inc,) = await w.incidents()
    assert inc.status == "closed" and inc.data["closed_by"] == "child_has_it"


async def test_device_signals_are_dropped_while_the_parent_has_paused_robin(dworld):
    w, parent = await paired_world(dworld)
    await w.parent_says("Robin, band karo")
    n_child, n_calls = len(w.child_texts()), len(w.caller.calls)
    r = await w.device.signal(w, "payment_notification", **S5)
    assert r.status_code == 200  # the phone is not told anything is wrong
    assert await w.incidents() == []
    assert len(w.child_texts()) == n_child and len(w.caller.calls) == n_calls
    # ... and nobody else can switch it back on: only the parent resumes
    assert await w.hub.fam.resume(parent.id, "admin_chat", actor="admin_on_behalf") is False
    await w.device.signal(w, "payment_notification", **S5)
    assert await w.incidents() == []
    await w.parent_says("shuru karo")
    await w.advance(minutes=10)  # past the engine's duplicate-window for the same payment
    await w.device.signal(w, "payment_notification", **{**S5, "amount_paise": 6_000_000})
    assert len(await w.incidents()) == 1


async def test_without_the_childs_consent_the_phone_signal_does_not_alert(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()  # no 'enable device signals' / 'enable payment alerts'
    parent = await w.parent()
    await w.device.pair(parent.id)
    n = len(w.child_texts())
    await w.device.signal(w, "payment_notification", **S5)
    assert await w.incidents() == [] and len(w.child_texts()) == n


async def test_care_protocol_phrase_from_the_child_silences_non_urgent_nudges_but_not_an_urgent_alert(dworld):
    w, _ = await paired_world(dworld)
    out = await w.child_says("I want to die")  # the child's own words: the care protocol takes over (never the brain)
    assert out and "14416" in out[0]
    # the daily check-in is held back (care active) ...
    await w.advance(hours=1)
    assert w.calls(purpose="checkin") == []
    rows = [r.data.get("detail") for r in await w.audit_rows() if r.data.get("event") == "call" and r.data.get("purpose") == "checkin"]
    assert rows == ["care_active"]
    # ... so is a WATCH-level nudge to the parent (a long unknown call alone is WATCH in careful mode; here a small known-payee debit is WATCH)
    n = len(w.calls(role="parent"))
    await w.device.signal(w, "payment_notification", app="hdfc", direction="debit", amount_paise=2_000_000, payee_kind="known")
    assert len(w.calls(role="parent")) == n
    # ... but an urgent HIGH-with-money alert still reaches the child and rings the parent
    n_child = len(w.child_texts())
    await w.device.signal(w, "payment_notification", **S5)
    assert len(w.child_texts()) > n_child
    assert [c.purpose for c in w.calls(role="parent")][-1:] == ["nudge"]


async def test_device_tier_spelling_does_not_matter_end_to_end(dworld):
    """T01 regression through the real service: the device package says 'HIGH' / 'S5'; the family engine acts on it."""
    w, parent = await paired_world(dworld)
    from friday.robin import alerts as alerts_mod

    res = await alerts_mod.raise_alert(alerts_mod.RobinAlert(parent.id, "HIGH", "S2", "remote access app opened", signals=("pattern_s2",)))  # type: ignore[arg-type]
    assert res.accepted and res.reason == "ok"


async def test_two_different_payments_minutes_apart_are_two_alerts_to_the_child(dworld):
    """Found by this harness: the family engine merged any two alerts of one scenario and tier inside 5 minutes, so the second payment was never told."""
    w, _ = await paired_world(dworld)
    await w.device.signal(w, "payment_notification", **S5)
    n = len(w.child_texts())
    await w.advance(minutes=2)
    await w.device.signal(w, "payment_notification", **{**S5, "amount_paise": 3_000_000})
    heads = [t for t in w.child_texts()[n:] if t.startswith("Important")]
    assert len(heads) == 1 and "Rs 30,000" in heads[0]
    assert len(await w.incidents()) == 2


async def test_device_signals_only_consent_still_alerts_for_a_payment_app_scenario(dworld):
    """S3 (payment app opened during a long unknown call) is flagged money; a family that agreed to device signals but not payment alerts must still be told."""
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    await w.child_says("enable device signals")  # NOT payment alerts
    parent = await w.parent()
    await w.device.pair(parent.id)
    w.script_calls(CallResult.NO_ANSWER)
    n = len(w.child_texts())
    await w.device.signal(w, "unknown_call_started", call_id="c1", number_class="mobile")
    await w.advance(minutes=5)
    await w.device.signal(w, "call_state_offhook", call_id="c1", duration_s=300, ongoing=True)
    await w.advance(minutes=1)
    await w.device.signal(w, "payment_app_foreground", app="phonepe")
    heads = [t for t in w.child_texts()[n:] if t.startswith("Important")]
    assert len(heads) == 1 and line("alert.money_note")[:25] in heads[0]


async def test_a_money_alert_at_night_still_reaches_the_child_and_rings_the_parent(dworld):
    """23:30 is inside quiet hours and outside the calling window: money HIGH is the documented exception."""
    from datetime import datetime

    from friday.core.clock import IST
    from tests.e2e.robin.harness import RobinWorld

    await dworld.close()
    w = await RobinWorld.start(device=True, now=datetime(2026, 1, 5, 21, 0, tzinfo=IST))
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        await w.consent_device()
        parent = await w.parent()
        await w.device.pair(parent.id)
        w.script_calls(CallResult.NO_ANSWER)
        w.clock.set(datetime(2026, 1, 5, 23, 30, tzinfo=IST))
        n = len(w.child_texts())
        await w.device.signal(w, "payment_notification", **S5)
        assert len(w.child_texts()) == n + 1
        assert [c.purpose for c in w.calls(role="parent")][-1:] == ["nudge"]  # money overrides quiet hours
        await w.advance(minutes=5)
        assert [c.purpose for c in w.calls(role="child")] == ["escalation_child"]  # ... and the calling window
    finally:
        await w.close()


async def test_a_child_in_a_care_episode_can_still_stop_an_alert_with_the_button(dworld):
    """The care protocol takes over the child's chat; it must not swallow 'Mark safe' on a parent's alert."""
    w, _ = await paired_world(dworld)
    await w.device.signal(w, "payment_notification", **S5)
    await w.child_says("I want to die")
    await w.tap("safe")
    (inc,) = await w.incidents()
    assert inc.status == "closed" and inc.data["closed_by"] == "child_safe"
