"""Wire models: what the LLM (real or fake) returns for each ``purpose``.

They are deliberately flatter and simpler than the core models (no free-form
dicts, everything nullable instead of defaulted) so they work with Anthropic
structured outputs. The brain converts wire -> core models in code, where the
hard rules (approval, delegation, secrets, minimum disclosure) are enforced.

``strict_schema(Model)`` turns a pydantic model into a JSON schema accepted by
structured outputs: every object ``additionalProperties: false`` with all
properties required, no defaults / titles / length constraints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from friday.core.models import (
    AutonomyCategory,
    CallActionType,
    CallMode,
    CallOutcome,
    CareRequestKind,
    ExtractionKind,
    FactKind,
    FanOutStrategy,
    Intent,
    Language,
    QuestionPurpose,
    Recurrence,
    TaskType,
    Tone,
)


class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class KV(Wire):
    key: str
    value: str


# ------------------------------------------------------------------ interpret


class DelegationOut(Wire):
    granted: bool = False
    scope: list[str] = []
    max_price_inr: int | None = None
    window_start: str | None = None  # ISO datetime, UTC or with offset
    window_end: str | None = None
    time_window_text: str | None = None
    conditions: list[str] = []
    user_words: str | None = None


class RecurrenceOut(Wire):
    freq: Recurrence = Recurrence.WEEKLY
    interval: int = 1
    interval_days: int | None = None
    weekdays: list[int] = []
    day_of_month: int | None = None
    time_ist: str = "10:00"


class StayOut(Wire):
    destination: str
    check_in: str  # YYYY-MM-DD
    check_out: str
    adults: int = 2
    children: int = 0
    rooms: int = 1
    max_rate_per_night_inr: int | None = None
    property_types: list[str] = []
    preferences: list[str] = []


class TaskDraft(Wire):
    type: TaskType
    goal: str
    business_name: str | None = None
    business_phone: str | None = None
    category: str | None = None
    item: str | None = None
    reference: str | None = None
    company: str | None = None
    care_request: CareRequestKind | None = None
    discovery_query: str | None = None
    location_text: str | None = None
    when_text: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    preferred_times: list[str] = []
    party_size: int | None = None
    budget_max_inr: int | None = None
    budget_target_inr: int | None = None
    questions: list[str] = []
    constraints: list[str] = []
    delegation: DelegationOut | None = None
    recurrence: RecurrenceOut | None = None
    stay: StayOut | None = None
    beneficiary_ref: str | None = None  # words used for who it's for ("papa")
    place_ref: str | None = None  # words used for where ("mummy ke ghar ke paas")
    call_mode: CallMode = CallMode.AGENT
    fan_out: FanOutStrategy | None = None
    missing: list[str] = []
    notes: str | None = None


class FactOut(Wire):
    kind: FactKind = FactKind.GENERAL
    key: str
    value: str
    due_on: str | None = None  # YYYY-MM-DD (IST)
    recurrence: Recurrence = Recurrence.NONE
    about_person_ref: str | None = None
    confidence: float = 0.9


class PersonOut(Wire):
    name: str
    relation: str | None = None
    phone: str | None = None
    language: Language | None = None
    aliases: list[str] = []
    city: str | None = None
    notes: str | None = None


class PlaceOut(Wire):
    label: str
    address_text: str | None = None
    city: str | None = None
    person_ref: str | None = None
    aliases: list[str] = []
    maps_link: str | None = None


class IdentifierOut(Wire):
    company: str | None = None
    label: str
    value: str


class VendorRatingOut(Wire):
    business_ref: str | None = None
    rating: int | None = None
    outcome: str | None = None
    note: str | None = None


class AnswerOut(Wire):
    text: str
    option_index: int | None = None
    approves: bool = False


class ProfileUpdatesOut(Wire):
    name: str | None = None
    city: str | None = None
    language: Language | None = None
    tone: Tone | None = None
    morning_briefing: bool | None = None
    briefing_hour_ist: int | None = None
    forget: str | None = None  # "forget my rent date" (no core intent yet)
    pause_days: int | None = None


class AutonomyOut(Wire):
    category: AutonomyCategory
    level: int = 2
    enabled: bool = True


class InterpretOut(Wire):
    intent: Intent
    reply: str | None = None
    task: TaskDraft | None = None
    task_id: str | None = None
    answer: AnswerOut | None = None
    facts: list[FactOut] = []
    person: PersonOut | None = None
    place: PlaceOut | None = None
    identifier: IdentifierOut | None = None
    vendor_rating: VendorRatingOut | None = None
    choice_index: int | None = None
    profile: ProfileUpdatesOut | None = None
    autonomy: list[AutonomyOut] = []
    requires_pin: bool = False
    forget_fact_ids: list[str] = []
    confidence: float = 0.9


# ------------------------------------------------------------------ references


class AliasOut(Wire):
    target: str  # "person" | "place"
    target_id: str
    alias: str


class ButtonOut(Wire):
    id: str
    title: str


class ResolutionOut(Wire):
    person_id: str | None = None
    place_id: str | None = None
    location_text: str | None = None
    ambiguous: bool = False
    clarification: str | None = None
    buttons: list[ButtonOut] = []
    new_aliases: list[AliasOut] = []


# ------------------------------------------------------------------ call policy


class QuestionOut(Wire):
    text: str
    purpose: QuestionPurpose = QuestionPurpose.CLARIFY
    options: list[str] = []


class QuoteOut(Wire):
    amount_inr: int | None = None
    original_amount_inr: int | None = None
    price_text: str
    inclusions: list[str] = []
    exclusions: list[str] = []
    validity: str | None = None
    available_slots: list[str] = []
    notes: str | None = None


class CareOut(Wire):
    ticket_number: str | None = None
    agent_name: str | None = None
    promised_date: str | None = None  # YYYY-MM-DD
    promised_text: str | None = None
    escalation_level: int = 1
    resolved: bool = False
    ivr_path: list[str] = []


class CallActionOut(Wire):
    type: CallActionType
    text: str | None = None
    language: Language = Language.HINGLISH
    digits: str | None = None
    outcome: CallOutcome | None = None
    question: QuestionOut | None = None
    collected: list[KV] = []
    quote: QuoteOut | None = None
    commits_booking: bool = False
    care: CareOut | None = None
    user_update: str | None = None
    max_hold_s: int | None = None
    leave_after_bridge: bool = True


# ------------------------------------------------------------------ reports


class SummaryOut(Wire):
    summary: str
    details: list[KV] = []
    next_steps: list[str] = []
    alert: str | None = None


class CompareOut(Wire):
    summary: str
    recommended_index: int | None = None


class NudgeButtonOut(Wire):
    action: str
    title: str


class NudgeOut(Wire):
    send: bool
    text: str | None = None
    buttons: list[NudgeButtonOut] = []
    reason: str = ""


class OnboardingOut(Wire):
    reply: str
    name: str | None = None
    city: str | None = None
    language: Language | None = None
    tone: Tone | None = None
    invite_code: str | None = None
    consent_given: bool | None = None
    pin: str | None = None
    skip: bool = False


class ReasonOut(Wire):
    index: int
    reason: str


class ReasonsOut(Wire):
    reasons: list[ReasonOut] = []


class PriceItemOut(Wire):
    name: str
    amount_inr: int | None = None
    price_text: str | None = None
    unit: str | None = None


class ExtractOut(Wire):
    kind: ExtractionKind = ExtractionKind.GENERIC
    text: str
    items: list[PriceItemOut] = []
    business_name: str | None = None
    quote_amount_inr: int | None = None
    quote_text: str | None = None
    inclusions: list[str] = []
    confidence: float = 0.8


class TranslateOut(Wire):
    text: str


class BusinessReplyOut(Wire):
    text: str
    language: Language = Language.HINGLISH
    hangup: bool = False


# ------------------------------------------------------------------ strict schema

_DROP = {
    "default",
    "title",
    "maxLength",
    "minLength",
    "maxItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "format",
    "examples",
    "description",
}


def _strict(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _strict(v) for k, v in node.items() if k not in _DROP}
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties", {})
            out["additionalProperties"] = False
            out["required"] = list(props.keys())
        if "minItems" in out and out["minItems"] not in (0, 1):
            out.pop("minItems")
        return out
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for structured outputs (all fields required, nullable via anyOf)."""
    return _strict(model.model_json_schema())
