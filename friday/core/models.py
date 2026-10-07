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
from datetime import date, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from friday.core.clock import at_ist, ensure_utc, to_ist, utcnow


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
    """Spoken/written language. Calls OPEN in Hinglish and then MIRROR the callee.

    EN/HI/HINGLISH are guaranteed in Phase 1; the regional languages are used when
    the configured STT/TTS provider supports them (see ``SUPPORTED_*`` on providers).
    """

    EN = "en"
    HI = "hi"
    HINGLISH = "hinglish"  # code-mixed Hindi+English, Roman or Devanagari
    TA = "ta"  # Tamil
    TE = "te"  # Telugu
    KN = "kn"  # Kannada
    MR = "mr"  # Marathi
    BN = "bn"  # Bengali
    GU = "gu"  # Gujarati
    ML = "ml"  # Malayalam
    PA = "pa"  # Punjabi
    OR = "or"  # Odia

    @property
    def bcp47(self) -> str:
        """Locale tag for STT/TTS vendors (Hinglish -> hi-IN; vendors code-switch)."""
        return {"en": "en-IN", "hinglish": "hi-IN"}.get(self.value, f"{self.value}-IN")


CORE_LANGUAGES: frozenset[Language] = frozenset({Language.EN, Language.HI, Language.HINGLISH})
DEFAULT_CALL_LANGUAGE = Language.HINGLISH

# The ONE fixed line of every call (founder rule #5). Spoken by the voice runner
# itself before the policy's first turn, so it can never be skipped or rephrased.
_DISCLOSURE = {
    Language.EN: "Hi, I'm Friday, an AI assistant calling on behalf of {name}.",
    Language.HI: "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट, {name} की ओर से कॉल कर रही हूँ।",
    Language.HINGLISH: "Hi, main Friday hoon, ek AI assistant, {name} ki taraf se call kar rahi hoon.",
}


def disclosure_line(on_behalf_of: str | None, language: Language = DEFAULT_CALL_LANGUAGE) -> str:
    """Mandatory AI disclosure. Falls back to Hinglish for languages without a template."""
    tpl = _DISCLOSURE.get(language, _DISCLOSURE[Language.HINGLISH])
    return tpl.format(name=on_behalf_of or "my user")


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
    CIRCLE = "circle"  # optional: "Who else do you look after?"
    PLACES = "places"  # optional: "Save your home and office?"
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
    BENEFICIARY_CONTACT = "beneficiary_contact"  # a circle member agreed to hear from Friday


class PersonConsent(StrEnum):
    """Whether Friday may message/call a circle member directly (rule P5)."""

    NOT_ASKED = "not_asked"
    PENDING = "pending"  # one-time opt-in message sent, no reply yet
    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"


class PlaceSource(StrEnum):
    TYPED = "typed"
    VOICE = "voice"
    MAPS_LINK = "maps_link"  # pasted Google Maps URL
    WA_LOCATION = "wa_location"  # WhatsApp location pin
    DIRECTORY = "directory"  # came from a BusinessDirectory result


class TaskType(StrEnum):
    """Every Phase-1 "footwork" job. Behaviour per type comes from DATA - a
    ``BriefTemplate`` (friday/brain/templates/) - never from per-type code branches.
    Brief section refs (A1..A13) in comments.
    """

    BOOKING = "booking"  # core: clinic, salon, restaurant, service provider
    ENQUIRY = "enquiry"  # core + A11: open? price? tutors, coaching, admissions, gyms
    RESCHEDULE = "reschedule"  # A1
    CANCEL_BOOKING = "cancel_booking"  # A1
    RECONFIRM = "reconfirm"  # A2: "is my 7pm table still on?"
    RUNNING_LATE = "running_late"  # A2: notify the business
    ORDER = "order"  # A3: pharmacy / kirana / water cans / tiffin (no payment)
    STOCK_HUNT = "stock_hunt"  # A4: fan-out, stop at first match
    SERVICE_COORDINATION = "service_coordination"  # A5: ETA, chase no-show, arrival, done?
    STATUS_CHASE = "status_chase"  # A6: repair shop, tailor, refund, delivery
    COMPLAINT = "complaint"  # A7: non-IVR local business
    RENTAL_HUNT = "rental_hunt"  # A8: brokers/landlords - rent, deposit, rules, visit slots
    QUOTE = "quote"  # A9: big-ticket quote collection + negotiation; never commits
    HEALTHCARE = "healthcare"  # A10: doctor slots, lab home collection, physio/nurse visits
    RECURRING_BOOKING = "recurring_booking"  # A12: parent; spawns a BOOKING per schedule
    WELLBEING_CHECKIN = "wellbeing_checkin"  # A13: call a circle member (opt-in only)
    CUSTOMER_CARE = "customer_care"  # C21-26: IVR + hold + agent; complaint/refund/ticket...
    HOTEL_BOOKING = "hotel_booking"  # D27-29: API search + reviews -> shortlist -> call
    #                                  properties (rate, hold) -> approval -> confirm -> reconfirm
    DISCOVERY = "discovery"  # generic parent: search -> shortlist -> child calls
    #                          -> comparison -> user picks -> child BOOKING call


class TargetKind(StrEnum):
    BUSINESS = "business"
    PERSON = "person"  # circle member (wellbeing check-in, reminders) - needs opt-in


class FanOutStrategy(StrEnum):
    SINGLE = "single"  # one target
    SEQUENTIAL = "sequential"  # one after another (quotes: each call gets prior quotes)
    PARALLEL = "parallel"  # up to ``concurrency`` at once, aggregate all (B14)
    FIRST_MATCH = "first_match"  # parallel/sequential, cancel the rest on first success (A4)


