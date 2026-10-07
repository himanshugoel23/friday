"""Provider and service contracts. Engineers code against THESE, not each other.

Every external provider has (a) a real implementation and (b) a fake/simulator,
both satisfying the Protocol below, wired by ``friday.core.container``.

Implementation ownership
------------------------
  LLMClient, Brain (incl. CallPolicy, Translator), DocumentExtractor
                                              -> AI Engineer      friday/brain/
  TelephonyProvider/CallLeg, STTProvider, TTSProvider, AudioClassifier,
  CallSessionRunner                           -> Voice Engineer   friday/voice/
  MessagingChannel, SMSProvider               -> Backend Engineer friday/channels/
  BusinessDirectory, Geocoder, NumberVerifier, OfficialNumberDirectory
                                              -> Backend Engineer friday/discovery/
  *Repository                                 -> Backend Engineer friday/db/repositories/

Signatures here are FROZEN. Additive changes only (new optional kwargs with
defaults; new Protocols) - see docs/TASKS.md "Changing core".

Owner: Engineering Manager (core).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from friday.core.clock import Clock  # re-export
from friday.core.crypto import KeyProvider  # re-export (SECURITY-12)
from friday.core.models import (
    AccountIdentifier,
    AudioClassification,
    AudioClip,
    BriefTemplate,
    Business,
    BusinessCandidate,
    CallAction,
    CallBrief,
    CallResult,
    Channel,
    ConversationContext,
    DialStatus,
    ExtractedDocument,
    ExtractionKind,
    Fact,
    FridayNumber,
    GeocodeResult,
    GeoPoint,
    GuestDetails,
    HotelBooking,
    HotelBookingMode,
    HotelOffer,
    HotelProperty,
    InboundMessage,
    Interpretation,
    Language,
    MediaBlob,
    MidCallQuestion,
    Nudge,
    NudgeCandidate,
    NudgeDecision,
    NumberCheck,
    NumberChoice,
    NumberHealth,
    NumberOutcome,
    NumberStatus,
    OfficialNumber,
    OnboardingStep,
    OnboardingTurn,
    OutboundCallRequest,
    OutboundMessage,
    Person,
    Place,
    Quote,
    QuoteComparison,
    ReferenceResolution,
    RelatedTask,
    ReplyButton,
    SendReceipt,
    ShortlistItem,
    StayRequest,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
    TemplateRef,
    Transcript,
    Transcription,
    Urgency,
    User,
    UserAnswer,
    VendorInteraction,
    VoiceProfile,
)
from friday.core.scale import (  # re-export (scale-out contracts)
    Cache,
    DistributedLock,
    IdempotencyStore,
    JobQueue,
    Outbox,
    RateLimiter,
)

__all__ = [
    "Cache",
    "CancellableRunner",
    "DistributedLock",
    "IdempotencyStore",
    "InboundCallRunner",
    "InboundTelephony",
    "JobQueue",
    "KeyProvider",
    "Notifier",
    "NumberPool",
    "Outbox",
    "RateLimiter",
    "TaskEngine",
    "TELEPHONY_CAPABILITIES",
    "telephony_capabilities",
    "AskUser",
    "AudioClassifier",
    "Brain",
    "BusinessDirectory",
    "BusinessRepository",
    "CallEnded",
    "CallLeg",
    "CallPolicy",
    "CallSessionRunner",
    "Clock",
    "DocumentExtractor",
    "FactRepository",
    "Geocoder",
    "HotelProvider",
    "IdentifierRepository",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "MessagingChannel",
    "NotifyUser",
    "NudgeRepository",
    "NumberVerifier",
    "OfficialNumberDirectory",
    "PersonRepository",
    "PlaceRepository",
    "ProviderError",
    "SMSProvider",
    "STTProvider",
    "TTSProvider",
    "TaskRepository",
    "TelephonyProvider",
    "Translator",
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
    """Thin transport over a chat model. The brain builds prompts; this only sends.

    * ``purpose`` - stable label ("interpret", "call_turn", "summarize", "extract"...)
      for logs/cost accounting; the deterministic fake keys canned output on it.
    * ``json_schema`` - ask for a JSON object matching the schema (real client uses
      structured outputs); ``LLMResponse.text`` then holds the JSON string.
    * ``attachments`` - images/PDFs for vision (menus, quote photos - B15).
    * ``model`` None -> Settings.llm_model. Live call turns pass Settings.llm_fast_model.
    """

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        purpose: str = "general",
        model: str | None = None,
        max_tokens: int = 1024,
        effort: Effort | None = None,
        json_schema: dict | None = None,
        attachments: Sequence[MediaBlob] = (),
    ) -> LLMResponse: ...


# =============================================================================== brain


@runtime_checkable
class CallPolicy(Protocol):
    """Decides Friday's next move on a LIVE call. Goal-driven, no scripts.

    Called by the voice CallSessionRunner after every callee utterance (and once
    right after the fixed disclosure line). Must be fast (<~1.5s): use the fast model.
    NOT called while the runner is in hold-listening mode (WAIT_ON_HOLD).

    Contract:
      * ``transcript`` has FRIDAY, CALLEE (with detected ``language`` and audio class)
        and SYSTEM turns, e.g. "USER ANSWERED: 6pm", "USER DID NOT ANSWER WITHIN 90s",
        "HUMAN AGENT JOINED AFTER 7m HOLD", "BLOCKED: unapproved long number".
      * Mirror the callee: ``CallAction.language`` = language of the last CALLEE turn
        (if TTS supports it), else ``brief.opening_language``.
      * Never commit money. Approval rule (founder, final): unless
        ``brief.can_commit(answers)`` (confirmation call-back with ``approved_terms``,
        or an explicit ``brief.delegation`` - and then only within its price/time/scope
        limits), do NOT confirm: tell the business she'll call back after checking
        with the user and HANGUP with outcome PENDING_APPROVAL + the offer.
        (ApprovalMode.HOLD_THEN_CALLBACK, opt-in, may ASK_USER(APPROVE_BOOKING) first.)
        Mark the confirming action ``commits_booking=True``.
      * Friday is female: feminine Hindi/Hinglish verb forms ("karti hoon").
      * IVR: understand spoken menus -> PRESS_KEYS (or SAY the option); prefer the
        human-agent path; WAIT_ON_HOLD on hold music/queue messages.
      * Never speak/key OTP/PIN/CVV/password; share only ``brief.approved_identifiers``.
        If verification is demanded -> BRIDGE_USER (patch-in) or HANGUP with
        outcome NEEDS_USER_VERIFICATION and the gathered context.
      * Answer honestly if asked whether it is an AI.
      * End with HANGUP + ``outcome`` (+ ``quote`` / ``care`` / ``collected``).
    Phase 2 inbound calls reuse this protocol with a different brief.
    """

    async def next_call_action(
        self, brief: CallBrief, transcript: Transcript, answers: Sequence[UserAnswer]
    ) -> CallAction: ...


@runtime_checkable
class Translator(Protocol):
    """Live translator mode (B18): one utterance at a time, meaning-preserving."""

    async def translate(
        self, text: str, *, target: Language, source: Language | None = None, context: str = ""
    ) -> str: ...


@runtime_checkable
class Brain(CallPolicy, Translator, Protocol):
    """All language understanding/generation. Pure: no DB, no sending, no sleeping.
    The backend builds a ConversationContext snapshot and acts on the result.
    """

    def template_for(self, task_type: TaskType) -> BriefTemplate:
        """The data-driven template for a task type (friday/brain/templates/)."""
        ...

    async def interpret(self, ctx: ConversationContext, message: InboundMessage) -> Interpretation:
        """Understand a user message (text / voice-note transcript / button reply /
        location pin). Hinglish-aware. Extracts task specs (incl. fan_out/recurrence
        from the template), facts, people/places, settings, identifiers, vendor
        ratings, answers to ctx.pending_question, choices from comparisons."""
        ...

    async def resolve_references(self, ctx: ConversationContext, text: str) -> ReferenceResolution:
        """Map "papa", "mummy ke ghar ke paas", "near my office", "his place" onto
        ctx.people / ctx.places. Ambiguous -> ``clarification`` (ask ONCE). Proposes
        ``new_aliases``. ``interpret`` uses it internally (Interpretation.resolution)."""
        ...

    async def onboarding_turn(
        self, ctx: ConversationContext, step: OnboardingStep, message: InboundMessage | None
    ) -> OnboardingTurn:
        """One step of conversational onboarding. ``message`` None = open the step."""
        ...

    def build_inbound_brief(
        self,
        ctx: ConversationContext,
        *,
        caller_phone: str,
        tasks: Sequence[Task] = (),
        related: Sequence[RelatedTask] = (),
        kind: str = "answered",
        friday_number: str | None = None,
        caller_matches_business: bool = True,
        business_name: str | None = None,
    ) -> CallBrief:
        """Business call-back / missed-call call-back brief (BRIEF E-31..37):
        ``brief.direction`` / ``brief.inbound`` set; unknown or spoofed callers get a
        brief that reveals nothing (SECURITY-8). Synchronous (no I/O)."""
        ...

    async def build_call_brief(self, ctx: ConversationContext, task: Task) -> CallBrief:
        """Task + template + memory (people, places, vendor history, sibling quotes,
        approved identifiers, approved terms) -> CallBrief. Applies minimum-disclosure:
        only what the business needs goes into shareable_details."""
        ...

    async def shortlist(
        self,
        ctx: ConversationContext,
        spec: TaskSpec,
        candidates: Sequence[BusinessCandidate],
        n: int,
    ) -> list[ShortlistItem]:
        """Pick the best ``n`` callable candidates (ratings, reviews, vendor history)."""
        ...

    async def summarize_call(
        self, ctx: ConversationContext, task: Task, result: CallResult
    ) -> TaskResult:
        """User-facing report + structured details/quotes/care outcome, follow-ups,
        vendor interactions to record, wellbeing alert, business-touch template."""
        ...

    async def compare_quotes(
        self, ctx: ConversationContext, parent: Task, quotes: Sequence[Quote]
    ) -> QuoteComparison:
        """Rank quotes/answers from a parent task's child calls and write the comparison."""
        ...

    async def judge_nudge(
        self, ctx: ConversationContext, candidate: NudgeCandidate
    ) -> NudgeDecision:
        """Should this proactive nudge be sent, and with what copy/action?
        Guardrails (cap, quiet hours, consent) are enforced by the backend."""
        ...


