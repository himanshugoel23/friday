# ruff: noqa: E501
"""Every user-facing line of refund tracking. STATUS: PENDING_FOUNDER_APPROVAL for all of it.

Hear-before-change (CLAUDE.md rule 3): none of this wording reaches a real user until the founder
has approved it; ``FRIDAY_REFUNDS_ENABLED`` stays OFF until then. There are NO spoken lines in this
file. ``VENDOR_CALL_QUESTIONS`` is what a vendor follow-up call would ask: it is data for a task
spec, a PENDING line too, and the real task adapter refuses to start a call while
``CALL_LINE_STATUS`` is not ``APPROVED`` (a reviewed commit flips it after the founder hears audio).
Two languages per line: ``hinglish`` (default, Roman) and ``en``; any other falls back to Hinglish.

Rules the wording follows: short, warm, no emojis; every PROACTIVE message carries a one-clause
reason and how to stop it; amounts are "expected, not confirmed" until the user or a document says
otherwise; no line states a legal right or a refund window; nothing says Friday holds or moves
money; vendor text is never interpolated except the cleaned, capped vendor name.
"""

from __future__ import annotations

from datetime import date, datetime

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
PENDING_FOUNDER_APPROVAL = True
CALL_LINE_STATUS = "PENDING_FOUNDER_APPROVAL"  # flip to "APPROVED" only after the audio is heard
LANGS = ("hinglish", "en")
DEFAULT_LANGUAGE = "hinglish"
BUTTON_PREFIX = "refund:"
STOP_HINT = {
    "hinglish": "Nahi chahiye toh 'refund mute' bol dena.",
    "en": "Say 'refund mute' to stop these.",
}

# What a vendor follow-up call would ask (PENDING; data for TaskSpec.questions, not a script).
VENDOR_CALL_QUESTIONS: dict[str, list[str]] = {
    "hinglish": [
        "Is booking ya order ka refund process ho gaya hai?",
        "Refund kitne rupaye ka aur kis tareekh tak aayega?",
        "Koi reference ya ticket number mil sakta hai?",
    ],
    "en": [
        "Has the refund for this booking or order been processed?",
        "How much will it be, and by which date?",
        "Can you give a reference or ticket number?",
    ],
}

