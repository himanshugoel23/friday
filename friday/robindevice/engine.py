"""Scenario engine: turns a parent's stored signal events into findings (S1-S8), then decides what to do
with them: shadow-mode logging, cooldowns, 'this was fine' learning, quiet hours, the nudge ceiling,
a parent prompt payload and AlertPort calls.

Rules are DATA (``scenarios.yaml``); the named checks below are the only code. The 'why' string is built
from signal types and numbers only. Nothing here blocks, calls or contacts a bank or the police.
"""

from __future__ import annotations

import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from friday.core.clock import IST
from friday.core.logging import get_logger
from friday.robindevice import copy as C
from friday.robindevice.ports import (
    CONSENT_ITEMS,
    TIER_RANK,
    AlertPort,
    ConsentPort,
    ParentInfo,
    ParentLookup,
)
from friday.robindevice.rules import Rules, Scenario, SignalDef, TierDef
from friday.robindevice.store import Event, Fired, ParentState, Prompt

log = get_logger(__name__)

MIN = 60_000
ACTIVE_GAP_MS = 8 * MIN  # an off-hook call with no update for this long is treated as ended
RING_MS = 90_000
CAMERA_OPEN_CAP_MS = 2 * 3_600_000  # a camera 'start' with no 'stop' counts for at most this long
TIER_BY_RANK = {v: k for k, v in TIER_RANK.items()}


# ----------------------------------------------------------------------------- helpers


def format_inr(paise: int) -> str:
    rupees = paise // 100
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"Rs {s}"


def ist(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, IST)


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_window(ms: int, start: str, end: str) -> bool:
    """Is the IST clock time of ``ms`` inside [start, end), where the window may cross midnight?"""
    t = ist(ms)
    cur = t.hour * 60 + t.minute
    a, b = _hhmm(start), _hhmm(end)
    return a <= cur < b if a <= b else (cur >= a or cur < b)


def next_clock(ms: int, hhmm: str) -> int:
    t = ist(ms)
    h, m = (int(x) for x in hhmm.split(":"))
    target = t.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= t:
        target += timedelta(days=1)
    return int(target.timestamp() * 1000)


def awake_overlap_hours(start_ms: int, end_ms: int, awake_start: str = "07:00", awake_end: str = "22:00") -> float:
    """Hours of [start,end] that fall inside the daily awake window (IST), minute resolution."""
    if end_ms <= start_ms:
        return 0.0
    total = 0
    t = start_ms
    while t < end_ms:
        if in_window(t, awake_start, awake_end):
            total += min(MIN, end_ms - t)
        t += MIN
    return total / 3_600_000


# ----------------------------------------------------------------------------- derived views


@dataclass
class Call:
    id: str
    start: int
    cls: str
    hash: str | None
    direction: str = "incoming"
    end: int | None = None
    ended_dur_s: int | None = None
    ended_answered: bool = False
    off_last: int = 0
    off_dur_s: int = 0
    off_ongoing: bool = False

    @property
    def answered(self) -> bool:
        return self.ended_answered or self.off_last > 0

    def active(self, now: int) -> bool:
        if self.end is not None:
            return False
        if self.off_last:
            return self.off_ongoing and now - self.off_last <= ACTIVE_GAP_MS
        return now - self.start <= RING_MS

    def duration_s(self, now: int) -> float:
        if not self.answered:
            return 0.0
        if self.end is not None:
            base = self.ended_dur_s if self.ended_dur_s is not None else (self.end - self.start) / 1000
            return float(max(base, self.off_dur_s))
        if self.off_last and self.active(now):
            return self.off_dur_s + (now - self.off_last) / 1000
        return float(self.off_dur_s)

    def last_ms(self, now: int) -> int:
        if self.end is not None:
            return self.end
        return now if self.active(now) else max(self.off_last, self.start)


