"""Consumer-call settings (env prefix ``FRIDAY_CALLS_``). Kept apart from core ``Settings`` so the
parallel workstreams do not collide in one file. Names only here; values live in the server env.

Never reads a .env file by itself: the process environment is the only source.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CallsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRIDAY_CALLS_", env_file=None, extra="ignore")

    enabled: bool = True  # master kill switch for consumer calls (FRIDAY_CALLS_ENABLED=false)
    disabled_kinds: str = ""  # CSV of callee kinds switched off, e.g. "unknown,group"
    # per-user safety caps (per IST day)
    daily_call_cap: int = Field(default=10, ge=0)
    daily_minute_cap: int = Field(default=30, ge=0)
    max_call_seconds: int = Field(default=300, ge=30)  # hard per-call ceiling
    # `friday consumer call-test`: the default (and highest) length of the founder's test call
    test_call_seconds: int = Field(default=150, ge=30, le=300)
    # per-recipient frequency across ALL users
    number_day_cap: int = Field(default=3, ge=0)  # >= retry attempts of one request
    number_week_cap: int = Field(default=6, ge=0)
    # calling windows (IST, "HH:MM-HH:MM"), per callee kind
    window_business: str = "09:00-19:00"
    window_provider: str = "09:00-19:00"
    window_customer_care: str = "09:00-19:00"
    window_official: str = "09:00-19:00"
    window_unknown: str = "09:00-19:00"
    window_family_friend: str = "08:00-21:30"
    window_group: str = "09:00-19:00"
    strike_ban_threshold: int = Field(default=3, ge=1)  # abuse strikes before a user is blocked
    approval_ttl_hours: int = Field(default=24, ge=1)  # an approval older than this is stale
    recording_retention_days: int = Field(default=30, ge=1, le=365)
    group_max_members: int = Field(default=10, ge=1)
    retry_max_attempts: int = Field(default=3, ge=1, le=5)  # via the existing task policy

    def kind_disabled(self, kind: str) -> bool:
        return kind in {k.strip() for k in self.disabled_kinds.split(",") if k.strip()}

    def window_for(self, kind: str) -> tuple[str, str]:
        raw = getattr(self, f"window_{kind}", self.window_business)
        start, _, end = raw.partition("-")
        return start.strip(), end.strip()
