"""Task + template + memory -> ``CallBrief`` (deterministic, no LLM: this is where
minimum disclosure is enforced, so it must be predictable).

Rules
* ``shareable_details`` holds only what the business needs: booking name always;
  a visit/delivery address only for home-visit / delivery tasks with a place;
  guest names for stays. ``Person.notes`` NEVER go in (they are private).
* Delegation: task.delegation, else spec.delegation, else the recurring rule's.
* Competing quotes come only from real sibling calls (open tasks in ctx).
* Inbound call-backs (BRIEF E-30..37): ``inbound=InboundContext`` returns an
  ``InboundCallBrief``; ``build_inbound_brief`` handles unmatched / ambiguous callers.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from friday.core.clock import format_ist
from friday.core.config import Settings
from friday.core.models import (
    ApprovalPolicy,
    Business,
    CallDirection,
    CallMode,
    ContactTarget,
    ConversationContext,
    Delegation,
    InteractionKind,
    Language,
    NegotiationPolicy,
    Person,
    Place,
    Quote,
    TargetKind,
    Task,
    TaskType,
)

from .inbound import (
    AwaitableCallBrief,
    InboundCallBrief,
    InboundContext,
    RelatedTask,
    task_label,
)
from .templates import template_for
from .textutil import format_inr

HOME_VISIT_CATEGORIES = {
    "ac repair",
    "plumber",
    "electrician",
    "carpenter",
    "nursing",
    "diagnostic lab",
    "physiotherapist",
    "packers and movers",
    "interior designer",
    "water supplier",
    "kirana",
    "tiffin service",
    "pharmacy",
}
HOME_VISIT_TYPES = {TaskType.ORDER, TaskType.SERVICE_COORDINATION}
CARE_MAX_DURATION_S = 1200


class BriefError(ValueError):
    """The task can't be turned into a call yet (no target / phone)."""


def home_visit_task(task: Task, spec) -> bool:
    return (
        task.type in HOME_VISIT_TYPES
        or (spec.category in HOME_VISIT_CATEGORIES)
        or "home visit" in spec.constraints
        or "home collection" in (spec.goal or "").lower()
    )


def _person(ctx: ConversationContext, person_id: str | None) -> Person | None:
    return next((p for p in ctx.people if p.id == person_id), None) if person_id else None


def _place(ctx: ConversationContext, place_id: str | None) -> Place | None:
    return next((p for p in ctx.places if p.id == place_id), None) if place_id else None


def _business(ctx: ConversationContext, task: Task, target: ContactTarget) -> Business | None:
    bid = target.business_id or task.spec.business_id
    for b in ctx.known_businesses:
        if (bid and b.id == bid) or b.phone == target.phone:
            return b
    return None


def resolve_target(ctx: ConversationContext, task: Task) -> ContactTarget:
    if task.target is not None:
        return task.target
    spec = task.spec
    if task.type == TaskType.WELLBEING_CHECKIN or (
        task.beneficiary.person_id
        and not spec.business_phone
        and not spec.business_name
        and task.type == TaskType.WELLBEING_CHECKIN
    ):
        p = _person(ctx, task.beneficiary.person_id)
        if p and p.phone:
            return ContactTarget(
                kind=TargetKind.PERSON,
                name=p.name,
                phone=p.phone,
                person_id=p.id,
                language_hint=p.language,
            )
    if task.candidate and task.candidate.phone:
        return ContactTarget(
            kind=TargetKind.BUSINESS, name=task.candidate.name, phone=task.candidate.phone
        )
    if spec.business_phone:
        return ContactTarget(
            kind=TargetKind.BUSINESS,
            name=spec.business_name or spec.company or "the business",
            phone=spec.business_phone,
            business_id=spec.business_id,
        )
    raise BriefError(f"task {task.id} has no call target / phone yet")


def _vendor_history(ctx: ConversationContext, business_id: str | None) -> list[str]:
    if not business_id:
        return []
    out = []
    for v in sorted(
        (v for v in ctx.vendor_history if v.business_id == business_id),
        key=lambda v: v.at,
        reverse=True,
    )[:6]:
        when = format_ist(v.at, "%b %Y")
        if v.kind in (InteractionKind.QUOTED, InteractionKind.PAID) and v.amount_inr:
            verb = "quoted" if v.kind == InteractionKind.QUOTED else "charged"
            out.append(f"{verb} {format_inr(v.amount_inr)} ({when})")
        elif v.kind == InteractionKind.NO_SHOW:
            out.append(f"no-show ({when})")
        elif v.kind == InteractionKind.RATED and v.rating:
            out.append(f"user rated {v.rating}/5 ({when})")
        elif v.kind == InteractionKind.BOOKED:
            out.append(f"booked before ({when})")
    return out


