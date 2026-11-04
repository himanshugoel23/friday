# ruff: noqa: E501
"""Missed calls, either direction (Phase 1, AI only; builds on friday/receptionist forwarding, which delivers the call to Robin's line).

* Robin answers the forwarded call and asks who is calling, what it is about, and whether it is urgent (``steps_for``).
* The MISSED person gets a WhatsApp message with who called, when and why: the child as chat text; the parent as text + a short voice note in
  their language (``ParentChannel``; the app outbox when there is no channel).
* If the caller says it is urgent / an emergency (or a strong danger word is in what they said) the message carries the call CONTEXT and Robin
  keeps RINGING the missed person: every 3 minutes, at most 6 tries, stopping on pickup, acknowledgement ('Mark safe', 'I have it') or
  'I am fine'. Quiet hours do not apply to this. A danger word also marks the incident PHYSICAL for the emergency desk (authority.py).

Wiring of the forwarded call into this service (the voice front door) is NOT done; ``RobinHub.on_missed_call`` is the function to call.
"""

from __future__ import annotations

from dataclasses import dataclass

from friday.calls.numbers import canonical
from friday.robin import answers as ans
from friday.robin.alerts import AlertEngine
from friday.robin.context import Ctx
from friday.robin.family import FamilyService
from friday.robin.models import AnswerRaw, Family, Member, Role, Step
from friday.robin.store import Record
from friday.urgent.policy import EMERGENCY_WORDS


@dataclass
class MissedResult:
    missed_role: str
    urgent: bool
    summary: str
    incident_id: str | None = None


class MissedCallService:
    def __init__(self, ctx: Ctx, fam: FamilyService, alerts: AlertEngine) -> None:
        self.ctx, self.fam, self.alerts = ctx, fam, alerts

    async def steps_for(self, family: Family) -> list[Step]:
        slots = await self.ctx.slots(family)
        return [Step(line="missed.ask_who", slots=slots, expect="free"), Step(line="missed.ask_urgent", slots=slots, expect="yesno", on_yes="missed.urgent_ack", on_no="missed.normal_ack")]

    async def _resolve(self, phone: str) -> tuple[Family, Member] | None:
        e = canonical(phone)
        if e is None:
            return None
        for m in await self.ctx.store.members_by_phone(e):
            if m.role in (Role.PARENT, Role.CHILD):
                fam = await self.ctx.store.get_family(m.family_id)
                if fam is not None and fam.status.value != "deleted":
                    return fam, m
        return None

    async def _caller_label(self, fam: Family, caller_phone: str | None, missed: Member) -> str:
        lang = await self.ctx.chat_lang(fam)
        e = canonical(caller_phone) if caller_phone else None
        if e:
            for m in await self.ctx.store.members_by_phone(e):
                if m.family_id == fam.id and m.id != missed.id:
                    return fam.parent_label if m.role == Role.PARENT else (m.name or "your family")
        return self.ctx.say("missed.unknown_caller", lang)

    async def on_missed(self, missed_phone: str, caller_phone: str | None, answers: list[AnswerRaw]) -> MissedResult | None:
        c = self.ctx
        hit = await self._resolve(missed_phone)
        if hit is None:
            return None
        fam, missed = hit
        said = {a.line: a.text for a in answers}
        lang_child = await c.chat_lang(fam)
        summary = " ".join(said.get("missed.ask_who", "").split())[:160] or c.say("missed.no_summary", lang_child)
        words = set(ans.words(summary))
        danger = bool(words & {w.lower() for w in EMERGENCY_WORDS})
        urgent = ans.yesno(said.get("missed.ask_urgent", "")) is True or danger
        who = await self._caller_label(fam, caller_phone, missed)
        when = c.local(missed).strftime("%H:%M")
        # 1. the message to the missed person
        incident_id = None
        if missed.role == Role.PARENT:
            key = "missed.msg_urgent" if urgent else "missed.msg"
            text = c.say(key, missed.language, who=who, time=when, summary=summary)
            ch = c.parent_channel
            if ch is not None:
                await ch.send_text(missed, text)
                await ch.send_voice_note(missed, text, missed.language)
            else:
                await c.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=c.clock.now(), data={"member_id": missed.id, "line": key, "purpose": "missed", "text": text, "incident_id": None}))
        else:
            if urgent:
                text = c.say("missed.child_note_urgent", lang_child, who=who, parent=fam.parent_label, time=when, summary=summary, minutes=int(c.settings.robin_missed_ring_minutes), tries=int(c.settings.robin_missed_ring_max))
            else:
                text = c.say("missed.child_note", lang_child, who=who, parent=fam.parent_label, time=when, summary=summary)
            await c.tell_child(fam, text)
        await c.audit(fam, "missed_call", f"Took a message from {who} for {fam.parent_label if missed.role == Role.PARENT else 'you'}" + (" (urgent)." if urgent else "."))
        # 2. urgent: keep ringing the missed person
        if urgent:
            incident_id = await self.alerts.open_missed_urgent(fam, missed, who=who, summary=summary, danger=danger, when=when)
        return MissedResult(missed.role.value, urgent, summary, incident_id)