@runtime_checkable
class DocumentExtractor(Protocol):
    """Menus / price lists / quote photos / PDFs -> structured data (B15).
    Real impl: LLM vision in friday/brain/; fake: deterministic from filename/meta."""

    async def extract(
        self, media: MediaBlob, *, kind: ExtractionKind = ExtractionKind.GENERIC, hint: str = ""
    ) -> ExtractedDocument: ...


# =============================================================================== voice


class CallEnded(Exception):  # noqa: N818 - a signal, not an error
    """Raised by CallLeg methods when the remote side hung up."""


@runtime_checkable
class STTProvider(Protocol):
    name: str
    supported_languages: frozenset[Language]

    async def transcribe(
        self, audio: AudioClip, *, language_hint: Language | None = None
    ) -> Transcription:
        """Batch STT (WhatsApp voice notes, recordings). MUST set the DETECTED
        ``language``. Streaming STT for live calls is internal to friday/voice."""
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
class AudioClassifier(Protocol):
    """Human vs IVR prompt vs hold music vs queue announcement vs voicemail (C23).
    Used inside real CallLegs to fill Transcription.audio_class."""

    async def classify(self, audio: AudioClip) -> AudioClassification: ...


@runtime_checkable
class CallLeg(Protocol):
    """One party on a live call, at the *utterance* level. Real legs hide media
    streams, VAD, streaming STT, audio classification and TTS behind this; the
    simulator leg exchanges text (and emits audio classes directly).
    """

    provider: str
    provider_call_id: str | None

    async def wait_for_answer(self, timeout_s: float) -> DialStatus: ...

    async def speak(self, text: str, language: Language) -> None:
        """Synthesize + play to the call; returns when playback finished."""
        ...

    async def listen(self, timeout_s: float) -> Transcription | None:
        """Next chunk from this party: a complete utterance (with detected language)
        or an audio-class chunk (HOLD_MUSIC / QUEUE_ANNOUNCEMENT / IVR_PROMPT...).
        None on silence timeout. Raises CallEnded if they hung up."""
        ...

    async def send_dtmf(self, digits: str) -> None:
        """Press keys ('0'-'9', '*', '#', 'w' = 0.5s pause)."""
        ...

    async def add_participant(self, phone: str, *, announce: str | None = None) -> CallLeg:
        """Conference a third party into THIS call (warm transfer / patch-in /
        translator). Returns the new party's leg (listen() on it hears only them)."""
        ...

    async def leave(self) -> None:
        """Friday drops out; remaining participants stay bridged (warm transfer)."""
        ...

    async def hangup(self) -> None:
        """End the call for everyone."""
        ...

    async def recording_url(self) -> str | None:
        """Available after the call ends (None if recording disabled/failed)."""
        ...


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str  # "twilio" / "exotel" / "plivo" / "simulator"

    async def place_call(self, request: OutboundCallRequest) -> CallLeg:
        """Start dialling. Returns immediately; use leg.wait_for_answer()."""
        ...


