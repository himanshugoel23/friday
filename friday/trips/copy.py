# ruff: noqa: E501
"""Every user-facing line of the trip timeline. STATUS: PENDING_FOUNDER_APPROVAL for all of it.

Hear-before-change (CLAUDE.md rule 3): none of this wording reaches a real user until the founder
has approved it; ``FRIDAY_TRIPS_ENABLED`` stays OFF until then. There are NO spoken lines in this
file. The hotel-call questions (``HOTEL_CALL_QUESTIONS``) are what the call agent would ask the
hotel: they are PENDING lines too and need an audio sample before any call. Two languages per line:
``hinglish`` (default, Roman) and ``en``; any other language falls back to Hinglish.

Rules the wording follows: short, warm, no emojis, every PROACTIVE message carries a one-clause
reason ("isliye ki ...") and how to stop it; document text is never interpolated except the
cleaned, length-capped values passed to ``t`` (a hotel or trip name is data, never an instruction);
no line claims a flight time that is not in a document or a provider answer; stale data is
labelled with its age; nothing says "booked" (Friday books nothing here).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
PENDING_FOUNDER_APPROVAL = True
LANGS = ("hinglish", "en")
DEFAULT_LANGUAGE = "hinglish"
BUTTON_PREFIX = "trip:"
STOP_HINT = {
    "hinglish": "Nahi chahiye toh 'trip mute' bol dena.",
    "en": "Say 'trip mute' to stop these.",
}

# What the call agent asks the hotel (PENDING; data for TaskSpec.questions, not a script).
HOTEL_CALL_QUESTIONS: dict[str, list[str]] = {
    "hinglish": [
        "Booking confirm hai? Naam aur dates sahi hain?",
        "Early check-in mil sakta hai? Kitne baje se?",
        "Hamare pahunchne ka time bata dein; koi special request note ho jayegi?",
    ],
    "en": [
        "Is the booking confirmed under this name and these dates?",
        "Is early check-in possible, and from what time?",
        "May we note our arrival time and a special request?",
    ],
}

TEXTS: dict[str, dict[str, str]] = {
    "created": {
        "hinglish": "Trip bana di: {title}, {start} se {end}. {n} cheezein jodi. 'meri trip' bologe toh din-ba-din plan dikha dungi.",
        "en": "Trip created: {title}, {start} to {end}. {n} items added. Say 'meri trip' for the day-wise plan.",
    },
    "created.none": {
        "hinglish": "Koi confirmed ticket ya hotel nahi mila. Pehle document bhejkar 'sahi hai' bol do, phir trip bana dungi.",
        "en": "I found no confirmed ticket or hotel. Send the document and confirm it first, then I will build the trip.",
    },
    "no_trip": {
        "hinglish": "Abhi koi trip nahi hai. Ticket ya hotel ki photo bhej do, ya 'nayi trip' bolo.",
        "en": "No trip yet. Send a ticket or hotel photo, or say 'new trip'.",
    },
    "plan.header": {
        "hinglish": "Aapka din-ba-din plan ({start} se {end}):",
        "en": "Your day-wise plan ({start} to {end}):",
    },
    "plan.day": {"hinglish": "{day}:", "en": "{day}:"},
    "plan.leave": {
        "hinglish": "{time} nikalna hai ({mode} {dep} ka hai; {buf} min pehle pahunchna, raaste ka {travel} min)",
        "en": "{time} leave ({mode} departs {dep}; {buf} min buffer, {travel} min to get there)",
    },
    "plan.depart": {
        "hinglish": "{time} {label} {route}",
        "en": "{time} {label} {route}",
    },
    "plan.arrive": {
        "hinglish": "{time} pahunchna: {route}",
        "en": "{time} arrives: {route}",
    },
    "plan.hotel_call": {
        "hinglish": "{time} hotel ko pehle call karna ({hotel}): aap haan bologe tabhi",
        "en": "{time} call the hotel first ({hotel}): only if you say yes",
    },
    "plan.checkin": {
        "hinglish": "{time} {hotel} mein check-in",
        "en": "{time} check-in at {hotel}",
    },
    "plan.checkin.unknown": {
        "hinglish": "{hotel} mein check-in (time document mein nahi hai)",
        "en": "check-in at {hotel} (time not in the document)",
    },
    "plan.checkout": {
        "hinglish": "{time} {hotel} se check-out",
        "en": "{time} check-out from {hotel}",
    },
    "plan.assume.travel": {
        "hinglish": "Maine raaste ka {mins} min maana hai; sahi time bata do ('airport tak 40 min') toh badal dungi.",
        "en": "I assumed {mins} min to get there; tell me the real time ('40 min to the airport') and I will change it.",
    },
    "plan.assume.intl": {
        "hinglish": "Airport pehchana nahi, isliye international wala lamba buffer liya hai.",
        "en": "I did not recognise an airport, so I used the longer international buffer.",
    },
    "plan.assume.tz": {
        "hinglish": "Kuch jagah ka time zone pata nahi, wahan India ka time maana hai.",
        "en": "I did not know some time zones and assumed Indian time there.",
    },
    "plan.pointer": {
        "hinglish": "Ticket aapke Drive mein hai.",
        "en": "The ticket is in your Drive.",
    },
    "nudge.leave_by": {
        "hinglish": "{time} tak nikalna hai: {mode} {dep} ka hai. {assume}Isliye bata rahi hoon ki {buf} min pehle pahunchna aur raaste ka {travel} min lagega. {stop}",
        "en": "Leave by {time}: your {mode} departs {dep}. {assume}Telling you because you need {buf} min there plus {travel} min on the road. {stop}",
    },
    "nudge.leave_by.assume": {
        "hinglish": "(Raaste ka {mins} min maana hai, sahi bata do toh badal dungi.) ",
        "en": "(I assumed {mins} min on the road; tell me the real time and I will change it.) ",
    },
    "nudge.hotel_call": {
        "hinglish": "{hotel} mein {when} check-in hai. Pehle hotel ko call karke booking, early check-in aur aapke pahunchne ka time confirm kar doon? Isliye puch rahi hoon ki check-in par dikkat na aaye. Call se pehle main ek baar aur poochungi. {stop}",
        "en": "Check-in at {hotel} is {when}. Shall I call the hotel first to confirm the booking, early check-in and your arrival time? I am asking so check-in goes smoothly. I will ask once more before the call. {stop}",
    },
    "nudge.hotel_call.nonumber": {
        "hinglish": "Hotel ka number aapke document mein nahi hai, mere paas bhi nahi. Number bhej do, tabhi call kar paungi.",
        "en": "The hotel's number is not in your document and I do not have it. Send me the number and then I can call.",
    },
    "hotel_call.ask_number": {
        "hinglish": "Theek hai. Hotel ka number bhej do (main apne se koi number nahi dhoondhungi).",
        "en": "Okay. Please send the hotel's number (I will not look one up on my own).",
    },
    "hotel_call.queued": {
        "hinglish": "Theek hai, hotel ko call ka plan bana diya. Dial karne se pehle aapse ek baar aur poochungi.",
        "en": "Okay, the hotel call is planned. I will ask you once more before dialling.",
    },
    "hotel_call.bad_number": {
        "hinglish": "Yeh number sahi nahi lag raha. Poora number bhejo, jaise +91 98xxxxxxxx.",
        "en": "That does not look like a valid number. Please send the full number, like +91 98xxxxxxxx.",
    },
    "nudge.cab": {
        "hinglish": "{time} ko {place} se cab chahiye hogi. Booking main nahi karti; yeh link se khud book kar lo: {link}. Isliye yaad dila rahi hoon ki nikalne ka time {time} hai. {stop}",
        "en": "You will need a cab at {time} from {place}. I do not book it; use this link: {link}. Reminding you because you leave at {time}. {stop}",
    },
    "nudge.cab.noaddr": {
        "hinglish": "{time} ko cab chahiye hogi. Pickup kahan se hoga? Address bata do toh ride ka link bana dungi. Booking main nahi karti. {stop}",
        "en": "You will need a cab at {time}. Where is the pickup? Tell me the address and I will make the ride link. I do not book it. {stop}",
    },
    "cab.handoff": {
        "hinglish": "Yeh raha link: {link}. Booking aap khud confirm karna.",
        "en": "Here is the link: {link}. You confirm the booking yourself.",
    },
    "cab.noaddr": {
        "hinglish": "Pehle pickup address bata do, phir link bana dungi.",
        "en": "Tell me the pickup address first and I will make the link.",
    },
    "nudge.checkin": {
        "hinglish": "{hotel} mein check-in {time} se hai. Isliye bata rahi hoon ki aap aaj pahunch rahe hain. {stop}",
        "en": "Check-in at {hotel} is from {time}. Telling you because you arrive today. {stop}",
    },
    "nudge.checkin.unknown": {
        "hinglish": "{hotel} mein aaj check-in hai, par time document mein nahi hai. Hotel se poochna padega. {stop}",
        "en": "You check in at {hotel} today but the time is not in the document. It needs a call to the hotel. {stop}",
    },
    "nudge.checkout": {
        "hinglish": "{hotel} se check-out {time} tak hai. Isliye bata rahi hoon ki aaj aapka last din hai. {stop}",
        "en": "Check-out from {hotel} is by {time}. Telling you because today is your last day there. {stop}",
    },
    "nudge.checkout.unknown": {
        "hinglish": "Aaj {hotel} se check-out hai (time document mein nahi hai). {stop}",
        "en": "You check out of {hotel} today (time not in the document). {stop}",
    },
    "nudge.day_plan": {
        "hinglish": "Aaj ka plan: {lines} Isliye bheja ki aaj aapki trip ka din hai. {stop}",
        "en": "Today's plan: {lines} Sent because today is a trip day. {stop}",
    },
    "nudge.lounge": {
        "hinglish": "Aapke {card} mein {airport} par lounge access ho sakta hai (rule {checked} ko check hua{conf}). Card app par ek baar confirm kar lena. Isliye bataya ki aapki flight {dep} ki hai. {stop}",
        "en": "Your {card} may include lounge access at {airport} (rule checked {checked}{conf}). Please confirm on your card app. Telling you because your flight is {dep}. {stop}",
    },
    "lounge.conf.medium": {"hinglish": "; purana ho sakta hai", "en": "; may be out of date"},
    "lounge.conf.low": {
        "hinglish": "; kaafi purana, zaroor confirm karna",
        "en": "; quite old, please do confirm",
    },
    "watch.delay": {
        "hinglish": "{flight} {mins} min late hai: ab {new_dep} par udegi (pehle {old_dep}). Nikalne ka time ab {leave} hai. {age}Isliye bataya ki flight ka time badla hai. {stop}",
        "en": "{flight} is delayed by {mins} min: it now departs {new_dep} (was {old_dep}). Your leave-by is now {leave}. {age}Telling you because the departure time changed. {stop}",
    },
    "watch.back": {
        "hinglish": "{flight} ab time par hai ({dep}). Nikalne ka time wapas {leave}. {age}{stop}",
        "en": "{flight} is back on time ({dep}). Leave-by is back to {leave}. {age}{stop}",
    },
    "watch.cancelled": {
        "hinglish": "{flight} cancel ho gayi lagti hai. {age}Airline se pakka confirm kar lo. Refund ya naya ticket chahiye toh bolna, main madad karungi. Isliye bataya ki flight ka status badla hai. {stop}",
        "en": "{flight} looks cancelled. {age}Please confirm with the airline. Tell me if you want help with a refund or a new ticket. Telling you because the status changed. {stop}",
    },
    "watch.gate": {
        "hinglish": "{flight}: gate {gate}. {age}{stop}",
        "en": "{flight}: gate {gate}. {age}{stop}",
    },
    "watch.terminal": {
        "hinglish": "{flight}: terminal {terminal}. {age}{stop}",
        "en": "{flight}: terminal {terminal}. {age}{stop}",
    },
    "age.stale": {
        "hinglish": "(Yeh jaankari {mins} min purani hai.) ",
        "en": "(This information is {mins} min old.) ",
    },
    "muted": {
        "hinglish": "Theek hai, is trip ke reminders band. 'trip unmute' bologe toh phir shuru.",
        "en": "Okay, reminders for this trip are off. Say 'trip unmute' to turn them back on.",
    },
    "unmuted": {
        "hinglish": "Reminders phir se chalu.",
        "en": "Reminders are back on.",
    },
    "travel.set": {
        "hinglish": "Theek hai, raaste ka {mins} min. Nikalne ke time naye hisaab se.",
        "en": "Okay, {mins} min on the road. Leave-by times updated.",
    },
    "pickup.set": {
        "hinglish": "Pickup address note kar liya.",
        "en": "Pickup address noted.",
    },
    "task.skipped": {
        "hinglish": "Theek hai, chhod diya.",
        "en": "Okay, skipped.",
    },
    "task.unknown": {
        "hinglish": "Yeh yaad dilana ab nahi mila.",
        "en": "I could not find that reminder any more.",
    },
    "btn.yes": {"hinglish": "Haan", "en": "Yes"},
    "btn.no": {"hinglish": "Nahi", "en": "No"},
    "btn.link": {"hinglish": "Link bhejo", "en": "Send the link"},
}


def lang_of(language: str | None) -> str:
    return language if language in LANGS else DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, **kw: str | int) -> str:
    return TEXTS[key][lang_of(language)].format(**kw)


def stop_hint(language: str = DEFAULT_LANGUAGE) -> str:
    return STOP_HINT[lang_of(language)]


# --------------------------------------------------------------------------- formatting helpers
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_time(dt: datetime, tz: str, *, home: str = "Asia/Kolkata") -> str:
    """'06:30' in the leg's own zone; a zone other than India's is named ('06:30 Asia/Dubai')."""
    local = dt.astimezone(ZoneInfo(tz))
    base = f"{local:%H:%M}"
    return base if tz == home else f"{base} ({tz.split('/')[-1].replace('_', ' ')} time)"


def fmt_day(dt: datetime, tz: str) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}"


def fmt_date(d) -> str:  # noqa: ANN001
    return f"{d.day} {MONTHS[d.month - 1]}"


def clean_name(value: str | None, limit: int = 40) -> str:
    """A hotel or trip name read from a document is data: one line, capped, no control chars."""
    from friday.docunderstand.safety import clean_text

    return clean_text(value or "", limit)