class CallMode(StrEnum):
    AGENT = "agent"  # Friday converses alone (default)
    WARM_TRANSFER = "warm_transfer"  # B17: reach the right person, then patch the user in
    TRANSLATOR = "translator"  # B18: user + business on one call, Friday translates


class CareRequestKind(StrEnum):
    """What a CUSTOMER_CARE task is about (C21)."""

    COMPLAINT = "complaint"
    REFUND = "refund"
    DISPUTE = "dispute"
    CANCELLATION = "cancellation"
    ESCALATION = "escalation"
    SERVICE_REQUEST = "service_request"
    TICKET_STATUS = "ticket_status"


class EscalationLevel(IntEnum):
    FRONTLINE = 1
    SUPERVISOR = 2
    GRIEVANCE_OFFICER = 3
    NODAL_OFFICER = 4  # appellate / principal nodal officer
    REGULATOR_OMBUDSMAN = 5  # text guidance only (RBI/insurance ombudsman, TRAI, consumer forum)


class AudioClass(StrEnum):
    """What the far end currently sounds like (C23). Produced by an AudioClassifier
    inside real call legs; emitted directly by the simulator."""

    HUMAN = "human"
    IVR_PROMPT = "ivr_prompt"  # "press 1 for..."
    HOLD_MUSIC = "hold_music"
    QUEUE_ANNOUNCEMENT = "queue_announcement"  # "your call is important... wait 5 minutes"
    VOICEMAIL = "voicemail"
    SILENCE = "silence"
    UNKNOWN = "unknown"


class SensitiveKind(StrEnum):
    """Never spoken or keyed by Friday, ever (C24)."""

    OTP = "otp"
    PIN = "pin"
    CVV = "cvv"
    PASSWORD = "password"
    CARD_NUMBER = "card_number"  # full PAN


class HotelBookingMode(StrEnum):
    """No payments in Phase 1 (D28)."""

    PAY_AT_HOTEL = "pay_at_hotel"  # API booking of a pay-at-property rate
    BOOKING_LINK = "booking_link"  # send the user the official booking/payment link
    DIRECT_HOLD = "direct_hold"  # property holds the room by phone against user's own payment


class HotelBookingStatus(StrEnum):
    HELD = "held"  # property holding the room (until hold_until)
    LINK_SENT = "link_sent"
    CONFIRMED = "confirmed"
    RECONFIRMED = "reconfirmed"  # day-before check
    MODIFIED = "modified"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InteractionKind(StrEnum):
    """Vendor memory events (B20)."""

    CALLED = "called"
    QUOTED = "quoted"
    BOOKED = "booked"
    PAID = "paid"  # user-reported price paid (Friday never pays)
    NO_SHOW = "no_show"
    COMPLETED = "completed"  # service done
    RATED = "rated"
    COMPLAINT = "complaint"
    NOTE = "note"


class NumberVerdict(StrEnum):
    TRUSTED = "trusted"  # e.g. multiple consistent listings / used before successfully
    UNKNOWN = "unknown"
    SUSPICIOUS = "suspicious"  # warn the user before calling / sharing details
    SCAM = "scam"  # known scam list -> never call, never share


