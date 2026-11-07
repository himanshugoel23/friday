# ruff: noqa: E501
"""Alerts: tiers INFO / WATCH / HIGH / EMERGENCY, the autonomy ceilings, the ladder, the child's buttons.

THE CONTRACT for the device/signal package (stable): build a ``RobinAlert`` and ``await raise_alert(alert)``
(module-level, below) or call ``AlertEngine.raise_alert`` through the ``AlertPort`` protocol. It returns an
``AlertResult``; nothing else of Robin is needed. ``raise_alert`` answers ``accepted=False`` with a reason
(``robin_off``, ``no_such_parent``, ``no_consent``, ``paused``) instead of raising.

Autonomy ceilings (docs/PARENT_CARE_PHASE1_SPEC.md section 5; the family may lower them, never raise them):
parent app nudges at most 2 per hour; calls to the parent at most 3 per incident, spaced 5 minutes (same for
the child and the second contact); quiet hours 22:00 to 07:00 apply only to non-security items (WATCH nudges, INFO, check-ins, reminders, digests); HIGH and above, SOS, urgent missed calls and authority ignore quiet hours and the calling window (T20); at most
3 escalation calls per person per day; the second contact only if the child named them in advance; every
alert says why in one line; everything stops on a tap of 'Mark safe', on 'I have it', or when the parent
says they are fine; Robin never blocks a number, never messages a bank or a third party, and never dials 112.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from friday.core.clock import ist_day_bounds
from friday.core.logging import get_logger
from friday.core.models import ReplyButton
from friday.robin import answers as ans
from friday.robin.authority import category_of
from friday.robin.context import Ctx
from friday.robin.family import FamilyService
from friday.robin.models import (
    TIER_ORDER,
    CallResult,
    ConsentItem,
    Family,
    FamilyStatus,
    Member,
    Role,
    Sensitivity,
    Step,
    Tier,
    normalise_scenario,
    parse_tier,
)
from friday.robin.store import Record

log = get_logger(__name__)

MAX_CALLS_PER_TARGET = 3
DAILY_ALERT_CAP = 10  # child WhatsApp alerts per family per day (WATCH and HIGH); EMERGENCY and SOS are exempt
RECOVER_AFTER_S = 120


@dataclass(frozen=True)
class RobinAlert:
    """What the device/signal package hands over. Stable contract."""

    parent_member_id: str
    tier: Tier
    scenario: str  # 'S1'..'S8', 'sos', 'checkin_unanswered', ...
    why: str  # ONE line, shown to the child: 'unknown caller 22 minutes + camera on'
    money: bool = False  # a payment app or a bank alert is part of it (quiet-hours exception for HIGH)
    dedupe_key: str | None = None  # same key = same incident (idempotent)
    occurred_at: datetime | None = None
    location: tuple[float, float] | None = None  # used only if the parent consented to location, and only in an SOS
    amount_text: str | None = None  # e.g. 'Rs 49,000' for S5: the child gets exactly this and nothing more
    category: str = ""  # optional: physical | fraud | distress (default derived from the scenario); only the emergency desk uses it
    signals: tuple[str, ...] = ()  # optional independent signals ('sos_button', 'pattern_s1', 'payment_alert'); two confirm an emergency


@dataclass(frozen=True)
class AlertResult:
    accepted: bool
    reason: str = ""  # 'ok', or why not: robin_off, no_such_parent, no_consent, paused, family_not_active
    incident_id: str | None = None
    duplicate: bool = False


@runtime_checkable
class AlertPort(Protocol):
    async def raise_alert(self, alert: RobinAlert) -> AlertResult: ...


_ENGINE: AlertPort | None = None


def set_default_engine(engine: AlertPort | None) -> None:
    """Called by the wiring when FRIDAY_ROBIN_ENABLED is on (and by tests)."""
    global _ENGINE
    _ENGINE = engine


async def raise_alert(alert: RobinAlert) -> AlertResult:
    """Module-level entry point for the device/signal package. Never raises."""
    eng = _ENGINE
    if eng is None:
        return AlertResult(False, "robin_off")
    try:
        return await eng.raise_alert(alert)
    except Exception as e:  # noqa: BLE001 - a signal path must never crash on Robin
        log.exception("robin: raise_alert failed (%s)", type(e).__name__)
        return AlertResult(False, "error")


# ============================================================================ plans
def effective_tier(tier: Tier, sensitivity: Sensitivity) -> Tier:
    """Sensitivity changes thresholds, not what data is read: Calm turns WATCH into a digest note; Careful lifts INFO to WATCH.
    HIGH and EMERGENCY are never lowered."""
    if sensitivity == Sensitivity.CALM and tier == Tier.WATCH:
        return Tier.INFO
    if sensitivity == Sensitivity.CAREFUL and tier == Tier.INFO:
        return Tier.WATCH
    return tier


def plan_for(tier: Tier, scenario: str, spacing_s: int, *, minimal_sos: bool = False) -> list[dict[str, Any]]:
    s = spacing_s

    def st(action: str, offset: int) -> dict[str, Any]:
        return {"action": action, "offset_s": offset, "state": "todo", "result": None}

    if scenario == "sos" and minimal_sos:  # family not active yet: only the child (WhatsApp + up to 3 rings), no second contact, no authority
        steps = [st("wa_child", 0), st("call_child", 0), st("call_child", s), st("call_child", 2 * s)]
    elif scenario == "sos":
        steps = [st("wa_child", 0), st("wa_second", 0), st("call_child", 0), st("call_child", s), st("call_second", s), st("call_child", 2 * s), st("authority", 3 * s)]
    elif scenario == "checkin_unanswered":
        steps = [st("wa_child", 0), st("call_child", s), st("wa_second", 2 * s), st("call_second", 3 * s)]
    elif tier == Tier.EMERGENCY:
        steps = [st("wa_child", 0), st("wa_second", 0), st("call_child", 0), st("nudge_parent", 0), st("call_child", s), st("nudge_parent", s), st("call_child", 2 * s), st("nudge_parent", 2 * s), st("call_second", 2 * s), st("authority", 3 * s)]
    elif tier == Tier.HIGH:
        steps = [st("wa_child", 0), st("nudge_parent", 0), st("nudge_parent", s), st("call_child", s), st("nudge_parent", 2 * s), st("call_child", 2 * s), st("wa_second", 3 * s), st("call_second", 3 * s), st("authority", 4 * s)]  # ladder failing for a medical/fraud HIGH
    else:  # WATCH
        steps = [st("wa_child", 0), st("nudge_parent", 0)]
    return steps


def nudge_line(alert_scenario: str, why: str, money: bool, has_safe_word: bool) -> str:  # noqa: ARG001
    if money:
        return "nudge.money"
    if alert_scenario == "S2":
        return "nudge.remote_access"
    if alert_scenario == "S4" and has_safe_word:
        return "nudge.safe_word"
    return "nudge.generic"


class AlertEngine:
    def __init__(self, ctx: Ctx, family_svc: FamilyService) -> None:
        self.ctx, self.fam, self.store = ctx, family_svc, ctx.store
        self.authority: Any = None  # authority.AuthorityService (set by the hub); None = no emergency desk

    # ------------------------------------------------------------------ the entry point
    async def raise_alert(self, alert: RobinAlert) -> AlertResult:
        c = self.ctx
        tier_in, known = parse_tier(alert.tier)  # str tiers from other packages: case-insensitive; garbage -> HIGH, never lower
        if not known:
            log.warning("robin: unknown alert tier %r treated as HIGH", str(alert.tier)[:20])
        alert = replace(alert, tier=tier_in, scenario=normalise_scenario(alert.scenario))
        parent = await self.store.get_member(alert.parent_member_id)
        if parent is None or parent.role != Role.PARENT:
            return AlertResult(False, "no_such_parent")
        family = await self.store.get_family(parent.family_id)
        if family is None or family.status == FamilyStatus.DELETED:
            return AlertResult(False, "no_such_parent")
        sos = alert.scenario == "sos"  # an SOS works even after the parent paused Robin: the parent pressed it
        if (parent.paused or family.status == FamilyStatus.PAUSED) and not sos:
            return AlertResult(False, "paused")
        minimal_sos = False
        if sos and family.status not in (FamilyStatus.ACTIVE, FamilyStatus.PAUSED):
            # SOS ALWAYS works (founder, 2026-11-06): setup or consent not complete is no reason to leave the child unwarned.
            child = await c.child(family)
            if child is None or not child.phone:
                log.error("robin: SOS from a family that is not active and has NO child contact; nobody can be told (family %s)", family.id)
                await c.audit(family, "sos_failed", "An SOS was pressed but there is no contact number for you; nobody could be told.", scenario="sos")
                return AlertResult(False, "no_child_contact")
            minimal_sos = True
        elif family.status not in (FamilyStatus.ACTIVE, FamilyStatus.PAUSED) or (family.status == FamilyStatus.PAUSED and not sos):
            return AlertResult(False, "family_not_active")
        internal = sos or alert.scenario.startswith("checkin")
        if not internal:
            items = await c.active_items(parent)
            need = {ConsentItem.DEVICE_SIGNALS.value, ConsentItem.PAYMENT_ALERTS.value}  # either one; the device API already checks the item of each signal, and a money flag must not narrow this (S3 reads the payment APP under device_signals)
            if not (items & need):
                await c.audit(family, "alert_refused", f"A signal about {family.parent_label} was ignored because they have not agreed to that (consent).", scenario=alert.scenario)
                return AlertResult(False, "no_consent")
        tier = effective_tier(alert.tier, family.settings.sensitivity)
        why = " ".join((alert.why or "").split())[:160] or "unusual activity"
        now = c.clock.now()
        key = alert.dedupe_key or f"{alert.scenario}:{parent.id}:{tier.value}:{int(now.timestamp() // 300)}"
        loc = alert.location if (alert.location and sos and await c.has_consent(parent, ConsentItem.LOCATION)) else None
        data = {
            "tier": tier.value, "scenario": alert.scenario, "why": why, "money": bool(alert.money), "amount_text": alert.amount_text,
            "parent_id": parent.id, "location": list(loc) if loc else None, "occurred_at": (alert.occurred_at or now).isoformat(),
            "category": category_of(alert.scenario, alert.category), "signals": list(alert.signals) + (["sos_button"] if sos else []), "what": "threat" if alert.scenario == "threat" else "unknown",
            "steps": plan_for(tier, alert.scenario, family.settings.call_spacing_min * 60, minimal_sos=minimal_sos), "calls": {}, "child_reached": False, "closed_by": None,
        }  # fmt: skip
        status = "closed" if tier == Tier.INFO else "open"
        rec, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="incident", key=key[:64], status=status, at=now, due_at=now if status == "open" else None, data=data))
        if not created:
            return AlertResult(True, "ok", rec.id, duplicate=True)
        if tier == Tier.INFO:
            await c.audit(family, "alert", f"Noted for the digest: {why}", incident_id=rec.id, tier=tier.value)
            return AlertResult(True, "ok", rec.id)
        await c.audit(family, "alert", f"{tier.value.upper()} alert: {why}", incident_id=rec.id, tier=tier.value, scenario=alert.scenario)
        await self.run_incident(rec.id)
        return AlertResult(True, "ok", rec.id)

    # ------------------------------------------------------------------ the ladder
    async def tick(self) -> int:
        now = self.ctx.clock.now()
        n = 0
        for rec in await self.store.due("incident", ("open",), now):
            await self.run_incident(rec.id)
            n += 1
        for rec in await self.store.due("incident", ("running",), now - timedelta(seconds=RECOVER_AFTER_S)):  # a replica died mid-step
            await self._recover(rec)
            n += 1
        return n

    async def _recover(self, rec: Record) -> None:
        d = rec.data
        for st in d["steps"]:
            if st["state"] == "started":
                st["state"], st["result"] = "done", "unknown"  # never dial the same step twice
        if await self.store.cas(rec.id, "running", status="open", data=d, due_at=self._next_due(rec.at, d)):
            return

    @staticmethod
    def _next_due(created: datetime, d: dict[str, Any]) -> datetime | None:
        todo = [s["offset_s"] for s in d["steps"] if s["state"] == "todo"]
        return created + timedelta(seconds=min(todo)) if todo else None

    async def run_incident(self, incident_id: str) -> None:
        rec = await self.store.get(incident_id)
        if rec is None or rec.status != "open" or not await self.store.cas(rec.id, "open", status="running"):
            return
        c = self.ctx
        d = rec.data
        family = await self.store.get_family(rec.family_id)
        parent = await self.store.get_member(d["parent_id"])
        if family is None or parent is None or family.status == FamilyStatus.DELETED or (parent.paused and d["scenario"] != "sos"):
            await self.store.cas(rec.id, "running", status="closed", data={**d, "closed_by": "stopped"}, due_at=None)
            return
        now = c.clock.now()
        try:
            for st in d["steps"]:
                if st["state"] != "todo" or rec.at + timedelta(seconds=st["offset_s"]) > now:
                    continue
                latest = await self.store.get(rec.id)
                if latest is None or latest.status != "running":
                    break
                st["state"] = "started"
                await self.store.set_data(rec.id, d)  # persisted BEFORE the dial: a crash can never lead to a second dial
                st["result"] = await self._do(st["action"], family, parent, rec, d)
                st["state"] = "done"
                await self.store.set_data(rec.id, d)
        finally:
            fresh = await self.store.get(rec.id)
            if fresh is not None and fresh.status == "running":
                nxt = self._next_due(rec.at, d)
                await self.store.cas(rec.id, "running", status="open" if nxt else "exhausted", data=d, due_at=nxt)

    # ------------------------------------------------------------------ one ladder step
    async def _do(self, action: str, family: Family, parent: Member, rec: Record, d: dict[str, Any]) -> str:  # noqa: C901
        c = self.ctx
        tier = Tier(d["tier"])
        sos = d["scenario"] == "sos"
        money = bool(d.get("money"))
        urgent = TIER_ORDER[tier] >= TIER_ORDER[Tier.HIGH]
        if action == "wa_child":
            if await self._flood_capped(family, rec, d):
                return "capped"
            return "sent" if await self._message_child(family, parent, rec, d) else "failed"
        if action == "wa_second":
            second = await c.second(family)
            if second is None or not second.call_ok:
                return "no_second_contact"
            slots = await c.slots(family)
            lang = second.language if second.language in ("en", "hinglish") else "hinglish"
            loc = self._loc_text(d, lang)
            text = c.say("sos.second", lang, loc=loc, **slots) if d["scenario"] == "sos" else c.say("alert.second", lang, why=d["why"], **slots)
            ok = await c.tell_second(family, second, text)
            await c.audit(family, "message", f"Messaged the second contact: {'sent' if ok else 'could not send'}.", incident_id=rec.id)
            return "sent" if ok else "failed"
        if action == "call_child":
            child = await c.child(family)
            if child is None or d["child_reached"] or self._calls(d, "child") >= MAX_CALLS_PER_TARGET:
                return "skipped"
            slots = await c.slots(family)
            line = "child.ring_sos" if sos else "child.ring_unreached" if d["scenario"] == "checkin_unanswered" else "child.ring"
            out = await c.call(family, child, "escalation_child", [Step(line=line, slots=slots)], dedupe_key=f"{rec.id}:child:{self._calls(d, 'child') + 1}", emergency=tier == Tier.EMERGENCY, money=money, incident_id=rec.id, bypass_care=urgent, sos=sos, security=urgent or sos)
            self._count(d, "child", out.result)
            if out.result == CallResult.ANSWERED:
                d["child_reached"] = True
            return out.result.value if out.result != CallResult.REFUSED else f"refused:{out.detail}"
        if action == "call_second":
            second = await c.second(family)
            if second is None or not second.call_ok:
                return "no_second_contact"
            if self._calls(d, "second") >= MAX_CALLS_PER_TARGET:
                return "skipped"
            slots = await c.slots(family)
            out = await c.call(family, second, "escalation_second", [Step(line="second.ring", slots=slots)], dedupe_key=f"{rec.id}:second:{self._calls(d, 'second') + 1}", emergency=tier == Tier.EMERGENCY, money=money, incident_id=rec.id, bypass_care=True, security=urgent or sos)
            self._count(d, "second", out.result)
            return out.result.value if out.result != CallResult.REFUSED else f"refused:{out.detail}"
        if action == "nudge_parent":
            return await self._nudge_parent(family, parent, rec, d)
        if action == "authority":
            return "no_authority" if self.authority is None else await self.authority.consider(family, parent, rec, d)
        if action == "ring_target":
            return await self._ring_target(family, rec, d)
        return "unknown_action"

    @staticmethod
    def _calls(d: dict[str, Any], who: str) -> int:
        return int(d["calls"].get(who, 0))

    @staticmethod
    def _count(d: dict[str, Any], who: str, result: CallResult) -> None:
        if result != CallResult.REFUSED:
            d["calls"][who] = int(d["calls"].get(who, 0)) + 1

    def _loc_text(self, d: dict[str, Any], lang: str) -> str:
        loc = d.get("location")
        return self.ctx.say("sos.loc", lang, lat=f"{loc[0]:.5f}", lon=f"{loc[1]:.5f}") if loc else ""

    async def _nudge_parent(self, family: Family, parent: Member, rec: Record, d: dict[str, Any]) -> str:
        c = self.ctx
        tier, money = Tier(d["tier"]), bool(d.get("money"))
        if d["scenario"] == "sos":
            return "skipped"
        has_sw = bool(family.settings.safe_word_hash)
        line = nudge_line(d["scenario"], d["why"], money, has_sw)
        slots = await c.slots(family)
        if tier == Tier.WATCH:
            if await c.care_active(family.owner_user_id):
                return "skipped:care_active"
            if c.in_quiet(parent, family):
                return "skipped:quiet_hours"
            if await self.fam.nudges_last_hour(family, parent) >= family.settings.nudges_per_hour:
                await c.audit(family, "nudge_skipped", f"Did not nudge {family.parent_label}: already nudged {family.settings.nudges_per_hour} times this hour.", incident_id=rec.id)
                return "skipped:hourly_cap"
            await self.fam.queue_app_notification(family, parent, line, purpose="nudge", incident_id=rec.id)
            return "app_notification"
        # HIGH / EMERGENCY: also one app banner (not capped at EMERGENCY), then the call
        if self._calls(d, "parent") >= min(MAX_CALLS_PER_TARGET, family.settings.calls_per_incident):
            return "skipped:call_cap"
        if self._calls(d, "parent") == 0 and (tier == Tier.EMERGENCY or await self.fam.nudges_last_hour(family, parent) < family.settings.nudges_per_hour):
            await self.fam.queue_app_notification(family, parent, line, purpose="nudge", incident_id=rec.id)
        step = Step(line=line, slots=slots, expect="yesno", on_yes="nudge.fine_ack", on_no="nudge.not_fine_ack")
        out = await c.call(family, parent, "nudge", [step], dedupe_key=f"{rec.id}:parent:{self._calls(d, 'parent') + 1}", emergency=tier == Tier.EMERGENCY, money=money, incident_id=rec.id, bypass_care=True, security=True)  # HIGH and above only (WATCH returned above)
        self._count(d, "parent", out.result)
        if out.result == CallResult.ANSWERED:
            heard = out.answers[0].text if out.answers else ""
            fine = ans.is_fine(heard) or ans.yesno(heard) is True
            if ans.is_stop(heard) or out.detail == "stop_requested":
                await self.fam.pause(parent.id, "voice")
                return "parent_paused"
            if fine:
                d["parent_fine"] = True
                if await self._close(rec.id, d, "parent_fine", family):
                    await self._parent_fine_note(family, rec, await c.chat_lang(family))
                return "parent_fine"
            if ans.yesno(heard) is False:
                d["parent_not_fine"] = True
                lang = await c.chat_lang(family)
                await c.tell_child(family, c.say("alert.head.high", lang, parent=family.parent_label, why=f"{family.parent_label} said no when I asked if all is fine"))
                return "parent_not_fine"
        return out.result.value if out.result != CallResult.REFUSED else f"refused:{out.detail}"

    # ------------------------------------------------------------------ urgent missed call: keep ringing the missed person
    async def open_missed_urgent(self, family: Family, missed: Member, *, who: str, summary: str, danger: bool, when: str) -> str | None:
        c = self.ctx
        parent = await c.parent(family)
        if parent is None:
            return None
        gap = int(c.settings.robin_missed_ring_minutes) * 60
        tries = int(c.settings.robin_missed_ring_max)
        now = c.clock.now()
        data = {
            "tier": Tier.EMERGENCY.value, "scenario": "missed_urgent", "why": f"{who} called and says it is urgent: {summary}", "money": False, "amount_text": None,
            "parent_id": parent.id, "target": missed.id, "who": who, "location": None, "occurred_at": now.isoformat(), "category": "physical" if danger else "",
            "signals": ["urgent_missed_call"] + (["danger_words"] if danger else []), "what": "medical" if danger else "unknown",
            "steps": [{"action": "ring_target", "offset_s": i * gap, "state": "todo", "result": None} for i in range(tries)] + ([{"action": "authority", "offset_s": tries * gap, "state": "todo", "result": None}] if danger else []),
            "calls": {}, "child_reached": missed.role != Role.CHILD, "closed_by": None, "reached": False,
        }  # fmt: skip
        rec, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="incident", key=f"missed:{missed.id}:{int(now.timestamp() // 60)}"[:64], status="open", at=now, due_at=now, data=data))
        if created:
            await c.audit(family, "alert", f"Urgent missed call: Robin will ring {family.parent_label if missed.role == Role.PARENT else 'you'} every {gap // 60} minutes, up to {tries} tries.", incident_id=rec.id)
            await self.run_incident(rec.id)
        return rec.id

    async def _ring_target(self, family: Family, rec: Record, d: dict[str, Any]) -> str:
        c = self.ctx
        if d.get("reached"):
            return "skipped:reached"
        target = await self.store.get_member(d["target"])
        if target is None:
            return "no_target"
        slots = await c.slots(family)
        addressee = family.parent_label if target.role == Role.PARENT else slots["child"]
        n = self._calls(d, "target") + 1
        out = await c.call(family, target, "emergency_ring", [Step(line="missed.emergency_ring", slots={"parent": addressee, "who": d.get("who", "someone")})], dedupe_key=f"{rec.id}:ring:{n}", emergency=True, incident_id=rec.id, bypass_care=True, security=True)
        self._count(d, "target", out.result)
        if out.result == CallResult.ANSWERED:
            d["reached"] = True  # stop on pickup
            await c.audit(family, "alert_closed", "The missed person picked up the emergency call; Robin stops ringing.", incident_id=rec.id)
            for st in d["steps"]:
                if st["state"] == "todo" and st["action"] == "ring_target":
                    st["state"], st["result"] = "done", "skipped:reached"
            return "answered"
        return out.result.value if out.result != CallResult.REFUSED else f"refused:{out.detail}"

    async def confirm_emergency(self, family: Family, incident_id: str, by: str) -> bool:
        """The parent (``parent``) or the admin (``child``) confirms a real emergency: a parent yes alone is enough for the desk; the admin's counts as one signal."""
        rec = await self.store.get(incident_id)
        if rec is None or rec.family_id != family.id or rec.status not in ("open", "running", "exhausted"):
            return False
        d = rec.data
        d["parent_confirmed" if by == "parent" else "child_confirmed"] = True
        await self.store.set_data(rec.id, d)
        await self.ctx.audit(family, "alert", f"Emergency confirmed by the {'parent' if by == 'parent' else 'admin'}.", incident_id=rec.id)
        return True

    # ------------------------------------------------------------------ the message to the child
    def _buttons(self, rec_id: str, lang: str) -> list[ReplyButton]:
        hl = lang != "en"
        return [
            ReplyButton(id=f"rb:{rec_id}:call", title="Parent ko call" if hl else "Call parent"),
            ReplyButton(id=f"rb:{rec_id}:join", title="Robin judegi" if hl else "Robin joins call"),
            ReplyButton(id=f"rb:{rec_id}:safe", title="Safe hai" if hl else "Mark safe"),
        ]  # WhatsApp allows 3 reply buttons: 'Show details' is the text command 'details' (the alert says so)

    async def _flood_capped(self, family: Family, rec: Record, d: dict[str, Any]) -> bool:
        """Alert-flood protection: at most ``robin_alert_daily_cap`` (default 10) child WhatsApp alerts per family per IST day for
        WATCH and HIGH. The first alert past the cap sends ONE "many alerts" summary (never silence). EMERGENCY and SOS are never
        capped. The incident, its calls and the audit trail still run; only the extra WhatsApp text is held back."""
        c = self.ctx
        if d["scenario"] == "sos" or Tier(d["tier"]) not in (Tier.WATCH, Tier.HIGH):
            return False
        cap = int(getattr(c.settings, "robin_alert_daily_cap", DAILY_ALERT_CAP))
        start, end = ist_day_bounds(c.clock.now())
        sent = 0
        for r in await self.store.list(family.id, "incident", since=start, until=end, limit=1000):
            if r.id == rec.id or r.data.get("scenario") == "sos" or r.data.get("tier") not in (Tier.WATCH.value, Tier.HIGH.value):
                continue
            if any(st["action"] == "wa_child" and st["state"] in ("started", "done") and st.get("result") == "sent" for st in r.data.get("steps", [])):
                sent += 1
        if sent < cap:
            return False
        _, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", key=f"floodsum:{start.date().isoformat()}", status="done", at=c.clock.now(), data={"n": sent}))
        if created:
            lang = await c.chat_lang(family)
            await c.tell_child(family, c.say("alert.flood_summary", lang, parent=family.parent_label, n=sent))
            await c.audit(family, "alert_flood", f"Many alerts today ({sent}): further minor alerts are held in the log; EMERGENCY and SOS still go out.", incident_id=rec.id)
        return True

    async def _message_child(self, family: Family, parent: Member, rec: Record, d: dict[str, Any]) -> bool:
        c = self.ctx
        lang = await c.chat_lang(family)
        tier = Tier(d["tier"])
        slots = await c.slots(family)
        why = d["why"] + (f" ({d['amount_text']})" if d.get("amount_text") else "")
        if d["scenario"] == "sos":
            text = c.say("sos.child", lang, parent=family.parent_label, loc=self._loc_text(d, lang))
        elif tier == Tier.EMERGENCY:
            text = c.say("alert.head.emergency", lang, parent=family.parent_label, why=why)
        elif tier == Tier.HIGH:
            text = c.say("alert.head.high", lang, parent=family.parent_label, why=why)
        else:
            text = c.say("alert.head.watch", lang, parent=family.parent_label, why=why)
        if d.get("money"):
            text += "\n" + c.say("alert.money_note", lang, **slots)
        text += "\n" + c.say("alert.hint", lang)
        ok = await c.tell_child(family, text, self._buttons(rec.id, lang))
        await c.audit(family, "message", f"Told you about it: {'sent' if ok else 'could not send'}.", incident_id=rec.id)
        return ok

    # ------------------------------------------------------------------ stopping
    async def _close(self, incident_id: str, d: dict[str, Any], by: str, family: Family) -> bool:
        d["closed_by"] = by
        ok = await self.store.cas(incident_id, ("open", "running", "exhausted"), status="closed", data=d, due_at=None)
        if ok:
            await self.ctx.audit(family, "alert_closed", f"Alert closed ({by.replace('_', ' ')}).", incident_id=incident_id, by=by)
        return ok

    async def stop(self, family: Family, incident_id: str | None, by: str) -> bool:
        """'Mark safe' / 'I have it' / the parent says they are fine. ``by``: child_safe, child_has_it, parent_fine."""
        rec = await self.store.get(incident_id) if incident_id else await self.latest_open(family)
        if rec is None or rec.family_id != family.id or rec.status not in ("open", "running", "exhausted"):
            return False
        ok = await self._close(rec.id, rec.data, by, family)
        if ok and self.authority is not None:
            await self.authority.cancel(family, rec.id, by)  # Mark safe / I have it / parent fine also cancel a running countdown
        if ok:
            lang = await self.ctx.chat_lang(family)
            key = {"child_safe": "alert.safe", "child_has_it": "alert.taken", "parent_fine": "alert.parent_fine"}.get(by, "alert.safe")
            if by == "parent_fine":
                await self._parent_fine_note(family, rec, lang)
            else:
                await self.ctx.tell_child(family, self.ctx.say(key, lang, parent=family.parent_label))
        return ok

    async def _parent_fine_note(self, family: Family, rec: Record, lang: str) -> None:
        c = self.ctx
        text = c.say("alert.parent_fine", lang, parent=family.parent_label)
        if rec.data.get("money"):  # never an all-clear for money
            text += "\n" + c.say("alert.money_note", lang, parent=family.parent_label)
        await c.tell_child(family, text)

    async def parent_fine(self, parent_member_id: str) -> int:
        """The parent said 'I am fine' (voice or app tap): close their open incidents."""
        parent = await self.store.get_member(parent_member_id)
        family = await self.store.get_family(parent.family_id) if parent else None
        if parent is None or family is None:
            return 0
        n = 0
        for rec in await self.store.list(family.id, "incident", status=("open", "running")):
            if rec.data.get("parent_id") == parent.id and rec.data.get("scenario") != "sos" and await self._close(rec.id, rec.data, "parent_fine", family):
                await self._parent_fine_note(family, rec, await self.ctx.chat_lang(family))
                n += 1
        return n

    async def latest_open(self, family: Family) -> Record | None:
        rows = await self.store.list(family.id, "incident", status=("open", "running", "exhausted"))
        return rows[-1] if rows else None

    async def open_count(self, family: Family) -> int:
        return len(await self.store.list(family.id, "incident", status=("open", "running")))

    # ------------------------------------------------------------------ the child's buttons and words
    async def on_button(self, family: Family, incident_id: str, action: str) -> str | None:
        c = self.ctx
        lang = await c.chat_lang(family)
        rec = await self.store.get(incident_id)
        if rec is None or rec.family_id != family.id:
            return c.say("alert.unknown", lang)
        parent = await c.parent(family)
        if action == "safe":
            return None if await self.stop(family, rec.id, "child_safe") else c.say("alert.unknown", lang)
        if action == "details":
            return self.details(rec, lang)
        if action == "call" and parent is not None:
            return c.say("alert.call_parent", lang, parent=family.parent_label, phone=parent.phone or "")
        if action == "join" and parent is not None:
            child = await c.child(family)
            if child is None:
                return c.say("alert.join_refused", lang, why="no_number")
            out = await c.bridge(family, child, parent, dedupe_key=f"{rec.id}:bridge:{int(c.clock.now().timestamp())}", incident_id=rec.id)
            if out.result == CallResult.REFUSED:
                return c.say("alert.join_refused", lang, why=out.detail)
            return c.say("alert.join_started", lang, parent=family.parent_label)
        return c.say("alert.unknown", lang)

    def details(self, rec: Record, lang: str) -> str:
        d = rec.data
        steps = ", ".join(f"{s['action']}={s['result'] or s['state']}" for s in d["steps"] if s["state"] != "todo") or "none yet"
        return self.ctx.say("alert.details", lang, why=d["why"], scenario=d["scenario"], tier=d["tier"], at=rec.at.strftime("%H:%M UTC"), steps=steps)
