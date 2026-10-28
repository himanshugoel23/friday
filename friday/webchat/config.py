# ruff: noqa: E501
"""Web channel settings (env prefix ``FRIDAY_WEB_``). Names only here; values live in the server env."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")


class WebConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRIDAY_WEB_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    channel_enabled: bool = False  # FRIDAY_WEB_CHANNEL_ENABLED=true switches the channel on (default OFF)
    admin_token: str | None = None  # FRIDAY_WEB_ADMIN_TOKEN (16-64 chars): enables the admin page; unset = no page
    invite_days: float = Field(default=30.0, gt=0, le=365)  # default life of a personal invite link
    # Caps: 0 = unlimited (the pilot default; the Vobiz prepaid balance is the natural ceiling).
    messages_per_min: int = Field(default=20, ge=0, le=600)  # per tester
    max_calls_per_day: int = Field(default=0, ge=0, le=1000)  # per tester, IST day
    max_spend_inr: float = Field(default=0.0, ge=0, le=100000)  # per tester, IST day (estimate)
    global_max_spend_inr: float = Field(default=0.0, ge=0, le=1000000)  # all testers, IST day
    max_call_seconds: int = Field(default=180, ge=30, le=600)
    reply_wait_s: float = Field(default=25.0, ge=0, le=60)  # how long a send waits for Friday's first reply
    dir: str = "var/web"

    @property
    def path(self) -> Path:
        return Path(self.dir)

    def problems(self) -> list[str]:
        out: list[str] = []
        if self.admin_token is not None and not TOKEN_RE.fullmatch(self.admin_token):
            out.append("FRIDAY_WEB_ADMIN_TOKEN must be 16-64 characters: letters, digits, - or _.")
        return out
