"""Settings of the savings engine (kept here so this package merges without touching Settings).

Each value can be overridden with an environment variable ``FRIDAY_SAVINGS_<NAME>``; the defaults
are the policy documented in docs/SAVINGS_ENGINE.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(f"FRIDAY_SAVINGS_{name}")
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"FRIDAY_SAVINGS_{name}")
    return default if raw in (None, "") else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SavingsConfig:
    # a rule checked longer ago than this is flagged "confirm on your card app"
    stale_after_days: int = field(default_factory=lambda: _env_int("STALE_AFTER_DAYS", 30))
    # older than this the rule is shown with LOW confidence
    very_stale_after_days: int = field(
        default_factory=lambda: _env_int("VERY_STALE_AFTER_DAYS", 90)
    )
    # EXAMPLE rows (example.invalid) are served only when this is on (dev and tests)
    allow_example_rules: bool = field(
        default_factory=lambda: _env_bool("ALLOW_EXAMPLE_RULES", False)
    )
    # bill reminders: days before the due date (0 = on the day), sent at this IST hour
    bill_reminder_days: tuple[int, ...] = (3, 1, 0)
    bill_reminder_hour_ist: int = field(default_factory=lambda: _env_int("BILL_HOUR_IST", 9))
    # how many options a "kaun sa card" answer lists
    max_options_shown: int = 3
    # sanity bounds on a rule's rate (basis points)
    max_rate_bp_reward: int = 2500
    max_rate_bp_discount: int = 5000


DEFAULT_CONFIG = SavingsConfig()
