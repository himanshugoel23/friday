# ruff: noqa: E501
"""Medicine: schedule, reminders, taken/missed capture, stock estimate, the weekly count, the refill alert.

NO MEDICAL ADVICE, by construction: Robin stores what the child typed (or what the prescription photo
said, after the child confirmed it), reminds at those times, counts pills, and says 'ask the doctor' for
anything else. It never interprets a dose, never suggests a change, never says what a medicine is for.

Stock estimate: pills = strips x pills per strip on the purchase date (or the parent's last count);
remaining = pills - doses per day x days since; days left = remaining / doses per day. It is an ESTIMATE
(it assumes every dose is taken), corrected every week by the parent's own count.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.robin import answers as ans
from friday.robin.context import Ctx
from friday.robin.models import (
    CallResult,
    ConsentItem,
    Family,
    FamilyStatus,
    Medicine,
    Member,
    Step,
)
from friday.robin.store import Record

log = get_logger(__name__)

GIVE_UP_AFTER = timedelta(hours=2)
RETRY_AFTER = timedelta(minutes=20)
_TIME = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?", re.I)
_DOSE = re.compile(r"\b(\d+(?:\.\d+)?\s?(?:mg|mcg|ug|g|ml|iu|units?))\b", re.I)
_FREQ_DOTS = re.compile(r"\b([0-3½])\s*[-–]\s*([0-3½])\s*[-–]\s*([0-3½])\b")
_SLOTS = {"OD": ["08:00"], "BD": ["08:00", "20:00"], "BID": ["08:00", "20:00"], "TDS": ["08:00", "14:00", "20:00"], "TID": ["08:00", "14:00", "20:00"], "HS": ["21:00"]}


def parse_clock(text: str) -> str | None:
    """'8am' / '8:30 pm' / '20:00' / '9 baje' -> 'HH:MM'. None when not a time."""
    m = _TIME.fullmatch(text.strip())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if mi > 59:
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if h > 23:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_date(text: str, today: date) -> date | None:
    t = text.strip().lower()
    if t in ("today", "aaj"):
        return today
    if t in ("yesterday", "kal"):
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def parse_add(text: str, today: date) -> Medicine | str:
    """'add medicine Amlodipine 5mg at 8am, 8pm strips 2 of 10 bought 2026-11-01'. Returns a Medicine or an error code."""
    body = re.sub(r"^\s*add\s+(?:a\s+)?(?:medicine|medicines|dawai|dawa|tablet)\s+", "", text, flags=re.I).strip()
    if not body or body == text.strip():
        return "format"
    bought = None
    m = re.search(r"\bbought\s+(\S+)", body, re.I)
    if m:
        bought = parse_date(m.group(1), today)
        body = (body[: m.start()] + body[m.end():]).strip()
        if bought is None:
            return "bad_date"
    strips, per = 0.0, 10
    m = re.search(r"\bstrips?\s+(\d+(?:\.\d+)?)(?:\s+of\s+(\d+))?", body, re.I)
    if m:
        strips = float(m.group(1))
        per = int(m.group(2)) if m.group(2) else 10
        body = (body[: m.start()] + body[m.end():]).strip()
    times: list[str] = []
    m = re.search(r"\bat\s+(.+)$", body, re.I)
    if m:
        for part in re.split(r"\s*(?:,|\band\b|&)\s*", m.group(1).strip()):
            t = parse_clock(part)
            if t is None:
                return "bad_time"
            times.append(t)
        body = body[: m.start()].strip()
    if not times:
        return "no_time"
    dose = ""
    d = _DOSE.search(body)
    if d:
        dose = d.group(1)
        body = (body[: d.start()] + body[d.end():]).strip()
    name = " ".join(body.split())[:40]
    if not name:
        return "format"
    return Medicine(name=name, dose_text=dose, times=sorted(set(times)), strips=strips, pills_per_strip=per, last_purchase_date=bought or (today if strips else None))


def parse_prescription_line(line: str, today: date) -> Medicine | None:
    """One line read from a prescription photo ('Amlodipine 5 mg 1-0-1' / 'Metformin 500mg BD'). The CHILD confirms before saving."""
    text = " ".join(line.split())
    if not text:
        return None
    times: list[str] = []
    f = _FREQ_DOTS.search(text)
    if f:
        for slot, v in zip(("08:00", "14:00", "21:00"), f.groups(), strict=True):
            if v != "0":
                times.append(slot)
        text = (text[: f.start()] + text[f.end():]).strip()
    else:
        for code, slots in _SLOTS.items():
            m = re.search(rf"\b{code}\b", text, re.I)
            if m:
                times = list(slots)
                text = (text[: m.start()] + text[m.end():]).strip()
                break
    dose = ""
    d = _DOSE.search(text)
    if d:
        dose = d.group(1)
        text = (text[: d.start()] + text[d.end():]).strip()
    name = re.sub(r"^(?:tab\.?|tablet|cap\.?|capsule|syp\.?)\s+", "", text, flags=re.I).strip(" .,-")[:40]
    if not name or not times:
        return None
    return Medicine(name=name, dose_text=dose, times=times, last_purchase_date=today)


def remaining_pills(med: Medicine, today: date) -> float:
    if med.stock_counted_at is not None:
        base, start = float(med.stock_adjust), med.stock_counted_at.date()
    else:
        base, start = med.strips * med.pills_per_strip, med.last_purchase_date or today
    return base - med.doses_per_day * max((today - start).days, 0)


def days_left(med: Medicine, today: date) -> int:
    return max(int(remaining_pills(med, today) // med.doses_per_day), 0)


class MedicineService:
    def __init__(self, ctx: Ctx, family_svc: Any) -> None:
        self.ctx, self.fam, self.store = ctx, family_svc, ctx.store

    # ------------------------------------------------------------------ the list
    async def meds(self, family: Family, status: str = "active") -> list[tuple[Record, Medicine]]:
        out = []
        for r in await self.store.list(family.id, "medicine", status=status):
            out.append((r, Medicine(**r.data)))
        return out

    async def add(self, family: Family, med: Medicine, *, status: str = "active") -> Record:
        # the unique key is a KEYED HASH of the name: a medicine name is health data and must not sit in a plaintext column
        key = ("p:" if status == "proposed" else "") + self.store.hasher.cipher.blind_index(re.sub(r"\W+", "", med.name.lower()), label="robin_medicine")[:60]
        old = await self.store.by_key(family.id, "medicine", key)
        if old is not None:
            await self.store.delete_record(old.id)  # same name again = replace
        rec, _ = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="medicine", key=key, status=status, at=self.ctx.clock.now(), data=med.model_dump(mode="json")))
        if status == "active":
            await self.ctx.audit(family, "medicine", f"Saved the medicine {med.name} at {', '.join(med.times)}.")
        return rec

    async def find(self, family: Family, name: str) -> tuple[Record, Medicine] | None:
        n = re.sub(r"\W+", "", name.lower())
        for r, m in await self.meds(family):
            if re.sub(r"\W+", "", m.name.lower()).startswith(n) and n:
                return r, m
        return None

    async def remove(self, family: Family, name: str) -> str | None:
        hit = await self.find(family, name)
        if hit is None:
            return None
        await self.store.delete_record(hit[0].id)
        await self.ctx.audit(family, "medicine", f"Removed the medicine {hit[1].name}.")
        return hit[1].name

    async def set_count(self, family: Family, name: str, pills: int) -> bool:
        hit = await self.find(family, name)
        if hit is None or pills < 0:
            return False
        rec, med = hit
        med.stock_adjust, med.stock_counted_at = float(pills), self.ctx.clock.now()
        await self.store.set_data(rec.id, med.model_dump(mode="json"))
        await self.ctx.audit(family, "medicine", f"Updated the pill count of {med.name}.")
        return True

    # ------------------------------------------------------------------ prescription photo -> child confirms
    async def propose(self, family: Family, meds: list[Medicine]) -> int:
        for r, _ in await self.meds(family, "proposed"):
            await self.store.delete_record(r.id)
        for m in meds:
            await self.add(family, m, status="proposed")
        return len(meds)

    async def has_proposal(self, family: Family) -> bool:
        return bool(await self.store.list(family.id, "medicine", status="proposed"))

    async def confirm(self, family: Family, yes: bool) -> int:
        n = 0
        for r, m in await self.meds(family, "proposed"):
            await self.store.delete_record(r.id)
            if yes:
                await self.add(family, m)
                n += 1
        return n

    async def from_document_lines(self, family: Family, text_lines: list[str]) -> list[Medicine]:
        today = self.ctx.local(await self._parent_or_child(family)).date()
        meds = [m for line in text_lines if (m := parse_prescription_line(line, today))]
        if meds:
            await self.propose(family, meds)
        return meds

    async def _parent_or_child(self, family: Family) -> Member:
        return (await self.ctx.parent(family)) or (await self.ctx.child(family))  # type: ignore[return-value]

    # ------------------------------------------------------------------ scheduler
    async def tick(self) -> int:
        n = 0
        for fam in await self.store.all_families(("active",)):
            parent = await self.ctx.parent(fam)
            if parent is None or parent.paused:
                continue
            n += await self._schedule(fam, parent)
            n += await self._refill_alerts(fam, parent)
        n += await self._process_due()
        return n

    def _reminders_paused(self, fam: Family) -> bool:
        until = fam.settings.reminders_paused_until
        return bool(until and until > self.ctx.clock.now())

    async def _schedule(self, fam: Family, parent: Member) -> int:
        c = self.ctx
        if self._reminders_paused(fam) or not await c.has_consent(parent, ConsentItem.MEDICINE_REMINDERS):
            return 0
        now = c.clock.now()
        loc = c.local(parent, now)
        n = 0
        for _, med in await self.meds(fam):
            for t in med.times:
                h, mi = (int(x) for x in t.split(":"))
                due_local = loc.replace(hour=h, minute=mi, second=0, microsecond=0)
                if due_local > loc:
                    continue
                key = f"{med.id}:{loc.date().isoformat()}:{t}"
                due = due_local.astimezone(now.tzinfo)
                rec, created = await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="dose", key=key, status="due", at=due, due_at=due, data={"med_id": med.id, "name": med.name, "slot": t, "date": loc.date().isoformat(), "attempts": 0, "parent_id": parent.id}))
                n += int(created)
        return n

    async def _process_due(self) -> int:
        c = self.ctx
        now = c.clock.now()
        groups: dict[tuple[str, str, str], list[Record]] = {}
        for rec in await self.store.due("dose", ("due", "retry"), now):
            groups.setdefault((rec.family_id, rec.data["parent_id"], f"{rec.data['date']} {rec.data['slot']}"), []).append(rec)
        done = 0
        for (fam_id, parent_id, _slot), recs in groups.items():
            fam, parent = await self.store.get_family(fam_id), await self.store.get_member(parent_id)
            if fam is None or parent is None or fam.status != FamilyStatus.ACTIVE:
                continue
            if now - recs[0].at > GIVE_UP_AFTER:
                for r in recs:
                    await self.store.cas(r.id, ("due", "retry"), status="unreached", due_at=None)
                continue
            if self._reminders_paused(fam):
                continue
            claimed = [r for r in recs if await self.store.cas(r.id, r.status, status="calling")]
            if not claimed:
                continue
            slots = await c.slots(fam)
            steps = [Step(line="med.remind", slots={**slots, "medicine": r.data["name"]}, expect="yesno", on_yes="med.thanks", on_no="med.later") for r in claimed]
            out = await c.call(fam, parent, "medicine", steps, dedupe_key=f"dose:{claimed[0].key}:{claimed[0].data['attempts'] + 1}")
            done += 1
            await self._apply(fam, parent, claimed, out)
        return done

    async def _apply(self, fam: Family, parent: Member, recs: list[Record], out: Any) -> None:
        c = self.ctx
        now = c.clock.now()
        if out.result == CallResult.ANSWERED:
            if out.detail == "stop_requested":
                for r in recs:
                    await self.store.cas(r.id, "calling", status="unreached", due_at=None)
                await self.fam.pause(parent.id, "voice")
                return
            lang = await c.chat_lang(fam)
            for r, a in zip(recs, out.answers + [None] * len(recs), strict=False):
                said = ans.yesno(a.text) if a else None
                if said is False:
                    await self.store.cas(r.id, "calling", status="missed", due_at=None, data={**r.data, "attempts": r.data["attempts"] + 1})
                    await c.tell_child(fam, c.say("med.missed", lang, parent=fam.parent_label, medicine=r.data["name"], time=r.data["slot"]))
                    await c.audit(fam, "dose", f"{fam.parent_label} did not take {r.data['name']} ({r.data['slot']}).")
                elif said is True:
                    await self.store.cas(r.id, "calling", status="taken", due_at=None, data={**r.data, "attempts": r.data["attempts"] + 1, "source": "voice"})
                else:
                    await self.store.cas(r.id, "calling", status="unreached", due_at=None, data={**r.data, "attempts": r.data["attempts"] + 1})
            return
        for r in recs:
            attempts = r.data["attempts"] + 1
            if out.result == CallResult.REFUSED and out.detail in ("quiet_hours", "care_active", "kill_switch"):
                await self.store.cas(r.id, "calling", status="retry", due_at=now + RETRY_AFTER, data={**r.data})  # not an attempt
            elif out.result == CallResult.REFUSED:
                await self.store.cas(r.id, "calling", status="unreached", due_at=None, data={**r.data, "refused": out.detail})
            elif attempts < 2:
                await self.store.cas(r.id, "calling", status="retry", due_at=now + RETRY_AFTER, data={**r.data, "attempts": attempts})
            else:
                await self.store.cas(r.id, "calling", status="unreached", due_at=None, data={**r.data, "attempts": attempts})

    async def record_dose(self, family: Family, dose_id: str, taken: bool, source: str = "app_tap") -> bool:
        """The Android app (or the parent in a check-in) reports a dose: taken / not taken."""
        rec = await self.store.get(dose_id)
        if rec is None or rec.family_id != family.id or rec.kind != "dose":
            return False
        ok = await self.store.cas(rec.id, ("due", "retry", "calling", "unreached", "missed", "taken"), status="taken" if taken else "missed", due_at=None, data={**rec.data, "source": source})
        return ok

    # ------------------------------------------------------------------ refill alert to the child
    async def _refill_alerts(self, fam: Family, parent: Member) -> int:
        c = self.ctx
        loc = c.local(parent)
        n = 0
        lang = await c.chat_lang(fam)
        for _, med in await self.meds(fam):
            left = days_left(med, loc.date())
            for level in sorted({fam.settings.refill_days, 2}):
                if left > level:
                    continue
                key = f"refill:{med.id}:{med.last_purchase_date}:{med.stock_counted_at.date() if med.stock_counted_at else ''}:{level}"[:64]
                _, created = await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="digest", key=key, status="sent", at=c.clock.now(), data={"med": med.name, "days": left}))
                if created:
                    await c.tell_child(fam, c.say("med.refill", lang, medicine=med.name, days=left))
                    await c.audit(fam, "refill", f"Told you that {med.name} has about {left} days left.")
                    n += 1
                break
        return n

    # ------------------------------------------------------------------ weekly count: extra steps of a check-in call
    def weekly_count_steps(self, meds: list[Medicine], slots: dict[str, str], *, limit: int = 2) -> list[Step]:
        return [Step(line="med.count_ask", slots={**slots, "medicine": m.name}, expect="count", on_yes=None) for m in meds[:limit]]

    async def apply_counts(self, family: Family, steps: list[Step], answers: list[Any]) -> int:
        n = 0
        by_line: dict[str, list[str]] = {}
        for a in answers:
            by_line.setdefault(a.line, []).append(a.text)
        texts = by_line.get("med.count_ask", [])
        counts = [s for s in steps if s.line == "med.count_ask"]
        for s, t in zip(counts, texts, strict=False):
            k = ans.count(t)
            if k is not None and await self.set_count(family, s.slots["medicine"], k):
                n += 1
        return n

    async def summary_for_list(self, family: Family) -> list[str]:
        parent = await self._parent_or_child(family)
        today = self.ctx.local(parent).date()
        lang = await self.ctx.chat_lang(family)
        out = []
        for _, m in await self.meds(family):
            out.append(self.ctx.say("med.list_item", lang, medicine=m.name, dose=m.dose_text, times=", ".join(m.times), days=days_left(m, today)))
        return out