TEXTS: dict[str, dict[str, str]] = {
    # ---- proposals (Friday noticed something; the user decides)
    "suspect.ask": {
        "hinglish": "{vendor} ki {what} cancel hui hai. Agar paisa pehle de diya tha, toh kya main refund par nazar rakhun? {amount}Yeh sirf yaad dilane ke liye hai, kuch apne aap nahi karungi.",
        "en": "{vendor}: your {what} was cancelled. If you had paid, shall I keep track of the refund? {amount}I will only remind you; I will not do anything on my own.",
    },
    "suspect.again": {
        "hinglish": "Pichhli baat: {vendor} ke refund par nazar rakhun? Haan ya na bata do. {stop}",
        "en": "Earlier question: shall I track the {vendor} refund? Just say yes or no. {stop}",
    },
    "suspect.yes": {
        "hinglish": "Theek hai, {vendor} ka refund track kar rahi hoon. Jab bhi vendor ne kuch kaha ya paisa aaya, bata dena. 'mera refund kahan hai' bologe toh list dikha dungi.",
        "en": "Done, I am tracking the {vendor} refund. Tell me whenever the vendor says something or the money arrives. Say 'where is my refund' for the list.",
    },
    "suspect.no": {
        "hinglish": "Theek hai, {vendor} ka refund track nahi karungi.",
        "en": "Okay, I will not track the {vendor} refund.",
    },
    "what.trip_leg": {"hinglish": "booking", "en": "booking"},
    "what.order": {"hinglish": "order", "en": "order"},
    "what.bill_dispute": {"hinglish": "bill", "en": "bill"},
    "what.user": {"hinglish": "booking ya order", "en": "booking or order"},
    "amount.expected": {
        "hinglish": "Expected {amount} (abhi confirm nahi). ",
        "en": "Expected {amount} (not confirmed yet). ",
    },
    # ---- opening by the user
    "open.ok": {
        "hinglish": "Note kar liya: {vendor} ka refund{amount_part}. Maine kuch nahi bheja ya maanga, bas track kar rahi hoon. Vendor ne kuch kaha ho toh bata dena.",
        "en": "Noted: the {vendor} refund{amount_part}. I have not asked anyone for anything; I am only tracking it. Tell me what the vendor says.",
    },
    "open.need_vendor": {
        "hinglish": "Kis ka refund? Aise bolo: 'Exampleair ka refund nahi aaya, 4500'.",
        "en": "Whose refund? Say it like: 'Exampleair refund not received, 4500'.",
    },
    "open.exists": {
        "hinglish": "{vendor} ka refund pehle se track ho raha hai ({state}).",
        "en": "The {vendor} refund is already being tracked ({state}).",
    },
    "amount.part": {
        "hinglish": " ({amount}, abhi confirm nahi)",
        "en": " ({amount}, not confirmed yet)",
    },
    # ---- "where is my refund"
    "list.none": {
        "hinglish": "Abhi koi refund track nahi ho raha. 'Exampleair ka refund nahi aaya' bol do toh shuru kar dungi.",
        "en": "No refund is being tracked right now. Say 'Exampleair refund not received' and I will start.",
    },
    "list.header": {"hinglish": "Aapke khule refund:", "en": "Your open refunds:"},
    "list.item": {
        "hinglish": "{n}. {vendor}{amount}: {state}, {age} se.",
        "en": "{n}. {vendor}{amount}: {state}, for {age}.",
    },
    "list.item.promised": {
        "hinglish": "{n}. {vendor}: {promised_amount} {date} tak ka vaada, {age} se.",
        "en": "{n}. {vendor}: {promised_amount} promised by {date}, for {age}.",
    },
    "list.footer": {
        "hinglish": "Paisa aa gaya ho toh 'refund aa gaya' bol do. Bank main nahi dekh sakti, isliye aapki baat ya proof hi maanungi.",
        "en": "Say 'refund received' once it arrives. I cannot see your bank, so I go by your word or proof.",
    },
    "age.today": {"hinglish": "aaj", "en": "today"},
    "age.days": {"hinglish": "{n} din", "en": "{n} days"},
    "state.suspected": {"hinglish": "aapki haan ka intezaar", "en": "waiting for your yes"},
    "state.opened": {"hinglish": "shuru kiya", "en": "opened"},
    "state.requested": {"hinglish": "vendor se maanga", "en": "asked the vendor"},
    "state.vendor_acknowledged": {"hinglish": "vendor ne maana", "en": "vendor acknowledged"},
    "state.promised": {"hinglish": "vaada mila", "en": "promised"},
    "state.received": {"hinglish": "kuch paisa aaya", "en": "part received"},
    "state.rejected": {"hinglish": "vendor ne mana kiya", "en": "rejected by the vendor"},
    "state.escalated": {"hinglish": "upar bheja", "en": "escalated"},
    "state.closed": {"hinglish": "band", "en": "closed"},
    # ---- the user's updates
    "requested.ok": {
        "hinglish": "Theek hai, {vendor}: refund maang liya, yeh note kar liya. Kuch din mein poochungi.",
        "en": "Okay, {vendor}: refund requested, noted. I will check in after a few days.",
    },
    "ack.ok": {
        "hinglish": "Note kiya: {vendor} ne maan liya hai. Date aur amount bataye toh likh lungi.",
        "en": "Noted: {vendor} acknowledged it. If they give a date and an amount, tell me.",
    },
    "promised.ok": {
        "hinglish": "{vendor} ne {amount} {date} tak ka kaha. Maine note kar liya (vendor ki baat, pakki nahi). Us din ke baad poochungi.",
        "en": "{vendor} said {amount} by {date}. Noted as the vendor's word, not certain. I will ask after that day.",
    },
    "promised.need": {
        "hinglish": "Date aur amount dono chahiye, jaise 'Exampleair 20 Nov tak 4500'.",
        "en": "I need both a date and an amount, like 'Exampleair by 20 Nov 4500'.",
    },
    "rejected.ok": {
        "hinglish": "Note kiya: {vendor} ne mana kar diya. Upar bhejna hai ya band karna hai? Aap batao.",
        "en": "Noted: {vendor} said no. Escalate it or close it? Your call.",
    },
    "escalated.ok": {
        "hinglish": "Theek hai, {vendor} ka case 'upar bheja' mark kiya. Hafte mein ek baar poochungi.",
        "en": "Okay, the {vendor} case is marked escalated. I will check in once a week.",
    },
    "received.exact": {
        "hinglish": "Badhiya! {vendor}: {amount} aa gaya, expected {expected} ke barabar. Aapki baat par band kar diya.",
        "en": "Great. {vendor}: {amount} arrived, matching the expected {expected}. Closed on your word.",
    },
    "received.exact_proof": {
        "hinglish": "Badhiya! {vendor}: {amount} aa gaya, expected {expected} ke barabar. Proof ke saath band kiya.",
        "en": "Great. {vendor}: {amount} arrived, matching the expected {expected}. Closed with proof.",
    },
    "received.unknown": {
        "hinglish": "{vendor}: {amount} aa gaya, note kar liya. Expected amount pata nahi tha. Band kar diya.",
        "en": "{vendor}: {amount} arrived, noted. I did not have an expected amount. Closed.",
    },
    "received.over": {
        "hinglish": "{vendor}: {amount} aaya, expected {expected} se {diff} zyada. Note kar liya, band kar diya.",
        "en": "{vendor}: {amount} arrived, {diff} more than the expected {expected}. Noted and closed.",
    },
    "received.short": {
        "hinglish": "{vendor}: {amount} aaya, par expected {expected} tha, {diff} kam. Baaki ke liye chase karun, ya itna theek hai?",
        "en": "{vendor}: {amount} arrived, but {expected} was expected, {diff} short. Chase the rest, or is this fine?",
    },
    "received.need_amount": {
        "hinglish": "Kitna aaya? Jaise 'Exampleair refund aa gaya 4500'.",
        "en": "How much arrived? Like 'Exampleair refund received 4500'.",
    },
    "closed.dropped": {
        "hinglish": "Theek hai, {vendor} ka refund band kar diya. Aap kahoge toh dobara khol dungi.",
        "en": "Okay, the {vendor} refund is closed. Say so and I will reopen it.",
    },
    "closed.accepted": {
        "hinglish": "Theek hai, {vendor} ka case band, vendor ka mana maan liya.",
        "en": "Okay, the {vendor} case is closed; the vendor's no is accepted.",
    },
    "case.unknown": {
        "hinglish": "Yeh refund mujhe nahi mila. 'mera refund kahan hai' se list dekho.",
        "en": "I could not find that refund. Say 'where is my refund' for the list.",
    },
    "case.which": {
        "hinglish": "Kaun sa refund? Naam saath bolo, jaise 'Exampleair'.",
        "en": "Which refund? Add the name, like 'Exampleair'.",
    },
    "illegal": {
        "hinglish": "Yeh abhi nahi ho sakta ({state} par hai).",
        "en": "That cannot be done right now (it is at {state}).",
    },
    "muted": {
        "hinglish": "Theek hai, refund ke reminders band. 'refund unmute' se wapas.",
        "en": "Okay, refund reminders are off. 'refund unmute' brings them back.",
    },
    "unmuted": {"hinglish": "Refund reminders wapas chalu.", "en": "Refund reminders are back on."},
    # ---- evidence
    "evidence.saved": {
        "hinglish": "Rakh liya ({level}). File ya photo main nahi rakhti, sirf amount aur reference.",
        "en": "Saved ({level}). I do not keep the file or photo, only the amount and reference.",
    },
    "level.observed": {"hinglish": "maine khud dekha", "en": "I saw it myself"},
    "level.vendor_stated": {"hinglish": "vendor ne kaha", "en": "the vendor said it"},
    "level.user_supplied": {"hinglish": "aapne bheja", "en": "you supplied it"},
    # ---- reminders (each: a reason and how to stop)
    "nudge.requested_q": {
        "hinglish": "{vendor} ka refund {age} se khula hai. Kya aapne vendor se maang liya? Isliye pooch rahi hoon ki bina maange paisa nahi aata. {stop}",
        "en": "The {vendor} refund has been open for {age}. Have you asked the vendor yet? I ask because refunds rarely arrive unasked. {stop}",
    },
    "nudge.checkin": {
        "hinglish": "{vendor} ka refund{amount_part} {age} se atka hai ({state}). Kuch aaya ya vendor ne kuch kaha? Isliye pooch rahi hoon ki aapne bataya tha. {stop}",
        "en": "The {vendor} refund{amount_part} has been pending for {age} ({state}). Did anything arrive, or has the vendor said anything? I ask because you asked me to track it. {stop}",
    },
    "nudge.received_q": {
        "hinglish": "{vendor} ne {amount} {date} tak ka kaha tha. Aa gaya? Isliye pooch rahi hoon ki woh din nikal gaya. {stop}",
        "en": "{vendor} had said {amount} by {date}. Did it arrive? I ask because that day has passed. {stop}",
    },
    "nudge.rejected_q": {
        "hinglish": "{vendor} ne mana kiya tha. Upar bhejna hai (main vendor ko follow-up ka plan bana sakti hoon) ya band karun? {stop}",
        "en": "{vendor} had said no. Escalate (I can propose a vendor follow-up) or close it? {stop}",
    },
    "nudge.short_q": {
        "hinglish": "{vendor}: {amount} aaya tha, {diff} kam. Baaki chase karun ya band kar dun? {stop}",
        "en": "{vendor}: {amount} arrived, {diff} short. Chase the rest or close it? {stop}",
    },
    "notyet.ok": {
        "hinglish": "Theek hai, main thodi der baad phir poochungi.",
        "en": "Okay, I will ask again a little later.",
    },
    # ---- buttons
    "btn.yes": {"hinglish": "Haan, track karo", "en": "Yes, track it"},
    "btn.no": {"hinglish": "Nahi", "en": "No"},
    "btn.asked": {"hinglish": "Haan, maang liya", "en": "Yes, I asked"},
    "btn.received": {"hinglish": "Aa gaya", "en": "It arrived"},
    "btn.notyet": {"hinglish": "Abhi nahi aaya", "en": "Not yet"},
    "btn.chase": {"hinglish": "Upar bhejo", "en": "Escalate"},
    "btn.close": {"hinglish": "Band karo", "en": "Close it"},
    "btn.call_ok": {"hinglish": "Haan, call plan karo", "en": "Yes, plan the call"},
    "btn.call_no": {"hinglish": "Nahi", "en": "No"},
    # ---- vendor follow-up proposals (the user approves; nothing runs before)
    "followup.call": {
        "hinglish": "{vendor} ko refund ke baare mein call karun? Number: {number} ({source}). Aap haan bologe tabhi, aur call se pehle phir poochungi.",
        "en": "Shall I call {vendor} about the refund? Number: {number} ({source}). Only if you say yes, and I will ask again before dialling.",
    },
    "followup.draft": {
        "hinglish": 'Call ki jagah aap yeh message vendor ko bhej sakte ho:\n"{draft}"',
        "en": 'Instead of a call, you can send the vendor this message:\n"{draft}"',
    },
    "followup.draft_body": {
        "hinglish": "Namaste, meri {what} cancel hui thi. Refund{amount_part} abhi tak nahi aaya. Kripya status bataiye.",
        "en": "Hello, my {what} was cancelled. The refund{amount_part} has not arrived yet. Please share the status.",
    },
    "followup.no_number": {
        "hinglish": "{vendor} ka koi number mere paas aapke documents ya records mein nahi hai, aur main number khud nahi dhoondhti. Aap number bhej do ('refund number +91...') ya ticket/bill ki photo bhejo.",
        "en": "I have no number for {vendor} in your documents or records, and I never look numbers up on my own. Send it ('refund number +91...') or a photo of the ticket or bill.",
    },
    "followup.approved": {
        "hinglish": "Theek hai. Call plan bana di; dial karne se pehle main phir poochungi.",
        "en": "Okay. The call is planned; I will ask again before I dial.",
    },
    "followup.declined": {
        "hinglish": "Theek hai, vendor ko follow-up nahi karungi.",
        "en": "Okay, no vendor follow-up.",
    },
    "followup.cap": {
        "hinglish": "Is refund ke liye {n} follow-up ho chuke. Ab aap khud vendor se baat karo ya bank se dispute karo; main track karti rahungi.",
        "en": "{n} follow-ups have already been made for this refund. Please talk to the vendor yourself or raise a dispute with your bank; I will keep tracking.",
    },
    "followup.off": {
        "hinglish": "Vendor ko follow-up abhi chalu nahi hai. Aap khud poochna chaho toh message ka draft de sakti hoon.",
        "en": "Vendor follow-up calls are not switched on. I can give you a message draft to send yourself.",
    },
    "number.saved": {
        "hinglish": "Number rakh liya (aapka diya hua). Isi se call propose karungi, aapki haan ke baad.",
        "en": "Number saved (supplied by you). I will propose a call to it, only after your yes.",
    },
    "number.bad": {
        "hinglish": "Yeh number sahi nahi lag raha ya call ke liye allowed nahi hai.",
        "en": "That number looks wrong or cannot be called.",
    },
    # ---- who to call
    "who.header": {
        "hinglish": "{vendor} ke liye yeh number mere paas hain:",
        "en": "Numbers I hold for {vendor}:",
    },
    "who.line": {"hinglish": "{n}. {number} ({source})", "en": "{n}. {number} ({source})"},
    "who.issuer": {
        "hinglish": "Aapne {bank} se pay kiya tha: dispute ke liye card ke peeche ka number ya {bank} ka app dekho. Main number nahi bataungi jo mere paas nahi hai.",
        "en": "You paid with {bank}: for a dispute use the number on the back of the card or the {bank} app. I will not quote a number I do not hold.",
    },
    "source.user": {"hinglish": "aapne diya", "en": "you gave it"},
    "source.document": {"hinglish": "aapke document se", "en": "from your document"},
    "source.task": {"hinglish": "pehli call ka number", "en": "number from the earlier call"},
    "source.evidence": {"hinglish": "aapke proof se", "en": "from your proof"},
    "source.vendor_record": {"hinglish": "verified vendor record", "en": "verified vendor record"},
}


def lang_of(language: str | None) -> str:
    return language if language in LANGS else DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, **kw: str | int) -> str:
    return TEXTS[key][lang_of(language)].format(**kw)


def stop_hint(language: str = DEFAULT_LANGUAGE) -> str:
    return STOP_HINT[lang_of(language)]


def copy_ids() -> list[str]:
    return sorted(TEXTS)


# --------------------------------------------------------------------------- formatting helpers
def money(paise: int | None) -> str:
    if paise is None:
        return ""
    rupees, rem = divmod(int(paise), 100)
    return f"Rs {rupees:,}" if rem == 0 else f"Rs {rupees:,}.{rem:02d}"


def fmt_date(d: date | datetime) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{d.day} {months[d.month - 1]}"


def age_text(days: int, language: str = DEFAULT_LANGUAGE) -> str:
    return t("age.today", language) if days <= 0 else t("age.days", language, n=days)
