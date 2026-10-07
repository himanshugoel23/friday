"""Deterministic, goal-driven call agent (the fake LLM's ``call_turn`` and the
real path's fallback). It is NOT a per-business Q&A tree: it reads the brief's
goal/constraints and the transcript, and decides the next move with the same
rules the LLM prompt states. Output passes through ``friday.brain.guards`` after.
"""

from __future__ import annotations

import re

from friday.core.models import (
    ApprovalMode,
    CallActionType,
    CallBrief,
    CallMode,
    CallOutcome,
    CareRequestKind,
    Language,
    QuestionPurpose,
    TargetKind,
    TaskType,
    Transcript,
    UserAnswer,
)

from ..copy import first_name
from ..inbound import CLOSED_ELSEWHERE, InboundContext, RelatedTask, inbound_of
from ..lang import mirror, text_language
from ..schemas import KV, CallActionOut, CareOut, QuestionOut, QuoteOut
from ..textutil import (
    format_inr,
    has_any,
    is_no,
    is_yes,
    minutes_of,
    norm,
    parse_time_of_day,
    slot_to_datetime,
)
from .callstate import (
    AI_QUESTION,
    CALL_LATER,
    CANT_RESOLVE,
    DISTRESS,
    DO_NOT_CALL,
    HOSTILE_AI,
    IDENTIFIER_PROMPT,
    MED_SKIPPED,
    PAYMENT_WORDS,
    POSITIVE_WORDS,
    VERIFY_WORDS,
    WAIT_WORDS,
    WRONG_NUMBER,
    CallState,
    affirmative,
    find_agent,
    find_promise,
    find_ticket,
    is_hold,
    is_ivr,
    ivr_options,
    read_state,
    strip_tag,
    wait_minutes,
)

COMMIT_TYPES = {TaskType.BOOKING, TaskType.HEALTHCARE, TaskType.RESCHEDULE, TaskType.ORDER,
                TaskType.RECURRING_BOOKING, TaskType.HOTEL_BOOKING}
INFO_TYPES = {TaskType.ENQUIRY, TaskType.STOCK_HUNT, TaskType.STATUS_CHASE,
              TaskType.RENTAL_HUNT}
QUOTE_TYPES = {TaskType.QUOTE, TaskType.DISCOVERY}
MAX_FRIDAY_TURNS = 12


class Turn:
    """Per-turn helpers: language choice + phrase picking + action builders."""

    def __init__(self, st: CallState, speakable: frozenset[Language] | None) -> None:
        self.st = st
        self.b = st.brief
        lang = mirror(st.callee_lang, self.b.opening_language, speakable)
        self.lang = text_language(lang)
        self.name = first_name(self.b.on_behalf_of, "my user")
        self.who = self.b.beneficiary_name or self.b.on_behalf_of

    def t(self, *, en: str, hinglish: str, hi: str | None = None) -> str:
        if self.lang == Language.EN:
            return en
        if self.lang == Language.HI and hi:
            return hi
        return hinglish

    # ------------------------------------------------------------------ builders
    def quote(self, notes: str | None = None) -> QuoteOut | None:
        st = self.st
        if st.price is None and not st.slots:
            return None
        parts = []
        if st.price is not None:
            if st.original_price and st.original_price != st.price:
                parts.append(f"{format_inr(st.original_price)} -> {format_inr(st.price)}")
            else:
                parts.append(format_inr(st.price))
        parts += st.extras[:2]
        return QuoteOut(
            amount_inr=st.price,
            original_amount_inr=st.original_price,
            price_text="; ".join(parts) or "price not stated",
            inclusions=st.inclusions[:4],
            available_slots=st.slots[:4],
            notes=notes,
        )

    def act(self, type_: CallActionType, text: str | None = None, **kw) -> CallActionOut:
        if "quote" not in kw:
            kw["quote"] = self.quote()
        return CallActionOut(type=type_, text=text, language=self.lang, **kw)

    def say(self, text: str, **kw) -> CallActionOut:
        return self.act(CallActionType.SAY, text, **kw)

    def hangup(self, text: str, outcome: CallOutcome, **kw) -> CallActionOut:
        return self.act(CallActionType.HANGUP, text, outcome=outcome, **kw)

    def callback(self, extra: dict[str, str] | None = None, pre: str = "") -> CallActionOut:
        """Founder approval rule: never confirm; promise a call-back; PENDING_APPROVAL."""
        st = self.st
        collected = [KV(key="offered_slots", value=", ".join(st.slots))] if st.slots else []
        if st.price is not None:
            collected.append(KV(key="price", value=format_inr(st.price)))
        held = st.after_friday_said("hold", "rakh sakte", "rakh dijiye")
        if held:
            collected.append(KV(key="held", value="yes" if affirmative(held) else "no"))
        for k, v in (extra or {}).items():
            collected.append(KV(key=k, value=v))
        text = pre + self.t(
            en=f"Thank you. I'll confirm with {self.name} and call you back in 10-15 minutes.",
            hinglish=f"Shukriya ji. Main {self.name} ji se confirm karke 10-15 minute mein call "
                     f"back karti hoon.",
            hi=f"शुक्रिया जी। मैं {self.name} जी से कन्फ़र्म करके 10-15 मिनट में कॉल बैक करती हूँ।")
        return self.hangup(text, CallOutcome.PENDING_APPROVAL, collected=collected)


# =============================================================================== entry


def next_action(brief: CallBrief, transcript: Transcript, answers: list[UserAnswer],
                speakable: frozenset[Language] | None = None) -> CallActionOut:
    st = read_state(brief, transcript, answers)
    tn = Turn(st, speakable)
    ib = inbound_of(brief)

    if brief.mode == CallMode.TRANSLATOR:
        return tn.act(CallActionType.WAIT)

    sys_action = _system_turn(tn)
    if sys_action is not None:
        return sys_action

    last = st.last_callee.text if st.last_callee else ""
    lt = norm(last)
    last_is_newest = st.last is not None and st.last is st.last_callee

    # IVR / hold (only when the newest thing we heard is that prompt)
    if last_is_newest and last and is_hold(last):
        mins = wait_minutes(last)
        company = brief.company or brief.target.name
        update = f"On hold with {company}" + (f", expected wait ~{mins} min" if mins else "") + \
            ". I'll tell you when a person picks up."
        return tn.act(CallActionType.WAIT_ON_HOLD, max_hold_s=brief.max_hold_s,
                      user_update=update)
    if last_is_newest and last and is_ivr(last):
        return _ivr(tn, last)

    # verification / OTP demanded by a human
    if last_is_newest and has_any(lt, VERIFY_WORDS) and brief.task_type != \
            TaskType.WELLBEING_CHECKIN:
        return _verification(tn)

    if ib is not None:
        action = _inbound(tn, ib)
        if action is not None:
            return _with_ai_answer(tn, lt, action)

    if st.last_callee is not None and last_is_newest:
        early = _universal(tn, lt)
        if early is not None:
            return early

    if len(st.friday) >= MAX_FRIDAY_TURNS:
        return _wrap_up(tn)

    action = _flow(tn)
    return _with_ai_answer(tn, lt if last_is_newest else "", action)


def _flow(tn: Turn) -> CallActionOut:
    b = tn.b
    if b.mode == CallMode.WARM_TRANSFER:
        return _warm_transfer(tn)
    tt = b.task_type
    if tt == TaskType.WELLBEING_CHECKIN or b.target.kind == TargetKind.PERSON:
        return _wellbeing(tn)
    if tt == TaskType.CUSTOMER_CARE:
        return _care(tn)
    if tt in (TaskType.CANCEL_BOOKING,):
        return _cancel(tn)
    if tt in (TaskType.RECONFIRM, TaskType.RUNNING_LATE):
        return _notify(tn)
    if tt in (TaskType.SERVICE_COORDINATION, TaskType.COMPLAINT):
        return _coordination(tn)
    if tt in INFO_TYPES:
        return _enquiry(tn)
    if tt in QUOTE_TYPES and not (b.approved_terms or b.delegation.granted):
        return _quote(tn)
    return _booking(tn)