TELEPHONY_CAPABILITIES: frozenset[str] = frozenset(
    {
        "outbound", "inbound", "missed_call", "media_stream", "dtmf", "recording", "amd",
        "bridge_transfer", "bridge_conference",
    }
)  # fmt: skip


@runtime_checkable
class InboundTelephony(Protocol):
    """Providers that accept inbound calls (BRIEF E30-37). Separate from
    ``TelephonyProvider`` so providers without inbound still satisfy that Protocol."""

    def capabilities(self) -> frozenset[str]:
        """Subset of TELEPHONY_CAPABILITIES; used for per-call routing fallback."""
        ...

    def take_inbound(self, provider_call_id: str) -> CallLeg | None:
        """Claim a parked inbound leg announced by ``InboundCallReceived``."""
        ...


def telephony_capabilities(provider: object) -> frozenset[str]:
    """``provider.capabilities()`` if implemented, else the outbound basics."""
    fn = getattr(provider, "capabilities", None)
    if callable(fn):
        return frozenset(fn())
    return frozenset({"outbound", "dtmf", "recording"})


AskUser = Callable[[MidCallQuestion], Awaitable[UserAnswer | None]]
"""Supplied by the task engine. Sends the question to the user (WhatsApp buttons)
and resolves with their answer, or None after ``question.timeout_s``."""

