"""Task-engine policy knobs (BRIEF E.30-37) with safe defaults, overridable by env
(``FRIDAY_TASKS_*``). Kept local until merged into core ``Settings`` (see
docs/CORE_CHANGES.md)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TaskPolicy(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRIDAY_TASKS_", extra="ignore")

    # --- E.36 no-answer / busy retries
    max_attempts: int = 3  # total dial attempts per task (first call included)
    no_answer_delays_min: list[int] = Field(default_factory=lambda: [10, 45])
    # attempt after the listed delays: the next good window at least this far away
    final_window_gap_min: int = 120
    busy_delay_min: int = 5
    failed_delay_min: int = 5  # technical failure
    vague_callback_min: int = 120  # "call later" with no time
    try_alt_numbers: bool = True  # other listed numbers between attempts
    whatsapp_request_on_no_answer: bool = True  # short WA request if the business has WA
    business_request_template: str = "friday_biz_request"
    # --- E.30-35 call memory + inbound
    caller_ids: list[str] = Field(default_factory=list)  # Friday numbers (sticky per business)
    inbound_lookback_days: int = 30
    missed_call_notify_after: int = 3  # notify the user after N missed calls on one task
    # --- E.37 late call-backs
    better_offer_pct: int = 15  # "materially better" = at least this % cheaper
    # --- misc
    offer_question_timeout_s: int = 7200  # approval options lapse after 2h (US-3.11)
    max_progress_updates_per_call: int = 3  # US-30.3
