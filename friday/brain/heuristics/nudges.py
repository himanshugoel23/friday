"""Proactive nudge judgement + copy per ``NudgeKind`` (deterministic path).
Guardrails (cap, quiet hours, consent, autonomy) are the backend's; this only
decides usefulness/timing and writes copy that always offers an action."""

from __future__ import annotations

from datetime import timedelta

from friday.core.clock import ensure_utc, format_ist
from friday.core.models import ConversationContext, NudgeCandidate, NudgeKind, Urgency

from ..copy import first_name, say
from ..schemas import NudgeButtonOut, NudgeOut


def _b(action: str, title: str) -> NudgeButtonOut:
    return NudgeButtonOut(action=action, title=title)


def judge(ctx: ConversationContext, cand: NudgeCandidate) -> NudgeOut:
    lang, tone = ctx.profile.language, ctx.profile.tone
    d = cand.data or {}
    now = ensure_utc(ctx.now)
    due = ensure_utc(cand.due_at)
    person = next((p for p in ctx.people if p.id == cand.person_id), None)
    who = first_name(person.name) if person else None
    biz = d.get("business_name") or d.get("business") or ""
    what = d.get("what") or d.get("title") or d.get("service") or cand.reason

    def s(en: str, hinglish: str | None = None) -> str:
        return say(lang, tone, en=en, hinglish=hinglish)

    if d.get("already_done") or d.get("resolved"):
        return NudgeOut(send=False, reason="already resolved")
    task = next((t for t in ctx.open_tasks if t.id == cand.task_id), None) if cand.task_id else None

    k = cand.kind
    if k == NudgeKind.WELLBEING_ALERT:
        detail = d.get("alert") or cand.reason
        return NudgeOut(send=True, reason="safety alert", text=s(
            f"⚠ {who or 'Your family member'} may need attention: {detail}. If it's an "
            f"emergency, call 112/108.",
            f"⚠ {who or 'Aapke family member'} ko dhyan chahiye: {detail}. Emergency ho toh "
            f"112/108."), buttons=[_b("call_now", "Call them now"),
                                   _b("call_doctor", "Call their doctor"),
                                   _b("recording", "Listen")])
    if k == NudgeKind.TASK_REMINDER:
        if due < now - timedelta(minutes=15):
            return NudgeOut(send=False, reason="appointment already passed")
        when = format_ist(due, "%I:%M %p").lstrip("0")
        return NudgeOut(send=True, reason="upcoming appointment", text=s(
            f"Reminder: {what}{' at ' + biz if biz and biz not in what else ''} at {when}.",
            f"Yaad dila doon: {what}{' - ' + biz if biz and biz not in what else ''}, {when} "
            f"baje."), buttons=[_b("ok", "OK"), _b("late", "Running late"),
                                _b("reschedule", "Reschedule")])
    if k == NudgeKind.FOLLOW_UP:
        if task is not None and task.status.is_terminal and d.get("confirmed"):
            return NudgeOut(send=False, reason="already confirmed")
        return NudgeOut(send=True, reason="follow-up", text=s(
            f"Did {biz or 'they'} come and get it done?",
            f"{biz or 'Woh'} aaye the? Kaam ho gaya?"),
            buttons=[_b("done", "Yes, all done"), _b("not_fixed", "Not fixed"),
                     _b("no_show", "Didn't come")])
    if k == NudgeKind.DATE_BASED:
        value = d.get("value") or cand.reason
        when = format_ist(due, "%d %b")
        about = f"{who}'s " if who else ""
        return NudgeOut(send=True, reason="date fact coming up", text=s(
            f"Heads up: {about}{value} - {when}. Want me to handle it?",
            f"Heads up: {about}{value} - {when}. Main handle karun?"),
            buttons=[_b("yes", "Yes, call"), _b("later", "Remind later"),
                     _b("dismiss", "Not needed")])
    if k == NudgeKind.PATTERN:
        if d.get("ignored_streak", 0) >= 3:
            return NudgeOut(send=False, reason="user keeps ignoring this pattern")
        weeks = d.get("weeks") or d.get("interval_weeks")
        since = f"{weeks} weeks since your last {what}" if weeks else f"Time for {what}?"
        usual = f" {biz}, {d.get('usual_slot')} like usual?" if biz and d.get("usual_slot") else \
            (f" Book {biz} like usual?" if biz else " Want me to book it?")
        return NudgeOut(send=True, reason="routine due", text=s(f"{since} ✂️{usual}",
                                                                 f"{since} ✂️{usual}"),
                        buttons=[_b("book", "Book it"), _b("later", "Not now"),
                                 _b("stop", "Stop these")])
    if k == NudgeKind.RECURRING_DUE:
        return NudgeOut(send=True, reason="recurring instance due", text=s(
            f"Next {what}{' for ' + who if who else ''} is coming up ({format_ist(due, '%a %d %b')})."
            f" Book the usual slot?",
            f"Agla {what}{' ' + who + ' ke liye' if who else ''} aa raha hai "
            f"({format_ist(due, '%a %d %b')}). Usual slot book karun?"),
            buttons=[_b("book", "Book it"), _b("skip", "Skip this one"),
                     _b("pause", "Pause series")])
    if k == NudgeKind.MORNING_BRIEFING:
        items = d.get("items") or []
        lines = "\n".join(f"• {i}" for i in items[:5]) or s("Nothing urgent today.",
                                                           "Aaj kuch urgent nahi.")
        name = first_name(ctx.profile.name)
        return NudgeOut(send=True, reason="opt-in briefing", text=s(
            f"Good morning{', ' + name if name else ''} ☀️\n{lines}",
            f"Good morning{', ' + name if name else ''} ☀️\n{lines}"),
            buttons=[_b("ok", "Thanks"), _b("details", "Details"), _b("stop", "Stop briefing")])
    if k == NudgeKind.TASK_RESULT:
        text = d.get("summary") or cand.reason
        return NudgeOut(send=True, reason="task result", text=text,
                        buttons=[_b("ok", "OK"), _b("details", "Details")])
    return NudgeOut(send=cand.urgency != Urgency.NORMAL, reason="unknown kind",
                    text=cand.reason, buttons=[_b("ok", "OK")])
