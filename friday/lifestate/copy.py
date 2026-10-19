"""ALL user-facing text of the life state module lives here (and only here).

PENDING_FOUNDER_APPROVAL: none of these lines has been approved. Under the hear-before-change rule
they must be sent to the founder (text for WhatsApp, audio sample for any line that is spoken)
and approved before real users see them. Tests assert the structure (a why-clause on every
proactive message), never the exact words, so the words can change freely after review.

Rules the wording follows:
  * short, warm Hinglish; never nagging; no emojis;
  * every PROACTIVE message carries a one-clause reason ("isliye ki ...") and how to stop it;
  * lines only use the kind of an event ("interview"), never an untrusted title;
  * the same why-clause is also available on its own (``why_*``) so tests can check it.
"""

from __future__ import annotations

from datetime import datetime

from friday.core.clock import ist_date, to_ist
from friday.lifestate.models import EventKind

PENDING_FOUNDER_APPROVAL = True

KIND_NOUN: dict[EventKind, str] = {
    EventKind.INTERVIEW: "interview",
    EventKind.MEETING: "meeting",
    EventKind.APPOINTMENT: "appointment",
    EventKind.TRAVEL: "safar",
    EventKind.BILL_DUE: "bill",
    EventKind.PERSONAL: "plan",
    EventKind.OTHER: "event",
}

TOPIC_LABEL: dict[str, str] = {
    "all": "saare reminders aur sawaal",
    "after_event": "event ke baad poochna",
    "before_event": "event se pehle yaad dilana",
    "bill_due": "bill ke reminders",
    "commitment": "yaad dilane wale reminders",
    "morning_brief": "subah ka brief",
}

