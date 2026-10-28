# ruff: noqa: E501
"""QA settings (env prefix ``FRIDAY_QA_``). Names only here; values live in the server env.

Never reads a .env file by itself: the process environment is the only source (the server's
settings loader fills the environment first).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APPROVAL_PHRASE = "YES, call my phone"  # typed or tapped; compared exactly
HARD_MAX_CALL_SECONDS = 180  # a QA call never lasts longer than 3 minutes, whatever is configured
DEFAULT_PORT = 8767


class QaConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRIDAY_QA_", env_file=None, extra="ignore")

    live: bool = False  # FRIDAY_QA_LIVE=true switches QA mode on (default OFF)
    max_calls_per_day: int = Field(default=20, ge=1, le=100)
    max_spend_inr: float = Field(default=100.0, gt=0, le=2000)  # per IST day, estimated
    call_seconds: int = Field(default=HARD_MAX_CALL_SECONDS, ge=30)
    countdown_s: int = Field(default=10, ge=0, le=60)  # the visible "ring now" countdown
    urgent_wait_minutes: int = Field(
        default=2, ge=1, le=5
    )  # urgent scenario: minutes before the call
    dir: str = "var/qa"

    @property
    def seconds(self) -> int:
        return min(self.call_seconds, HARD_MAX_CALL_SECONDS)

    @property
    def path(self) -> Path:
        return Path(self.dir)
