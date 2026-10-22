# ruff: noqa: E501
"""EVERY NEW line the human-voice layer may speak. One module, so the founder reviews one place.

STATUS: PENDING_FOUNDER_APPROVAL for every line (hear-before-change, CLAUDE.md rule 3). They are
spoken ONLY when the matching switch is on (internal-test profile); production never speaks them.
Rules (tests enforce them): Friday is the user's assistant and never says she is human; no digits;
female Hindi forms; no promise or commitment; Roman for ``hinglish``, Devanagari for ``hi``.
``{name}`` is the user's name (a slot). The variants are synonyms of an approved moment, chosen
deterministically per call (friday.human.variants), never freely generated.
"""

from __future__ import annotations

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "hi", "en")

# key -> language -> variants (index 0 is the default used when nothing else is chosen)
VARIANTS: dict[str, dict[str, list[str]]] = {
    # sounds played during the other side's LONG answers, at a pause, never over them
    "bc.short": {
        "hinglish": ["Haan ji.", "Hmm.", "Achha."],
        "hi": ["हाँ जी।", "हम्म।", "अच्छा।"],
        "en": ["Okay.", "I see.", "Right."],
    },
    # a short hold when the model is slow
    "hold.moment": {
        "hinglish": ["Ek second ji.", "Bas ek second.", "Ek minute, dekh rahi hoon."],
        "hi": ["एक सेकंड जी।", "बस एक सेकंड।", "एक मिनट, देख रही हूँ।"],
        "en": ["One second.", "Just a moment.", "One moment, let me check."],
    },
    # variants of the existing "Thank you for holding" line (session _HOLD_LINES)
    "hold.waiting": {
        "hinglish": [
            "Hold karne ke liye dhanyavaad. Main abhi {name} ke jawab ka intezaar kar rahi hoon.",
            "Aapke intezaar ka shukriya. Main abhi {name} ke jawab ka wait kar rahi hoon.",
            "Thoda aur ruk jaiye, {name} ka jawab abhi aana baaki hai.",
        ],
        "hi": [
            "होल्ड करने के लिए धन्यवाद। मैं अभी {name} के जवाब का इंतज़ार कर रही हूँ।",
            "आपके इंतज़ार का शुक्रिया। मैं अभी {name} के जवाब का इंतज़ार कर रही हूँ।",
            "थोड़ा और रुकिए, {name} का जवाब अभी आना बाकी है।",
        ],
        "en": [
            "Thank you for holding. I'm still waiting for {name}'s reply.",
            "Thanks for waiting, I'm still waiting to hear back from {name}.",
            "Please bear with me, {name}'s reply has not come in yet.",
        ],
    },
    # variants of the existing cancel line (session _CANCEL_LINE)
    "cancel.sorry": {
        "hinglish": [
            "Sorry, mujhe abhi yeh call khatam karni hogi. Aapke time ke liye dhanyavaad.",
            "Maaf kijiye, mujhe yeh call abhi band karni padegi. Aapka bahut shukriya.",
            "Sorry ji, mujhe abhi call rakhni hogi. Aapke time ka dhanyavaad.",
        ],
        "hi": [
            "माफ़ कीजिए, मुझे अभी यह कॉल खत्म करनी होगी। आपके समय के लिए धन्यवाद।",
            "माफ़ कीजिए, मुझे यह कॉल अभी बंद करनी पड़ेगी। आपका बहुत शुक्रिया।",
            "सॉरी जी, मुझे अभी कॉल रखनी होगी। आपके समय का धन्यवाद।",
        ],
        "en": [
            "Sorry, I need to end this call now. Thank you for your time.",
            "I am sorry, I have to end the call now. Thank you very much.",
            "Sorry, I have to go now. Thanks for your time.",
        ],
    },
    # joins the unfinished point after an interruption (barge-in resume)
    "resume.connector": {
        "hinglish": ["Toh main yeh keh rahi thi,", "Haan toh, main bata rahi thi,", "Toh jo main keh rahi thi,"],
        "hi": ["तो मैं यह कह रही थी,", "हाँ तो, मैं बता रही थी,", "तो जो मैं कह रही थी,"],
        "en": ["So, as I was saying,", "Right, I was saying,", "So, what I was about to say,"],
    },
    # ONE quick apology when the other side sounds rushed or annoyed
    "mood.apology": {
        "hinglish": ["Maaf kijiye, bas ek chhoti si baat.", "Sorry ji, main jaldi se poochti hoon.", "Aapka time nahi lungi, bas ek baat."],
        "hi": ["माफ़ कीजिए, बस एक छोटी सी बात।", "सॉरी जी, मैं जल्दी से पूछती हूँ।", "आपका समय नहीं लूँगी, बस एक बात।"],
        "en": ["Sorry, just one quick thing.", "Sorry about that, I will be quick.", "I will not take your time, just one thing."],
    },
}

# EXISTING, already approved lines the human layer re-uses unchanged (not new, not in the pending list)
EXISTING_REPEAT_LINE = "Sorry, ek baar phir?"  # playbook confusion line (docs/PLAYBOOKS.md)


def all_lines() -> list[tuple[str, str, int, str]]:
    """[(key, language, variant index, text)] of every NEW line, for the doc and the CLI."""
    return [(k, lang, i, t) for k, by in VARIANTS.items() for lang in LANGS for i, t in enumerate(by[lang])]
