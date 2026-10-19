"""CallGate: one deterministic allow / deny / ask decision in front of every dial (A6.8).

Same pattern as ``friday.connectors.gate.ActionGate``: the model only proposes; this code runs
afterwards and cannot be talked out of a rule. Hard refusals come first (deny wins over ask); then
the things the user can still fix (approval, number confirmation) or time can fix (calling window)
come back as ``ask`` with a reason code.

Rules, in order: kill switch and per-kind switches; user standing; abuse / safety classifier;
number validity; emergency numbers; test-mode allow-list; do-not-call registry; per-user daily call
and minute caps; per-recipient day and week caps across ALL users; approval bound to the exact
brief by hash (and fresh, and for this number); number confirmed back; calling window by kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from friday.calls import classify as cls
from friday.calls.dnc import DncRegistry
from friday.calls.models import CallBrief, CalleeKind, CallRequest
from friday.calls.numbers import NumberHasher, canonical, is_emergency
from friday.calls.settings import CallsSettings
from friday.calls.stores import CallStore
from friday.core.clock import at_ist, ist_day_bounds, to_ist
from friday.core.models import User, UserStatus
from friday.tasks.scheduling import hhmm


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class GateDecision:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)  # machine codes, never user text
    refusal_key: str | None = None  # copy key to show the user
    category: str | None = None  # classifier category for refusals and routes
    strike: bool = False  # the request counts as abuse against the user
    defer_until: datetime | None = None  # ask(outside_window): dial then
    max_duration_s: int | None = None  # allow: the hard ceiling for this call

    @property
    def allowed(self) -> bool:
        return self.verdict == Verdict.ALLOW


def _deny(code: str, key: str | None = None, **kw: Any) -> GateDecision:
    return GateDecision(Verdict.DENY, [code], refusal_key=key, **kw)


def next_window_start(kind: str, when: datetime, settings: CallsSettings) -> datetime:
    """Earliest instant >= ``when`` inside the calling window of ``kind`` (IST wall clock)."""
    (sh, sm), (eh, em) = (hhmm(x) for x in settings.window_for(kind))
    t = when
    for _ in range(3):
        local = to_ist(t)
        start, end = at_ist(local.date(), sh, sm), at_ist(local.date(), eh, em)
        if t < start:
            return start
        if t < end:
            return t
        t = at_ist(local.date() + timedelta(days=1), sh, sm)
    return t


def in_window(kind: str, when: datetime, settings: CallsSettings) -> bool:
    return next_window_start(kind, when, settings) == when


class CallGate:
    def __init__(
        self,
        *,
        store: CallStore,
        dnc: DncRegistry,
        hasher: NumberHasher,
        settings: CallsSettings | None = None,
        core_settings: Any = None,
    ) -> None:
        self.store, self.dnc, self.hasher = store, dnc, hasher
        self.settings = settings or CallsSettings()
        self.core = core_settings  # friday.core.config.Settings (pause flag, test allow-list)

    # ------------------------------------------------------------------ helpers
    def _killed(self) -> bool:
        if not self.settings.enabled:
            return True
        if self.core is not None:
            from friday.pause import is_paused

            return is_paused(self.core)
        return False

    @staticmethod
    def _texts(request: CallRequest, brief: CallBrief) -> list[str | None]:
        return [
            request.raw_text, request.purpose, brief.goal, *brief.must_say, *brief.ask_list,
            *brief.shareable_facts, brief.opening_line,
        ]  # fmt: skip

    # ------------------------------------------------------------------ the decision
    async def decide(
        self, request: CallRequest, brief: CallBrief, user: User, now: datetime
    ) -> GateDecision:
        s = self.settings
        if self._killed():
            return _deny("kill_switch", "deny_killed")
        if s.kind_disabled(request.callee_kind.value):
            return _deny("kind_disabled", "deny_kind_off")
        if user.status != UserStatus.ACTIVE or request.user_id != user.id:
            return _deny("user_not_active", "deny_user_blocked")
        if await self.store.strikes(user.id) >= s.strike_ban_threshold:
            return _deny("user_blocked", "deny_user_blocked")
        if brief.request_id != request.id or brief.user_id != user.id:
            return _deny("brief_mismatch")

        verdict = cls.classify(*self._texts(request, brief))
        if not verdict.ok:
            return GateDecision(
                Verdict.DENY,
                [f"{verdict.action}:{verdict.category}"],
                refusal_key=verdict.line_key,
                category=verdict.category,
                strike=verdict.strike,
            )

        if request.callee_kind == CalleeKind.GROUP:
            return self._group_parent(request, brief, now)

        number = request.callee_number
        if not number:
            return _deny("no_number")
        if is_emergency(number) or is_emergency(request.callee_ref or ""):
            return _deny("emergency_number", "refuse_emergency_number", category="emergency_number")
        e164 = canonical(number)
        if e164 is None:
            return _deny("invalid_number", "deny_invalid_number")
        if self.core is not None and self.core.pilot_dial_blocked(e164):
            return _deny("test_allowlist", "deny_test_mode")
        if await self.dnc.is_blocked(e164):
            return _deny("dnc", "deny_dnc")

        number_hash = self.hasher.hash(e164)
        day_start, day_end = ist_day_bounds(now)
        if await self.store.calls_between(user.id, day_start, day_end) >= s.daily_call_cap:
            return _deny("user_daily_calls", "deny_cap_user_calls")
        planned = min(brief.limits.max_duration_s or s.max_call_seconds, s.max_call_seconds)
        used_s = await self.store.seconds_between(user.id, day_start, day_end)
        if (used_s + planned) / 60 > s.daily_minute_cap:
            return _deny("user_daily_minutes", "deny_cap_user_minutes")
        if await self.store.number_calls_since(number_hash, day_start) >= s.number_day_cap:
            return _deny("number_day_cap", "deny_cap_number")
        if await self.store.number_calls_since(number_hash, now - timedelta(days=7)) >= (
            s.number_week_cap
        ):
            return _deny("number_week_cap", "deny_cap_number")

        asks: list[str] = []
        if not brief.approved or not brief.approval_hash:
            asks.append("approval_missing")
        elif brief.approval_hash != brief.content_hash() or brief.callee_number_hash != number_hash:
            asks.append("approval_stale")
        elif brief.approved_at and now - brief.approved_at > timedelta(hours=s.approval_ttl_hours):
            asks.append("approval_expired")
        if not request.number_confirmed:
            asks.append("number_unconfirmed")
        defer: datetime | None = None
        if not in_window(request.callee_kind.value, now, s):
            asks.append("outside_window")
            defer = next_window_start(request.callee_kind.value, now, s)
        if asks:
            return GateDecision(Verdict.ASK, asks, defer_until=defer)
        return GateDecision(Verdict.ALLOW, ["ok"], max_duration_s=planned)

    def _group_parent(self, request: CallRequest, brief: CallBrief, now: datetime) -> GateDecision:
        """The parent never dials; it only needs a sane size and the user's approval. Every child
        goes through ``decide`` on its own number."""
        if len(request.group_members) > self.settings.group_max_members:
            return _deny("group_too_big", "deny_group_too_big")
        if not brief.is_approved_as_is():
            reason = "approval_stale" if brief.approved else "approval_missing"
            return GateDecision(Verdict.ASK, [reason])
        return GateDecision(Verdict.ALLOW, ["group_parent"])