def _competing_quotes(ctx: ConversationContext, task: Task, target: ContactTarget) -> list[Quote]:
    quotes: list[Quote] = []
    if not task.parent_task_id:
        return quotes
    for other in ctx.open_tasks:
        related = other.id == task.parent_task_id or other.parent_task_id == task.parent_task_id
        if not related or other.id == task.id or not other.result:
            continue
        for q in other.result.quotes:
            if q.amount_inr and q.business_name != target.name and q not in quotes:
                quotes.append(q)
    return quotes


def _api_offer(ctx: ConversationContext, task: Task, target: ContactTarget):
    pools = [task.result] + [t.result for t in ctx.open_tasks if t.id == task.parent_task_id]
    for res in pools:
        if not res:
            continue
        for offer in res.hotel_offers:
            if offer.property.phone == target.phone or offer.property.name == target.name:
                return offer
    return None


def _delegation(task: Task) -> Delegation:
    if task.delegation.granted:
        return task.delegation
    if task.spec.delegation.granted:
        return task.spec.delegation
    rec = task.recurrence or task.spec.recurrence
    if rec and rec.delegation.granted:
        return rec.delegation
    return Delegation()


def _goal(task: Task, target: ContactTarget, beneficiary: str, settings_goal: str) -> str:
    spec = task.spec
    tpl = template_for(task.type)
    if task.approved_terms:
        return f"Call back {target.name} and confirm what the user approved: {task.approved_terms}"
    values = {
        "what": spec.item or spec.category or spec.discovery_query or "the request",
        "beneficiary": beneficiary,
        "when": spec.when_text or ", ".join(spec.preferred_times),
        "target": target.name,
        "reference": spec.reference or "-",
        "company": spec.company or target.name,
        "care_request": (
            spec.care_request.value.replace("_", " ").capitalize()
            if spec.care_request
            else "Request"
        ),
    }
    try:
        templ = tpl.goal_template.format(**values)
    except (KeyError, IndexError):
        templ = ""
    return spec.goal or settings_goal or templ