NotifyUser = Callable[[str], Awaitable[None]]
"""Supplied by the task engine. Fire-and-forget progress note to the user
("On hold with Airtel, expected wait ~8 min")."""


@runtime_checkable
class CallSessionRunner(Protocol):
    """Runs one call end to end: dial -> fixed disclosure -> policy loop -> hangup.

    Responsibilities:
      * speak ``brief.disclosure()`` first (to a human; on IVR, when an agent joins)
      * mirror language (speak each action in ``action.language``)
      * ASK_USER: hold with polished hold lines (no fillers) while awaiting ``ask_user``
      * WAIT_ON_HOLD: hold-listening mode, no LLM turns, until HUMAN/IVR_PROMPT or
        max hold -> HOLD_TIMEOUT; send hold progress via ``notify_user``
      * PRESS_KEYS; BRIDGE_USER (add_participant + leave); TRANSLATOR mode loop
      * enforce ``friday.core.safety`` on every utterance/key and ``brief.can_commit``
        on ``commits_booking`` actions (block -> SYSTEM turn -> ask policy again)
      * enforce max duration; map dial failures to outcomes; recording + transcript;
        publish call events on the bus
    Never raises for call-level failures: returns CallResult(outcome=FAILED, error=...).
    """

    async def run(
        self, brief: CallBrief, ask_user: AskUser, notify_user: NotifyUser | None = None
    ) -> CallResult: ...