class ExtractionKind(StrEnum):
    MENU = "menu"
    PRICE_LIST = "price_list"
    QUOTE = "quote"
    BILL = "bill"
    GENERIC = "generic"


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"  # brain is extracting spec / resolving business
    DISCOVERING = "discovering"  # parent: searching directory + shortlisting
    WAITING_CHILDREN = "waiting_children"  # parent: child calls in progress
    AWAITING_CHOICE = "awaiting_choice"  # parent: comparison sent, user must pick
    NEEDS_INFO = "needs_info"  # waiting for the user to fill a missing spec field
    # user must OK something: the call itself (autonomy < 4), or - after a
    # "call back later" approval call - the slot/price; then a follow-up call confirms.
    AWAITING_APPROVAL = "awaiting_approval"
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
    # Offer/slot obtained, business agreed to wait; call ended to get user approval.
    # Task -> AWAITING_APPROVAL; on approval the engine places a confirm call.
    PENDING_APPROVAL = "pending_approval"
    TRANSFERRED = "transferred"  # warm transfer done; user talking to the business
    HOLD_TIMEOUT = "hold_timeout"  # C23: gave up after max hold; retry at a better time
    NEEDS_USER_VERIFICATION = "needs_user_verification"  # C24: user must verify / call back
    FAILED = "failed"  # technical failure
    CANCELLED = "cancelled"

    @property
    def is_retryable(self) -> bool:
        return self in (
            CallOutcome.BUSY,
            CallOutcome.NO_ANSWER,
            CallOutcome.VOICEMAIL,
            CallOutcome.CALLBACK_LATER,
            CallOutcome.HOLD_TIMEOUT,
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
    # speak ``text`` (e.g. "Let me confirm with Rahul, could you hold a moment?"), send
    # ``question`` to the user on WhatsApp, keep the line on HOLD up to
    # brief.approval.hold_timeout_s; the answer (or timeout) comes back as a SYSTEM turn.
    ASK_USER = "ask_user"
    WAIT = "wait"  # say nothing, keep listening (callee checking something)
    PRESS_KEYS = "press_keys"  # DTMF ``digits`` (IVR menu choice / approved identifier)
    # Enter low-cost hold-listening: NO LLM turns until the AudioClassifier hears a
    # HUMAN (or IVR_PROMPT), or ``max_hold_s`` passes (-> HOLD_TIMEOUT).
    WAIT_ON_HOLD = "wait_on_hold"
    # WARM_TRANSFER mode: dial the user into the call (three-way). ``text`` is said to
    # the callee first ("Connecting you to Rahul now"). Runner then leaves if
    # ``leave_after_bridge`` else stays silent/monitoring.
    BRIDGE_USER = "bridge_user"
    HANGUP = "hangup"  # speak text (goodbye) then end the call


class MessageKind(StrEnum):
    TEXT = "text"
    VOICE_NOTE = "voice_note"
    BUTTON_REPLY = "button_reply"
    IMAGE = "image"
    DOCUMENT = "document"  # PDF quotes, menus
    LOCATION = "location"
    CONTACT = "contact"  # shared vCard (business phone!)
    SYSTEM = "system"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class QuestionPurpose(StrEnum):
    CLARIFY = "clarify"  # "Do you want the AC gas refill too?"
    APPROVE_BOOKING = "approve_booking"  # slot/price approval - mandatory before confirming
    CHOOSE_OPTION = "choose_option"  # "4pm or 6pm?"


class ApprovalMode(StrEnum):
    """How the call agent gets the owner's OK before committing to a booking."""

    HOLD_THEN_CALLBACK = "hold_then_callback"  # hold up to N s; if no answer, call back later
    HOLD_ONLY = "hold_only"  # hold up to N s; if no answer, wrap up politely, no callback
    CALLBACK_ONLY = "callback_only"  # never hold; collect offer, end, call back after approval


class Intent(StrEnum):
    NEW_TASK = "new_task"  # "book a haircut at Looks tomorrow 6pm" / "find me an AC guy"
    CHOOSE = "choose"  # picks a business/quote from a comparison
    SAVE_IDENTIFIER = "save_identifier"  # "my Airtel account no is ..." (never OTP/PIN/CVV)
    TASK_UPDATE = "task_update"  # modifies / adds info to an open task
    ANSWER_QUESTION = "answer_question"  # answers an outstanding mid-call/clarifying q
    APPROVE = "approve"  # yes/go-ahead for a pending approval or nudge action
    REJECT = "reject"
    CANCEL_TASK = "cancel_task"
    REMEMBER = "remember"  # "my rent is due on 5th"
    RATE_VENDOR = "rate_vendor"  # "plumber was great, 5 stars" / "he overcharged"
    ADD_PERSON = "add_person"  # "add my dad, +91 98..., lives in Jaipur"
    ADD_PLACE = "add_place"  # "save this as Mom & Dad's home" / location pin / maps link
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
    RECURRING_DUE = "recurring_due"  # "weekly physio tomorrow - book same slot?"
    WELLBEING_ALERT = "wellbeing_alert"  # check-in sounded wrong -> URGENT
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
    FAMILY = "family"  # wellbeing check-ins, nudges about circle members


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
    person_id: str | None = None  # BENEFICIARY_CONTACT: which circle member consented
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


# =============================================================================== people & places


class GeoPoint(_Model):
    lat: float
    lng: float


class Person(_Model):
    """Someone in the user's circle (mom, dad, spouse, friend...). Owned by ONE user.

    ``notes`` are private to the owner: never shown to another person, never sent
    to a business, never used in messages to a different circle member.
    """

    id: str = Field(default_factory=new_id)
    owner_user_id: str
    name: str  # "Ramesh Sharma"
    relation: str | None = None  # free text, normalised lower-case: "father", "mother", "friend"
    aliases: list[str] = Field(default_factory=list)  # "papa", "dad", "pitaji" - learned over time
    phone: str | None = None  # E.164
    language: Language | None = None  # for reminders to them and calls about them
    notes: str | None = None  # PRIVATE: "diabetic, prefers morning appointments"
    contact_consent: PersonConsent = PersonConsent.NOT_ASKED  # messages/reminders to them
    consent_at: datetime | None = None
    checkin_consent: PersonConsent = PersonConsent.NOT_ASKED  # A13 wellbeing CALLS to them
    linked_user_id: str | None = None  # if they later join Friday themselves
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def can_be_contacted(self) -> bool:
        return bool(self.phone) and self.contact_consent == PersonConsent.OPTED_IN


class Place(_Model):
    """A saved, labelled location ("Home", "Office", "Mom & Dad's home")."""

    id: str = Field(default_factory=new_id)
    owner_user_id: str
    label: str
    aliases: list[str] = Field(default_factory=list)  # "PG", "Nani's", "ghar"
    address_text: str | None = None  # as given by the user
    formatted_address: str | None = None  # normalised by the Geocoder
    city: str | None = None
    location: GeoPoint | None = None
    source: PlaceSource = PlaceSource.TYPED
    person_id: str | None = None  # whose place it is (None = the owner's own)
    ephemeral: bool = False  # a one-off "current location" pin, not a saved place
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LocationPin(_Model):
    """WhatsApp location message payload."""

    lat: float
    lng: float
    name: str | None = None
    address: str | None = None


class GeocodeResult(_Model):
    location: GeoPoint
    formatted_address: str
    city: str | None = None
    provider_place_id: str | None = None
    confidence: float = 1.0


class Beneficiary(_Model):
    """Who a task is for. ``person_id`` None == the requester themself."""

    person_id: str | None = None

    @property
    def is_self(self) -> bool:
        return self.person_id is None


class AliasLearning(_Model):
    """'PG' means place X / 'nani' means person Y - learned from conversation."""

    target: Literal["person", "place"]
    target_id: str
    alias: str


class ReferenceResolution(_Model):
    """brain.resolve_references() output for one user utterance."""

    person_id: str | None = None  # resolved beneficiary (None = self / not mentioned)
    place_id: str | None = None  # resolved saved place
    location_text: str | None = None  # unresolved free-text location ("near MG Road")
    ambiguous: bool = False
    clarification: str | None = None  # ask ONCE: "Mom & Dad's Pune home or the Delhi flat?"
    clarification_buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    new_aliases: list[AliasLearning] = Field(default_factory=list)


# =============================================================================== memory


class OpeningPeriod(_Model):
    """One open interval on an IST weekday (0=Mon..6=Sun), 'HH:MM' 24h, close > open."""

    weekday: int = Field(ge=0, le=6)
    open: str  # "10:00"
    close: str  # "13:30"


class BusinessHours(_Model):
    """Weekly opening hours in IST (B19). Lunch breaks = two periods on a day."""

    periods: list[OpeningPeriod] = Field(default_factory=list)
    source: str | None = None  # "google_places" / "learned_on_call" / "user"
    notes: str | None = None  # "closed 2nd Sunday"

    @staticmethod
    def _minutes(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    def is_open(self, when: datetime) -> bool | None:
        """None if hours unknown (no periods)."""
        if not self.periods:
            return None
        local = to_ist(when)
        mins = local.hour * 60 + local.minute
        return any(
            p.weekday == local.weekday()
            and self._minutes(p.open) <= mins < self._minutes(p.close)
            for p in self.periods
        )

    def next_open(self, when: datetime, *, margin_min: int = 0) -> datetime | None:
        """Earliest UTC instant >= ``when`` at which the business is open (and stays
        open for ``margin_min``). None if hours unknown."""
        if not self.periods:
            return None
        local = to_ist(when)
        for day in range(8):
            d = local.date() + timedelta(days=day)
            for p in sorted(
                (p for p in self.periods if p.weekday == d.weekday()),
                key=lambda p: self._minutes(p.open),
            ):
                start = at_ist(d, *divmod(self._minutes(p.open), 60))
                end = at_ist(d, *divmod(self._minutes(p.close), 60)) - timedelta(minutes=margin_min)
                candidate = max(start, ensure_utc(when))
                if candidate < end:
                    return candidate
        return None


class Business(_Model):
    """A business Friday has dealt with or found. Shared across users (B2B groundwork);
    per-user history lives in VendorInteraction."""

    id: str = Field(default_factory=new_id)
    name: str
    phone: str  # E.164
    whatsapp_phone: str | None = None  # B15: if reachable on WhatsApp
    category: str | None = None  # "salon", "clinic", "restaurant", "plumber"...
    city: str | None = None
    address: str | None = None
    location: GeoPoint | None = None
    hours: BusinessHours | None = None  # B19
    best_call_times: list[str] = Field(default_factory=list)  # learned: "after 11am", "not 1-3pm"
    notes: str | None = None  # "closed Tuesdays", "ask for Ramesh"
    language_hint: Language | None = None
    directory_provider: str | None = None
    directory_place_id: str | None = None
    rating: float | None = None  # public rating from directory
    review_count: int | None = None
    verification: NumberVerdict | None = None  # last NumberVerifier verdict
    is_customer_care: bool = False  # large company care line (C21)
    ivr_notes: list[str] = Field(default_factory=list)  # learned: "2 -> 9 reaches an agent"
    created_by_user_id: str | None = None
    last_called_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class VendorInteraction(_Model):
    """Vendor memory (B20): one event between a user and a business."""

    id: str = Field(default_factory=new_id)
    user_id: str
    business_id: str
    kind: InteractionKind
    task_id: str | None = None
    call_id: str | None = None
    amount_inr: int | None = None  # quoted / paid
    rating: int | None = Field(default=None, ge=1, le=5)  # user's rating
    outcome: str | None = None  # "on time", "no-show", "overcharged"
    note: str | None = None
    at: datetime = Field(default_factory=utcnow)


class ContactTarget(_Model):
    """Who a call/message goes to: a business OR a circle member."""

    kind: TargetKind
    name: str
    phone: str  # E.164
    business_id: str | None = None
    person_id: str | None = None
    language_hint: Language | None = None


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
    person_id: str | None = None  # fact about a circle member ("Dad's BP check due")
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
    location: LocationPin | None = None  # for LOCATION: WhatsApp pin
    # Set by backend when the sender is a known business (B15 WhatsApp-to-business
    # replies: menus, price lists, quote photos) or a circle member.
    business_id: str | None = None
    person_id: str | None = None
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
    business_id: str | None = None  # recipient is a business (B15)
    # Set when the recipient is a circle member (not the user). The backend
    # notifier MUST refuse unless Person.contact_consent == OPTED_IN (except the
    # one-time opt-in request itself, which is a template).
    person_id: str | None = None


class SendReceipt(_Model):
    message_id: str  # our OutboundMessage.id
    provider_message_id: str | None = None
    ok: bool = True
    error: str | None = None
    sent_at: datetime = Field(default_factory=utcnow)


# =============================================================================== money & quotes


class Budget(_Model):
    """User's limits. Amounts in whole rupees. Friday NEVER pays or commits money."""

    max_inr: int | None = None  # hard ceiling - never accept above this
    target_inr: int | None = None  # what we'd like to pay
    notes: str | None = None  # "including parts", "per person"


class NegotiationPolicy(_Model):
    enabled: bool = True
    # tactics the call agent may use; brain prompt enforces, QA tests
    may_ask_discount: bool = True
    may_cite_competing_quotes: bool = True  # "another shop quoted ₹1,800"
    may_ask_package_deal: bool = True
    max_rounds: int = 2  # discount asks per call before accepting best offer
    walk_away_above_inr: int | None = None  # defaults to Budget.max_inr


class Quote(_Model):
    """Structured price offer captured on a call."""

    business_id: str | None = None
    business_name: str
    amount_inr: int | None = None  # final (post-negotiation) price, if numeric
    original_amount_inr: int | None = None  # first price quoted, before negotiation
    price_text: str  # verbatim-ish: "₹1,500 + ₹300 visiting charge"
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    validity: str | None = None  # "valid till Sunday", "today only"
    available_slots: list[str] = Field(default_factory=list)  # "Sat 4pm", "Sun 11am"
    notes: str | None = None
    within_budget: bool | None = None
    call_id: str | None = None
    task_id: str | None = None

    @property
    def negotiated(self) -> bool:
        return (
            self.amount_inr is not None
            and self.original_amount_inr is not None
            and self.amount_inr < self.original_amount_inr
        )


# =============================================================================== discovery


class BusinessCandidate(_Model):
    """A business found via a BusinessDirectory (Google Places / simulator)."""

    provider: str  # "google_places" / "simulator"
    place_id: str  # provider's stable id
    name: str
    phone: str | None = None  # E.164; candidates without a phone can't be called
    category: str | None = None
    address: str | None = None
    location: GeoPoint | None = None
    distance_km: float | None = None
    rating: float | None = None  # 0-5
    review_count: int = 0
    review_snippets: list[str] = Field(default_factory=list)  # a few recent/relevant reviews
    maps_url: str | None = None
    open_now: bool | None = None
    price_level: int | None = None  # 0-4 if provider has it


class ShortlistItem(_Model):
    candidate: BusinessCandidate
    rank: int  # 1 = best
    reason: str  # short, user-facing: "4.7★ (320 reviews), people praise quick visits"


class QuoteComparison(_Model):
    """brain.compare_quotes() output, sent to the user to pick from."""

    summary: str  # user-facing comparison text
    ranked_quotes: list[Quote] = Field(default_factory=list)  # best first
    recommended_index: int | None = None  # into ranked_quotes
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)


class PriceItem(_Model):
    name: str
    amount_inr: int | None = None
    price_text: str | None = None
    unit: str | None = None  # "per plate", "per visit"


class ExtractedDocument(_Model):
    """DocumentExtractor output for a menu / price list / quote image or PDF."""

    kind: ExtractionKind
    text: str  # faithful transcription (OCR-ish)
    items: list[PriceItem] = Field(default_factory=list)
    quote: Quote | None = None
    business_name: str | None = None
    confidence: float = 1.0


class NumberCheck(_Model):
    """NumberVerifier output (B16)."""

    phone: str
    verdict: NumberVerdict
    score: float = 0.5  # 0 = surely scam, 1 = surely genuine
    signals: list[str] = Field(default_factory=list)  # "3 consistent listings", "on scam list"
    warn_user: bool = False
    checked_at: datetime = Field(default_factory=utcnow)


class OfficialNumber(_Model):
    """Curated, verified customer-care number (C26)."""

    company: str  # "Airtel"
    phone: str  # E.164 or toll-free as dialable string
    purpose: str | None = None  # "prepaid", "broadband", "credit card", "grievance"
    region: str | None = None
    source: str  # "company website (verified 2026-09)"
    verified_at: date | None = None


_SECRET_LABEL = re.compile(r"\b(otp|cvv|cvc|m?pin|password|passcode|passwd)\b", re.I)


class AccountIdentifier(_Model):
    """A user-saved identifier Friday MAY share on a care call, only if approved for
    that task (C22/C24): registered mobile, account/consumer no., order id, policy no.
    OTP/PIN/CVV/passwords can never be stored here."""

    id: str = Field(default_factory=new_id)
    user_id: str
    company: str | None = None
    label: str  # "Airtel broadband account number"
    value: str  # SENSITIVE: never logged; encrypted at rest by the repository

    @field_validator("label")
    @classmethod
    def _never_secrets(cls, v: str) -> str:
        if _SECRET_LABEL.search(v):
            raise ValueError("OTPs, PINs, CVVs and passwords can never be saved")
        return v

    @property
    def masked(self) -> str:
        return ("•" * max(0, len(self.value) - 4)) + self.value[-4:]


class CareOutcome(_Model):
    """Structured result of a customer-care call (C25)."""

    company: str | None = None
    request_kind: CareRequestKind | None = None
    ticket_number: str | None = None
    agent_name: str | None = None
    promised_date: date | None = None  # IST date; auto follow-up when it passes
    promised_text: str | None = None  # "within 48 hours"
    escalation_level: EscalationLevel = EscalationLevel.FRONTLINE
    resolved: bool = False
    hold_seconds: int = 0
    ivr_path: list[str] = Field(default_factory=list)  # keys pressed / options spoken
    escalation_guidance: str | None = None  # text-only formal routes (ombudsman, etc.)


class StayRequest(_Model):
    """What the user wants for a hotel/homestay/guesthouse (D27)."""

    destination: str  # "Udaipur", "near Mom & Dad's home, Pune"
    near: GeoPoint | None = None
    check_in: date
    check_out: date
    adults: int = 2
    children: int = 0
    rooms: int = 1
    max_rate_per_night_inr: int | None = None
    property_types: list[str] = Field(default_factory=list)  # "hotel", "homestay", "guesthouse"
    preferences: list[str] = Field(default_factory=list)  # "breakfast", "early check-in", "lake view"
    guest_person_id: str | None = None  # booking for a circle member

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class HotelProperty(_Model):
    provider: str  # "expedia_rapid" / "simulator"
    property_id: str
    name: str
    phone: str | None = None  # E.164 - needed for the direct call
    address: str | None = None
    location: GeoPoint | None = None
    star_rating: float | None = None
    guest_rating: float | None = None  # provider's, 0-5 normalised
    review_count: int = 0
    review_snippets: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    maps_url: str | None = None


class HotelOffer(_Model):
    property: HotelProperty
    room_type: str
    rate_per_night_inr: int | None = None
    total_inr: int | None = None
    pay_at_hotel: bool = False
    refundable: bool | None = None
    inclusions: list[str] = Field(default_factory=list)  # "breakfast"
    cancellation_policy: str | None = None
    booking_link: str | None = None  # official link (BOOKING_LINK mode)
    offer_token: str | None = None  # provider rate/room token for book()


class GuestDetails(_Model):
    """Minimum guest info shared with the hotel/provider."""

    name: str
    phone: str | None = None
    email: str | None = None


class HotelBooking(_Model):
    id: str = Field(default_factory=new_id)
    task_id: str | None = None
    provider: str  # "expedia_rapid" / "direct_call" / "simulator"
    mode: HotelBookingMode
    status: HotelBookingStatus
    property: HotelProperty
    room_type: str | None = None
    check_in: date
    check_out: date
    guests: int = 2
    total_inr: int | None = None
    confirmation_ref: str | None = None  # itinerary id / hotel's booking number
    booking_link: str | None = None
    hold_until: datetime | None = None
    guest_name: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class MediaBlob(_Model):
    """Downloaded media (voice note, image, PDF)."""

    data: bytes
    mime: str
    filename: str | None = None


# =============================================================================== tasks


class FanOutPolicy(_Model):
    """How a parent task spreads over several targets (B14, A4, A9)."""

    strategy: FanOutStrategy = FanOutStrategy.SINGLE
    concurrency: int = 3  # PARALLEL / FIRST_MATCH
    max_targets: int = 5


class RecurrenceRule(_Model):
    """A12 recurring bookings / A13 daily check-ins. Times are IST wall-clock."""

    freq: Recurrence  # WEEKLY / MONTHLY / YEARLY (DAILY via interval_days)
    interval: int = 1  # every N freq units
    interval_days: int | None = None  # overrides freq: every N days (1 = daily)
    weekdays: list[int] = Field(default_factory=list)  # 0=Mon (WEEKLY)
    day_of_month: int | None = None  # MONTHLY
    time_ist: str = "10:00"  # "HH:MM" when to run / place the call
    lead_days: int = 0  # book this many days before the occurrence
    until: date | None = None
    next_run_at: datetime | None = None  # UTC, maintained by the task engine


class BriefTemplate(_Model):
    """Data, not code: how a TaskType becomes calls. Shipped as files in
    friday/brain/templates/ (AI Engineer); the brain applies it in build_call_brief
    and when planning (fills TaskSpec.fan_out etc.)."""

    task_type: TaskType
    goal_template: str  # "Book {what} for {beneficiary} {when} at {target}"
    required_fields: list[str] = Field(default_factory=list)  # spec fields before calling
    default_questions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    target_kind: TargetKind = TargetKind.BUSINESS
    fan_out: FanOutPolicy = Field(default_factory=FanOutPolicy)
    call_mode: CallMode = CallMode.AGENT
    needs_approval_to_commit: bool = True  # bookings/orders: always True
    may_negotiate: bool = False
    follow_up_after_h: int | None = None  # A5 "did the plumber come?"
    safety_rules: list[str] = Field(default_factory=list)  # e.g. "never give medical advice"


class TaskSpec(_Model):
    """What the user wants done - extracted by the brain, refined via clarifications."""

    type: TaskType
    goal: str  # one line, e.g. "Book a haircut for Rahul tomorrow 6-8pm"
    business_name: str | None = None
    business_phone: str | None = None  # E.164; required before CALLING
    business_id: str | None = None
    category: str | None = None  # salon / clinic / restaurant / plumber...
    reference: str | None = None  # existing booking/order/ticket ref (A1/A2/A6/C25)
    company: str | None = None  # CUSTOMER_CARE: "Airtel", "HDFC Bank"
    care_request: CareRequestKind | None = None
    # AccountIdentifier ids the user approved for THIS task (C24). Nothing else is shared.
    approved_identifier_ids: list[str] = Field(default_factory=list)
    item: str | None = None  # A3/A4: "Dolo 650 x 2 strips"
    fan_out: FanOutPolicy | None = None  # None -> template default
    call_mode: CallMode = CallMode.AGENT
    recurrence: RecurrenceRule | None = None  # A12 / A13
    stay: StayRequest | None = None  # HOTEL_BOOKING
    # discovery (TaskType.DISCOVERY or no business named)
    discovery_query: str | None = None  # "AC repair"
    location_text: str | None = None  # "near Indiranagar, Bangalore"
    shortlist_size: int = 3
    budget: Budget | None = None
    negotiation: NegotiationPolicy = Field(default_factory=NegotiationPolicy)
    preferred_times: list[str] = Field(default_factory=list)  # "Sat morning", "after 6pm"
    when_text: str | None = None  # user's words: "tomorrow evening"
    window_start: datetime | None = None  # resolved UTC window, if any
    window_end: datetime | None = None
    party_size: int | None = None
    questions: list[str] = Field(default_factory=list)  # for enquiries: what to ask
    constraints: list[str] = Field(default_factory=list)  # "female doctor", "under 500"
    # decisions Friday may take alone on the call; anything else -> ASK_USER
    allowed_decisions: list[str] = Field(default_factory=list)
    on_behalf_of: str | None = None  # name used in the AI disclosure
    call_language: Language = Language.HINGLISH  # OPENING language; mirrored after that
    notes: str | None = None
    missing: list[str] = Field(default_factory=list)  # fields the brain still needs

    @property
    def is_ready_to_call(self) -> bool:
        return bool(self.business_phone) and not self.missing

    @property
    def needs_discovery(self) -> bool:
        return self.type in (TaskType.DISCOVERY, TaskType.STOCK_HUNT) or (
            not self.business_phone and bool(self.discovery_query)
        )


class Task(_Model):
    id: str = Field(default_factory=new_id)
    requester_user_id: str  # the Friday user who asked (and approves)
    beneficiary: Beneficiary = Field(default_factory=Beneficiary)  # who it's for
    place_id: str | None = None  # where (home visit address / "near" anchor)
    type: TaskType
    status: TaskStatus = TaskStatus.CREATED
    spec: TaskSpec
    target: ContactTarget | None = None  # resolved who-to-call (business or person)
    attempts: int = 0
    max_attempts: int = 3
    next_attempt_at: datetime | None = None  # queued/scheduled dial time (business-hours aware)
    last_outcome: CallOutcome | None = None
    result: TaskResult | None = None
    # multi-call: parent (DISCOVERY/STOCK_HUNT/QUOTE/RECURRING_BOOKING...) -> children
    parent_task_id: str | None = None
    recurrence: RecurrenceRule | None = None  # parent of recurring children
    candidate: BusinessCandidate | None = None  # child: which shortlisted business
    shortlist: list[ShortlistItem] = Field(default_factory=list)  # parent
    approved_terms: str | None = None  # user-approved slot/price for a confirm call
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
    quotes: list[Quote] = Field(default_factory=list)
    comparison: QuoteComparison | None = None  # DISCOVERY parent
    needs_approval: MidCallQuestion | None = None  # PENDING_APPROVAL: what to ask the user
    alert: str | None = None  # A13: something sounded wrong -> URGENT nudge to the user
    care: CareOutcome | None = None  # C25: ticket, promised date -> follow_up_at
    hotel_offers: list[HotelOffer] = Field(default_factory=list)  # D27 API search results
    hotel_booking: HotelBooking | None = None  # D28 (held/confirmed/link)
    extracted: list[ExtractedDocument] = Field(default_factory=list)  # B15 menus/quotes
    interactions: list[VendorInteraction] = Field(default_factory=list)  # B20 to persist
    facts: list[Fact] = Field(default_factory=list)  # e.g. business notes learned
    business_touch: TemplateRef | None = None  # end-of-call SMS/WA to the business


# =============================================================================== calls


class CallTurn(_Model):
    speaker: Speaker
    text: str
    at: datetime = Field(default_factory=utcnow)
    language: Language | None = None  # detected (CALLEE) / spoken (FRIDAY)
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
    purpose: QuestionPurpose = QuestionPurpose.CLARIFY
    options: list[str] = Field(default_factory=list, max_length=3)  # become reply buttons
    allow_free_text: bool = True
    timeout_s: int = 90
    asked_at: datetime = Field(default_factory=utcnow)


class UserAnswer(_Model):
    question_id: str
    text: str  # chosen option title or free text
    option_index: int | None = None
    # brain/backend set True when this answers an APPROVE_BOOKING question positively
    approves: bool = False
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
    quote: Quote | None = None  # latest/best quote captured so far
    # True if ``text`` confirms a booking/commitment to the business. The runner
    # refuses such an action unless the brief allows it (brief.can_commit(answers)).
    commits_booking: bool = False
    leave_after_bridge: bool = True  # BRIDGE_USER
    max_hold_s: int | None = None  # WAIT_ON_HOLD (None -> brief.max_hold_s)
    care: CareOutcome | None = None  # latest care details captured (ticket no, agent...)
    user_update: str | None = None  # progress note for the user ("on hold, ~8 min wait")


class ApprovalPolicy(_Model):
    """Book only after asking the owner (founder rule #3). Not optional."""

    mode: ApprovalMode = ApprovalMode.HOLD_THEN_CALLBACK
    hold_timeout_s: int = 90  # how long the business may be kept on hold
    # Free-form rules the brain must follow, e.g. "price above ₹2000 needs approval".
    rules: list[str] = Field(default_factory=list)


class CallBrief(_Model):
    """Goal-driven call instructions (founder rule #6). Built by the task engine
    (via brain.build_call_brief), consumed by the CallPolicy each turn. No scripts.
    """

    task_id: str
    requester_user_id: str
    task_type: TaskType
    goal: str  # "Get a quote for AC servicing (2 split ACs) and a Sat slot"
    target: ContactTarget  # who we dial (business or circle member)
    business: Business | None = None  # when target.kind == BUSINESS and known
    mode: CallMode = CallMode.AGENT
    template: BriefTemplate | None = None  # success criteria, safety rules
    on_behalf_of: str  # requester's name for the disclosure
    # Who the booking is for, if not the requester ("Ramesh Sharma", "father").
    beneficiary_name: str | None = None
    beneficiary_relation: str | None = None
    # The ONLY personal details the agent may share with the business (minimum
    # needed): e.g. {"patient name": "Ramesh Sharma", "visit address": "..."}.
    # Never includes private Person.notes unless the user explicitly allowed it.
    shareable_details: dict[str, str] = Field(default_factory=dict)
    location_context: str | None = None  # "near Mom & Dad's home, Kothrud, Pune"
    opening_language: Language = DEFAULT_CALL_LANGUAGE
    user_language: Language = Language.HINGLISH  # for mid-call questions to the user
    constraints: list[str] = Field(default_factory=list)
    preferred_times: list[str] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    party_size: int | None = None
    questions: list[str] = Field(default_factory=list)  # things to find out
    budget: Budget | None = None
    negotiation: NegotiationPolicy = Field(default_factory=NegotiationPolicy)
    competing_quotes: list[Quote] = Field(default_factory=list)  # leverage from sibling calls
    vendor_history: list[str] = Field(default_factory=list)  # "charged ₹400 last time (Mar)"
    user_context: list[str] = Field(default_factory=list)  # relevant facts, e.g. "has 2 split ACs"
    allowed_disclosures: list[str] = Field(default_factory=list)  # "first name", "area"
    forbidden_disclosures: list[str] = Field(
        default_factory=lambda: ["user's phone number", "home address", "payment details"]
    )
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    # Set on a follow-up confirm call: the slot/price the user already approved.
    approved_terms: str | None = None
    user_phone: str | None = None  # BRIDGE_USER / TRANSLATOR: who to bridge in (never spoken)
    # Customer care (C21-26)
    company: str | None = None
    care_request: CareRequestKind | None = None
    reference: str | None = None  # existing ticket / order id
    approved_identifiers: list[AccountIdentifier] = Field(default_factory=list)  # may share
    ivr_notes: list[str] = Field(default_factory=list)  # known menu paths
    max_hold_s: int = 1500
    prefer_human_agent: bool = True
    # Hotel direct call (D27): availability, room type, inclusions, direct rate, hold.
    stay: StayRequest | None = None
    api_offer: HotelOffer | None = None  # online rate to beat when negotiating
    attempt: int = 1
    max_duration_s: int = 300

    def disclosure(self, language: Language | None = None) -> str:
        return disclosure_line(self.on_behalf_of, language or self.opening_language)

    def can_commit(self, answers: list[UserAnswer]) -> bool:
        """Booking may be confirmed only with prior user approval."""
        return bool(self.approved_terms) or any(a.approves for a in answers)


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
    quotes: list[Quote] = Field(default_factory=list)
    questions: list[MidCallQuestion] = Field(default_factory=list)
    answers: list[UserAnswer] = Field(default_factory=list)
    languages_heard: list[Language] = Field(default_factory=list)  # callee, in order of switch
    care: CareOutcome | None = None
    hold_seconds: int = 0  # time spent in hold-listening mode (no LLM cost)
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
    language: Language = DEFAULT_CALL_LANGUAGE  # opening language (STT hint)
    metadata: dict[str, str] = Field(default_factory=dict)


class AudioClip(_Model):
    data: bytes
    mime: str = "audio/wav"  # "audio/wav", "audio/ogg" (WA voice note), "audio/x-mulaw"
    sample_rate: int = 16000


class Transcription(_Model):
    """STT output. ``language`` is the DETECTED language of this utterance - it
    drives language mirroring (founder rule #1), so providers must fill it."""

    text: str
    language: Language | None = None
    confidence: float | None = None
    is_final: bool = True
    # What the far end sounded like for this chunk (C23). Hold music/queue chunks may
    # have empty ``text`` (or the announcement text).
    audio_class: AudioClass = AudioClass.HUMAN


class AudioClassification(_Model):
    audio_class: AudioClass
    confidence: float = 1.0


class VoiceProfile(_Model):
    """Which TTS voice to use. Calm, clean, polished - no fillers/breaths (rule #5)."""

    provider: str  # "sarvam" / "elevenlabs" / "fake"
    voice_id: str
    language: Language
    speaking_rate: float = 1.0
    style: str = "calm"


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
    vendor_history: list[VendorInteraction] = Field(default_factory=list)  # B20
    people: list[Person] = Field(default_factory=list)  # owner's circle
    places: list[Place] = Field(default_factory=list)  # owner's saved places
    autonomy: list[AutonomySetting] = Field(default_factory=list)


class Interpretation(_Model):
    """brain.interpret() output - the backend acts on it, then sends ``reply``."""

    intent: Intent
    reply: str | None = None  # what to say back now (None = engine will report later)
    buttons: list[ReplyButton] = Field(default_factory=list, max_length=3)
    task_spec: TaskSpec | None = None  # NEW_TASK / TASK_UPDATE
    task_id: str | None = None  # which open task this refers to
    resolution: ReferenceResolution | None = None  # who/where (from resolve_references)
    person_upsert: Person | None = None  # ADD_PERSON (or edits)
    place_upsert: Place | None = None  # ADD_PLACE (address still to geocode)
    identifier_upsert: AccountIdentifier | None = None  # SAVE_IDENTIFIER
    vendor_interactions: list[VendorInteraction] = Field(default_factory=list)  # RATE_VENDOR
    answer: UserAnswer | None = None  # ANSWER_QUESTION
    facts: list[Fact] = Field(default_factory=list)  # REMEMBER or incidental extraction
    choice_index: int | None = None  # CHOOSE: index into the comparison/shortlist
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
    people: list[Person] = Field(default_factory=list)  # at CIRCLE
    places: list[Place] = Field(default_factory=list)  # at PLACES (backend geocodes)
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
    person_id: str | None = None  # nudge ABOUT a circle member ("Dad's BP check")
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
    person_id: str | None = None  # about whom
    recipient_person_id: str | None = None  # sent TO a circle member (needs opt-in)
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
