# ruff: noqa: E501
"""EVERY line the live engine may speak. ONE module, so the founder reviews one place.

STATUS: PENDING_FOUNDER_APPROVAL for every line below (hear-before-change, CLAUDE.md rule 3).
No line here is approved audio. Nothing in this module may be changed after approval without a
new audio sample. Each line has a stable id ``<move>.<variant>.<relationship>.<language>.<n>``
(``relationship`` is ``*`` when the line is the default for every kind of callee).

Rules the lines obey (tests enforce them):
* Friday is the user's ASSISTANT, never the user: no line says "I am <user>"; the user is only ever
  referred to by name as the person on whose behalf she calls.
* Friday is female in Hindi forms (bol rahi hoon, karti hoon, dungi).
* Roman Hinglish for ``hinglish``, Devanagari for ``hi``, plain English for ``en``.
* No digits except the national emergency number 112 in the distress line. Times, amounts and
  names are SLOTS filled from the brief or the callee's own words and verified by slotguard.
* {slot} placeholders: user, callee, purpose, message, question, fact, value. ``{ack}`` is filled
  from the ack pool (never one of the last two used). The user's name is a slot, so the user's
  pronoun is never assumed (HANDOFF rule 5): lines use the name or "unhe/unko".
* Disclosure, "are you AI?", stop, wrong-number, distress, voicemail and opt-out lines are fixed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from friday.liveagent.contracts import CalleeKind, CallLanguage
from friday.liveagent.moves import Move

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
GENERIC = "*"
LANGS = ("hinglish", "hi", "en")

# Acknowledgement pools ("Achha theek hai" style, founder 13 Oct: vary them, never the same twice).
ACK_POOL: dict[str, tuple[str, ...]] = {
    "hinglish": ("Ji", "Achha", "Okay", "Theek hai", "Samajh gayi"),
    "hi": ("जी", "अच्छा", "ओके", "ठीक है", "समझ गई"),
    "en": ("Okay", "Right", "I see", "Alright", "Got it"),
}
# Short fillers while waiting (used for hold lines and the asking-the-user wait).
FILLERS: dict[str, tuple[str, ...]] = {
    "hinglish": ("Ek second.", "Bas ek minute."),
    "hi": ("एक सेकंड।", "बस एक मिनट।"),
    "en": ("One second.", "Just a moment."),
}

# (move, variant) -> relationship ("*" = default) -> language -> candidate texts
_CATALOG: dict[tuple[str, str], dict[str, dict[str, list[str]]]] = {}


def _add(
    move: Move,
    variant: str,
    hinglish: Sequence[str],
    hi: Sequence[str],
    en: Sequence[str],
    rel: str | CalleeKind = GENERIC,
) -> None:
    key = (move.value, variant)
    r = rel.value if isinstance(rel, CalleeKind) else rel
    _CATALOG.setdefault(key, {}).setdefault(r, {})
    _CATALOG[key][r] = {"hinglish": list(hinglish), "hi": list(hi), "en": list(en)}


E, F = CalleeKind.FAMILY_ELDER, CalleeKind.FRIEND

# ------------------------------------------------------------------ GREET
_add(
    Move.GREET,
    "named",
    ["Hello, kya meri baat {callee} se ho rahi hai?"],
    ["हैलो, क्या मेरी बात {callee} से हो रही है?"],
    ["Hello, am I speaking with {callee}?"],
)
_add(
    Move.GREET, "named", ["Namaste {callee}."], ["नमस्ते {callee}।"], ["Hello {callee}, namaste."], E
)
_add(Move.GREET, "named", ["Hello {callee}!"], ["हैलो {callee}!"], ["Hello {callee}!"], F)
_add(Move.GREET, "plain", ["Hello, namaste."], ["हैलो, नमस्ते।"], ["Hello, good day."])
_add(Move.GREET, "plain", ["Namaste ji."], ["नमस्ते जी।"], ["Hello, namaste."], E)
_add(Move.GREET, "plain", ["Hello!"], ["हैलो!"], ["Hello!"], F)

# ------------------------------------------------------------------ DISCLOSE (always fixed)
_add(
    Move.DISCLOSE,
    "intro",
    [
        "Main Friday bol rahi hoon, {user} ki virtual assistant. {user} ki taraf se aapko call kiya hai."
    ],
    ["मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} की तरफ़ से आपको कॉल किया है।"],
    ["This is Friday, a virtual assistant calling on behalf of {user}."],
)
_add(
    Move.DISCLOSE,
    "intro",
    [
        "Main Friday bol rahi hoon, {user} ki assistant. Main ek virtual assistant hoon, aur {user} ki taraf se aapko phone kiya hai."
    ],
    [
        "मैं फ्राइडे बोल रही हूँ, {user} की असिस्टेंट। मैं एक वर्चुअल असिस्टेंट हूँ और {user} की तरफ़ से आपको फ़ोन किया है।"
    ],
    ["Hello, this is Friday, {user}'s virtual assistant. I am calling on {user}'s behalf."],
    E,
)
_add(
    Move.DISCLOSE,
    "intro",
    [
        "Main Friday, {user} ki virtual assistant bol rahi hoon. {user} ne mujhse aapko call karwaya hai."
    ],
    ["मैं फ्राइडे, {user} की वर्चुअल असिस्टेंट बोल रही हूँ। {user} ने मुझसे आपको कॉल करवाया है।"],
    ["I am Friday, {user}'s virtual assistant. {user} asked me to call you."],
    F,
)
_add(
    Move.DISCLOSE,
    "who",
    ["Main Friday hoon, {user} ki virtual assistant. {user} ki taraf se call kar rahi hoon."],
    ["मैं फ्राइडे हूँ, {user} की वर्चुअल असिस्टेंट। {user} की तरफ़ से कॉल कर रही हूँ।"],
    ["I am Friday, {user}'s virtual assistant, calling on {user}'s behalf."],
)
_add(
    Move.DISCLOSE,
    "who",
    ["Main Friday hoon, {user} ki assistant. {user} ne mujhe aapse baat karne ko kaha hai."],
    ["मैं फ्राइडे हूँ, {user} की असिस्टेंट। {user} ने मुझे आपसे बात करने को कहा है।"],
    ["I am Friday, {user}'s assistant. {user} asked me to speak with you."],
    E,
)
# The truthful answer to "are you a robot / AI / real person?". Both candidates are truthful.
_add(
    Move.DISCLOSE,
    "are_you_ai",
    [
        "Ji haan, main ek AI assistant hoon, {user} ki taraf se call kar rahi hoon.",
        "Sach bataun toh haan, main AI assistant hoon. {user} ne mujhe aapko call karne ko kaha hai.",
    ],
    [
        "जी हाँ, मैं एक ए आई असिस्टेंट हूँ, {user} की तरफ़ से कॉल कर रही हूँ।",
        "सच कहूँ तो हाँ, मैं ए आई असिस्टेंट हूँ। {user} ने मुझे आपको कॉल करने को कहा है।",
    ],
    [
        "Yes, I am an AI assistant, calling on behalf of {user}.",
        "To be honest, yes, I am an AI assistant. {user} asked me to call you.",
    ],
)

# ------------------------------------------------------------------ STATE_PURPOSE
_add(
    Move.STATE_PURPOSE,
    "purpose",
    [
        "{user} ki taraf se ek chhoti si baat: {purpose}",
        "Mere call karne ki wajah yeh hai: {purpose}",
    ],
    ["{user} की तरफ़ से एक छोटी सी बात: {purpose}", "मेरे कॉल करने की वजह यह है: {purpose}"],
    ["A quick matter from {user}: {purpose}", "The reason for my call: {purpose}"],
)
_add(
    Move.STATE_PURPOSE,
    "purpose",
    ["Aapse ek chhoti si baat karni thi. {purpose}", "{user} ne yeh kehne ko kaha tha. {purpose}"],
    ["आपसे एक छोटी सी बात करनी थी। {purpose}", "{user} ने यह कहने को कहा था। {purpose}"],
    ["I just had a small thing to tell you. {purpose}", "{user} asked me to say this. {purpose}"],
    E,
)
_add(
    Move.STATE_PURPOSE,
    "purpose",
    ["{user} ne mujhe yeh bolne ko kaha: {purpose}", "Bas ek chhoti si baat: {purpose}"],
    ["{user} ने मुझे यह बोलने को कहा: {purpose}", "बस एक छोटी सी बात: {purpose}"],
    ["{user} asked me to tell you: {purpose}", "Just a quick thing: {purpose}"],
    F,
)
_add(
    Move.STATE_PURPOSE,
    "offer_callback",
    ["Agar abhi time nahi hai, toh main {user} se keh kar baad mein dobara call kar sakti hoon."],
    ["अगर अभी समय नहीं है, तो मैं {user} से कहकर बाद में दोबारा कॉल कर सकती हूँ।"],
    ["If now is not a good time, I can call again later."],
)
_add(
    Move.STATE_PURPOSE,
    "message",
    ["Ek baat aur batani thi: {message}", "Aur haan, {message}"],
    ["एक बात और बतानी थी: {message}", "और हाँ, {message}"],
    ["One more thing to tell you: {message}", "Also, {message}"],
)

# ------------------------------------------------------------------ ASK
_add(
    Move.ASK,
    "question",
    ["Mujhe ek cheez poochhni thi: {question}", "Ek sawaal hai: {question}"],
    ["मुझे एक चीज़ पूछनी थी: {question}", "एक सवाल है: {question}"],
    ["I had one thing to ask: {question}", "One question: {question}"],
)
_add(
    Move.ASK,
    "question",
    ["Ek baat poochhni thi: {question}", "Aapse ek cheez poochh sakti hoon? {question}"],
    ["एक बात पूछनी थी: {question}", "आपसे एक चीज़ पूछ सकती हूँ? {question}"],
    ["May I ask you one thing? {question}", "I wanted to ask: {question}"],
    E,
)
_add(
    Move.ASK,
    "followup",
    ["Maaf kijiye, bas ek baar phir: {question}", "Main dobara poochh leti hoon: {question}"],
    ["माफ़ कीजिए, बस एक बार फिर: {question}", "मैं दोबारा पूछ लेती हूँ: {question}"],
    ["Sorry, just once more: {question}", "Let me ask again: {question}"],
)

# ------------------------------------------------------------------ ANSWER_FROM_BRIEF
_add(
    Move.ANSWER_FROM_BRIEF,
    "fact",
    ["Mujhe bas itna pata hai: {fact}", "{ack}, mere paas yeh jaankari hai: {fact}"],
    ["मुझे बस इतना पता है: {fact}", "{ack}, मेरे पास यह जानकारी है: {fact}"],
    ["All I know is this: {fact}", "{ack}, here is what I have: {fact}"],
)
# The fixed deflection for anything not marked shareable (A3.6).
_add(
    Move.ANSWER_FROM_BRIEF,
    "defer",
    [
        "Yeh mujhe pata nahi hai, main {user} se puchhkar aapko bata dungi.",
        "Is baare mein main abhi kuch keh nahi sakti, {user} se puchhkar batati hoon.",
    ],
    [
        "यह मुझे पता नहीं है, मैं {user} से पूछकर आपको बता दूँगी।",
        "इस बारे में मैं अभी कुछ कह नहीं सकती, {user} से पूछकर बताती हूँ।",
    ],
    [
        "I do not know that, I will check with {user} and let you know.",
        "I cannot say anything about that right now, I will ask {user} and tell you.",
    ],
)
_add(
    Move.ANSWER_FROM_BRIEF,
    "defer",
    [
        "Yeh main {user} se puchhkar aapko bata dungi, ji.",
        "Main {user} se poochh kar aapko call karke bata dungi.",
    ],
    ["यह मैं {user} से पूछकर आपको बता दूँगी, जी।", "मैं {user} से पूछकर आपको कॉल करके बता दूँगी।"],
    [
        "I will ask {user} and let you know.",
        "I will check with {user} and call you back with that.",
    ],
    E,
)
# Secrets (OTP, PIN, card number, CVV, password, Aadhaar): never, from anyone, on any call.
_add(
    Move.ANSWER_FROM_BRIEF,
    "secret",
    [
        "Maaf kijiye, main OTP, PIN ya card jaisi details kisi ko nahi batati. Ye mere paas hain bhi nahi.",
        "Yeh details main nahi de sakti, na hi OTP ya PIN kisi ko batati hoon.",
    ],
    [
        "माफ़ कीजिए, मैं ओटीपी, पिन या कार्ड जैसी जानकारी किसी को नहीं बताती। ये मेरे पास हैं भी नहीं।",
        "यह जानकारी मैं नहीं दे सकती, न ही ओटीपी या पिन किसी को बताती हूँ।",
    ],
    [
        "Sorry, I never share an OTP, PIN or card details with anyone. I do not have them either.",
        "I cannot give those details, and I never share OTPs or PINs.",
    ],
)

# ------------------------------------------------------------------ CONFIRM
_add(
    Move.CONFIRM,
    "readback_note",
    ["{ack}, {value}, maine note kar liya.", "{ack}, {value}. Shukriya."],
    ["{ack}, {value}, मैंने नोट कर लिया।", "{ack}, {value}। शुक्रिया।"],
    ["{ack}, {value}, I have noted that.", "{ack}, {value}. Thank you."],
)
_add(
    Move.CONFIRM,
    "readback_check",
    ["Maine {value} suna, sahi hai na?", "{value}, yehi bola na aapne?"],
    ["मैंने {value} सुना, सही है न?", "{value}, यही बोला न आपने?"],
    ["I heard {value}, is that right?", "{value}, did I get that right?"],
)
_add(
    Move.CONFIRM,
    "thanks",
    ["{ack}, shukriya.", "{ack}, bahut achha."],
    ["{ack}, शुक्रिया।", "{ack}, बहुत अच्छा।"],
    ["{ack}, thank you.", "{ack}, good."],
)
# Agreeing to something INSIDE the brief limits (the commitment guard allowed it).
_add(
    Move.CONFIRM,
    "commit_ok",
    ["Ji, {value} theek hai.", "{ack}, {value} pakka."],
    ["जी, {value} ठीक है।", "{ack}, {value} पक्का।"],
    ["Yes, {value} works.", "{ack}, {value} it is."],
)
# Anything outside the limits: no yes, a call-back instead.
_add(
    Move.CONFIRM,
    "need_user",
    [
        "Yeh main abhi pakka nahi kar sakti. Main {user} se confirm karke aapko call back karti hoon.",
        "Is par main abhi haan nahi bol sakti. {user} se poochh kar aapko wapas call karungi.",
    ],
    [
        "यह मैं अभी पक्का नहीं कर सकती। मैं {user} से कन्फ़र्म करके आपको कॉल बैक करती हूँ।",
        "इस पर मैं अभी हाँ नहीं बोल सकती। {user} से पूछकर आपको वापस कॉल करूँगी।",
    ],
    [
        "I cannot confirm that right now. I will check with {user} and call you back.",
        "I cannot say yes to that yet. I will ask {user} and call you back.",
    ],
)

# ------------------------------------------------------------------ HANDLE_OBJECTION
_add(
    Move.HANDLE_OBJECTION,
    "busy",
    [
        "Koi baat nahi. Aap kab free honge? Main tab dobara call kar lungi.",
        "Theek hai, aapko kab call karun? Jab aapko theek lage.",
    ],
    [
        "कोई बात नहीं। आप कब फ़्री होंगे? मैं तब दोबारा कॉल कर लूँगी।",
        "ठीक है, आपको कब कॉल करूँ? जब आपको ठीक लगे।",
    ],
    [
        "No problem. When will you be free? I will call again then.",
        "That is fine. When would be a good time to call?",
    ],
)
_add(
    Move.HANDLE_OBJECTION,
    "busy_noted",
    ["Theek hai, main {value} par dobara call karti hoon.", "{ack}, {value} par call karungi."],
    ["ठीक है, मैं {value} पर दोबारा कॉल करती हूँ।", "{ack}, {value} पर कॉल करूँगी।"],
    ["Alright, I will call again at {value}.", "{ack}, I will call at {value}."],
)
_add(
    Move.HANDLE_OBJECTION,
    "refuses",
    ["Theek hai, koi baat nahi. Main {user} ko bata dungi.", "Bilkul, jaisa aapko theek lage."],
    ["ठीक है, कोई बात नहीं। मैं {user} को बता दूँगी।", "बिल्कुल, जैसा आपको ठीक लगे।"],
    ["That is fine, no problem. I will let {user} know.", "Of course, whatever you prefer."],
)
_add(
    Move.HANDLE_OBJECTION,
    "asks_money",
    [
        "Paise ya payment ke baare mein main kuch tay nahi kar sakti. Yeh {user} se puchhkar hi hoga.",
        "Payment ki baat main nahi kar sakti, yeh {user} khud tay karenge.",
    ],
    [
        "पैसे या पेमेंट के बारे में मैं कुछ तय नहीं कर सकती। यह {user} से पूछकर ही होगा।",
        "पेमेंट की बात मैं नहीं कर सकती, यह {user} खुद तय करेंगे।",
    ],
    [
        "I cannot decide anything about money or payment. That will be for {user} to decide.",
        "I cannot discuss payment; {user} will settle that directly.",
    ],
)
_add(
    Move.HANDLE_OBJECTION,
    "asks_personal",
    [
        "Yeh jaankari mere paas nahi hai. Main {user} se puchhkar aapko bata dungi.",
        "Iske liye mujhe {user} se puchhna padega, main wapas batati hoon.",
    ],
    [
        "यह जानकारी मेरे पास नहीं है। मैं {user} से पूछकर आपको बता दूँगी।",
        "इसके लिए मुझे {user} से पूछना पड़ेगा, मैं वापस बताती हूँ।",
    ],
    [
        "I do not have that information. I will check with {user} and tell you.",
        "I need to ask {user} for that; I will get back to you.",
    ],
)
_add(
    Move.HANDLE_OBJECTION,
    "off_topic",
    [
        "Ji, lekin abhi main bas isi kaam ke liye call kar rahi hoon.",
        "Haan ji, par main sirf is baat ke liye call kar rahi hoon.",
    ],
    [
        "जी, लेकिन अभी मैं बस इसी काम के लिए कॉल कर रही हूँ।",
        "हाँ जी, पर मैं सिर्फ़ इस बात के लिए कॉल कर रही हूँ।",
    ],
    [
        "Of course, but right now I am only calling about this.",
        "Sure, but I am only calling for this one thing.",
    ],
)
_add(
    Move.HANDLE_OBJECTION,
    "clarify",
    [
        "Maaf kijiye, mujhe theek se samajh nahi aaya. Kya aap ek baar phir bata sakte hain?",
        "Sorry, awaaz thodi saaf nahi aayi. Kya aap dobara bol sakte hain?",
    ],
    [
        "माफ़ कीजिए, मुझे ठीक से समझ नहीं आया। क्या आप एक बार फिर बता सकते हैं?",
        "सॉरी, आवाज़ थोड़ी साफ़ नहीं आई। क्या आप दोबारा बोल सकते हैं?",
    ],
    [
        "Sorry, I did not quite catch that. Could you say it once more?",
        "Sorry, the line is not clear. Could you repeat that?",
    ],
)
_add(
    Move.HANDLE_OBJECTION,
    "silence",
    ["Hello? Kya aap meri awaaz sun pa rahe hain?", "Hello, aap line par hain?"],
    ["हैलो? क्या आप मेरी आवाज़ सुन पा रहे हैं?", "हैलो, आप लाइन पर हैं?"],
    ["Hello? Can you hear me?", "Hello, are you still there?"],
)
_add(
    Move.HANDLE_OBJECTION,
    "repeat_prefix",
    ["Ji, main dobara kehti hoon.", "Zaroor, phir se bolti hoon."],
    ["जी, मैं दोबारा कहती हूँ।", "ज़रूर, फिर से बोलती हूँ।"],
    ["Of course, let me say it again.", "Sure, once more."],
)
_add(
    Move.HANDLE_OBJECTION,
    "repeat_prefix",
    ["Ji, main dheere se dobara kehti hoon.", "Zaroor ji, thoda dheere se phir bolti hoon."],
    ["जी, मैं धीरे से दोबारा कहती हूँ।", "ज़रूर जी, थोड़ा धीरे से फिर बोलती हूँ।"],
    ["Of course, let me say it again, more slowly.", "Sure, I will say it slowly once more."],
    E,
)

# ------------------------------------------------------------------ HOLD_WAIT
_add(
    Move.HOLD_WAIT,
    "wait",
    ["Ji, main line par hoon, aap araam se dekh lijiye.", "Theek hai, main wait karti hoon."],
    ["जी, मैं लाइन पर हूँ, आप आराम से देख लीजिए।", "ठीक है, मैं वेट करती हूँ।"],
    ["Sure, I am on the line, take your time.", "Alright, I will wait."],
)
_add(
    Move.HOLD_WAIT,
    "thanks",
    ["Ji, shukriya.", "Shukriya, main yahin hoon."],
    ["जी, शुक्रिया।", "शुक्रिया, मैं यहीं हूँ।"],
    ["Thank you.", "Thanks, I am here."],
)
_add(
    Move.HOLD_WAIT,
    "asking_user",
    [
        "Ek minute, main {user} se puchh leti hoon.",
        "Bas ek minute, {user} se confirm kar leti hoon.",
    ],
    ["एक मिनट, मैं {user} से पूछ लेती हूँ।", "बस एक मिनट, {user} से कन्फ़र्म कर लेती हूँ।"],
    ["One minute, let me check with {user}.", "Just a moment, I will confirm with {user}."],
)
_add(
    Move.HOLD_WAIT,
    "still_here",
    ["Ji, main abhi bhi line par hoon.", "Main yahin hoon, ji."],
    ["जी, मैं अभी भी लाइन पर हूँ।", "मैं यहीं हूँ, जी।"],
    ["I am still on the line.", "I am still here."],
)

# ------------------------------------------------------------------ VOICEMAIL (fixed, short, no private content)
_add(
    Move.VOICEMAIL,
    "message",
    [
        "Namaste, main Friday bol rahi hoon, {user} ki virtual assistant. {user} ne aapko call kiya tha. Jab time mile, kripya {user} ko wapas call kar lijiye. Dhanyavaad."
    ],
    [
        "नमस्ते, मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} ने आपको कॉल किया था। जब समय मिले, कृपया {user} को वापस कॉल कर लीजिए। धन्यवाद।"
    ],
    [
        "Hello, this is Friday, {user}'s virtual assistant. {user} tried to call you. Please call {user} back when you can. Thank you."
    ],
)
_add(
    Move.VOICEMAIL,
    "message",
    [
        "Namaste, main Friday, {user} ki assistant. {user} ne call kiya tha. Fursat mein unhe ek call kar dijiye. Shukriya."
    ],
    ["नमस्ते, मैं फ्राइडे, {user} की असिस्टेंट। {user} ने कॉल किया था। फ़ुर्सत में उन्हें एक कॉल कर दीजिए। शुक्रिया।"],
    [
        "Hello, this is Friday, {user}'s assistant. {user} called you. Please give them a call when you are free. Thank you."
    ],
    F,
)

# ------------------------------------------------------------------ CLOSE
_add(
    Move.CLOSE,
    "done",
    [
        "Bahut shukriya, aapka time dene ke liye. Main {user} ko bata deti hoon. Namaste.",
        "Shukriya, aapki madad ke liye. {user} ko bata dungi. Namaste.",
    ],
    [
        "बहुत शुक्रिया, आपका समय देने के लिए। मैं {user} को बता देती हूँ। नमस्ते।",
        "शुक्रिया, आपकी मदद के लिए। {user} को बता दूँगी। नमस्ते।",
    ],
    [
        "Thank you very much for your time. I will let {user} know. Goodbye.",
        "Thanks for your help. I will tell {user}. Goodbye.",
    ],
)
_add(
    Move.CLOSE,
    "done",
    [
        "Bahut bahut shukriya. Apna khayal rakhiye. Namaste.",
        "Shukriya ji, main {user} ko bata deti hoon. Apna khayal rakhiye.",
    ],
    ["बहुत बहुत शुक्रिया। अपना ख़याल रखिए। नमस्ते।", "शुक्रिया जी, मैं {user} को बता देती हूँ। अपना ख़याल रखिए।"],
    [
        "Thank you so much. Please take care. Goodbye.",
        "Thank you, I will tell {user}. Please take care.",
    ],
    E,
)
_add(
    Move.CLOSE,
    "done",
    ["Thanks yaar, main {user} ko bata deti hoon. Bye!", "Shukriya! {user} ko bata dungi. Bye!"],
    ["थैंक्स यार, मैं {user} को बता देती हूँ। बाय!", "शुक्रिया! {user} को बता दूँगी। बाय!"],
    ["Thanks, I will tell {user}. Bye!", "Thank you! I will let {user} know. Bye!"],
    F,
)
_add(
    Move.CLOSE,
    "need_approval",
    [
        "Theek hai, main {user} se confirm karke aapko call back karti hoon. Shukriya.",
        "Main {user} se poochh kar aapko wapas call karungi. Shukriya, namaste.",
    ],
    [
        "ठीक है, मैं {user} से कन्फ़र्म करके आपको कॉल बैक करती हूँ। शुक्रिया।",
        "मैं {user} से पूछकर आपको वापस कॉल करूँगी। शुक्रिया, नमस्ते।",
    ],
    [
        "Alright, I will confirm with {user} and call you back. Thank you.",
        "I will check with {user} and call you back. Thank you, goodbye.",
    ],
)
_add(
    Move.CLOSE,
    "busy_later",
    [
        "Theek hai, main tab dobara call karti hoon. Shukriya aapka.",
        "Koi baat nahi, tab baat karte hain. Namaste.",
    ],
    ["ठीक है, मैं तब दोबारा कॉल करती हूँ। शुक्रिया आपका।", "कोई बात नहीं, तब बात करते हैं। नमस्ते।"],
    ["Alright, I will call again then. Thank you.", "No problem, we will talk then. Goodbye."],
)
_add(
    Move.CLOSE,
    "declined",
    [
        "Bilkul theek hai. Aapka time dene ke liye shukriya. Namaste.",
        "Koi baat nahi ji. Shukriya, namaste.",
    ],
    ["बिल्कुल ठीक है। आपका समय देने के लिए शुक्रिया। नमस्ते।", "कोई बात नहीं जी। शुक्रिया, नमस्ते।"],
    [
        "That is perfectly fine. Thank you for your time. Goodbye.",
        "No problem at all. Thank you, goodbye.",
    ],
)
_add(
    Move.CLOSE,
    "unresolved",
    [
        "Lagta hai abhi baat nahi ho paa rahi. Main {user} ko bata deti hoon aur dobara koshish karungi. Shukriya.",
        "Abhi baat poori nahi ho paayi. Main {user} ko bata kar phir call karungi. Namaste.",
    ],
    [
        "लगता है अभी बात नहीं हो पा रही। मैं {user} को बता देती हूँ और दोबारा कोशिश करूँगी। शुक्रिया।",
        "अभी बात पूरी नहीं हो पाई। मैं {user} को बताकर फिर कॉल करूँगी। नमस्ते।",
    ],
    [
        "It looks like we are not getting through right now. I will tell {user} and try again. Thank you.",
        "We could not finish this now. I will tell {user} and call again. Goodbye.",
    ],
)
_add(
    Move.CLOSE,
    "time_up",
    [
        "Aapka bahut time le liya, maaf kijiye. Baaki baat main {user} se puchhkar baad mein kar lungi. Shukriya.",
        "Main aur time nahi lungi. Baaki main {user} se puchhkar baad mein batati hoon. Namaste.",
    ],
    [
        "आपका बहुत समय ले लिया, माफ़ कीजिए। बाकी बात मैं {user} से पूछकर बाद में कर लूँगी। शुक्रिया।",
        "मैं और समय नहीं लूँगी। बाकी मैं {user} से पूछकर बाद में बताती हूँ। नमस्ते।",
    ],
    [
        "I have taken a lot of your time, sorry. I will check the rest with {user} and follow up later. Thank you.",
        "I will not take more of your time. I will follow up on the rest later. Goodbye.",
    ],
)

# ------------------------------------------------------------------ STOP (immediate, polite, fixed)
_add(
    Move.STOP,
    "stop_calling",
    ["Bilkul, maaf kijiye. Main dobara call nahi karungi. Namaste."],
    ["बिल्कुल, माफ़ कीजिए। मैं दोबारा कॉल नहीं करूँगी। नमस्ते।"],
    ["Of course, I am sorry. I will not call again. Goodbye."],
)
_add(
    Move.STOP,
    "wrong_number",
    ["Oh, maaf kijiye, galat number lag gaya. Pareshani ke liye sorry. Namaste."],
    ["ओह, माफ़ कीजिए, ग़लत नंबर लग गया। परेशानी के लिए सॉरी। नमस्ते।"],
    ["Oh, I am sorry, I dialled the wrong number. Sorry for the trouble. Goodbye."],
)
_add(
    Move.STOP,
    "distress",
    [
        "Aap theek nahi lag rahe. Main abhi {user} ko turant batati hoon. Agar madad chahiye toh 112 par call kijiye. Apna khayal rakhiye."
    ],
    [
        "आप ठीक नहीं लग रहे। मैं अभी {user} को तुरंत बताती हूँ। अगर मदद चाहिए तो 112 पर कॉल कीजिए। अपना ख़याल रखिए।"
    ],
    [
        "You do not sound well. I am telling {user} right now. If you need help, please call 112. Take care."
    ],
)
_add(
    Move.STOP,
    "no_bots",
    [
        "Samajh gayi, maaf kijiye. Main {user} ko bata deti hoon. Aapko dobara pareshan nahi karungi. Namaste."
    ],
    ["समझ गई, माफ़ कीजिए। मैं {user} को बता देती हूँ। आपको दोबारा परेशान नहीं करूँगी। नमस्ते।"],
    ["Understood, I am sorry. I will tell {user}. I will not bother you again. Goodbye."],
)
_add(
    Move.STOP,
    "hostile",
    ["Maaf kijiye, aapko pareshani hui. Main call band karti hoon. Namaste."],
    ["माफ़ कीजिए, आपको परेशानी हुई। मैं कॉल बंद करती हूँ। नमस्ते।"],
    ["I am sorry for the trouble. I will end the call now. Goodbye."],
)
_add(
    Move.STOP,
    "stop_calling",
    ["Bilkul ji, maaf kijiye. Main dobara phone nahi karungi. Namaste."],
    ["बिल्कुल जी, माफ़ कीजिए। मैं दोबारा फ़ोन नहीं करूँगी। नमस्ते।"],
    ["Of course, I am sorry. I will not call again. Goodbye."],
    E,
)
_add(
    Move.STOP,
    "wrong_number",
    ["Oh, maaf kijiye ji, galat number lag gaya. Pareshani ke liye maafi. Namaste."],
    ["ओह, माफ़ कीजिए जी, ग़लत नंबर लग गया। परेशानी के लिए माफ़ी। नमस्ते।"],
    ["Oh, I am sorry, I have the wrong number. Sorry to have troubled you. Goodbye."],
    E,
)

# ------------------------------------------------------------------ catalog access

_SLOT = re.compile(r"{(\w+)}")


@dataclass(frozen=True)
class PendingLine:
    id: str
    move: str
    variant: str
    relationship: str
    language: str
    text: str
    status: str = LINE_STATUS

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(_SLOT.findall(self.text))


def all_lines() -> list[PendingLine]:
    """Every line, with its stable id, for the founder's review kit."""
    out: list[PendingLine] = []
    for (move, variant), by_rel in sorted(_CATALOG.items()):
        for rel, by_lang in sorted(by_rel.items()):
            for lang in LANGS:
                for i, text in enumerate(by_lang[lang]):
                    out.append(
                        PendingLine(
                            f"{move}.{variant}.{rel}.{lang}.{i}", move, variant, rel, lang, text
                        )
                    )
    return out


