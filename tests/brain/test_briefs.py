"""AI-4 references, AI-5 templates + build_call_brief."""

from __future__ import annotations

import pytest

from friday.brain.briefs import BriefError
from friday.brain.heuristics.references import resolve
from friday.brain.templates import load_templates, template_for
from friday.core.models import (
    Beneficiary,
    Business,
    CallMode,
    ContactTarget,
    ConversationTurn,
    Delegation,
    Direction,
    InteractionKind,
    Quote,
    RecurrenceRule,
    Recurrence,
    TargetKind,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
    VendorInteraction,
)

from .conftest import make_ctx

# ------------------------------------------------------------------ templates


@pytest.mark.parametrize("task_type", list(TaskType))
def test_every_task_type_has_a_template(task_type):
    tpl = template_for(task_type)
    assert tpl.task_type == task_type and tpl.goal_template
    assert tpl.default_questions and tpl.success_criteria


def test_templates_are_data_and_valid():
    templates = load_templates()
    assert set(templates) == set(TaskType)
    assert template_for(TaskType.STOCK_HUNT).fan_out.strategy.value == "first_match"
    assert template_for(TaskType.WELLBEING_CHECKIN).target_kind == TargetKind.PERSON
    assert not template_for(TaskType.ENQUIRY).needs_approval_to_commit
    assert template_for(TaskType.BOOKING).needs_approval_to_commit


async def test_brain_template_for(brain):
    assert brain.template_for(TaskType.QUOTE).may_negotiate


# ------------------------------------------------------------------ references


@pytest.mark.parametrize(("text", "person", "place"), [
    ("book a doctor for papa near their home", "p_dad", "pl_parents"),
    ("mummy ke ghar ke paas koi physio", "p_mom", "pl_parents"),
    ("find a cafe near my office", None, "pl_office"),
    ("something near home", None, "pl_home"),
    ("dinner at Priya's place", "p_priya", "pl_priya"),
    ("Suresh ji ke liye dentist", "p_dad", None),
    ("book a plumber", None, None),
])
def test_resolve_people_and_places(family_ctx, text, person, place):
    r = resolve(family_ctx, text)
    assert r.person_id == person and r.place_id == place and not r.ambiguous


def test_pronoun_resolves_from_recent_turns(family_ctx):
    ctx = family_ctx.model_copy(update={"recent": [
        ConversationTurn(direction=Direction.INBOUND, text="Priya is coming over on Sunday")]})
    r = resolve(ctx, "find a florist near her place")
    assert r.person_id == "p_priya" and r.place_id == "pl_priya"


def test_ambiguous_asks_once_with_buttons(family_ctx):
    from friday.core.models import Place

    extra = Place(id="pl_dad2", owner_user_id="u1", label="Delhi flat", person_id="p_dad")
    ctx = family_ctx.model_copy(update={"places": [*family_ctx.places, extra]})
    r = resolve(ctx, "doctor near papa's home")
    assert r.ambiguous and r.clarification and 1 < len(r.buttons) <= 3
    assert all(b.id.startswith("r:place:") and len(b.title) <= 20 for b in r.buttons)


def test_new_alias_learned(family_ctx):
    r = resolve(family_ctx, "papa ke liye dentist")
    assert r.person_id == "p_dad"
    assert [a.alias for a in r.new_aliases] == ["papa"]


def test_unknown_reference(family_ctx):
    r = resolve(family_ctx, "book for my cousin Rohit near MG Road")
    assert r.person_id is None and r.place_id is None
    assert r.location_text == "mg road"


async def test_brain_resolve_references(brain, family_ctx):
    r = await brain.resolve_references(family_ctx, "near my office")
    assert r.place_id == "pl_office"


async def test_disambiguation_tap_updates_waiting_task(brain, family_ctx):
    from friday.core.models import MessageKind

    from .conftest import msg

    waiting = Task(id="tw", requester_user_id="u1", type=TaskType.HEALTHCARE,
                   status=TaskStatus.NEEDS_INFO,
                   spec=TaskSpec(type=TaskType.HEALTHCARE, goal="doctor"))
    ctx = family_ctx.model_copy(update={"open_tasks": [waiting], "recent": [
        ConversationTurn(direction=Direction.INBOUND, text="book a doctor for papa tomorrow "
                                                           "morning near his home")]})
    out = await brain.interpret(ctx, msg("Delhi flat", kind=MessageKind.BUTTON_REPLY,
                                         button_id="r:place:pl_parents"))
    assert out.intent.value == "task_update" and out.task_id == "tw"
    assert out.resolution.place_id == "pl_parents"


# ------------------------------------------------------------------ briefs


def _task(**kw) -> Task:
    spec = TaskSpec(**{"type": TaskType.BOOKING, "goal": "Book a haircut for Suresh",
                       "business_name": "Looks", "business_phone": "+918040000001",
                       "category": "salon", **kw.pop("spec", {})})
    return Task(**{"id": "t1", "requester_user_id": "u1", "type": spec.type, "spec": spec, **kw})


