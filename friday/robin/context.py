# ruff: noqa: E501
"""Shared plumbing of the Robin family core: brand, lines, audit log, quiet hours, consent, the one gated dial.

``Ctx.call`` is the ONLY way Robin rings anyone. Founder rule (2026-11-06, T20): security/safety calls (``security=True``: HIGH and
above, SOS, urgent missed calls, authority) never consult quiet hours or the calling window; only the anti-flood caps and the parent's
own pause apply. Everything else (check-in, medicine, intro, WATCH nudges) still respects both. In order it checks: family state, the parent's pause,
the parent's consent for that purpose (child and second contact: they agreed that Robin may ring), a
number, quiet hours, the care protocol, the daily cap per person, then the CallGate (pilot allow-list,
kill switch, do-not-call, caps) and only then the port. Every outcome, including every refusal, is written
to the audit log ('what Robin did today').
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from friday.core.clock import Clock, ist_day_bounds
from friday.core.logging import get_logger
from friday.core.models import ReplyButton, User
from friday.robin import lines
from friday.robin.models import (
    CallOutcome,
    CallResult,
    ConsentItem,
    Family,
    FamilyStatus,
    Member,
    Role,
    Step,
)
from friday.robin.ports import ParentCaller, Sender, UserDirectory
from friday.robin.store import Record, RobinStore

log = get_logger(__name__)

# purpose -> the consent items of which ANY one allows the call (None = no parent consent needed)
CONSENT_FOR: dict[str, tuple[ConsentItem, ...] | None] = {
    "intro": None,  # the first call; it is the consent call
    "checkin": (ConsentItem.DAILY_CHECKIN_CALLS,),
    "callnow": (ConsentItem.DAILY_CHECKIN_CALLS,),
    "medicine": (ConsentItem.MEDICINE_REMINDERS,),
    "emergency_ring": (ConsentItem.DAILY_CHECKIN_CALLS, ConsentItem.MEDICINE_REMINDERS, ConsentItem.SCAM_CHECK, ConsentItem.DEVICE_SIGNALS, ConsentItem.PAYMENT_ALERTS),  # an urgent missed call / the desk: any consent
    "nudge": (ConsentItem.DEVICE_SIGNALS, ConsentItem.PAYMENT_ALERTS, ConsentItem.SCAM_CHECK, ConsentItem.DAILY_CHECKIN_CALLS),
}
ESCALATION_PURPOSES = ("nudge", "escalation_child", "escalation_second", "bridge")  # emergency_ring has its own ceiling: 6 tries, 3 minutes apart
# purposes that the care protocol silences (Robin goes quiet while the child is in distress)
CARE_SILENCED = ("checkin", "callnow", "medicine", "nudge", "digest")


@dataclass
class Ctx:
    store: RobinStore
    clock: Clock
    send: Sender
    caller: ParentCaller
    gate: Any
    users: UserDirectory
    settings: Any
    care: Any = lambda user_id: False  # noqa: E731 - care.is_active, sync or async
    paused: Any = lambda: False  # noqa: E731 - the global kill switch
    extra_senders: dict[str, Any] = field(default_factory=dict)
    parent_channel: Any = None  # ports.ParentChannel (WhatsApp, voice-note first); None = outbox only
    on_reached: Any = None  # async (family, parent) called after an answered call to the parent
    audit_sink: Any = None  # async (action, user_id, *, actor, source, counts): the core audit log (kept after 'delete everything'; counts only, no PII)

    # ------------------------------------------------------------------ brand and lines
    @property
    def brand(self) -> str:
        return str(getattr(self.settings, "brand_name", "Friday") or "Friday")

    def say(self, key: str, lang: str = "hinglish", **slots: object) -> str:
        return lines.say(key, lang, brand=self.brand, **slots)

    # ------------------------------------------------------------------ people
    async def owner(self, family: Family) -> User | None:
        return await self.users.get(family.owner_user_id)

    async def parent(self, family: Family) -> Member | None:
        ms = await self.store.members(family.id, Role.PARENT)
        return ms[0] if ms else None

    async def child(self, family: Family) -> Member | None:
        ms = await self.store.members(family.id, Role.CHILD)
        return ms[0] if ms else None

    async def second(self, family: Family) -> Member | None:
        ms = await self.store.members(family.id, Role.SECOND_CONTACT)
        return ms[0] if ms else None

    async def slots(self, family: Family) -> dict[str, str]:
        child = await self.child(family)
        return {"parent": family.parent_label, "child": (child.name if child and child.name else "ji")}

    async def chat_lang(self, family: Family) -> str:
        child = await self.child(family)
        return child.language if child and child.language in lines.CHAT_LANGS else "hinglish"

    # ------------------------------------------------------------------ time
    def local(self, member: Member, now: datetime | None = None) -> datetime:
        try:
            tz = ZoneInfo(member.timezone or "Asia/Kolkata")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("Asia/Kolkata")
        return (now or self.clock.now()).astimezone(tz)

    @staticmethod
    def parse_hhmm(text: str) -> time:
        h, _, m = text.strip().partition(":")
        return time(int(h), int(m or 0))

    def in_quiet(self, member: Member, family: Family, now: datetime | None = None) -> bool:
        start = self.parse_hhmm(member.quiet_start or family.settings.quiet_start)
        end = self.parse_hhmm(member.quiet_end or family.settings.quiet_end)
        t = self.local(member, now).time().replace(second=0, microsecond=0)
        if start == end:
            return False
        return (start <= t < end) if start < end else (t >= start or t < end)

    def local_day_bounds(self, member: Member, now: datetime | None = None) -> tuple[datetime, datetime]:
        loc = self.local(member, now)
        start = loc.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    # ------------------------------------------------------------------ care protocol
    async def care_active(self, user_id: str) -> bool:
        try:
            r = self.care(user_id)
            if inspect.isawaitable(r):
                r = await r
            return bool(r)
        except Exception:  # noqa: BLE001 - never let the care check break a safety path
            return False

    # ------------------------------------------------------------------ consent
    async def active_items(self, member: Member) -> set[str]:
        return {c.item for c in await self.store.consents(member.family_id, member.id) if c.active}

    async def has_consent(self, member: Member, item: ConsentItem | str) -> bool:
        return str(getattr(item, "value", item)) in await self.active_items(member)

    # ------------------------------------------------------------------ audit log ('what Robin did today')
    async def audit(self, family: Family, event: str, text: str, *, key: str | None = None, **data: Any) -> Record:
        rec = Record(family_id=family.id, user_id=family.owner_user_id, kind="audit", key=key, status=event[:16], at=self.clock.now(), data={"event": event, "text": text, **data})
        out, _ = await self.store.put(rec)
        return out

    async def audit_today(self, family: Family, parent: Member | None) -> list[Record]:
        now = self.clock.now()
        if parent is not None:
            start, end = self.local_day_bounds(parent, now)
        else:
            start, end = ist_day_bounds(now)
        return await self.store.list(family.id, "audit", since=start, until=end)

    # ------------------------------------------------------------------ messages to the child
    async def tell_child(self, family: Family, text: str, buttons: Sequence[ReplyButton] = ()) -> bool:
        try:
            await self.send(family.owner_user_id, text, list(buttons)[:3])
            for m in await self.store.members(family.id, Role.CO_ADMIN):
                if m.user_id:
                    try:
                        await self.send(m.user_id, text, list(buttons)[:3])
                    except Exception as e:  # noqa: BLE001
                        log.warning("robin: message to a co-admin failed (%s)", type(e).__name__)
            return True
        except Exception as e:  # noqa: BLE001 - a failed send never stops the ladder
            log.warning("robin: message to the child failed (%s)", type(e).__name__)
            return False

    async def tell_second(self, family: Family, second: Member, text: str) -> bool:
        sender = self.extra_senders.get("second")
        if sender is None:
            return False
        try:
            await sender(second, text)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("robin: message to the second contact failed (%s)", type(e).__name__)
            return False

    # ------------------------------------------------------------------ the one gated dial
    async def calls_today(self, family: Family, member: Member, purposes: tuple[str, ...] = ESCALATION_PURPOSES) -> int:
        start, end = ist_day_bounds(self.clock.now())
        rows = await self.store.list(family.id, "audit", since=start, until=end)
        return sum(1 for r in rows if r.data.get("event") == "call" and r.data.get("member_id") == member.id and r.data.get("purpose") in purposes and r.data.get("result") != CallResult.REFUSED.value)

    async def call(
        self, family: Family, member: Member, purpose: str, steps: list[Step], *, dedupe_key: str, emergency: bool = False, money: bool = False,
        incident_id: str | None = None, max_seconds: int = 180, bypass_care: bool = False, sos: bool = False, security: bool = False,
    ) -> CallOutcome:  # fmt: skip
        now = self.clock.now()
        who = {Role.PARENT: family.parent_label, Role.CHILD: "you", Role.SECOND_CONTACT: "the second contact", Role.CO_ADMIN: "you"}[member.role]

        async def refuse(detail: str) -> CallOutcome:
            await self.audit(family, "call", f"Did not call {who} ({purpose}): {detail}", member_id=member.id, purpose=purpose, result=CallResult.REFUSED.value, detail=detail, incident_id=incident_id)
            return CallOutcome(result=CallResult.REFUSED, detail=detail)

        if self.paused():
            return await refuse("kill_switch")
        if family.status == FamilyStatus.DELETED:
            return await refuse("family_deleted")
        if member.role == Role.PARENT:
            if member.paused:
                return await refuse("parent_paused")
            if purpose != "intro" and family.status != FamilyStatus.ACTIVE:
                return await refuse("family_not_active")
            if purpose != "intro" and await self.store.by_key(family.id, "intro", "notified") is None:
                return await refuse("parent_not_notified")
            need = CONSENT_FOR.get(purpose, (ConsentItem.DEVICE_SIGNALS,))
            if need is not None and not (set(i.value for i in need) & await self.active_items(member)):
                return await refuse("no_consent")
        elif not member.call_ok and not (sos and member.role == Role.CHILD):  # an SOS may ring the admin who set Robin up even before call_ok was recorded
            return await refuse("not_agreed_to_calls")
        if not member.phone:
            return await refuse("no_number")
        security = security or emergency or sos  # T20: a security/safety call (HIGH and above, SOS, urgent missed call, authority) never consults quiet hours or the calling window
        if member.role == Role.PARENT and self.in_quiet(member, family, now) and not (security or money):
            return await refuse("quiet_hours")
        if purpose in CARE_SILENCED and not (emergency or bypass_care) and await self.care_active(family.owner_user_id):
            return await refuse("care_active")
        if purpose in ESCALATION_PURPOSES and await self.calls_today(family, member) >= family.settings.daily_escalation_cap:
            return await refuse("daily_cap")
        owner = await self.owner(family)
        if owner is None:
            return await refuse("no_owner")
        verdict = await self.gate.check(owner, member.phone, override_window=security or money, now=now)
        if not verdict.allowed:
            return await refuse("gate:" + ",".join(verdict.reasons))
        out = await self.caller.converse(member=member, family=family, purpose=purpose, steps=steps, dedupe_key=dedupe_key, brand=self.brand, max_seconds=max_seconds)
        await self.audit(family, "call", f"Called {who} ({purpose}): {out.result.value}", member_id=member.id, purpose=purpose, result=out.result.value, detail=out.detail, incident_id=incident_id)
        if member.role == Role.PARENT and out.result == CallResult.ANSWERED and self.on_reached is not None:
            await self.on_reached(family, member)
        return out

    async def bridge(self, family: Family, child: Member, parent: Member, *, dedupe_key: str, incident_id: str | None = None) -> CallOutcome:
        """'Robin joins the call': both numbers go through the same checks as any other dial."""
        now = self.clock.now()
        for m in (child, parent):
            if m.role == Role.PARENT and (m.paused or family.status != FamilyStatus.ACTIVE):
                return CallOutcome(result=CallResult.REFUSED, detail="parent_paused")
            if m.role == Role.CHILD and not m.call_ok:
                return CallOutcome(result=CallResult.REFUSED, detail="not_agreed_to_calls")
            owner = await self.owner(family)
            if owner is None or not m.phone:
                return CallOutcome(result=CallResult.REFUSED, detail="no_number")
            verdict = await self.gate.check(owner, m.phone, override_window=True, now=now)
            if not verdict.allowed:
                return CallOutcome(result=CallResult.REFUSED, detail="gate:" + ",".join(verdict.reasons))
        if self.paused():
            return CallOutcome(result=CallResult.REFUSED, detail="kill_switch")
        if not await self.has_consent(parent, ConsentItem.DAILY_CHECKIN_CALLS) and not await self.active_items(parent):
            return CallOutcome(result=CallResult.REFUSED, detail="no_consent")
        out = await self.caller.bridge(child=child, parent=parent, family=family, dedupe_key=dedupe_key, brand=self.brand)
        await self.audit(family, "call", f"Joined {family.parent_label} and you on one call: {out.result.value}", member_id=child.id, purpose="bridge", result=out.result.value, detail=out.detail, incident_id=incident_id)
        return out