def build_call_brief(
    ctx: ConversationContext,
    task: Task,
    settings: Settings | None = None,
    *,
    inbound: InboundContext | None = None,
):
    settings = settings or Settings(_env_file=None)
    spec = task.spec
    target = resolve_target(ctx, task)
    template = template_for(task.type)
    business = _business(ctx, task, target)
    requester = ctx.profile.name or "my user"
    person = _person(ctx, task.beneficiary.person_id)
    place = _place(ctx, task.place_id)
    beneficiary_name = person.name if person else None
    relation = person.relation if person else None
    booking_name = beneficiary_name or requester

    # ---- minimum disclosure
    shareable: dict[str, str] = {}
    if target.kind == TargetKind.BUSINESS:
        label = {TaskType.HEALTHCARE: "patient name", TaskType.HOTEL_BOOKING: "guest name"}.get(
            task.type, "booking name"
        )
        shareable[label] = booking_name
        if spec.party_size:
            shareable["party size"] = str(spec.party_size)
        if place and home_visit_task(task, spec):
            addr = place.formatted_address or place.address_text
            if addr:
                key = "delivery address" if task.type == TaskType.ORDER else "visit address"
                shareable[key] = addr
        if spec.reference:
            shareable["reference"] = spec.reference
    # location context: the full address only for home visits (it is then also a
    # shareable detail); otherwise just the area/city so the agent can say "near X"
    location = None
    if place:
        if home_visit_task(task, spec):
            addr = place.formatted_address or place.address_text
            location = f"{place.label}" + (f", {addr}" if addr else "")
        else:
            location = place.city or spec.location_text or None
    elif spec.location_text:
        location = spec.location_text

    # ---- languages
    opening = spec.call_language or Language.HINGLISH
    if target.kind == TargetKind.PERSON and target.language_hint:
        opening = target.language_hint
    elif business and business.language_hint:
        opening = business.language_hint

    # ---- negotiation & approval
    negotiation = spec.negotiation.model_copy()
    if not template.may_negotiate:
        negotiation = NegotiationPolicy(
            enabled=False,
            may_ask_discount=False,
            may_cite_competing_quotes=False,
            may_ask_package_deal=False,
            max_rounds=0,
        )
    elif negotiation.walk_away_above_inr is None and spec.budget and spec.budget.max_inr:
        negotiation.walk_away_above_inr = spec.budget.max_inr
    approval = ApprovalPolicy(
        hold_timeout_s=settings.mid_call_question_timeout_s, rules=list(template.success_criteria)
    )

    identifiers = [
        i for i in ctx.identifiers if i.id in spec.approved_identifier_ids
    ]
    user_phone = None
    if (
        spec.call_mode in (CallMode.WARM_TRANSFER, CallMode.TRANSLATOR)
        or task.type == TaskType.CUSTOMER_CARE
    ):
        user_phone = ctx.user.phone

    max_duration = settings.call_max_duration_s
    if task.type == TaskType.WELLBEING_CHECKIN:
        max_duration = settings.checkin_max_duration_s
    if task.type == TaskType.CUSTOMER_CARE:
        max_duration = CARE_MAX_DURATION_S

    constraints = list(spec.constraints)
    if task.type != TaskType.WELLBEING_CHECKIN:
        constraints.append("no advance payment or deposit")
    user_context: list[str] = []
    if business:
        user_context += [
            f"{f.key.replace('_', ' ')}: {f.value}"
            for f in ctx.facts
            if f.business_id == business.id
        ]
    if spec.notes:
        user_context.append(spec.notes)

    kwargs = dict(
        task_id=task.id,
        requester_user_id=task.requester_user_id,
        task_type=task.type,
        goal=_goal(task, target, booking_name, ""),
        target=target,
        business=business,
        mode=spec.call_mode,
        template=template,
        on_behalf_of=requester,
        beneficiary_name=beneficiary_name,
        beneficiary_relation=relation,
        shareable_details=shareable,
        location_context=location,
        opening_language=opening,
        user_language=ctx.profile.language,
        constraints=constraints,
        preferred_times=list(spec.preferred_times),
        window_start=spec.window_start,
        window_end=spec.window_end,
        party_size=spec.party_size,
        questions=list(spec.questions or template.default_questions)[:5],
        budget=spec.budget,
        negotiation=negotiation,
        competing_quotes=_competing_quotes(ctx, task, target),
        vendor_history=_vendor_history(ctx, business.id if business else target.business_id),
        user_context=user_context,
        allowed_disclosures=sorted(shareable.keys()),
        forbidden_disclosures=[
            "user's phone number",
            "home address (unless listed above)",
            "payment details",
            "OTP/PIN/CVV/passwords",
            "Aadhaar/PAN",
            "private notes about family members",
        ],
        approval=approval,
        approved_terms=task.approved_terms,
        delegation=_delegation(task),
        user_phone=user_phone,
        company=spec.company,
        care_request=spec.care_request,
        reference=spec.reference,
        approved_identifiers=identifiers,
        ivr_notes=list(business.ivr_notes) if business else [],
        max_hold_s=settings.ivr_max_hold_s,
        stay=spec.stay,
        api_offer=_api_offer(ctx, task, target) if task.type == TaskType.HOTEL_BOOKING else None,
        attempt=task.attempts + 1,
        max_duration_s=max_duration,
    )
    if (
        inbound is None
        and target.kind == TargetKind.BUSINESS
        and not task.approved_terms  # confirmation call-backs stay with the LLM policy
        and (settings is None or getattr(settings, "playbooks_enabled", True))
    ):
        from friday.playbooks.select import playbook_fields

        kwargs.update(
            playbook_fields(
                task_type=task.type,
                category=(business.category if business else None) or spec.category,
                goal=kwargs["goal"],
                item=spec.item,
                when_text=spec.when_text,
                preferred_times=list(spec.preferred_times),
                window_start=spec.window_start,
                window_end=spec.window_end,
                now=ctx.now,
                requester_name=requester,
                beneficiary_name=beneficiary_name,
                constraints=constraints,
                budget_max_inr=spec.budget.max_inr if spec.budget else None,
                enabled=getattr(settings, "playbooks_enabled", True),
                business_name=target.name,
                delegation_granted=bool(_delegation(task).granted),
                name_speller=_name_speller(settings),
            )
        )
    if inbound is None:
        return AwaitableCallBrief(**kwargs)
    if not inbound.caller_matches_business:
        return build_inbound_brief(
            ctx,
            caller_phone=inbound.caller_phone,
            kind=inbound.kind,
            friday_number=inbound.friday_number,
            caller_matches_business=False,
            settings=settings,
        )
    if inbound.matched_task_id is None and len(inbound.related) <= 1:
        inbound = inbound.model_copy(update={"matched_task_id": task.id})
    direction = CallDirection.OUTBOUND if inbound.kind == "missed_call" else CallDirection.INBOUND
    return InboundCallBrief(direction=direction, inbound=inbound, **kwargs)