# =============================================================================== shared


def _system_turn(tn: Turn) -> CallActionOut | None:
    st = tn.st
    if st.last is None or st.last.speaker.value != "system":
        return None
    s = norm(st.last.text)
    if s.startswith("blocked"):
        if has_any(s, ("otp", "pin", "cvv", "password", "unapproved", "number", "identifier")):
            return _verification(tn)
        if has_any(s, ("commit", "approval", "can_commit", "confirm")):
            return tn.callback()
        return tn.say(tn.t(en="Sorry, let me rephrase that.",
                           hinglish="Maaf kijiye, main dobara bolti hoon."))
    if "did not answer" in s or "no answer" in s or "timeout" in s or "timed out" in s:
        return tn.callback({"user_timeout": "true"})
    if s.startswith("user answered") or s.startswith("user said"):
        return None  # handled by flows through ``answers``
    if "human agent joined" in s or "agent joined" in s:
        return None
    return None


def _universal(tn: Turn, lt: str) -> CallActionOut | None:
    st, b = tn.st, tn.b
    if has_any(lt, DO_NOT_CALL):
        return tn.hangup(tn.t(en="Understood, sorry for the trouble. Have a good day.",
                              hinglish="Ji samajh gayi, takleef ke liye maafi. Aapka din achha "
                                       "rahe."),
                         CallOutcome.DECLINED, collected=[KV(key="do_not_call", value="true")])
    if has_any(lt, WRONG_NUMBER):
        return tn.hangup(tn.t(en="Sorry, wrong number. Thank you.",
                              hinglish="Maaf kijiye, galat number lag gaya. Shukriya."),
                         CallOutcome.DECLINED, collected=[KV(key="wrong_number", value="true")])
    if has_any(lt, HOSTILE_AI):
        if st.friday_said("30 second", "quick", "jaldi", "bas ek"):
            return tn.hangup(tn.t(en="No problem, thank you for your time.",
                                  hinglish="Koi baat nahi ji, aapka samay dene ke liye shukriya."),
                             CallOutcome.DECLINED,
                             collected=[KV(key="refused_ai", value="true")])
        return tn.say(tn.t(
            en=f"I understand. It's a quick 30-second request for {tn.name} - {_ask_line(tn)}",
            hinglish=f"Bilkul samajh sakti hoon ji. Bas 30 second ka kaam hai, {tn.name} ji ke "
                     f"liye - {_ask_line(tn)}"))
    if has_any(lt, CALL_LATER) and not has_any(lt, WAIT_WORDS) and b.task_type != \
            TaskType.WELLBEING_CHECKIN:
        start, _e, _x = parse_time_of_day(lt)
        when = re.search(r"(after|baad|in|tomorrow|kal)[^.?!]{0,20}", lt)
        collected = [KV(key="callback_at", value=(when.group(0).strip() if when else "later"))]
        if start is not None:
            collected.append(KV(key="callback_time_min_ist", value=str(start)))
        return tn.hangup(tn.t(en="Sure, I'll call back then. Thank you.",
                              hinglish="Ji zaroor, tab call karti hoon. Shukriya."),
                         CallOutcome.CALLBACK_LATER, collected=collected)
    if has_any(lt, WAIT_WORDS) and len(lt.split()) <= 8 and not st.slots[-1:] == [lt]:
        return tn.act(CallActionType.WAIT)
    if has_any(lt, PAYMENT_WORDS) and b.task_type not in (TaskType.CUSTOMER_CARE,):
        return tn.callback({"advance_requested": st.last_callee.text[:120]},
                           pre=tn.t(en="I can't agree to any payment on this call. ",
                                    hinglish="Payment ke baare mein main abhi haan nahi bol "
                                             "sakti. "))
    return None


def _with_ai_answer(tn: Turn, lt: str, action: CallActionOut) -> CallActionOut:
    if not lt or not has_any(lt, AI_QUESTION):
        return action
    honest = tn.t(en=f"Yes, I'm an AI assistant calling for {tn.name}. ",
                  hinglish=f"Ji haan, main ek AI assistant hoon, {tn.name} ji ki taraf se. ",
                  hi=f"जी हाँ, मैं एक AI असिस्टेंट हूँ, {tn.name} जी की तरफ़ से। ")
    if action.type in (CallActionType.SAY, CallActionType.HANGUP, CallActionType.ASK_USER):
        action.text = honest + (action.text or "")
        return action
    return CallActionOut(type=CallActionType.SAY, text=honest + _ask_line(tn),
                         language=tn.lang, quote=action.quote)


def _verification(tn: Turn) -> CallActionOut:
    b = tn.b
    gathered = [KV(key="verification_required", value="true")]
    if b.user_phone:
        return tn.act(
            CallActionType.BRIDGE_USER,
            tn.t(en=f"I'm an AI assistant, so I can't share OTPs. I'll connect {tn.name} to "
                    f"verify directly - one moment please.",
                 hinglish=f"Main AI assistant hoon, OTP share nahi kar sakti. Main abhi {tn.name} "
                          f"ji ko call pe jod deti hoon, woh khud verify kar denge."),
            leave_after_bridge=True, collected=gathered)
    return tn.hangup(
        tn.t(en=f"I'm an AI assistant and can't share OTPs or verification details. {tn.name} "
                f"will call you back to verify. Thank you.",
             hinglish=f"Main AI assistant hoon, OTP ya verification details share nahi kar "
                      f"sakti. {tn.name} ji khud call karke verify kar denge. Shukriya."),
        CallOutcome.NEEDS_USER_VERIFICATION, collected=gathered)


def _ask_line(tn: Turn) -> str:
    """One-sentence ask for the goal (used in openings & re-asks)."""
    b = tn.b
    when = ", ".join(b.preferred_times[:2])
    tt = b.task_type
    if b.approved_terms:
        return tn.t(en=f"{tn.name} has approved: {b.approved_terms}. Could you please confirm it?",
                    hinglish=f"{tn.name} ji ne {b.approved_terms} approve kiya hai. Kya aap "
                             f"confirm kar sakte hain?")
    if tt == TaskType.HOTEL_BOOKING and b.stay:
        s = b.stay
        return tn.t(
            en=f"I'm looking for a room for {s.adults} adults from {s.check_in:%d %b} to "
               f"{s.check_out:%d %b}"
               f"{' - ' + ', '.join(s.preferences) if s.preferences else ''}. Is it available?",
            hinglish=f"{s.check_in:%d %b} se {s.check_out:%d %b} tak {s.adults} logon ke liye "
                     f"room chahiye tha"
                     f"{' - ' + ', '.join(s.preferences) if s.preferences else ''}. Available hai?")
    goal = b.goal.rstrip(".")
    if tt in INFO_TYPES or tt in QUOTE_TYPES:
        q = (b.questions or (b.template.default_questions if b.template else []) or [goal])[0]
        return q
    need = _need_phrase(goal, b.target.name)
    when_part = f", {when}" if when and when not in need else ""
    if tt == TaskType.ORDER:
        return tn.t(en=f"I'd like to place an order: {need}{when_part}. Is it available, and "
                       f"what would the total be with delivery?",
                    hinglish=f"Ek order dena tha: {need}{when_part}. Available hai, aur delivery "
                             f"ke saath total kitna hoga?")
    if tt == TaskType.RESCHEDULE:
        return tn.t(en=f"I'm calling to move a booking: {need}{when_part}. Is that possible?",
                    hinglish=f"Ek booking shift karni thi: {need}{when_part}. Ho payega?")
    return tn.t(en=f"I'd like to book {need}{when_part}. What slots do you have?",
                hinglish=f"{need}{when_part} ke liye slot chahiye tha. Kaunse slots available "
                         f"hain?",
                hi=f"{need}{when_part} के लिए स्लॉट चाहिए था। कौनसे स्लॉट available हैं?")


