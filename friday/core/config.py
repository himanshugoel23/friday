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

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["simulator", "live"]
LLMProviderName = Literal["auto", "anthropic", "fake"]
TelephonyProviderName = Literal["auto", "simulator", "twilio", "exotel", "plivo"]
STTProviderName = Literal["auto", "fake", "sarvam", "deepgram"]
TTSProviderName = Literal["auto", "fake", "sarvam", "elevenlabs"]
WhatsAppProviderName = Literal["auto", "simulator", "cloud"]
SMSProviderName = Literal["auto", "fake", "msg91"]
DirectoryProviderName = Literal["auto", "simulator", "google_places"]
GeocoderProviderName = Literal["auto", "simulator", "google"]
HotelProviderName = Literal["auto", "simulator", "expedia_rapid"]


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

    # ------------------------------------------------------------------ WhatsApp (channels)
    whatsapp_provider: WhatsAppProviderName = "auto"
    whatsapp_access_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("WHATSAPP_ACCESS_TOKEN", "FRIDAY_WHATSAPP_ACCESS_TOKEN")
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
        default_factory=lambda: {
            "nudge": "friday_nudge_v1",
            "task_update": "friday_task_update_v1",
            "question": "friday_question_v1",
            "reengage": "friday_reengage_v1",
        }
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
    monthly_call_cap: int = 10
    pin_max_attempts: int = 5
    admin_phones: list[str] = Field(default_factory=list)  # bootstrap users, skip invite

    # ------------------------------------------------------------------ simulator
    sim_seed: int = 7  # deterministic simulated businesses
    sim_business_answer_rate: float = 1.0  # 1.0 = always answers; <1 exercises retries

    # ================================================================== resolution
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def resolve_llm(self) -> Literal["anthropic", "fake"]:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "anthropic" if (self.is_live or self.anthropic_api_key) else "fake"

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
        return "google_places" if (self.is_live or self.google_places_api_key) else "simulator"

    def resolve_geocoder(self) -> Literal["simulator", "google"]:
        if self.geocoder_provider != "auto":
            return self.geocoder_provider
        return "google" if (self.is_live or self.google_places_api_key) else "simulator"

    def resolve_hotels(self) -> Literal["simulator", "expedia_rapid"]:
        # book() has real-world side effects -> real provider only in live mode.
        if not self.is_live:
            return "simulator"
        return "expedia_rapid" if self.hotel_provider == "auto" else self.hotel_provider

    def resolve_telephony(self) -> Literal["simulator", "twilio", "exotel", "plivo"]:
        if not self.is_live:
            return "simulator"
        return "twilio" if self.telephony_provider == "auto" else self.telephony_provider

    def resolve_whatsapp(self) -> Literal["simulator", "cloud"]:
        if not self.is_live:
            return "simulator"
        return "cloud" if self.whatsapp_provider == "auto" else self.whatsapp_provider

    def resolve_sms(self) -> Literal["fake", "msg91"]:
        if not self.is_live:
            return "fake"
        return "msg91" if self.sms_provider == "auto" else self.sms_provider

    def live_problems(self) -> list[str]:
        """Missing/unsafe configuration for the resolved providers (empty == OK)."""
        problems: list[str] = []
        need: dict[str, object] = {}
        if self.resolve_llm() == "anthropic":
            need["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        tel = self.resolve_telephony()
        if tel == "twilio":
            need |= {
                "TWILIO_ACCOUNT_SID": self.twilio_account_sid,
                "TWILIO_AUTH_TOKEN": self.twilio_auth_token,
                "TWILIO_FROM_NUMBER": self.twilio_from_number,
            }
        elif tel == "exotel":
            need |= {
                "EXOTEL_SID": self.exotel_sid,
                "EXOTEL_API_KEY": self.exotel_api_key,
                "EXOTEL_API_TOKEN": self.exotel_api_token,
            }
        elif tel == "plivo":
            need |= {"PLIVO_AUTH_ID": self.plivo_auth_id, "PLIVO_AUTH_TOKEN": self.plivo_auth_token}
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
        if self.is_live and self.secret_key.get_secret_value() == "dev-insecure-change-me":
            problems.append("FRIDAY_SECRET_KEY must be set in live mode")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings for entrypoints only. Library code receives Settings via DI."""
    return Settings()
