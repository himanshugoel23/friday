# ruff: noqa: E501
"""Every user-facing line of the family Drive feature. STATUS: PENDING_FOUNDER_APPROVAL for all of it.

Hear-before-change (CLAUDE.md rule 3): none of this wording (including the folder names that appear
in the user's Drive) may reach a real user until the founder has approved it;
``FRIDAY_FAMILY_DRIVE_ENABLED`` stays OFF until then. There are no spoken lines. Three languages per
line: ``hinglish`` (default, Roman), ``en`` and ``hi`` (Devanagari). Document text is NEVER
interpolated except the sanitised file name and the structured values passed to ``t``.
"""

from __future__ import annotations

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
PENDING_FOUNDER_APPROVAL = True
LANGS = ("hinglish", "en", "hi")
DEFAULT_LANGUAGE = "hinglish"
BUTTON_PREFIX = "fd:"

# Folder names shown in the user's own Drive (PENDING). Keys in tree.py never change.
FOLDER_NAMES: dict[str, str] = {
    "root": "Friday",
    "family": "Family",
    "trips": "Trips",
    "passports": "Passports",
    "visas": "Visas",
    "ids": "IDs",
    "insurance": "Insurance",
    "bills": "Bills",
    "other": "Other",
    "tickets": "Tickets",
    "hotel": "Hotel",
    "default_person": "Me",
    "default_trip": "Unsorted trip",
}
# Words inside generated file names (PENDING).
NAME_WORDS: dict[str, str] = {
    "train": "Train",
    "hotel": "Hotel",
    "passport": "Passport",
    "expires": "exp",
    "bill": "Bill",
    "document": "Document",
}

TEXTS: dict[str, dict[str, str]] = {
    "filed": {
        "hinglish": "Rakh diya aapke Google Drive mein: {path}. Link: {link}",
        "en": "Saved in your Google Drive: {path}. Link: {link}",
        "hi": "आपके Google Drive में रख दिया: {path}। लिंक: {link}",
    },
    "filed.again": {
        "hinglish": "Yeh pehle se aapke Drive mein hai. Link: {link}",
        "en": "This is already in your Drive. Link: {link}",
        "hi": "यह पहले से आपके Drive में है। लिंक: {link}",
    },
    "file.failed": {
        "hinglish": "Drive mein rakh nahi payi, kuch save nahi hua. Dobara bhej do.",
        "en": "I could not save it to your Drive and nothing was kept. Please send it again.",
        "hi": "Drive में नहीं रख पाई, कुछ सेव नहीं हुआ। दोबारा भेज दो।",
    },
    "where.found": {
        "hinglish": "Mil gaya: {name}. Link: {link}",
        "en": "Found it: {name}. Link: {link}",
        "hi": "मिल गया: {name}। लिंक: {link}",
    },
    "where.none": {
        "hinglish": "Yeh mujhe aapke Drive mein nahi mila.",
        "en": "I could not find that in your Drive.",
        "hi": "यह मुझे आपके Drive में नहीं मिला।",
    },
    "where.gone": {
        "hinglish": "Yeh file ab Drive mein nahi hai (shayad hata di gayi). Maine apna note hata diya.",
        "en": "That file is no longer in your Drive (maybe deleted). I removed my note of it.",
        "hi": "यह फ़ाइल अब Drive में नहीं है। मैंने अपना नोट हटा दिया।",
    },
    "share.ask": {
        "hinglish": "{email} ko aapke Friday folder ka {role} access doon? Haan bolo to hi dungi.",
        "en": "Give {email} {role} access to your Friday folder? I will only do it if you say yes.",
        "hi": "क्या {email} को आपके Friday फ़ोल्डर का {role} एक्सेस दूँ? हाँ बोलो तभी दूँगी।",
    },
    "share.done": {
        "hinglish": "Ho gaya: {email} ab aapka Friday folder dekh sakte hain.",
        "en": "Done: {email} can now open your Friday folder.",
        "hi": "हो गया: {email} अब आपका Friday फ़ोल्डर देख सकते हैं।",
    },
    "share.declined": {
        "hinglish": "Theek hai, share nahi kiya.",
        "en": "Okay, I did not share it.",
        "hi": "ठीक है, शेयर नहीं किया।",
    },
    "share.revoked": {
        "hinglish": "{email} ka access hata diya.",
        "en": "Removed access for {email}.",
        "hi": "{email} का एक्सेस हटा दिया।",
    },
    "disconnect.done": {
        "hinglish": "Maine Drive se judi apni sab jaankari hata di. Aapki files Drive mein aapki hi hain, unhe maine nahi chheda.",
        "en": "I deleted everything I kept about your Drive. Your files are still yours in Drive; I did not touch them.",
        "hi": "मैंने Drive से जुड़ी अपनी सारी जानकारी हटा दी। आपकी फ़ाइलें Drive में आपकी ही हैं, मैंने उन्हें नहीं छुआ।",
    },
    "needs_reconnect": {
        "hinglish": "Google Drive dobara jodna padega. Naya link bhejun?",
        "en": "Your Google Drive needs to be connected again. Shall I send a new link?",
        "hi": "Google Drive दोबारा जोड़ना पड़ेगा। नया लिंक भेजूँ?",
    },
    "not_linked": {
        "hinglish": "Abhi Drive juda nahi hai. Jodna chahoge?",
        "en": "Your Drive is not connected yet. Would you like to connect it?",
        "hi": "अभी Drive जुड़ा नहीं है। जोड़ना चाहोगे?",
    },
    "unreachable": {
        "hinglish": "Abhi Google Drive tak pahunch nahi paayi. Thodi der baad try karti hoon.",
        "en": "I cannot reach Google Drive right now. I will try again shortly.",
        "hi": "अभी Google Drive तक नहीं पहुँच पाई। थोड़ी देर बाद कोशिश करती हूँ।",
    },
}
_IDX = {"hinglish": 0, "en": 1, "hi": 2}


def lang_of(language: str | None) -> str:
    return language if language in LANGS else DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, **kw: str) -> str:
    return TEXTS[key][lang_of(language)].format(**kw)


def folder_name(key: str) -> str:
    return FOLDER_NAMES[key]