def _need_phrase(goal: str, target: str) -> str:
    """'Book a haircut for Ankit at Looks salon, Sat' -> 'a haircut for Ankit, Sat'."""
    g = re.sub(r"^(book|order|get|reschedule|schedule)\s+", "", goal, flags=re.I)
    if target:
        g = re.sub(rf"\s+(at|from|with)\s+{re.escape(target)}", "", g, flags=re.I)
    return g.strip()


def _wrap_up(tn: Turn) -> CallActionOut:
    st = tn.st
    if st.slots or st.price is not None:
        if tn.b.task_type in COMMIT_TYPES and not tn.b.approved_terms:
            return tn.callback()
        return tn.hangup(tn.t(en="Thank you, that's all I needed.",
                              hinglish="Shukriya ji, bas itna hi jaanna tha."),
                         CallOutcome.SUCCESS if tn.b.task_type not in COMMIT_TYPES
                         else CallOutcome.PARTIAL)
    return tn.hangup(tn.t(en="Thank you for your time. I'll get back if needed.",
                          hinglish="Aapke samay ke liye shukriya ji."), CallOutcome.PARTIAL)


# =============================================================================== IVR


_AGENT_WORDS = ("executive", "agent", "customer care", "speak", "talk", "representative",
                "customer service", "baat", "officer", "assistance", "other queries")
_AVOID_WORDS = ("repeat", "balance", "recharge offers", "offers", "new connection", "sales")


def _ivr(tn: Turn, prompt: str) -> CallActionOut:
    st, b = tn.st, tn.b
    prompt = strip_tag(prompt)
    p = norm(prompt)
    path = _ivr_path(st)
    care = CareOut(ivr_path=path, escalation_level=1)
    if has_any(p, ("otp", "one time password", "verification code", "pin", "cvv", "password")):
        return _verification(tn)
    if re.search(IDENTIFIER_PROMPT, p):
        ident = _identifier_for(b, p)
        if ident is None:
            return tn.hangup(None, CallOutcome.NEEDS_USER_VERIFICATION,
                             collected=[KV(key="ivr_needs", value=prompt[:120])], care=care,
                             user_update=f"{b.company or b.target.name}'s IVR needs a detail you "
                                         f"haven't approved for this call.")
        digits = re.sub(r"\D", "", ident.value)
        if "hash" in p or "#" in p:
            digits += "#"
        return tn.act(CallActionType.PRESS_KEYS, digits=digits, care=care)
    options = ivr_options(prompt)
    if not options:
        if has_any(p, ("say", "boliye", "tell us")) and has_any(p, ("agent", "executive")):
            return tn.say("Agent", care=care)
        return tn.act(CallActionType.WAIT, care=care)
    repeats = sum(1 for t in st.callee if norm(strip_tag(t.text)) == p)
    key = _pick_ivr_key(b, options, tried=_tried_for_prompt(st, p) if repeats > 1 else set())
    return tn.act(CallActionType.PRESS_KEYS, digits=key, care=care)


def _tried_for_prompt(st: CallState, p: str) -> set[str]:
    tried: set[str] = set()
    turns = st.transcript.turns
    for i, t in enumerate(turns[:-1]):
        if t.speaker.value == "callee" and norm(strip_tag(t.text)) == p:
            nxt = turns[i + 1]
            m = re.search(r"(?:dtmf|pressed|keys?)\D*([0-9*#]+)", norm(nxt.text))
            if m:
                tried.add(m.group(1))
    return tried


def _ivr_path(st: CallState) -> list[str]:
    path = []
    for t in st.transcript.turns:
        if t.speaker.value in ("friday", "system"):
            m = re.search(r"(?:dtmf|pressed|keys?)\D*([0-9*#]{1,2})\b", norm(t.text))
            if m:
                path.append(m.group(1))
    return path


def _pick_ivr_key(b: CallBrief, options: list[tuple[str, str]], tried: set[str]) -> str:
    want_lang = "hindi" if b.opening_language == Language.HI else "english"
    goal_words = set(re.findall(r"[a-z]{4,}", norm(" ".join([
        b.goal, b.company or "", (b.care_request.value if b.care_request else ""),
        " ".join(b.ivr_notes)]))))
    if b.care_request == CareRequestKind.COMPLAINT:
        goal_words |= {"fault", "complaint", "report", "problem", "issue", "technical"}
    if b.care_request == CareRequestKind.REFUND:
        goal_words |= {"refund", "billing", "bill", "payment"}
    best, best_score = None, -99.0
    for key, label in options:
        if key in tried:
            continue
        lbl = norm(label)
        score = 0.0
        if has_any(lbl, ("hindi", "english")):
            score += 5 if want_lang in lbl else 1
        if has_any(lbl, _AGENT_WORDS) and b.prefer_human_agent:
            score += 3
        score += 2 * len(goal_words & set(re.findall(r"[a-z]{4,}", lbl)))
        if has_any(lbl, _AVOID_WORDS):
            score -= 3
        if has_any(lbl, ("main menu", "previous menu", "go back")):
            score -= 1
        if score > best_score:
            best, best_score = key, score
    if best is None or best_score < 0:
        back = next((k for k, lbl in options if has_any(norm(lbl), ("main menu", "go back",
                                                                     "previous"))), None)
        return back or (best or options[0][0])
    return best


def _identifier_for(b: CallBrief, prompt: str):
    if not b.approved_identifiers:
        return None
    wants_mobile = has_any(prompt, ("mobile", "phone", "registered number"))
    for ident in b.approved_identifiers:
        lbl = norm(ident.label)
        if wants_mobile and has_any(lbl, ("mobile", "phone", "registered")):
            return ident
        if not wants_mobile and not has_any(lbl, ("mobile", "phone")):
            if any(w in lbl for w in re.findall(r"[a-z]{4,}", prompt)):
                return ident
    if not wants_mobile:
        return next((i for i in b.approved_identifiers
                     if not has_any(norm(i.label), ("mobile", "phone"))), None)
    return None


# =============================================================================== booking


def _delegated_slot(tn: Turn) -> str | None:
    """Earliest offered slot within the explicit delegation's limits (or None)."""
    st, d = tn.st, tn.b.delegation
    if not d.granted:
        return None
    if d.max_price_inr is not None and (st.price is None or st.price > d.max_price_inr):
        return None
    tw_start = tw_end = None
    if d.time_window_text:
        tw_start, tw_end, exact = parse_time_of_day(d.time_window_text)
        if exact and tw_start is not None:
            tw_end = tw_start + 60
    candidates = []
    for slot in st.slots:
        when = slot_to_datetime(slot, d.window_start or tn.b.window_start or st.started)
        if when is None:
            continue
        if (d.window_start or d.window_end) and not d.allows_time(when):
            continue
        if tw_start is not None and tw_end is not None and not (
                tw_start <= minutes_of(when) <= tw_end):
            continue
        candidates.append((when, slot))
    if candidates:
        return sorted(candidates)[0][1]
    if not st.slots and not (d.window_start or d.window_end or d.time_window_text):
        return "the offered slot" if st.price is not None else None
    return None


def _confirm_text(tn: Turn, terms: str) -> str:
    who = tn.who
    return tn.t(en=f"Please confirm it: {terms}, in the name of {who}. Is that correct?",
                hinglish=f"Toh confirm kar dijiye: {terms}, {who} ke naam pe. Sahi hai?",
                hi=f"तो कन्फ़र्म कर दीजिए: {terms}, {who} के नाम पे। सही है?")


def _terms(tn: Turn, slot: str | None) -> str:
    st = tn.st
    bits = [slot] if slot else []
    if st.price is not None:
        bits.append(format_inr(st.price))
    return ", ".join(bits) or tn.b.goal


