"""Recurring bookings (A12), wellbeing check-ins with consent (A13), customer care
with official numbers + pre-call summary + follow-up (C21-26)."""

from datetime import date, timedelta

from friday.core.clock import to_ist
from friday.core.models import (
    AccountIdentifier,
    CallOutcome,
    CareOutcome,
    CareRequestKind,
    Delegation,
    Person,
    PersonConsent,
    Recurrence,
    RecurrenceRule,
    TaskSpec,
    TaskType,
)
from friday.core.models import (
    TaskStatus as S,
)
from friday.tasks.engine import ROLE_CARE_FOLLOWUP, ROLE_INSTANCE, role_of
from friday.tasks.events import WellbeingAlertRaised
from tests.tasks.conftest import AIRTEL, LOOKS, SCAM
from tests.tasks.fakes import offer_then_confirm, outcome, result


def rule(**kw):
    base = dict(
        freq=Recurrence.WEEKLY,
        weekdays=[1, 4],
        time_ist="10:00",
        lead_days=3,
        delegation=Delegation(granted=True, max_price_inr=800, time_window_text="10-11am"),
    )
    return RecurrenceRule(**{**base, **kw})


async def test_recurring_series_spawns_delegated_instances(env):
    env.runner.script(LOOKS, offer_then_confirm("Looks", 400))
    spec = TaskSpec(
        type=TaskType.RECURRING_BOOKING,
        goal="Weekly haircut",
        business_phone=LOOKS,
        business_name="Looks Unisex Salon",
        recurrence=rule(),
    )
    t = await env.task(spec)
    assert t.status == S.SCHEDULED and t.delegation.granted
    run_at = to_ist(t.next_attempt_at)
    assert (run_at.date(), run_at.hour) == (date(2026, 1, 6), 10)  # Fri 9th occurrence - 3 days
    assert "Series set up" in env.texts()[-1]
    env.clock.set(t.next_attempt_at)
    assert await env.engine.tick() == 1
    await env.engine.drain()
    inst = [x for x in env.repos.tasks.items.values() if role_of(x) == ROLE_INSTANCE]
    assert len(inst) == 1 and inst[0].type == TaskType.BOOKING
    assert inst[0].status == S.COMPLETED and env.runner.briefs[0].delegation.granted
    assert to_ist(inst[0].spec.window_start).date() == date(2026, 1, 9)
    parent = await env.get(t.id)
    assert parent.status == S.SCHEDULED
    assert to_ist(parent.recurrence.next_run_at).date() == date(2026, 1, 10)
    await env.engine.cancel(t.id)
    assert (await env.get(t.id)).status == S.CANCELLED
    assert await env.engine.tick() == 0


async def test_recurring_series_ends(env):
    spec = TaskSpec(
        type=TaskType.RECURRING_BOOKING,
        goal="x",
        business_phone=LOOKS,
        recurrence=rule(until=date(2026, 1, 4)),
    )
    t = await env.task(spec)
    assert t.status == S.COMPLETED


