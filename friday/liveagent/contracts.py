"""Small pydantic models the live engine consumes and produces.

W1 (package ``friday/calls``) builds the real ``CallBrief`` and consumes ``CallOutcome``. Until it
lands these stand-ins carry exactly the W1 field names (goal, must_say, must_not_say, ask_list,
limits, tone, relationship, shareable_facts, private_facts, language; status, summary,
commitments, needs_user_approval, next_actions) so the lead can unify them at merge time. Fields
marked EXTRA are additions W2 needs; W1 should provide them (see docs/LIVE_AGENT.md section 8).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CalleeKind(StrEnum):
    """Who is being called. Drives the move set, the register of the fixed lines and the risk."""

    FAMILY_ELDER = "family_elder"  # parent, grandparent, any elder (slower, extra respectful)
    FRIEND = "friend"  # friend or peer family member (warmer, casual)
    PROVIDER = "provider"  # plumber, driver, cook, tutor, landlord
    CUSTOMER_CARE = "customer_care"  # telecom, bank, utility, courier (IVR, hold, authentication)
    OFFICIAL = "official"  # school, RWA, society office, clinic desk, help desk
    UNKNOWN = "unknown"  # seller on an ad, a number from a message
    BUSINESS = "business"  # shop, salon, restaurant (usually the approved playbooks instead)


class CallLanguage(StrEnum):
    HINGLISH = "hinglish"  # Roman Hindi+English (the default voice)
    HI = "hi"  # Hindi in Devanagari
    EN = "en"  # English


class Limits(BaseModel):
    """What Friday may agree to without asking the user. Anything outside -> needs_user_approval."""

    max_amount_inr: int | None = None  # CONFIDENTIAL: never spoken
    allowed_times: list[str] = Field(default_factory=list)  # times Friday may accept, as words
    # kinds of commitment that may be accepted: "time", "visit", "callback", "booking". Friday
    # never agrees to "payment": the user pays, Friday never does.
    allowed_commitments: list[str] = Field(default_factory=list)
    max_call_seconds: int = 300
    max_hold_seconds: int = 120


class CallBrief(BaseModel):
    goal: str
    must_say: list[str] = Field(default_factory=list)  # delivered verbatim, one by one
    must_not_say: list[str] = Field(default_factory=list)  # phrases/topics that must never appear
    ask_list: list[str] = Field(default_factory=list)  # questions to ask, in order
    limits: Limits = Field(default_factory=Limits)
    tone: str = "warm"  # warm | formal | casual | brief
    relationship: CalleeKind = CalleeKind.UNKNOWN
    shareable_facts: dict[str, str] = Field(default_factory=dict)  # may be told to the callee
    private_facts: dict[str, str] = Field(default_factory=dict)  # NEVER spoken
    language: CallLanguage = CallLanguage.HINGLISH
    # --- EXTRA (W2 needs them; W1 should fill them) ---
    user_name: str = "user"  # how the callee knows the user ("Himanshu", "Rohan bhaiya")
    goal_spoken: str | None = None  # one short sentence in the call language, shown for approval
    callee_name: str | None = None  # how to address the callee ("Mummy", "Sharma ji")
    voicemail_allowed: bool = False  # may the fixed short voicemail message be left?
    user_phone_hint: str | None = None  # never spoken; for the warm-transfer hook only


class Callee(BaseModel):
    kind: CalleeKind
    name: str | None = None
    number: str | None = None  # never logged unmasked


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"  # goal met (asks answered, messages delivered)
    PARTIAL = "partial"  # some of it done
    NEEDS_USER_APPROVAL = "needs_user_approval"  # something needs the user's yes first
    CALL_BACK_LATER = "call_back_later"  # callee was busy; asked to call at a time
    DECLINED = "declined"  # callee declined to engage
    VOICEMAIL_LEFT = "voicemail_left"
    VOICEMAIL_NO_MESSAGE = "voicemail_no_message"  # reached a mailbox; the brief did not allow it
    UNREACHABLE = "unreachable"  # carrier message: switched off, not reachable
    WRONG_NUMBER = "wrong_number"  # apologised; mark the number
    DO_NOT_CALL = "do_not_call"  # callee asked not to be called (or not to talk to bots)
    DISTRESS = "distress"  # callee sounded distressed: tell the user at once
    HOSTILE = "hostile"  # abuse: ended politely
    UNRESOLVED = "unresolved"  # escalated to a polite end (loop, silence, IVR dead end)
    CUT_OFF = "cut_off"  # max duration / turns reached
    DROPPED = "dropped"  # the line dropped


class Commitment(BaseModel):
    """Something Friday agreed to ON the call, inside the brief limits."""

    kind: str  # time | visit | callback | booking
    text: str  # in the callee's own words
    within_limits: bool = True


class ApprovalRequest(BaseModel):
    """Something the callee asked for that Friday may not agree to alone."""

    kind: str  # payment | time | visit | booking | personal_detail | question | other
    text: str  # what was asked, in the callee's words
    reason: str  # why it needs the user


class CallOutcome(BaseModel):
    status: OutcomeStatus
    summary: str
    commitments: list[Commitment] = Field(default_factory=list)
    needs_user_approval: list[ApprovalRequest] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    speaker: str  # "friday" | "callee" | "system"
    text: str  # numbers already masked
    move: str | None = None
    t: float = 0.0  # seconds since the call started


class EngineEvent(BaseModel):
    """One line of the audit trail: what was understood, which move, which guard fired."""

    t: float
    kind: str  # understood | move | guard | hard_stop | ivr | hold | policy_rejected | ...
    detail: str
    data: dict[str, str | float | int | bool | None] = Field(default_factory=dict)


class LiveCallResult(BaseModel):
    outcome: CallOutcome
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    events: list[EngineEvent] = Field(default_factory=list)
    duration_s: float = 0.0
    friday_lines: list[str] = Field(default_factory=list)  # unmasked spoken lines, for the guards
    pending_line_ids: list[str] = Field(default_factory=list)  # lines used (founder review)
