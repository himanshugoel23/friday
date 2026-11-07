# ruff: noqa: E501
"""Data of the Robin family core. Nothing here talks to a network.

Personal data (phones, names, the safe-word hash, medicine names, check-in answers) is only ever stored
inside encrypted JSON columns (store.py); the indexed columns hold ids, states and times.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from friday.core.models import new_id


class Role(StrEnum):
    """Founder roles: ADMIN = CHILD (pays, configures what Robin does), CO_ADMIN = a sibling with the same
    rights, USER = PARENT, CONTACT = SECOND_CONTACT (receives alerts only). Stored values are kept stable."""

    PARENT = "parent"
    CHILD = "child"
    CO_ADMIN = "co_admin"
    SECOND_CONTACT = "second_contact"


class Tier(StrEnum):
    INFO = "info"
    WATCH = "watch"
    HIGH = "high"
    EMERGENCY = "emergency"


TIER_ORDER = {Tier.INFO: 0, Tier.WATCH: 1, Tier.HIGH: 2, Tier.EMERGENCY: 3}


def parse_tier(value: object, default: Tier = Tier.HIGH) -> tuple[Tier, bool]:
    """Tolerant tier parser for the device/family seam. Case and spaces are ignored ('HIGH', ' emergency ').
    Returns ``(tier, recognised)``; anything unknown yields ``default`` (HIGH: a garbled tier is never lowered)."""
    if isinstance(value, Tier):
        return value, True
    try:
        return Tier(str(value).strip().lower()), True
    except ValueError:
        return default, False


# Scenarios the family package treats specially. The device package sends 'SOS' / 'THREAT'; the family engine tests the lowercase ids.
_SPECIAL_SCENARIOS = ("sos", "threat", "checkin_unanswered")


def normalise_scenario(value: object) -> str:
    """'SOS' -> 'sos', 'THREAT' -> 'threat'; every other id (S1..S8, SHARE, ...) is kept as sent, only trimmed."""
    text = str(value or "").strip()
    return text.lower() if text.lower() in _SPECIAL_SCENARIOS else text


class Sensitivity(StrEnum):
    CALM = "calm"
    BALANCED = "balanced"
    CAREFUL = "careful"


class FamilyStatus(StrEnum):
    ONBOARDING = "onboarding"  # set up by the child, the parent has not consented yet
    ACTIVE = "active"
    PAUSED = "paused"  # the PARENT paused Robin (voice or app)
    DELETED = "deleted"


class ConsentItem(StrEnum):
    DAILY_CHECKIN_CALLS = "daily_checkin_calls"
    MEDICINE_REMINDERS = "medicine_reminders"
    SCAM_CHECK = "scam_check"
    DEVICE_SIGNALS = "device_signals"
    PAYMENT_ALERTS = "payment_alerts"
    LOCATION = "location"
    AUTHORITY_CALLS = "authority_calls"  # Robin may place the policy-gated AUTHORITY call (112 / 1930) in a confirmed emergency; DRY-RUN unless switched live
    CALL_LISTENING = "call_listening"  # Robin on a call routed through its own line (screen-first / listen-in); recording is NOT built
    SHARE_SUMMARY_WITH_CHILD = "share_summary_with_child"


CONSENT_ITEMS = tuple(i.value for i in ConsentItem)
# FOUNDER (final, 2026-11-04): ALL consent is given by the CHILD (admin) on the parent's behalf (basis 'admin_on_behalf', recorded
# with who, when and how). The parent is NOTIFIED, not asked, and can stop everything at any time; only the PARENT can resume the
# sensitive items after a stop. LEGAL REVIEW FLAG: DPDP has no verified route for a child consenting for a non-disabled adult parent.
SENSITIVE_ITEMS = frozenset({"device_signals", "payment_alerts", "location", "call_listening", "authority_calls"})
# the consent call asks for these; the rest (device_signals, payment_alerts, location) come from the Android app
VOICE_CONSENT_ITEMS = (
    ConsentItem.DAILY_CHECKIN_CALLS,
    ConsentItem.MEDICINE_REMINDERS,
    ConsentItem.SCAM_CHECK,
    ConsentItem.SHARE_SUMMARY_WITH_CHILD,
)


class ConsentSource(StrEnum):
    VOICE_YES = "voice_yes"
    APP_TAP = "app_tap"
    ADMIN_CHAT = "admin_chat"  # the child (admin) consented on the parent's behalf, in the chat
    GUARDIAN = "guardian"  # given by the admin for a parent with a lawful guardian (guardian flag + basis recorded)


class FamilySettings(BaseModel):
    checkin_time: str = "09:00"  # parent's local time, HH:MM
    sensitivity: Sensitivity = Sensitivity.BALANCED
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    refill_days: int = 5
    reminders_paused_until: datetime | None = None  # the CHILD paused medicine reminders (e.g. hospital stay)
    nudges_per_hour: int = 2  # ceilings (spec section 5); the family may lower them, never raise above these
    calls_per_incident: int = 3
    call_spacing_min: int = 5
    daily_escalation_cap: int = 3
    guardian_basis: str | None = None  # documented basis (e.g. 'court order / medical incapacity'); NOT verified in Phase 1: legal review
    guardian_set_at: datetime | None = None
    good_morning: bool = False  # per-family on/off: good-morning message to the parent
    festival_graphics: bool = False  # per-family on/off: festival greeting graphics
    good_morning_time: str = "07:30"
    safe_word_enabled: bool = False  # founder 2026-11-04: no safe word by default; optional per family
    call_audio_retention_days: int = 0  # listening cues only; 0 = nothing kept
    safe_word_hash: str | None = None
    safe_word_set_at: datetime | None = None


class Family(BaseModel):
    id: str = Field(default_factory=new_id)
    owner_user_id: str  # the child's Friday user: erasure key, pays, talks to Robin
    status: FamilyStatus = FamilyStatus.ONBOARDING
    parent_label: str = "Papa"  # how the child calls them: 'Papa', 'Mummy'
    settings: FamilySettings = Field(default_factory=FamilySettings)
    created_at: datetime | None = None


class Member(BaseModel):
    id: str = Field(default_factory=new_id)
    family_id: str
    role: Role
    name: str = ""
    phone: str | None = Field(default=None, repr=False)  # E.164; decrypted only in memory
    phone_hash: str = ""
    language: str = "hinglish"  # hinglish | hi | en
    timezone: str = "Asia/Kolkata"
    quiet_start: str | None = None  # None -> the family setting
    quiet_end: str | None = None
    call_ok: bool = False  # child / second contact agreed that Robin may ring (second contact: named in advance)
    paused: bool = False  # the parent paused Robin
    paused_at: datetime | None = None
    user_id: str | None = None  # the Friday user, for the child
    address: str | None = None  # the parent's address, for the authority call script only (admin sets it)


class Consent(BaseModel):
    id: str = Field(default_factory=new_id)
    family_id: str
    member_id: str
    item: str
    given_at: datetime
    source: ConsentSource
    given_by: str = "admin_on_behalf"  # admin_on_behalf (default) | user (the parent said yes themselves)
    withdrawn_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.withdrawn_at is None


class Medicine(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    dose_text: str = ""  # as the child typed it: '5 mg'. Never interpreted, never advised on.
    times: list[str] = Field(default_factory=list)  # local HH:MM, one per dose
    strips: float = 0  # strips in stock at last_purchase_date
    pills_per_strip: int = 10
    last_purchase_date: date | None = None
    stock_adjust: float = 0  # pills counted by the parent at stock_counted_at (the weekly "kitni goliyan bachi")
    stock_counted_at: datetime | None = None
    active: bool = True
    ordered_at: datetime | None = None  # T12: the child tapped "ordered" on a refill alert (Robin never orders or pays; this only quiets the next alert)

    @property
    def doses_per_day(self) -> int:
        return max(len(self.times), 1)


class Step(BaseModel):
    """One thing Robin says on a call, and what it listens for after it."""

    line: str  # key in lines.py
    slots: dict[str, str] = Field(default_factory=dict)
    expect: str = "none"  # none | yesno | free | mood | count
    on_yes: str | None = None  # line spoken after a yes (or "I am fine")
    on_no: str | None = None  # line spoken after a no


class AnswerRaw(BaseModel):
    line: str
    text: str = ""


class CallResult(StrEnum):
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"
    REFUSED = "refused"


class CallOutcome(BaseModel):
    result: CallResult
    detail: str = ""
    answers: list[AnswerRaw] = Field(default_factory=list)
    hung_up_early: bool = False
