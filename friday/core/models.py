"""Shared domain models and enums - the lingua franca between brain, voice,
channels, tasks, proactive and api.

Rules
-----
* Pure data (pydantic v2). No I/O, no provider SDK types, no ORM objects.
* Persisted entities carry ``id: str`` (uuid4 hex from ``new_id()``) and aware-UTC
  datetimes. The ORM tables in ``friday/db/tables.py`` mirror these 1:1; the
  Backend Engineer's repositories convert ORM rows <-> these models.
* Phone numbers are E.164 strings (``+919876543210``); use ``normalize_phone``.

Owner: Engineering Manager (core, frozen). Additive changes only: new optional
fields with defaults, new enum members. Never rename/remove.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow


def new_id() -> str:
    return uuid.uuid4().hex


_DIGITS = re.compile(r"\D+")


def normalize_phone(raw: str, default_cc: str = "+91") -> str:
    """Best-effort E.164 normalisation, India-first.

    '98765 43210' -> '+919876543210'; '09876543210' -> '+919876543210';
    '919876543210' -> '+919876543210'; '+1 415 555 0100' -> '+14155550100'.
    """
    raw = raw.strip()
    if raw.startswith("whatsapp:"):
        raw = raw[len("whatsapp:") :]
    plus = raw.startswith("+")
    digits = _DIGITS.sub("", raw)
    if not digits:
        raise ValueError(f"not a phone number: {raw!r}")
    if plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    cc = default_cc.lstrip("+")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+{cc}{digits}"
    if digits.startswith(cc) and len(digits) == 10 + len(cc):
        return "+" + digits
    return "+" + digits


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, validate_assignment=True)


# =============================================================================== enums


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    VOICE = "voice"  # Phase 2: user calls Friday / Friday calls user
    SIMULATOR = "simulator"  # local chat simulator stands in for WhatsApp


class Language(StrEnum):
    EN = "en"
    HI = "hi"
    HINGLISH = "hinglish"


class Tone(StrEnum):
    FRIENDLY = "friendly"  # default: witty, warm, concise
    FORMAL = "formal"
    PLAYFUL = "playful"


class OnboardingStep(StrEnum):
    """Ordered conversational onboarding. Persisted on User.onboarding_step."""

    INVITE_CODE = "invite_code"
    NAME = "name"
    CITY = "city"
    LANGUAGE = "language"
    TONE = "tone"
    CONSENT = "consent"
    PIN = "pin"
    FIRST_TASK = "first_task"
    DONE = "done"


class UserStatus(StrEnum):
    WAITLISTED = "waitlisted"  # messaged without invite
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"  # "delete everything" executed; row kept as tombstone (no PII)


class ConsentKind(StrEnum):
    TERMS_PRIVACY = "terms_privacy"  # DPDP 2023 notice + "I agree"
    CALL_RECORDING = "call_recording"
    PROACTIVE = "proactive"
    MORNING_BRIEFING = "morning_briefing"


class TaskType(StrEnum):
    BOOKING = "booking"  # clinic, salon, restaurant, service provider
    ENQUIRY = "enquiry"  # open? price? stock?


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"  # brain is extracting spec / resolving business
    NEEDS_INFO = "needs_info"  # waiting for the user to fill a missing spec field
    AWAITING_APPROVAL = "awaiting_approval"  # user must OK the call (autonomy < 4)
    SCHEDULED = "scheduled"  # will dial at next_attempt_at (retry / call-back-later)
    CALLING = "calling"
    AWAITING_USER = "awaiting_user"  # mid-call question outstanding, business on hold
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


class DialStatus(StrEnum):
    """Result of trying to connect an outbound call (before any conversation)."""

    ANSWERED = "answered"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"  # answering machine / IVR greeting detected
    FAILED = "failed"  # invalid number, carrier error...


class CallOutcome(StrEnum):
    """Final outcome of one call attempt."""

    SUCCESS = "success"  # goal achieved (booked / answered the enquiry)
    PARTIAL = "partial"  # some info, goal not fully met
    DECLINED = "declined"  # business said no (fully booked, out of stock...)
    CALLBACK_LATER = "callback_later"  # "call after 5"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    HUNG_UP = "hung_up"  # business hung up mid-call (metric: <20%)
    USER_TIMEOUT = "user_timeout"  # mid-call question unanswered; call wrapped up
    FAILED = "failed"  # technical failure
    CANCELLED = "cancelled"

    @property
    def is_retryable(self) -> bool:
        return self in (
            CallOutcome.BUSY,
            CallOutcome.NO_ANSWER,
            CallOutcome.VOICEMAIL,
            CallOutcome.CALLBACK_LATER,
            CallOutcome.FAILED,
        )


class CallDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"  # Phase 2


class Speaker(StrEnum):
    FRIDAY = "friday"
    CALLEE = "callee"  # the business (outbound) / the user (Phase 2 inbound)
    SYSTEM = "system"  # events: "user answered: 6pm", "on hold", DTMF...


class CallActionType(StrEnum):
    SAY = "say"  # speak text, then listen for the reply
    ASK_USER = "ask_user"  # speak hold_text, ask the user on WhatsApp, wait for answer
    WAIT = "wait"  # say nothing, keep listening (callee checking something)
    DTMF = "dtmf"  # press keys (IVR menus) - optional for Phase 1
    HANGUP = "hangup"  # speak text (goodbye) then end the call


class MessageKind(StrEnum):
    TEXT = "text"
    VOICE_NOTE = "voice_note"
    BUTTON_REPLY = "button_reply"
    IMAGE = "image"
    LOCATION = "location"
    CONTACT = "contact"  # shared vCard (business phone!)
    SYSTEM = "system"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Intent(StrEnum):
    NEW_TASK = "new_task"  # "book a haircut at Looks tomorrow 6pm"
    TASK_UPDATE = "task_update"  # modifies / adds info to an open task
    ANSWER_QUESTION = "answer_question"  # answers an outstanding mid-call/clarifying q
    APPROVE = "approve"  # yes/go-ahead for a pending approval or nudge action
    REJECT = "reject"
    CANCEL_TASK = "cancel_task"
    REMEMBER = "remember"  # "my rent is due on 5th"
    QUERY_MEMORY = "query_memory"  # "what's my dentist's number?"
    SETTINGS = "settings"  # tone, language, autonomy, quiet hours, briefing opt-in
    STATUS = "status"  # "what happened with the salon?"
    DELETE_DATA = "delete_data"  # "delete everything"
    INVITE = "invite"  # "give me an invite code"
    HELP = "help"
    SMALL_TALK = "small_talk"
    UNKNOWN = "unknown"


class FactKind(StrEnum):
    DATE = "date"  # "rent due on 5th", "insurance expires March"
    PREFERENCE = "preference"  # "I like Dr. Mehta", "usual haircut: Looks Salon"
    PERSON = "person"  # "my wife Priya"
    PATTERN = "pattern"  # derived: haircut every ~4 weeks
    GENERAL = "general"


class Recurrence(StrEnum):
    NONE = "none"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class NudgeKind(StrEnum):
    TASK_REMINDER = "task_reminder"  # "appointment in 2h"
    FOLLOW_UP = "follow_up"  # "did the plumber come?"
    DATE_BASED = "date_based"  # from Fact(kind=DATE)
    PATTERN = "pattern"  # "4 weeks since haircut - book usual?"
    MORNING_BRIEFING = "morning_briefing"
    TASK_RESULT = "task_result"  # not unprompted; report of a finished task


class Urgency(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"  # bypasses daily cap
    SAFETY = "safety"  # bypasses daily cap AND quiet hours


class NudgeStatus(StrEnum):
    PENDING = "pending"  # candidate, not yet judged
    SCHEDULED = "scheduled"  # approved, waiting for send time (e.g. after quiet hours)
    SENT = "sent"
    SUPPRESSED = "suppressed"  # guardrail or brain said no
    ACTED = "acted"
    IGNORED = "ignored"
    DISMISSED = "dismissed"


class FeedbackType(StrEnum):
    ACTED = "acted"
    IGNORED = "ignored"  # no response within window
    DISMISSED = "dismissed"  # "not now"
    SNOOZED = "snoozed"
    STOP = "stop"  # "stop sending these" -> autonomy level for category drops to off


class AutonomyLevel(IntEnum):
    INFORM = 1  # just tell me
    SUGGEST = 2  # suggest an action with buttons
    ACT_WITH_APPROVAL = 3  # prepare the action, run it when I tap "Yes"
    ACT_AUTOMATICALLY = 4  # explicit opt-in only; still never pays/commits money


class AutonomyCategory(StrEnum):
    """Categories autonomy levels are set per. Keep coarse."""

    BOOKINGS = "bookings"
    ENQUIRIES = "enquiries"
    REMINDERS = "reminders"
    FOLLOW_UPS = "follow_ups"
    ROUTINES = "routines"  # pattern nudges (haircut, groceries...)
    BRIEFING = "briefing"


# =============================================================================== people


class User(_Model):
    """Identity + access. PII-light (profile data lives in Profile)."""

    id: str = Field(default_factory=new_id)
    phone: str  # E.164, unique
    status: UserStatus = UserStatus.ONBOARDING
    onboarding_step: OnboardingStep = OnboardingStep.INVITE_CODE
    pin_hash: str | None = None  # never the raw PIN
    pin_failed_attempts: int = 0
    invited_by_user_id: str | None = None
    invites_remaining: int = 5
    monthly_call_cap: int = 10
    last_inbound_at: datetime | None = None  # drives WhatsApp 24h window
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Profile(_Model):
    user_id: str
    name: str | None = None
    city: str | None = None
    language: Language = Language.HINGLISH
    tone: Tone = Tone.FRIENDLY
    morning_briefing: bool = False
    briefing_hour_ist: int = 8
    preferred_channel: Channel = Channel.WHATSAPP
    updated_at: datetime = Field(default_factory=utcnow)


class Consent(_Model):
    id: str = Field(default_factory=new_id)
    user_id: str
    kind: ConsentKind
    granted: bool
    policy_version: str = "2026-01"
    evidence_text: str | None = None  # the user's literal "I agree"
    message_id: str | None = None
    recorded_at: datetime = Field(default_factory=utcnow)


class Invite(_Model):
    code: str  # short, human-typeable, unique
    created_by_user_id: str | None = None  # None = admin/system invite
    redeemed_by_user_id: str | None = None
    redeemed_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AutonomySetting(_Model):
    user_id: str
    category: AutonomyCategory
    level: AutonomyLevel = AutonomyLevel.SUGGEST
    enabled: bool = True  # False == user said "stop" for this category
    updated_at: datetime = Field(default_factory=utcnow)


# =============================================================================== memory


class Business(_Model):
    id: str = Field(default_factory=new_id)
    name: str
    phone: str  # E.164
    category: str | None = None  # "salon", "clinic", "restaurant", "plumber"...
    city: str | None = None
    address: str | None = None
    notes: str | None = None  # "closed Tuesdays", "ask for Ramesh"
    language_hint: Language | None = None
    created_by_user_id: str | None = None
    last_called_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Fact(_Model):
    """A remembered piece of information about the user."""

    id: str = Field(default_factory=new_id)
    user_id: str
    kind: FactKind
    key: str  # normalised short label, e.g. "rent_due", "usual_salon", "insurance_expiry"
    value: str  # human readable, e.g. "5th of every month", "Looks Salon, Indiranagar"
    due_on: date | None = None  # next occurrence for DATE facts (IST calendar date)
    recurrence: Recurrence = Recurrence.NONE
    business_id: str | None = None
    confidence: float = 1.0
    source_message_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# =============================================================================== messaging


class ReplyButton(_Model):
    """WhatsApp interactive reply button (max 3 per message, title <= 20 chars).

    ``id`` is the payload we get back. Use the helpers below to build/parse ids:
    ``q:<question_id>:<option_index>`` for mid-call questions,
    ``n:<nudge_id>:<action>`` for nudge actions, ``a:<task_id>:<yes|no>`` for approvals.
    """

    id: str = Field(max_length=256)
    title: str = Field(max_length=20)


def question_button_id(question_id: str, option_index: int) -> str:
    return f"q:{question_id}:{option_index}"


def nudge_button_id(nudge_id: str, action: str) -> str:
    return f"n:{nudge_id}:{action}"


def approval_button_id(task_id: str, approve: bool) -> str:
    return f"a:{task_id}:{'yes' if approve else 'no'}"


def parse_button_id(button_id: str) -> tuple[str, str, str] | None:
    """'q:abc:1' -> ('q', 'abc', '1'); None if not one of ours."""
    parts = button_id.split(":", 2)
    if len(parts) != 3 or parts[0] not in {"q", "n", "a"}:
        return None
    return parts[0], parts[1], parts[2]


class TemplateRef(_Model):
    """A pre-approved template (WhatsApp outside 24h window, or DLT SMS).

    ``key`` is a logical name ("nudge", "task_update"...) mapped to the provider's
    template id/name via Settings.whatsapp_templates / Settings.sms_dlt_templates.
    """

    key: str
    params: list[str] = Field(default_factory=list)  # positional {{1}}, {{2}}...
    language: str = "en"


class InboundMessage(_Model):
    """Normalised message from any channel. Channel adapters produce these."""

    id: str = Field(default_factory=new_id)
    channel: Channel
    from_phone: str  # E.164
    user_id: str | None = None  # resolved by backend after lookup
    kind: MessageKind = MessageKind.TEXT
    text: str | None = None  # typed text, or STT transcript for voice notes
    media_url: str | None = None  # provider media id/url (voice note, image)
    media_mime: str | None = None
    button_id: str | None = None  # for BUTTON_REPLY: ReplyButton.id
    contact_phone: str | None = None  # for CONTACT: shared number
    provider_message_id: str | None = None
    reply_to_provider_id: str | None = None
    received_at: datetime = Field(default_factory=utcnow)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


class OutboundMessage(_Model):
    """What we want to send. Exactly one of text / template should drive the body.

    The backend's notifier decides channel and freeform-vs-template (24h rule);
    the brain only fills ``text``/``buttons``.
    """

    id: str = Field(default_factory=new_id)
    channel: Channel
    to_phone: str
    user_id: str | None = None
    text: str | None = None
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    template: TemplateRef | None = None
    media_url: str | None = None  # e.g. call recording as voice note
    media_mime: str | None = None
    task_id: str | None = None
    nudge_id: str | None = None
    question_id: str | None = None


class SendReceipt(_Model):
    message_id: str  # our OutboundMessage.id
    provider_message_id: str | None = None
    ok: bool = True
    error: str | None = None
    sent_at: datetime = Field(default_factory=utcnow)


# =============================================================================== tasks


class TaskSpec(_Model):
    """What the user wants done - extracted by the brain, refined via clarifications."""

    type: TaskType
    goal: str  # one line, e.g. "Book a haircut for Rahul tomorrow 6-8pm"
    business_name: str | None = None
    business_phone: str | None = None  # E.164; required before CALLING
    business_id: str | None = None
    category: str | None = None  # salon / clinic / restaurant / plumber...
    when_text: str | None = None  # user's words: "tomorrow evening"
    window_start: datetime | None = None  # resolved UTC window, if any
    window_end: datetime | None = None
    party_size: int | None = None
    questions: list[str] = Field(default_factory=list)  # for enquiries: what to ask
    constraints: list[str] = Field(default_factory=list)  # "female doctor", "under 500"
    # decisions Friday may take alone on the call; anything else -> ASK_USER
    allowed_decisions: list[str] = Field(default_factory=list)
    on_behalf_of: str | None = None  # name used in the AI disclosure
    call_language: Language = Language.HINGLISH
    notes: str | None = None
    missing: list[str] = Field(default_factory=list)  # fields the brain still needs

    @property
    def is_ready_to_call(self) -> bool:
        return bool(self.business_phone) and not self.missing


class Task(_Model):
    id: str = Field(default_factory=new_id)
    user_id: str
    type: TaskType
    status: TaskStatus = TaskStatus.CREATED
    spec: TaskSpec
    attempts: int = 0
    max_attempts: int = 3
    next_attempt_at: datetime | None = None
    last_outcome: CallOutcome | None = None
    result: TaskResult | None = None
    source_message_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskResult(_Model):
    """User-facing report produced by brain.summarize_call()."""

    success: bool
    summary: str  # what to tell the user (in their language/tone)
    details: dict[str, str] = Field(default_factory=dict)  # "time": "6pm", "price": "₹400"
    appointment_at: datetime | None = None  # UTC; feeds TASK_REMINDER nudges
    next_steps: list[str] = Field(default_factory=list)
    follow_up_at: datetime | None = None  # feeds FOLLOW_UP nudges
    retry_suggested: bool = False
    facts: list[Fact] = Field(default_factory=list)  # e.g. business notes learned
    business_touch: TemplateRef | None = None  # end-of-call SMS/WA to the business


# =============================================================================== calls


class CallTurn(_Model):
    speaker: Speaker
    text: str
    at: datetime = Field(default_factory=utcnow)
    language: Language | None = None
    confidence: float | None = None  # STT confidence for CALLEE turns


class Transcript(_Model):
    turns: list[CallTurn] = Field(default_factory=list)

    def add(self, speaker: Speaker, text: str, at: datetime | None = None, **kw: Any) -> CallTurn:
        turn = CallTurn(speaker=speaker, text=text, at=at or utcnow(), **kw)
        self.turns.append(turn)
        return turn

    def last(self, speaker: Speaker | None = None) -> CallTurn | None:
        for turn in reversed(self.turns):
            if speaker is None or turn.speaker == speaker:
                return turn
        return None

    def render(self) -> str:
        """Plain text for prompts/logs: 'FRIDAY: ...\\nCALLEE: ...'."""
        return "\n".join(f"{t.speaker.value.upper()}: {t.text}" for t in self.turns)


class MidCallQuestion(_Model):
    """Question Friday needs the user to answer while the business holds."""

    id: str = Field(default_factory=new_id)
    task_id: str
    call_id: str | None = None
    text: str  # "They have 4pm or 6pm. Which one?"
    options: list[str] = Field(default_factory=list, max_length=3)  # become reply buttons
    allow_free_text: bool = True
    timeout_s: int = 90
    asked_at: datetime = Field(default_factory=utcnow)


class UserAnswer(_Model):
    question_id: str
    text: str  # chosen option title or free text
    option_index: int | None = None
    message_id: str | None = None
    answered_at: datetime = Field(default_factory=utcnow)


class CallAction(_Model):
    """The brain's decision for the next turn of a live call (see CallPolicy)."""

    type: CallActionType
    text: str | None = None  # SAY/HANGUP: what to speak. ASK_USER: hold line for callee
    language: Language = Language.HINGLISH  # TTS language for ``text``
    question: MidCallQuestion | None = None  # required for ASK_USER
    digits: str | None = None  # DTMF
    outcome: CallOutcome | None = None  # HANGUP: brain's verdict on the call
    collected: dict[str, str] = Field(default_factory=dict)  # facts learned so far


