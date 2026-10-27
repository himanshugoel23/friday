# ruff: noqa: E501
"""The decisions of the urgent-call escalation, as plain code (no I/O, no clock of its own).

``is_emergency``  which classifier reasons count as a TRUE emergency (the only thing that may ring in
                  quiet hours). Code rules only: a model verdict, an "urgent contact", a custom user
                  keyword or a weak word ("urgent", "jaldi") is URGENT but never an emergency.
``plan``          the timer of one escalation (per-user override on top of the defaults).
``decide``        what to do with one due escalation right now.

Design rule: every doubt resolves to NOT ringing. A phone call is the most intrusive thing Friday can
do, so a stale alert, a switched-off feature, a missing opt-in or a rule that cannot be checked all
cancel or refuse; none of them calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from friday.urgent.models import (
    MAX_CALLS_LIMIT,
    Decision,
    EscalationState,
    EscStatus,
    Policy,
    UserEscalationConfig,
)

# Subset of the receptionist's STRONG_URGENT words that mean danger to life or safety right now.
# Illness/"tabiyat", "serious", "operation", "madad" are urgent but not emergencies.
EMERGENCY_WORDS = frozenset(
    {
        "emergency", "accident", "ambulance", "heart attack", "ventilator", "unconscious", "injured",
        "died", "death", "passed away", "kidnap", "fire", "icu", "bachao", "behosh", "haadsa", "hadsa",
        "dil ka daura", "chot lagi", "emergency hai", "guzar", "nidhan",
        "इमरजेंसी", "एमरजेंसी", "एक्सीडेंट", "हादसा", "एम्बुलेंस", "बेहोश", "बचाओ", "निधन", "आईसीयू",
    }
)  # fmt: skip
_PREFIX = "urgent word: "


def is_emergency(reasons: list[str], *, source: str = "rules") -> bool:
    """True only when a built-in strong word from the emergency list fired in the code rules."""
    if source != "rules":
        return False
    return any(r.startswith(_PREFIX) and r[len(_PREFIX):].strip().lower() in EMERGENCY_WORDS for r in reasons)


@dataclass(frozen=True)
class Plan:
    wait_s: int
    max_calls: int
    spacing_s: int


def plan(cfg: UserEscalationConfig | None, policy: Policy) -> Plan:
    cfg = UserEscalationConfig.model_validate((cfg or UserEscalationConfig()).model_dump())  # re-clamp
    return Plan(
        wait_s=(cfg.minutes * 60) if cfg.minutes else policy.wait_s,
        max_calls=min(cfg.max_calls or policy.max_calls, MAX_CALLS_LIMIT),
        spacing_s=(cfg.spacing_minutes * 60) if cfg.spacing_minutes else policy.spacing_s,
    )


@dataclass(frozen=True)
class Facts:
    """Everything ``decide`` needs that is not on the state row."""

    switch_on: bool
    paused: bool  # the kill switch
    user_active: bool
    opted_in: bool
    own_number: str | None  # the user's phone as Friday has it
    cfg_number: str | None  # the number the user opted in with
    in_quiet_hours: bool
    emergency_in_quiet: bool  # the user allows emergencies to ring in quiet hours
    daily_capped: bool


def decide(st: EscalationState, now: datetime, facts: Facts, policy: Policy) -> Decision:
    if st.status != EscStatus.PENDING:
        return Decision(action="wait", reason="not_open")
    if st.next_action_at is None or now < st.next_action_at:
        return Decision(action="wait", reason="not_due")
    if facts.paused:
        return Decision(action="cancel", reason="kill_switch", status=EscStatus.CANCELLED)
    if not facts.switch_on:
        return Decision(action="cancel", reason="switch_off", status=EscStatus.CANCELLED)
    if now - st.next_action_at > timedelta(seconds=policy.stale_s):
        return Decision(action="cancel", reason="stale", status=EscStatus.CANCELLED)
    if st.calls_made >= st.max_calls:
        return Decision(action="cancel", reason="no_calls_left", status=EscStatus.EXHAUSTED)
    if not facts.user_active:
        return Decision(action="cancel", reason="user_not_active", status=EscStatus.CANCELLED)
    if not facts.opted_in:
        return Decision(action="cancel", reason="not_opted_in", status=EscStatus.CANCELLED)
    if not facts.own_number or facts.cfg_number != facts.own_number:
        return Decision(action="refuse", reason="not_own_number", status=EscStatus.REFUSED)
    if facts.in_quiet_hours and not (st.emergency and facts.emergency_in_quiet):
        return Decision(action="cancel", reason="quiet_hours", status=EscStatus.CANCELLED)
    if st.calls_made == 0 and facts.daily_capped:
        return Decision(action="cancel", reason="daily_cap", status=EscStatus.CANCELLED)
    return Decision(action="call", reason="due")