def _name_speller(settings: Settings | None) -> object | None:
    """How the voice reads names, worked out once when the call brief is built (never mid-call)."""
    from friday.voice.names import speller_from_settings

    return speller_from_settings(settings) if settings is not None else None


def related_from_task(
    task: Task,
    ctx: ConversationContext,
    *,
    discussed: str | None = None,
    resolution: str = "open",
    booking_details: str | None = None,
    called_at: datetime | None = None,
) -> RelatedTask:
    """Helper for the backend: build a ``RelatedTask`` from a task + its last result."""
    person = _person(ctx, task.beneficiary.person_id)
    last_quote = task.result.quotes[-1] if task.result and task.result.quotes else None
    return RelatedTask(
        task_id=task.id,
        task_type=task.type,
        goal=task.spec.goal,
        label=task_label(task.type, task.spec.goal, task.spec.item),
        beneficiary_name=person.name if person else ctx.profile.name,
        status=task.status,
        last_outcome=task.last_outcome,
        called_at=called_at,
        discussed=discussed or (task.result.summary if task.result else None),
        last_quote=last_quote,
        approved_terms=task.approved_terms,
        resolution=resolution,  # type: ignore[arg-type]
        booking_details=booking_details,
    )


def build_inbound_brief(
    ctx: ConversationContext,
    *,
    caller_phone: str,
    related: list[RelatedTask] | None = None,
    tasks: list[Task] | None = None,
    kind: str = "answered",
    friday_number: str | None = None,
    caller_matches_business: bool = True,
    business_name: str | None = None,
    settings: Settings | None = None,
) -> InboundCallBrief:
    """Brief for a business calling back / a missed-call call-back (E-31..33).

    * one related task  -> that task's brief + inbound context (resume / close loop)
    * several           -> asks the caller which one, then continues that one
    * none / unknown    -> message-taking brief that reveals no user details
    """
    related = list(related or [])
    tasks = list(tasks or [])
    if not caller_matches_business:
        # E-34: caller ID doesn't match the business record -> treat as unknown; the
        # brief must carry nothing about the user, the beneficiary or the task.
        related, tasks = [], []
    if not related and tasks:
        related = [related_from_task(t, ctx) for t in tasks]
    ib = InboundContext(
        kind=kind if related else "unknown",  # type: ignore[arg-type]
        caller_phone=caller_phone,
        friday_number=friday_number,
        caller_matches_business=caller_matches_business and bool(related),
        business_name=business_name,
        related=related,
        matched_task_id=related[0].task_id if len(related) == 1 else None,
    )
    primary = None
    if len(related) >= 1:
        primary = next((t for t in tasks if t.id == related[0].task_id), None)
    if primary is not None:
        target = primary.target or ContactTarget(
            kind=TargetKind.BUSINESS,
            name=business_name or primary.spec.business_name or "the business",
            phone=caller_phone,
        )
        primary = primary.model_copy(update={"target": target})
        return build_call_brief(ctx, primary, settings, inbound=ib)
    task_id = (
        related[0].task_id
        if related
        else "inbound-" + hashlib.sha1(caller_phone.encode()).hexdigest()[:24]
    )
    goal = (
        "Business called back: find out which request it is about and continue it"
        if related
        else "Unknown caller: take a message (name, purpose, call-back number); "
        "share no user details"
    )
    named = caller_matches_business and bool(related)
    return InboundCallBrief(
        direction=CallDirection.OUTBOUND if kind == "missed_call" else CallDirection.INBOUND,
        inbound=ib,
        task_id=task_id,
        requester_user_id=ctx.user.id,
        task_type=related[0].task_type if related else TaskType.ENQUIRY,
        goal=goal,
        target=ContactTarget(
            kind=TargetKind.BUSINESS, name=business_name or "Caller", phone=caller_phone
        ),
        on_behalf_of=(ctx.profile.name or "my user") if named else "a Friday user",
        opening_language=Language.HINGLISH,
        user_language=ctx.profile.language,
        shareable_details={},
        max_duration_s=(settings or Settings(_env_file=None)).call_max_duration_s,
    )
