"""Proactive engine: every trigger + every guardrail, autonomy levels, feedback."""

import asyncio
from datetime import date, datetime, timedelta

from friday.core.clock import IST, to_ist
from friday.core.models import (
    AutonomyCategory,
    AutonomyLevel,
    AutonomySetting,
    CallOutcome,
    CareOutcome,
    ContactTarget,
    Fact,
    FactKind,
    HotelBooking,
    HotelBookingMode,
    HotelBookingStatus,
    HotelProperty,
    Nudge,
    NudgeCandidate,
    NudgeDecision,
    NudgeKind,
    NudgeStatus,
    Person,
    Recurrence,
    RecurrenceRule,
    TargetKind,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
    Urgency,
)
from friday.proactive.guardrails import evaluate
from friday.tasks.events import WellbeingAlertRaised
from tests.tasks.conftest import LOOKS


def ist(*a):
    return datetime(*a, tzinfo=IST)


async def add_task(env, *, appt=None, status=TaskStatus.COMPLETED, created=None, **kw):
    t = Task(
        requester_user_id=env.user.id,
        type=kw.pop("type", TaskType.BOOKING),
        spec=kw.pop("spec", TaskSpec(type=TaskType.BOOKING, goal="Haircut", business_id="b1")),
        status=status,
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks", phone=LOOKS),
        last_outcome=CallOutcome.SUCCESS,
        result=kw.pop("result", TaskResult(success=True, summary="ok", appointment_at=appt)),
        created_at=created or env.clock.now(),
        **kw,
    )
    await env.repos.tasks.add(t)
    return t


async def add_fact(env, key, due, **kw):
    f = Fact(user_id=env.user.id, kind=FactKind.DATE, key=key, value=key, due_on=due, **kw)
    await env.repos.facts.upsert(f)
    return f


def sent(env):
    return env.repos.nudges.by_status(NudgeStatus.SENT)


async def test_task_reminder_urgent_and_dedupe(env, pe):
    await add_task(env, appt=env.clock.now() + timedelta(minutes=90))
    out = await pe.tick()
    assert len(out) == 1 and out[0].kind == NudgeKind.TASK_REMINDER
    assert out[0].urgency == Urgency.URGENT
    msg = env.notifier.last()
    assert msg.nudge_id == out[0].id and msg.template.key == "nudge"
    assert [b.title for b in msg.buttons] == ["Got it", "Not now", "Stop these"]
    assert env.notifier.sent[-1][1] == Urgency.URGENT
    assert await pe.tick() == []  # dedupe


async def test_evening_before_reminder(env, pe):
    env.clock.set(ist(2026, 1, 5, 20, 30))
    await add_task(env, appt=ist(2026, 1, 6, 10, 0))
    out = await pe.tick()
    assert [n.dedupe_key.endswith(":eve") for n in out] == [True]


async def test_quiet_hours_schedule_then_send_and_safety_bypass(env, pe):
    env.clock.set(ist(2026, 1, 5, 23, 0))
    await add_fact(env, "rent_due", date(2026, 1, 7))  # 1 day lead -> fires on the 6th (IST)
    env.clock.set(ist(2026, 1, 6, 6, 0))
    await pe.tick()
    sched = env.repos.nudges.by_status(NudgeStatus.SCHEDULED)
    assert len(sched) == 1 and to_ist(sched[0].scheduled_for).hour == 8
    assert env.notifier.sent == []
    # SAFETY goes out at once even in quiet hours
    await env.bus.publish(WellbeingAlertRaised(task_id="t1", user_id=env.user.id, text="Dad fell"))
    assert env.notifier.sent[-1][1] == Urgency.SAFETY
    assert "Dad fell" in env.notifier.last().text
    env.clock.set(ist(2026, 1, 6, 8, 0))
    out = await pe.tick()
    assert [n.kind for n in out] == [NudgeKind.DATE_BASED]
    assert env.repos.nudges.items[sched[0].id].status == NudgeStatus.SENT


async def test_stale_in_quiet_hours_suppressed(env, pe):
    env.clock.set(ist(2026, 1, 5, 23, 0))
    await add_task(env, appt=ist(2026, 1, 6, 0, 30))
    await pe.tick()
    sup = env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)
    assert sup and "stale" in sup[0].reason


