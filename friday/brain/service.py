"""``Brain`` implementation (``build_brain``). Pure: no DB, no sending, no sleeping.

Every LLM-backed method follows one pattern (``_ask``): static system prompt per
purpose + JSON ``<input>`` payload -> structured output (wire model) -> code
converts to core models and enforces the hard rules. If the LLM fails (timeout,
refusal, invalid output) the deterministic handler for that purpose answers
instead, so a provider hiccup never leaves a caller in silence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from friday.core.config import Settings
from friday.core.interfaces import LLMClient, LLMMessage, ProviderError
from friday.core.logging import get_logger
from friday.core.models import (
    CORE_LANGUAGES,
    AccountIdentifier,
    AutonomyLevel,
    AutonomySetting,
    Budget,
    BusinessCandidate,
    CallAction,
    CallBrief,
    CallResult,
    ConversationContext,
    Delegation,
    Direction,
    Fact,
    FanOutPolicy,
    GeoPoint,
    InboundMessage,
    Intent,
    InteractionKind,
    Interpretation,
    Language,
    MessageKind,
    NudgeCandidate,
    NudgeDecision,
    NudgeKind,
    OnboardingStep,
    OnboardingTurn,
    Person,
    Place,
    PlaceSource,
    Quote,
    QuoteComparison,
    RecurrenceRule,
    ReferenceResolution,
    ReplyButton,
    ShortlistItem,
    StayRequest,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
    TemplateRef,
    Transcript,
    UserAnswer,
    VendorInteraction,
    normalize_phone,
    nudge_button_id,
)

from . import briefs, guards, handlers, reports
from .copy import first_name
from .heuristics.interpret import draft_missing
from .heuristics.lexicon import DELEGATION_PHRASES, SECRET_WORDS
from .heuristics.onboarding import onboarding_turn as _onboarding
from .heuristics.references import canonical_relation, resolve
from .inbound import InboundCallBrief, InboundContext, RelatedTask
from .prompts import render_input, system_prompt
from .schemas import (
    CallActionOut,
    CompareOut,
    InterpretOut,
    NudgeOut,
    ResolutionOut,
    SummaryOut,
    TaskDraft,
    TranslateOut,
    strict_schema,
)
from .templates import template_for
from .textutil import has_any, norm, truncate_title

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

_PROFILE_FIELDS = {"name", "city", "language", "tone", "morning_briefing", "briefing_hour_ist"}


# =============================================================================== payloads


def ctx_payload(ctx: ConversationContext, *, recent: int = 12) -> dict[str, Any]:
    """Trimmed context for prompts: private Person.notes are never sent."""
    slim = ctx.model_copy(update={
        "recent": ctx.recent[-recent:],
        "facts": ctx.facts[-40:],
        "vendor_history": ctx.vendor_history[-20:],
        "people": [p.model_copy(update={"notes": None}) for p in ctx.people],
        "open_tasks": [t.model_copy(update={"result": _slim_result(t.result)})
                       for t in ctx.open_tasks[:10]],
    })
    return slim.model_dump(mode="json", exclude_none=True)


def _slim_result(result: TaskResult | None) -> TaskResult | None:
    if result is None:
        return None
    return result.model_copy(update={"interactions": [], "facts": [], "extracted": [],
                                     "hotel_offers": result.hotel_offers[:5]})


def brief_payload(brief: CallBrief) -> dict[str, Any]:
    data = brief.model_dump(mode="json", exclude_none=True, exclude={"user_phone"})
    if brief.user_phone:
        data["user_phone"] = "+00000000000"  # presence only: the number is never in a prompt
    data["can_bridge_user"] = bool(brief.user_phone)
    return data


# =============================================================================== conversion


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        from friday.core.clock import ensure_utc

        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _phone(value: str | None, cc: str = "+91") -> str | None:
    if not value:
        return None
    try:
        p = normalize_phone(value, cc)
    except ValueError:
        return None
    digits = re.sub(r"\D", "", p)
    return p if 10 <= len(digits) <= 13 else None


def _explicit_delegation(words: str | None, ctx: ConversationContext, msg_text: str) -> bool:
    """Delegation is NEVER inferred: the user's own text must contain an explicit
    hand-over phrase, and ``user_words`` must be something the user actually said."""
    texts = [msg_text] + [t.text for t in ctx.recent if t.direction == Direction.INBOUND]
    if words and not any(norm(words) in norm(t) or norm(t) in norm(words) for t in texts if t):
        return False
    source = words or msg_text
    return has_any(norm(source), DELEGATION_PHRASES)


def draft_to_spec(d: TaskDraft, ctx: ConversationContext, msg_text: str,
                  settings: Settings) -> TaskSpec:
    cc = settings.default_country_code
    phone = _phone(d.business_phone, cc)
    business_id = None
    name_low = norm(d.business_name)
    for b in ctx.known_businesses:
        if (phone and b.phone == phone) or (name_low and name_low.split()[0] in norm(b.name)):
            business_id = b.id
            phone = phone or b.phone  # US-3.2 #2: number from memory
            d.business_name = d.business_name or b.name
            break
    budget = None
    if d.budget_max_inr or d.budget_target_inr:
        budget = Budget(max_inr=d.budget_max_inr, target_inr=d.budget_target_inr)
    delegation = Delegation()
    if d.delegation and d.delegation.granted and _explicit_delegation(d.delegation.user_words,
                                                                      ctx, msg_text):
        delegation = Delegation(
            granted=True, scope=d.delegation.scope or ["slot"],
            window_start=_parse_dt(d.delegation.window_start),
            window_end=_parse_dt(d.delegation.window_end),
            time_window_text=d.delegation.time_window_text,
            max_price_inr=d.delegation.max_price_inr,
            conditions=d.delegation.conditions,
            user_words=d.delegation.user_words or msg_text,
        )
    recurrence = None
    if d.recurrence:
        r = d.recurrence
        recurrence = RecurrenceRule(freq=r.freq, interval=max(1, r.interval),
                                    interval_days=r.interval_days, weekdays=r.weekdays,
                                    day_of_month=r.day_of_month, time_ist=r.time_ist or "10:00",
                                    delegation=delegation)
    stay = None
    if d.stay and d.stay.check_in and d.stay.check_out:
        ci, co = _parse_date(d.stay.check_in), _parse_date(d.stay.check_out)
        if ci and co and co > ci:
            stay = StayRequest(destination=d.stay.destination, check_in=ci, check_out=co,
                               adults=d.stay.adults, children=d.stay.children,
                               rooms=d.stay.rooms,
                               max_rate_per_night_inr=d.stay.max_rate_per_night_inr,
                               property_types=d.stay.property_types,
                               preferences=d.stay.preferences)
    missing = list(dict.fromkeys([*d.missing, *draft_missing(d)]))
    if stay is None and d.type == TaskType.HOTEL_BOOKING and "stay" not in missing:
        missing.append("stay")
    tpl = template_for(d.type)
    return TaskSpec(
        type=d.type,
        goal=d.goal,
        business_name=d.business_name,
        business_phone=phone,
        business_id=business_id,
        category=d.category,
        reference=d.reference,
        company=d.company,
        care_request=d.care_request,
        item=d.item,
        fan_out=FanOutPolicy(strategy=d.fan_out, concurrency=tpl.fan_out.concurrency,
                             max_targets=tpl.fan_out.max_targets) if d.fan_out else None,
        call_mode=d.call_mode,
        recurrence=recurrence,
        delegation=delegation,
        stay=stay,
        discovery_query=d.discovery_query,
        location_text=d.location_text,
        shortlist_size=settings.discovery_shortlist_size,
        budget=budget,
        preferred_times=d.preferred_times,
        when_text=d.when_text,
        window_start=_parse_dt(d.window_start),
        window_end=_parse_dt(d.window_end),
        party_size=d.party_size,
        questions=d.questions[:5],
        constraints=d.constraints,
        on_behalf_of=ctx.profile.name,
        call_language=Language.HINGLISH,
        notes=d.notes,
        missing=missing,
    )


def resolution_from(out: ResolutionOut, ctx: ConversationContext) -> ReferenceResolution:
    people = {p.id for p in ctx.people}
    places = {p.id for p in ctx.places}
    buttons = [ReplyButton(id=b.id[:256], title=truncate_title(b.title)) for b in out.buttons[:3]]
    aliases = []
    for a in out.new_aliases:
        if (a.target == "person" and a.target_id in people) or (
                a.target == "place" and a.target_id in places):
            from friday.core.models import AliasLearning

            aliases.append(AliasLearning(target=a.target, target_id=a.target_id, alias=a.alias))
    return ReferenceResolution(
        person_id=out.person_id if out.person_id in people else None,
        place_id=out.place_id if out.place_id in places else None,
        location_text=out.location_text,
        ambiguous=out.ambiguous and bool(out.clarification),
        clarification=out.clarification if out.ambiguous else None,
        clarification_buttons=buttons if out.ambiguous else [],
        new_aliases=aliases,
    )


# =============================================================================== the brain


class FridayBrain:
    """``Brain`` (CallPolicy + Translator + everything else)."""

    def __init__(self, llm: LLMClient, settings: Settings | None = None, *,
                 speakable: frozenset[Language] | Callable[[], frozenset[Language] | None]
                 | None = None) -> None:
        self.llm = llm
        self.settings = settings or Settings(_env_file=None)
        self._speakable = speakable

    # ------------------------------------------------------------------ plumbing
    @property
    def speakable(self) -> frozenset[Language] | None:
        sp = self._speakable
        if callable(sp):
            try:
                sp = sp()
            except Exception:  # noqa: BLE001 - TTS not available: assume core languages
                sp = None
            self._speakable = sp or CORE_LANGUAGES
        return self._speakable  # type: ignore[return-value]

    async def _ask(self, purpose: str, payload: dict[str, Any], out_model: type[BaseModel], *,
                   system: str, fallback: Callable[[], BaseModel], fast: bool = False,
                   max_tokens: int = 2000, effort: str | None = None,
                   instruction: str = "") -> Any:
        try:
            resp = await self.llm.complete(
                system=system,
                messages=[LLMMessage(role="user", content=render_input(payload, instruction))],
                purpose=purpose,
                model=self.settings.llm_fast_model if fast else None,
                max_tokens=max_tokens,
                effort=effort,  # type: ignore[arg-type]
                json_schema=strict_schema(out_model),
            )
            return out_model.model_validate_json(resp.text)
        except (ProviderError, ValidationError, ValueError) as e:
            log.warning("brain %s: LLM unusable (%s); deterministic fallback", purpose,
                        type(e).__name__)
            return fallback()

    # ------------------------------------------------------------------ templates
    def template_for(self, task_type: TaskType):
        return template_for(task_type)

    # ------------------------------------------------------------------ interpret
    async def interpret(self, ctx: ConversationContext, message: InboundMessage) -> Interpretation:
        payload = {"ctx": ctx_payload(ctx), "message": message.model_dump(mode="json",
                                                                          exclude_none=True)}
        out: InterpretOut = await self._ask(
            "interpret", payload, InterpretOut,
            system=system_prompt("interpret", tone=ctx.profile.tone,
                                 language=ctx.profile.language),
            fallback=lambda: handlers.h_interpret(payload), fast=True, effort="low")
        return self._interpretation(ctx, message, out)

    def _interpretation(self, ctx: ConversationContext, msg: InboundMessage,
                        out: InterpretOut) -> Interpretation:
        text = msg.text or ""
        cc = self.settings.default_country_code
        open_ids = {t.id for t in ctx.open_tasks}
        task_id = out.task_id if (out.task_id in open_ids or (
            out.task_id and msg.button_id and out.task_id in msg.button_id)) else None
        intent = out.intent
        reply = out.reply
        buttons: list[ReplyButton] = []

        # ---- references (deterministic; '#<id>' refs come from disambiguation taps)
        resolution = None
        spec = None
        if out.task is not None:
            d = out.task
            res_out = resolve(ctx, " ".join(x for x in (text, d.beneficiary_ref or "",
                                                         d.place_ref or "") if x))
            if d.beneficiary_ref and d.beneficiary_ref.startswith("#"):
                res_out.person_id, res_out.ambiguous = d.beneficiary_ref[1:], False
            if d.place_ref and d.place_ref.startswith("#"):
                res_out.place_id, res_out.ambiguous = d.place_ref[1:], False
            resolution = resolution_from(res_out, ctx)
            spec = draft_to_spec(d, ctx, text, self.settings)
            if resolution.location_text and not spec.location_text:
                spec.location_text = resolution.location_text
            if resolution.place_id and not spec.location_text:
                pl = next((p for p in ctx.places if p.id == resolution.place_id), None)
                if pl:
                    spec.location_text = pl.formatted_address or pl.address_text or pl.label
            if resolution.person_id:
                person = next((p for p in ctx.people if p.id == resolution.person_id), None)
                if person and spec.type == TaskType.WELLBEING_CHECKIN:
                    spec.missing = [m for m in spec.missing if m != "beneficiary"]
            if resolution.ambiguous:
                spec.missing.append("beneficiary" if any(
                    b.id.startswith("r:person") for b in resolution.clarification_buttons)
                    else "place")
                reply = resolution.clarification
                buttons = resolution.clarification_buttons
            if msg.button_id and msg.button_id.startswith("r:"):
                waiting = [t for t in ctx.open_tasks if t.status == TaskStatus.NEEDS_INFO]
                if waiting:
                    intent, task_id = Intent.TASK_UPDATE, waiting[-1].id

        facts = [self._fact(ctx, f, msg) for f in out.facts]
        person = None
        if out.person is not None:
            p = out.person
            person = Person(owner_user_id=ctx.user.id, name=p.name or "New contact",
                            relation=canonical_relation(p.relation),
                            aliases=[a for a in p.aliases if a][:5], phone=_phone(p.phone, cc),
                            language=p.language, notes=p.notes)
        place = None
        if out.place is not None:
            pl = out.place
            ephemeral = "__ephemeral__" in pl.aliases
            person_id = None
            if pl.person_ref:
                if person and norm(pl.person_ref) in (norm(person.name), *map(norm,
                                                                              person.aliases)):
                    person_id = person.id
                else:
                    person_id = resolve(ctx, pl.person_ref).person_id
            source = PlaceSource.TYPED
            if pl.maps_link:
                source = PlaceSource.MAPS_LINK
            elif msg.kind == MessageKind.LOCATION:
                source = PlaceSource.WA_LOCATION
            elif msg.kind == MessageKind.VOICE_NOTE:
                source = PlaceSource.VOICE
            place = Place(owner_user_id=ctx.user.id, label=pl.label,
                          aliases=[a for a in pl.aliases if a != "__ephemeral__"],
                          address_text=pl.maps_link or pl.address_text, city=pl.city,
                          location=GeoPoint(lat=msg.location.lat, lng=msg.location.lng)
                          if msg.location else None, source=source, person_id=person_id,
                          ephemeral=ephemeral)
        identifier = None
        if out.identifier is not None:
            idf = out.identifier
            if has_any(norm(f"{idf.label} {idf.value}"), SECRET_WORDS):
                identifier = None
            else:
                try:
                    identifier = AccountIdentifier(user_id=ctx.user.id, company=idf.company,
                                                   label=idf.label, value=idf.value)
                except ValidationError:
                    identifier = None
            if identifier is None:
                reply = ("I can't save OTPs, PINs, CVVs or passwords - and I'll never ask for "
                         "them. Account or consumer numbers are fine.")
        interactions = self._ratings(ctx, out)
        answer = None
        if out.answer is not None:
            qid = None
            if ctx.pending_question is not None:
                qid = ctx.pending_question.id
            else:
                task = next((t for t in ctx.open_tasks if t.id == task_id), None)
                if task and task.result and task.result.needs_approval:
                    qid = task.result.needs_approval.id
            if qid or intent == Intent.ANSWER_QUESTION:
                answer = UserAnswer(question_id=qid or "unknown", text=out.answer.text,
                                    option_index=out.answer.option_index,
                                    approves=out.answer.approves, message_id=msg.id)
        profile_updates: dict[str, Any] = {}
        if out.profile is not None:
            profile_updates = {k: v for k, v in out.profile.model_dump().items()
                               if v is not None and k in _PROFILE_FIELDS}
        autonomy = [AutonomySetting(user_id=ctx.user.id, category=a.category,
                                    level=AutonomyLevel(min(max(a.level, 1), 4)),
                                    enabled=a.enabled) for a in out.autonomy]
        requires_pin = out.requires_pin or intent == Intent.DELETE_DATA or any(
            a.level == AutonomyLevel.ACT_AUTOMATICALLY for a in autonomy)
        return Interpretation(
            intent=intent, reply=reply, buttons=buttons, task_spec=spec, task_id=task_id,
            resolution=resolution, person_upsert=person, place_upsert=place,
            identifier_upsert=identifier, vendor_interactions=interactions, answer=answer,
            facts=facts, choice_index=out.choice_index, profile_updates=profile_updates,
            autonomy_updates=autonomy, requires_pin=requires_pin,
            confidence=min(max(out.confidence, 0.0), 1.0),
        )

    def _fact(self, ctx: ConversationContext, f, msg: InboundMessage) -> Fact:
        person_id = resolve(ctx, f.about_person_ref).person_id if f.about_person_ref else None
        return Fact(user_id=ctx.user.id, kind=f.kind, key=f.key[:60], value=f.value[:300],
                    due_on=_parse_date(f.due_on), recurrence=f.recurrence, person_id=person_id,
                    confidence=min(max(f.confidence, 0.0), 1.0), source_message_id=msg.id)

    def _ratings(self, ctx: ConversationContext, out: InterpretOut) -> list[VendorInteraction]:
        r = out.vendor_rating
        if r is None:
            return []
        biz_id = None
        if r.business_ref:
            ref = norm(r.business_ref)
            biz_id = next((b.id for b in ctx.known_businesses if ref and (
                ref in norm(b.name) or norm(b.name).split()[0] in ref)), None)
        if biz_id is None:
            done = sorted((t for t in ctx.open_tasks if t.target and t.target.business_id),
                          key=lambda t: t.updated_at, reverse=True)
            biz_id = done[0].target.business_id if done else None
        if biz_id is None and ctx.vendor_history:
            biz_id = sorted(ctx.vendor_history, key=lambda v: v.at)[-1].business_id
        if biz_id is None:
            return []
        kind = InteractionKind.NO_SHOW if r.outcome == "no-show" else InteractionKind.RATED
        rating = min(max(r.rating, 1), 5) if r.rating else None
        return [VendorInteraction(user_id=ctx.user.id, business_id=biz_id, kind=kind,
                                  rating=rating, outcome=r.outcome, note=r.note)]

    # ------------------------------------------------------------------ references
    async def resolve_references(self, ctx: ConversationContext, text: str
                                 ) -> ReferenceResolution:
        payload = {"ctx": ctx_payload(ctx), "text": text}
        out: ResolutionOut = await self._ask(
            "resolve_references", payload, ResolutionOut,
            system=system_prompt("resolve_references"),
            fallback=lambda: handlers.h_resolve(payload), fast=True, effort="low",
            max_tokens=600)
        return resolution_from(out, ctx)

    # ------------------------------------------------------------------ onboarding
    async def onboarding_turn(self, ctx: ConversationContext, step: OnboardingStep,
                              message: InboundMessage | None) -> OnboardingTurn:
        turn, draft = _onboarding(ctx, step, message)
        if draft is not None:
            turn.first_task = draft_to_spec(draft, ctx, (message.text if message else "") or "",
                                            self.settings)
        return turn

    # ------------------------------------------------------------------ briefs
    def build_call_brief(self, ctx: ConversationContext, task: Task, *,
                         inbound: InboundContext | None = None) -> CallBrief:
        """Deterministic (no I/O). The returned brief is awaitable, so both
        ``await brain.build_call_brief(...)`` (Protocol) and a plain call work."""
        return briefs.build_call_brief(ctx, task, self.settings, inbound=inbound)

    def build_inbound_brief(self, ctx: ConversationContext, *, caller_phone: str,
                                  tasks: Sequence[Task] = (),
                                  related: Sequence[RelatedTask] = (), kind: str = "answered",
                                  friday_number: str | None = None,
                                  caller_matches_business: bool = True,
                                  business_name: str | None = None) -> InboundCallBrief:
        """Business call-back / missed call (BRIEF E-31..37); see ``briefs``."""
        return briefs.build_inbound_brief(
            ctx, caller_phone=caller_phone, related=list(related), tasks=list(tasks), kind=kind,
            friday_number=friday_number, caller_matches_business=caller_matches_business,
            business_name=business_name, settings=self.settings)

    # ------------------------------------------------------------------ discovery
    async def shortlist(self, ctx: ConversationContext, spec: TaskSpec,
                        candidates: Sequence[BusinessCandidate], n: int) -> list[ShortlistItem]:
        return reports.shortlist(ctx, spec, list(candidates), n,
                                 min_rating=self.settings.discovery_min_rating)

    # ------------------------------------------------------------------ live calls
    async def next_call_action(self, brief: CallBrief, transcript: Transcript,
                               answers: Sequence[UserAnswer]) -> CallAction:
        speak = self.speakable
        payload = {"brief": brief_payload(brief),
                   "transcript": transcript.model_dump(mode="json", exclude_none=True),
                   "answers": [a.model_dump(mode="json") for a in answers],
                   "speakable": sorted(lang.value for lang in speak) if speak else None}

        def fallback() -> CallActionOut:
            return policy_next(brief, transcript, answers, speak)

        out: CallActionOut = await self._ask(
            "call_turn", payload, CallActionOut, system=system_prompt("call_turn"),
            fallback=fallback, fast=True, effort="low", max_tokens=700)
        return guards.to_call_action(out, brief, list(answers))

    async def translate(self, text: str, *, target: Language, source: Language | None = None,
                        context: str = "") -> str:
        payload = {"text": text, "target": target.value,
                   "source": source.value if source else None, "context": context}
        out: TranslateOut = await self._ask(
            "translate", payload, TranslateOut, system=system_prompt("translate"),
            fallback=lambda: handlers.h_translate(payload), fast=True, effort="low",
            max_tokens=500)
        # numbers / amounts must survive translation unchanged
        nums_in = re.findall(r"\d+", text)
        if any(n not in out.text for n in nums_in):
            return handlers.h_translate(payload).text  # type: ignore[attr-defined]
        return out.text

    # ------------------------------------------------------------------ reports
    async def summarize_call(self, ctx: ConversationContext, task: Task, result: CallResult
                             ) -> TaskResult:
        payload = {"ctx": ctx_payload(ctx, recent=4),
                   "task": task.model_dump(mode="json", exclude_none=True),
                   "result": result.model_dump(mode="json", exclude_none=True)}
        det = reports.summary_text(ctx, task, result)
        out: SummaryOut = await self._ask(
            "summarize", payload, SummaryOut,
            system=system_prompt("summarize", tone=ctx.profile.tone,
                                 language=ctx.profile.language),
            fallback=lambda: det, effort="low", max_tokens=1200)
        if not out.summary.strip():
            out = det
        # structured parts are always the deterministic ones
        out.details = det.details + [d for d in out.details if d.key not in
                                     {x.key for x in det.details}]
        if not out.next_steps:
            out.next_steps = det.next_steps
        out.alert = out.alert or det.alert
        return reports.build_task_result(ctx, task, result, out, self.settings)

    async def compare_quotes(self, ctx: ConversationContext, parent: Task,
                             quotes: Sequence[Quote]) -> QuoteComparison:
        budget_max = parent.spec.budget.max_inr if parent.spec.budget else None
        ranked = reports.rank_quotes(list(quotes), budget_max)
        payload = {"ctx": ctx_payload(ctx, recent=2),
                   "parent": parent.model_dump(mode="json", exclude_none=True),
                   "ranked": [q.model_dump(mode="json", exclude_none=True) for q in ranked]}
        out: CompareOut = await self._ask(
            "compare", payload, CompareOut,
            system=system_prompt("compare", tone=ctx.profile.tone, language=ctx.profile.language),
            fallback=lambda: reports.compare_text(ctx, parent, ranked), effort="low",
            max_tokens=1000)
        return reports.build_comparison(parent, ranked, out)

    # ------------------------------------------------------------------ proactive
    @staticmethod
    def nudge_id_for(candidate: NudgeCandidate) -> str:
        """Id the backend should give the Nudge so the ``n:<id>:<action>`` buttons match
        (or pass ``candidate.data['nudge_id']``)."""
        if candidate.data.get("nudge_id"):
            return str(candidate.data["nudge_id"])
        return hashlib.sha1(f"{candidate.user_id}|{candidate.dedupe_key}".encode()).hexdigest()[:32]

    async def judge_nudge(self, ctx: ConversationContext, candidate: NudgeCandidate
                          ) -> NudgeDecision:
        payload = {"ctx": ctx_payload(ctx, recent=4),
                   "candidate": candidate.model_dump(mode="json", exclude_none=True)}
        out: NudgeOut = await self._ask(
            "judge_nudge", payload, NudgeOut,
            system=system_prompt("judge_nudge", tone=ctx.profile.tone,
                                 language=ctx.profile.language),
            fallback=lambda: handlers.h_nudge(payload), effort="low", max_tokens=600)
        if candidate.kind == NudgeKind.WELLBEING_ALERT:
            out.send = True
        if not out.send:
            return NudgeDecision(send=False, reason=out.reason or "not useful now")
        det = handlers.h_nudge(payload)
        text = (out.text or det.text or candidate.reason).strip()  # type: ignore[attr-defined]
        nid = self.nudge_id_for(candidate)
        src = out.buttons or det.buttons  # type: ignore[attr-defined]
        buttons = [ReplyButton(id=nudge_button_id(nid, re.sub(r"[^a-z0-9_]", "_",
                                                              b.action.lower())[:30]),
                               title=truncate_title(b.title)) for b in src[:3]]
        if not buttons:  # every nudge offers an action
            buttons = [ReplyButton(id=nudge_button_id(nid, "ok"), title="OK"),
                       ReplyButton(id=nudge_button_id(nid, "stop"), title="Stop these")]
        lang = "hi" if ctx.profile.language == Language.HI else "en"
        template = TemplateRef(key="nudge", params=[first_name(ctx.profile.name, "there"),
                                                    " ".join(text.split())[:900]], language=lang)
        return NudgeDecision(send=True, text=text, buttons=buttons, template=template,
                             proposed_task=self._proposed_task(ctx, candidate, text),
                             reason=out.reason or "useful")

    def _proposed_task(self, ctx: ConversationContext, cand: NudgeCandidate, text: str
                       ) -> TaskSpec | None:
        d = cand.data or {}
        if cand.kind not in (NudgeKind.PATTERN, NudgeKind.RECURRING_DUE, NudgeKind.DATE_BASED,
                             NudgeKind.FOLLOW_UP) and not d.get("task_type"):
            return None
        biz = d.get("business_name")
        phone = _phone(d.get("business_phone"), self.settings.default_country_code)
        if not biz and not phone and not d.get("task_type"):
            return None
        ttype = TaskType(d.get("task_type") or (
            TaskType.SERVICE_COORDINATION if cand.kind == NudgeKind.FOLLOW_UP else
            TaskType.BOOKING))
        what = d.get("what") or d.get("service") or "the usual"
        delegation = Delegation()
        if d.get("usual_slot") and d.get("usual_price"):
            # US-3.11: tapping "Book it" on a nudge naming an exact slot+price is delegation
            delegation = Delegation(granted=True, scope=["slot", "price"],
                                    time_window_text=str(d["usual_slot"]),
                                    max_price_inr=int(d["usual_price"]),
                                    user_words=f"Tapped 'Book it' on: {text[:200]}")
        return TaskSpec(type=ttype, goal=f"Book {what} at {biz or 'the usual place'}"
                        + (f", {d['usual_slot']}" if d.get("usual_slot") else ""),
                        business_name=biz, business_phone=phone,
                        business_id=d.get("business_id"), delegation=delegation,
                        preferred_times=[str(d["usual_slot"])] if d.get("usual_slot") else [],
                        on_behalf_of=ctx.profile.name)


def policy_next(brief: CallBrief, transcript: Transcript, answers: Sequence[UserAnswer],
                speak: frozenset[Language] | None) -> CallActionOut:
    from .heuristics import policy

    return policy.next_action(brief, transcript, list(answers), speak)


def build_brain(c: Container) -> FridayBrain:
    def speakable() -> frozenset[Language] | None:
        if not c.is_available("tts"):
            return None
        return frozenset(c.tts.supported_languages)

    return FridayBrain(c.llm, c.settings, speakable=speakable)


__all__ = ["FridayBrain", "build_brain", "InboundCallBrief", "InboundContext", "RelatedTask"]