class CallContext(_Model):
    """Everything the call policy needs; built by the task engine, read-only to voice."""

    task: Task
    user_name: str | None = None  # for "calling on behalf of <name>"
    user_language: Language = Language.HINGLISH
    business: Business | None = None
    direction: CallDirection = CallDirection.OUTBOUND
    attempt: int = 1
    answers: list[UserAnswer] = Field(default_factory=list)  # mid-call answers so far
    max_duration_s: int = 300


class CallResult(_Model):
    """Returned by CallSessionRunner.run(); persisted by the task engine."""

    call_id: str = Field(default_factory=new_id)
    task_id: str
    provider: str  # "twilio" / "simulator" ...
    provider_call_id: str | None = None
    direction: CallDirection = CallDirection.OUTBOUND
    to_phone: str
    dial_status: DialStatus
    outcome: CallOutcome
    transcript: Transcript = Field(default_factory=Transcript)
    collected: dict[str, str] = Field(default_factory=dict)  # last CallAction.collected
    questions: list[MidCallQuestion] = Field(default_factory=list)
    answers: list[UserAnswer] = Field(default_factory=list)
    recording_url: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None

    @property
    def duration_s(self) -> float:
        if not self.ended_at or not self.answered_at:
            return 0.0
        return (self.ended_at - self.answered_at).total_seconds()