def build_calls(events: list[Event], trusted: set[str]) -> list[Call]:
    calls: dict[str, Call] = {}
    order: list[Call] = []
    for e in sorted(events, key=lambda x: x.ts_ms):
        d = e.data
        if e.type == "unknown_call_started":
            c = Call(d["call_id"], e.ts_ms, d["number_class"], d.get("number_hash"), d.get("direction", "incoming"))
            calls[c.id] = c
            order.append(c)
        elif e.type == "unknown_call_ended":
            c = calls.get(d["call_id"])
            if c is None:
                c = Call(d["call_id"], e.ts_ms - d["duration_s"] * 1000, "mobile", None)
                calls[c.id] = c
                order.append(c)
            c.end, c.ended_dur_s, c.ended_answered = e.ts_ms, d["duration_s"], bool(d["answered"])
        elif e.type == "call_state_offhook":
            c = calls.get(d.get("call_id") or "")
            if c is None:
                open_ = [x for x in order if x.end is None and 0 <= e.ts_ms - x.start <= 3 * 3_600_000]
                c = open_[-1] if open_ else None
            if c is None:
                continue  # an off-hook with no unknown call is an ordinary call: ignored on purpose
            c.off_last, c.off_dur_s, c.off_ongoing = e.ts_ms, max(c.off_dur_s, d["duration_s"]), bool(d["ongoing"])
            if not d["ongoing"] and c.end is None:
                c.end = e.ts_ms
    return [c for c in order if not (c.hash and c.hash in trusted)]


