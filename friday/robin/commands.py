# ruff: noqa: E501
"""The child's (admin's) chat commands: onboarding and everything Robin does. Used by the web chat and the WhatsApp path
(``friday/api/inbound.py`` calls ``RobinHub.handle`` right after the document hook).

Onboarding is a small state machine kept in one record (kind ``pending``, key ``setup``): phone, language, check-in time,
quiet hours, second contact, sensitivity, may-I-ring-you. At the end the admin's consent is recorded for the non-sensitive
items (basis ``admin_on_behalf``), the parent is NOTIFIED (voice note + text, and an optional introduction call), and
nothing rings the parent before that notification. Sensitive items are switched on by a separate, explicit 'enable ...'.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User
from friday.robin.alerts import AlertEngine
from friday.robin.checkin import CheckinService
from friday.robin.context import Ctx
from friday.robin.family import ITEM_LABEL, FamilyService
from friday.robin.intro import IntroService
from friday.robin.medicine import MedicineService, days_left, parse_add, parse_clock
from friday.robin.models import (
    VOICE_CONSENT_ITEMS,
    ConsentSource,
    Family,
    FamilyStatus,
)
from friday.robin.store import Record

log = get_logger(__name__)

HAS_IT_PHRASES = ("i have it", "i've got it", "main dekh leta hoon", "main dekh leti hoon")
SAFE_PHRASES = ("mark safe", "safe")
ACK_PHRASES = HAS_IT_PHRASES + SAFE_PHRASES

_REL = {"father": "Papa", "dad": "Papa", "papa": "Papa", "pitaji": "Papa", "mother": "Mummy", "mom": "Mummy", "mummy": "Mummy", "mama": "Mummy", "maa": "Mummy", "ma": "Mummy"}
_SETUP = re.compile(r"^\s*(?:please\s+)?set\s*up\s+\w+\s+for\s+(?:my\s+)?(?P<rel>[a-z ]{2,20}?)\s*$", re.I)
_SETUP_HI = re.compile(r"^\s*(?P<rel>[a-z]{2,10})\s+ke\s+liye\s+\w+\s+set\s*up(?:\s+karo)?\s*$", re.I)
_HINGLISH = re.compile(r"\b(ke|liye|karo|kya|hai|mera|meri|papa|mummy|haan|nahi|kripya)\b|[ऀ-ॿ]", re.I)
_ITEM_WORDS = {"device signals": "device_signals", "phone signals": "device_signals", "payment alerts": "payment_alerts", "location": "location", "call listening": "call_listening", "authority calls": "authority_calls", "emergency desk": "authority_calls", "scam check": "scam_check", "daily check-in": "daily_checkin_calls", "check-in calls": "daily_checkin_calls", "medicine reminders": "medicine_reminders", "share summary": "share_summary_with_child"}
_PAIR = re.compile(r"^(?:please\s+)?pair\s+(?:the\s+|a\s+|my\s+)?(?:phone|app|device)(?:\s+(?:for|of)\s+(?:my\s+)?[a-z ]{2,24})?$|^pair\s+[a-z]{2,12}(?:'s|s)?\s+(?:phone|app)$|^[a-z]{2,12}\s+ka\s+phone\s+(?:jodo|pair\s+karo|connect\s+karo)$", re.I)
_FORWARD = re.compile(r"^(?:set\s*up\s+)?forward(?:ing)?\s+(?:on\s+)?([a-z ]{2,24}?)(?:\s+for\s+(me|my phone|mine))?$", re.I)
_FORWARD_TEST = re.compile(r"^test\s+(?:the\s+)?forward(?:ing)?$|^forward(?:ing)?\s+test$", re.I)
_WHAT_ON = re.compile(r"^what(?:'s|s| is| are)\s+(?:switched\s+|turned\s+)?on(?:\s+for\s+\w+)?\??$|^kya\s+kya\s+chalu\s+hai\??$", re.I)
_WHAT_TODAY = re.compile(r"^what\s+(?:did\s+\w+\s+do|\w+\s+did)(?:\s+today)?\??$|^aaj\s+\w+\s+ne\s+kya\s+kiya\??$", re.I)
_STEPS = ("phone", "language", "time", "quiet", "second", "sens", "childcall")


def _lang_of(text: str) -> str:
    return "hinglish" if _HINGLISH.search(text or "") else "en"


class RobinCommands:
    def __init__(self, ctx: Ctx, fam: FamilyService, intro: IntroService, checkin: CheckinService, meds: MedicineService, alerts: AlertEngine, safe_word_switch: bool = False) -> None:
        self.ctx, self.fam, self.intro, self.checkin, self.meds, self.alerts, self.store = ctx, fam, intro, checkin, meds, alerts, ctx.store
        self.safe_word_switch = safe_word_switch
        self.device: Any = None  # T08: getter -> the robindevice DeviceService (None or absent = phone pairing is off); set by the hub

    async def _reply(self, user: User, key: str, lang: str, buttons: list | None = None, **slots: object) -> bool:
        await self.ctx.send(user.id, self.ctx.say(key, lang, **slots), buttons or [])
        return True

    async def _text(self, user: User, text: str) -> bool:
        await self.ctx.send(user.id, text, [])
        return True

    # ------------------------------------------------------------------ entry
    async def handle(self, user: User, msg: InboundMessage) -> bool:  # noqa: C901
        fam = await self.fam.family_of_owner(user.id)
        if msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith("rb:"):
            _, inc, action = (msg.button_id.split(":") + ["", ""])[:3]
            if fam is None:
                return False
            if action in ("ordered", "rxyes", "rxno"):  # T12: medicine buttons share the rb: prefix (inc = the medicine id / family id)
                return await self._medicine_button(user, fam, inc, action, await self.ctx.chat_lang(fam))
            out = await self.alerts.on_button(fam, inc, action)
            if out:
                await self._text(user, out)
            return True
        if msg.kind != MessageKind.TEXT or not (msg.text or "").strip():
            return False
        text = " ".join(msg.text.strip().split())
        t = text.lower()
        lang = (await self.ctx.chat_lang(fam)) if fam else _lang_of(text)

        m = _SETUP.match(text) or _SETUP_HI.match(text)
        if m:
            return await self._setup_start(user, m.group("rel").strip().lower(), lang)
        if fam is None:
            if t in ("parent status", "papa status", "mummy status") or _PAIR.match(text) or _WHAT_ON.match(text) or _WHAT_TODAY.match(text):
                return await self._reply(user, "setup.no_family", lang)
            return False
        await self._show_held(fam)  # T08: what the child's phone could not receive earlier is shown first, once
        pend = await self.store.by_key(fam.id, "pending", "setup")
        if pend is not None and pend.status in _STEPS:
            handled = await self._setup_step(user, fam, pend, text, lang)
            if handled:
                return True
        conf = await self.store.by_key(fam.id, "pending", "delete")
        if conf is not None:
            await self.store.delete_record(conf.id)
            if text.strip() == "DELETE":
                return await self._delete(user, fam, lang)
            return await self._reply(user, "cmd.delete_cancelled", lang)
        return await self._command(user, fam, text, t, lang)

    async def _medicine_button(self, user: User, fam: Family, ref: str, action: str, lang: str) -> bool:
        """'ordered' on a refill alert (Robin never orders or pays), or yes/no on a prescription proposal."""
        if action == "ordered":
            name = await self.meds.mark_ordered(fam, ref)
            return await self._reply(user, "med.ordered_ack", lang, medicine=name) if name else await self._reply(user, "med.not_found", lang)
        if not await self.meds.has_proposal(fam):
            return await self._reply(user, "med.rx_nothing_open", lang)
        n = await self.meds.confirm(fam, action == "rxyes")
        return await self._reply(user, "med.confirm_saved" if action == "rxyes" else "med.confirm_dropped", lang, n=n)

    # ------------------------------------------------------------------ T08: pairing the parent's phone, the held inbox
    async def _pair(self, user: User, fam: Family, parent: Any, lang: str) -> bool:
        """"pair phone for papa": a single-use code (15 minutes) and a robin://pair link, shown to the CHILD, who enters it on the parent's phone.
        The parent never types. The code is a secret: it goes into the reply only, never into the audit log or a log line."""
        slots = {"parent": fam.parent_label}
        if parent is None:
            return await self._reply(user, "pair.not_ready", lang, **slots)
        svc = self.device() if self.device is not None else None
        if svc is None:
            return await self._reply(user, "pair.off", lang)
        try:
            code = await svc.create_pairing_code(parent.id)
        except Exception as e:  # noqa: BLE001 - unknown parent on the device side
            log.warning("robin: pairing code could not be made (%s)", type(e).__name__)
            return await self._reply(user, "pair.off", lang)
        from friday.robindevice.store import PAIR_CODE_TTL_S

        await self.ctx.audit(fam, "pair_code", f"Made a one-time code to connect {fam.parent_label}'s phone (the code itself is not kept in this log).")
        return await self._reply(user, "pair.steps", lang, code=code, link=f"robin://pair?code={code}", minutes=PAIR_CODE_TTL_S // 60, **slots)

    async def _forward(self, user: User, fam: Family, carrier_text: str, for_child: bool, lang: str) -> bool:
        """"forwarding jio": the per-carrier codes (all [U], unverified on a real SIM) for the parent's phone, or the child's own with 'for me'."""
        from friday.robin.forwarded import forwarding_text, known_carrier

        key = known_carrier(carrier_text)
        if key is None:
            return await self._reply(user, "forward.unknown_carrier", lang)
        child = await self.ctx.child(fam)
        who = ((child.name if child else "") or "you") if for_child else fam.parent_label
        text = forwarding_text(self.ctx, key, who=who, lang=lang)
        if text is None:
            return await self._reply(user, "forward.unavailable", lang)
        await self.ctx.audit(fam, "forwarding_help", f"Showed the call-forwarding steps for {'your phone' if for_child else fam.parent_label + chr(39) + 's phone'}.")
        return await self._text(user, text)

    async def _show_held(self, fam: Family) -> None:
        inbox = self.ctx.inbox
        if inbox is not None:
            try:
                await inbox.deliver(fam, self.ctx.send)
            except Exception as e:  # noqa: BLE001 - never blocks the command
                log.warning("robin: could not show the held messages (%s)", type(e).__name__)

    # ------------------------------------------------------------------ onboarding
    async def _setup_start(self, user: User, rel_word: str, lang: str) -> bool:
        label = _REL.get(rel_word.split()[-1] if rel_word else "", rel_word.title()[:24] or "Papa")
        rel = "father" if label == "Papa" else "mother" if label == "Mummy" else rel_word
        old = await self.fam.family_of_owner(user.id)
        if old is not None:
            await self.fam.erase(old)
        fam = await self.fam.create_family(user, parent_label=label, child_language=lang)
        await self.store.put(Record(family_id=fam.id, user_id=user.id, kind="pending", key="setup", status="phone", at=self.ctx.clock.now(), data={"rel": rel}))
        return await self._reply(user, "setup.start", lang, rel=rel)

    async def _set_step(self, rec: Record, status: str, **data: Any) -> None:
        await self.store.cas(rec.id, rec.status, status=status, data={**rec.data, **data})

    async def _setup_step(self, user: User, fam: Family, rec: Record, text: str, lang: str) -> bool:  # noqa: C901
        step, d = rec.status, rec.data
        t = text.lower()
        slots = {"parent": fam.parent_label}
        if t in ("cancel", "stop setup", "cancel setup"):
            await self.fam.erase(fam)
            return await self._reply(user, "setup.cancelled", lang)
        if step == "phone":
            res = await self.fam.add_parent(fam, text, language="hinglish")
            if res == "bad_number":
                return await self._reply(user, "setup.bad_number", lang)
            if res == "same_number":
                return await self._reply(user, "setup.same_number", lang, rel=d.get("rel", "parent"))
            await self._set_step(rec, "language")
            return await self._reply(user, "setup.ask_language", lang, **slots)
        parent = await self.ctx.parent(fam)
        if parent is None:
            return False
        if step == "language":
            pl = "hi" if t.startswith("hindi") or t == "hi" else "en" if t.startswith("eng") else "hinglish" if t.startswith("hing") else None
            if pl is None:
                return await self._reply(user, "setup.ask_language", lang, **slots)
            parent.language = pl
            await self.store.save_member(parent, fam.owner_user_id)
            await self._set_step(rec, "time")
            return await self._reply(user, "setup.ask_time", lang)
        if step == "time":
            hhmm = parse_clock(re.sub(r"^(?:at\s+|subah\s+)", "", t))
            if hhmm is None:
                return await self._reply(user, "setup.bad_time", lang)
            if self._in_window(hhmm, fam.settings.quiet_start, fam.settings.quiet_end):
                return await self._reply(user, "setup.time_in_quiet", lang, start=fam.settings.quiet_start, end=fam.settings.quiet_end)
            await self.fam.update_settings(fam, checkin_time=hhmm)
            await self._set_step(rec, "quiet")
            return await self._reply(user, "setup.ask_quiet", lang, start=fam.settings.quiet_start, end=fam.settings.quiet_end, **slots)
        if step == "quiet":
            if t not in ("ok", "okay", "haan", "yes"):
                mm = re.match(r"^(.+?)\s*(?:-|–|to)\s*(.+)$", t)
                a, b = (parse_clock(mm.group(1)), parse_clock(mm.group(2))) if mm else (None, None)
                if a is None or b is None:
                    return await self._reply(user, "setup.bad_quiet", lang)
                await self.fam.update_settings(fam, quiet_start=a, quiet_end=b)
                if self._in_window(fam.settings.checkin_time, a, b):
                    await self._set_step(rec, "time")
                    return await self._reply(user, "setup.time_in_quiet", lang, start=a, end=b)
            await self._set_step(rec, "second")
            return await self._reply(user, "setup.ask_second", lang)
        if step == "second":
            if t not in ("no", "nahi", "none", "n"):
                res = await self.fam.set_second_contact(fam, text)
                if res == "bad_number":
                    return await self._reply(user, "setup.bad_number", lang)
            await self._set_step(rec, "sens")
            return await self._reply(user, "setup.ask_sensitivity", lang)
        if step == "sens":
            s = self.fam.sensitivity(t)
            if s is None:
                return await self._reply(user, "setup.bad_sensitivity", lang)
            await self.fam.update_settings(fam, sensitivity=s)
            await self._set_step(rec, "childcall")
            return await self._reply(user, "setup.ask_child_call", lang, **slots)
        if step == "childcall":
            yes = t in ("yes", "y", "haan", "ha", "ok")
            child = await self.ctx.child(fam)
            if child is not None:
                child.call_ok = yes
                await self.store.save_member(child, fam.owner_user_id)
            await self.store.cas(rec.id, "childcall", status="done")
            return await self._finish_setup(user, fam, parent, lang)
        return False

    @staticmethod
    def _in_window(hhmm: str, start: str, end: str) -> bool:
        t, s, e = (tuple(int(x) for x in v.split(":")) for v in (hhmm, start, end))
        return (s <= t < e) if s < e else (t >= s or t < e)

    async def _finish_setup(self, user: User, fam: Family, parent: Any, lang: str) -> bool:
        # the admin's consent on the parent's behalf, for the non-sensitive items; sensitive ones need an explicit 'enable'
        for item in VOICE_CONSENT_ITEMS:
            await self.fam.give_consent(parent.id, item.value, ConsentSource.ADMIN_CHAT, given_by="admin_on_behalf")
        slots = {"parent": fam.parent_label}
        await self._reply(user, "setup.done", lang, **slots)
        if getattr(self.ctx.settings, "robin_forwarded_calls_enabled", False):  # T10: offer the missed-call forwarding steps (per carrier)
            await self._reply(user, "forward.ask", lang, who=fam.parent_label)
        await self.intro.notify_parent(fam)
        status = await self.intro.start(fam)  # the optional introduction call; refused while lines are PENDING / number not allow-listed
        if status.startswith("refused"):
            pass  # IntroService already told the child why
        return True

    # ------------------------------------------------------------------ the rest
    async def _command(self, user: User, fam: Family, text: str, t: str, lang: str) -> bool:  # noqa: C901
        c = self.ctx
        slots = {"parent": fam.parent_label}
        parent = await c.parent(fam)
        if t in (f"{c.brand.lower()} help", "robin help", "help robin"):
            return await self._reply(user, "cmd.help", lang)
        if re.match(r"^(?:parent|papa|mummy|mom|dad|mama)\s+status$|^how is (?:papa|mummy|mom|dad|mama|my \w+)\??$", t):
            return await self._status(user, fam, lang)
        if _PAIR.match(text):
            return await self._pair(user, fam, parent, lang)
        if getattr(c.settings, "robin_forwarded_calls_enabled", False):  # T10: missed-call forwarding setup text; switch off = these words are not ours
            if _FORWARD_TEST.match(text.strip()):
                return await self._reply(user, "forward.test", lang, who=fam.parent_label, seconds=int(c.settings.robin_forwarded_call_max_s))
            mf = _FORWARD.match(text.strip())
            if mf:
                return await self._forward(user, fam, mf.group(1), bool(mf.group(2)), lang)
        if _WHAT_ON.match(text):
            return await self._text(user, await self.fam.render_view(fam, "on"))
        if _WHAT_TODAY.match(text):
            return await self._text(user, await self.fam.render_view(fam, "today"))
        if re.match(r"^call\s+(?:papa|mummy|mom|dad|mama|parent|my \w+)$", t):
            await self._reply(user, "callnow.started", lang, **slots)
            await self.checkin.call_now(fam)
            return True
        if t.startswith("add medicine") or t.startswith("add dawai"):
            if parent is None:
                return False
            today = c.local(parent).date()
            res = parse_add(text, today)
            if isinstance(res, str):
                return await self._reply(user, "med.format", lang)
            await self.meds.add(fam, res)
            await self._reply(user, "med.added", lang, medicine=res.name, times=", ".join(res.times), days=days_left(res, today))
            if not await c.has_consent(parent, "medicine_reminders"):
                await self._reply(user, "med.consent_missing", lang, **slots)
            return True
        if t in ("medicines", "medicine", "meds", "list medicines", "dawaiyan"):
            rows = await self.meds.summary_for_list(fam)
            return await self._text(user, "\n".join(rows)) if rows else await self._reply(user, "med.list_empty", lang, **slots)
        mm = re.match(r"^remove (?:medicine |dawai )?(.+)$", t)
        if mm:
            name = await self.meds.remove(fam, mm.group(1))
            return await self._reply(user, "med.removed", lang, medicine=name) if name else await self._reply(user, "med.not_found", lang)
        mm = re.match(r"^pills left (.+?) (\d+)$", t)
        if mm:
            ok = await self.meds.set_count(fam, mm.group(1), int(mm.group(2)))
            return await self._text(user, "OK" if ok else c.say("med.not_found", lang))
        if t in ("yes", "y", "haan", "ha") and await self.meds.has_proposal(fam):
            n = await self.meds.confirm(fam, True)
            return await self._reply(user, "med.confirm_saved", lang, n=n)
        if t in ("no", "nahi", "n") and await self.meds.has_proposal(fam):
            await self.meds.confirm(fam, False)
            return await self._reply(user, "med.confirm_dropped", lang)
        mm = re.match(r"^check-?\s?in time\s+(.+)$", t)
        if mm:
            hhmm = parse_clock(re.sub(r"^(?:at\s+)", "", mm.group(1)))
            if hhmm is None:
                return await self._reply(user, "setup.bad_time", lang)
            if self._in_window(hhmm, fam.settings.quiet_start, fam.settings.quiet_end):
                return await self._reply(user, "setup.time_in_quiet", lang, start=fam.settings.quiet_start, end=fam.settings.quiet_end)
            await self.fam.update_settings(fam, checkin_time=hhmm)
            return await self._reply(user, "cmd.checkin_set", lang, time=hhmm, **slots)
        mm = re.match(r"^sensitivity\s+(\w+)$", t)
        if mm:
            s = self.fam.sensitivity(mm.group(1))
            if s is None:
                return await self._reply(user, "setup.bad_sensitivity", lang)
            await self.fam.update_settings(fam, sensitivity=s)
            return await self._reply(user, "cmd.sensitivity_set", lang, level=s.value)
        if re.match(r"^what (?:does|do) \w+ see\??$", t) or t in ("what do you see", "what you see"):
            return await self._text(user, await self.fam.render_view(fam))
        mm = re.match(r"^pause reminders?(?: (?:for )?(\d+) days?)?$", t)
        if mm:
            days = int(mm.group(1) or 1)
            until = c.clock.now() + timedelta(days=days)
            await self.fam.update_settings(fam, reminders_paused_until=until)
            return await self._reply(user, "med.paused", lang, until=until.strftime("%d %b"))
        if t in ("resume reminders", "resume reminder"):
            await self.fam.update_settings(fam, reminders_paused_until=None)
            return await self._reply(user, "med.resumed", lang)
        if t in ("digest", "daily digest", "weekly digest"):
            out = await self.checkin.digest_now(fam, weekly=t.startswith("weekly"))
            return await self._text(user, out or c.say("digest.empty", lang))
        if self.safe_word_switch:
            mm = re.match(r"^safe word (on|off)$", t)
            if mm:
                await self.fam.update_settings(fam, safe_word_enabled=mm.group(1) == "on")
                return await self._text(user, f"safe word {mm.group(1)}")
            mm = re.match(r"^safe word (.+)$", t)
            if mm:
                if not fam.settings.safe_word_enabled:
                    return await self._text(user, c.say("safeword.format", lang, **slots))
                ok = await self.fam.set_safe_word(fam, mm.group(1))
                return await self._reply(user, "safeword.set" if ok else "safeword.format", lang, **slots)
        mm = re.match(r"^(enable|switch on|turn on)\s+(.+)$", t)
        if mm:
            item = _ITEM_WORDS.get(mm.group(2).strip())
            if item is None:
                return await self._reply(user, "enable.unknown", lang, items=", ".join(sorted(_ITEM_WORDS)))
            res = await self.fam.admin_consent(fam, item)
            label = ITEM_LABEL[item][0 if lang == "en" else 1]
            if res == "parent_paused":
                return await self._reply(user, "consent.parent_paused", lang, item=label, **slots)
            await self._reply(user, "enable.done", lang, item=label, **slots)
            return await self._reply(user, "consent.admin_given", lang, item=label, **slots)
        mm = re.match(r"^(disable|switch off|turn off)\s+(.+)$", t)
        if mm and _ITEM_WORDS.get(mm.group(2).strip()) and parent is not None:
            item = _ITEM_WORDS[mm.group(2).strip()]
            await self.fam.withdraw_consent(parent.id, item, tell_child=False, actor="admin_on_behalf", source="admin_chat")
            return await self._text(user, f"OK: {ITEM_LABEL[item][0]} off")
        mm = re.match(r"^(good morning|festival greetings?) (on|off)$", t)
        if mm:
            on = mm.group(2) == "on"
            if mm.group(1) == "good morning":
                await self.fam.update_settings(fam, good_morning=on)
                return await self._reply(user, "gm.on" if on else "gm.off", lang, **slots)
            await self.fam.update_settings(fam, festival_graphics=on)
            return await self._reply(user, "fest.on" if on else "fest.off", lang, **slots)
        mm = re.match(r"^guardian mode\s*(.*)$", t)
        if mm:
            basis = mm.group(1).strip()
            if basis == "off":
                await self.fam.clear_guardian(fam)
                return await self._reply(user, "guardian.off", lang, **slots)
            if not await self.fam.set_guardian(fam, basis):
                return await self._reply(user, "guardian.bad_basis", lang)
            return await self._reply(user, "guardian.set", lang, basis=basis[:200], **slots)
        mm = re.match(r"^(?:parent name|papa name)\s+(.{2,40})$", text, re.I)
        if mm and parent is not None:
            parent.name = mm.group(1).strip()
            await self.store.save_member(parent, fam.owner_user_id)
            return await self._reply(user, "authority.set_name", lang)
        mm = re.match(r"^(?:set )?address\s+(.{5,200})$", text, re.I)
        if mm and parent is not None:
            parent.address = mm.group(1).strip()
            await self.store.save_member(parent, fam.owner_user_id)
            return await self._reply(user, "authority.set_address", lang)
        if t in ("confirm emergency", "yes it is an emergency"):
            rec = await self.alerts.latest_open(fam)
            if rec is not None and await self.alerts.confirm_emergency(fam, rec.id, "child"):
                return await self._reply(user, "alert.taken", lang)
        if t in ("try intro again", "retry introduction"):
            await self.intro.reset_declined(fam)
            await self.intro.start(fam)
            return True
        if t in ("details", "show details"):
            rec = await self.alerts.latest_open(fam)
            return await self._text(user, self.alerts.details(rec, lang)) if rec else await self._reply(user, "alert.unknown", lang)
        if t in HAS_IT_PHRASES:
            return await self._ack(user, fam, "child_has_it", lang)
        if t in SAFE_PHRASES:
            return await self._ack(user, fam, "child_safe", lang)
        if t in ("delete everything for my parent", "delete everything for my parents"):
            await self.store.put(Record(family_id=fam.id, user_id=user.id, kind="pending", key="delete", status="ask", at=c.clock.now(), data={}))
            return await self._reply(user, "cmd.delete_ask", lang, **slots)
        return False

    async def is_open_ack(self, user_id: str, text: str) -> bool:
        """T20: True when ``text`` is exactly the child's "I have it" / "Mark safe" AND an alert is open, so the care protocol lets it through
        (a care episode must not swallow the word that stops an alert)."""
        if " ".join(text.lower().split()) not in ACK_PHRASES:
            return False
        fam = await self.fam.family_of_owner(user_id)
        return fam is not None and await self.alerts.latest_open(fam) is not None

    async def _ack(self, user: User, fam: Family, by: str, lang: str) -> bool:
        latest = await self.alerts.latest_open(fam)
        if latest is None:
            return False  # not ours: let the normal chat answer
        await self.hub_cancel_authority(fam, latest.id, by)
        if not await self.alerts.stop(fam, None, by):
            await self._reply(user, "alert.unknown", lang)
        return True

    async def hub_cancel_authority(self, fam: Family, incident_id: str, by: str) -> None:
        auth = getattr(self.alerts, "authority", None)
        if auth is not None:
            await auth.cancel(fam, incident_id, by)

    async def _status(self, user: User, fam: Family, lang: str) -> bool:
        c = self.ctx
        parent = await c.parent(fam)
        state = c.say("status.paused" if fam.status == FamilyStatus.PAUSED else "status.active", lang, parent=fam.parent_label)
        today = (await c.audit_today(fam, parent))[-1:]
        meds = len(await self.meds.meds(fam))
        alerts = await self.alerts.open_count(fam)
        await self._reply(user, "status.line", lang, parent=fam.parent_label, state=state, time=fam.settings.checkin_time, today=today[0].data["text"] if today else "-", meds=meds, alerts=alerts)
        return True

    async def _delete(self, user: User, fam: Family, lang: str) -> bool:
        label = fam.parent_label
        await self.fam.erase(fam)
        return await self._reply(user, "cmd.delete_done", lang, parent=label)