@runtime_checkable
class InboundCallRunner(Protocol):
    """Runs an already-answered inbound leg (business call-back) with the same loop."""

    async def run_inbound(
        self,
        leg: CallLeg,
        brief: CallBrief,
        ask_user: AskUser,
        notify_user: NotifyUser | None = None,
        *,
        context: str | None = None,
    ) -> CallResult: ...


@runtime_checkable
class CancellableRunner(Protocol):
    def cancel(self, task_id: str) -> None:
        """FIRST_MATCH sibling found: wrap up this task's live call politely (CANCELLED)."""
        ...


# =============================================================================== channels


@runtime_checkable
class Notifier(Protocol):
    """Backend's single outbound path (impl: friday.channels.notifier). Picks channel,
    enforces the 24h window (template fallback), circle-member consent, quiet hours,
    logs every message. Brain/voice never send directly."""

    async def send(
        self, msg: OutboundMessage, *, urgency: Urgency | None = None
    ) -> SendReceipt: ...

    async def notify_user(
        self,
        user_id: str,
        text: str | None = None,
        *,
        buttons: Sequence[ReplyButton] = (),
        template: TemplateRef | None = None,
        task_id: str | None = None,
        nudge_id: str | None = None,
        question_id: str | None = None,
    ) -> SendReceipt: ...

    async def ask_user(self, user_id: str, question: MidCallQuestion) -> SendReceipt: ...

    async def message_person(
        self, person_id: str, text: str | None = None, *, template: TemplateRef | None = None
    ) -> SendReceipt:
        """Consent-gated (Person.contact_consent == OPTED_IN)."""
        ...

    async def request_person_opt_in(
        self, person: Person, *, requester_name: str, what: str
    ) -> SendReceipt: ...

    async def business_touch(
        self,
        business: Business,
        template: TemplateRef,
        *,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> SendReceipt: ...


@runtime_checkable
class TaskEngine(Protocol):
    """Backend B's engine as seen by the inbound pipeline / call-back service / API.
    Return values are informational (implementations may return the updated Task).
    ``match`` / ``contact`` = friday.db.repositories.CallbackMatch / InboundContact.
    Optional extra: ``handle_unknown_caller(match, contact)``."""

    async def submit(self, task: Task) -> Any:
        """Task already persisted (CREATED)."""
        ...

    async def handle_answer(self, answer: UserAnswer) -> Any: ...

    async def approve(self, task_id: str, approve: bool) -> Any: ...

    async def choose(self, task_id: str, index: int) -> Any: ...

    async def cancel(self, task_id: str) -> Any: ...

    async def update_spec(self, task_id: str, spec: TaskSpec) -> Any: ...

    async def handle_business_callback(self, match: Any, contact: Any) -> Any: ...

    async def handle_missed_call(self, match: Any, contact: Any) -> Any: ...

    async def handle_business_message(self, msg: InboundMessage, match: Any) -> Any: ...

    async def start(self) -> None:
        """Queue workers / schedulers for this process's roles."""
        ...

    async def stop(self) -> None: ...


@runtime_checkable
class MessagingChannel(Protocol):
    """Chat channel (WhatsApp Cloud API, local simulator) to users, opted-in circle
    members, and businesses (B15).

    ``send`` sends exactly what it is given; the 24h-window decision (free-form vs
    ``msg.template``) and consent checks are made by the backend notifier first.
    """

    channel: Channel

    async def send(self, msg: OutboundMessage) -> SendReceipt: ...

    async def fetch_media(self, media_url: str) -> MediaBlob:
        """Download inbound media (voice note, image, PDF) by provider id/url."""
        ...


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
        self, query: str, location: str, *, near: GeoPoint | None = None, limit: int = 10
    ) -> list[BusinessCandidate]:
        """Text search, e.g. ("AC repair", "Indiranagar, Bengaluru"). Results may lack
        phone/reviews; call ``details`` for the ones you shortlist."""
        ...

    async def details(self, place_id: str) -> BusinessCandidate | None:
        """Full record: phone (E.164), rating, review_count, review_snippets, hours."""
        ...


