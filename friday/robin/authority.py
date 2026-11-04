# ruff: noqa: E501
"""AUTHORITY CALLS (112 / 1930) of the AI emergency desk. Switch ``FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED`` default OFF, and even when on it is
a DRY-RUN by default (``FRIDAY_ROBIN_AUTHORITY_DRY_RUN``): it only LOGS the script it would speak. There is NO live adapter in this repo:
the CallGate also refuses emergency numbers (112 and 1930 are in ``calls/numbers.EMERGENCY_NUMBERS``), so a live path needs a reviewed gate
change, a real adapter, legal clearance and the founder's explicit approval. Tests never place or simulate a real 112 call.

Preconditions, ALL required before anything is even logged as a call (each refusal is audited):
  1. the switch is on, and the parent has NOT paused Robin;
  2. consent item ``authority_calls`` recorded by the admin;
  3. a confirmed EMERGENCY: two independent signals (e.g. SOS button + the ladder failing to reach the child, or the device's pattern + the
     parent saying they are threatened), OR the parent said yes / the admin confirmed;
  4. category: PHYSICAL (medical, threat, SOS) -> 112. FRAUD -> never 112; only a conference/bridge of the child to 1930 (Robin does not speak
     alone) when money is involved, plus a cybercrime.gov.in complaint DRAFT for the child (sent even with the switch off: it is only text).
     DISTRESS only -> never a call; handed to the care protocol;
  5. the parent's name and address from the profile (admin sets them), a fixed calm script (what, where, who, callback number);
  6. a 60-second 'I am fine' cancel window with a spoken countdown, SKIPPED only when the parent is unresponsive (no answer);
  7. a hard cap of ONE authority call per incident; an audit record for every decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from friday.core.logging import get_logger
from friday.robin import answers as ans
from friday.robin.context import Ctx
from friday.robin.models import CallOutcome, CallResult, ConsentItem, Family, Member, Step
from friday.robin.store import Record

log = get_logger(__name__)

PHYSICAL, FRAUD, DISTRESS = "physical", "fraud", "distress"
_SCENARIO_CATEGORY = {"sos": PHYSICAL, "threat": PHYSICAL, "medical": PHYSICAL, "fall": PHYSICAL, "distress": DISTRESS}


def category_of(scenario: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if scenario in _SCENARIO_CATEGORY:
        return _SCENARIO_CATEGORY[scenario]
    if scenario[:1] == "S" and scenario[1:].isdigit():
        return FRAUD  # S1..S8 of the scenario table are fraud patterns
    return ""


@runtime_checkable
class AuthorityCaller(Protocol):
    live: bool

    async def place(self, *, kind: str, script: str, bridge_with: str | None, dedupe_key: str) -> CallOutcome: ...


@dataclass
class DryRunAuthorityCaller:
    """Logs the script it would speak. Dials nothing, simulates nothing."""

    live: bool = False
    logged: list[dict[str, Any]] = field(default_factory=list)

    async def place(self, *, kind: str, script: str, bridge_with: str | None, dedupe_key: str) -> CallOutcome:
        self.logged.append({"kind": kind, "script": script, "bridge_with": bridge_with, "dedupe_key": dedupe_key})
        log.info("robin authority DRY RUN: would contact %s", kind)
        return CallOutcome(result=CallResult.ANSWERED, detail="dry_run")


class AuthorityService:
    def __init__(self, ctx: Ctx, caller: AuthorityCaller | None = None) -> None:
        self.ctx = ctx
        self.caller: AuthorityCaller = caller or DryRunAuthorityCaller()

    # ------------------------------------------------------------------ switches
    def _on(self) -> bool:
        return bool(getattr(self.ctx.settings, "robin_authority_calls_enabled", False))

    def _dry(self) -> bool:
        return bool(getattr(self.ctx.settings, "robin_authority_dry_run", True))

    @staticmethod
    def signals_of(d: dict[str, Any]) -> set[str]:
        s = set(d.get("signals") or [])
        if not d.get("child_reached") and d.get("calls", {}).get("child", 0) >= 1:
            s.add("ladder_failed")  # we rang the child and nobody picked up
        if d.get("child_confirmed"):
            s.add("child_confirmed")
        return s

    async def _refuse(self, family: Family, d: dict[str, Any], why: str, *, tell: bool = False) -> str:
        c = self.ctx
        await c.audit(family, "authority", f"Emergency desk did not contact the authorities: {why}.", why=why)
        if tell and why not in d.setdefault("told_refusals", []):
            d["told_refusals"].append(why)
            await c.tell_child(family, c.say("authority.refused", await c.chat_lang(family), parent=family.parent_label, why=why))
        return f"refused:{why}"

    # ------------------------------------------------------------------ the ladder step
    async def consider(self, family: Family, parent: Member, rec: Record, d: dict[str, Any]) -> str:
        c = self.ctx
        cat = category_of(d.get("scenario", ""), d.get("category", ""))
        lang = await c.chat_lang(family)
        if cat == DISTRESS:
            await c.audit(family, "authority", "Distress only: no call to anyone official; handed to the care protocol.")
            await c.tell_child(family, c.say("authority.distress", lang, parent=family.parent_label))
            return "distress_to_care"
        if cat not in (PHYSICAL, FRAUD):
            return "no_category"
        if cat == FRAUD:
            if not d.get("money"):
                return await self._refuse(family, d, "fraud_without_money")
            if not d.get("complaint_sent"):
                d["complaint_sent"] = True
                await c.tell_child(family, c.say("authority.complaint", lang, parent=family.parent_label, when=rec.at.strftime("%d %b %Y %H:%M UTC"), why=d.get("why", ""), amount=d.get("amount_text") or "unknown"))
        if not self._on():
            return await self._refuse(family, d, "switch_off")
        if parent.paused:
            return await self._refuse(family, d, "parent_paused")
        if not await c.has_consent(parent, ConsentItem.AUTHORITY_CALLS):
            return await self._refuse(family, d, "no_consent", tell=True)
        if not (len(self.signals_of(d)) >= 2 or d.get("parent_confirmed")):
            return await self._refuse(family, d, "not_confirmed")
        if cat == PHYSICAL and not (parent.address and parent.name):
            return await self._refuse(family, d, "no_name_or_address", tell=True)
        key = f"auth:{rec.id}"[:64]
        window = int(getattr(c.settings, "robin_authority_countdown_s", 60))
        now = c.clock.now()
        auth, created = await c.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", key=key, status="countdown", at=now, due_at=now + timedelta(seconds=window), data={"incident_id": rec.id, "category": cat, "what": d.get("what", "unknown")}))
        if not created:
            return "already_started"  # hard cap: one authority call per incident
        await c.tell_child(family, c.say("authority.countdown_child", lang, parent=family.parent_label, seconds=window))
        slots = await c.slots(family)
        out = await c.call(family, parent, "emergency_ring", [Step(line="authority.countdown", slots=slots, expect="yesno")], dedupe_key=f"{rec.id}:countdown", emergency=True, incident_id=rec.id, bypass_care=True)
        heard = out.answers[0].text if out.answers else ""
        if out.result == CallResult.ANSWERED and (ans.is_fine(heard) or "cancel" in heard.lower()):
            await self._set(auth, "cancelled", "parent_fine")
            await c.audit(family, "authority", "Authority call cancelled: the parent said they are fine.")
            return "cancelled"
        if out.result != CallResult.ANSWERED:  # unresponsive parent: no waiting
            return await self._place(family, parent, auth, rec.id)
        return "countdown"

    async def _set(self, auth: Record, status: str, why: str) -> None:
        await self.ctx.store.cas(auth.id, "countdown", status=status, due_at=None, data={**auth.data, "result": why})

    async def cancel(self, family: Family, incident_id: str, by: str) -> bool:
        auth = await self.ctx.store.by_key(family.id, "pending", f"auth:{incident_id}"[:64])
        if auth is None or auth.status != "countdown":
            return False
        await self._set(auth, "cancelled", by)
        await self.ctx.audit(family, "authority", f"Authority call cancelled ({by}).")
        return True

    async def tick(self) -> int:
        n = 0
        for auth in await self.ctx.store.due("pending", ("countdown",), self.ctx.clock.now()):
            if not auth.key or not auth.key.startswith("auth:"):
                continue
            fam = await self.ctx.store.get_family(auth.family_id)
            inc = await self.ctx.store.get(auth.data["incident_id"])
            if fam is None or inc is None or inc.status not in ("open", "running", "exhausted"):
                await self.ctx.store.cas(auth.id, "countdown", status="cancelled", due_at=None)
                continue
            parent = await self.ctx.store.get_member(inc.data["parent_id"])
            if parent is None or parent.paused:
                await self.ctx.store.cas(auth.id, "countdown", status="cancelled", due_at=None)
                continue
            await self._place(fam, parent, auth, inc.id)
            n += 1
        return n

    # ------------------------------------------------------------------ the (dry-run) call
    def script_for(self, family: Family, parent: Member, child: Member | None, cat: str, what: str) -> tuple[str, str, str | None]:
        c = self.ctx
        if cat == PHYSICAL:
            w = c.say(f"authority.what.{what if what in ('medical', 'threat') else 'unknown'}", "hinglish")
            text = c.say("authority.script_112", "hinglish", name=parent.name, address=parent.address or "", what=w, callback=(child.phone if child else "") or "")
            return "112", text, None
        text = c.say("authority.bridge_1930", "hinglish", child=(child.name if child and child.name else "ji"), parent=family.parent_label)
        return "1930", text, child.id if child else None

    async def _place(self, family: Family, parent: Member, auth: Record, incident_id: str) -> str:
        c = self.ctx
        if not await c.store.cas(auth.id, "countdown", status="placing", due_at=None):
            return "raced"
        child = await c.child(family)
        kind, script, bridge = self.script_for(family, parent, child, auth.data["category"], auth.data.get("what", "unknown"))
        if kind == "112" and auth.data["category"] != PHYSICAL:  # belt and braces: fraud-only / distress-only NEVER reach 112
            await c.store.cas(auth.id, "placing", status="refused")
            return "refused:not_physical"
        if not self._dry() and not self.caller.live:
            await c.store.cas(auth.id, "placing", status="refused", data={**auth.data, "result": "no_live_adapter"})
            return await self._refuse(family, {}, "no_live_adapter", tell=False)
        out = await self.caller.place(kind=kind, script=script, bridge_with=bridge, dedupe_key=f"{incident_id}:authority")
        await c.store.cas(auth.id, "placing", status="dry_run" if self._dry() else "placed", data={**auth.data, "result": out.detail, "kind": kind})
        mode = "DRY RUN (nothing dialled): would have contacted" if self._dry() else "Contacted"
        await c.audit(family, "authority", f"{mode} {kind}. Script: {script}", kind=kind, dry_run=self._dry(), incident_id=incident_id)
        who = "112 (police, ambulance, fire)" if kind == "112" else "the cyber-fraud helpline 1930 (you, connected by conference)"
        await c.tell_child(family, c.say("authority.dry_run", await c.chat_lang(family), parent=family.parent_label, who=who))
        return "dry_run" if self._dry() else "placed"
