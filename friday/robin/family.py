# ruff: noqa: E501
"""The family model in action: create a family, add the parent / second contact, record and withdraw
consent, pause and resume (by the parent, at any time), the 'what your child sees' view, the safe word,
the app-notification outbox, and 'delete everything'.

Consent is per parent and per item, with a timestamp, a source (voice yes / app tap) and a withdrawal
time. NOTHING calls a parent before a consent exists: ``context.Ctx.call`` enforces it, and the only
exception is the introduction call itself (the consent call).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from friday.calls.numbers import canonical
from friday.core.logging import get_logger
from friday.core.models import User
from friday.robin import lines
from friday.robin.context import Ctx
from friday.robin.models import (
    CONSENT_ITEMS,
    SENSITIVE_ITEMS,
    Consent,
    ConsentSource,
    Family,
    FamilySettings,
    FamilyStatus,
    Member,
    Role,
    Sensitivity,
)
from friday.robin.ports import run_erase_hooks
from friday.robin.store import Record

log = get_logger(__name__)

ITEM_LABEL = {
    "daily_checkin_calls": ("daily check-in calls", "roz ke check-in call"),
    "medicine_reminders": ("medicine reminders", "dawai ke reminders"),
    "scam_check": ("scam check", "scam check"),
    "device_signals": ("phone safety signals", "phone ke safety signals"),
    "payment_alerts": ("payment alerts", "payment alerts"),
    "location": ("location (only in an SOS)", "location (sirf SOS mein)"),
    "authority_calls": ("the emergency desk contacting the authorities (dry-run first)", "emergency desk ka authorities ko phone (pehle dry-run)"),
    "call_listening": ("the assistant listening in on calls routed through its own line", "assistant ka apni line se guzri calls mein sunna"),
    "share_summary_with_child": ("sharing a daily summary with your child", "roz ka saar bachche ko dikhana"),
}


class FamilyService:
    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self.store = ctx.store

    # ------------------------------------------------------------------ create
    async def create_family(self, owner: User, *, parent_label: str = "Papa", child_name: str = "", child_language: str = "hinglish") -> Family:
        fam = Family(owner_user_id=owner.id, parent_label=parent_label.strip()[:24] or "Papa", created_at=self.ctx.clock.now(), settings=FamilySettings(refill_days=int(getattr(self.ctx.settings, "robin_refill_days", 5))))
        await self.store.save_family(fam)
        child = Member(family_id=fam.id, role=Role.CHILD, name=child_name.strip()[:40], phone=owner.phone, language=child_language, user_id=owner.id)
        await self.store.save_member(child, owner.id)
        await self.ctx.audit(fam, "setup", f"{self.ctx.brand} was set up for {fam.parent_label}. No call will be made until they agree.")
        return fam

    async def add_parent(self, family: Family, phone: str, *, language: str = "hinglish", name: str = "") -> Member | str:
        """Returns the Member, or an error code ('bad_number', 'same_number')."""
        e164 = canonical(phone) if phone else None
        if e164 is None:
            try:
                from friday.core.models import normalize_phone

                e164 = normalize_phone(phone, "+91")
            except ValueError:
                return "bad_number"
            e164 = canonical(e164)
        if e164 is None:
            return "bad_number"
        owner = await self.ctx.owner(family)
        if owner is not None and canonical(owner.phone) == e164:
            return "same_number"
        for old in await self.store.members(family.id, Role.PARENT):
            await self.store.delete_member(old.id)
        m = Member(family_id=family.id, role=Role.PARENT, name=name.strip()[:40], phone=e164, language=language if language in lines.LANGS else "hinglish")
        await self.store.save_member(m, family.owner_user_id)
        return m

    async def set_second_contact(self, family: Family, phone: str, name: str = "") -> Member | str:
        e164 = canonical(phone)
        if e164 is None:
            return "bad_number"
        for old in await self.store.members(family.id, Role.SECOND_CONTACT):
            await self.store.delete_member(old.id)
        # named in advance by the child = the child asked Robin to contact them in an incident
        m = Member(family_id=family.id, role=Role.SECOND_CONTACT, name=name.strip()[:40], phone=e164, call_ok=True)
        await self.store.save_member(m, family.owner_user_id)
        await self.ctx.audit(family, "setup", "A second contact was named in advance.")
        return m

    async def update_settings(self, family: Family, **changes: Any) -> Family:
        data = family.settings.model_dump()
        data.update(changes)
        family.settings = FamilySettings(**data)
        await self.store.save_family(family)
        return family

    async def set_status(self, family: Family, status: FamilyStatus) -> Family:
        family.status = status
        await self.store.save_family(family)
        return family

    # ------------------------------------------------------------------ consent
    async def give_consent(self, member_id: str, item: str, source: ConsentSource, *, given_by: str = "admin_on_behalf") -> Consent | None:
        """Record a consent for a parent. ``admin_on_behalf`` (source admin_chat) is the normal route; a parent's own
        yes (voice / app tap, ``given_by='user'``) is recorded with its own basis and replaces the admin's."""
        member = await self.store.get_member(member_id)
        if member is None or member.role != Role.PARENT or item not in CONSENT_ITEMS:
            return None
        family = await self.store.get_family(member.family_id)
        if family is None or family.status == FamilyStatus.DELETED:
            return None
        if (given_by == "user") == (source == ConsentSource.ADMIN_CHAT) or given_by not in ("user", "admin_on_behalf"):
            return None  # the basis and the source must agree
        c = await self.store.save_consent(Consent(family_id=family.id, member_id=member.id, item=item, given_at=self.ctx.clock.now(), source=source, given_by=given_by), family.owner_user_id)
        if family.status == FamilyStatus.ONBOARDING:
            # the admin can never undo a parent's STOP: a parent who paused during setup keeps the family PAUSED
            await self.set_status(family, FamilyStatus.PAUSED if member.paused else FamilyStatus.ACTIVE)
        actor = "guardian" if given_by == "admin_on_behalf" and family.settings.guardian_basis else given_by
        who = family.parent_label if given_by == "user" else "the admin, on their behalf"
        flag = " Legal-review flag." if given_by == "admin_on_behalf" and item in SENSITIVE_ITEMS else ""
        await self.ctx.audit(family, "consent", f"{who} agreed to {ITEM_LABEL[item][0]} ({source.value}).{flag}", item=item, source=source.value, given_by=given_by, actor=actor, at=c.given_at.isoformat())
        return c

    async def request_consent(self, family: Family, item: str) -> str:
        """The admin REQUESTS an item. A sensitive one is asked of the parent; it is never switched on remotely."""
        if item not in CONSENT_ITEMS:
            return "unknown_item"
        key = f"req:{item}"
        await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", key=key, status="requested", at=self.ctx.clock.now(), data={"item": item}))
        await self.ctx.audit(family, "consent_request", f"The admin asked for {ITEM_LABEL[item][0]}; waiting for {family.parent_label}.", item=item, actor="admin_on_behalf", source="admin_chat", at=self.ctx.clock.now().isoformat())
        return "requested" if item in SENSITIVE_ITEMS else "not_sensitive"

    async def set_guardian(self, family: Family, basis: str) -> bool:
        if len(basis.strip()) < 8:
            return False
        await self.update_settings(family, guardian_basis=basis.strip()[:200], guardian_set_at=self.ctx.clock.now())
        await self.ctx.audit(family, "guardian", "Guardian mode was switched on by the admin; basis recorded, NOT verified (flagged for legal review).")
        return True

    async def clear_guardian(self, family: Family) -> None:
        await self.update_settings(family, guardian_basis=None, guardian_set_at=None)
        await self.ctx.audit(family, "guardian", "Guardian mode was switched off.")

    async def admin_consent(self, family: Family, item: str) -> str:
        """The admin consents for the parent (the normal route). After the PARENT stopped Robin, sensitive items stay off:
        only the parent can resume them; the admin's wish is recorded as a request."""
        parent = await self.ctx.parent(family)
        if parent is None:
            return "no_parent"
        if parent.paused and item in SENSITIVE_ITEMS:
            await self.request_consent(family, item)
            return "parent_paused"
        c = await self.give_consent(parent.id, item, ConsentSource.ADMIN_CHAT, given_by="admin_on_behalf")
        return "given" if c else "refused"

    async def add_co_admin(self, family: Family, user: User, name: str = "") -> Member:
        m = Member(family_id=family.id, role=Role.CO_ADMIN, name=name.strip()[:40], phone=user.phone, user_id=user.id, call_ok=True)
        await self.store.save_member(m, family.owner_user_id)
        await self.ctx.audit(family, "setup", "A co-admin was added.")
        return m

    async def monthly_reminder(self, family: Family) -> bool:
        """Once a month the parent is reminded (app notification) of what is switched on."""
        parent = await self.ctx.parent(family)
        if parent is None or parent.paused:
            return False
        key = f"monthly:{self.ctx.local(parent).strftime('%Y-%m')}"
        active = sorted(await self.ctx.active_items(parent))
        if not active:
            return False
        _, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="digest", key=key, status="sent", at=self.ctx.clock.now(), data={}))
        if not created:
            return False
        slots = {**await self.ctx.slots(family), "items": ", ".join(ITEM_LABEL[i][0] for i in active)}
        text = self.ctx.say("monthly.reminder", parent.language, **slots)
        await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", status="queued", at=self.ctx.clock.now(), data={"member_id": parent.id, "line": "monthly.reminder", "purpose": "monthly", "text": text, "incident_id": None}))
        await self.ctx.audit(family, "notify", f"Reminded {family.parent_label} of what is switched on.")
        return True

    async def withdraw_consent(self, member_id: str, item: str, *, tell_child: bool = True, actor: str = "user", source: str = "voice") -> bool:
        """``actor``: user (the parent), admin_on_behalf (the child) or guardian; ``source``: voice / app / parent_device / admin_chat."""
        member = await self.store.get_member(member_id)
        if member is None:
            return False
        family = await self.store.get_family(member.family_id)
        if family is None:
            return False
        ok = await self.store.withdraw(member.id, item, self.ctx.clock.now())
        if ok:
            who = family.parent_label if actor == "user" else "the admin, on their behalf"
            await self.ctx.audit(family, "consent", f"{who} withdrew consent for {ITEM_LABEL.get(item, (item,))[0]} ({source}).", item=item, source=source, actor=actor, at=self.ctx.clock.now().isoformat())
            if tell_child:
                lang = await self.ctx.chat_lang(family)
                await self.ctx.tell_child(family, self.ctx.say("consent.withdrawn", lang, parent=family.parent_label, item=ITEM_LABEL.get(item, (item, item))[0 if lang == "en" else 1]))
        return ok

    async def withdraw_all(self, member_id: str, *, actor: str = "user", source: str = "voice") -> int:
        member = await self.store.get_member(member_id)
        if member is None:
            return 0
        n = 0
        for c in await self.store.consents(member.family_id, member.id):
            if c.active and await self.withdraw_consent(member.id, c.item, tell_child=False, actor=actor, source=source):
                n += 1
        return n

    # ------------------------------------------------------------------ pause / resume by the parent
    async def pause(self, parent_member_id: str, source: str = "voice") -> bool:
        m = await self.store.get_member(parent_member_id)
        fam = await self.store.get_family(m.family_id) if m else None
        if m is None or fam is None or m.role != Role.PARENT or fam.status == FamilyStatus.DELETED:
            return False
        m.paused, m.paused_at = True, self.ctx.clock.now()
        await self.store.save_member(m, fam.owner_user_id)
        if fam.status == FamilyStatus.ACTIVE:
            await self.set_status(fam, FamilyStatus.PAUSED)
        await self.ctx.audit(fam, "pause", f"{fam.parent_label} paused {self.ctx.brand} ({source}).", actor="user", source=source, at=self.ctx.clock.now().isoformat())
        lang = await self.ctx.chat_lang(fam)
        await self.ctx.tell_child(fam, self.ctx.say("pause.parent", lang, parent=fam.parent_label))
        return True

    async def resume(self, parent_member_id: str, source: str = "voice", actor: str = "user") -> bool:
        """Only the PARENT resumes after a parent pause. Any other actor (the admin, a guardian) is refused and audited."""
        m = await self.store.get_member(parent_member_id)
        fam = await self.store.get_family(m.family_id) if m else None
        if m is None or fam is None or m.role != Role.PARENT or fam.status == FamilyStatus.DELETED:
            return False
        if actor != "user":
            if m.paused:
                await self.ctx.audit(fam, "resume_refused", f"The admin tried to resume {self.ctx.brand} after {fam.parent_label} paused it; refused, only {fam.parent_label} can resume.", actor=actor, source=source, at=self.ctx.clock.now().isoformat())
            return False
        m.paused, m.paused_at = False, None
        await self.store.save_member(m, fam.owner_user_id)
        if fam.status == FamilyStatus.PAUSED:
            await self.set_status(fam, FamilyStatus.ACTIVE)
        await self.ctx.audit(fam, "resume", f"{fam.parent_label} resumed {self.ctx.brand} ({source}).", actor="user", source=source, at=self.ctx.clock.now().isoformat())
        lang = await self.ctx.chat_lang(fam)
        await self.ctx.tell_child(fam, self.ctx.say("resume.parent", lang, parent=fam.parent_label))
        return True

    # ------------------------------------------------------------------ what each side sees
    async def view(self, family: Family) -> dict[str, Any]:
        """The ONE generated page, shown to the child ('what does Robin see') and to the parent (app screen)."""
        parent = await self.ctx.parent(family)
        consents = {c.item: c for c in (await self.store.consents(family.id, parent.id) if parent else [])}
        items = []
        for item in CONSENT_ITEMS:
            c = consents.get(item)
            items.append({
                "item": item, "label": ITEM_LABEL[item][0],
                "state": "withdrawn" if c and not c.active else ("agreed" if c else "not_agreed"),
                "given_at": c.given_at.isoformat() if c else None, "source": c.source.value if c else None, "given_by": c.given_by if c else None, "sensitive": item in SENSITIVE_ITEMS,
                "withdrawn_at": c.withdrawn_at.isoformat() if c and c.withdrawn_at else None,
            })  # fmt: skip
        active = {i["item"] for i in items if i["state"] == "agreed"}
        shared = []
        if "share_summary_with_child" in active:
            shared.append("daily check-in answers (ate, slept, pain, mood, strange calls, medicines)")
        else:
            shared.append("only whether the check-in call was answered")
        if "payment_alerts" in active:
            shared.append("payment alerts above the family limit (amount and time, no message text)")
        if "location" in active:
            shared.append("location, only during an SOS")
        shared.append("alerts about risky activity, with one line saying why")
        audit = await self.ctx.audit_today(family, parent)
        return {
            "parent_label": family.parent_label, "status": family.status.value, "paused": bool(parent and parent.paused),
            "items": items, "shared_with_child": shared,
            "never": ["records calls", "reads messages, notifications or SMS in this part", "asks for OTP, PIN or passwords", "pays money", "dials 112 by itself"],
            "audit_today": [{"at": r.at.isoformat(), "text": r.data.get("text", "")} for r in audit],
        }  # fmt: skip

    async def render_view(self, family: Family) -> str:
        v = await self.view(family)
        lang = await self.ctx.chat_lang(family)
        child = await self.ctx.child(family)
        slots = {"parent": family.parent_label, "child": (child.name if child and child.name else "you")}
        out = [self.ctx.say("view.child.head", lang, **slots)]
        idx = 0 if lang == "en" else 1
        for it in v["items"]:
            label = ITEM_LABEL[it["item"]][idx]
            when = (it["withdrawn_at"] or it["given_at"] or "")[:10]
            key = {"agreed": "view.item.on", "withdrawn": "view.item.withdrawn", "not_agreed": "view.item.off"}[it["state"]]
            out.append(self.ctx.say(key, lang, item=label, when=when, source=it["source"] or ""))
        out.append(self.ctx.say("view.shared", lang, child=slots["child"], shared="; ".join(v["shared_with_child"])))
        out.append(self.ctx.say("view.never", lang))
        out.append(self.ctx.say("view.audit_head", lang))
        rows = [f"- {r['text']}" for r in v["audit_today"][-12:]]
        out.extend(rows or [self.ctx.say("view.audit_empty", lang)])
        return "\n".join(out)

    # ------------------------------------------------------------------ safe word (stored hashed)
    def _sw_hash(self, family: Family, word: str) -> str:
        norm = " ".join(word.lower().split())
        return self.store.hasher.cipher.blind_index(norm, label=f"robin_safeword:{family.id}")

    async def set_safe_word(self, family: Family, word: str) -> bool:
        if not family.settings.safe_word_enabled or len(word.strip()) < 3:
            return False
        await self.update_settings(family, safe_word_hash=self._sw_hash(family, word), safe_word_set_at=self.ctx.clock.now())
        await self.ctx.audit(family, "safeword", "A family safe word was set (stored scrambled).")
        return True

    def check_safe_word(self, family: Family, word: str) -> bool:
        h = family.settings.safe_word_hash
        return bool(h) and h == self._sw_hash(family, word)

    # ------------------------------------------------------------------ app-notification outbox (the device API reads it)
    async def queue_app_notification(self, family: Family, parent: Member, line: str, *, purpose: str, incident_id: str | None = None) -> Record:
        slots = await self.ctx.slots(family)
        text = self.ctx.say(line, parent.language, **slots)
        rec = Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", status="queued", at=self.ctx.clock.now(), data={"member_id": parent.id, "line": line, "purpose": purpose, "text": text, "incident_id": incident_id})
        out, _ = await self.store.put(rec)
        await self.ctx.audit(family, "notify", f"Sent {family.parent_label} a notification in the app ({purpose}).", purpose=purpose, incident_id=incident_id)
        return out

    async def nudges_last_hour(self, family: Family, parent: Member) -> int:
        since = self.ctx.clock.now().replace(microsecond=0) - timedelta(hours=1)
        rows = await self.store.list(family.id, "pending", since=since)
        return sum(1 for r in rows if r.data.get("member_id") == parent.id and r.data.get("purpose") == "nudge")

    async def take_app_notifications(self, parent_member_id: str) -> list[dict[str, Any]]:
        """For the device API: queued notifications for this parent, marked delivered."""
        m = await self.store.get_member(parent_member_id)
        if m is None:
            return []
        out = []
        for r in await self.store.list(m.family_id, "pending", status="queued"):
            if r.data.get("member_id") == m.id and await self.store.cas(r.id, "queued", status="sent"):
                out.append({"id": r.id, "text": r.data.get("text", ""), "line": r.data.get("line"), "purpose": r.data.get("purpose")})
        return out

    # ------------------------------------------------------------------ delete everything
    async def erase(self, family: Family, *, actor: str = "admin_on_behalf", source: str = "admin_chat", tell_child: bool = False) -> dict[str, int]:
        """'Delete everything' for one family: the CHILD (admin) owns this. Removes the family rows AND, through the erase
        hooks, everything the device package holds for the parents (rows, pairing codes, live analyzers, token cache), so the
        phone's token stops working. Audited without personal data (counts only, kept in the core audit log because the family's
        own log is erased too). ``tell_child``: send ``cmd.delete_done`` once (the chat command replies itself, so it passes False)."""
        parents = [m.id for m in await self.store.members(family.id, Role.PARENT)]
        owner_id, label = family.owner_user_id, family.parent_label
        lang = await self.ctx.chat_lang(family)
        counts = await self.store.erase_family(family.id)
        counts.update(await run_erase_hooks(parents))
        log.info("robin: family erased (%s)", ",".join(f"{k}={v}" for k, v in counts.items()))
        sink = self.ctx.audit_sink
        if sink is not None:
            try:
                await sink("robin.family_erased", owner_id, actor=actor, source=source, counts=counts)
            except Exception as e:  # noqa: BLE001 - the erase already happened
                log.error("robin: erase audit failed (%s)", type(e).__name__)
        if tell_child:
            await self.ctx.send(owner_id, self.ctx.say("cmd.delete_done", lang, parent=label), [])
        return counts

    # ------------------------------------------------------------------ lookup by phone (inbound parent call, app)
    async def parent_by_phone(self, phone: str) -> tuple[Family, Member] | None:
        e164 = canonical(phone)
        if e164 is None:
            return None
        for m in await self.store.members_by_phone(e164):
            if m.role == Role.PARENT:
                fam = await self.store.get_family(m.family_id)
                if fam and fam.status != FamilyStatus.DELETED:
                    return fam, m
        return None

    async def family_of_owner(self, user_id: str) -> Family | None:
        fams = [f for f in await self.store.families_for_owner(user_id) if f.status != FamilyStatus.DELETED]
        return fams[-1] if fams else None

    @staticmethod
    def sensitivity(text: str) -> Sensitivity | None:
        t = text.strip().lower()
        for s in Sensitivity:
            if t == s.value or t.startswith(s.value):
                return s
        return None