def has_variant(move: Move, variant: str) -> bool:
    return (move.value, variant) in _CATALOG


def variants_of(move: Move) -> list[str]:
    return sorted({v for (m, v) in _CATALOG if m == move.value})


def required_slots(move: Move, variant: str) -> frozenset[str]:
    """Slots that every candidate of (move, variant) needs, minus the engine-filled ``ack``."""
    needed: set[str] = set()
    for by_lang in _CATALOG[(move.value, variant)].values():
        for texts in by_lang.values():
            for t in texts:
                needed |= set(_SLOT.findall(t))
    needed.discard("ack")
    return frozenset(needed)


def _candidates(move: Move, variant: str, rel: CalleeKind, lang: CallLanguage) -> list[PendingLine]:
    by_rel = _CATALOG[(move.value, variant)]
    use = rel.value if rel.value in by_rel else GENERIC
    texts = by_rel[use][lang.value]
    return [
        PendingLine(
            f"{move.value}.{variant}.{use}.{lang.value}.{i}",
            move.value,
            variant,
            use,
            lang.value,
            t,
        )
        for i, t in enumerate(texts)
    ]


def norm_line(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


@dataclass(frozen=True)
class Rendered:
    line_id: str
    text: str


class MissingSlot(KeyError):
    pass


def pick_ack(lang: CallLanguage, recent: Sequence[str]) -> str:
    """An acknowledgement that was not one of the last two used."""
    pool = list(ACK_POOL[lang.value])
    fresh = [a for a in pool if a not in recent[-2:]] or pool
    return fresh[len(recent) % len(fresh)]


def render(
    move: Move,
    variant: str,
    rel: CalleeKind,
    lang: CallLanguage,
    slots: dict[str, str],
    *,
    avoid: Sequence[str] = (),
    recent_acks: Sequence[str] = (),
    seed: int = 0,
) -> Rendered | None:
    """The line for (move, variant) with slots filled. Candidates already spoken (``avoid``,
    normalised comparison) are skipped; rotation by ``seed`` keeps the output deterministic but
    varied. Returns None when every candidate would repeat a recent line (the repeat guard)."""
    cands = _candidates(move, variant, rel, lang)
    blocked = {norm_line(a) for a in avoid}
    n = len(cands)
    for k in range(n):
        cand = cands[(seed + k) % n]
        needed = set(_SLOT.findall(cand.text)) - {"ack"}
        missing = needed - set(slots)
        if missing:
            raise MissingSlot(",".join(sorted(missing)))
        values = dict(slots)
        if "{ack}" in cand.text:
            values["ack"] = pick_ack(lang, recent_acks)
        text = cand.text.format(**values)
        text = re.sub(r"\s+([,.!?])", r"\1", text).strip()
        if norm_line(text) in blocked:
            continue
        from friday.qa.override import note_pending_line

        note_pending_line("liveagent", cand.id)  # no-op unless a QA call is running
        return Rendered(cand.id, text)
    return None


def filler(lang: CallLanguage, seed: int = 0) -> str:
    pool = FILLERS[lang.value]
    return pool[seed % len(pool)]