class OutboundCallRequest(_Model):
    to_phone: str
    task_id: str
    record: bool = True
    ring_timeout_s: int = 30
    max_duration_s: int = 300
    language: Language = Language.HINGLISH
    metadata: dict[str, str] = Field(default_factory=dict)


class AudioClip(_Model):
    data: bytes
    mime: str = "audio/wav"  # "audio/wav", "audio/ogg" (WA voice note), "audio/x-mulaw"
    sample_rate: int = 16000


class Transcription(_Model):
    text: str
    language: Language | None = None
    confidence: float | None = None


# =============================================================================== brain I/O


class ConversationTurn(_Model):
    direction: Direction
    text: str
    at: datetime = Field(default_factory=utcnow)


class ConversationContext(_Model):
    """Snapshot the backend builds for every brain call. Brain does no DB I/O."""

    user: User
    profile: Profile
    now: datetime  # aware UTC (from Clock)
    recent: list[ConversationTurn] = Field(default_factory=list)  # oldest first, ~20
    facts: list[Fact] = Field(default_factory=list)
    open_tasks: list[Task] = Field(default_factory=list)
    pending_question: MidCallQuestion | None = None  # outstanding mid-call question
    known_businesses: list[Business] = Field(default_factory=list)
    autonomy: list[AutonomySetting] = Field(default_factory=list)