WEEKDAYS = ["Somvar", "Mangalvar", "Budhvar", "Guruvar", "Shukravar", "Shanivar", "Ravivar"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

STOP_HINT = "Nahi chahiye toh 'mat poocho' bol dena."


# --------------------------------------------------------------------------- formatting helpers
def noun(kind: EventKind) -> str:
    return KIND_NOUN.get(kind, "event")


def topic_label(topic: str) -> str:
    base, _, sub = topic.partition(":")
    label = TOPIC_LABEL.get(base, base)
    return f"{label} ({sub})" if sub else label


def fmt_clock(dt: datetime) -> str:
    """'dopahar 2 baje', 'shaam 6:30 baje', 'raat 12 baje'."""
    t = to_ist(dt)
    h, m = t.hour, t.minute
    if h == 0 and m == 0:
        word, h12 = "raat", 12
    elif 4 <= h < 12:
        word, h12 = "subah", h
    elif 12 <= h < 16:
        word, h12 = "dopahar", h - 12 or 12
    elif 16 <= h < 20:
        word, h12 = "shaam", h - 12
    else:
        word, h12 = "raat", (h - 12) if h > 12 else (h or 12)
    mins = f":{m:02d}" if m else ""
    return f"{word} {h12}{mins} baje"


def fmt_day(dt: datetime, now: datetime) -> str:
    d, today = ist_date(dt), ist_date(now)
    delta = (d - today).days
    if delta == 0:
        return "aaj"
    if delta == 1:
        return "kal"
    if delta == 2:
        return "parso"
    t = to_ist(dt)
    return f"{WEEKDAYS[t.weekday()]} {t.day} {MONTHS[t.month - 1]}"


def fmt_when(dt: datetime, now: datetime) -> str:
    return f"{fmt_day(dt, now)} {fmt_clock(dt)}"


# --------------------------------------------------------------------------- capture (replies)
def confirm_event(kind: EventKind, when: str, *, title: str | None = None) -> str:
    what = noun(kind) if kind != EventKind.OTHER else (title or "event")
    return f"Theek hai, {when} {what} yaad rakh liya. Galat laga toh 'galat' bol do."


def confirm_bill(when: str, title: str | None = None) -> str:
    what = f"{title} ka bill" if title else "bill"
    return f"Theek hai, {what} {when} tak due hai, yaad rakh liya. Galat laga toh 'galat' bol do."


def confirm_commitment(text: str, when: str, repeat_note: str | None = None) -> str:
    extra = f" ({repeat_note})" if repeat_note else ""
    return f"Theek hai, {when} yaad dilaungi: {text}{extra}. Galat laga toh 'galat' bol do."


def clash_note(kind: EventKind, when: str) -> str:
    return f"Dhyaan rahe, us waqt aapka ek aur {noun(kind)} hai ({when})."


def ask_time(what: str) -> str:
    return f"{what} kitne baje hai?"


def ask_date(what: str) -> str:
    return f"{what} kis din hai?"


def ask_am_pm(hour: int) -> str:
    return f"{hour} baje matlab dopahar ya raat?"


def ask_what(when: str) -> str:
    return f"{when} kya hai? Ek line mein bata do."


def ask_past_kal() -> str:
    return "'Kal' matlab beeta hua kal ya aane wala kal? Din bata do."


def ask_unclear() -> str:
    return "Samajh nahi aaya. Kya, kab (din aur time) ek line mein bata do?"


def undo_done() -> str:
    return "Theek hai, hata diya."


def undo_nothing() -> str:
    return "Abhi hatane ke liye kuch nahi mila."


# --------------------------------------------------------------------------- proactive lines
# Every function below returns text that ends with a one-clause reason and the way to stop it.
def why_after_event(kind: EventKind, ended: datetime) -> str:
    return f"Isliye pooch rahi hoon ki aapka {noun(kind)} {fmt_clock(ended)} khatam hua tha"


def after_event(kind: EventKind, ended: datetime) -> str:
    asks = {
        EventKind.INTERVIEW: "Interview kaisa gaya? Kuch yaad rakhna ho toh bata do.",
        EventKind.MEETING: "Meeting kaisi rahi? Koi kaam yaad rakhna ho toh bata do.",
        EventKind.APPOINTMENT: "Appointment kaisa raha? Koi follow-up chahiye toh bata do.",
        EventKind.TRAVEL: "Pahunch gaye? Sab theek?",
    }
    head = asks.get(kind, "Kaisa raha? Kuch yaad rakhna ho toh bata do.")
    return f"{head} {why_after_event(kind, ended)}. {STOP_HINT}"


def why_before_event(kind: EventKind, start: datetime) -> str:
    return f"Isliye bata rahi hoon ki aapka {noun(kind)} {fmt_clock(start)} hai"


def before_event(kind: EventKind, start: datetime, leave_by: datetime | None = None) -> str:
    leave = f" {fmt_clock(leave_by)} tak nikalna hoga." if leave_by else ""
    return (
        f"{noun(kind).capitalize()} {fmt_clock(start)} hai.{leave} "
        f"{why_before_event(kind, start)}. {STOP_HINT}"
    )


def why_bill(due: datetime) -> str:
    return "Isliye yaad dila rahi hoon ki bill ki last date paas hai"


def bill_due(days_left: int, due: datetime, now: datetime, pay_link: str | None = None) -> str:
    when = "aaj" if days_left <= 0 else ("kal" if days_left == 1 else f"{days_left} din mein")
    link = f" Pay karne ka link: {pay_link}" if pay_link else ""
    return f"Ek bill {when} due hai ({fmt_day(due, now)}).{link} {why_bill(due)}. {STOP_HINT}"


def why_commitment() -> str:
    return "Isliye yaad dila rahi hoon ki aapne mujhse kaha tha"


def commitment_due(text: str) -> str:
    return f"Yaad dila rahi hoon: {text}. {why_commitment()}. {STOP_HINT}"


# --------------------------------------------------------------------------- morning brief
def why_brief() -> str:
    return "Ye aaj ke aapke events aur bills ka brief hai, isliye bheja"


def brief(lines: list[str], suggestion: str | None, more: int = 0) -> str:
    body = "\n".join(f"- {ln}" for ln in lines)
    if more > 0:
        body += f"\n- aur {more} cheezein"
    tip = f"\n{suggestion}" if suggestion else ""
    return f"Suprabhat. Aaj:\n{body}{tip}\n({why_brief()}. 'brief band' bolo toh band.)"


def brief_event_line(kind: EventKind, title: str | None, start: datetime) -> str:
    label = title or noun(kind)
    return f"{fmt_clock(start)}: {label}"


def brief_bill_line(days_left: int) -> str:
    return "bill aaj due hai" if days_left <= 0 else f"bill {days_left} din mein due hai"


def brief_commitment_line(text: str, due: datetime) -> str:
    return f"{fmt_clock(due)}: {text}"


def suggest_leave(start: datetime, leave_by: datetime) -> str:
    return f"Suggestion: {fmt_clock(start)} ke liye {fmt_clock(leave_by)} tak nikal jaana."


def suggest_clash() -> str:
    return "Suggestion: aaj do events ek hi time par hain, ek ko aage kar lein?"


def suggest_bill() -> str:
    return "Suggestion: bill aaj nipta do, last date nikal na jaye."


# --------------------------------------------------------------------------- replies and mute
def note_saved() -> str:
    return "Likh liya. Jab chahiye ho yaad dila dungi."


def mute_done(topic: str) -> str:
    return (
        f"Theek hai, ab {topic_label(topic)} nahi bhejungi. "
        "Wapas chahiye toh 'phir se poocho' bolna."
    )


def unmute_done(topic: str) -> str:
    return f"Theek hai, {topic_label(topic)} phir se chalu."


def channel_set(topic: str, channel: str) -> str:
    how = {"voice_note": "voice note", "call": "call", "text": "text message"}[channel]
    return f"Theek hai, {topic_label(topic)} ke liye ab {how} bhejungi. Badalna ho toh bata dena."


def channel_unavailable(channel: str) -> str:
    return "Abhi sirf text message bhej sakti hoon; voice note ya call jaldi."


# --------------------------------------------------------------------------- memory controls
def remember_empty() -> str:
    return "Abhi mujhe aapke din ke baare mein kuch yaad nahi. Bata do toh yaad rakhungi."


def remember_summary(event_lines: list[str], commitment_lines: list[str], topics: list[str]) -> str:
    parts = ["Mujhe ye yaad hai:"]
    if event_lines:
        parts.append("Events:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(event_lines, 1)))
    if commitment_lines:
        parts.append(
            "Reminders:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(commitment_lines, 1))
        )
    if topics:
        parts.append("Band kiye hue: " + ", ".join(topics))
    parts.append("Kuch bhulana ho toh 'bhool jao <naam>' bolo, sab ke liye 'sab delete karo'.")
    return "\n".join(parts)


def forgot(n: int) -> str:
    return f"Theek hai, {n} cheez bhula di." if n == 1 else f"Theek hai, {n} cheezein bhula di."


def forget_none(query: str) -> str:
    return "Is naam ki koi cheez yaad nahi mili."


def forget_ambiguous(candidates: list[str]) -> str:
    opts = "\n".join(f"{i}. {c}" for i, c in enumerate(candidates, 1))
    return f"Kaun si? Thoda aur saaf bolo:\n{opts}"


def delete_all_prompt() -> str:
    return (
        "Aapke din ki saari yaad (events, reminders, notes, settings) hamesha ke liye mita dungi. "
        "Pakka? 'haan, sab mita do' likho."
    )


def delete_all_done() -> str:
    return "Ho gaya. Aapke din ki saari yaad mita di."


def delete_all_cancelled() -> str:
    return "Theek hai, kuch nahi mitaya."


def export_ready() -> str:
    return "Ye aapka poora data hai (file). Ise sirf aap dekh sakte ho."


def edit_done(kind: EventKind, when: str) -> str:
    return f"Theek hai, {noun(kind)} ab {when} hai."


def edit_none() -> str:
    return "Kaun sa event badalna hai, samajh nahi aaya. Naam ke saath bolo."


# --------------------------------------------------------------------------- internal context
# Injected into the front door / live call prompts. Not user-facing; never includes titles,
# notes, locations or people.
def ctx_free() -> str:
    return "free"


def ctx_in_event(kind: EventKind, until: str, protected: bool) -> str:
    tag = " (protected: do not interrupt unless urgent)" if protected else ""
    return f"in event ({kind.value}) until {until}{tag}"


def ctx_travelling(until: str) -> str:
    return f"travelling until {until}"


def ctx_quiet(until: str) -> str:
    return f"quiet hours (sleeping) until {until}"