def _booking(tn: Turn) -> CallActionOut:
    st, b = tn.st, tn.b
    reply = st.reply_text()
    approved = st.approved_answer()
    commit_ok = bool(b.approved_terms) or approved is not None
    asked_confirm = st.friday_said("confirm kar dijiye", "please confirm", "कन्फ़र्म कर दीजिए",
                                   "could you please confirm", "confirm kar sakte")

    # -- opening
    if not st.friday:
        if b.approved_terms:
            return tn.say(
                tn.t(en=f"We spoke a little while ago about {b.goal[:1].lower() + b.goal[1:]}. "
                        f"{tn.name} has approved {b.approved_terms}. "
                        + _confirm_text(tn, b.approved_terms),
                     hinglish=f"Abhi thodi der pehle baat hui thi. {tn.name} ji ne "
                              f"{b.approved_terms} confirm kiya hai. "
                              + _confirm_text(tn, b.approved_terms)),
                commits_booking=True)
        return tn.say(_ask_line(tn))

    # -- confirmation (call-back with approved terms, or approved on this call)
    if commit_ok:
        terms = b.approved_terms or (approved.text if approved else "")
        if not asked_confirm:
            return tn.say(_confirm_text(tn, terms), commits_booking=True)
        if reply and is_yes(reply) and not has_any(reply, ("full", "not available", "nahi")):
            return tn.hangup(tn.t(en="Thank you! You'll get a confirmation message. Have a good day.",
                                  hinglish="Bahut shukriya ji! Confirmation message aa jayega."),
                             CallOutcome.SUCCESS,
                             collected=[KV(key="confirmed_terms", value=terms)])
        if reply and (is_no(reply) or has_any(reply, ("full", "gone", "nahi hai", "not "
                                                                                 "available"))):
            if st.slots:
                return tn.callback({"slot_lost": terms})
            return tn.hangup(tn.t(en="I understand. I'll let them know. Thank you.",
                                  hinglish="Samajh gayi ji, main bata deti hoon. Shukriya."),
                             CallOutcome.DECLINED, collected=[KV(key="slot_lost", value=terms)])
        if not reply:
            return tn.act(CallActionType.WAIT)
        return tn.say(_confirm_text(tn, terms), commits_booking=True)

    # -- nothing on offer yet
    if not st.slots and st.price is None:
        if reply and has_any(reply, ("full", "not available", "no slot", "booked", "closed",
                                     "nahi hai", "khatam", "sorry")):
            if st.friday_said("koi aur", "any other", "another day", "dusra"):
                return tn.hangup(tn.t(en="No problem, thank you for checking.",
                                      hinglish="Koi baat nahi ji, check karne ke liye shukriya."),
                                 CallOutcome.DECLINED,
                                 collected=[KV(key="reason", value=reply[:120])])
            return tn.say(tn.t(en="I see. Is any other day or time available this week?",
                               hinglish="Achha. Is hafte koi aur din ya time mil sakta hai?"))
        if st.friday_count(*_ASK_MARKERS) >= 2:
            return _wrap_up(tn)
        return tn.say(_ask_line(tn))

    # -- price & inclusions & negotiation
    if st.price is None and not st.friday_said("price", "kitna", "charge", "cost", "fees",
                                               "rate"):
        return tn.say(tn.t(en="And what would the price be, including everything?",
                           hinglish="Aur price kitna hoga, sab milake?",
                           hi="और प्राइस कितना होगा, सब मिलाके?"))
    neg = _negotiate(tn)
    if neg is not None:
        return neg
    over_budget = b.budget and b.budget.max_inr and st.price and st.price > b.budget.max_inr

    # -- delegated decision within limits
    if b.delegation.granted and not over_budget:
        slot = _delegated_slot(tn)
        if slot is not None:
            terms = _terms(tn, slot)
            if not asked_confirm:
                return tn.say(_confirm_text(tn, terms), commits_booking=True,
                              collected=[KV(key="delegated_choice", value=terms)])
            if reply and is_yes(reply):
                return tn.hangup(tn.t(en="Thank you! Have a good day.",
                                      hinglish="Bahut shukriya ji!"),
                                 CallOutcome.SUCCESS,
                                 collected=[KV(key="confirmed_terms", value=terms),
                                            KV(key="delegated", value="true")])

    # -- opt-in hold-then-callback: ask the owner mid-call first
    if b.approval.mode == ApprovalMode.HOLD_THEN_CALLBACK and not st.friday_said(
            "checking with", "confirm kar rahi", "check kar rahi") and st.slots:
        opts = [f"{s}{', ' + format_inr(st.price) if st.price else ''}" for s in st.slots[:2]]
        opts.append("None of these")
        return tn.act(CallActionType.ASK_USER, tn.t(
            en=f"One moment please, I'm checking with {tn.name}.",
            hinglish=f"Ek minute ji, main {tn.name} ji se confirm kar rahi hoon."),
            question=QuestionOut(text=f"{b.target.name}: {', '.join(st.slots[:3])}"
                                      f"{' at ' + format_inr(st.price) if st.price else ''}. "
                                      f"Book which?",
                                 purpose=QuestionPurpose.APPROVE_BOOKING, options=opts))

    # -- default: call-back route (ask to hold, then end)
    if not st.friday_said("hold", "rakh sakte", "रख सकते"):
        slot_txt = st.slots[0] if len(st.slots) == 1 else "the slot" if tn.lang == Language.EN \
            else "slot"
        if len(st.slots) > 1:
            slot_txt = " / ".join(st.slots[:2])
        return tn.say(tn.t(
            en=f"Thank you. I'll confirm with {tn.name} and call you back in 10-15 minutes. "
               f"Could you hold {slot_txt} till then?",
            hinglish=f"Shukriya ji. Main {tn.name} ji se confirm karke 10-15 minute mein call back "
                     f"karti hoon. Tab tak {slot_txt} hold kar sakte hain?",
            hi=f"शुक्रिया जी। मैं {tn.name} जी से कन्फ़र्म करके 10-15 मिनट में कॉल बैक करती हूँ। "
               f"तब तक {slot_txt} रख सकते हैं?"))
    if not reply:
        return tn.act(CallActionType.WAIT)
    return tn.callback(pre="")


_ASK_MARKERS = ("slots", "slot", "available", "chahiye", "calling to", "call kar rahi")


def _negotiate(tn: Turn) -> CallActionOut | None:
    st, b = tn.st, tn.b
    n = b.negotiation
    may = (b.template.may_negotiate if b.template else True) and n.enabled and n.may_ask_discount
    if not may or st.price is None:
        return None
    target = (b.budget.target_inr if b.budget else None)
    ceiling = n.walk_away_above_inr or (b.budget.max_inr if b.budget else None)
    if b.api_offer and b.api_offer.rate_per_night_inr:
        ceiling = ceiling or b.api_offer.rate_per_night_inr
    goal_price = target or ceiling
    if goal_price is None or st.price <= goal_price:
        return None
    rounds = st.friday_count("discount", "best price", "kam kar", "could you do", "can you do",
                             "kar sakte hain kya")
    if rounds >= n.max_rounds:
        return None
    ask = target if target and st.price > target else ceiling
    if rounds == 0:
        comp = None
        if n.may_cite_competing_quotes and b.competing_quotes:
            cq = min((q for q in b.competing_quotes if q.amount_inr), key=lambda q: q.amount_inr,
                     default=None)
            if cq is not None and cq.amount_inr and cq.amount_inr < st.price:
                comp = cq
        if comp is not None:
            return tn.say(tn.t(
                en=f"Another place quoted {format_inr(comp.amount_inr)}. Could you do "
                   f"{format_inr(ask)}?",
                hinglish=f"Ek aur jagah ne {format_inr(comp.amount_inr)} quote kiya hai. Aap "
                         f"{format_inr(ask)} mein kar sakte hain kya?"))
        if b.api_offer and b.api_offer.rate_per_night_inr:
            return tn.say(tn.t(
                en=f"Since it's a direct booking, could you do {format_inr(ask)} a night? "
                   f"Online it's {format_inr(b.api_offer.rate_per_night_inr)}.",
                hinglish=f"Direct booking hai, toh {format_inr(ask)} per night kar sakte hain "
                         f"kya? Online {format_inr(b.api_offer.rate_per_night_inr)} hai."))
        return tn.say(tn.t(en=f"Could you do {format_inr(ask)}? That would really help.",
                           hinglish=f"Thoda kam kar sakte hain kya? {format_inr(ask)} mein ho "
                                    f"jayega?"))
    if n.may_ask_package_deal and rounds == 1 and ceiling and st.price > ceiling:
        return tn.say(tn.t(en="Is that your best price? Anything included, like the visit charge?",
                           hinglish="Yeh aapka best price hai? Visit charge waive ho sakta hai "
                                    "kya?"))
    return None