class Interpretation(_Model):
    """brain.interpret() output - the backend acts on it, then sends ``reply``."""

    intent: Intent
    reply: str | None = None  # what to say back now (None = engine will report later)
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    task_spec: TaskSpec | None = None  # NEW_TASK / TASK_UPDATE
    task_id: str | None = None  # which open task this refers to
    answer: UserAnswer | None = None  # ANSWER_QUESTION
    facts: list[Fact] = Field(default_factory=list)  # REMEMBER or incidental extraction
    profile_updates: dict[str, Any] = Field(default_factory=dict)  # SETTINGS: Profile fields
    autonomy_updates: list[AutonomySetting] = Field(default_factory=list)
    requires_pin: bool = False  # sensitive action (DELETE_DATA, autonomy level 4...)
    confidence: float = 1.0


class OnboardingTurn(_Model):
    """brain.onboarding_turn() output for the current OnboardingStep."""

    reply: str
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    profile_updates: dict[str, Any] = Field(default_factory=dict)  # name/city/language/tone
    invite_code: str | None = None  # extracted at INVITE_CODE
    consent_given: bool | None = None  # at CONSENT: True only on explicit agreement
    pin: str | None = None  # at PIN: 4 digits as typed; backend hashes, never stores raw
    first_task: TaskSpec | None = None  # at FIRST_TASK
    next_step: OnboardingStep  # brain proposes; backend validates & persists


