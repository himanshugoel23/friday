"""Numbers of refund tracking. Every default is a PROPOSAL the founder approves."""

from __future__ import annotations

from dataclasses import dataclass

from friday.core.config import Settings


@dataclass(frozen=True)
class RefundConfig:
    weekly_cap: int = 3  # refund nudges per user per rolling 7 days (all cases together)
    max_nudges_per_case: int = 8  # then the case goes quiet until the user asks
    quiet_start: int = 22  # IST, same hours as the other proactive senders
    quiet_end: int = 8
    nudge_hour: int = 10  # a day-based reminder is due at this IST hour
    expire_after_hours: int = 72  # a reminder held (quiet / cap) this long past due is dropped
    suspected_lapse_days: int = 7  # an unconfirmed suspicion is dropped (never a real case)
    amount_tolerance_paise: int = 100  # rounding / gateway fee counts as exact
    chase_calls_enabled: bool = False  # FRIDAY_REFUND_CHASE_CALLS: call proposals at all
    max_chase_calls: int = 2  # approved vendor follow-ups per case
    retention_days: int = 180  # a closed case is deleted this long after closing

    @classmethod
    def from_settings(cls, s: Settings) -> RefundConfig:
        return cls(
            weekly_cap=s.refund_weekly_cap,
            quiet_start=s.quiet_hours_start,
            quiet_end=s.quiet_hours_end,
            chase_calls_enabled=s.refund_chase_calls,
            max_chase_calls=s.refund_max_chase_calls,
            amount_tolerance_paise=s.refund_amount_tolerance_paise,
            retention_days=s.refunds_retention_days,
        )