def _quote(tn: Turn) -> CallActionOut:
    """QUOTE / DISCOVERY children: collect a comparable quote, negotiate, never commit."""
    st = tn.st
    if not st.friday:
        return tn.say(tn.t(en=f"I'm calling for {tn.name}: {tn.b.goal}. What would it cost, and "
                              f"when can you do it?",
                           hinglish=f"{tn.name} ji ke liye call kar rahi hoon: {tn.b.goal}. Kitna "
                                    f"lagega aur kab kar sakte hain?"))
    if st.price is None:
        if st.friday_count("cost", "lagega", "price") >= 2:
            return _wrap_up(tn)
        return tn.say(tn.t(en="What would the total price be?",
                           hinglish="Total price kitna hoga?"))
    if not st.friday_said("include", "included", "shaamil"):
        return tn.say(tn.t(en="What does that include?", hinglish="Isme kya kya include hai?"))
    neg = _negotiate(tn)
    if neg is not None:
        return neg
    if not st.slots and not st.friday_said("when", "kab", "slot"):
        return tn.say(tn.t(en="And when could you do it?", hinglish="Aur kab kar sakte hain?"))
    if not st.friday_said("hold", "rakh sakte"):
        return tn.say(tn.t(en=f"Thank you. I'll share this with {tn.name} and get back to you. "
                              f"Could you hold the slot for an hour?",
                           hinglish=f"Shukriya ji. Main {tn.name} ji ko bata ke aapko batati hoon. "
                                    f"Ek ghante ke liye slot hold kar sakte hain?"))
    if not st.reply_text():
        return tn.act(CallActionType.WAIT)
    held = st.after_friday_said("hold", "rakh sakte")
    return tn.hangup(tn.t(en="Thank you, I'll get back to you soon.",
                          hinglish="Theek hai ji, shukriya. Jaldi batati hoon."),
                     CallOutcome.SUCCESS,
                     collected=[KV(key="held", value="yes" if affirmative(held) else "no")])


# =============================================================================== info flows


def _questions(tn: Turn) -> list[str]:
    b = tn.b
    return list(b.questions or (b.template.default_questions if b.template else []))[:5]


def _enquiry(tn: Turn) -> CallActionOut:
    st, b = tn.st, tn.b
    qs = _questions(tn) or [b.goal]
    asked = [q for q in qs if st.friday_has(q[:24])]
    collected = []
    for q in asked:
        ans = st.after_friday_has(q[:24])
        if ans:
            collected.append(KV(key=q, value=ans[:160]))
    reply = st.reply_text()
    if b.task_type == TaskType.STOCK_HUNT and asked and reply:
        first = st.after_friday_has(qs[0][:24])
        if first and (has_any(first, ("out of stock", "nahi hai", "not available", "khatam",
                                      "nahi", "no", "illa", "don't have", "dont have"))
                      and not has_any(first, ("hai ji", "yes", "available hai", "haan"))):
            return tn.hangup(tn.t(en="Okay, thank you for checking.",
                                  hinglish="Theek hai ji, check karne ke liye shukriya."),
                             CallOutcome.DECLINED, collected=collected +
                             [KV(key="in_stock", value="no")])
    remaining = [q for q in qs if q not in asked]
    if not st.friday:
        lead = tn.t(en=f"I'm calling for {tn.name}. ", hinglish=f"{tn.name} ji ke liye ek "
                                                               f"jaankari chahiye thi. ")
        return tn.say(lead + remaining[0])
    if asked and not reply:
        return tn.act(CallActionType.WAIT)
    if remaining:
        return tn.say(remaining[0], collected=collected)
    if b.task_type == TaskType.STOCK_HUNT:
        collected.append(KV(key="in_stock", value="yes"))
    answered = sum(1 for kv in collected if kv.value and not has_any(
        kv.value, ("pata nahi", "don't know", "dont know", "no idea")))
    return tn.hangup(tn.t(en="Thank you so much, that's all I needed.",
                          hinglish="Bahut shukriya ji, bas itna hi jaanna tha."),
                     CallOutcome.SUCCESS if answered else CallOutcome.PARTIAL,
                     collected=collected)


def _notify(tn: Turn) -> CallActionOut:
    """RECONFIRM / RUNNING_LATE."""
    st, b = tn.st, tn.b
    reply = st.reply_text()
    ref = b.reference or b.approved_terms
    if not st.friday:
        if b.task_type == TaskType.RECONFIRM:
            return tn.say(tn.t(
                en=f"I'm calling to reconfirm {tn.who}'s booking{' (' + ref + ')' if ref else ''}"
                   f" - {b.goal}. Is it still on?",
                hinglish=f"{tn.who} ki booking{' (' + ref + ')' if ref else ''} reconfirm karni "
                         f"thi - {b.goal}. Kya booking pakki hai?"))
        return tn.say(tn.t(
            en=f"{b.goal}. Will the slot still be held?",
            hinglish=f"{b.goal}. Kya slot hold rahega?"))
    if not reply:
        return tn.act(CallActionType.WAIT)
    if st.slots and has_any(reply, ("instead", "change", "shift", "ya", "or", "available")) and \
            not is_yes(reply):
        return tn.callback({"new_slot_offered": ", ".join(st.slots)})
    if is_yes(reply) or has_any(reply, ("confirmed", "on hai", "pakka", "held", "aa jaiye",
                                        "theek hai", "no problem")):
        key = "reconfirmed" if b.task_type == TaskType.RECONFIRM else "slot_held"
        return tn.hangup(tn.t(en="Thank you, noted.", hinglish="Shukriya ji, note kar liya."),
                         CallOutcome.SUCCESS, collected=[KV(key=key, value="yes"),
                                                         KV(key="business_said", value=reply[:160])])
    return tn.hangup(tn.t(en=f"Thank you, I'll let {tn.name} know.",
                          hinglish=f"Shukriya ji, main {tn.name} ji ko bata deti hoon."),
                     CallOutcome.PARTIAL, collected=[KV(key="business_said", value=reply[:160])])


def _cancel(tn: Turn) -> CallActionOut:
    st, b = tn.st, tn.b
    reply = st.reply_text()
    if not st.friday:
        ref = f" ({b.reference})" if b.reference else ""
        return tn.say(tn.t(en=f"I'm calling to cancel {tn.who}'s booking{ref}: {b.goal}.",
                           hinglish=f"{tn.who} ki booking{ref} cancel karni thi: {b.goal}."))
    if not reply:
        return tn.act(CallActionType.WAIT)
    if st.price is not None or has_any(reply, ("charge", "fee", "penalty", "deduct", "kat")):
        return tn.callback({"cancellation_fee": reply[:120]})
    if is_yes(reply) or has_any(reply, ("cancelled", "cancel kar", "ho gaya", "done")):
        return tn.hangup(tn.t(en="Thank you for your help.", hinglish="Shukriya ji."),
                         CallOutcome.SUCCESS, collected=[KV(key="cancelled", value="yes")])
    if st.friday_count("cancel") >= 2:
        return tn.hangup(tn.t(en="Thank you, I'll check with them.",
                              hinglish="Shukriya ji, main baat karke batati hoon."),
                         CallOutcome.PARTIAL, collected=[KV(key="business_said",
                                                            value=reply[:160])])
    return tn.say(tn.t(en="Could you please cancel it? Is there any charge?",
                       hinglish="Kya aap please cancel kar denge? Koi charge toh nahi?"))


