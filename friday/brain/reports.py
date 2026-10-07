"""User-facing reports: ``summarize_call`` -> TaskResult, ``compare_quotes``,
``shortlist``. Structured fields are computed deterministically in code; only the
prose (summary / next steps / alert) may come from the LLM. ``summary_text`` is the
deterministic prose (fake LLM + fallback).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from friday.core.clock import ensure_utc, format_ist
from friday.core.config import Settings
from friday.core.models import (
    BusinessCandidate,
    CallDirection,
    CallOutcome,
    CallResult,
    ConversationContext,
    Fact,
    FactKind,
    InteractionKind,
    MidCallQuestion,
    QuestionPurpose,
    Quote,
    QuoteComparison,
    ReplyButton,
    ShortlistItem,
    Speaker,
    Task,
    TaskResult,
    TaskSpec,
    TaskType,
    TemplateRef,
    VendorInteraction,
)

from .copy import first_name, say
from .heuristics.callstate import DISTRESS
from .schemas import KV, CompareOut, SummaryOut
from .templates import template_for
from .textutil import format_inr, has_any, norm, slot_to_datetime, truncate_title

BOOKING_TYPES = {TaskType.BOOKING, TaskType.HEALTHCARE, TaskType.RESCHEDULE, TaskType.ORDER,
                 TaskType.RECURRING_BOOKING, TaskType.HOTEL_BOOKING}
RETRY_BACKOFF_MIN = (10, 45)  # BRIEF E-36: +10 min, +45 min, then next good window
BUSY_BACKOFF_MIN = 5


def _biz_name(task: Task, result: CallResult) -> str:
    if task.target:
        return task.target.name
    return task.spec.business_name or task.spec.company or "the business"


def _who(ctx: ConversationContext, task: Task) -> str:
    p = next((p for p in ctx.people if p.id == task.beneficiary.person_id), None)
    return p.name if p else (first_name(ctx.profile.name) or "you")


def _best_quote(result: CallResult) -> Quote | None:
    return result.quotes[-1] if result.quotes else None


def _alert(result: CallResult) -> str | None:
    if result.collected.get("alert"):
        return result.collected["alert"]
    callee = " ".join(t.text for t in result.transcript.turns if t.speaker == Speaker.CALLEE)
    if has_any(norm(callee), DISTRESS):
        sent = next((t.text for t in result.transcript.turns
                     if t.speaker == Speaker.CALLEE and has_any(norm(t.text), DISTRESS)), callee)
        return sent[:200]
    return None


def next_attempt_time(task: Task, result: CallResult, now: datetime) -> datetime:
    if task.next_attempt_at:
        return task.next_attempt_at
    if result.outcome == CallOutcome.BUSY:
        return ensure_utc(now) + timedelta(minutes=BUSY_BACKOFF_MIN)
    idx = min(max(task.attempts, 1) - 1, len(RETRY_BACKOFF_MIN) - 1)
    return ensure_utc(now) + timedelta(minutes=RETRY_BACKOFF_MIN[idx])


def is_final_attempt(task: Task) -> bool:
    return max(task.attempts, 1) >= task.max_attempts


def summary_text(ctx: ConversationContext, task: Task, result: CallResult) -> SummaryOut:
    lang, tone = ctx.profile.language, ctx.profile.tone
    biz = _biz_name(task, result)
    q = _best_quote(result)
    col = result.collected
    details: list[KV] = []
    if q and q.amount_inr is not None:
        price = (f"{format_inr(q.original_amount_inr)} → {format_inr(q.amount_inr)}"
                 if q.negotiated else format_inr(q.amount_inr))
        details.append(KV(key="price", value=price))
    if q and q.available_slots:
        details.append(KV(key="slots", value=", ".join(q.available_slots[:3])))
    for k in ("confirmed_terms", "eta", "remedy", "promised", "callback_at", "reason"):
        if col.get(k):
            details.append(KV(key=k, value=col[k]))
    if result.care and result.care.ticket_number:
        details.append(KV(key="ticket", value=result.care.ticket_number))

    def s(en: str, hinglish: str | None = None) -> str:
        return say(lang, tone, en=en, hinglish=hinglish)

    out = result.outcome
    # ---------------------------------------------------------------- inbound / call-backs
    if result.direction == CallDirection.INBOUND or "message_taken" in col or \
            "matched_task_id" in col:
        inbound = _inbound_summary(ctx, task, result, s)
        if inbound is not None:
            return inbound
    if task.type == TaskType.WELLBEING_CHECKIN:
        alert = _alert(result)
        who = _who(ctx, task)
        if out in (CallOutcome.NO_ANSWER, CallOutcome.BUSY, CallOutcome.VOICEMAIL):
            return SummaryOut(summary=s(f"{who} didn't pick up the check-in call. I'll try again "
                                        f"shortly.", f"{who} ne check-in call nahi uthayi. Thodi der "
                                                     f"mein phir try karungi."),
                              next_steps=["Retry", "Call them yourself"])
        bits = []
        for key, label in (("medicine", "medicines"), ("feeling", "feeling"),
                           ("food_sleep", "food & sleep"), ("needs", "needs")):
            if col.get(key):
                bits.append(f"{label}: {col[key]}")
        if col.get("medicine_taken") == "no":
            bits.append("did NOT take medicine")
        body = "; ".join(bits) or "all okay"
        if alert:
            return SummaryOut(summary=s(f"⚠ {who} sounded unwell: \"{alert}\". I told them I'd "
                                        f"let you know right away. If it gets worse, call 112/108.",
                                        f"⚠ {who} ki tabiyat theek nahi lagi: \"{alert}\". Maine "
                                        f"kaha main turant aapko bataungi. Zyada ho toh 112/108."),
                              details=details, alert=alert,
                              next_steps=["Call them now", "Call their doctor",
                                          "Listen to recording"])
        return SummaryOut(summary=s(f"{who} check-in ☀️ {body}.", f"{who} check-in ☀️ {body}."),
                          details=details, next_steps=["Listen", "OK"])
    if out == CallOutcome.SUCCESS:
        if task.type in BOOKING_TYPES:
            terms = col.get("confirmed_terms") or task.approved_terms or (
                ", ".join(q.available_slots[:1]) if q and q.available_slots else "")
            return SummaryOut(summary=s(f"Booked ✅ {biz}: {terms}. I'll remind you before.",
                                        f"Ho gaya ✅ {biz}: {terms}. Pehle yaad dila dungi."),
                              details=details, next_steps=["Reschedule", "Cancel booking"])
        if task.type == TaskType.CUSTOMER_CARE:
            c = result.care
            ticket = c.ticket_number if c and c.ticket_number else "-"
            promise = f" · {c.promised_text}" if c and c.promised_text else ""
            return SummaryOut(summary=s(f"Done ✅ {biz}: ticket {ticket}{promise}. I'll follow up "
                                        f"if it isn't resolved by then.",
                                        f"Ho gaya ✅ {biz}: ticket {ticket}{promise}. Tab tak "
                                        f"resolve nahi hua toh follow-up karungi."),
                              details=details, next_steps=["Transcript", "Done"])
        if task.type == TaskType.STOCK_HUNT:
            return SummaryOut(summary=s(f"Found it ✅ {biz} has {task.spec.item or 'it'} in stock"
                                        f"{' at ' + format_inr(q.amount_inr) if q and q.amount_inr else ''}.",
                                        f"Mil gaya ✅ {biz} ke paas {task.spec.item or 'yeh'} hai"
                                        f"{', ' + format_inr(q.amount_inr) if q and q.amount_inr else ''}."),
                              details=details, next_steps=["Order for delivery", "Done"])
        answers = [f"• {k}: {v}" for k, v in col.items()
                   if k not in ("held", "in_stock", "matched_task_id") and len(v) < 200]
        head = s(f"{biz}:", f"{biz}:")
        return SummaryOut(summary="\n".join([head, *answers[:6]]) if answers else
                          s(f"Done ✅ {biz} - {task.spec.goal}.", f"Ho gaya ✅ {biz} - "
                                                                 f"{task.spec.goal}."),
                          details=details, next_steps=["Book it", "Done"])
    if out in (CallOutcome.PENDING_APPROVAL, CallOutcome.USER_TIMEOUT):
        slots = ", ".join(q.available_slots[:3]) if q and q.available_slots else ""
        price = f" ({format_inr(q.amount_inr)})" if q and q.amount_inr else ""
        held = " They're holding it for now." if col.get("held") == "yes" else ""
        extra = ""
        if col.get("advance_requested"):
            extra = s(" They asked for an advance - I didn't agree to anything.",
                      " Unhone advance maanga - maine kuch commit nahi kiya.")
        return SummaryOut(summary=s(f"{biz}{price}: {slots or 'offer ready'}.{held}{extra} Book "
                                    f"which?",
                                    f"{biz}{price}: {slots or 'offer mil gaya'}.{held}{extra} "
                                    f"Kaunsa book karun?"),
                          details=details, next_steps=["Approve to confirm by call-back"])
    if out in (CallOutcome.BUSY, CallOutcome.NO_ANSWER, CallOutcome.VOICEMAIL):
        return _retry_copy(ctx, task, result, s, details)
    if out == CallOutcome.CALLBACK_LATER:
        when = col.get("callback_at", "later")
        return SummaryOut(summary=s(f"{biz} asked me to call {when}. I'll call back then.",
                                    f"{biz} ne kaha {when} call karo. Tab call kar lungi."),
                          details=details)
    if out == CallOutcome.DECLINED:
        if col.get("refused_ai"):
            return SummaryOut(summary=s(f"{biz} didn't want to talk to an AI assistant, sorry about "
                                        f"that. Their number is {task.target.phone if task.target else ''}"
                                        f" if you'd like to call, or I can try somewhere else.",
                                        f"{biz} AI assistant se baat nahi karna chahte the. Aap khud "
                                        f"call kar sakte ho, ya main kahin aur try karun?"),
                              details=details, next_steps=["Find another place", "OK"])
        if col.get("wrong_number"):
            return SummaryOut(summary=s(f"That number isn't {biz}. Got the right one?",
                                        f"Yeh number {biz} ka nahi hai. Sahi number bhejenge?"))
        reason = col.get("reason") or col.get("slot_lost") or "they couldn't do it"
        if col.get("in_stock") == "no":
            reason = f"{task.spec.item or 'the item'} is out of stock"
        return SummaryOut(summary=s(f"{biz} said no - {reason}.", f"{biz} ne mana kar diya - "
                                                                  f"{reason}."),
                          details=details, next_steps=["Try another place", "OK"])
    if out == CallOutcome.HOLD_TIMEOUT:
        mins = round(result.hold_seconds / 60)
        return SummaryOut(summary=s(f"I waited {mins} min on hold with {biz} and no one picked up. "
                                    f"I'll retry at a better time.",
                                    f"{biz} pe {mins} min hold pe rahi, koi nahi aaya. Better time "
                                    f"pe phir try karungi."),
                          details=details, next_steps=["Retry later", "Cancel"])
    if out == CallOutcome.NEEDS_USER_VERIFICATION:
        path = " → ".join((result.care.ivr_path if result.care else []) or [])
        ticket = result.care.ticket_number if result.care and result.care.ticket_number else None
        pack = f"Call {task.target.phone if task.target else biz}" + (f" → {path}" if path else "")
        pack += f", quote ticket {ticket}" if ticket else ""
        return SummaryOut(summary=s(f"{biz} needs the account holder to verify (OTP), which I "
                                    f"can't do. Callback pack: {pack}.",
                                    f"{biz} account holder ka verification (OTP) maang rahe hain, "
                                    f"jo main nahi kar sakti. Aap aise call karein: {pack}."),
                          details=details, next_steps=["Patch me in next time", "I'll call"])
    if out == CallOutcome.TRANSFERRED:
        return SummaryOut(summary=s(f"Connected you with {biz}.", f"Aapko {biz} se jod diya."))
    if out == CallOutcome.HUNG_UP:
        return SummaryOut(summary=s(f"{biz} hung up mid-call. Want me to try once more?",
                                    f"{biz} ne beech mein call kaat di. Ek baar aur try karun?"),
                          details=details, next_steps=["Try again", "Find another place"])
    if out == CallOutcome.PARTIAL:
        got = "; ".join(f"{d.key}: {d.value}" for d in details) or "some details"
        return SummaryOut(summary=s(f"Spoke to {biz} - got {got}, but not everything.",
                                    f"{biz} se baat hui - {got} mila, par sab kuch nahi."),
                          details=details, next_steps=["Call again", "Done"])
    if out == CallOutcome.CANCELLED:
        return SummaryOut(summary=s(f"Call to {biz} cancelled.", f"{biz} wali call cancel ho gayi."))
    return SummaryOut(summary=s(f"Something went wrong calling {biz}. I'll retry in a few "
                                f"minutes.", f"{biz} ko call karte waqt dikkat aayi. Kuch minute "
                                             f"mein phir try karungi."),
                      details=details, next_steps=["Retry", "Cancel"])


def _retry_copy(ctx: ConversationContext, task: Task, result: CallResult, s, details
                ) -> SummaryOut:
    biz = _biz_name(task, result)
    what = {CallOutcome.BUSY: "busy", CallOutcome.VOICEMAIL: "voicemail"}.get(
        result.outcome, "no answer")
    if not is_final_attempt(task):
        nxt = next_attempt_time(task, result, ctx.now)
        at = format_ist(nxt, "%I:%M %p").lstrip("0").lower()
        return SummaryOut(
            summary=s(f"{biz} isn't picking up - I'll keep trying, next attempt {at}.",
                      f"{biz} phone nahi utha rahe - main try karti rahungi, agla try {at}."),
            details=[*details, KV(key="next_attempt_at", value=nxt.isoformat()),
                     KV(key="attempt", value=f"{max(task.attempts, 1)}/{task.max_attempts}")])
    tried = f"{max(task.attempts, 1)} tries"
    return SummaryOut(
        summary=s(f"Couldn't reach {biz} after {tried} (last: {what} at "
                  f"{format_ist(result.started_at, '%I:%M %p').lstrip('0').lower()}).",
                  f"{tried} ke baad bhi {biz} se baat nahi ho payi (last: {what}, "
                  f"{format_ist(result.started_at, '%I:%M %p').lstrip('0').lower()})."),
        details=details,
        next_steps=["Try later today", "Try tomorrow", "Pick another business"])


def _inbound_summary(ctx: ConversationContext, task: Task, result: CallResult, s
                     ) -> SummaryOut | None:
    col = result.collected
    biz = _biz_name(task, result)
    q = _best_quote(result)
    if col.get("message_taken"):
        bits = [col.get("caller_name") and f"name: {col['caller_name']}",
                col.get("purpose") and f"about: {col['purpose']}",
                col.get("callback_number") and f"call back: {col['callback_number']}"]
        msg = "; ".join(b for b in bits if b) or col.get("message", "no details")
        return SummaryOut(summary=s(f"An unknown caller rang Friday's number and left a message "
                                    f"({msg}). I shared no details about you.",
                                    f"Ek unknown caller ne message chhoda ({msg}). Maine aapki "
                                    f"koi detail share nahi ki."),
                          details=[KV(key="caller", value=result.to_phone)])
    label = task.spec.goal
    if col.get("closed_loop"):
        if col.get("late_offer") and q:
            return SummaryOut(summary=s(f"{biz} called back late with an offer "
                                        f"({q.price_text}). Your need was already met, so I "
                                        f"thanked them and closed it.",
                                        f"{biz} ne baad mein offer ke saath call kiya "
                                        f"({q.price_text}). Kaam pehle ho chuka tha, toh maine "
                                        f"shukriya bolke band kar diya."))
        return SummaryOut(summary=s(f"{biz} called back about \"{label}\" - already sorted, so I "
                                    f"thanked them and closed the loop.",
                                    f"{biz} ne \"{label}\" ke liye call back kiya - kaam ho chuka "
                                    f"tha, toh shukriya bolke baat khatam kar di."))
    if col.get("better_offer"):
        return SummaryOut(summary=s(f"{biz} called with a better offer after your booking: "
                                    f"{q.price_text if q else col['better_offer']}. Your booking is "
                                    f"unchanged. Switch only if it can be changed without a "
                                    f"penalty - want me to ask?",
                                    f"{biz} ne booking ke baad behtar offer diya: "
                                    f"{q.price_text if q else col['better_offer']}. Booking waisi "
                                    f"hi hai. Bina penalty change ho sake toh poochun?"),
                          next_steps=["Ask to switch", "Keep as is"])
    if col.get("change_request"):
        return SummaryOut(summary=s(f"{biz} called about your booking and wants a change: "
                                    f"\"{col['change_request']}\". I didn't agree to anything. "
                                    f"Approve?",
                                    f"{biz} ne booking change karne ke liye call kiya: "
                                    f"\"{col['change_request']}\". Maine kuch final nahi kiya. "
                                    f"Approve karun?"),
                          next_steps=["Approve change", "Keep original", "Cancel booking"])
    if col.get("business_cancelled"):
        return SummaryOut(summary=s(f"Heads up: {biz} called to cancel - \"{col['business_cancelled']}"
                                    f"\". Want me to find another option?",
                                    f"Dhyan dein: {biz} ne cancel karne ke liye call kiya - "
                                    f"\"{col['business_cancelled']}\". Doosra option dhundun?"),
                          next_steps=["Find another", "OK"])
    if col.get("ready"):
        return SummaryOut(summary=s(f"{biz} called: it's ready - \"{col['ready']}\".",
                                    f"{biz} ka call aaya: ready hai - \"{col['ready']}\"."))
    if col.get("reconfirmed"):
        return SummaryOut(summary=s(f"{biz} called to reconfirm; I confirmed it's still on.",
                                    f"{biz} ne reconfirm karne ke liye call kiya; maine bata diya "
                                    f"booking pakki hai."))
    return None


# =============================================================================== TaskResult


def build_task_result(ctx: ConversationContext, task: Task, result: CallResult,
                      text: SummaryOut, settings: Settings) -> TaskResult:
    tpl = template_for(task.type)
    q = _best_quote(result)
    col = result.collected
    biz_id = (task.target.business_id if task.target else None) or task.spec.business_id
    success = result.outcome == CallOutcome.SUCCESS
    is_booking = task.type in BOOKING_TYPES

    appointment_at = None
    if success and is_booking:
        terms = col.get("confirmed_terms") or task.approved_terms or (
            q.available_slots[0] if q and q.available_slots else None)
        if terms:
            appointment_at = slot_to_datetime(terms, result.started_at)
    follow_up_at = None
    if success and tpl.follow_up_after_h:
        base = appointment_at or ensure_utc(ctx.now)
        follow_up_at = base + timedelta(hours=tpl.follow_up_after_h)
    care = result.care
    if care and care.promised_date:
        from friday.core.clock import at_ist

        follow_up_at = at_ist(care.promised_date, 10) + timedelta(
            hours=settings.care_followup_grace_h)

    needs_approval = None
    if result.outcome in (CallOutcome.PENDING_APPROVAL, CallOutcome.USER_TIMEOUT) or \
            col.get("change_request") or col.get("better_offer"):
        options: list[str] = []
        price = f", {format_inr(q.amount_inr)}" if q and q.amount_inr else ""
        if q and q.available_slots:
            options = [truncate_title(f"{s}{price}", 60) for s in q.available_slots[:2]]
        if not options:
            options = ["Yes, book it"]
        options.append("None of these")
        needs_approval = MidCallQuestion(
            task_id=task.id, call_id=result.call_id,
            text=text.summary, purpose=QuestionPurpose.APPROVE_BOOKING, options=options[:3],
            timeout_s=7200)

    interactions: list[VendorInteraction] = []
    if biz_id and result.dial_status.value == "answered":
        interactions.append(VendorInteraction(user_id=task.requester_user_id, business_id=biz_id,
                                              kind=InteractionKind.CALLED, task_id=task.id,
                                              call_id=result.call_id,
                                              outcome=result.outcome.value, at=result.started_at))
        for quote in result.quotes:
            if quote.amount_inr:
                interactions.append(VendorInteraction(
                    user_id=task.requester_user_id, business_id=biz_id,
                    kind=InteractionKind.QUOTED, task_id=task.id, call_id=result.call_id,
                    amount_inr=quote.amount_inr, note=quote.price_text[:200],
                    at=result.started_at))
        if success and is_booking:
            interactions.append(VendorInteraction(
                user_id=task.requester_user_id, business_id=biz_id, kind=InteractionKind.BOOKED,
                task_id=task.id, call_id=result.call_id,
                amount_inr=q.amount_inr if q else None, at=result.started_at))
        if col.get("closed_loop"):
            interactions.append(VendorInteraction(
                user_id=task.requester_user_id, business_id=biz_id, kind=InteractionKind.NOTE,
                task_id=task.id, call_id=result.call_id,
                note="called back after the need was met; loop closed", at=result.started_at))

    facts: list[Fact] = []
    if biz_id and result.languages_heard:
        facts.append(Fact(user_id=task.requester_user_id, kind=FactKind.GENERAL,
                          key="business_language", value=result.languages_heard[-1].value,
                          business_id=biz_id, confidence=0.8))

    touch = None
    if success and task.target and task.target.kind.value == "business" and \
            result.direction == CallDirection.OUTBOUND:
        name = _who(ctx, task) if task.beneficiary.person_id else (ctx.profile.name or "")
        if is_booking:
            touch = TemplateRef(key="business_booking_confirmed",
                                params=[name, col.get("confirmed_terms", "") or "", "Friday"])
        elif task.type in (TaskType.ENQUIRY, TaskType.QUOTE, TaskType.STOCK_HUNT):
            touch = TemplateRef(key="business_enquiry_thanks", params=[name, "Friday"])

    details = {kv.key: kv.value for kv in text.details}
    alert = text.alert or (_alert(result) if task.type == TaskType.WELLBEING_CHECKIN else None)
    if task.type == TaskType.WELLBEING_CHECKIN and col.get("medicine_taken") == "no" and alert:
        alert = f"{alert} (also missed medicine)"
    return TaskResult(
        success=success,
        summary=text.summary,
        details=details,
        appointment_at=appointment_at,
        next_steps=text.next_steps,
        follow_up_at=follow_up_at,
        retry_suggested=result.outcome.is_retryable,
        quotes=list(result.quotes),
        needs_approval=needs_approval,
        alert=alert,
        care=care,
        interactions=interactions,
        facts=facts,
        business_touch=touch,
    )


# =============================================================================== compare


def rank_quotes(quotes: list[Quote], budget_max: int | None) -> list[Quote]:
    def key(q: Quote):
        within = q.within_budget if q.within_budget is not None else (
            budget_max is None or (q.amount_inr is not None and q.amount_inr <= budget_max))
        return (0 if within else 1, q.amount_inr if q.amount_inr is not None else math.inf,
                0 if q.available_slots else 1, q.business_name)
    return sorted(quotes, key=key)


def compare_text(ctx: ConversationContext, parent: Task, ranked: list[Quote]) -> CompareOut:
    lang, tone = ctx.profile.language, ctx.profile.tone
    if not ranked:
        return CompareOut(summary=say(lang, tone, en="No usable quotes came back. Want me to "
                                                     "search again?",
                                      hinglish="Koi kaam ka quote nahi mila. Phir se dhundun?"))
    lines = []
    for q in ranked:
        price = (f"{format_inr(q.original_amount_inr)} → {format_inr(q.amount_inr)}"
                 if q.negotiated else (format_inr(q.amount_inr) if q.amount_inr else q.price_text))
        bits = [price]
        if q.available_slots:
            bits.append(", ".join(q.available_slots[:2]))
        if q.inclusions:
            bits.append(q.inclusions[0][:50])
        if q.within_budget is False:
            bits.append("over budget")
        lines.append(f"• {q.business_name}: " + " · ".join(bits))
    best = ranked[0]
    why = []
    if best.amount_inr is not None:
        why.append("best price" if len(ranked) > 1 else "price fits")
    if best.available_slots:
        why.append("slot available")
    rec = say(lang, tone, en=f"My pick: {best.business_name} ({', '.join(why) or 'best fit'}).",
              hinglish=f"Meri pick: {best.business_name} ({', '.join(why) or 'best fit'}).")
    return CompareOut(summary="\n".join(lines + [rec]), recommended_index=0)


def comparison_buttons(parent: Task, ranked: list[Quote]) -> list[ReplyButton]:
    n = 3 if len(ranked) <= 2 else 2
    buttons = [ReplyButton(id=f"c:{parent.id}:{i}", title=truncate_title(f"Book {q.business_name}"))
               for i, q in enumerate(ranked[: min(n, len(ranked))])]
    if len(buttons) < 3:
        buttons.append(ReplyButton(id=f"c:{parent.id}:none", title="None of these"))
    return buttons[:3]


def build_comparison(parent: Task, ranked: list[Quote], text: CompareOut) -> QuoteComparison:
    idx = text.recommended_index
    if idx is None or not (0 <= idx < len(ranked)):
        idx = 0 if ranked else None
    return QuoteComparison(summary=text.summary, ranked_quotes=ranked, recommended_index=idx,
                           buttons=comparison_buttons(parent, ranked))


# =============================================================================== shortlist

_POSITIVE = ("on time", "punctual", "fair price", "honest", "great", "excellent", "quick",
             "patient", "professional", "clean", "friendly", "no upselling", "reasonable",
             "recommend", "best", "polite")
_NEGATIVE = ("overcharg", "late", "rude", "scam", "fraud", "otp", "never came", "no show",
             "dirty", "unprofessional", "cheat", "worst", "expensive", "upsell")


def shortlist(ctx: ConversationContext, spec: TaskSpec, candidates: list[BusinessCandidate],
              n: int, min_rating: float = 3.8) -> list[ShortlistItem]:
    scored: list[tuple[float, str, BusinessCandidate, str]] = []
    history = {}
    known = {b.phone: b.id for b in ctx.known_businesses}
    for v in ctx.vendor_history:
        history.setdefault(v.business_id, []).append(v)
    for cand in candidates:
        if not cand.phone:
            continue
        rating = cand.rating or 0.0
        count = cand.review_count or 0
        bayes = (rating * count + 4.0 * 20) / (count + 20) if rating else 3.0
        score = bayes
        reviews = " ".join(cand.review_snippets).lower()
        pos = [w for w in _POSITIVE if w in reviews]
        neg = [w for w in _NEGATIVE if w in reviews]
        score += 0.08 * len(pos) - 0.25 * len(neg)
        if cand.distance_km is not None:
            score -= 0.08 * max(0.0, cand.distance_km - 1.0)
        past = history.get(known.get(cand.phone, ""), [])
        used_before = any(v.kind in (InteractionKind.BOOKED, InteractionKind.COMPLETED,
                                     InteractionKind.PAID) for v in past)
        bad_past = any(v.kind == InteractionKind.NO_SHOW or (v.rating is not None and v.rating <= 2)
                       for v in past)
        if used_before:
            score += 0.3
        if bad_past:
            score -= 1.0
        if cand.rating is not None and cand.rating < min_rating:
            score -= 0.5
        reason_bits = []
        if cand.rating:
            reason_bits.append(f"{cand.rating:.1f}★ ({count})")
        if used_before:
            reason_bits.append("you've used them before")
        if bad_past:
            reason_bits.append("⚠ bad experience last time")
        if pos and cand.review_snippets:
            snippet = next((r for r in cand.review_snippets if any(w in r.lower() for w in pos)),
                           cand.review_snippets[0])
            reason_bits.append(f"\"{snippet[:60]}\"")
        if neg:
            reason_bits.append(f"⚠ reviews mention {neg[0].rstrip('g')}")
        if cand.distance_km is not None:
            reason_bits.append(f"{cand.distance_km:.1f} km")
        scored.append((round(score, 4), cand.name, cand, ", ".join(reason_bits)))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [ShortlistItem(candidate=c, rank=i + 1, reason=r or "nearby option")
            for i, (_s, _n, c, r) in enumerate(scored[: max(0, n)])]


_LONG_DIGITS = re.compile(r"\d[\d\s-]{5,}\d")


def reason_input(item: ShortlistItem) -> dict:
    """Non-personal facts about one ranked candidate for the batched reasons call."""
    c = item.candidate
    return {"name": c.name, "rating": c.rating, "reviews": c.review_count,
            "snippets": [s[:140] for s in c.review_snippets[:3]],
            "distance_km": c.distance_km, "default_reason": item.reason}


def clean_reason(text: str | None) -> str | None:
    """LLM-written reasons are shown to the user: short, no numbers that look like
    phones/accounts, no links. Anything odd -> keep the deterministic reason."""
    if not text:
        return None
    t = " ".join(text.split())[:110]
    if _LONG_DIGITS.search(t) or "http" in t.lower() or "@" in t:
        return None
    return t


_DETERMINISTIC_ONLY = {CallOutcome.BUSY, CallOutcome.NO_ANSWER, CallOutcome.VOICEMAIL,
                       CallOutcome.CALLBACK_LATER, CallOutcome.HOLD_TIMEOUT,
                       CallOutcome.NEEDS_USER_VERIFICATION, CallOutcome.TRANSFERRED,
                       CallOutcome.HUNG_UP, CallOutcome.FAILED, CallOutcome.CANCELLED,
                       CallOutcome.DECLINED}


def needs_llm_summary(task: Task, result: CallResult) -> bool:
    """Templates cover the routine outcomes; the LLM only writes the prose for calls
    with real content (success / partial / offers, check-ins)."""
    if result.outcome in _DETERMINISTIC_ONLY:
        return False
    col = result.collected
    if col.get("message_taken") or col.get("closed_loop"):
        return False
    return True
