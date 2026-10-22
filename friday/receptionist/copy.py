# ruff: noqa: E501
"""Every USER-FACING line of the receptionist (WhatsApp texts, button titles, the spoken
"what did I miss?" answer). STATUS: PENDING_FOUNDER_APPROVAL for all of them. The spoken answer
for calling Friday also needs audio approval before it is ever voiced.

The user sees the caller's number in full (it is the user's own missed call); logs never do.
"""

from __future__ import annotations

import re

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "en")

BUTTONS = {  # titles are <= 20 characters (WhatsApp limit)
    "callback": {"hinglish": "Call back", "en": "Call back"},
    "ignore": {"hinglish": "Ignore", "en": "Ignore"},
    "block": {"hinglish": "Block", "en": "Block"},
}

TEXTS: dict[str, dict[str, str]] = {
    "urgent.head": {
        "hinglish": "URGENT: {who} ne abhi call kiya ({when}).",
        "en": "URGENT: {who} just called ({when}).",
    },
    "normal.head": {
        "hinglish": "{who} ne call kiya ({when}).",
        "en": "{who} called ({when}).",
    },
    "spam.head": {
        "hinglish": "Spam jaisa call: {who} ({when}).",
        "en": "Likely spam call: {who} ({when}).",
    },
    "line.reason": {"hinglish": "Kaam: {reason}", "en": "About: {reason}"},
    "line.snippet": {"hinglish": "Unke shabd: \"{snippet}\"", "en": "Their words: \"{snippet}\""},
    "line.number": {"hinglish": "Number: {number}", "en": "Number: {number}"},
    "line.callback_number": {"hinglish": "Unhone yeh number diya: {number}", "en": "They gave this number: {number}"},
    "line.why": {"hinglish": "Kyun urgent/spam laga: {why}", "en": "Why flagged: {why}"},
    "line.no_message": {"hinglish": "Unhone koi message nahi chhoda.", "en": "They left no message."},
    "line.declined": {"hinglish": "Unhone kaha ki kuch note na karein, isliye details nahi hain.", "en": "They asked me not to note anything, so there are no details."},
    "who.unknown": {"hinglish": "ek anjaan number", "en": "an unknown number"},
    "who.named": {"hinglish": "{name} ({number})", "en": "{name} ({number})"},
    "who.contact": {"hinglish": "{contact}", "en": "{contact}"},
    "reply.callback": {"hinglish": "Theek hai. Call back ke liye number: {number}. Is par tap karke call kar lijiye.", "en": "Okay. Number to call back: {number}. Tap it to call."},
    "reply.ignore": {"hinglish": "Theek hai, ignore kar diya.", "en": "Okay, ignored."},
    "reply.block": {"hinglish": "{number} ko Friday par block kar diya: ab se unka call message liye bina khatam hoga. Apne phone par bhi block karna ho toh Phone app > Recents > us number par tap karke Block chuniye (main aapke phone par block nahi kar sakti).", "en": "Blocked {number} on Friday: their calls will end politely without taking a message. To block on your phone too, open the Phone app > Recents > tap the number > Block (I cannot block on your phone)."},
    "reply.stale": {"hinglish": "Yeh message ab available nahi hai.", "en": "That message is no longer available."},
    "digest.head": {"hinglish": "Kal raat se {n} call(s) miss hui, jo Friday ne uthayi:", "en": "{n} missed call(s) Friday answered since last night:"},
    "digest.item": {"hinglish": "- {when} {who}: {reason}", "en": "- {when} {who}: {reason}"},
    "digest.spam": {"hinglish": "{n} spam jaise call(s) bhi aaye ({names}).", "en": "{n} likely spam call(s) too ({names})."},
    "missed.none": {"hinglish": "Koi nayi miss call nahi hai.", "en": "You have no new missed calls."},
    "missed.head": {"hinglish": "Aapki {n} call(s) miss hui: {urgent} urgent, {normal} normal, {spam} spam jaisi.", "en": "You missed {n} call(s): {urgent} urgent, {normal} normal, {spam} likely spam."},
    "missed.item": {"hinglish": "- {when} {who}: {reason}", "en": "- {when} {who}: {reason}"},
    "missed.calendar": {"hinglish": "Aaj ka calendar: {events}.", "en": "On your calendar today: {events}."},
    "spoken.none": {"hinglish": "Koi nayi miss call nahi hai.", "en": "You have no new missed calls."},
    "spoken.head": {"hinglish": "{n} call miss hui. {urgent_part}{normal_part}{spam_part}", "en": "You missed {n} calls. {urgent_part}{normal_part}{spam_part}"},
    "spoken.urgent": {"hinglish": "{n} urgent: {who} ne {reason}. ", "en": "{n} urgent: {who} about {reason}. "},
    "spoken.normal": {"hinglish": "{n} normal. ", "en": "{n} normal. "},
    "spoken.spam": {"hinglish": "{n} spam jaisi. ", "en": "{n} likely spam. "},
    "spoken.more": {"hinglish": "Poori list WhatsApp par bhej di hai.", "en": "I have sent the full list on WhatsApp."},
    "status.on": {"hinglish": "Receptionist chalu hai: jo call aap {rings} ring tak nahi uthate, Friday uthayegi.", "en": "Receptionist is on: calls you do not answer within about {rings} rings go to Friday."},
    "status.off": {"hinglish": "Receptionist band hai. Forwarding band karne ke liye {cancel} dial karein.", "en": "Receptionist is off. To stop forwarding on your phone dial {cancel}."},
    "test.confirmed": {"hinglish": "Forwarding sahi chal rahi hai: Friday ko forwarded call mili.", "en": "Forwarding works: Friday received the forwarded call."},
    "test.failed": {"hinglish": "Test call forward nahi hui. Codes aur carrier voicemail dobara check karein.", "en": "The test call was not forwarded. Please re-check the codes and the carrier voicemail."},
}

_SLOT = re.compile(r"\{(\w+)\}")


def t(key: str, lang: str = "hinglish", **slots: object) -> str:
    text = TEXTS[key][lang if lang in LANGS else "hinglish"]
    return _SLOT.sub(lambda m: str(slots[m.group(1)]), text)


def button_title(action: str, lang: str = "hinglish") -> str:
    return BUTTONS[action][lang if lang in LANGS else "hinglish"]


def all_texts() -> list[tuple[str, str, str]]:
    out = [(f"rcpw.{k}.{lang}", lang, TEXTS[k][lang]) for k in TEXTS for lang in LANGS]
    out += [(f"rcpw.button.{k}.{lang}", lang, BUTTONS[k][lang]) for k in BUTTONS for lang in LANGS]
    return out