async def test_daily_cap_three_and_urgent_exempt(env, pe):
    today = to_ist(env.clock.now()).date()
    for i, key in enumerate(["rent_due", "emi_due", "bill_due", "fee_due"]):
        await add_fact(env, f"{key}{i}", today + timedelta(days=1))
    await pe.tick()
    assert len(sent(env)) == 3
    sup = env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)
    assert len(sup) == 1 and sup[0].reason == "daily cap reached"
    await add_task(env, appt=env.clock.now() + timedelta(minutes=60))
    await pe.tick()
    assert len(sent(env)) == 4  # urgent reminder exempt


async def test_autonomy_disabled_and_stop_button(env, pe):
    await env.repos.autonomy.upsert(
        AutonomySetting(user_id=env.user.id, category=AutonomyCategory.REMINDERS, enabled=False)
    )
    await add_fact(env, "rent_due", to_ist(env.clock.now()).date() + timedelta(days=1))
    await pe.tick()
    assert env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)[0].reason.startswith("user stopped")
    # stop via button disables the category
    f2 = await add_fact(
        env, "birthday_mom", to_ist(env.clock.now()).date() + timedelta(days=3), person_id="p1"
    )
    out = await pe.tick()
    assert out[0].fact_id == f2.id and out[0].category == AutonomyCategory.FAMILY
    await pe.handle_nudge_action(out[0].id, "stop")
    settings = await env.repos.autonomy.list_for_user(env.user.id)
    assert any(s.category == AutonomyCategory.FAMILY and not s.enabled for s in settings)
    assert env.repos.nudges.feedback[-1].type.value == "stop"


async def history(env, kind, statuses, sent_at):
    for i, st in enumerate(statuses):
        n = Nudge(
            user_id=env.user.id,
            kind=kind,
            category=AutonomyCategory.REMINDERS,
            dedupe_key=f"old{i}",
            status=st,
            sent_at=sent_at,
            created_at=sent_at - timedelta(minutes=10 - i),
            responded_at=sent_at,
        )
        await env.repos.nudges.add(n)


async def test_ignore_learning_suppress_backoff_and_reset(env, pe):
    now = env.clock.now()
    await history(env, NudgeKind.DATE_BASED, [NudgeStatus.IGNORED] * 3, now - timedelta(days=3))
    await add_fact(env, "rent_due", to_ist(now).date() + timedelta(days=1))
    await pe.tick()
    assert env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)[0].reason == "ignored 3 in a row"


async def test_ignore_backoff_after_two(env, pe):
    now = env.clock.now()
    await history(
        env,
        NudgeKind.DATE_BASED,
        [NudgeStatus.IGNORED, NudgeStatus.DISMISSED],
        now - timedelta(hours=20),
    )
    await add_fact(env, "rent_due", to_ist(now).date() + timedelta(days=1))
    await pe.tick()
    assert (
        env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)[0].reason == "backing off after ignores"
    )


async def test_acted_resets_streak(env, pe):
    now = env.clock.now()
    await history(
        env,
        NudgeKind.DATE_BASED,
        [NudgeStatus.IGNORED, NudgeStatus.IGNORED, NudgeStatus.IGNORED, NudgeStatus.ACTED],
        now - timedelta(days=3),
    )
    await add_fact(env, "rent_due", to_ist(now).date() + timedelta(days=1))
    await pe.tick()
    assert len(sent(env)) == 1


async def test_unanswered_marked_ignored_after_24h(env, pe):
    await add_task(env, appt=env.clock.now() + timedelta(minutes=90))
    [n] = await pe.tick()
    env.clock.advance(hours=25)
    await pe.tick()
    assert env.repos.nudges.items[n.id].status == NudgeStatus.IGNORED
    assert env.repos.nudges.feedback[-1].type.value == "ignored"


