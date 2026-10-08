"""Task-engine policy knobs (BRIEF E.30-37), read from core ``Settings.tasks_*``
(env ``FRIDAY_TASKS_*``) and ``Settings.friday_numbers``. A plain view object so tests
can override single values without touching the environment."""

from __future__ import annotations

from pydantic import BaseModel, Field

from friday.core.config import Settings

_FIELDS = (
    "max_attempts",
    "no_answer_delays_min",
    "final_window_gap_min",
    "busy_delay_min",
    "failed_delay_min",
    "vague_callback_min",
    "try_alt_numbers",
    "whatsapp_request_on_no_answer",
    "business_request_template",
    "inbound_lookback_days",
    "missed_call_notify_after",
    "better_offer_pct",
    "offer_question_timeout_s",
    "max_progress_updates_per_call",
)


class TaskPolicy(BaseModel):
    max_attempts: int = 3
    no_answer_delays_min: list[int] = Field(default_factory=lambda: [10, 45])
    final_window_gap_min: int = 120
    busy_delay_min: int = 5
    failed_delay_min: int = 5
    vague_callback_min: int = 120
    try_alt_numbers: bool = True
    whatsapp_request_on_no_answer: bool = True
    business_request_template: str = "friday_biz_request"
    inbound_lookback_days: int = 30
    missed_call_notify_after: int = 3
    better_offer_pct: int = 15
    offer_question_timeout_s: int = 7200
    max_progress_updates_per_call: int = 3
    caller_ids: list[str] = Field(default_factory=list)  # Settings.friday_numbers

    @classmethod
    def from_settings(cls, s: Settings, **overrides: object) -> TaskPolicy:
        values = {f: getattr(s, f"tasks_{f}") for f in _FIELDS}
        values["caller_ids"] = list(s.friday_numbers)
        return cls(**{**values, **overrides})