@runtime_checkable
class Geocoder(Protocol):
    """Address / maps link / pin -> coordinates + normalised address."""

    name: str

    async def geocode(
        self, text: str, *, near: GeoPoint | None = None, region: str = "in"
    ) -> GeocodeResult | None: ...

    async def resolve_maps_link(self, url: str) -> GeocodeResult | None:
        """Pasted Google Maps URL (incl. maps.app.goo.gl short links)."""
        ...

    async def reverse(self, point: GeoPoint) -> GeocodeResult | None:
        """WhatsApp location pin -> normalised address."""
        ...


@runtime_checkable
class OfficialNumberDirectory(Protocol):
    """Curated, verified customer-care numbers (C26). Data file + simulator."""

    async def lookup(self, company: str, *, purpose: str | None = None) -> list[OfficialNumber]: ...

    async def find_by_phone(self, phone: str) -> OfficialNumber | None: ...


@runtime_checkable
class NumberVerifier(Protocol):
    """Scam / fake-number check before calling or sharing details (B16, C26).
    Signals: official directory, multiple consistent listings, past call history,
    known-scam list. Simulator: deterministic verdicts from a fixture list."""

    async def verify(
        self, phone: str, *, claimed_name: str | None = None, company: str | None = None
    ) -> NumberCheck: ...


@runtime_checkable
class HotelProvider(Protocol):
    """Official hotel API (Expedia Rapid first; Booking.com/Agoda affiliate later)
    + simulator (D27-29). No scraping. No payments: only pay-at-hotel bookings or
    official booking links. Direct phone bookings go through the call engine."""

    name: str

    async def search(self, stay: StayRequest, *, limit: int = 20) -> list[HotelOffer]:
        """Availability + rates for the stay."""
        ...

    async def property_details(self, property_id: str) -> HotelProperty | None:
        """Incl. phone number (for the direct call), ratings, amenities."""
        ...

    async def book(
        self, offer: HotelOffer, stay: StayRequest, guest: GuestDetails, *, mode: HotelBookingMode
    ) -> HotelBooking:
        """PAY_AT_HOTEL -> real reservation (only if ``offer.pay_at_hotel``);
        BOOKING_LINK -> no reservation, returns status LINK_SENT with ``booking_link``.
        Never called without the user's explicit approval."""
        ...

    async def cancel(self, booking: HotelBooking) -> HotelBooking: ...

    async def modify(self, booking: HotelBooking, stay: StayRequest) -> HotelBooking: ...


@runtime_checkable
class NumberPool(Protocol):
    """Friday caller-ID pool (founder: caller-ID reputation & rotation). Impl: Backend B.

    Rules the implementation MUST follow:
      * sticky: a business keeps its number while that number can dial; moved only
        when retired (then ``NumberChoice.changed`` -> brief.number_changed)
      * new businesses: local city/circle first, then best health, then least load
      * pacing per number: max/hour, max/day (warm-up ramp), max concurrent, min gap
        -> ``NumberChoice.not_before``; never bursts
      * COOLING / RETIRED numbers never dial out (still receive / forward call-backs)
      * global DNC / blocks are honoured across the WHOLE pool - rotation is never
        used to get around a business that blocked Friday (``is_blocked``)
    """

    async def choose_for(
        self,
        business_phone: str,
        *,
        city: str | None = None,
        circle: str | None = None,
        business_id: str | None = None,
    ) -> NumberChoice | None:
        """None = no number may dial now (all paced/cooling) or the business is blocked/DNC."""
        ...

    async def record_outcome(
        self,
        number_phone: str,
        outcome: NumberOutcome,
        *,
        business_phone: str | None = None,
        duration_s: float = 0.0,
    ) -> None:
        """Feeds health; DNC_REQUEST / BLOCKED also mark the business pool-wide."""
        ...

    async def release(self, number_phone: str) -> None:
        """Call ended: frees the concurrency slot."""
        ...

    async def health(self, number_phone: str) -> NumberHealth: ...

    async def rescore(self) -> list[FridayNumber]:
        """Recompute health; move WARMING->ACTIVE, ACTIVE->COOLING, COOLING->ACTIVE or
        RETIRED per Settings thresholds. Returns numbers whose status changed."""
        ...

    async def set_status(self, number_phone: str, status: NumberStatus, *, reason: str) -> None:
        """Ops override: cooldown / retire / reactivate."""
        ...

    async def is_blocked(self, business_phone: str) -> bool:
        """DNC request or block recorded on ANY pool number."""
        ...

    async def owner_of(self, number_phone: str) -> FridayNumber | None:
        """For inbound routing: which pool number (incl. retired-forwarding) was dialled."""
        ...

    async def list_numbers(self) -> list[FridayNumber]:
        """Ops dashboard: health, volume, status."""
        ...