def _coordination(tn: Turn) -> CallActionOut:
    """SERVICE_COORDINATION (ETA / chase) and COMPLAINT (remedy + date)."""
    st, b = tn.st, tn.b
    reply = st.reply_text()
    complaint = b.task_type == TaskType.COMPLAINT
    if not st.friday:
        if complaint:
            return tn.say(tn.t(en=f"I'm calling for {tn.name} about a problem: {b.goal}. "
                                  f"What can you do to fix it, and by when?",
                               hinglish=f"{tn.name} ji ki taraf se ek problem ke baare mein call "
                                        f"kiya hai: {b.goal}. Aap ise kaise theek karenge, aur "
                                        f"kab tak?"))
        return tn.say(tn.t(en=f"I'm calling for {tn.name} about the visit - {b.goal}. When "
                              f"will the technician reach?",
                           hinglish=f"{tn.name} ji ki taraf se visit ke baare mein - {b.goal}. "
                                    f"Technician kab tak pahunchenge?"))
    if not reply:
        return tn.act(CallActionType.WAIT)
    if st.price is not None and not complaint:
        return tn.callback({"revised_price": reply[:120]})
    promised, text = find_promise(reply, st.started)
    has_time = bool(st.slots) or promised is not None or bool(re.search(
        r"\d+\s*(min|minute|ghante|hour)", reply))
    if has_time or (complaint and has_any(reply, ("refund", "redo", "replace", "free", "dobara",
                                                   "discount", "theek kar"))):
        key = "remedy" if complaint else "eta"
        return tn.hangup(tn.t(en=f"Thank you, I'll let {tn.name} know.",
                              hinglish=f"Shukriya ji, {tn.name} ji ko bata deti hoon."),
                         CallOutcome.SUCCESS,
                         collected=[KV(key=key, value=reply[:160])] +
                         ([KV(key="promised", value=text)] if text else []))
    if len(st.friday) >= 3 or (complaint and has_any(reply, ("no", "nahi", "can't", "won't"))
                               and st.friday_count("remedy", "theek", "fix") >= 1
                               and len(st.friday) >= 2):
        return tn.hangup(tn.t(en=f"Okay, I'll let {tn.name} know. Thank you.",
                              hinglish=f"Theek hai ji, {tn.name} ji ko bata deti hoon."),
                         CallOutcome.DECLINED if complaint else CallOutcome.PARTIAL,
                         collected=[KV(key="business_said", value=reply[:160])])
    return tn.say(tn.t(en="Could you give me a definite time?",
                       hinglish="Koi pakka time bata sakte hain?"))


# =============================================================================== customer care


def _care(tn: Turn) -> CallActionOut:
    st, b = tn.st, tn.b
    texts = [t.text for t in st.callee if not is_ivr(t.text) and not is_hold(t.text)]
    human = " ".join(texts)
    ticket = find_ticket(human)
    agent = None
    for txt in texts:
        agent = find_agent(txt) or agent
    promised, promised_text = find_promise(human, st.started)
    asked_sup = st.friday_said("supervisor", "escalate", "senior")
    level = 2 if asked_sup and (has_any(norm(human), ("supervisor", "team lead", "senior",
                                                      "manager")) or any(
        "joined" in norm(s.text) for s in st.system)) else 1
    care = CareOut(ticket_number=ticket, agent_name=agent,
                   promised_date=promised.isoformat() if promised else None,
                   promised_text=promised_text, escalation_level=level, ivr_path=_ivr_path(st))
    reply = st.reply_text()
    if not texts:
        return tn.act(CallActionType.WAIT, care=care)
    if not st.friday or not st.friday_said("calling", "call kar rahi", "issue", "problem",
                                           "complaint", "refund"):
        ref = f" Reference: {b.reference}." if b.reference else ""
        return tn.say(tn.t(en=f"I'm calling for {tn.name}: {b.goal}.{ref} Could you help?",
                           hinglish=f"{tn.name} ji ki taraf se call kar rahi hoon: {b.goal}.{ref} "
                                    f"Aap help kar sakti hain?"), care=care)
    # identifier asked?
    if has_any(reply, ("account number", "registered mobile", "registered number", "customer id",
                       "consumer number", "order id", "number bataiye", "your number",
                       "account id", "policy number")) and not ticket:
        ident = _identifier_for(b, reply)
        if ident is not None:
            return tn.say(tn.t(en=f"Sure, it's {ident.value}.", hinglish=f"Ji, {ident.value}."),
                          care=care)
        return tn.say(tn.t(en=f"I don't have that detail approved for this call. Could you "
                              f"raise the request and share a ticket number? {tn.name} can "
                              f"share it later.",
                           hinglish=f"Yeh detail abhi share karne ki permission nahi hai. Aap "
                                    f"request raise karke ticket number de sakti hain? {tn.name} ji "
                                    f"baad mein de denge."), care=care)
    if ticket:
        if not st.friday_said("note kar liya", "noted the ticket", "ticket number note"):
            when = f", {promised_text}" if promised_text else ""
            return tn.say(tn.t(en=f"Let me confirm: I've noted the ticket number{when}. Is that "
                                  f"right?",
                               hinglish=f"Confirm kar leti hoon: ticket number note kar liya"
                                        f"{when}. Sahi hai?"), care=care)
        care.resolved = has_any(norm(human), ("resolved", "done", "credited", "processed",
                                              "ho gaya"))
        return tn.hangup(tn.t(en="Thank you so much for your help.",
                              hinglish="Bahut shukriya aapki help ke liye."),
                         CallOutcome.SUCCESS, care=care,
                         collected=[KV(key="ticket", value=ticket)] +
                         ([KV(key="agent", value=agent)] if agent else []))
    if reply and has_any(reply, CANT_RESOLVE) and not asked_sup:
        return tn.say(tn.t(en="I understand. Could you please escalate this to a supervisor?",
                           hinglish="Samajh sakti hoon. Kya aap ise supervisor ko escalate kar "
                                    "sakti hain?"), care=care)
    if len(st.friday) >= 6:
        return tn.hangup(tn.t(en="Thank you. I'll follow up later.",
                              hinglish="Shukriya, main baad mein follow up karungi."),
                         CallOutcome.PARTIAL, care=care)
    if not reply:
        return tn.act(CallActionType.WAIT, care=care)
    return tn.say(tn.t(en="Could you share the ticket or complaint number, and by when it will be "
                          "resolved?",
                       hinglish="Kya aap complaint ya ticket number de sakti hain, aur kab tak "
                                "resolve hoga?"), care=care)


# =============================================================================== wellbeing


_CHECKIN_QS = [
    ("medicine", "Have you taken your medicines today?", "Aaj ki dawai le li aapne?",
     "आज की दवाई ले ली आपने?"),
    ("feeling", "How are you feeling?", "Tabiyat kaisi hai, sab theek?",
     "तबीयत कैसी है, सब ठीक?"),
    ("food_sleep", "Did you eat and sleep well?", "Khana aur neend theek ho rahe hain?",
     "खाना और नींद ठीक हो रहे हैं?"),
    ("needs", "Do you need anything at home?", "Ghar ke liye kuch chahiye?",
     "घर के लिए कुछ चाहिए?"),
]


