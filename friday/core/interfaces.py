"""Provider and service contracts. Engineers code against THESE, not each other.

Every external provider has (a) a real implementation and (b) a fake/simulator,
both satisfying the Protocol below, wired by ``friday.core.container``.

Ownership of implementations
----------------------------
  LLMClient, Brain/CallPolicy            -> AI Engineer      (friday/brain/)
  TelephonyProvider/CallLeg, STT, TTS,
  CallSessionRunner                      -> Voice Engineer   (friday/voice/)
  MessagingChannel, SMSProvider,
  BusinessDirectory, Geocoder, *Repository -> Backend Engineer (friday/channels/,
                                            friday/discovery/, friday/db/repositories/)

Signatures here are FROZEN. Additive changes only (new optional kwargs with
defaults, new methods with a default implementation in a mixin) - see TASKS.md.

Owner: Engineering Manager (core).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from friday.core.clock import Clock  # re-export
from friday.core.models import (
    AudioClip,
    BusinessCandidate,
    CallAction,
    CallBrief,
    CallResult,
    Channel,
    ConversationContext,
    DialStatus,
    Fact,
    GeocodeResult,
    GeoPoint,
    InboundMessage,
    Interpretation,
    Language,
    MidCallQuestion,
    Nudge,
    NudgeCandidate,
    NudgeDecision,
    OnboardingStep,
    OnboardingTurn,
    OutboundCallRequest,
    OutboundMessage,
    Person,
    Place,
    Quote,
    QuoteComparison,
    ReferenceResolution,
    SendReceipt,
    ShortlistItem,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TemplateRef,
    Transcript,
    Transcription,
    User,
    UserAnswer,
    VoiceProfile,
)

__all__ = [
    "AskUser",
    "Brain",
    "BusinessDirectory",
    "CallEnded",
    "CallLeg",
    "CallPolicy",
    "CallSessionRunner",
    "Clock",
    "FactRepository",
    "Geocoder",
    "PersonRepository",
    "PlaceRepository",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "MessagingChannel",
    "NudgeRepository",
    "ProviderError",
    "SMSProvider",
    "STTProvider",
    "TTSProvider",
    "TaskRepository",
    "TelephonyProvider",
    "UserRepository",
]


class ProviderError(RuntimeError):
    """Any external provider failure, normalised. ``retryable`` guides callers."""

    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable


# =============================================================================== LLM


class LLMMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


Effort = Literal["low", "medium", "high"]


@runtime_checkable
class LLMClient(Protocol):
    """Thin wrapper over a chat model. Brain builds prompts; this only transports.

    ``purpose`` is a stable label ("interpret", "call_turn", "summarize", ...) used
    for logging/cost accounting and by the deterministic fake to pick a canned
    response. ``json_schema`` asks for a JSON object matching the schema (the real
    client uses structured outputs; ``text`` then holds the JSON string).
    """

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        purpose: str = "general",
        model: str | None = None,  # None -> Settings.llm_model; pass llm_fast_model for calls
        max_tokens: int = 1024,
        effort: Effort | None = None,
        json_schema: dict | None = None,
    ) -> LLMResponse: ...


# =============================================================================== brain


@runtime_checkable
class CallPolicy(Protocol):
    """Decides Friday's next move on a LIVE call. Goal-driven, no scripts.

    Called by the voice CallSessionRunner after every callee utterance (and once
    right after the fixed disclosure line). Must be fast (<~1.5s): use the fast model.

    Contract:
      * ``transcript`` includes FRIDAY, CALLEE (with detected ``language``) and SYSTEM
        turns (e.g. "USER ANSWERED: 6pm", "USER DID NOT ANSWER WITHIN 90s",
        "RUNNER: booking confirmation requires user approval first").
      * Mirror the callee: ``CallAction.language`` = language of the last CALLEE turn
        (if supported), else ``brief.opening_language``.
      * Never commit money. Before confirming a booking emit ASK_USER with
        ``question.purpose=APPROVE_BOOKING`` unless ``brief.can_commit(answers)``.
        Set ``commits_booking=True`` on the action that confirms.
      * Answer honestly if asked whether it is an AI/human.
      * End with HANGUP + ``outcome`` (+ ``quote``/``collected``).
    Phase 2 inbound calls reuse this protocol with a different brief/goal.
    """

    async def next_call_action(
        self, brief: CallBrief, transcript: Transcript, answers: Sequence[UserAnswer]
    ) -> CallAction: ...


@runtime_checkable
class Brain(CallPolicy, Protocol):
    """All language understanding/generation. Pure: no DB, no sending, no sleeping.
    The backend builds a ConversationContext snapshot and acts on the result.
    """

    async def interpret(self, ctx: ConversationContext, message: InboundMessage) -> Interpretation:
        """Understand a user message (text / voice-note transcript / button reply).
        Hinglish-aware. Extracts task specs, facts, settings, answers to pending
        questions (ctx.pending_question), choices from comparisons."""
        ...

    async def onboarding_turn(
        self, ctx: ConversationContext, step: OnboardingStep, message: InboundMessage | None
    ) -> OnboardingTurn:
        """One step of conversational onboarding. ``message`` None = start the step."""
        ...

    async def resolve_references(
        self, ctx: ConversationContext, text: str
    ) -> ReferenceResolution:
        """Map "papa", "mummy ke ghar ke paas", "near my office", "his place" (from
        ctx.recent) onto ctx.people / ctx.places. Ambiguous -> ask ONCE via
        ``clarification``. Proposes ``new_aliases`` it learned ("PG" = Bengaluru home).
        ``interpret`` calls this internally and puts it in Interpretation.resolution;
        exposed separately so the backend can re-resolve after a clarification."""
        ...

    async def build_call_brief(self, ctx: ConversationContext, task: Task) -> CallBrief:
        """Turn a task (+ user memory, sibling quotes, approved terms) into a CallBrief."""
        ...

    async def shortlist(
        self,
        ctx: ConversationContext,
        spec: TaskSpec,
        candidates: Sequence[BusinessCandidate],
        n: int,
    ) -> list[ShortlistItem]:
        """Pick the best ``n`` callable candidates using ratings + review text, with reasons."""
        ...

    async def summarize_call(
        self, ctx: ConversationContext, task: Task, result: CallResult
    ) -> TaskResult:
        """User-facing report, structured details/quotes, follow-ups, business touch."""
        ...

    async def compare_quotes(
        self, ctx: ConversationContext, parent: Task, quotes: Sequence[Quote]
    ) -> QuoteComparison:
        """Rank quotes from a discovery task's child calls and write the comparison."""
        ...

    async def judge_nudge(self, ctx: ConversationContext, candidate: NudgeCandidate) -> NudgeDecision:
        """Should this proactive nudge be sent, and with what copy/action?
        Guardrails (cap, quiet hours) are enforced by the backend, not here."""
        ...


