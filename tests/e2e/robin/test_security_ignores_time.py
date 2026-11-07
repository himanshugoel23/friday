# ruff: noqa: E501
"""T20 (founder, 2026-11-06): "It is about security, so security things should not take timing into consideration."

Every security/safety path (HIGH and above, SOS, fall/threat, urgent missed-call rings, the emergency desk's dry-run) ignores the calling window and
quiet hours, day or night; only the anti-flood caps and the parent's own pause apply. WATCH nudges, INFO, check-ins, medicine reminders and digests
still respect both. The table below runs EVERY (scenario, tier) through the real engine, the real CallGate (calling window 08:00 to 21:30 IST) and
the family's quiet hours at 03:00 IST (tested with fakes: the parent's phone is a recording fake, nothing is dialled or sent anywhere).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from friday.core.clock import IST
from friday.robin.alerts import RobinAlert
from friday.robin.models import AnswerRaw, CallResult, Step, Tier
from tests.e2e.robin.harness import CHILD, PARENT, SECOND, RobinWorld

NIGHT = datetime(2026, 1, 6, 3, 0, tzinfo=IST)  # 03:00 IST, inside quiet hours (22:00 to 07:00) and outside the calling window
SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "checkin_unanswered", "sos", "threat")
ALL_TIERS = (Tier.INFO, Tier.WATCH, Tier.HIGH, Tier.EMERGENCY)
ONLY_EMERGENCY = {"sos", "threat"}  # these only exist as EMERGENCY (the parent pressed help / said they are threatened)
CASES = [(s, t) for s in SCENARIOS for t in ((Tier.EMERGENCY,) if s in ONLY_EMERGENCY else ALL_TIERS)]
REFUSED_BY_TIME = ("quiet_hours", "outside_window")


def is_security(scenario: str, tier: Tier) -> bool:
    return tier in (Tier.HIGH, Tier.EMERGENCY) or scenario in ONLY_EMERGENCY


async def night_world(**kw) -> RobinWorld:
    """Active family with a named second contact, set up in the daytime; then the clock jumps to 03:00 IST the next day. Nobody answers any call."""
    w = await RobinWorld.start(**kw)
    w.script_calls(CallResult.ANSWERED)  # the introduction call
    await w.setup_family(second=SECOND)
    await w.consent_device()
    w.script_calls(CallResult.NO_ANSWER)
    w.hub.ctx.extra_senders["second"] = _second_sink
    return w


async def _second_sink(member, text):  # the second contact's WhatsApp: a no-op fake
    return None


def go_to_night(w: RobinWorld, day: int) -> None:
    w.clock.set(NIGHT.replace(day=NIGHT.day + day))


async def time_refusals(w: RobinWorld, incident_id: str | None = None) -> list[str]:
    return [r.data.get("detail", "") for r in await w.audit_rows() if r.data.get("event") == "call" and (incident_id is None or r.data.get("incident_id") == incident_id) and any(k in str(r.data.get("detail", "")) for k in REFUSED_BY_TIME)]


def rings(w: RobinWorld, role: str | None = None, purpose: str | None = None):  # noqa: ANN201
    """Calls since the family was set up (the daytime introduction call is left out)."""
    return [c for c in w.calls(role=role, purpose=purpose) if c.purpose != "intro"]


# ---------------------------------------------------------------------------- the table
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_table_every_scenario_and_tier_at_0300_security_ignores_the_window_and_the_rest_respects_it(scenario):
    w = await night_world()
    try:
        parent = await w.parent()
        for day, tier in enumerate(t for s, t in CASES if s == scenario):  # one night per tier: the per-person daily call cap never mixes two cases
            go_to_night(w, day)
            before = len(w.caller.calls)
            res = await w.hub.alerts.raise_alert(RobinAlert(parent.id, tier, scenario, f"table {scenario} {tier.value}", dedupe_key=f"t20:{scenario}:{tier.value}"))
            assert res.accepted, (scenario, tier, res.reason)
            for _ in range(5):  # 03:00 to 03:25: past every step of the ladder that rings (steps are 0 to 5 minutes apart)
                await w.advance(minutes=5)
            rang = w.caller.calls[before:]
            ctx = f"{scenario}/{tier.value}"
            if is_security(scenario, tier):
                assert [c for c in rang if c.role == "child"], f"{ctx}: a security alert must ring the child at 03:00 IST, got {[(c.role, c.purpose) for c in rang]}"
                assert not await time_refusals(w, res.incident_id), f"{ctx}: a security call was refused by quiet hours or the calling window: {await time_refusals(w, res.incident_id)}"
            else:
                assert rang == [], f"{ctx}: a non-security item must not ring at 03:00 IST: {[(c.role, c.purpose) for c in rang]}"
                if tier == Tier.WATCH:
                    (inc,) = [i for i in await w.incidents() if i.key == f"t20:{scenario}:{tier.value}"]
                    nudge = [s["result"] for s in inc.data["steps"] if s["action"] == "nudge_parent"]
                    assert (nudge or scenario == "checkin_unanswered") and all(r == "skipped:quiet_hours" for r in nudge), f"{ctx}: WATCH still respects quiet hours: {nudge}"
    finally:
        await w.close()


async def test_table_the_rule_is_not_vacuous_a_non_security_call_is_refused_and_a_security_call_is_not_at_0300():
    w = await night_world()
    try:
        go_to_night(w, 0)
        fam, parent, child = await w.family(), await w.parent(), None
        child = await w.hub.ctx.child(fam)
        step = [Step(line="child.ring", slots={"parent": "Papa", "child": "ji"})]
        c = w.hub.ctx
        # non-security: the parent's check-in / medicine / digest-style calls respect quiet hours; a plain call to the child respects the calling window
        for purpose in ("checkin", "medicine", "callnow"):
            out = await c.call(fam, parent, purpose, step, dedupe_key=f"ns:{purpose}")
            assert out.result == CallResult.REFUSED and out.detail == "quiet_hours", (purpose, out.detail)
        out = await c.call(fam, child, "escalation_child", step, dedupe_key="ns:child")
        assert out.result == CallResult.REFUSED and "outside_window" in out.detail, out.detail
        assert w.caller.calls == [] or all(x.purpose not in ("checkin", "medicine", "callnow", "escalation_child") for x in w.caller.calls)
        # security: same calls, same hour, flagged as security: they go out
        out = await c.call(fam, child, "escalation_child", step, dedupe_key="s:child", security=True)
        assert out.result != CallResult.REFUSED, out.detail
        out = await c.call(fam, parent, "nudge", step, dedupe_key="s:parent", security=True)
        assert out.result != CallResult.REFUSED, out.detail
        # the parent's own pause still wins over security
        await w.parent_says("Robin, band karo")
        out = await c.call(fam, await w.parent(), "nudge", step, dedupe_key="s:paused", security=True)
        assert out.result == CallResult.REFUSED and out.detail == "parent_paused"
    finally:
        await w.close()


# ---------------------------------------------------------------------------- HIGH rings the child at night even without money
async def test_non_money_high_rings_the_parent_and_then_the_child_at_night():
    w = await night_world()
    try:
        go_to_night(w, 0)
        parent = await w.parent()
        await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S2", "remote access app opened during a call", dedupe_key="t20:night-high"))
        assert [c.purpose for c in rings(w, "parent")] == ["nudge"]  # the first nudge rings at once, 03:00 IST
        await w.advance(minutes=5)
        assert [c.purpose for c in w.calls(role="child")] == ["escalation_child"]  # +5 minutes: the child's phone rings at 03:05 IST
        await w.advance(minutes=5)
        assert len(w.calls(role="child")) == 2 and len(rings(w, "parent")) <= 3
        assert not await time_refusals(w)
    finally:
        await w.close()


async def test_watch_and_info_at_night_stay_quiet_but_the_child_is_still_told_by_message():
    w = await night_world()
    try:
        go_to_night(w, 0)
        parent = await w.parent()
        n = len(w.child_texts())
        await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.WATCH, "S6", "night video activity", dedupe_key="t20:w"))
        await w.advance(minutes=30)
        assert rings(w) == [] and len(w.child_texts()) == n + 1  # one WhatsApp, no ring, no parent nudge
        assert [n for n in await w.hub.fam.take_app_notifications(parent.id) if n["purpose"] == "nudge"] == []
    finally:
        await w.close()


# ---------------------------------------------------------------------------- SOS and the emergency desk at night
async def test_sos_at_night_rings_child_and_second_contact_and_the_desk_dry_run_runs():
    w = await RobinWorld.start(device=True, robin_authority_calls_enabled=True)
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family(second=SECOND)
        await w.child_says("enable authority calls")
        await w.child_says("parent name Ramesh Verma")
        await w.child_says("address 12 Test Lane, Pune")
        w.hub.ctx.extra_senders["second"] = _second_sink
        await w.device.pair((await w.parent()).id)
        w.script_calls(CallResult.NO_ANSWER)
        go_to_night(w, 0)
        assert (await w.device.sos()).status_code == 200
        for _ in range(5):
            await w.advance(minutes=5)
        assert len(w.calls(role="child")) == 3 and len(w.calls(role="second_contact")) == 1
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1  # the desk's 60-second 'I am fine' countdown call to the parent, 03:15 IST
        (rec,) = await w.authority_records()
        assert rec.status == "dry_run"  # the desk acted (dry run: nothing dialled) at night too
        assert not await time_refusals(w)
        assert w.f.c.telephony.legs == []
    finally:
        await w.close()


# ---------------------------------------------------------------------------- an urgent missed call keeps ringing at night
async def test_urgent_missed_call_rings_the_parent_through_the_night():
    w = await night_world()
    try:
        go_to_night(w, 0)
        res = await w.hub.on_missed_call(PARENT, CHILD, [AnswerRaw(line="missed.ask_who", text="beta"), AnswerRaw(line="missed.ask_urgent", text="yes")])
        assert res is not None and res.urgent
        for _ in range(5):
            await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 6  # 6 tries, 3 minutes apart, all at 03:00 to 03:15 IST
        assert not await time_refusals(w)
        # ... and a missed call to the CHILD at night rings the child
        go_to_night(w, 1)
        await w.hub.on_missed_call(CHILD, PARENT, [AnswerRaw(line="missed.ask_who", text="papa"), AnswerRaw(line="missed.ask_urgent", text="yes")])
        assert [c.purpose for c in w.calls(role="child")][-1] == "emergency_ring"
    finally:
        await w.close()


# ---------------------------------------------------------------------------- caps and pause still apply
async def test_the_alert_flood_cap_still_holds_a_minor_alert_but_never_an_emergency_at_night():
    w = await night_world()
    try:
        go_to_night(w, 0)
        parent = await w.parent()
        for i in range(10):
            await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.WATCH, "S6", f"minor {i}", dedupe_key=f"t20:flood:{i}"))
        n = len(w.child_texts())
        await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.WATCH, "S6", "minor 11", dedupe_key="t20:flood:11"))
        assert len(w.child_texts()) == n + 1  # one 'many alerts' summary, not the eleventh alert
        await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "S2", "emergency", dedupe_key="t20:flood:em"))
        assert any("emergency" in t.lower() for t in w.child_texts()[n + 1 :])  # EMERGENCY is never capped
        assert [c for c in w.calls(role="child")]  # and it rang the child at night
    finally:
        await w.close()


async def test_the_parents_own_pause_stops_a_non_sos_security_alert_at_night():
    w = await night_world()
    try:
        parent = await w.parent()
        await w.parent_says("Robin, band karo")
        go_to_night(w, 0)
        res = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S2", "remote access", dedupe_key="t20:paused"))
        assert not res.accepted and res.reason == "paused"
        assert rings(w) == []
    finally:
        await w.close()


# ---------------------------------------------------------------------------- the child's typed words stop an alert during a care episode
@pytest.mark.parametrize("word,by", [("I have it", "child_has_it"), ("Mark safe", "child_safe")])
async def test_typed_ack_during_an_open_care_episode_stops_the_alert(word, by):
    w = await night_world()
    try:
        parent = await w.parent()
        await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S2", "remote access app opened", dedupe_key=f"t20:care:{by}"))
        (inc,) = await w.incidents()
        assert inc.status in ("open", "exhausted")
        await w.child_says("I do not want to live anymore")  # the care protocol opens an episode (it answers with the helpline lines)
        user_id = (await w.child.user_row()).id
        assert await w.f.rt.pipeline.care.is_active(user_id)
        out = await w.child_says(word)
        (inc,) = await w.incidents()
        assert inc.status == "closed" and inc.data["closed_by"] == by, (out, inc.status)
        # a distressed message during the episode is still the care protocol's, never Robin's
        out = await w.child_says("I have it but I want to die")
        (inc,) = await w.incidents()
        assert inc.data["closed_by"] == by
    finally:
        await w.close()


async def test_typed_ack_without_an_open_alert_is_still_the_care_protocols_during_an_episode():
    w = await night_world()
    try:
        await w.child_says("I do not want to live anymore")
        user_id = (await w.child.user_row()).id
        assert await w.f.rt.pipeline.care.is_active(user_id)
        n_calls = len(w.caller.calls)
        out = await w.child_says("Mark safe")
        assert out, "the care protocol answered (nothing to stop, so it is not passed to Robin)"
        assert len(w.caller.calls) == n_calls
    finally:
        await w.close()


# ---------------------------------------------------------------------------- the second contact's production sender
async def test_the_production_second_contact_sender_is_wired_and_carries_only_the_alert_line_to_the_named_contact():
    from friday.core.models import OutboundMessage
    from friday.robin.wiring import make_second_sender

    w = await RobinWorld.start()
    try:
        sender = w.hub.ctx.extra_senders.get("second")
        assert sender is not None and sender.__name__ == "send_second"  # build_robin registered it (the same object the strict xfail asked for)
        w.script_calls(CallResult.ANSWERED)
        fam = await w.setup_family(second=SECOND)
        second = await w.hub.ctx.second(fam)
        parent = await w.parent()
        sent: list[OutboundMessage] = []

        class FakeNotifier:
            ok = True

            async def send(self, msg: OutboundMessage):  # noqa: ANN201
                sent.append(msg)

                class R:
                    pass

                r = R()
                r.ok, r.error = self.ok, "template_required"  # type: ignore[attr-defined]
                return r

        fake = FakeNotifier()
        send = make_second_sender(lambda: fake)
        await send(second, "Papa may need help.")
        assert len(sent) == 1 and sent[0].to_phone == SECOND and sent[0].text == "Papa may need help." and sent[0].template is None and sent[0].buttons == []
        # only the named second contact: never the parent, never the child, never one who did not agree
        for other in (parent, await w.hub.ctx.child(fam)):
            with pytest.raises(PermissionError):
                await send(other, "x")
        second.call_ok = False
        with pytest.raises(PermissionError):
            await send(second, "x")
        second.call_ok = True
        fake.ok = False  # the Notifier refused (e.g. outside the 24 h window): the engine must hear about it
        with pytest.raises(RuntimeError):
            await send(second, "x")
        assert len(sent) == 2
        # through the engine (Ctx.tell_second): a refusal comes back False, so the audit says "could not send"
        assert await w.hub.ctx.tell_second(fam, second, "alert") is False  # the real sender over the simulator channel: no inbound from this number in 24 h, so a template is required (Meta blocked): reported as not sent
    finally:
        await w.close()
