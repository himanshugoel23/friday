"""Every user-facing line of the voice-note feature. PENDING_FOUNDER_APPROVAL.

Nothing here is approved wording: the founder reads and changes these lines before the switch
``FRIDAY_VOICE_NOTE_REPLIES`` is turned on for anyone. Two variants per line: Roman Hinglish
(default) and Devanagari (used when the user wrote in Devanagari). The voice note itself never has
its own words: it speaks the same reply text the chatbot would have sent as text.
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

ROMAN: dict[str, str] = {
    "heard": 'Maine suna: "{text}". Sahi hai?',
    "heard_yes": "Haan, sahi",
    "heard_no": "Nahi",
    "heard_retry": "Theek hai. Phir se bhej do, ya likh do.",
    "heard_expired": "Yeh baat purani ho gayi. Phir se bhej do.",
    "too_long": "Yeh voice note kaafi lamba hai. Chhota bhej do, ya likh do.",
    "not_understood": "Awaaz samajh nahi aayi. Phir se bhej do, ya likh do.",
    "pref_text": "Theek hai, ab se text mein jawab dungi.",
    "pref_voice": (
        "Theek hai, ab se voice note mein jawab dungi. "
        "Number aur zaroori baatein text mein bhi bhejungi."
    ),
    "pref_both": "Theek hai, ab se voice note aur text, dono bhejungi.",
    "pref_mirror": (
        "Theek hai, jaise aap bhejenge waise hi jawab dungi: voice par voice, text par text."
    ),
}

DEVANAGARI: dict[str, str] = {
    "heard": 'मैंने सुना: "{text}"। सही है?',
    "heard_yes": "हाँ, सही",
    "heard_no": "नहीं",
    "heard_retry": "ठीक है। फिर से भेज दो, या लिख दो।",
    "heard_expired": "यह बात पुरानी हो गई। फिर से भेज दो।",
    "too_long": "यह वॉइस नोट काफ़ी लंबा है। छोटा भेज दो, या लिख दो।",
    "not_understood": "आवाज़ समझ नहीं आई। फिर से भेज दो, या लिख दो।",
    "pref_text": "ठीक है, अब से टेक्स्ट में जवाब दूँगी।",
    "pref_voice": (
        "ठीक है, अब से वॉइस नोट में जवाब दूँगी। नंबर और ज़रूरी बातें टेक्स्ट में भी भेजूँगी।"
    ),
    "pref_both": "ठीक है, अब से वॉइस नोट और टेक्स्ट, दोनों भेजूँगी।",
    "pref_mirror": "ठीक है, जैसे आप भेजेंगे वैसे ही जवाब दूँगी: वॉइस पर वॉइस, टेक्स्ट पर टेक्स्ट।",
}

BUTTON_IDS = {"yes": "vn:ok", "no": "vn:no"}


def line(key: str, script: str = "roman", **kw: str) -> str:
    table = DEVANAGARI if script == "devanagari" else ROMAN
    return table[key].format(**kw) if kw else table[key]


def _register_variants() -> None:
    from friday.lang_dev.reply import register_variant

    for key, roman in ROMAN.items():
        if "{" not in roman:
            register_variant(roman, DEVANAGARI[key])


_register_variants()