# =============================================================================== voice


class CallEnded(Exception):  # noqa: N818 - it's a signal, not an error
    """Raised by CallLeg.listen/speak when the remote side hung up."""


@runtime_checkable
class STTProvider(Protocol):
    name: str
    supported_languages: frozenset[Language]

    async def transcribe(
        self, audio: AudioClip, *, language_hint: Language | None = None
    ) -> Transcription:
        """Batch STT (WhatsApp voice notes, recordings). MUST set ``language``
        (detected). Streaming STT for live calls is internal to friday/voice."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    supported_languages: frozenset[Language]

    def voice_for(self, language: Language) -> VoiceProfile:
        """Calm, polished voice for ``language`` (Settings.tts_voices overrides)."""
        ...

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        """Speak ``text`` verbatim. MUST NOT add fillers, breaths or hesitations."""
        ...


@runtime_checkable
class CallLeg(Protocol):
    """One live phone call, at the *utterance* level. Real legs hide media streams,
    VAD, streaming STT and TTS behind this; the simulator leg exchanges text.
    """

    provider: str
    provider_call_id: str | None

    async def wait_for_answer(self, timeout_s: float) -> DialStatus: ...

    async def speak(self, text: str, language: Language) -> None:
        """Synthesize + play; returns when playback finished. Raises CallEnded."""
        ...

    async def listen(self, timeout_s: float) -> Transcription | None:
        """Next complete callee utterance (with detected language), or None on
        silence timeout. Raises CallEnded if the remote hung up."""
        ...

    async def send_dtmf(self, digits: str) -> None: ...

    async def hangup(self) -> None: ...

    async def recording_url(self) -> str | None:
        """Available after hangup (may be None if recording disabled/failed)."""
        ...


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str  # "twilio" / "exotel" / "plivo" / "simulator"

    async def place_call(self, request: OutboundCallRequest) -> CallLeg:
        """Start dialling. Returns immediately; use leg.wait_for_answer()."""
        ...


AskUser = Callable[[MidCallQuestion], Awaitable[UserAnswer | None]]
"""Supplied by the task engine. Sends the question to the user (WhatsApp buttons)
and resolves with their answer, or None after ``question.timeout_s``."""


@runtime_checkable
class CallSessionRunner(Protocol):
    """Runs one call end to end: dial -> disclosure -> policy loop -> hangup.

    Responsibilities: speak the fixed disclosure first (``brief.disclosure()``),
    mirror language (speak each action in ``action.language``), hold with polished
    hold lines while awaiting ``ask_user``, enforce ``brief.can_commit`` on
    ``commits_booking`` actions, enforce max duration, map dial failures to
    outcomes, collect recording + transcript, publish call events on the bus.
    Never raises for call-level failures - returns CallResult(outcome=FAILED, error=...).
    """

    async def run(self, brief: CallBrief, ask_user: AskUser) -> CallResult: ...


# =============================================================================== channels


@runtime_checkable
class MessagingChannel(Protocol):
    """User-facing chat channel (WhatsApp Cloud API, local simulator).

    ``send`` sends exactly what it is given; the 24h-window decision (free-form vs
    ``msg.template``) is made by the backend notifier before calling it.
    """

    channel: Channel

    async def send(self, msg: OutboundMessage) -> SendReceipt: ...


@runtime_checkable
class SMSProvider(Protocol):
    """DLT-registered template SMS only (no free-form SMS in India)."""

    name: str

    async def send_template(self, to_phone: str, template: TemplateRef) -> SendReceipt: ...


# =============================================================================== discovery


@runtime_checkable
class BusinessDirectory(Protocol):
    """Places/maps search (Google Places, simulator). Read-only."""

    name: str

    async def search(
        self, query: str, location: str, *, limit: int = 10
    ) -> list[BusinessCandidate]:
        """Text search, e.g. ("AC repair", "Indiranagar, Bengaluru"). Results may lack
        phone/reviews; call ``details`` for the ones you shortlist."""
        ...

    async def details(self, place_id: str) -> BusinessCandidate | None:
        """Full record incl. phone (E.164), rating, review_count, review_snippets."""
        ...


@runtime_checkable
class Geocoder(Protocol):
    """Address/maps-link -> coordinates (Google Geocoding/Places, simulator)."""

    name: str

    async def geocode(
        self, text: str, *, near: GeoPoint | None = None, region: str = "in"
    ) -> GeocodeResult | None:
        """Free-text address ("Kothrud, Pune", "B-12 Vasant Kunj Delhi")."""
        ...

    async def resolve_maps_link(self, url: str) -> GeocodeResult | None:
        """Pasted Google Maps URL (incl. maps.app.goo.gl short links)."""
        ...

    async def reverse(self, point: GeoPoint) -> GeocodeResult | None:
        """WhatsApp location pin -> normalised address."""
        ...


# =============================================================================== repositories
# Minimal persistence contracts used across backend modules (tasks, proactive, api).
# Backend Engineer implements them in friday/db/repositories/ and may add methods.


class TaskRepository(Protocol):
    async def get(self, task_id: str) -> Task | None: ...
    async def add(self, task: Task) -> Task: ...
    async def save(self, task: Task) -> Task: ...
    async def set_status(self, task_id: str, status: TaskStatus) -> Task: ...
    async def list_for_user(self, user_id: str, *, open_only: bool = False) -> list[Task]: ...
    async def list_children(self, parent_task_id: str) -> list[Task]: ...
    async def list_due(self, now: datetime) -> list[Task]:
        """SCHEDULED tasks with next_attempt_at <= now."""
        ...
    async def save_call(self, result: CallResult) -> None: ...


class UserRepository(Protocol):
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_phone(self, phone: str) -> User | None: ...
    async def add(self, user: User) -> User: ...
    async def save(self, user: User) -> User: ...


class FactRepository(Protocol):
    async def list_for_user(self, user_id: str) -> list[Fact]: ...
    async def upsert(self, fact: Fact) -> Fact: ...


class PersonRepository(Protocol):
    async def get(self, person_id: str) -> Person | None: ...
    async def list_for_owner(self, owner_user_id: str) -> list[Person]: ...
    async def upsert(self, person: Person) -> Person: ...


class PlaceRepository(Protocol):
    async def get(self, place_id: str) -> Place | None: ...
    async def list_for_owner(self, owner_user_id: str) -> list[Place]: ...
    async def upsert(self, place: Place) -> Place: ...


class NudgeRepository(Protocol):
    async def add(self, nudge: Nudge) -> Nudge: ...
    async def save(self, nudge: Nudge) -> Nudge: ...
    async def exists(self, user_id: str, dedupe_key: str) -> bool: ...
    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int: ...


