# ruff: noqa: E501
"""Text that only the integration layer needs. PENDING_FOUNDER_APPROVAL.

Hear-before-change (CLAUDE.md rule 3): nothing in this module may be shown to a real user, or spoken
on a call, until the founder has approved the wording. The wording of each package still lives in
its own copy module (friday/calls/copy.py, friday/savings/copy.py, friday/lifestate/copy.py,
friday/google/consent_copy.py, friday/liveagent/lines.py); this module only holds the few lines that
belong to the seams between them. Placeholders use ``{name}`` format fields.

Two kinds of text:
* ``LINES``: messages on the user's WhatsApp.
* ``SPOKEN``: the only words the bridge adds to a call (they go into the brief the user approved,
  so they appear in the approval message through the opening-line preview and the plan).
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

DEFAULT_LANGUAGE = "hinglish"

LINES: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- Google
    "google_connect_link": {
        "hinglish": "Google jodne ke liye yeh link kholiye (10 minute mein expire ho jata hai): {link}",
        "en": "Open this link to connect Google (it expires in 10 minutes): {link}",
    },
    "google_not_configured": {
        "hinglish": "Google abhi mere yahan set up nahi hai. Thoda wait kijiye.",
        "en": "Google is not set up on my side yet. Please wait a little.",
    },
    "google_connected": {
        "hinglish": "Google juda hua hai ({email}).",
        "en": "Google is connected ({email}).",
    },
    "google_needs_reconnect": {
        "hinglish": "Google ka connection tut gaya hai. 'google connect' likhiye, naya link bhejti hoon.",
        "en": "The Google connection broke. Write 'connect google' and I'll send a new link.",
    },
    "google_not_connected": {
        "hinglish": "Google juda nahi hai. Jodna ho to 'google connect' likhiye.",
        "en": "Google is not connected. Write 'connect google' to connect it.",
    },
    "google_disconnected": {
        "hinglish": "Google hata diya. Mere paas ab aapka Google ka koi data nahi hai.",
        "en": "Google is disconnected. I no longer hold any of your Google data.",
    },
    "google_disconnect_nothing": {
        "hinglish": "Google juda hi nahi tha.",
        "en": "Google was not connected.",
    },
    # ---------------------------------------------------------------- the user's day
    "day_empty": {
        "hinglish": "Aaj ke liye mere paas kuch noted nahi hai.",
        "en": "I have nothing noted for today.",
    },
    # ---------------------------------------------------------------- calls
    "intake_cancelled": {
        "hinglish": "Theek hai, call ka plan hata diya.",
        "en": "Okay, I dropped the call plan.",
    },
    "call_no_voice": {
        "hinglish": "Abhi call lagane ka rasta chalu nahi hai, isliye yeh call nahi hui.",
        "en": "The calling line is not switched on yet, so this call did not happen.",
    },
    # ---------------------------------------------------------------- bridge summaries (W2 -> W1)
    "summary_delivered": {
        "hinglish": "Aapka sandesh pahuncha diya.",
        "en": "I passed on your message.",
    },
    "summary_voicemail_left": {
        "hinglish": "Voicemail par chhota sa fixed message chhoda hai.",
        "en": "I left the short fixed message on voicemail.",
    },
    "summary_cut_off": {
        "hinglish": "Call ka time poora ho gaya, isliye baat adhoori rahi.",
        "en": "The call hit its time limit, so it is not finished.",
    },
    "summary_distress": {
        "hinglish": "Samne wale pareshan lag rahe the. Please unhe khud ek baar phone kar lijiye.",
        "en": "The person sounded distressed. Please call them yourself.",
    },
    "summary_hostile": {
        "hinglish": "Samne wale naraaz the, maine call tameez se band kar di.",
        "en": "The person was upset, so I ended the call politely.",
    },
    "summary_unresolved": {
        "hinglish": "Baat aage nahi badh paayi, isliye maine call band kar di.",
        "en": "We were not getting anywhere, so I ended the call.",
    },
    "summary_unanswered": {
        "hinglish": "Jawab nahi mila: {items}",
        "en": "Not answered: {items}",
    },
    "summary_health": {
        "hinglish": "Unhone apni sehat ke baare mein kuch kaha, ek baar haal-chaal pooch lijiye.",
        "en": "They mentioned a health problem; you may want to check on them.",
    },
    "summary_callback": {
        "hinglish": "Unhone {when} ke aas-paas call karne ko kaha.",
        "en": "They asked for a call around {when}.",
    },
}

SPOKEN: dict[str, dict[str, str]] = {
    # said to the callee in place of the purpose when the purpose is itself a question that the
    # ask list will put next (so the same sentence is not spoken twice)
    "goal_spoken_ask": {
        "hinglish": "Aapse ek sawaal poochna tha.",
        "hi": "आपसे एक सवाल पूछना था।",
        "en": "I had a question for you.",
    },
    # how the callee hears the user when the profile has no name
    "unnamed_user": {
        "hinglish": "mere user",
        "hi": "मेरे यूज़र",
        "en": "my user",
    },
}


def line(key: str, lang: str = DEFAULT_LANGUAGE, **fmt: object) -> str:
    variants = LINES[key]
    text = variants.get(lang) or variants[DEFAULT_LANGUAGE]
    return text.format(**fmt) if fmt else text


def spoken(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    variants = SPOKEN[key]
    return variants.get(lang) or variants[DEFAULT_LANGUAGE]