async def test_brief_minimum_disclosure(brain, family_ctx):
    task = _task(beneficiary=Beneficiary(person_id="p_dad"), place_id="pl_parents")
    brief = await brain.build_call_brief(family_ctx, task)
    dumped = brief.model_dump_json()
    assert "diabetic" not in dumped  # Person.notes never in a brief
    assert brief.shareable_details == {"booking name": "Suresh Verma"}
    assert "Kothrud" not in dumped  # salon visit: no home address
    assert brief.beneficiary_name == "Suresh Verma" and brief.beneficiary_relation == "father"
    assert brief.on_behalf_of == "Ankit Sharma" and brief.user_phone is None
    assert brief.approval.mode.value == "callback" and not brief.can_commit([])


async def test_home_visit_shares_address(brain, family_ctx):
    task = _task(place_id="pl_home", spec={"category": "plumber", "goal": "Fix a tap"})
    brief = brain.build_call_brief(family_ctx, task)  # sync use also works
    assert brief.shareable_details["visit address"] == "12, 4th Cross, Indiranagar"


async def test_brief_negotiation_budget_vendor_history_competing_quotes(brain):
    biz = Business(id="b1", name="CoolCare", phone="+918040000003", language_hint=None)
    sibling = Task(id="t2", requester_user_id="u1", type=TaskType.QUOTE, parent_task_id="p",
                   spec=TaskSpec(type=TaskType.QUOTE, goal="AC"),
                   result=TaskResult(success=True, summary="", quotes=[
                       Quote(business_name="Frosty", amount_inr=450, price_text="₹450")]))
    ctx = make_ctx(known_businesses=[biz], open_tasks=[sibling], vendor_history=[
        VendorInteraction(user_id="u1", business_id="b1", kind=InteractionKind.PAID,
                          amount_inr=400)])
    from friday.core.models import Budget

    task = _task(parent_task_id="p", type=TaskType.QUOTE,
                 target=ContactTarget(kind=TargetKind.BUSINESS, name="CoolCare",
                                      phone="+918040000003", business_id="b1"),
                 spec={"type": TaskType.QUOTE, "goal": "AC service quote",
                       "budget": Budget(max_inr=600, target_inr=500)})
    brief = await brain.build_call_brief(ctx, task)
    assert brief.negotiation.enabled and brief.negotiation.walk_away_above_inr == 600
    assert brief.competing_quotes[0].amount_inr == 450
    assert brief.vendor_history and "₹400" in brief.vendor_history[0]
    assert brief.business.id == "b1"


async def test_brief_no_negotiation_for_healthcare(brain, ctx):
    brief = await brain.build_call_brief(ctx, _task(type=TaskType.HEALTHCARE,
                                                    spec={"type": TaskType.HEALTHCARE}))
    assert not brief.negotiation.enabled


async def test_brief_delegation_and_confirmation_callback(brain, ctx):
    d = Delegation(granted=True, max_price_inr=800, user_words="you decide")
    brief = await brain.build_call_brief(ctx, _task(spec={"delegation": d}))
    assert brief.delegation.granted and brief.can_commit([])
    cb = await brain.build_call_brief(ctx, _task(approved_terms="Sat 12:30, ₹600"))
    assert cb.approved_terms and "12:30" in cb.goal and cb.can_commit([])


async def test_recurring_rule_delegation_used(brain, ctx):
    rule = RecurrenceRule(freq=Recurrence.WEEKLY, weekdays=[1],
                          delegation=Delegation(granted=True, max_price_inr=700))
    brief = await brain.build_call_brief(ctx, _task(recurrence=rule))
    assert brief.delegation.max_price_inr == 700


async def test_care_brief_identifiers_and_bridge(brain):
    from friday.core.models import AccountIdentifier, CareRequestKind

    ident = AccountIdentifier(id="i1", user_id="u1", label="Registered mobile",
                              value="9800000001")
    ctx = make_ctx()
    object.__setattr__(ctx, "identifiers", [ident])  # proposed core field (CORE_CHANGES)
    task = _task(type=TaskType.CUSTOMER_CARE, spec={
        "type": TaskType.CUSTOMER_CARE, "company": "Airtel", "goal": "Broadband refund",
        "care_request": CareRequestKind.REFUND, "approved_identifier_ids": ["i1"],
        "business_phone": "+911800000121"})
    brief = await brain.build_call_brief(ctx, task)
    assert brief.approved_identifiers == [ident] and brief.user_phone == "+919800000001"
    assert brief.max_duration_s >= 1200 and brief.company == "Airtel"


async def test_wellbeing_brief_targets_person(brain, family_ctx):
    task = Task(id="tw", requester_user_id="u1", type=TaskType.WELLBEING_CHECKIN,
                beneficiary=Beneficiary(person_id="p_dad"),
                spec=TaskSpec(type=TaskType.WELLBEING_CHECKIN, goal="Check in on dad"))
    brief = await brain.build_call_brief(family_ctx, task)
    assert brief.target.kind == TargetKind.PERSON and brief.target.phone == "+919829000001"
    assert brief.opening_language.value == "hi" and "diabetic" not in brief.model_dump_json()


async def test_warm_transfer_brief_has_user_phone(brain, ctx):
    brief = await brain.build_call_brief(ctx, _task(spec={"call_mode": CallMode.WARM_TRANSFER}))
    assert brief.user_phone == ctx.user.phone


async def test_brief_without_target_raises(brain, ctx):
    task = Task(id="tx", requester_user_id="u1", type=TaskType.BOOKING,
                spec=TaskSpec(type=TaskType.BOOKING, goal="x"))
    with pytest.raises(BriefError):
        await brain.build_call_brief(ctx, task)