def _wellbeing(tn: Turn) -> CallActionOut:
    st = tn.st
    name = tn.name
    all_said = norm(st.callee_text())
    collected: list[KV] = []
    for key, en, hing, hi in _CHECKIN_QS:
        ans = st.after_friday_has(en[:18], hing[:14], hi[:10])
        if ans:
            collected.append(KV(key=key, value=ans[:160]))
    if has_any(all_said, MED_SKIPPED):
        collected.append(KV(key="medicine_taken", value="no"))
    distress = has_any(all_said, DISTRESS)
    reply = st.reply_text()
    if has_any(reply, ("stop calling", "mat karna call", "don't call tomorrow",
                       "kal call mat", "call mat karo")):
        return tn.hangup(tn.t(en=f"Of course. I'll let {name} know. Take care!",
                              hinglish=f"Ji zaroor, main {name} ko bata dungi. Apna khayal rakhiye!"),
                         CallOutcome.SUCCESS, collected=collected +
                         [KV(key="stop_request", value=reply[:120])])
    if distress and not st.friday_said("112", "108"):
        alert = next((t.text for t in st.callee if has_any(norm(t.text), DISTRESS)), reply)
        return tn.hangup(tn.t(
            en=f"I'm sorry to hear that. I'm telling {name} right away. If it gets worse, "
               f"please call 112 or 108. Take care.",
            hinglish=f"Yeh sunke dukh hua. Main abhi {name} ko bata rahi hoon. Agar takleef "
                     f"badhe toh 112 ya 108 pe call kariye. Apna khayal rakhiye.",
            hi=f"यह सुनकर दुख हुआ। मैं अभी {name} को बता रही हूँ। तकलीफ़ बढ़े तो 112 या 108 पे "
               f"कॉल कीजिए।"),
            CallOutcome.SUCCESS, collected=collected + [KV(key="alert", value=alert[:200])])
    if has_any(reply, ("kaunsi dawai", "which medicine", "should i take", "kitni dawai",
                       "doctor ko", "kya karun")):
        return tn.say(tn.t(en=f"I'm not a doctor, so I'll pass this to {name} right away.",
                           hinglish=f"Main doctor nahi hoon, yeh main {name} ko turant bata dungi."),
                      collected=collected)
    asked = [k for k, en, hing, hi in _CHECKIN_QS if st.friday_has(en[:18], hing[:14], hi[:10])]
    if asked and not reply:
        return tn.act(CallActionType.WAIT, collected=collected)
    for key, en, hing, hi in _CHECKIN_QS:
        if key not in asked:
            lead = ""
            if not st.friday:
                lead = tn.t(en=f"{name} asked me to check on you. ",
                            hinglish=f"{name} ne aapka haal-chaal poochne ko kaha tha. ",
                            hi=f"{name} ने आपका हाल-चाल पूछने को कहा था। ")
            return tn.say(lead + tn.t(en=en, hinglish=hing, hi=hi), collected=collected)
    return tn.hangup(tn.t(en=f"Lovely talking to you. I'll tell {name} everything's okay. "
                             f"Take care!",
                          hinglish=f"Aapse baat karke achha laga. {name} ko bata dungi. Apna "
                                   f"khayal rakhiye!",
                          hi=f"आपसे बात करके अच्छा लगा। {name} को बता दूँगी। अपना ख़याल रखिए!"),
                     CallOutcome.SUCCESS, collected=collected)


def _warm_transfer(tn: Turn) -> CallActionOut:
    st = tn.st
    if not st.friday:
        return tn.say(_ask_line(tn))
    if st.reply_text() and tn.b.user_phone:
        return tn.act(CallActionType.BRIDGE_USER, tn.t(
            en=f"Thank you. I'm connecting {tn.name} to you now, one moment.",
            hinglish=f"Shukriya ji. Main abhi {tn.name} ji ko call pe jod rahi hoon, ek minute."),
            leave_after_bridge=True)
    return tn.act(CallActionType.WAIT)


# =============================================================================== inbound


def _related_for(tn: Turn, ib: InboundContext) -> tuple[RelatedTask | None, bool]:
    """(chosen related task, asked-which-already)."""
    if ib.matched_task_id:
        return next((r for r in ib.related if r.task_id == ib.matched_task_id), None), False
    if len(ib.related) == 1:
        return ib.related[0], False
    st = tn.st
    asked = st.friday_said("ke baare mein hai ya", "is this about", "kis booking", "which one")
    if not asked:
        return None, False
    ans = st.after_friday_said("ke baare mein hai ya", "is this about", "kis booking",
                               "which one")
    if not ans:
        return None, True
    for r in ib.related:
        words = [w for w in re.findall(r"[a-z]{3,}", norm(r.label + " " + (r.beneficiary_name or
                                                                           "")))]
        if any(w in ans for w in words):
            return r, True
    for i, words in enumerate((("first", "pehla", "pehle"), ("second", "dusra", "doosra"))):
        if has_any(ans, words) and i < len(ib.related):
            return ib.related[i], True
    return None, True


def _greeting(tn: Turn, ib: InboundContext, rel: RelatedTask | None) -> str:
    who = rel.beneficiary_name if rel and rel.beneficiary_name else tn.name
    named = ib.caller_matches_business
    about = rel.label if rel else ""
    when_txt = ""
    if rel and rel.last_quote and rel.last_quote.available_slots:
        when_txt = f" ({', '.join(rel.last_quote.available_slots[:2])})"
    if ib.kind == "missed_call":
        return tn.t(
            en=("Hello, I'm Friday, an AI assistant. We got a missed call from this number. "
                + (f"We had called you earlier on behalf of {who} about {about}{when_txt}. "
                   if named and rel else "")),
            hinglish=("Namaste, main Friday hoon, ek AI assistant. Is number se missed call aaya "
                      "tha. " + (f"Humne pehle {who} ji ki taraf se {about}{when_txt} ke liye "
                                 f"call kiya tha. " if named and rel else "")))
    return tn.t(
        en=("Hi, this is Friday, an AI assistant. Thanks for calling back. "
            + (f"We called you earlier on behalf of {who} about {about}{when_txt}. "
               if named and rel else "")),
        hinglish=("Namaste, main Friday hoon, ek AI assistant. Call back karne ke liye shukriya. "
                  + (f"Humne pehle {who} ji ki taraf se {about}{when_txt} ke liye call kiya tha. "
                     if named and rel else "")))


def _inbound(tn: Turn, ib: InboundContext) -> CallActionOut | None:
    st = tn.st
    reply = st.reply_text()
    lt = st.last_text()
    # never reveal user details to unverified / unknown callers
    asks_details = has_any(lt, ("address", "phone number", "his number", "her number",
                                "client ka", "kiska", "who is your client", "customer ka naam",
                                "unka number", "unka address", "details do"))
    if ib.is_unknown:
        return _take_message(tn, asks_details)
    if asks_details and not ib.caller_matches_business:
        return tn.say(tn.t(en="I'm sorry, I can't share anyone's details on this call. I can "
                              "pass on a message.",
                           hinglish="Maaf kijiye, main is call pe kisi ki details share nahi kar "
                                    "sakti. Aapka message aage pahuncha sakti hoon."))
    rel, asked_which = _related_for(tn, ib)
    if rel is None:
        if not asked_which:
            labels = [r.label for r in ib.related[:3]]
            q = tn.t(en=f"Is this about the {' or the '.join(labels)}?",
                     hinglish=f"Kya yeh {' ke baare mein hai ya '.join(labels)} ke baare mein hai?")
            if not st.friday:
                return tn.say(_greeting(tn, ib, None) + q)
            return tn.say(q)
        if not reply:
            return tn.act(CallActionType.WAIT)
        if st.friday_count("ke baare mein hai ya", "is this about") >= 2:
            return _take_message(tn, False)
        labels = [r.label for r in ib.related[:3]]
        return tn.say(tn.t(en=f"Sorry, which one - {' or '.join(labels)}?",
                           hinglish=f"Maaf kijiye, kaunsa - {' ya '.join(labels)}?"))
    collected = [KV(key="matched_task_id", value=rel.task_id)]
    first = not st.friday
    greet = _greeting(tn, ib, rel) if first else ""

    # (a) need already met elsewhere / cancelled / stock found: close the loop politely
    if rel.resolution in CLOSED_ELSEWHERE:
        who = rel.beneficiary_name or tn.name
        close = tn.t(
            en=f"Thank you for calling back - {who}'s requirement has been taken care of, so we "
               f"won't need it this time. Have a good day.",
            hinglish=f"Call back karne ke liye shukriya - {who} ji ki zaroorat poori ho gayi hai, "
                     f"toh is baar zaroorat nahi padegi. Aapka din achha rahe.",
            hi=f"कॉल बैक करने के लिए शुक्रिया - {who} जी की ज़रूरत पूरी हो गई है, तो इस बार "
               f"ज़रूरत नहीं पड़ेगी। आपका दिन अच्छा रहे।")
        q = tn.quote(notes="offer made after the task was resolved")
        if q is not None:
            return tn.hangup(greet + close, CallOutcome.PARTIAL, quote=q,
                             collected=collected + [KV(key="late_offer", value="true"),
                                                    KV(key="closed_loop", value="true")])
        return tn.hangup(greet + close, CallOutcome.SUCCESS,
                         collected=collected + [KV(key="closed_loop", value="true")])

    # (b) booked with THIS business: the call is about that booking
    if rel.resolution == "booked_here":
        return _about_booking(tn, rel, greet, collected)

    # (c)/(31) task still open: resume it with the related task's goal
    if first:
        prior = f"{rel.discussed} " if rel.discussed else ""
        return tn.say(greet + tn.t(en=f"{prior}Do you have an update for us?",
                                   hinglish=f"{prior}Boliye, kya update hai?"),
                      collected=collected)
    working = tn.b.model_copy(update={"task_type": rel.task_type, "goal": rel.goal,
                                      "task_id": rel.task_id,
                                      "approved_terms": rel.approved_terms or
                                      tn.b.approved_terms})
    if not ib.caller_matches_business:
        working = working.model_copy(update={"shareable_details": {}})
    sub = Turn(read_state(working, st.transcript, st.answers), None)
    sub.lang = tn.lang
    if rel.last_quote and sub.st.price is None and rel.last_quote.amount_inr:
        sub.st.price = rel.last_quote.amount_inr
        sub.st.original_price = rel.last_quote.original_amount_inr or rel.last_quote.amount_inr
    early = _universal(sub, lt) if lt else None
    action = early or _flow(sub)
    action.collected = collected + list(action.collected)
    return action