async def test_recurring_last_instance_completes_parent(env):
    spec = TaskSpec(
        type=TaskType.RECURRING_BOOKING,
        goal="x",
        business_phone=LOOKS,
        recurrence=rule(until=date(2026, 1, 9)),
    )
    t = await env.task(spec)
    env.clock.set(t.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    assert (await env.get(t.id)).status == S.COMPLETED


async def test_queued_unplanned_recurring_from_pipeline(env):
    """The inbound pipeline may persist a task as SCHEDULED (abuse limiter) w/o submit."""
    from friday.core.models import Task

    spec = TaskSpec(
        type=TaskType.RECURRING_BOOKING, goal="x", business_phone=LOOKS, recurrence=rule()
    )
    task = Task(
        requester_user_id=env.user.id,
        type=spec.type,
        spec=spec,
        recurrence=spec.recurrence,
        status=S.SCHEDULED,
        next_attempt_at=env.clock.now(),
    )
    await env.repos.tasks.add(task)
    await env.engine.tick()
    await env.engine.drain()
    t = await env.get(task.id)
    assert t.status == S.SCHEDULED and t.recurrence.next_run_at is not None


async def add_mom(env, consent=PersonConsent.NOT_ASKED):
    mom = Person(
        owner_user_id=env.user.id,
        name="Sunita",
        relation="mother",
        phone="+919822222222",
        checkin_consent=consent,
    )
    await env.repos.people.upsert(mom)
    return mom


async def test_checkin_requires_member_consent_then_alerts(env):
    alerts = []

    async def on_alert(ev):
        alerts.append(ev)

    env.bus.subscribe(WellbeingAlertRaised, on_alert)
    mom = await add_mom(env)
    spec = TaskSpec(type=TaskType.WELLBEING_CHECKIN, goal="Morning check-in with Mom")
    t = await env.task(spec, beneficiary_person_id=mom.id)
    assert t.status == S.NEEDS_INFO and "hasn't agreed" in env.texts()[-1]
    assert env.runner.briefs == []
    mom.checkin_consent = PersonConsent.OPTED_IN
    await env.repos.people.upsert(mom)
    env.runner.script(
        mom.phone, outcome(CallOutcome.SUCCESS, collected={"alert": "Mom said she feels dizzy"})
    )
    await env.engine.update_spec(t.id, spec)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED and t.target.kind.value == "person"
    brief = env.runner.briefs[0]
    assert brief.max_duration_s <= env.engine.settings.checkin_max_duration_s
    assert alerts and alerts[0].text == "Mom said she feels dizzy"
    assert not env.notifier.to_business()  # no business touch for a person


async def test_checkin_unreachable_alerts_after_attempts(env):
    alerts = []

    async def on_alert(ev):
        alerts.append(ev)

    env.bus.subscribe(WellbeingAlertRaised, on_alert)
    mom = await add_mom(env, PersonConsent.OPTED_IN)
    env.runner.default = outcome(CallOutcome.NO_ANSWER)
    env.engine.policy.max_attempts = 1
    t = await env.task(
        TaskSpec(type=TaskType.WELLBEING_CHECKIN, goal="check-in"), beneficiary_person_id=mom.id
    )
    assert t.status == S.FAILED and alerts and "couldn't reach Sunita" in alerts[0].text


async def test_daily_checkin_series_with_consent(env):
    mom = await add_mom(env, PersonConsent.OPTED_IN)
    spec = TaskSpec(
        type=TaskType.WELLBEING_CHECKIN,
        goal="daily check-in",
        recurrence=RecurrenceRule(freq=Recurrence.WEEKLY, interval_days=1, time_ist="10:30"),
    )
    t = await env.task(spec, beneficiary_person_id=mom.id)
    assert t.status == S.SCHEDULED
    env.clock.set(t.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    inst = [x for x in env.repos.tasks.items.values() if role_of(x) == ROLE_INSTANCE][0]
    assert inst.type == TaskType.WELLBEING_CHECKIN and inst.status == S.COMPLETED


async def test_checkin_without_person(env):
    t = await env.task(TaskSpec(type=TaskType.WELLBEING_CHECKIN, goal="check-in"))
    assert t.status == S.NEEDS_INFO


def care(**kw):
    return TaskSpec(
        type=TaskType.CUSTOMER_CARE,
        goal="Broadband down 3 days, raise complaint",
        company="Airtel",
        care_request=CareRequestKind.COMPLAINT,
        **kw,
    )


async def test_care_official_number_precall_summary_and_followup(env):
    ident = AccountIdentifier(
        user_id=env.user.id, company="Airtel", label="Registered mobile", value="9811111111"
    )
    await env.repos.identifiers.upsert(ident)
    promised = date(2026, 1, 8)

    async def ticket(brief, ask, notify):
        return result(
            brief,
            CallOutcome.SUCCESS,
            care=CareOutcome(company="Airtel", ticket_number="SR12345", promised_date=promised),
        )

    env.runner.script(AIRTEL, ticket)
    t = await env.task(care(approved_identifier_ids=[ident.id]))
    assert t.status == S.AWAITING_APPROVAL and t.target.phone == AIRTEL
    summary = env.texts()[-1]
    assert "official number" in summary and "••••••1111" in summary and "9811111111" not in summary
    await env.engine.approve(t.id, True)
    await env.engine.drain()
    t = await env.get(t.id)
    assert t.status == S.COMPLETED
    fu = next(x for x in env.repos.tasks.items.values() if role_of(x) == ROLE_CARE_FOLLOWUP)
    assert fu.status == S.SCHEDULED and fu.spec.reference == "SR12345"
    assert to_ist(fu.next_attempt_at).date() == promised + timedelta(days=1)
    # follow-up runs without another pre-call approval (covered by the original Go)
    env.clock.set(fu.next_attempt_at)
    await env.engine.tick()
    await env.engine.drain()
    assert env.repos.tasks.items[fu.id].status == S.COMPLETED


async def test_care_user_number_not_official_is_replaced(env):
    t = await env.task(care(business_phone="+919812345678"))
    assert t.target.phone == AIRTEL and "official number instead" in env.texts()[0]


async def test_care_unknown_company_and_scam_number(env):
    t = await env.task(
        TaskSpec(type=TaskType.CUSTOMER_CARE, goal="refund", company="Zorbo Telecom")
    )
    assert t.status == S.FAILED and "can't verify" in t.result.summary
    t2 = await env.task(
        TaskSpec(type=TaskType.CUSTOMER_CARE, goal="refund", company="Zorbo", business_phone=SCAM)
    )
    assert t2.status == S.FAILED and env.runner.briefs == []
