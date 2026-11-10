# ruff: noqa: E501
"""The daily check-in: scheduler, call plan, retries, structured result, one line to the child, digests,
and the escalation ladder when nobody answers.

Plan of the call (``plan_steps``): greeting (says it is an AI), ate, slept, pain, mood word, any strange
call or money request, medicines taken, on the weekly day also 'how many pills are left?'. Unanswered:
up to 2 retries spaced 20 minutes; after the last one the ladder starts (WhatsApp the child, call the child,
the second contact only if the child named them in advance) through ``alerts.AlertEngine``. A check-in only
happens with the parent's ``daily_checkin_calls`` consent, outside quiet hours, and never while the care
protocol is active (it is postponed and, after 3 hours, skipped).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.robin import answers as ans
from friday.robin.alerts import AlertEngine, RobinAlert
from friday.robin.context import Ctx
from friday.robin.family import FamilyService
from friday.robin.medicine import MedicineService
from friday.robin.models import (
    CallOutcome,
    CallResult,
    ConsentItem,
    Family,
    FamilyStatus,
    Member,
    Step,
    Tier,
)
from friday.robin.store import Record

log = get_logger(__name__)
GIVE_UP_AFTER = timedelta(hours=3)
DIGEST_HOUR = 20
WEEKLY_COUNT_WEEKDAY = 6  # Sunday


def base_steps(slots: dict[str, str]) -> list[Step]:
    """The fixed part of the daily check-in call (greeting, six short questions, goodbye). Also what `friday robin call-test` speaks."""
    return [
        Step(line="checkin.greet", slots=slots),
        Step(line="checkin.q.ate", slots=slots, expect="yesno"),
        Step(line="checkin.q.slept", slots=slots, expect="yesno"),
        Step(line="checkin.q.pain", slots=slots, expect="yesno", on_yes="checkin.pain_ack"),
        Step(line="checkin.q.mood", slots=slots, expect="mood"),
        Step(line="checkin.q.strange", slots=slots, expect="yesno", on_yes="checkin.strange_ack"),
        Step(line="checkin.bye", slots=slots),
    ]


def parse_answers(out: CallOutcome) -> dict[str, Any]:
    said = {a.line: a.text for a in out.answers}

    def yn(key: str) -> bool | None:
        return ans.yesno(said.get(key, ""))

    mood_word, mood_low = ans.mood(said.get("checkin.q.mood", ""))
    res: dict[str, Any] = {
        "ate": yn("checkin.q.ate"), "slept": yn("checkin.q.slept"), "pain": yn("checkin.q.pain"), "mood": mood_word, "mood_low": mood_low,
        "strange": yn("checkin.q.strange"), "meds": yn("checkin.q.meds"), "anything": any(t.strip() for t in said.values()),
    }  # fmt: skip
    concerns = []
    if res["pain"] is True:
        concerns.append("pain")
    if res["strange"] is True:
        concerns.append("strange_call")
    if res["ate"] is False:
        concerns.append("not_eaten")
    if res["slept"] is False:
        concerns.append("not_slept")
    if res["meds"] is False:
        concerns.append("meds_missed")
    if mood_low:
        concerns.append("low_mood")
    res["concerns"] = concerns
    return res


class CheckinService:
    def __init__(self, ctx: Ctx, family_svc: FamilyService, meds: MedicineService, alerts: AlertEngine, *, retries: int = 2, retry_minutes: int = 20) -> None:
        self.ctx, self.fam, self.meds, self.alerts, self.store = ctx, family_svc, meds, alerts, ctx.store
        self.retries, self.retry = min(retries, 2), timedelta(minutes=retry_minutes)

    # ------------------------------------------------------------------ the call plan
    async def plan_steps(self, family: Family, parent: Member, *, weekly: bool) -> tuple[list[Step], list[Step]]:
        slots = await self.ctx.slots(family)
        steps = base_steps(slots)[:-1]
        if await self.ctx.has_consent(parent, ConsentItem.MEDICINE_REMINDERS) and await self.meds.meds(family):
            steps.append(Step(line="checkin.q.meds", slots=slots, expect="yesno"))
        count_steps: list[Step] = []
        if weekly:
            med_list = sorted((m for _, m in await self.meds.meds(family)), key=lambda m: m.name)
            count_steps = self.meds.weekly_count_steps(med_list, slots)
            steps += count_steps
        steps.append(Step(line="checkin.bye", slots=slots))
        return steps, count_steps

    # ------------------------------------------------------------------ the scheduler
    async def tick(self) -> int:
        n = 0
        for fam in await self.store.all_families(("active",)):
            parent = await self.ctx.parent(fam)
            if parent is None or parent.paused or not await self.ctx.has_consent(parent, ConsentItem.DAILY_CHECKIN_CALLS):
                continue
            n += await self._plan_today(fam, parent)
            n += await self._digests(fam, parent)
        n += await self._process_due()
        n += await self.alerts.tick()
        return n

    async def _plan_today(self, fam: Family, parent: Member) -> int:
        c = self.ctx
        now = c.clock.now()
        loc = c.local(parent, now)
        h, m = (int(x) for x in fam.settings.checkin_time.split(":"))
        at_local = loc.replace(hour=h, minute=m, second=0, microsecond=0)
        if at_local > loc:
            return 0
        _, created = await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="checkin", key=loc.date().isoformat(), status="due", at=at_local.astimezone(now.tzinfo), due_at=at_local.astimezone(now.tzinfo), data={"attempts": 0, "date": loc.date().isoformat(), "parent_id": parent.id, "weekly": loc.weekday() == WEEKLY_COUNT_WEEKDAY}))
        return int(created)

    async def _process_due(self) -> int:
        n = 0
        for rec in await self.store.due("checkin", ("due", "retry"), self.ctx.clock.now()):
            await self.run(rec.id)
            n += 1
        return n

    async def run(self, rec_id: str) -> str:
        c = self.ctx
        rec = await self.store.get(rec_id)
        if rec is None or rec.status not in ("due", "retry") or not await self.store.cas(rec.id, rec.status, status="calling"):
            return "skipped"
        d = dict(rec.data)
        fam, parent = await self.store.get_family(rec.family_id), await self.store.get_member(d["parent_id"])
        if fam is None or parent is None or fam.status != FamilyStatus.ACTIVE:
            await self.store.cas(rec.id, "calling", status="skipped", due_at=None)
            return "skipped"
        now = c.clock.now()
        steps, count_steps = await self.plan_steps(fam, parent, weekly=bool(d.get("weekly")))
        d["attempts"] = int(d["attempts"]) + 1
        out = await c.call(fam, parent, "checkin", steps, dedupe_key=f"checkin:{rec.id}:{d['attempts']}", max_seconds=240)
        return await self._after(fam, parent, rec, d, out, count_steps, now)

    async def _after(self, fam: Family, parent: Member, rec: Record, d: dict[str, Any], out: CallOutcome, count_steps: list[Step], now: datetime) -> str:
        c = self.ctx
        if out.result == CallResult.REFUSED:
            d["attempts"] -= 1  # a refusal is not a try
            if out.detail in ("no_consent", "parent_paused", "family_not_active", "family_deleted") or now - rec.at > GIVE_UP_AFTER:
                await self.store.cas(rec.id, "calling", status="skipped", due_at=None, data={**d, "skipped": out.detail})
                return f"skipped:{out.detail}"
            await self.store.cas(rec.id, "calling", status="due", due_at=now + timedelta(minutes=30), data=d)  # quiet hours, care protocol, line pending, window: later
            return f"deferred:{out.detail}"
        if out.result == CallResult.ANSWERED:
            if out.detail == "stop_requested":
                await self.store.cas(rec.id, "calling", status="stopped", due_at=None, data=d)
                await self.fam.pause(parent.id, "voice")
                return "stopped"
            if out.detail == "help_requested":  # 'madad' on the check-in call: the same EMERGENCY as the SOS button (same dedupe key, so never twice)
                await self.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.EMERGENCY, scenario="sos", why=f"{fam.parent_label} asked for help on the check-in call", dedupe_key=f"sos:{parent.id}:{int(now.timestamp() // 300)}", signals=("parent_said_help",)))
            res = parse_answers(out)
            d["result"] = res
            await self.store.cas(rec.id, "calling", status="done", due_at=None, data=d)
            if count_steps:
                await self.meds.apply_counts(fam, count_steps, out.answers)
            await self._tell_result(fam, res)
            await self.note_reached(fam, parent)
            return "done"
        if d["attempts"] <= self.retries:
            await self.store.cas(rec.id, "calling", status="retry", due_at=now + self.retry, data=d)
            return "retry"
        await self.store.cas(rec.id, "calling", status="unanswered", due_at=None, data=d)
        lang = await c.chat_lang(fam)
        res_alert = await self.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.HIGH, scenario="checkin_unanswered", why=c.say("checkin.result.missed", lang, parent=fam.parent_label, n=d["attempts"]), dedupe_key=f"checkin:{d['date']}"))
        return "unanswered" if res_alert.accepted else f"unanswered:{res_alert.reason}"

    # ------------------------------------------------------------------ result to the child (one line)
    async def summary_line(self, fam: Family, res: dict[str, Any], *, full: bool) -> str:
        c = self.ctx
        lang = await c.chat_lang(fam)
        if not full or not res.get("anything"):
            return c.say("sum.answered_only", lang)

        def yn(v: bool | None) -> str:
            return c.say("sum.yes" if v is True else "sum.no" if v is False else "sum.unclear", lang)

        parts = [c.say("sum.ate", lang, v=yn(res["ate"])), c.say("sum.slept", lang, v=yn(res["slept"])), c.say("sum.pain", lang, v=yn(res["pain"]))]
        if res.get("mood"):
            parts.append(c.say("sum.mood", lang, v=res["mood"]))
        parts.append(c.say("sum.strange", lang, v=yn(res["strange"])))
        if res.get("meds") is not None:
            parts.append(c.say("sum.meds", lang, v=yn(res["meds"])))
        return ", ".join(parts)

    async def _tell_result(self, fam: Family, res: dict[str, Any]) -> None:
        c = self.ctx
        lang = await c.chat_lang(fam)
        parent = await c.parent(fam)
        full = bool(parent and await c.has_consent(parent, ConsentItem.SHARE_SUMMARY_WITH_CHILD))
        summary = await self.summary_line(fam, res, full=full)
        key = "checkin.result.concern" if res["concerns"] and full else "checkin.result.ok"
        await c.tell_child(fam, c.say(key, lang, parent=fam.parent_label, summary=summary))
        await c.audit(fam, "checkin", f"Daily check-in with {fam.parent_label}: done." + (" Something to note." if res["concerns"] else ""), concerns=res["concerns"] if full else [])

    async def note_reached(self, fam: Family, parent: Member) -> None:
        """The parent answered a call (or phoned in): an open 'unanswered' ladder ends with 'Papa is fine'."""
        c = self.ctx
        for rec in await self.store.list(fam.id, "incident", status=("open", "running", "exhausted")):
            if rec.data.get("scenario") == "checkin_unanswered" and await self.store.cas(rec.id, ("open", "running", "exhausted"), status="closed", due_at=None, data={**rec.data, "closed_by": "parent_reached"}):
                await c.tell_child(fam, c.say("checkin.result.fine_later", await c.chat_lang(fam), parent=fam.parent_label))
                await c.audit(fam, "alert_closed", f"{fam.parent_label} was reached; the unanswered check-in alert is closed.", incident_id=rec.id)

    # ------------------------------------------------------------------ on demand ('call papa')
    async def call_now(self, fam: Family) -> str:
        c = self.ctx
        parent = await c.parent(fam)
        if parent is None:
            return "refused:no_parent"
        now = c.clock.now()
        steps, count_steps = await self.plan_steps(fam, parent, weekly=False)
        out = await c.call(fam, parent, "callnow", steps, dedupe_key=f"callnow:{fam.id}:{int(now.timestamp())}", max_seconds=240)
        lang = await c.chat_lang(fam)
        if out.result == CallResult.REFUSED:
            await c.tell_child(fam, c.say("callnow.refused", lang, parent=fam.parent_label, why=out.detail))
            return f"refused:{out.detail}"
        if out.result == CallResult.ANSWERED:
            if out.detail == "stop_requested":
                await self.fam.pause(parent.id, "voice")
                return "stopped"
            await self._tell_result(fam, parse_answers(out))
            await self.note_reached(fam, parent)
            return "done"
        await c.tell_child(fam, c.say("checkin.result.missed", lang, parent=fam.parent_label, n=1))
        return out.result.value

    # ------------------------------------------------------------------ digests (daily + weekly)
    async def build_digest(self, fam: Family, parent: Member, *, days: int) -> str:
        c = self.ctx
        lang = await c.chat_lang(fam)
        now = c.clock.now()
        start = c.local_day_bounds(parent, now)[1] - timedelta(days=days)
        cks = await self.store.list(fam.id, "checkin", since=start)
        done = [r for r in cks if r.status == "done"]
        concerns = [r for r in done if r.data.get("result", {}).get("concerns")]
        doses = await self.store.list(fam.id, "dose", since=start)
        taken, missed = sum(r.status == "taken" for r in doses), sum(r.status == "missed" for r in doses)
        alerts = [r for r in await self.store.list(fam.id, "incident", since=start) if r.data.get("tier") != "info"]
        full = await c.has_consent(parent, ConsentItem.SHARE_SUMMARY_WITH_CHILD)
        parts = [c.say("dg.checkins", lang, n=len(done), total=len(cks))] if cks else []
        if concerns and full:
            parts.append(c.say("dg.concerns", lang, n=len(concerns)))
        if doses:
            parts.append(c.say("dg.meds", lang, taken=taken, missed=missed))
        if alerts:
            parts.append(c.say("dg.alerts", lang, n=len(alerts)))
        return "; ".join(parts) or c.say("digest.empty", lang)

    async def digest_now(self, fam: Family, *, weekly: bool) -> str | None:
        parent = await self.ctx.parent(fam)
        if parent is None:
            return None
        lang = await self.ctx.chat_lang(fam)
        body = await self.build_digest(fam, parent, days=7 if weekly else 1)
        return self.ctx.say("digest.weekly" if weekly else "digest.daily", lang, parent=fam.parent_label, summary=body)

    async def _digests(self, fam: Family, parent: Member) -> int:
        c = self.ctx
        loc = c.local(parent)
        if loc.hour < DIGEST_HOUR or await c.care_active(fam.owner_user_id):
            return 0
        n = 0
        for weekly in (False, True):
            if weekly and loc.weekday() != WEEKLY_COUNT_WEEKDAY:
                continue
            key = f"{'weekly' if weekly else 'daily'}:{loc.date().isoformat()}"
            if await self.store.by_key(fam.id, "digest", key) is not None:
                continue
            text = await self.digest_now(fam, weekly=weekly)
            _, created = await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="digest", key=key, status="sent", at=c.clock.now(), data={}))
            if created and text:
                await c.tell_child(fam, text)
                n += 1
        return n

    @staticmethod
    def _unused(_: date | None = None) -> None:  # pragma: no cover
        return None