async def test_levels_inform_suggest_auto_and_undo(env, pe):
    spec = TaskSpec(
        type=TaskType.BOOKING,
        goal="usual haircut",
        business_phone=LOOKS,
        business_name="Looks Unisex Salon",
    )
    env.brain.decisions["date_based"] = NudgeDecision(
        send=True, text="Rent due tomorrow", proposed_task=spec
    )
    from tests.tasks.fakes import offer_then_confirm

    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    day = to_ist(env.clock.now()).date() + timedelta(days=1)
    # level 1 inform: no action besides Got it / Stop
    await env.repos.autonomy.upsert(
        AutonomySetting(
            user_id=env.user.id, category=AutonomyCategory.REMINDERS, level=AutonomyLevel.INFORM
        )
    )
    await add_fact(env, "rent_due_a", day)
    [n1] = await pe.tick()
    assert n1.proposed_task is None and [b.title for b in n1.buttons] == ["Got it", "Stop these"]
    # level 2 suggest: Yes -> task created (the tap is the request)
    await env.repos.autonomy.upsert(
        AutonomySetting(
            user_id=env.user.id, category=AutonomyCategory.REMINDERS, level=AutonomyLevel.SUGGEST
        )
    )
    await add_fact(env, "rent_due_b", day)
    [n2] = await pe.tick()
    assert n2.buttons[0].id.endswith(":yes")
    await pe.handle_nudge_action(n2, "yes")
    await env.engine.drain()
    created = [t for t in env.repos.tasks.items.values() if t.spec.goal == "usual haircut"]
    assert len(created) == 1 and created[0].status == TaskStatus.AWAITING_APPROVAL  # call-back rule
    assert env.repos.nudges.items[n2.id].status == NudgeStatus.ACTED
    # level 4: acts at once, reports with Undo
    await env.repos.autonomy.upsert(
        AutonomySetting(
            user_id=env.user.id,
            category=AutonomyCategory.REMINDERS,
            level=AutonomyLevel.ACT_AUTOMATICALLY,
        )
    )
    await add_fact(env, "rent_due_c", day)
    env.runner.gate = asyncio.Event()
    [n3] = await pe.tick()
    assert n3.status == NudgeStatus.ACTED and n3.buttons[0].title == "Undo" and n3.task_id
    await pe.handle_nudge_action(n3.id, "undo")
    env.runner.gate.set()
    await env.engine.drain()
    assert env.repos.tasks.items[n3.task_id].status == TaskStatus.CANCELLED


async def test_brain_declines_and_consent_gate(env, pe):
    env.brain.decisions["date_based"] = NudgeDecision(send=False, reason="not useful")
    await add_fact(env, "rent_due", to_ist(env.clock.now()).date() + timedelta(days=1))
    await pe.tick()
    assert env.repos.nudges.by_status(NudgeStatus.SUPPRESSED)[0].reason == "not useful"
    dad = Person(owner_user_id=env.user.id, name="Dad", phone="+919833333333")
    await env.repos.people.upsert(dad)
    cand = NudgeCandidate(
        user_id=env.user.id,
        kind=NudgeKind.TASK_REMINDER,
        category=AutonomyCategory.FAMILY,
        reason="x",
        due_at=env.clock.now(),
        dedupe_key="to-dad",
        data={"recipient_person_id": dad.id},
    )
    n = await pe.process(cand)
    assert n.status == NudgeStatus.SUPPRESSED and "opted in" in n.reason


async def test_brain_buttons_rekeyed_and_brain_failure(env, pe):
    from friday.core.models import ReplyButton

    env.brain.decisions["date_based"] = NudgeDecision(
        send=True, text="x", buttons=[ReplyButton(id="call", title="Yes, call")]
    )
    await add_fact(env, "rent_due", to_ist(env.clock.now()).date() + timedelta(days=1))
    [n] = await pe.tick()
    assert n.buttons[0].id == f"n:{n.id}:call"

    async def boom(ctx, c):
        raise RuntimeError

    env.brain.judge_nudge = boom
    await add_fact(env, "emi_due", to_ist(env.clock.now()).date() + timedelta(days=1))
    out = await pe.tick()
    assert out and out[0].text  # fallback copy, still actionable
    assert out[0].buttons


async def test_follow_up_care_recurring_stay_triggers(env, pe):
    now = env.clock.now()
    await add_task(
        env,
        result=TaskResult(success=True, summary="plumber", follow_up_at=now - timedelta(hours=1)),
    )
    await add_task(
        env,
        type=TaskType.CUSTOMER_CARE,
        result=TaskResult(
            success=True,
            summary="ticket",
            care=CareOutcome(company="Airtel", ticket_number="SR1", promised_date=date(2026, 1, 3)),
        ),
    )
    rule = RecurrenceRule(freq=Recurrence.WEEKLY, next_run_at=ist(2026, 1, 6, 10, 0))
    await add_task(
        env, type=TaskType.RECURRING_BOOKING, status=TaskStatus.SCHEDULED, recurrence=rule
    )
    env.clock.set(ist(2026, 1, 5, 18, 30))
    hb = HotelBooking(
        provider="direct_call",
        mode=HotelBookingMode.DIRECT_HOLD,
        status=HotelBookingStatus.CONFIRMED,
        property=HotelProperty(
            provider="x", property_id="p", name="Lakeview", address="Lake Pichola"
        ),
        check_in=date(2026, 1, 6),
        check_out=date(2026, 1, 8),
    )
    await add_task(
        env,
        type=TaskType.HOTEL_BOOKING,
        result=TaskResult(success=True, summary="s", hotel_booking=hb),
    )
    kinds = {c.dedupe_key.split(":")[0] for c in await pe.candidates(env.user.id)}
    assert {"followup", "care", "recurring", "stay"} <= kinds


