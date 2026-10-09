"""Application settings (pydantic-settings). Every env var Friday reads lives here.

Conventions
-----------
* Friday's own knobs use the ``FRIDAY_`` prefix (``FRIDAY_MODE``, ``FRIDAY_DATABASE_URL``...).
* Vendor credentials use the vendor's conventional name (``ANTHROPIC_API_KEY``,
  ``TWILIO_AUTH_TOKEN``...); the ``FRIDAY_``-prefixed spelling is also accepted.
* Every field has a safe default so ``Settings()`` works with **no env at all**
  (simulator mode, SQLite, fakes everywhere).
* Secrets are ``SecretStr``; call ``.get_secret_value()`` only at the point of use.

Provider resolution (see ``Settings.resolve_*``):
* ``FRIDAY_MODE=simulator`` (default): side-effecting providers (telephony,
  WhatsApp, SMS) are ALWAYS simulated - we never phone real businesses by
  accident. "Pure compute" providers (LLM, STT, TTS) use the real vendor when its
  key is present, otherwise the fake.
* ``FRIDAY_MODE=live``: ``auto`` picks the real default vendor for everything and
  ``Settings.live_problems()`` lists missing credentials (the container refuses
  to start if any).
* Any ``FRIDAY_*_PROVIDER`` can be pinned explicitly to override ``auto``.

Owner: Engineering Manager (core, frozen). Additive changes only (new optional
fields with defaults) - see docs/TASKS.md "Changing core".
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from friday.core.templates import default_whatsapp_names

Mode = Literal["simulator", "live"]
LLMProviderName = Literal["auto", "anthropic", "openai", "fake"]
TelephonyProviderName = Literal[
    "auto", "simulator", "routed", "sarvam", "twilio", "exotel", "plivo"
]
STTProviderName = Literal["auto", "fake", "sarvam", "deepgram"]
TTSProviderName = Literal["auto", "fake", "sarvam", "elevenlabs"]
WhatsAppProviderName = Literal["auto", "simulator", "cloud"]
SMSProviderName = Literal["auto", "fake", "msg91", "off"]
DirectoryProviderName = Literal["auto", "simulator", "google_places"]
GeocoderProviderName = Literal["auto", "simulator", "google"]
HotelProviderName = Literal["auto", "simulator", "expedia_rapid", "off"]
BackendName = Literal["auto", "memory", "postgres", "redis"]
WorkerRole = Literal["api", "task", "voice", "proactive", "batch"]
ProfileName = Literal["default", "pilot", "beta"]
ALL_ROLES: tuple[str, ...] = ("api", "task", "voice", "proactive", "batch")

# Comma-separated OR JSON list in env: FRIDAY_NUMBERS=+9180...,+9122...
CsvList = Annotated[list[str], NoDecode]
_DEV_SECRET = "dev-insecure-change-me"

# Founder cost rule: Haiku by default, Sonnet for live call turns, Opus only on escalation.
DEFAULT_LLM_MODELS: dict[str, str] = {
    "interpret": "claude-haiku-5-5",
    "resolve_references": "claude-haiku-5-5",
    "extract": "claude-haiku-5-5",
    "judge_nudge": "claude-haiku-5-5",
    "summarize": "claude-haiku-5-5",
    "compare": "claude-haiku-5-5",
    "shortlist_reasons": "claude-haiku-5-5",
    "translate": "claude-haiku-5-5",
    "sim_business": "claude-haiku-5-5",
    "call_turn": "claude-sonnet-5-5",
}

# OpenAI (GPT) routing, used when the resolved LLM provider is "openai". Same cost rule: the
# cheap model for every light job, the same cheap model with LOW reasoning for live call turns
# (latency), the bigger model only on explicit escalation. See docs/LIVE_TEST_WINDOWS.md.
OPENAI_LIGHT_MODEL = "gpt-5.4-mini"
OPENAI_ESCALATION_MODEL = "gpt-5.4"
DEFAULT_OPENAI_MODELS: dict[str, str] = {
    p: OPENAI_LIGHT_MODEL for p in DEFAULT_LLM_MODELS
}  # incl. call_turn
# reasoning_effort per purpose (GPT-5 family only): none | minimal | low | medium | high.
DEFAULT_OPENAI_REASONING: dict[str, str] = {"call_turn": "low"}
# ESTIMATES to verify against https://openai.com/api/pricing: USD per 1M tokens as
# [input, cached input, output]. Used only for internal INR cost logging, never shown to users.
DEFAULT_OPENAI_PRICES_USD_PER_MTOK: dict[str, list[float]] = {
    "gpt-5.4-nano": [0.20, 0.02, 1.25],
    "gpt-5.4-mini": [0.75, 0.075, 4.50],
    "gpt-5.4-pro": [30.0, 30.0, 180.0],
    "gpt-5.4": [2.50, 0.25, 15.0],
    "gpt-5.5": [5.0, 0.50, 30.0],
    "gpt-5-nano": [0.05, 0.005, 0.40],
    "gpt-5-mini": [0.25, 0.025, 2.0],
    "gpt-5": [1.25, 0.125, 10.0],
    "gpt-4.1-nano": [0.10, 0.025, 0.40],
    "gpt-4.1-mini": [0.40, 0.10, 1.60],
    "gpt-4.1": [2.0, 0.50, 8.0],
    "gpt-4o-mini": [0.15, 0.075, 0.60],
    "gpt-4o": [2.50, 1.25, 10.0],
}


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRIDAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------------ app
    mode: Mode = "simulator"
    # ``pilot`` (FRIDAY_PROFILE=pilot): voice-only live test on a laptop. In live mode it
    # needs only telephony + Sarvam + LLM + the secrets/keys + an https public URL;
    # WhatsApp/SMS/hotels/directory fall back to simulators and recordings stay off.
    # ``default`` keeps every production requirement. See docs/LIVE_TEST_WINDOWS.md.
    # ``beta`` (FRIDAY_PROFILE=beta): small private-beta production (docs/DEPLOY_AWS.md). Live mode
    # requires LLM, Sarvam, Vobiz + caller IDs, Google Places, WhatsApp Cloud, an https public URL,
    # all keys/secrets, the admin token and the legal links; Expedia hotels, MSG91/DLT SMS and the
    # object store are OPTIONAL and DISABLED (never simulated) when missing: hotels -> direct-call
    # path only, SMS -> off, recordings stay OFF without an object store.
    profile: ProfileName = "default"
    # Pilot safety: the ONLY numbers `friday livecall` may dial (E.164, CSV). Default empty.
    pilot_allowed_numbers: CsvList = Field(default_factory=list)
    pilot_max_spend_inr: float = 25.0  # `friday livecall` refuses if the estimate is above this
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    public_base_url: str = "http://localhost:8000"  # used for provider webhooks/callbacks
    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: SecretStr = SecretStr("dev-insecure-change-me")  # signing + PIN pepper
    default_country_code: str = "+91"
    default_language: Literal["en", "hi", "hinglish"] = "hinglish"
    media_dir: str = "./var/media"  # local recordings/voice notes (simulator + dev)

    # Legal links shown in the onboarding consent message. Required in the beta profile and any
    # non-pilot live mode (``live_problems``); the pilot (founder-only test) may leave them unset.
    terms_url: str | None = None
    privacy_url: str | None = None
    grievance_email: str | None = None  # Grievance Officer contact (DPDP / IT Rules)
    grievance_name: str | None = None  # optional: the Officer's name

    # ------------------------------------------------------------------ database
    database_url: str = "sqlite+aiosqlite:///./friday.db"  # Postgres: postgresql+asyncpg://
    db_echo: bool = False

    # ------------------------------------------------------------------ LLM (brain)
    llm_provider: LLMProviderName = "auto"
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("ANTHROPIC_API_KEY", "FRIDAY_ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5-5"  # planning, summaries, nudge judgement
    llm_fast_model: str = "claude-haiku-5-5"  # latency-critical: live call turns, intent
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2
    # Per-purpose routing (founder cost rule). FRIDAY_LLM_MODELS='{"call_turn": "..."}'.
    # ``llm_model`` / ``llm_fast_model`` are legacy fallbacks for unknown purposes.
    llm_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_LLM_MODELS))
    llm_default_purpose_model: str = "claude-haiku-5-5"  # purpose not in llm_models
    llm_escalation_model: str = "claude-opus-5-5"  # ONLY on explicit escalation
    llm_task_token_budget: int = 60_000  # per task; over budget -> cheaper model + alert
    llm_prompt_caching: bool = True
    llm_batch_enabled: bool = True  # Batch API for non-real-time work (Anthropic only)

    # OpenAI (GPT) as an alternative brain: FRIDAY_LLM_PROVIDER=openai, or auto with only
    # OPENAI_API_KEY set. Anthropic settings above are untouched.
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("OPENAI_API_KEY", "FRIDAY_OPENAI_API_KEY")
    )
    openai_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_OPENAI_MODELS))
    openai_default_purpose_model: str = OPENAI_LIGHT_MODEL  # purpose not in openai_models
    openai_escalation_model: str = OPENAI_ESCALATION_MODEL  # ONLY on explicit escalation
    openai_reasoning_effort: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_OPENAI_REASONING)
    )
    openai_default_reasoning_effort: str = "none"  # purposes not in openai_reasoning_effort
    openai_timeout_s: float = 30.0  # non-live-call purposes (total budget incl. retries)
    openai_call_turn_timeout_s: float = 8.0  # live call turn: then the brain degrades gracefully
    openai_max_retries: int = 2  # 429 / 5xx / connection, exponential backoff within the budget
    openai_prices_usd_per_mtok: dict[str, list[float]] = Field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_OPENAI_PRICES_USD_PER_MTOK.items()}
    )  # ESTIMATES: [input, cached input, output] per model prefix
    openai_usd_to_inr: float = 84.0
    # EXPERIMENT, off: call-turn non-strict schema (essential keys only). Measured: no latency gain,
    # 2-3 repair retries per 10 turns, so strict stays the default.
    openai_relaxed_call_schema: bool = False

    # ------------------------------------------------------------------ telephony (voice)
    telephony_provider: TelephonyProviderName = "auto"
    twilio_account_sid: str | None = Field(
        default=None, validation_alias=_alias("TWILIO_ACCOUNT_SID", "FRIDAY_TWILIO_ACCOUNT_SID")
    )
    twilio_auth_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("TWILIO_AUTH_TOKEN", "FRIDAY_TWILIO_AUTH_TOKEN")
    )
    twilio_from_number: str | None = Field(
        default=None, validation_alias=_alias("TWILIO_FROM_NUMBER", "FRIDAY_TWILIO_FROM_NUMBER")
    )
    exotel_sid: str | None = Field(default=None, validation_alias=_alias("EXOTEL_SID"))
    exotel_api_key: str | None = Field(default=None, validation_alias=_alias("EXOTEL_API_KEY"))
    exotel_api_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("EXOTEL_API_TOKEN")
    )
    exotel_caller_id: str | None = Field(default=None, validation_alias=_alias("EXOTEL_CALLER_ID"))
    plivo_auth_id: str | None = Field(default=None, validation_alias=_alias("PLIVO_AUTH_ID"))
    plivo_auth_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("PLIVO_AUTH_TOKEN")
    )
    plivo_from_number: str | None = Field(
        default=None, validation_alias=_alias("PLIVO_FROM_NUMBER")
    )
    # Founder decision (2026-10-08): Sarvam-only live telephony for now. ``auto`` resolves
    # to "sarvam". Exotel/Twilio stay available explicitly (FRIDAY_TELEPHONY_PROVIDER=exotel)
    # or via the failover router (FRIDAY_TELEPHONY_PROVIDER=routed + FRIDAY_TELEPHONY_ROUTE).
    telephony_route: CsvList = Field(default_factory=lambda: ["sarvam"])
    # Capabilities confirmed against Sarvam's account (e.g. "bridge_transfer"), CSV.
    sarvam_verified_capabilities: CsvList = Field(default_factory=list)
    exotel_subdomain: str = Field(
        default="api.in.exotel.com", validation_alias=_alias("EXOTEL_SUBDOMAIN")
    )
    exotel_voicebot_app_id: str | None = Field(
        default=None, validation_alias=_alias("EXOTEL_VOICEBOT_APP_ID")
    )
    exotel_caller_ids: CsvList = Field(
        default_factory=list, validation_alias=_alias("EXOTEL_CALLER_IDS")
    )
    sarvam_telephony_auth_id: str | None = Field(
        default=None, validation_alias=_alias("SARVAM_TELEPHONY_AUTH_ID", "VOBIZ_AUTH_ID")
    )
    sarvam_telephony_auth_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("SARVAM_TELEPHONY_AUTH_TOKEN", "VOBIZ_AUTH_TOKEN")
    )
    sarvam_telephony_base_url: str = "https://api.vobiz.ai/api/v1"
    sarvam_caller_ids: CsvList = Field(
        default_factory=list, validation_alias=_alias("SARVAM_CALLER_IDS")
    )
    inbound_claim_timeout_s: float = 10.0  # parked inbound leg -> fixed P1 message after this

    # Friday caller-ID pool (BRIEF E.30 + caller-ID reputation). Sticky per business.
    # FRIDAY_NUMBERS=+918000000001,+912200000002 (or JSON). Details per number live in
    # the NumberPool (FridayNumber rows); this is the bootstrap list.
    friday_numbers: CsvList = Field(
        default_factory=list, validation_alias=_alias("FRIDAY_NUMBERS", "FRIDAY_FRIDAY_NUMBERS")
    )

    # ---- caller-ID reputation & rotation (NumberPool defaults; ops-configurable)
    number_max_calls_per_hour: int = 15
    number_max_calls_per_day: int = 80
    number_max_concurrent: int = 2
    number_min_gap_s: int = 45  # pacing: no bursts on one number
    number_warmup_daily_caps: list[int] = Field(default_factory=lambda: [10, 20, 35, 50, 65])
    number_health_window_calls: int = 50  # rolling window for health metrics
    number_min_answer_rate: float = 0.35
    number_max_short_call_rate: float = 0.30  # answered calls < 10 s
    number_max_dnc_rate: float = 0.03
    number_short_call_s: int = 10
    number_cooldown_h: int = 72
    number_max_cooldowns_before_retire: int = 2
    number_retired_forward_days: int = 30  # retired numbers keep forwarding call-backs
    number_health_min_score: float = 0.5  # below -> cooling

    # ---- task retry / inbound policy (BRIEF E.30-37); env FRIDAY_TASKS_*
    tasks_max_attempts: int = 3
    tasks_no_answer_delays_min: list[int] = Field(default_factory=lambda: [10, 45])
    tasks_final_window_gap_min: int = 120
    tasks_busy_delay_min: int = 5
    tasks_failed_delay_min: int = 5
    tasks_vague_callback_min: int = 120
    tasks_try_alt_numbers: bool = True
    tasks_whatsapp_request_on_no_answer: bool = True
    tasks_business_request_template: str = "friday_biz_request"
    tasks_inbound_lookback_days: int = 30
    tasks_missed_call_notify_after: int = 3
    tasks_better_offer_pct: int = 15
    tasks_offer_question_timeout_s: int = 7200
    tasks_max_progress_updates_per_call: int = 3

    # call behaviour
    call_record: bool = True
    call_ring_timeout_s: int = 30
    call_max_duration_s: int = 300
    call_max_attempts: int = 3  # per task, across busy/no-answer retries
    call_retry_backoff_s: int = 900  # wait before re-dialling after busy/no-answer
    call_silence_timeout_s: float = 8.0  # callee silence before Friday re-prompts
    mid_call_question_timeout_s: int = 90  # default ApprovalPolicy.hold_timeout_s
    # While holding for the user, a short polished hold line ("Thank you for holding,
    # I'm still waiting for Rahul's confirmation") every N s. NOT a filler sound.
    call_hold_reminder_interval_s: int = 20
    callback_after_approval_delay_s: int = 0  # dial the confirm call right after approval

    # call engine (B14, B19)
    max_concurrent_calls: int = 5  # global cap across all users (cost + provider limits)
    fanout_default_concurrency: int = 3  # per parent task (PARALLEL / FIRST_MATCH)
    # When a business's hours are unknown, only dial inside this IST window.
    business_call_window_start: str = "09:30"
    business_call_window_end: str = "20:00"
    avoid_lunch_window: str = "13:30-14:30"  # IST; soft preference for small businesses
    # Customer care / IVR (C21-26)
    ivr_max_hold_s: int = 1500  # give up after 25 min on hold -> HOLD_TIMEOUT, retry later
    hold_user_update_interval_s: int = 300  # "still on hold with Airtel" cadence
    care_followup_grace_h: int = 24  # follow up this long after a promised date passes
    # Wellbeing check-ins (A13)
    checkin_default_time_ist: str = "10:30"
    checkin_max_duration_s: int = 240

    # ------------------------------------------------------------------ STT / TTS (voice)
    stt_provider: STTProviderName = "auto"
    tts_provider: TTSProviderName = "auto"
    sarvam_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("SARVAM_API_KEY", "FRIDAY_SARVAM_API_KEY")
    )
    sarvam_tts_speaker: str = "anushka"
    deepgram_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("DEEPGRAM_API_KEY", "FRIDAY_DEEPGRAM_API_KEY")
    )
    elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("ELEVENLABS_API_KEY", "FRIDAY_ELEVENLABS_API_KEY")
    )
    elevenlabs_voice_id: str | None = Field(
        default=None, validation_alias=_alias("ELEVENLABS_VOICE_ID", "FRIDAY_ELEVENLABS_VOICE_ID")
    )
    # Language -> provider voice id (JSON in env). Missing languages fall back to
    # the provider default for that language. Voice must be calm & polished; the
    # TTS layer must never inject fillers ("umm"), breaths or typing sounds.
    tts_voices: dict[str, str] = Field(default_factory=dict)
    tts_speaking_rate: float = 1.0
    tts_style: str = "calm"
    tts_voice_gender: Literal["female"] = "female"  # Friday is female (founder decision)

    # ------------------------------------------------------------------ WhatsApp (channels)
    whatsapp_provider: WhatsAppProviderName = "auto"
    whatsapp_access_token: SecretStr | None = Field(
        default=None,
        validation_alias=_alias("WHATSAPP_ACCESS_TOKEN", "FRIDAY_WHATSAPP_ACCESS_TOKEN"),
    )
    whatsapp_phone_number_id: str | None = Field(
        default=None,
        validation_alias=_alias("WHATSAPP_PHONE_NUMBER_ID", "FRIDAY_WHATSAPP_PHONE_NUMBER_ID"),
    )
    whatsapp_verify_token: SecretStr = Field(
        default=SecretStr("friday-dev-verify"),
        validation_alias=_alias("WHATSAPP_VERIFY_TOKEN", "FRIDAY_WHATSAPP_VERIFY_TOKEN"),
    )
    whatsapp_app_secret: SecretStr | None = Field(
        default=None, validation_alias=_alias("WHATSAPP_APP_SECRET", "FRIDAY_WHATSAPP_APP_SECRET")
    )
    whatsapp_api_version: str = "v21.0"
    whatsapp_session_window_h: int = 24
    # logical template key -> approved WhatsApp template name (JSON in env)
    whatsapp_templates: dict[str, str] = Field(
        default_factory=default_whatsapp_names  # single source: friday/core/templates.py
    )
    whatsapp_template_language: str = "en"

    # ------------------------------------------------------------------ SMS / DLT (channels)
    sms_provider: SMSProviderName = "auto"
    msg91_auth_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("MSG91_AUTH_KEY", "FRIDAY_MSG91_AUTH_KEY")
    )
    sms_sender_id: str = "FRIDAY"  # 6-char DLT header
    dlt_entity_id: str | None = Field(default=None, validation_alias=_alias("DLT_ENTITY_ID"))
    # logical template key -> DLT template id (JSON in env)
    sms_dlt_templates: dict[str, str] = Field(
        default_factory=lambda: {
            "business_booking_confirmed": "DLT_TPL_BIZ_BOOKING",
            "business_enquiry_thanks": "DLT_TPL_BIZ_ENQUIRY",
            "user_task_update": "DLT_TPL_USER_UPDATE",
            "user_reminder": "DLT_TPL_USER_REMINDER",
        }
    )

    # ------------------------------------------------------------------ discovery
    directory_provider: DirectoryProviderName = "auto"
    # One Google Maps Platform key (Places API (New) + Geocoding API enabled).
    google_places_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_alias(
            "GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_API_KEY", "FRIDAY_GOOGLE_PLACES_API_KEY"
        ),
    )
    geocoder_provider: GeocoderProviderName = "auto"
    discovery_max_candidates: int = 10  # fetched from the directory
    discovery_shortlist_size: int = 3  # called after the brain shortlists
    discovery_min_rating: float = 3.8
    # number safety (B16, C26)
    verify_numbers: bool = True  # NumberVerifier before every first call to a number
    scam_numbers_path: str | None = None  # extra known-scam list (one E.164 per line)
    official_numbers_path: str | None = None  # override curated care-number JSON

    # ------------------------------------------------------------------ hotels (D27-29)
    hotel_provider: HotelProviderName = "auto"
    expedia_rapid_api_key: str | None = Field(
        default=None, validation_alias=_alias("EXPEDIA_RAPID_API_KEY")
    )
    expedia_rapid_shared_secret: SecretStr | None = Field(
        default=None, validation_alias=_alias("EXPEDIA_RAPID_SHARED_SECRET")
    )
    expedia_rapid_base_url: str = "https://test.ean.com/v3"  # sandbox by default
    hotel_shortlist_size: int = 3
    hotel_reconfirm_hour_ist: int = 11  # day-before reconfirm call time

    # ------------------------------------------------------------------ proactive
    proactive_enabled: bool = True
    proactive_tick_s: int = 60
    proactive_daily_cap: int = 3  # unprompted msgs per IST day (urgent exempt)
    quiet_hours_start: int = 22  # IST hour, inclusive
    quiet_hours_end: int = 8  # IST hour, exclusive
    morning_briefing_hour: int = 8  # IST
    ignore_learning_threshold: int = 3  # consecutive ignores before backing off a kind
    task_reminder_lead_min: int = 120  # "appointment in 2h"
    follow_up_delay_h: int = 24  # "did the plumber come?"

    # ------------------------------------------------------------------ access / limits
    invite_only: bool = True
    invites_per_user: int = 5
    # No user-facing usage cap in beta. Internal cost tracking + ops-only abuse limit.
    abuse_rate_limit_enabled: bool = False
    abuse_max_calls_per_day: int = 30
    cost_alert_inr_per_user_month: float = 1500.0  # ops alert threshold (logs/event)
    pin_max_attempts: int = 5
    admin_phones: list[str] = Field(default_factory=list)  # bootstrap users, skip invite
    # Bearer token for /admin/* (the admin router also reads FRIDAY_ADMIN_TOKEN from os.environ).
    admin_token: SecretStr | None = None

    # ------------------------------------------------------------------ kill switch
    # ``friday pause`` (friday/pause.py): stops outbound calls + proactive messages at once.
    # Paused when FRIDAY_PAUSED=true OR the flag file exists (shared volume => all containers).
    paused: bool = False
    pause_file: str = "./var/PAUSED"

    # ------------------------------------------------------------------ security keys
    # SECURITY-30: separate keys per purpose. In dev each falls back to
    # HKDF(secret_key, label); in live all three are required (live_problems()).
    pin_pepper: SecretStr | None = None
    field_key: SecretStr | None = None  # local data key for field encryption (dev / no KMS)
    field_key_id: str | None = None  # KMS key id/ARN for envelope encryption in live
    index_key: SecretStr | None = None  # HMAC key for blind indexes (phone lookups)

    # ------------------------------------------------------------------ scale-out
    # One codebase, several process roles. FRIDAY_ROLES=api,task (CSV or JSON).
    roles: CsvList = Field(default_factory=lambda: list(ALL_ROLES))
    queue_backend: BackendName = "auto"  # auto: postgres if DATABASE_URL is Postgres
    lock_backend: BackendName = "auto"
    cache_backend: BackendName = "auto"  # auto: redis if redis_url, else memory
    rate_limit_backend: BackendName = "auto"
    redis_url: str | None = Field(
        default=None, validation_alias=_alias("REDIS_URL", "FRIDAY_REDIS_URL")
    )
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_s: float = 10.0
    object_store_url: str | None = None  # s3://bucket/prefix for recordings (None = media_dir)
    worker_concurrency: dict[str, int] = Field(
        default_factory=lambda: {"task": 32, "voice": 50, "proactive": 8, "batch": 4}
    )
    queue_poll_interval_s: float = 0.5
    queue_visibility_timeout_s: int = 300  # claimed job re-queued if not acked in time
    queue_max_attempts: int = 8  # then dead-letter
    # Provider concurrency / rate limits (backpressure). key -> limit.
    provider_concurrency: dict[str, int] = Field(
        default_factory=lambda: {
            "telephony": 200,
            "sarvam": 200,
            "exotel": 100,
            "twilio": 50,
            "stt": 300,
            "tts": 300,
            "llm": 200,
        }
    )
    provider_rate_per_s: dict[str, float] = Field(
        default_factory=lambda: {
            "telephony": 20.0,
            "whatsapp": 70.0,
            "sms": 20.0,
            "llm": 50.0,
            "google_places": 20.0,
        }
    )
    llm_tokens_per_min: int = 2_000_000
    webhook_idempotency_ttl_h: int = 72
    proactive_shards: int = 1  # proactive engine sharded by hash(user_id) % shards
    proactive_shard_index: int | None = None  # None = all shards in this process

    # ------------------------------------------------------------------ simulator
    sim_seed: int = 7  # deterministic simulated businesses
    sim_business_answer_rate: float = 1.0  # 1.0 = always answers; <1 exercises retries
    sim_time_scale: float | None = None  # simulator legs: virtual-time scale (None = auto)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        # `KEY=` lines in .env mean "unset", not "empty secret".
        return None if isinstance(v, str) and v.strip() == "" else v

    @field_validator(
        "telephony_route",
        "exotel_caller_ids",
        "sarvam_caller_ids",
        "friday_numbers",
        "roles",
        "sarvam_verified_capabilities",
        "pilot_allowed_numbers",
        mode="before",
    )
    @classmethod
    def _csv_list(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @model_validator(mode="after")
    def _pilot_no_recordings(self) -> Settings:
        if self.profile == "pilot":  # pilot: recordings are never persisted
            self.call_record = False
        elif self.profile == "beta" and not self.object_store_url:
            self.call_record = False  # beta: recordings only with an object store (S-6)
        return self

    # ================================================================== helpers
    def model_for(self, purpose: str, *, escalate: bool = False) -> str:
        """Model for an LLM purpose (founder routing). Never Opus (or the bigger GPT) unless
        ``escalate``. Follows the resolved provider: GPT names when it is ``openai``."""
        if self.resolve_llm() == "openai":
            if escalate:
                return self.openai_escalation_model
            return self.openai_models.get(purpose, self.openai_default_purpose_model)
        if escalate:
            return self.llm_escalation_model
        return self.llm_models.get(purpose, self.llm_default_purpose_model)

    def derived_key(self, label: str) -> bytes:
        """HKDF-style 32-byte key from ``secret_key`` for ``label`` (dev fallback only)."""
        prk = hmac.new(
            b"friday-kdf-v1", self.secret_key.get_secret_value().encode(), hashlib.sha256
        )
        return hmac.new(prk.digest(), label.encode() + b"\x01", hashlib.sha256).digest()

    def key_material(self, purpose: Literal["pin_pepper", "field_key", "index_key"]) -> bytes:
        """Explicit key if configured, else the HKDF fallback (SECURITY-30)."""
        explicit: SecretStr | None = getattr(self, purpose)
        if explicit is not None:
            return explicit.get_secret_value().encode()
        return self.derived_key(purpose)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def resolve_queue(self) -> Literal["memory", "postgres"]:
        if self.queue_backend in ("memory", "postgres"):
            return self.queue_backend
        return "postgres" if self.database_url.startswith("postgresql") else "memory"

    def resolve_lock(self) -> Literal["memory", "postgres", "redis"]:
        if self.lock_backend != "auto":
            return self.lock_backend
        return "postgres" if self.database_url.startswith("postgresql") else "memory"

    def resolve_cache(self) -> Literal["memory", "redis"]:
        if self.cache_backend in ("memory", "redis"):
            return self.cache_backend
        return "redis" if self.redis_url else "memory"

    def resolve_rate_limiter(self) -> Literal["memory", "redis"]:
        if self.rate_limit_backend in ("memory", "redis"):
            return self.rate_limit_backend
        return "redis" if self.redis_url else "memory"

    # ================================================================== resolution
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_pilot(self) -> bool:
        return self.profile == "pilot"

    @property
    def is_beta(self) -> bool:
        return self.profile == "beta"

    def beta_expedia_configured(self) -> bool:
        return bool(self.expedia_rapid_api_key and self.expedia_rapid_shared_secret)

    def beta_msg91_configured(self) -> bool:
        return bool(self.msg91_auth_key and self.dlt_entity_id)

    def legal_links_required(self) -> bool:
        return self.is_live and not self.is_pilot

    def missing_legal_settings(self) -> list[str]:
        """Env names of the legal settings that are required but unset (empty == fine)."""
        if not self.legal_links_required():
            return []
        have = {
            "FRIDAY_TERMS_URL": self.terms_url,
            "FRIDAY_PRIVACY_URL": self.privacy_url,
            "FRIDAY_GRIEVANCE_EMAIL": self.grievance_email,
        }
        return [k for k, v in have.items() if not (v and v.strip())]

    def optional_feature_notes(self) -> list[str]:
        """Live mode: every feature that is OFF or SIMULATED, in plain words (``friday check``)."""
        if not self.is_live:
            return []
        notes = []
        hotels = self.resolve_hotels()
        if hotels == "off":
            notes.append(
                "hotel live rates: OFF (no Expedia keys) - Friday still finds a hotel in the "
                "directory, phones it, asks availability and the rate and asks the user before "
                "any booking; users are told live rates are not available. No rates are made up"
            )
        elif hotels == "simulator":
            notes.append("hotels: SIMULATED (founder test only) - names carry [SIMULATED]")
        if self.resolve_sms() == "off":
            notes.append(
                "SMS: OFF (no MSG91/DLT) - Friday uses WhatsApp or a call-back; nothing is "
                "recorded as sent by SMS"
            )
        elif self.resolve_sms() == "fake":
            notes.append("SMS: SIMULATED (founder test only) - no real SMS is sent")
        if self.resolve_whatsapp() == "simulator":
            notes.append("WhatsApp: SIMULATED (founder test only) - no real message is sent")
        if self.resolve_directory() == "simulator":
            notes.append("business directory: SIMULATED (founder test only) - listings are fake")
        if self.resolve_geocoder() == "simulator":
            notes.append("geocoder: SIMULATED (founder test only)")
        if not self.object_store_url:
            notes.append("recordings: OFF (no FRIDAY_OBJECT_STORE_URL) - nothing is recorded")
        return notes

    def simulated_in_live(self) -> list[str]:
        """Components resolved to a simulator/fake while live (empty for a safe config)."""
        if not self.is_live:
            return []
        out = []
        if self.resolve_hotels() == "simulator":
            out.append("hotels")
        if self.resolve_sms() == "fake":
            out.append("sms")
        if self.resolve_whatsapp() == "simulator":
            out.append("messaging")
        if self.resolve_directory() == "simulator":
            out.append("directory")
        if self.resolve_geocoder() == "simulator":
            out.append("geocoder")
        return out

    def public_url_problem(self) -> str | None:
        """Why ``public_base_url`` cannot receive provider webhooks (None == fine)."""
        from urllib.parse import urlparse

        u = urlparse(self.public_base_url.strip())
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not host:
            return "FRIDAY_PUBLIC_BASE_URL must be an https:// URL (the tunnel address)"
        if host in ("localhost", "0.0.0.0", "::1") or host.startswith("127.") or (
            host.endswith(".local") or host.endswith(".localhost") or "." not in host
        ):
            return "FRIDAY_PUBLIC_BASE_URL must not be localhost (use the tunnel address)"
        return None

    def resolve_llm(self) -> Literal["anthropic", "openai", "fake"]:
        """auto: Anthropic if its key is set, else OpenAI if its key is set, else the fake in
        simulator mode. Live mode with neither key resolves to Anthropic so ``live_problems``
        reports the missing key (it never silently falls back to the fake)."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "anthropic" if self.is_live else "fake"

    def llm_key_name(self) -> str | None:
        """Env name of the key the resolved LLM provider needs (names only, never values)."""
        names = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
        return names.get(self.resolve_llm())

    def llm_key_configured(self) -> bool:
        return bool(
            {"anthropic": self.anthropic_api_key, "openai": self.openai_api_key}.get(
                self.resolve_llm()
            )
        )

    def resolve_stt(self) -> Literal["fake", "sarvam", "deepgram"]:
        if self.stt_provider != "auto":
            return self.stt_provider
        if self.sarvam_api_key:
            return "sarvam"
        if self.deepgram_api_key:
            return "deepgram"
        return "sarvam" if self.is_live else "fake"

    def resolve_tts(self) -> Literal["fake", "sarvam", "elevenlabs"]:
        if self.tts_provider != "auto":
            return self.tts_provider
        if self.sarvam_api_key:
            return "sarvam"
        if self.elevenlabs_api_key:
            return "elevenlabs"
        return "sarvam" if self.is_live else "fake"

    def resolve_directory(self) -> Literal["simulator", "google_places"]:
        # Read-only provider: real Places data is safe even in simulator mode.
        if self.directory_provider != "auto":
            return self.directory_provider
        if self.is_pilot:
            return "google_places" if self.google_places_api_key else "simulator"
        return "google_places" if (self.is_live or self.google_places_api_key) else "simulator"

    def resolve_geocoder(self) -> Literal["simulator", "google"]:
        if self.geocoder_provider != "auto":
            return self.geocoder_provider
        if self.is_pilot:
            return "google" if self.google_places_api_key else "simulator"
        return "google" if (self.is_live or self.google_places_api_key) else "simulator"

    def resolve_hotels(self) -> Literal["simulator", "expedia_rapid", "off"]:
        # book() has real-world side effects -> real provider only in live mode.
        # Live without Expedia keys is "off", never a simulator that invents rates; only the
        # pilot (founder test) or an explicit pin may simulate.
        if not self.is_live or (self.is_pilot and self.hotel_provider == "auto"):
            return "simulator"
        if self.is_beta and self.hotel_provider == "auto":  # optional in beta
            return "expedia_rapid" if self.beta_expedia_configured() else "off"
        return "expedia_rapid" if self.hotel_provider == "auto" else self.hotel_provider

    def resolve_telephony(
        self,
    ) -> Literal["simulator", "routed", "sarvam", "twilio", "exotel", "plivo"]:
        if not self.is_live:
            return "simulator"
        # auto -> Sarvam only (founder decision). "routed" must be chosen explicitly.
        return "sarvam" if self.telephony_provider == "auto" else self.telephony_provider

    def _telephony_needs(self, name: str) -> dict[str, object]:
        if name == "twilio":
            return {
                "TWILIO_ACCOUNT_SID": self.twilio_account_sid,
                "TWILIO_AUTH_TOKEN": self.twilio_auth_token,
                "TWILIO_FROM_NUMBER": self.twilio_from_number,
            }
        if name == "exotel":
            return {
                "EXOTEL_SID": self.exotel_sid,
                "EXOTEL_API_KEY": self.exotel_api_key,
                "EXOTEL_API_TOKEN": self.exotel_api_token,
                "EXOTEL_VOICEBOT_APP_ID": self.exotel_voicebot_app_id,
            }
        if name == "sarvam":
            return {
                "SARVAM_TELEPHONY_AUTH_ID": self.sarvam_telephony_auth_id,
                "SARVAM_TELEPHONY_AUTH_TOKEN": self.sarvam_telephony_auth_token,
            }
        if name == "plivo":
            return {"PLIVO_AUTH_ID": self.plivo_auth_id, "PLIVO_AUTH_TOKEN": self.plivo_auth_token}
        return {}

    def resolve_whatsapp(self) -> Literal["simulator", "cloud"]:
        if not self.is_live or (self.is_pilot and self.whatsapp_provider == "auto"):
            return "simulator"
        return "cloud" if self.whatsapp_provider == "auto" else self.whatsapp_provider

    def resolve_sms(self) -> Literal["fake", "msg91", "off"]:
        if not self.is_live or (self.is_pilot and self.sms_provider == "auto"):
            return "fake"
        if self.is_beta and self.sms_provider == "auto":  # optional in beta
            return "msg91" if self.beta_msg91_configured() else "off"
        return "msg91" if self.sms_provider == "auto" else self.sms_provider

    def live_problems(self) -> list[str]:
        """Missing/unsafe configuration for the resolved providers (empty == OK)."""
        problems: list[str] = []
        need: dict[str, object] = {}
        if self.resolve_llm() == "anthropic":
            if self.llm_provider == "auto" and not self.anthropic_api_key:
                # either provider's key satisfies the LLM requirement (auto picks the one set)
                problems.append("missing ANTHROPIC_API_KEY (or OPENAI_API_KEY): an LLM key")
            else:
                need["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        elif self.resolve_llm() == "openai":
            need["OPENAI_API_KEY"] = self.openai_api_key
        tel = self.resolve_telephony()
        if tel == "routed":
            route = self.telephony_route or ["twilio"]
            per = {n: self._telephony_needs(n) for n in route}
            if not any(needs and all(needs.values()) for needs in per.values()):
                missing = sorted({k for needs in per.values() for k, v in needs.items() if not v})
                problems.append(
                    "telephony: no provider in FRIDAY_TELEPHONY_ROUTE is fully configured"
                )
                problems += [f"missing {k}" for k in missing]
        elif tel != "simulator":
            need |= self._telephony_needs(tel)
        uses_sarvam = tel == "sarvam" or (tel == "routed" and "sarvam" in self.telephony_route)
        if uses_sarvam and not (self.sarvam_caller_ids or self.friday_numbers):
            problems.append("missing SARVAM_CALLER_IDS (or FRIDAY_NUMBERS): your Vobiz number")
        # S-6: no local-disk recordings in live (the pilot never records)
        if self.is_live and not self.is_pilot and not self.is_beta and not self.object_store_url:
            problems.append("missing FRIDAY_OBJECT_STORE_URL (s3://bucket/prefix) for recordings")
        if self.resolve_stt() == "sarvam" or self.resolve_tts() == "sarvam":
            need["SARVAM_API_KEY"] = self.sarvam_api_key
        if self.resolve_stt() == "deepgram":
            need["DEEPGRAM_API_KEY"] = self.deepgram_api_key
        if self.resolve_tts() == "elevenlabs":
            need["ELEVENLABS_API_KEY"] = self.elevenlabs_api_key
        if self.resolve_whatsapp() == "cloud":
            need |= {
                "WHATSAPP_ACCESS_TOKEN": self.whatsapp_access_token,
                "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
                "WHATSAPP_APP_SECRET": self.whatsapp_app_secret,
            }
        if self.resolve_directory() == "google_places" or self.resolve_geocoder() == "google":
            need["GOOGLE_PLACES_API_KEY"] = self.google_places_api_key
        if self.resolve_hotels() == "expedia_rapid":
            need |= {
                "EXPEDIA_RAPID_API_KEY": self.expedia_rapid_api_key,
                "EXPEDIA_RAPID_SHARED_SECRET": self.expedia_rapid_shared_secret,
            }
        if self.resolve_sms() == "msg91":
            need |= {"MSG91_AUTH_KEY": self.msg91_auth_key, "DLT_ENTITY_ID": self.dlt_entity_id}
        problems += [f"missing {k}" for k, v in need.items() if not v]
        if self.is_live and (self.is_pilot or self.is_beta) and (msg := self.public_url_problem()):
            problems.append(msg)
        # onboarding consent message: terms, privacy and the Grievance Officer contact
        problems += [
            f"missing {k} (legal link shown at onboarding)" for k in self.missing_legal_settings()
        ]
        links = (("FRIDAY_TERMS_URL", self.terms_url), ("FRIDAY_PRIVACY_URL", self.privacy_url))
        for k, v in links:
            if self.legal_links_required() and v and not v.strip().startswith("https://"):
                problems.append(f"{k} must be an https:// URL")
        if self.is_live and self.secret_key.get_secret_value() == _DEV_SECRET:
            problems.append("FRIDAY_SECRET_KEY must be set in live mode")
        if (
            self.is_live
            and self.resolve_whatsapp() == "cloud"
            and self.whatsapp_verify_token.get_secret_value() == "friday-dev-verify"
        ):  # SECURITY-17
            problems.append("WHATSAPP_VERIFY_TOKEN must be set in live mode")
        if self.is_live:  # SECURITY-30: separate keys, never derived from one secret
            if self.pin_pepper is None:
                problems.append("missing FRIDAY_PIN_PEPPER (separate from FRIDAY_SECRET_KEY)")
            if self.field_key is None and self.field_key_id is None:
                problems.append("missing FRIDAY_FIELD_KEY_ID (KMS) or FRIDAY_FIELD_KEY")
            if self.index_key is None:
                problems.append("missing FRIDAY_INDEX_KEY (blind-index HMAC key)")
            if self.log_level.upper() == "DEBUG":  # SECURITY-26
                problems.append("FRIDAY_LOG_LEVEL=DEBUG is not allowed in live mode")
        if self.is_live and self.is_beta:
            if not self.admin_token and not os.environ.get("FRIDAY_ADMIN_TOKEN"):
                problems.append("missing FRIDAY_ADMIN_TOKEN (protects /admin/health)")
            if not self.database_url.startswith("postgresql"):
                problems.append("FRIDAY_DATABASE_URL must be PostgreSQL (postgresql+asyncpg://)")
            if not self.invite_only:
                problems.append("FRIDAY_INVITE_ONLY must stay true in the beta")
            pinned = (
                self.whatsapp_provider == "simulator"
                or self.telephony_provider == "simulator"
                or self.directory_provider == "simulator"
                or self.geocoder_provider == "simulator"
                or self.hotel_provider == "simulator"
                or self.sms_provider == "fake"
            )
            if pinned:
                problems.append("beta must not pin a simulator provider in live mode")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings for entrypoints only. Library code receives Settings via DI."""
    return Settings()