# =============================================================================== repositories
# Minimal persistence contracts shared across backend modules (tasks, proactive,
# api). Backend Engineer implements them in friday/db/repositories/ and may add
# methods there. Brain and voice never touch repositories.


class TaskRepository(Protocol):
    async def get(self, task_id: str) -> Task | None: ...
    async def add(self, task: Task) -> Task: ...
    async def save(self, task: Task) -> Task: ...
    async def set_status(self, task_id: str, status: TaskStatus) -> Task: ...
    async def list_for_user(self, user_id: str, *, open_only: bool = False) -> list[Task]: ...
    async def list_children(self, parent_task_id: str) -> list[Task]: ...
    async def list_due(self, now: datetime) -> list[Task]:
        """SCHEDULED tasks / recurring parents with next run <= now."""
        ...

    async def save_call(self, result: CallResult) -> None: ...
    # extras used by the engines (implemented in friday.db.repositories)
    async def add_question(self, question: MidCallQuestion) -> MidCallQuestion: ...
    async def get_question(self, question_id: str) -> MidCallQuestion | None: ...
    async def answer_question(self, answer: UserAnswer) -> Any: ...
    async def save_hotel_booking(self, booking: HotelBooking, *, user_id: str) -> Any: ...


class UserRepository(Protocol):
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_phone(self, phone: str) -> User | None: ...
    async def add(self, user: User) -> User: ...
    async def save(self, user: User) -> User: ...
    async def list_active(self) -> list[User]: ...


class PersonRepository(Protocol):
    async def get(self, person_id: str) -> Person | None: ...
    async def list_for_owner(self, owner_user_id: str) -> list[Person]: ...
    async def upsert(self, person: Person) -> Person: ...


class PlaceRepository(Protocol):
    async def get(self, place_id: str) -> Place | None: ...
    async def list_for_owner(self, owner_user_id: str) -> list[Place]: ...
    async def upsert(self, place: Place) -> Place: ...


class BusinessRepository(Protocol):
    """Businesses + vendor memory (B20)."""

    async def get(self, business_id: str) -> Business | None: ...
    async def get_by_phone(self, phone: str) -> Business | None: ...
    async def upsert(self, business: Business) -> Business: ...
    async def add_interaction(self, interaction: VendorInteraction) -> VendorInteraction: ...
    async def interactions(
        self, user_id: str, *, business_id: str | None = None, limit: int = 50
    ) -> list[VendorInteraction]: ...


class IdentifierRepository(Protocol):
    """Account identifiers; values encrypted at rest."""

    async def list_for_user(self, user_id: str) -> list[AccountIdentifier]: ...
    async def upsert(self, identifier: AccountIdentifier) -> AccountIdentifier: ...


class FactRepository(Protocol):
    async def list_for_user(self, user_id: str) -> list[Fact]: ...
    async def upsert(self, fact: Fact) -> Fact: ...


class NudgeRepository(Protocol):
    async def add(self, nudge: Nudge) -> Nudge: ...
    async def save(self, nudge: Nudge) -> Nudge: ...
    async def exists(self, user_id: str, dedupe_key: str) -> bool: ...
    async def count_sent_between(self, user_id: str, start: datetime, end: datetime) -> int: ...
    async def get(self, nudge_id: str) -> Nudge | None: ...
    async def list_for_user(self, user_id: str) -> list[Nudge]: ...
    async def list_scheduled_due(self, now: datetime) -> list[Nudge]: ...
    async def list_sent_unanswered_before(self, before: datetime) -> list[Nudge]: ...
    async def add_feedback(self, feedback: Any) -> Any: ...