def camera_intervals(events: list[Event], now: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start: int | None = None
    for e in sorted(events, key=lambda x: x.ts_ms):
        if e.type == "camera_in_use_start":
            if start is not None:
                out.append((start, min(e.ts_ms, start + CAMERA_OPEN_CAP_MS)))
            start = e.ts_ms
        elif e.type == "camera_in_use_stop" and start is not None:
            out.append((start, e.ts_ms))
            start = None
    if start is not None:
        out.append((start, min(now, start + CAMERA_OPEN_CAP_MS)))
    return out


@dataclass
class Ctx:
    now: int
    st: ParentState
    rules: Rules
    scale: float
    threshold: int
    window_ms: int
    events: list[Event]
    calls: list[Call]
    cams: list[tuple[int, int]]
    anchor: Event | None = None

    def of_type(self, *types: str) -> list[Event]:
        return [e for e in self.events if e.type in types]

    def live_calls(self) -> list[Call]:
        return [c for c in self.calls if c.last_ms(self.now) >= self.now - self.window_ms]


# ----------------------------------------------------------------------------- the named checks
# Each returns None (no match) or a dict of placeholders for the 'why' line; '_last' = newest relevant time.


def _best_call(ctx: Ctx, pred: Callable[[Call], bool]) -> Call | None:
    best = None
    for c in ctx.live_calls():
        if pred(c) and (best is None or c.duration_s(ctx.now) > best.duration_s(ctx.now)):
            best = c
    return best


def p_unknown_call_min(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    need = p["min_minutes"] * ctx.scale * 60
    recent = p.get("active_or_recent_min")

    def ok(c: Call) -> bool:
        if c.duration_s(ctx.now) < need:
            return False
        return recent is None or c.active(ctx.now) or (c.end is not None and ctx.now - c.end <= recent * MIN)

    c = _best_call(ctx, ok)
    if c is None:
        return None
    return {"minutes": int(c.duration_s(ctx.now) // 60), "call_class": c.cls, "call_hash": c.hash, "_last": c.last_ms(ctx.now)}


def p_call_class(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    c = _best_call(ctx, lambda c: c.cls in p["classes"] and c.answered)
    if c is None:
        return None
    return {"call_class": c.cls, "call_hash": c.hash, "_last": c.last_ms(ctx.now)}


def p_camera_during_call(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    for c in ctx.live_calls():
        if not c.answered:
            continue
        end = c.end if c.end is not None else ctx.now
        for s, e in ctx.cams:
            if s <= end and e >= c.start:
                return {"_last": min(max(s, c.start), end)}
    return None


def p_camera_at_night(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    for e in reversed(ctx.of_type("camera_in_use_start")):
        if in_window(e.ts_ms, p["start"], p["end"]):
            return {"_last": e.ts_ms}
    return None


def _latest(ctx: Ctx, etype: str) -> Event | None:
    ev = ctx.of_type(etype)
    return max(ev, key=lambda e: e.ts_ms) if ev else None


def p_remote_app_opened(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    e = _latest(ctx, "remote_access_app_opened")
    return {"app": e.data["app"], "_last": e.ts_ms} if e else None


def p_remote_app_installed(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    e = _latest(ctx, "remote_access_app_installed")
    return {"app": e.data["app"], "_last": e.ts_ms} if e else None


def p_remote_app_near_call(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    for e in ctx.of_type("remote_access_app_opened", "remote_access_app_installed"):
        for c in ctx.calls:
            near = c.start <= e.ts_ms and (c.end is None or e.ts_ms - c.end <= p["within_min"] * MIN)
            if near and c.answered:
                return {"minutes": max(1, int(c.duration_s(ctx.now) // 60)), "_last": e.ts_ms}
    return None


def p_payment_app_after_call(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    for e in sorted(ctx.of_type("payment_app_foreground"), key=lambda x: -x.ts_ms):
        for c in ctx.calls:
            if not c.answered or e.ts_ms < c.start or e.ts_ms - c.start > p["within_min"] * MIN:
                continue
            if c.end is not None and e.ts_ms - c.end > p["ended_within_min"] * MIN:
                continue
            return {"app": e.data["app"], "gap_min": int((e.ts_ms - c.start) // MIN), "call_hash": c.hash, "_last": e.ts_ms}
    return None


def p_short_unknown_call(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    best = None
    for c in ctx.live_calls():
        d = c.duration_s(ctx.now)
        if c.end is not None and c.answered and 5 <= d <= p["max_minutes"] * 60:
            best = c if best is None or c.end > (best.end or 0) else best
    if best is None:
        return None
    return {"minutes": max(1, math.ceil(best.duration_s(ctx.now) / 60)), "call_hash": best.hash, "_last": best.end}


def p_recent_debit_new_payee(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    for e in sorted(ctx.of_type("payment_notification"), key=lambda x: -x.ts_ms):
        d = e.data
        if d["direction"] == "debit" and d["payee_kind"] in ("new", "unknown") and ctx.now - e.ts_ms <= p["within_min"] * MIN:
            return {"payee_kind": d["payee_kind"], "_last": e.ts_ms}
    return None


def _anchor(ctx: Ctx) -> Event | None:
    return ctx.anchor if ctx.anchor and ctx.anchor.type == "payment_notification" else None


def p_payment_debit(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    a = _anchor(ctx)
    if a is None or a.data["direction"] != "debit" or a.data["amount_paise"] < p["min_amount_paise"]:
        return None
    return {"amount": format_inr(a.data["amount_paise"]), "time": ist(a.ts_ms).strftime("%H:%M"), "_last": a.ts_ms}


def p_payment_over_threshold(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    a = _anchor(ctx)
    return {} if a and a.data["direction"] == "debit" and a.data["amount_paise"] >= ctx.threshold else None


def p_payment_payee(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    a = _anchor(ctx)
    if a and a.data["direction"] == "debit" and a.data["payee_kind"] in p["kinds"]:
        return {"payee_kind": a.data["payee_kind"]}
    return None


def p_payment_night(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    a = _anchor(ctx)
    night = ctx.rules.defaults["night_hours"]
    if a and a.data["direction"] == "debit" and a.data["payee_kind"] in p["kinds"] and in_window(a.ts_ms, night["start"], night["end"]):
        return {}
    return None


def p_payment_after_risk(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    a = _anchor(ctx)
    if a is None or a.data["direction"] != "debit":
        return None
    within = p["within_min"] * MIN
    for c in ctx.calls:
        long_enough = c.duration_s(ctx.now) >= p["call_min_minutes"] * 60
        if c.answered and long_enough and c.start <= a.ts_ms and (c.end is None or a.ts_ms - c.end <= within):
            return {"risk": f"after unknown call {int(c.duration_s(ctx.now) // 60)} minutes"}
    for e in ctx.of_type("remote_access_app_opened"):
        if 0 <= a.ts_ms - e.ts_ms <= within:
            return {"risk": "after remote-control app opened"}
    return None


_PT_RANK = {"NONE": 0, "INFO": 1, "WATCH": 2, "HIGH": 3}


def p_call_pattern_tier(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    """Latest conversation-pattern result (internal 'call_pattern' event) reaches the given tier."""
    evs = ctx.of_type("call_pattern")
    if not evs:
        return None
    e = max(evs, key=lambda x: x.ts_ms)
    if _PT_RANK[e.data["tier"]] < _PT_RANK[p["tier"]]:
        return None
    return {"cues": ", ".join(e.data["cue_ids"][:4]), "_last": e.ts_ms}


def p_heartbeat_gap_hours(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    dev = ctx.st.device
    if dev is None:
        return None
    need = p["min_hours"] * ctx.scale
    gap = awake_overlap_hours(dev.last_seen_ms, ctx.now) if p.get("awake_only") else (ctx.now - dev.last_seen_ms) / 3_600_000
    if gap < need:
        return None
    return {"hours": int((ctx.now - dev.last_seen_ms) // 3_600_000), "_last": dev.last_seen_ms}


def p_checkin_unanswered(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    ts = ctx.st.external.get("checkin_unanswered")
    return {} if ts and ctx.now - ts <= 24 * 3_600_000 else None


def p_battery_was_low(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    return {} if ctx.st.device and ctx.st.device.battery_low else None


def p_calendar_window(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any] | None:
    today = ist(ctx.now).strftime("%m-%d")
    a, b = p["start"], p["end"]
    ok = a <= today <= b if a <= b else (today >= a or today <= b)
    return {"_last": ctx.now} if ok else None


PREDICATES: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any] | None]] = {
    "unknown_call_min": p_unknown_call_min,
    "call_class": p_call_class,
    "camera_during_call": p_camera_during_call,
    "camera_at_night": p_camera_at_night,
    "remote_app_opened": p_remote_app_opened,
    "remote_app_installed": p_remote_app_installed,
    "remote_app_near_call": p_remote_app_near_call,
    "payment_app_after_call": p_payment_app_after_call,
    "short_unknown_call": p_short_unknown_call,
    "recent_debit_new_payee": p_recent_debit_new_payee,
    "payment_debit": p_payment_debit,
    "payment_over_threshold": p_payment_over_threshold,
    "payment_payee": p_payment_payee,
    "payment_night": p_payment_night,
    "payment_after_risk": p_payment_after_risk,
    "call_pattern_tier": p_call_pattern_tier,
    "heartbeat_gap_hours": p_heartbeat_gap_hours,
    "checkin_unanswered": p_checkin_unanswered,
    "battery_was_low": p_battery_was_low,
    "calendar_window": p_calendar_window,
}


# ----------------------------------------------------------------------------- findings


@dataclass
class Finding:
    sc: Scenario
    tdef: TierDef
    tier: str
    score: float
    why: str
    matched: tuple[str, ...]
    key: str
    last_ms: int
    call_hash: str | None
    details: dict[str, Any]
    pattern: str
    notes: list[str] = field(default_factory=list)


def _fragment(sig: SignalDef, vars_: dict[str, Any]) -> str:
    if not sig.why:
        return ""
    clean = {k: v for k, v in vars_.items() if not k.startswith("_")}
    try:
        return sig.why.format(**clean)
    except (KeyError, IndexError):
        return sig.why.split("{")[0].strip()


def evaluate_scenario(sc: Scenario, ctx: Ctx, shift: float) -> list[Finding]:
    anchors: list[Event | None] = [None]
    if sc.anchor:
        anchors = [e for e in ctx.of_type(sc.anchor) if ctx.now - e.ts_ms <= sc.window_ms()]
    out: list[Finding] = []
    for anchor in anchors:
        ctx.anchor = anchor
        score = 0.0
        matched: list[str] = []
        frags: list[str] = []
        vars_all: dict[str, Any] = {}
        last = 0
        ok = True
        for sig in sc.signals:
            r = PREDICATES[sig.predicate](ctx, sig.params)
            if r is None:
                if sig.required:
                    ok = False
                    break
                continue
            score += sig.weight
            matched.append(sig.id)
            vars_all.update({k: v for k, v in r.items() if not k.startswith("_") and k not in vars_all})
            last = max(last, r.get("_last", 0))
            f = _fragment(sig, r)
            if f:
                frags.append(f)
        ctx.anchor = None
        if not ok:
            continue
        eff = shift if sc.shiftable else 0
        chosen = None
        for t in sc.tiers:
            if score >= t.min_score + eff:
                chosen = t
        if chosen is None:
            continue
        key = f"{sc.id}:{anchor.id}" if anchor else sc.id
        if anchor is not None:
            d = anchor.data
            details: dict[str, Any] = {
                "amount_paise": d["amount_paise"], "direction": d["direction"],
                "ts_ms": anchor.ts_ms, "payee_kind": d["payee_kind"],
            }
        else:
            details = {"scenario_name": sc.name, "score": score}
        out.append(
            Finding(sc, chosen, chosen.tier, score, " + ".join(frags), tuple(matched), key,
                    last or ctx.now, vars_all.get("call_hash"), details, f"{sc.id}:{'+'.join(matched)}")
        )
    return out


def known_predicates() -> set[str]:
    return set(PREDICATES)


# ----------------------------------------------------------------------------- the engine


@dataclass
class RunResult:
    shadow: bool = False
    paused: bool = False
    alerts: int = 0
    prompts: list[Prompt] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)


class ScenarioEngine:
    def __init__(
        self,
        rules: Rules,
        alerts: AlertPort,
        consent: ConsentPort,
        parents: ParentLookup,
        *,
        brand: str = "Friday",
    ) -> None:
        self.rules = rules
        self.alerts = alerts
        self.consent = consent
        self.parents = parents
        self.brand = brand

    # --- shadow
    def shadow_days(self, st: ParentState) -> int:
        return st.shadow_days if st.shadow_days is not None else int(self.rules.defaults["shadow_days"])

    def in_shadow(self, st: ParentState, now: int) -> bool:
        if st.shadow_start_ms is None:
            return True
        return now < st.shadow_start_ms + self.shadow_days(st) * 86_400_000

    # --- main entry
    async def run(self, st: ParentState, now: int, info: ParentInfo | None = None) -> RunResult:
        res = RunResult()
        if st.paused_until_ms > now:
            res.paused = True
            return res
        info = info or await self.parents.get(st.parent_id)
        if info is None:
            return res
        d = self.rules.defaults
        sens = self.rules.sensitivity[st.sensitivity]
        consents = {i for i in CONSENT_ITEMS if await self.consent.has(st.parent_id, i)}
        horizon = now - int(d.get("retention_h", 48)) * 3_600_000
        st.events = [e for e in st.events if e.ts_ms >= horizon]
        shadow = self.in_shadow(st, now)
        res.shadow = shadow
        threshold = st.payment_threshold_paise or int(d["payment_threshold_paise"])
        max_window = max(sc.window_min for sc in self.rules.scenarios) * MIN
        base_events = [e for e in st.events if e.ts_ms >= now - max_window]
        calls = build_calls(base_events, st.trusted)
        cams = camera_intervals(base_events, now)
        cands: list[Finding] = []
        for sc in self.rules.scenarios:
            if sc.applies_if_tag and info.tags is not None and sc.applies_if_tag not in info.tags:
                continue
            if any(c not in consents for c in sc.needs_consent):
                continue
            if sc.unless_events and any(e.type in sc.unless_events for e in base_events):
                continue
            wnd = sc.window_min * MIN
            ctx = Ctx(now, st, self.rules, float(sens["duration_scale"]), threshold, wnd,
                      [e for e in base_events if e.ts_ms >= now - wnd], calls, cams)
            cands.extend(evaluate_scenario(sc, ctx, float(sens["threshold_shift"])))
        cands.sort(key=lambda f: (-TIER_RANK[f.tier], f.sc.priority))
        top_done = False
        nudged = False
        for f in cands:
            sc = f.sc
            shadow_eff = shadow and not sc.shadow_exempt
            if not self._pass_dedupe(st, f, now, shadow_eff):
                continue
            self._apply_learning(st, f, now)
            row = {"ts_ms": now, "scenario": sc.id, "tier": f.tier, "score": f.score, "why": f.why,
                   "shadow": shadow_eff, "key": f.key}
            if shadow_eff:
                self._shadow_count(st, f, now)
                st.fired[f.key] = _fired(f, now, True)
                st.log({**row, "outcome": "shadow"})
                res.findings.append({**row, "outcome": "shadow"})
                continue
            st.fired[f.key] = _fired(f, now, False)
            send_child = f.tdef.child_alert and (f.sc.anchor is not None or not top_done)
            if f.sc.anchor is None and f.tdef.child_alert:
                top_done = True
            if send_child:
                also = [x.sc.name for x in cands if x is not f and x.sc.anchor is None and x.key != f.key] if f.sc.anchor is None else []
                if also:
                    f.details["also"] = also
                await self._alert(st, f, now, res)
            prompt = None
            if f.tdef.prompt and not nudged:
                nudged = True
                prompt = self._make_prompt(st, f, now, info, res)
            outcome = "alerted" if send_child else "merged"
            if prompt is not None:
                outcome += "+prompt"
            st.log({**row, "outcome": outcome})
            res.findings.append({**row, "outcome": outcome})
        return res

    # --- dedupe, cooldown, learning
    def _pass_dedupe(self, st: ParentState, f: Finding, now: int, shadow_eff: bool) -> bool:
        rec = st.fired.get(f.key)
        if rec is not None and rec.shadow != shadow_eff:
            rec = None  # a shadow-week record never blocks a live alert
        rank = TIER_RANK[f.tier]
        if rec is not None:
            if rec.resolved_until_ms > now:
                st.bump("skipped:resolved")
                return False
            fresh = now - rec.ts_ms < f.sc.cooldown_min * MIN
            if rank <= rec.rank and (f.sc.anchor is not None or fresh):
                st.bump("skipped:cooldown")
                return False
        return True

    def _apply_learning(self, st: ParentState, f: Finding, now: int) -> None:
        sc = f.sc
        if sc.name == "remote_access" and st.support_window_until_ms > now:
            f.tier, f.tdef = "INFO", _info_def(f.tdef)
            f.notes.append("support_window")
            st.bump("downgraded:support_window")
            return
        if sc.suppressible and st.fine_counts.get(f.pattern, 0) >= 2 and TIER_RANK[f.tier] > 0:
            lower = TIER_BY_RANK[TIER_RANK[f.tier] - 1]
            tdef = next((t for t in sc.tiers if t.tier == lower), None)
            f.tier, f.tdef = lower, tdef or _info_def(f.tdef)
            f.notes.append("suppressed_pattern")
            st.bump("downgraded:suppressed_pattern")

    def _shadow_count(self, st: ParentState, f: Finding, now: int) -> None:
        st.bump(f"shadow:{f.sc.id}:{f.tier}")
        if f.tdef.child_alert:
            st.bump("shadow:would_alert_child")
        if f.tdef.prompt and now - f.last_ms <= int(self.rules.defaults["prompt_max_age_min"]) * MIN:
            st.bump("shadow:would_nudge")
            limit = int(self.rules.defaults["nudges_per_hour"])
            sim = st.shadow_nudge_times
            sim[:] = [t for t in sim if t > now - 3_600_000]
            if len(sim) >= limit:
                st.bump("shadow:would_nudge_ceiling_blocked")
            else:
                sim.append(now)

    # --- outputs
    async def _alert(self, st: ParentState, f: Finding, now: int, res: RunResult) -> None:
        details = dict(f.details)
        if f.last_ms < now - 30 * MIN:
            details["late"] = True
        if f.tdef.digest:
            details["digest"] = True
        if f.sc.money and TIER_RANK[f.tier] >= TIER_RANK["HIGH"]:
            details["money"] = True  # the scenario's rules.yaml flag, which the family side needs for the money note and the quiet-hours / calling-window exception
        if ":" in f.key:  # an event-anchored finding (S5: one payment = one incident): the family engine must not merge two payments inside its 5-minute bucket
            details["dedupe_key"] = f"{f.key}:{f.tier}"
        await self.alerts.raise_alert(st.parent_id, f.tier, f.sc.id, f.why or f.sc.name, details)
        st.record_audit({"ts_ms": now, "tier": f.tier, "scenario": f.sc.id, "why": f.why or f.sc.name, "details": details})
        if f.sc.id == "S7":
            st.s7_open = True
        res.alerts += 1

    def _make_prompt(self, st: ParentState, f: Finding, now: int, info: ParentInfo, res: RunResult) -> Prompt | None:
        d = self.rules.defaults
        if now - f.last_ms > int(d["prompt_max_age_min"]) * MIN:
            st.bump("nudge_skipped:old")
            return None
        quiet = d["quiet_hours"]
        not_before = now
        if in_window(now, quiet["start"], quiet["end"]):
            allowed = TIER_RANK[f.tier] >= TIER_RANK["HIGH"] and f.sc.money
            if not allowed:
                if f.tdef.defer_quiet:
                    not_before = next_clock(now, quiet["end"])
                else:
                    st.bump("nudge_skipped:quiet_hours")
                    return None
        st.nudge_times[:] = [t for t in st.nudge_times if t > now - 3_600_000]
        if len(st.nudge_times) >= int(d["nudges_per_hour"]):
            st.bump("nudge_skipped:ceiling")
            return None
        st.nudge_times.append(now)
        fmt: dict[str, Any] = {}
        if "amount_paise" in f.details:
            fmt["amount"] = format_inr(f.details["amount_paise"])
        p = Prompt(
            id=secrets.token_urlsafe(9), scenario=f.sc.id, tier=f.tier, key=str(f.tdef.prompt), incident=f.key,
            created_ms=now, not_before_ms=not_before, expires_ms=not_before + int(d["prompt_ttl_min"]) * MIN,
            full_screen=f.tdef.full_screen, fmt=fmt, pattern=f.pattern, call_hash=f.call_hash,
        )
        st.prompts[p.id] = p
        res.prompts.append(p)
        return p

    def payload(self, p: Prompt, lang: str) -> dict[str, Any]:
        """The JSON the Android app shows or reads aloud (PENDING wording)."""
        acts = C.PROMPT_ACTIONS.get(p.key, C.DEFAULT_ACTIONS)
        return {
            "prompt_id": p.id,
            "scenario": p.scenario,
            "tier": p.tier,
            "full_screen": p.full_screen,
            "read_aloud": True,
            "not_before_ms": p.not_before_ms,
            "expires_ms": p.expires_ms,
            "text": {lg: C.pick(C.PROMPTS, p.key, lg, brand=self.brand, **p.fmt) for lg in C.LANGS},
            "language": lang,
            "actions": [
                {"ack": ack, "label": {lg: C.pick(C.ACTIONS, label, lg) for lg in C.LANGS}}
                for ack, label in acts
            ],
            "status": C.STATUS,
        }


def _info_def(t: TierDef) -> TierDef:
    return TierDef("INFO", t.min_score, None, t.child_alert, False, t.defer_quiet, True)


def _fired(f: Finding, now: int, shadow: bool) -> Fired:
    return Fired(rank=TIER_RANK[f.tier], ts_ms=now, shadow=shadow)

