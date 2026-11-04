# ruff: noqa: E501
"""The introduction / consent call: the FIRST and only call a parent gets before consent exists.

It says it is an AI assistant called <brand>, who asked it to call, what it will and will not do, and how
to say no; then asks, one item at a time, for a spoken yes (daily check-in calls, medicine reminders,
scam check, a daily summary for the child). Only a clear YES is recorded (source ``voice_yes``); silence,
'no' and anything unclear record nothing. 'Stop' (or a decline of everything) means Robin never calls again
until the child asks it to try again. At most 2 attempts. The call goes through ``Ctx.call`` like any other
(pilot allow-list, CallGate, quiet hours) and the real dial refuses while the lines are PENDING approval.
"""

from __future__ import annotations

from datetime import timedelta

from friday.core.logging import get_logger
from friday.robin import answers as ans
from friday.robin.context import Ctx
from friday.robin.family import ITEM_LABEL, FamilyService
from friday.robin.models import (
    VOICE_CONSENT_ITEMS,
    CallResult,
    ConsentSource,
    Family,
    FamilyStatus,
    Step,
)
from friday.robin.store import Record

log = get_logger(__name__)
MAX_ATTEMPTS = 2
RETRY_AFTER = timedelta(hours=4)


class IntroService:
    def __init__(self, ctx: Ctx, family_svc: FamilyService) -> None:
        self.ctx, self.fam, self.store = ctx, family_svc, ctx.store

    @staticmethod
    def steps(slots: dict[str, str], *, ask: bool = False) -> list[Step]:
        """The notification call. Consent was given by the admin; the parent is NOTIFIED and may say 'stop'. ``ask=True`` also
        asks for the parent's own yes, which then replaces the admin's basis."""
        s = [Step(line=k, slots=slots) for k in ("intro.greet", "intro.will", "intro.wont", "intro.no", "notify.stop")]
        if ask:
            s += [Step(line=f"intro.ask.{i.value}", slots=slots, expect="yesno") for i in VOICE_CONSENT_ITEMS]
        s.append(Step(line="intro.thanks", slots=slots))
        return s

    async def attempts(self, family: Family) -> list[Record]:
        return [r for r in await self.store.list(family.id, "intro") if (r.key or "").startswith("attempt-")]

    async def is_notified(self, family: Family) -> bool:
        return await self.store.by_key(family.id, "intro", "notified") is not None

    async def notify_parent(self, family: Family) -> bool:
        """The parent is NOTIFIED, not asked: a WhatsApp voice note + text in their language (AI assistant called <brand>, who set it
        up, what it does and does not do, how to stop). With no WhatsApp adapter it waits in the app outbox. Marks 'notified'."""
        c = self.ctx
        parent = await c.parent(family)
        if parent is None or await self.is_notified(family):
            return False
        slots = await c.slots(family)
        text = "\n".join(c.say(k, parent.language, **slots) for k in ("notify.set_up_by", "intro.will", "intro.wont", "intro.no", "notify.stop"))
        ch = c.parent_channel
        sent = False
        if ch is not None:
            try:
                sent = bool(await ch.send_voice_note(parent, text, parent.language))
                await ch.send_text(parent, text)
            except Exception as e:  # noqa: BLE001
                log.warning("robin: notification to the parent failed (%s)", type(e).__name__)
        if not sent:
            await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", status="queued", at=c.clock.now(), data={"member_id": parent.id, "line": "notify", "purpose": "notify", "text": text, "incident_id": None}))
        await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="intro", key="notified", status="done", at=c.clock.now(), data={"voice_note": sent}))
        await c.audit(family, "notify", f"Told {family.parent_label} that {c.brand} was set up for them, what it does and how to stop it.")
        return True

    async def start(self, family: Family) -> str:
        """Place the introduction call now. Returns a short status code (the commands turn it into a chat line)."""
        c = self.ctx
        parent = await c.parent(family)
        if parent is None:
            return "no_parent"
        recs = await self.attempts(family)
        if any(r.status == "done" for r in recs):
            return "already_notified"
        if any(r.status == "declined" for r in recs):
            return "declined_before"
        if len([r for r in recs if r.status != "refused"]) >= MAX_ATTEMPTS:
            return "attempts_exhausted"
        n = len(recs) + 1
        rec, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="intro", key=f"attempt-{n}", status="calling", at=c.clock.now(), data={}))
        if not created:
            return "in_progress"
        out = await c.call(family, parent, "intro", self.steps(await c.slots(family)), dedupe_key=f"intro:{family.id}:{n}", max_seconds=300)
        return await self._finish(family, rec, out)

    async def _finish(self, family: Family, rec: Record, out) -> str:  # noqa: ANN001
        c = self.ctx
        lang = await c.chat_lang(family)
        slots = await c.slots(family)
        if out.result == CallResult.REFUSED:
            await self.store.cas(rec.id, "calling", status="refused", due_at=None)
            if out.detail == "line_pending":
                await c.tell_child(family, c.say("setup.intro_pending_line", lang, **slots))
            elif "test_allowlist" in out.detail:
                await c.tell_child(family, c.say("setup.not_allowed", lang, **slots))
            else:
                await c.tell_child(family, c.say("intro.result.refused", lang, why=out.detail))
            return f"refused:{out.detail}"
        if out.result != CallResult.ANSWERED:
            retry = (c.clock.now() + RETRY_AFTER) if rec.key == "attempt-1" else None
            await self.store.cas(rec.id, "calling", status="no_answer", due_at=retry)
            await c.tell_child(family, c.say("intro.result.no_answer", lang, **slots))
            return "no_answer"
        parent = await c.parent(family)
        said = {a.line: a.text for a in out.answers}
        stopped = out.detail == "stop_requested" or any(ans.is_stop(t) for t in said.values())
        if stopped and parent is not None:
            await self.store.cas(rec.id, "calling", status="declined", due_at=None)
            await self.fam.pause(parent.id, "voice")  # tells the child; only the parent can resume the sensitive items
            return "stopped"
        for item in VOICE_CONSENT_ITEMS:  # only when the call asked: the parent's own yes replaces the admin's basis
            if ans.yesno(said.get(f"intro.ask.{item.value}", "")) is True and parent is not None:
                await self.fam.give_consent(parent.id, item.value, ConsentSource.VOICE_YES, given_by="user")
        await self.store.cas(rec.id, "calling", status="done", due_at=None)
        active = await c.active_items(parent) if parent is not None else set()
        idx = 0 if lang == "en" else 1
        on = [ITEM_LABEL[i][idx] for i in sorted(active)]
        off = [v[idx] for k, v in ITEM_LABEL.items() if k not in active]
        await c.tell_child(family, c.say("intro.result.consented", lang, items=", ".join(on) or "-", declined=", ".join(off) or "-", **slots))
        return "notified"

    async def reset_declined(self, family: Family) -> None:
        """The child talked to the parent and asks Robin to try again."""
        for r in await self.attempts(family):
            await self.store.delete_record(r.id)

    async def retry_due(self) -> int:
        n = 0
        for rec in await self.store.due("intro", ("no_answer",), self.ctx.clock.now()):
            fam = await self.store.get_family(rec.family_id)
            if fam is None or fam.status == FamilyStatus.DELETED or not await self.store.cas(rec.id, "no_answer", status="retried", due_at=None):
                continue
            await self.start(fam)
            n += 1
        return n