def _about_booking(tn: Turn, rel: RelatedTask, greet: str, collected: list[KV]
                   ) -> CallActionOut:
    st = tn.st
    reply = st.reply_text()
    details = rel.booking_details or rel.approved_terms or rel.label
    if not st.friday:
        return tn.say(greet + tn.t(en=f"This is about the booking for {details}. How can I help?",
                                   hinglish=f"Yeh {details} wali booking ke baare mein hai na? "
                                            f"Boliye."),
                      collected=collected)
    if not reply:
        return tn.act(CallActionType.WAIT, collected=collected)
    if has_any(reply, PAYMENT_WORDS):
        return tn.callback({"advance_requested": reply[:120], **_kv(collected)},
                           pre=tn.t(en="I can't agree to any payment on this call. ",
                                    hinglish="Payment ke baare mein main abhi haan nahi bol "
                                             "sakti. "))
    lower_price = st.price is not None and rel.last_quote and rel.last_quote.amount_inr and \
        st.price < rel.last_quote.amount_inr
    if lower_price or has_any(reply, ("offer", "discount", "cheaper", "sasta", "kam mein")):
        return tn.hangup(tn.t(en=f"Thank you, I'll mention it to {tn.name}. The current booking "
                                 f"stays as it is for now.",
                              hinglish=f"Shukriya ji, {tn.name} ji ko bata dungi. Abhi booking "
                                       f"jaisi hai waisi rahegi."),
                         CallOutcome.PARTIAL,
                         quote=tn.quote(notes="better offer after booking - not accepted"),
                         collected=collected + [KV(key="better_offer", value=reply[:160])])
    if has_any(reply, ("reschedule", "shift", "change", "postpone", "prepone", "instead",
                       "badal", "nahi ho payega", "can't make", "not possible at")) or (
            st.slots and not is_yes(reply)):
        return tn.callback({"change_request": reply[:160], **_kv(collected)})
    if has_any(reply, ("cancel", "cancelled", "band rahega", "closed tomorrow")):
        return tn.hangup(tn.t(en=f"Understood, I'll let {tn.name} know right away. Thank you.",
                              hinglish=f"Samajh gayi ji, {tn.name} ji ko turant bata deti hoon."),
                         CallOutcome.PARTIAL,
                         collected=collected + [KV(key="business_cancelled", value=reply[:160])])
    if has_any(reply, ("ready", "pickup", "pick up", "le jaiye", "delivered", "aa gaya",
                       "taiyaar")):
        return tn.hangup(tn.t(en=f"Great, I'll tell {tn.name}. Thank you!",
                              hinglish=f"Badhiya, {tn.name} ji ko bata deti hoon. Shukriya!"),
                         CallOutcome.SUCCESS,
                         collected=collected + [KV(key="ready", value=reply[:160])])
    if has_any(reply, ("confirm", "aa rahe", "coming", "still on", "pakka", "reconfirm")) or \
            is_yes(reply):
        return tn.hangup(tn.t(en=f"Yes, the booking for {details} stands. Thank you for checking!",
                              hinglish=f"Ji haan, {details} wali booking pakki hai. Check karne ke "
                                       f"liye shukriya!"),
                         CallOutcome.SUCCESS,
                         collected=collected + [KV(key="reconfirmed", value="yes")])
    return tn.hangup(tn.t(en=f"Thank you, I'll pass this on to {tn.name}.",
                          hinglish=f"Shukriya ji, {tn.name} ji ko bata deti hoon."),
                     CallOutcome.PARTIAL,
                     collected=collected + [KV(key="business_said", value=reply[:160])])


def _kv(items: list[KV]) -> dict[str, str]:
    return {kv.key: kv.value for kv in items}


def _take_message(tn: Turn, asks_details: bool) -> CallActionOut:
    """Unknown caller (E-33): AI greeting, take a message, reveal nothing."""
    st = tn.st
    reply = st.reply_text()
    collected: list[KV] = []
    name_ans = st.after_friday_said("your name", "aapka naam", "naam bata")
    purpose_ans = st.after_friday_said("regarding", "kis silsile", "what is it about",
                                       "kis baare")
    number_ans = st.after_friday_said("call you back on", "kis number pe", "which number")
    if name_ans:
        collected.append(KV(key="caller_name", value=name_ans[:80]))
    if purpose_ans:
        collected.append(KV(key="purpose", value=purpose_ans[:160]))
    if number_ans:
        collected.append(KV(key="callback_number", value=re.sub(r"[^\d+]", "", number_ans)
                            or number_ans[:40]))
    refuse = ""
    if asks_details:
        refuse = tn.t(en="I'm sorry, I can't share anyone's details. ",
                      hinglish="Maaf kijiye, main kisi ki details share nahi kar sakti. ")
    if not st.friday:
        return tn.say(tn.t(en="Hello, this is Friday, an AI assistant. May I know your name and "
                              "what it is regarding? I'll pass on the message.",
                           hinglish="Namaste, main Friday hoon, ek AI assistant. Aapka naam aur "
                                    "kis silsile mein call kiya, bata dijiye - main message aage "
                                    "pahuncha dungi."))
    if not reply:
        return tn.act(CallActionType.WAIT, collected=collected)
    if not name_ans and not st.friday_said("your name", "aapka naam", "naam bata"):
        return tn.say(refuse + tn.t(en="May I have your name?", hinglish="Aapka naam bata "
                                                                         "dijiye?"),
                      collected=collected)
    if not purpose_ans and not st.friday_said("regarding", "kis silsile", "kis baare"):
        return tn.say(refuse + tn.t(en="And what is it regarding?",
                                    hinglish="Aur kis silsile mein call kiya tha?"),
                      collected=collected)
    if not number_ans and not st.friday_said("call you back on", "kis number pe"):
        return tn.say(refuse + tn.t(en="Which number should we call you back on?",
                                    hinglish="Aapko kis number pe call back karein?"),
                      collected=collected)
    if not collected:
        collected.append(KV(key="message", value=reply[:200]))
    return tn.hangup(refuse + tn.t(en="Thank you, I'll pass on your message.",
                                   hinglish="Shukriya, aapka message aage pahuncha dungi."),
                     CallOutcome.SUCCESS,
                     collected=collected + [KV(key="message_taken", value="true")])


__all__ = ["POSITIVE_WORDS", "next_action"]