async def test_pattern_nudge(env, pe):
    base = ist(2025, 11, 10, 11, 0)
    for i in range(3):
        await add_task(env, created=base + timedelta(days=28 * i))
    env.clock.set(base + timedelta(days=28 * 3, hours=2))
    cands = [c for c in await pe.candidates(env.user.id) if c.kind == NudgeKind.PATTERN]
    assert len(cands) == 1 and "4 weeks" in cands[0].reason
    env.clock.set(base + timedelta(days=28 * 3 + 5))
    assert not [c for c in await pe.candidates(env.user.id) if c.kind == NudgeKind.PATTERN]


async def test_morning_briefing_opt_in_and_skip_empty(env, pe):
    prof = await env.repos.profiles.get(env.user.id)
    env.clock.set(ist(2026, 1, 6, 8, 5))
    assert not [c for c in await pe.candidates(env.user.id) if c.kind == NudgeKind.MORNING_BRIEFING]
    prof.morning_briefing = True
    await env.repos.profiles.save(prof)
    assert not [
        c for c in await pe.candidates(env.user.id) if c.kind == NudgeKind.MORNING_BRIEFING
    ]  # nothing to say -> skip
    await add_fact(env, "insurance_expiry", date(2026, 1, 8))
    out = await pe.tick()
    brief = [n for n in out if n.kind == NudgeKind.MORNING_BRIEFING]
    assert brief and [b.title for b in brief[0].buttons] == ["Got it", "Stop these"]


async def test_wellbeing_alert_from_task_result_deduped_with_event(env, pe):
    t = await add_task(
        env,
        type=TaskType.WELLBEING_CHECKIN,
        result=TaskResult(success=True, summary="s", alert="dizzy"),
    )
    await env.bus.publish(WellbeingAlertRaised(task_id=t.id, user_id=env.user.id, text="dizzy"))
    await pe.tick()
    alerts = [n for n in env.repos.nudges.items.values() if n.kind == NudgeKind.WELLBEING_ALERT]
    assert len(alerts) == 1 and alerts[0].urgency == Urgency.SAFETY


def test_guardrail_unit_order(env_settings):
    now = ist(2026, 1, 5, 23, 0)
    c = NudgeCandidate(
        user_id="u",
        kind=NudgeKind.PATTERN,
        category=AutonomyCategory.ROUTINES,
        reason="r",
        due_at=now,
        dedupe_key="k",
    )
    assert evaluate(c, now=now, settings=env_settings).action == "schedule"
    safety = c.model_copy(update={"urgency": Urgency.SAFETY})
    assert evaluate(safety, now=now, settings=env_settings, sent_today=9).action == "send"
    assert (
        evaluate(safety, now=now, settings=env_settings, recipient_consent_ok=False).action
        == "suppress"
    )
    day = ist(2026, 1, 5, 12, 0)
    assert evaluate(c, now=day, settings=env_settings, sent_today=3).reason == "daily cap reached"
    urgent = c.model_copy(update={"urgency": Urgency.URGENT})
    assert (
        evaluate(urgent, now=day, settings=env_settings, sent_today=3, ignore_streak=5).action
        == "send"
    )
    old = day - timedelta(days=40)
    assert (
        evaluate(c, now=day, settings=env_settings, ignore_streak=3, last_ignored_at=old).action
        == "send"
    )  # 30-day suppression over


async def test_loop_start_stop_and_factory(env, pe, env_settings):
    env_settings.proactive_tick_s = 0
    await pe.start()
    await asyncio.sleep(0.01)
    await pe.stop()
    from friday.core.container import Container

    assert type(Container(env_settings).proactive).__name__ == "ProactiveEngine"