class NudgeCandidate(_Model):
    """Produced by proactive triggers; judged by brain.judge_nudge()."""

    user_id: str
    kind: NudgeKind
    category: AutonomyCategory
    urgency: Urgency = Urgency.NORMAL
    reason: str  # machine-written context: "appointment at Looks Salon in 2h"
    due_at: datetime  # when it's relevant (UTC)
    task_id: str | None = None
    fact_id: str | None = None
    dedupe_key: str  # one nudge per key, e.g. "reminder:<task_id>"
    data: dict[str, Any] = Field(default_factory=dict)


class NudgeDecision(_Model):
    send: bool
    text: str | None = None  # user-facing copy (must offer an action)
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    template: TemplateRef | None = None  # copy as template params when outside 24h
    proposed_task: TaskSpec | None = None  # action behind the "Yes" button
    reason: str = ""  # why send / not send (logged)


class Nudge(_Model):
    id: str = Field(default_factory=new_id)
    user_id: str
    kind: NudgeKind
    category: AutonomyCategory
    urgency: Urgency = Urgency.NORMAL
    status: NudgeStatus = NudgeStatus.PENDING
    dedupe_key: str
    text: str | None = None
    buttons: list[ReplyButton] = Field(default_factory=list)
    proposed_task: TaskSpec | None = None
    task_id: str | None = None
    fact_id: str | None = None
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class NudgeFeedback(_Model):
    id: str = Field(default_factory=new_id)
    nudge_id: str
    user_id: str
    type: FeedbackType
    at: datetime = Field(default_factory=utcnow)


class AuditEntry(_Model):
    """Full action log (Trust > autonomy). Append-only."""

    id: str = Field(default_factory=new_id)
    user_id: str | None
    actor: Literal["user", "friday", "system", "admin"]
    action: str  # "task.created", "call.placed", "consent.granted", "data.deleted"...
    subject_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)


# Resolve forward refs (Task -> TaskResult).
Task.model_rebuild()
