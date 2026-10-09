"""Front door: copy and deterministic understanding for people who CALL Friday's number.

Pure functions and tables, no I/O (the call loop lives in ``friday/voice/frontdoor.py``).

Rules baked into the copy (BRIEF: AI disclosure first, never pretend, trust > autonomy):
* the first thing every caller hears is the FIXED AI disclosure; it is pre-rendered in the shared
  TTS cache, so it costs nothing at call time and starts at once;
* Friday is female (Hindi/Hinglish use feminine forms), calm, short, no fillers, no emoji;
* nothing here ever asks for, repeats or reads out a PIN, OTP or CVV; sensitive actions stay on
  WhatsApp behind the PIN (Vobiz sends no keypad events in a media stream, so a PIN cannot be
  taken by voice);
* a line never claims something happened that did not.

Onboarding is a deterministic state machine (name -> language -> spoken consent); the LLM is only
used for free-form requests after that, via ``brain.interpret``.
"""

from __future__ import annotations

import re
from typing import Any

from friday.core.models import Language

_L = Language

# ---------------------------------------------------------------------------------------------
# Fixed lines. Keys are stable (they are also the pre-render list). Languages without a table
# entry fall back to English (regional callers are answered in English until their language has
# reviewed copy; STT still transcribes them).
# ---------------------------------------------------------------------------------------------
LINES: dict[str, dict[Language, str]] = {
    # --- the AI disclosure: ALWAYS the first words a caller hears
    "disclosure": {
        _L.EN: "Hello, this is Friday, an AI assistant.",
        _L.HINGLISH: "Namaste, main Friday hoon, ek AI assistant.",
        _L.HI: "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट।",
    },
    # --- unknown caller: disclosure + the first question in ONE fixed (pre-rendered) clip
    "greeting_new": {
        _L.EN: (
            "Hello, this is Friday, an AI assistant. I don't think we have spoken before. "
            "May I have your name?"
        ),
        _L.HINGLISH: (
            "Namaste, main Friday hoon, ek AI assistant. Lagta hai hum pehli baar baat kar "
            "rahe hain. Aapka naam kya hai?"
        ),
        _L.HI: (
            "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। लगता है हम पहली बार बात कर रहे हैं। "
            "आपका नाम क्या है?"
        ),
    },
    "hello_known": {  # {name}
        _L.EN: "{name}. What do you need?",
        _L.HINGLISH: "{name} ji, bataiye, kya karna hai?",
        _L.HI: "{name} जी, बताइए, मैं आपकी क्या मदद कर सकती हूँ?",
    },
    "hello_known_noname": {
        _L.EN: "What do you need?",
        _L.HINGLISH: "Bataiye, main aapki kya madad kar sakti hoon?",
        _L.HI: "बताइए, मैं आपकी क्या मदद कर सकती हूँ?",
    },
    "ask_name_again": {
        _L.EN: "Sorry, I missed that. What is your name?",
        _L.HINGLISH: "Sorry, mujhe samajh nahi aaya. Aapka naam kya hai?",
        _L.HI: "माफ़ कीजिए, मैं समझ नहीं पाई। आपका नाम क्या है?",
    },
    "ask_language": {  # {name}
        _L.EN: "Nice to meet you, {name}. Hindi, English, or a mix?",
        _L.HINGLISH: (
            "Aapse milkar achha laga, {name}. Aap kis bhasha mein baat karna chahenge: "
            "Hindi, English, ya dono?"
        ),
        _L.HI: (
            "आपसे मिलकर अच्छा लगा, {name}। आप किस भाषा में बात करना चाहेंगे: हिंदी, अंग्रेज़ी, "
            "या दोनों?"
        ),
    },
    "ask_consent": {
        _L.EN: (
            "One important thing. May I store your name and what you ask me, safely in India, "
            "so I can help you? Say yes to agree. You can say delete everything at any time."
        ),
        _L.HINGLISH: (
            "Ek zaroori baat. Kya main aapka naam aur aapki requests surakshit tareeke se India "
            "mein store kar sakti hoon, taaki main aapki madad kar sakoon? Agree karne ke liye "
            "haan boliye. Aap kabhi bhi, sab delete kar do, bol sakte hain."
        ),
        _L.HI: (
            "एक ज़रूरी बात। क्या मैं आपका नाम और आपकी रिक्वेस्ट सुरक्षित तरीके से भारत में "
            "स्टोर कर सकती हूँ, ताकि मैं आपकी मदद कर सकूँ? सहमत होने के लिए हाँ बोलिए। आप कभी "
            "भी, सब डिलीट कर दो, बोल सकते हैं।"
        ),
    },
    "consent_again": {
        _L.EN: "Sorry, was that a yes or a no? May I store your name and requests in India?",
        _L.HINGLISH: (
            "Sorry, yeh haan tha ya na? Kya main aapka naam aur requests India mein store "
            "kar sakti hoon?"
        ),
        _L.HI: (
            "माफ़ कीजिए, यह हाँ था या ना? क्या मैं आपका नाम और रिक्वेस्ट भारत में स्टोर कर "
            "सकती हूँ?"
        ),
    },
    "consent_ok": {  # {name}
        _L.EN: "Thanks, {name}. What do you need?",
        _L.HINGLISH: "Shukriya, {name}. Kya chahiye?",
        _L.HI: "शुक्रिया, {name}। आज मैं आपकी क्या मदद कर सकती हूँ?",
    },
    "consent_declined": {
        _L.EN: "Understood. I have not saved anything. You are welcome to call again. Goodbye.",
        _L.HINGLISH: (
            "Theek hai. Maine kuch bhi save nahi kiya hai. Aap kabhi bhi dobara call kar "
            "sakte hain. Namaste."
        ),
        _L.HI: (
            "ठीक है। मैंने कुछ भी सेव नहीं किया है। आप कभी भी दोबारा कॉल कर सकते हैं। नमस्ते।"
        ),
    },
    # --- rights
    "deleted_fresh": {
        _L.EN: "Done. I have deleted everything I stored about you. Goodbye.",
        _L.HINGLISH: (
            "Ho gaya. Maine aapke baare mein jo bhi store kiya tha, sab delete kar diya. Namaste."
        ),
        _L.HI: "हो गया। मैंने आपके बारे में जो भी स्टोर किया था, सब डिलीट कर दिया। नमस्ते।",
    },
    "deleted_nothing": {
        _L.EN: "Understood. Nothing about you is stored. Goodbye.",
        _L.HINGLISH: "Theek hai. Aapke baare mein kuch bhi store nahi hai. Namaste.",
        _L.HI: "ठीक है। आपके बारे में कुछ भी स्टोर नहीं है। नमस्ते।",
    },
    "delete_needs_pin": {
        _L.EN: (
            "I can delete everything, but it needs your PIN, and I never take a PIN on a call. "
            "Please ask me on WhatsApp."
        ),
        _L.HINGLISH: (
            "Main sab delete kar sakti hoon, lekin uske liye aapka PIN chahiye, aur main call par "
            "kabhi PIN nahi leti. Kripya mujhe WhatsApp par bataiye."
        ),
        _L.HI: (
            "मैं सब डिलीट कर सकती हूँ, लेकिन उसके लिए आपका PIN चाहिए, और मैं कॉल पर कभी PIN नहीं "
            "लेती। कृपया मुझे WhatsApp पर बताइए।"
        ),
    },
    # --- honest answers about what Friday is
    "bot_answer": {
        _L.EN: (
            "Yes, I am an AI assistant, not a human. I handle phone calls and errands for you."
        ),
        _L.HINGLISH: (
            "Ji haan, main ek AI assistant hoon, insaan nahi. Main aapke liye phone calls aur "
            "kaam sambhalti hoon."
        ),
        _L.HI: "जी हाँ, मैं एक AI असिस्टेंट हूँ, इंसान नहीं। मैं आपके लिए फ़ोन कॉल और काम संभालती हूँ।",
    },
    "capabilities": {
        _L.EN: (
            "I am Friday, an AI personal assistant. I can call businesses for you to book "
            "appointments, get quotes and follow up. What do you need?"
        ),
        _L.HINGLISH: (
            "Main Friday hoon, ek AI personal assistant. Main aapke liye businesses ko call "
            "karke appointment book kar sakti hoon, quotes la sakti hoon aur follow up kar "
            "sakti hoon. Aapko kya chahiye?"
        ),
        _L.HI: (
            "मैं Friday हूँ, एक AI पर्सनल असिस्टेंट। मैं आपके लिए बिज़नेस को कॉल करके अपॉइंटमेंट "
            "बुक कर सकती हूँ, कोट ला सकती हूँ और फ़ॉलो-अप कर सकती हूँ। आपको क्या चाहिए?"
        ),
    },
    "capabilities_pilot": {
        _L.EN: (
            "I am Friday, an AI personal assistant. In this test mode I can understand your "
            "request and set it up, but I cannot phone real businesses yet. What do you need?"
        ),
        _L.HINGLISH: (
            "Main Friday hoon, ek AI personal assistant. Is test mode mein main aapki request "
            "samajh kar set up kar sakti hoon, lekin abhi asli businesses ko call nahi kar "
            "sakti. Aapko kya chahiye?"
        ),
        _L.HI: (
            "मैं Friday हूँ, एक AI पर्सनल असिस्टेंट। इस टेस्ट मोड में मैं आपकी रिक्वेस्ट समझकर "
            "सेट अप कर सकती हूँ, लेकिन अभी असली बिज़नेस को कॉल नहीं कर सकती। आपको क्या चाहिए?"
        ),
    },
    # --- requests
    "confirm_task": {  # {goal}
        _L.EN: "{goal}. Shall I start?",
        _L.HINGLISH: "{goal}. Shuru karun?",
        _L.HI: "मैं यह करूँगी: {goal}। क्या मैं आगे बढ़ूँ? हाँ या ना बोलिए।",
    },
    "confirm_again": {
        _L.EN: "Sorry, was that a yes or a no?",
        _L.HINGLISH: "Sorry, yeh haan tha ya na?",
        _L.HI: "माफ़ कीजिए, यह हाँ था या ना?",
    },
    "confirm_no": {
        _L.EN: "Okay, I have not started anything. What would you like instead?",
        _L.HINGLISH: "Theek hai, maine kuch shuru nahi kiya. Aap kya karwana chahenge?",
        _L.HI: "ठीक है, मैंने कुछ शुरू नहीं किया। आप क्या करवाना चाहेंगे?",
    },
    "task_started_callback": {
        _L.EN: "On it. I will call you back with an update.",
        _L.HINGLISH: (
            "Shuru kar diya. Update ke saath call back karungi."
        ),
        _L.HI: "हो गया, मैंने इसे शुरू कर दिया है। अपडेट के साथ मैं आपको कॉल बैक करूँगी।",
    },
    "task_started_message": {
        _L.EN: "On it. I will message you on WhatsApp.",
        _L.HINGLISH: (
            "Shuru kar diya. Result WhatsApp par bhejungi."
        ),
        _L.HI: "हो गया, मैंने इसे शुरू कर दिया है। नतीजा मैं आपको WhatsApp पर भेजूँगी।",
    },
    "task_started_plain": {
        _L.EN: "Done, I have started on it. I cannot send you the result on this setup yet.",
        _L.HINGLISH: (
            "Ho gaya, maine isse shuru kar diya hai. Is setup mein abhi result bhej nahi sakti."
        ),
        _L.HI: "हो गया, मैंने इसे शुरू कर दिया है। इस सेटअप में मैं अभी नतीजा भेज नहीं सकती।",
    },
    "task_queued": {
        _L.EN: "I have queued it and it will start a little later. Is there something else?",
        _L.HINGLISH: "Maine isse queue kar diya hai, yeh thodi der baad shuru hoga. Kuch aur?",
        _L.HI: "मैंने इसे कतार में रख दिया है, यह थोड़ी देर बाद शुरू होगा। कुछ और?",
    },
    "task_not_started": {
        _L.EN: "I could not start that right now, so nothing has been done.",
        _L.HINGLISH: "Main isse abhi shuru nahi kar paayi, isliye kuch nahi hua hai.",
        _L.HI: "मैं इसे अभी शुरू नहीं कर पाई, इसलिए कुछ नहीं हुआ है।",
    },
    "pilot_no_business_calls": {
        _L.EN: (
            "In this test mode I cannot phone real businesses yet, so I have not started that. "
            "Anything else?"
        ),
        _L.HINGLISH: (
            "Is test mode mein main abhi asli businesses ko call nahi kar sakti, isliye maine "
            "yeh shuru nahi kiya. Kuch aur?"
        ),
        _L.HI: (
            "इस टेस्ट मोड में मैं अभी असली बिज़नेस को कॉल नहीं कर सकती, इसलिए मैंने यह शुरू "
            "नहीं किया। कुछ और?"
        ),
    },
    "need_pin_elsewhere": {
        _L.EN: (
            "That needs your PIN, and I never take a PIN on a call. I can't do it by phone yet."
        ),
        _L.HINGLISH: (
            "Uske liye aapka PIN chahiye, aur main call par kabhi PIN nahi leti. Yeh main abhi "
            "phone par nahi kar sakti."
        ),
        _L.HI: (
            "उसके लिए आपका PIN चाहिए, और मैं कॉल पर कभी PIN नहीं लेती। यह मैं अभी फ़ोन पर नहीं "
            "कर सकती।"
        ),
    },
    "not_by_voice": {
        _L.EN: "I can't do that on a call yet. Is there something else?",
        _L.HINGLISH: "Yeh main abhi call par nahi kar sakti. Kuch aur?",
        _L.HI: "यह मैं अभी कॉल पर नहीं कर सकती। कुछ और?",
    },
    "approvals_not_by_voice": {
        _L.EN: "I can't take approvals on a call yet. Is there something else?",
        _L.HINGLISH: "Approval main abhi call par nahi le sakti. Kuch aur?",
        _L.HI: "अप्रूवल मैं अभी कॉल पर नहीं ले सकती। कुछ और?",
    },
    "no_open_tasks": {
        _L.EN: "You have nothing open with me right now. What would you like?",
        _L.HINGLISH: "Abhi aapka mere paas koi kaam open nahi hai. Aap kya karwana chahenge?",
        _L.HI: "अभी आपका मेरे पास कोई काम खुला नहीं है। आप क्या करवाना चाहेंगे?",
    },
    "cancel_confirm": {  # {goal}
        _L.EN: "Cancel {goal}?",
        _L.HINGLISH: "{goal} cancel karun?",
        _L.HI: "इसे रद्द करूँ: {goal}? हाँ या ना बोलिए।",
    },
    "cancel_done": {
        _L.EN: "Done, I have cancelled it. Is there something else?",
        _L.HINGLISH: "Ho gaya, maine isse cancel kar diya. Kuch aur?",
        _L.HI: "हो गया, मैंने इसे रद्द कर दिया। कुछ और?",
    },
    "anything_else": {
        _L.EN: "Anything else?",
        _L.HINGLISH: "Kuch aur?",
        _L.HI: "कुछ और?",
    },
    # --- result call-backs (Friday rings the caller back)
    "cb_update": {  # {name}
        _L.EN: "{name}, here is an update on your request.",
        _L.HINGLISH: "{name}, aapki request ka update yeh hai.",
        _L.HI: "{name}, आपकी रिक्वेस्ट का अपडेट यह है।",
    },
    "cb_offer_whatsapp": {
        _L.EN: "Nothing is confirmed yet. I have sent you the details on WhatsApp to approve.",
        _L.HINGLISH: (
            "Abhi kuch confirm nahi hua hai. Maine details aapko WhatsApp par bhej di hain, "
            "approve karne ke liye."
        ),
        _L.HI: (
            "अभी कुछ कन्फ़र्म नहीं हुआ है। मैंने डिटेल्स आपको WhatsApp पर भेज दी हैं, अप्रूव करने "
            "के लिए।"
        ),
    },
    "cb_offer_novoice": {
        _L.EN: (
            "Nothing is confirmed yet. I cannot take approvals on a call yet, "
            "so I have not booked anything."
        ),
        _L.HINGLISH: (
            "Abhi kuch confirm nahi hua hai. Approval main abhi call par nahi le sakti, "
            "isliye maine kuch book nahi kiya."
        ),
        _L.HI: (
            "अभी कुछ कन्फ़र्म नहीं हुआ है। अप्रूवल मैं अभी कॉल पर नहीं ले सकती, इसलिए मैंने "
            "कुछ बुक नहीं किया।"
        ),
    },
    "cb_unfinished": {
        _L.EN: "I could not finish it.",
        _L.HINGLISH: "Main isse poora nahi kar paayi.",
        _L.HI: "मैं इसे पूरा नहीं कर पाई।",
    },
    # --- flow control
    "hold": {
        _L.EN: "One moment.",
        _L.HINGLISH: "Ek second.",
        _L.HI: "एक सेकंड।",
    },
    "didnt_catch": {
        _L.EN: "Sorry, say that again?",
        _L.HINGLISH: "Sorry, dobara bolenge?",
        _L.HI: "माफ़ कीजिए, मैं समझ नहीं पाई। क्या आप दोबारा बोल सकते हैं?",
    },
    "silence_prompt": {
        _L.EN: "Still here.",
        _L.HINGLISH: "Main yahin hoon.",
        _L.HI: "हैलो? मैं यहीं हूँ।",
    },
    "silence_bye": {
        _L.EN: "I can't hear you, so I will end the call. Please call again any time. Goodbye.",
        _L.HINGLISH: (
            "Mujhe aapki awaaz nahi aa rahi, isliye main call khatam kar rahi hoon. Aap kabhi "
            "bhi dobara call kar sakte hain. Namaste."
        ),
        _L.HI: (
            "मुझे आपकी आवाज़ नहीं आ रही, इसलिए मैं कॉल खत्म कर रही हूँ। आप कभी भी दोबारा कॉल "
            "कर सकते हैं। नमस्ते।"
        ),
    },
    "goodbye": {
        _L.EN: "Alright. Call any time.",
        _L.HINGLISH: "Theek hai. Jab chahe call kijiye.",
        _L.HI: "कॉल करने के लिए शुक्रिया। नमस्ते।",
    },
    "time_limit": {
        _L.EN: "We have reached the time limit for this call. Please call again. Goodbye.",
        _L.HINGLISH: "Is call ki time limit poori ho gayi hai. Kripya dobara call kijiye. Namaste.",
        _L.HI: "इस कॉल की समय सीमा पूरी हो गई है। कृपया दोबारा कॉल कीजिए। नमस्ते।",
    },
    "secret_refusal": {
        _L.EN: (
            "Please do not say any PIN, OTP or card number on this call. I never need them "
            "over the phone."
        ),
        _L.HINGLISH: (
            "Kripya is call par koi PIN, OTP ya card number mat boliye. Mujhe phone par inki "
            "kabhi zaroorat nahi hoti."
        ),
        _L.HI: (
            "कृपया इस कॉल पर कोई PIN, OTP या कार्ड नंबर मत बोलिए। मुझे फ़ोन पर इनकी कभी "
            "ज़रूरत नहीं होती।"
        ),
    },
    "trouble": {
        _L.EN: "Sorry, I am having trouble right now. Please call again in a few minutes. Goodbye.",
        _L.HINGLISH: (
            "Sorry, mujhe abhi dikkat aa rahi hai. Kripya kuch minute baad dobara call kijiye. "
            "Namaste."
        ),
        _L.HI: (
            "माफ़ कीजिए, मुझे अभी दिक्कत आ रही है। कृपया कुछ मिनट बाद दोबारा कॉल कीजिए। नमस्ते।"
        ),
    },
    # --- callers who are NOT served (fixed, pre-rendered, no LLM)
    "reject_private": {
        _L.EN: (
            "Hello, this is Friday, an AI assistant. This number is in a private test right now, "
            "so I can't help on this call. Alright. Call any time."
        ),
        _L.HINGLISH: (
            "Namaste, main Friday hoon, ek AI assistant. Yeh number abhi ek private test mein hai, "
            "isliye main is call par madad nahi kar sakti. Theek hai. Jab chahe call kijiye."
        ),
        _L.HI: (
            "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। यह नंबर अभी एक प्राइवेट टेस्ट में है, इसलिए "
            "मैं इस कॉल पर मदद नहीं कर सकती। कॉल करने के लिए शुक्रिया। नमस्ते।"
        ),
    },
    "reject_busy": {
        _L.EN: (
            "Hello, this is Friday, an AI assistant. I am helping someone else right now. "
            "Please call again in a few minutes. Goodbye."
        ),
        _L.HINGLISH: (
            "Namaste, main Friday hoon, ek AI assistant. Main abhi kisi aur ki madad kar rahi "
            "hoon. Kripya kuch minute baad dobara call kijiye. Namaste."
        ),
        _L.HI: (
            "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। मैं अभी किसी और की मदद कर रही हूँ। कृपया "
            "कुछ मिनट बाद दोबारा कॉल कीजिए। नमस्ते।"
        ),
    },
    "reject_limit": {
        _L.EN: (
            "Hello, this is Friday, an AI assistant. You have called a few times already. "
            "Please try again later. Goodbye."
        ),
        _L.HINGLISH: (
            "Namaste, main Friday hoon, ek AI assistant. Aap kai baar call kar chuke hain. "
            "Kripya baad mein koshish kijiye. Namaste."
        ),
        _L.HI: (
            "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। आप कई बार कॉल कर चुके हैं। कृपया बाद में "
            "कोशिश कीजिए। नमस्ते।"
        ),
    },
    "reject_unavailable": {
        _L.EN: (
            "Hello, this is Friday, an AI assistant. I can't take your call right now. "
            "Please try again later. Goodbye."
        ),
        _L.HINGLISH: (
            "Namaste, main Friday hoon, ek AI assistant. Main abhi aapki call nahi le sakti. "
            "Kripya baad mein koshish kijiye. Namaste."
        ),
        _L.HI: (
            "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। मैं अभी आपकी कॉल नहीं ले सकती। कृपया बाद में "
            "कोशिश कीजिए। नमस्ते।"
        ),
    },
}

#: lines that never contain caller-specific text: warmed into the shared TTS cache
PRERENDER_KEYS: tuple[str, ...] = tuple(
    k
    for k, v in LINES.items()
    if not any("{" in t for t in v.values())
)
#: the minimum set warmed in EVERY language (the rest only in the default language)
PRERENDER_ALWAYS: tuple[str, ...] = (
    "disclosure",
    "greeting_new",
    "reject_private",
    "reject_busy",
    "reject_limit",
    "reject_unavailable",
    "goodbye",
)


def pick_language(lang: Language | None) -> Language:
    """The language a fixed line is spoken in: EN/HI/HINGLISH have reviewed copy; regional
    languages are answered in English (the TTS layer may still voice them natively later)."""
    if lang in (_L.EN, _L.HI, _L.HINGLISH):
        return lang  # type: ignore[return-value]
    return _L.EN


def line(key: str, lang: Language | None, **kw: Any) -> str:
    table = LINES[key]
    text = table[pick_language(lang)]
    return text.format(**kw) if kw else text


def prerender_plan(default: Language) -> dict[Language, list[str]]:
    """What to warm in the shared cache: every caller-independent line in the default language,
    the disclosure/reject set in all three. Cost is a one-off ~(3 x 700 + 3500) characters."""
    plan: dict[Language, list[str]] = {}
    for lang in (_L.HINGLISH, _L.EN, _L.HI):
        keys = PRERENDER_KEYS if lang == pick_language(default) else PRERENDER_ALWAYS
        plan[lang] = [line(k, lang) for k in keys]
    return plan


# ---------------------------------------------------------------------------------------------
# Deterministic understanding (no LLM). Regexes cover English, romanised Hindi and Devanagari.
# ---------------------------------------------------------------------------------------------
_DEV = "ऀ-ॿ"
_B = rf"(?<![\w{_DEV}])"
_E = rf"(?![\w{_DEV}])"


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(_B + "(?:" + pattern + ")" + _E, re.I)


_YES = _rx(
    r"yes|yeah|yep|yup|sure|ok|okay|alright|agree|agreed|i agree|go ahead|do it|proceed|correct|"
    r"right|haan|han|haa|haanji|haan ji|ji haan|ji|bilkul|theek hai|thik hai|theek|kar do|kardo|"
    r"karo|sahi hai|sahi|मंज़ूर|हाँ|हां|हा|जी|जी हाँ|जी हां|बिल्कुल|ठीक है|ठीक|सहमत|कर दो|करो|सही"
)
_NO = _rx(
    r"no|nope|nah|not now|don'?t|do not|stop|cancel|never|disagree|nahi|nahin|nhi|na|mat|"
    r"mat karo|ruk jao|ruko|रुको|नहीं|ना|मत|मत करो|असहमत|रुक जाओ"
)
_DELETE = re.compile(
    r"(delete|erase|remove|wipe|forget)\s+(everything|all|my\s+(data|details|account|information))|"
    r"(sab|sabkuch|sab\s+kuch|saara|sara|mera\s+data|mera\s+sab)\s*(kuch\s*)?"
    r"(delete|hata|mita|erase|khatam)|"
    r"(delete|डिलीट)\s+(kar\s+do|kardo|karo|कर\s+दो)|"
    r"सब\s*(कुछ\s*)?(डिलीट|हटा|मिटा)|मेरा\s+(डेटा|सब)\s*(डिलीट|हटा|मिटा)",
    re.I,
)
_BOT = re.compile(
    r"\b(are|r)\s+(you|u)\s+(a\s+|an\s+)?(bot|robot|machine|ai|human|real|person|computer|"
    r"recording|automated)|\b(bot|robot)\b|is\s+this\s+(a\s+)?(bot|robot|recording|ai|machine)|"
    r"real\s+(person|human)|insaan\s+ho|insan\s+ho|aap\s+(insaan|ai|bot|robot|machine)|"
    r"tum\s+(insaan|ai|bot|robot)|(ai|bot|robot|machine)\s+(ho|hai|hain)|kya\s+aap\s+(ek\s+)?"
    r"(ai|bot|robot|insaan|machine)|रोबोट|इंसान\s+(हो|हैं|है)|मशीन|क्या\s+आप\s+(एक\s+)?(ai|बॉट|"
    r"रोबोट|इंसान)|बॉट",
    re.I,
)
_WHO = re.compile(
    r"\b(who|what)\s+(are|r)\s+(you|u)\b|what\s+can\s+you\s+do|what\s+do\s+you\s+do|"
    r"how\s+can\s+you\s+help|tell\s+me\s+about\s+(yourself|friday)|\bwho\s+is\s+this\b|"
    r"\bwho\s+am\s+i\s+talking\b|(aap|tum|tu)\s+kaun|kaun\s+(bol|ho|hai|hain)|"
    r"(aap|tum)\s+kya\s+(kar|karti|karte)|kya\s+kar\s+(sakti|sakte|sakta)|kya\s+kaam|"
    r"what\s+is\s+friday|आप\s+कौन|तुम\s+कौन|कौन\s+बोल|आप\s+क्या\s+(कर|करती)|क्या\s+कर\s+सकती",
    re.I,
)
_BYE = re.compile(
    r"\b(bye|goodbye|good\s+bye|alvida|that'?s\s+(all|it)|that\s+is\s+(all|it)|nothing\s+else|"
    r"no\s+thanks|no\s+thank\s+you|i\s+am\s+done|i'?m\s+done|bas\s+(itna|ho\s+gaya)|bas|"
    r"kuch\s+nahi|kuch\s+nahin|rakhti\s+hoon|rakhta\s+hoon|phone\s+rakh|chalo\s+bye)\b|"
    r"अलविदा|बस\s*(इतना|हो\s+गया)?|कुछ\s+नहीं|धन्यवाद,?\s*बस",
    re.I,
)
_SECRET = re.compile(
    r"\b(otp|o\.t\.p|one[- ]?time[- ]?(pass(word|code)?)|cvv|cvc|m?pin|t-?pin|pass(word|code)|"
    r"card\s+(number|no)|verification\s+code|security\s+code)\b|ओटीपी|पिन|पासवर्ड|सीवीवी",
    re.I,
)
_LANG_WORDS: list[tuple[re.Pattern[str], Language]] = [
    (_rx(r"hinglish|mix|mixed|dono|both|dono mein|hindi\s+and\s+english|hindi\s+english|मिक्स|दोनों"),
     _L.HINGLISH),
    (_rx(r"english|angrezi|angrezee|अंग्रेज़ी|अंग्रेजी|इंग्लिश"), _L.EN),
    (_rx(r"hindi|hindee|हिंदी|हिन्दी"), _L.HI),
    (_rx(r"tamil|தமிழ்"), _L.TA),
    (_rx(r"telugu|తెలుగు"), _L.TE),
    (_rx(r"kannada|ಕನ್ನಡ"), _L.KN),
    (_rx(r"marathi|मराठी"), _L.MR),
    (_rx(r"bengali|bangla|বাংলা"), _L.BN),
    (_rx(r"gujarati|ગુજરાતી"), _L.GU),
    (_rx(r"malayalam|മലയാളം"), _L.ML),
    (_rx(r"punjabi|ਪੰਜਾਬੀ"), _L.PA),
    (_rx(r"odia|oriya|ଓଡ଼ିଆ"), _L.OR),
]


def yes_no(text: str) -> bool | None:
    """True / False / None (unclear or both). 'haan nahi' is unclear on purpose."""
    t = text or ""
    y, n = bool(_YES.search(t)), bool(_NO.search(t))
    if y and not n:
        return True
    if n and not y:
        return False
    return None


_CONSENT_YES = _rx(
    r"yes|yeah|yep|yup|sure|ok|okay|i agree|agree|agreed|haan|han|haa|haanji|haan ji|ji haan|"
    r"bilkul|theek hai|thik hai|hanji|हाँ|हां|हा|जी हाँ|जी हां|बिल्कुल|ठीक है|सहमत"
)


def consents_yes(text: str) -> bool:
    """Explicit spoken agreement for the data-storage consent (a bare 'ji' is not enough)."""
    t = text or ""
    return bool(_CONSENT_YES.search(t)) and not _NO.search(t)


def wants_delete(text: str) -> bool:
    return bool(_DELETE.search(text or ""))


def asks_if_bot(text: str) -> bool:
    return bool(_BOT.search(text or ""))


def asks_who(text: str) -> bool:
    return bool(_WHO.search(text or ""))


def wants_to_end(text: str) -> bool:
    return bool(_BYE.search(text or ""))


def mentions_secret(text: str) -> bool:
    return bool(_SECRET.search(text or ""))


def parse_language_choice(text: str, detected: Language | None = None) -> Language | None:
    """'Hindi' / 'English' / 'dono' -> a Language; None when the caller named none. A caller who
    simply answers in a language is taken at their word (``detected``)."""
    for rx, language in _LANG_WORDS:
        if rx.search(text or ""):
            return language
    return None


_NAME_PREFIX = re.compile(
    r"^\s*(?:(?:hello|hi|hey|namaste|namaskar|haan|ji|jee|okay|ok|well|so|um|uh)[\s,.!]+)*"
    r"(?:my\s+name\s+is|my\s+name'?s|the\s+name\s+is|name\s+is|this\s+is|it'?s|i\s+am|i'?m|"
    r"call\s+me|you\s+can\s+call\s+me|mera\s+naam|mera\s+nam|naam|main|mai|"
    r"मेरा\s+नाम|मेरा\s+नाम\s+है|नाम|मैं)\s+",
    re.I,
)
_NAME_SUFFIX = re.compile(
    r"\s+(?:hai|hain|he|hu|hoon|hun|bol\s+(?:raha|rahi)\s+(?:hoon|hu|hun)|bol\s+(?:raha|rahi)|"
    r"speaking|here|ji|please|है|हैं|हूँ|हूं|बोल\s+रहा\s+हूँ|बोल\s+रही\s+हूँ|जी)\s*[.!?]*\s*$",
    re.I,
)
_NAME_BAD = re.compile(
    r"\d|@|https?:|\b(what|why|how|who|when|where|kya|kyun|kaun|kab|kaise|nahi|nahin|no|yes|"
    r"haan|book|call|help|please|otp|pin)\b|\?",
    re.I,
)
_NAME_OK = re.compile(rf"^[A-Za-z{_DEV}][A-Za-z{_DEV}.'\- ]{{0,38}}$")


def extract_name(text: str) -> str | None:
    """A caller's name from one utterance, or None if it does not look like a name.
    Stored only after spoken consent; never sent to an LLM from here."""
    t = (text or "").strip().strip(".,!?\"' ")
    if not t:
        return None
    t = _NAME_PREFIX.sub("", t, count=1)
    t = _NAME_SUFFIX.sub("", t).strip(".,!?\"' ")
    if not t or _NAME_BAD.search(t) or len(t.split()) > 4:
        return None
    if not _NAME_OK.match(t):
        return None
    words = [w for w in t.split() if w.lower() not in {"ji", "jee", "sir", "madam", "mr", "mrs"}]
    if not words:
        return None
    return " ".join(w[:1].upper() + w[1:] if w.isascii() else w for w in words)[:40]


# ---------------------------------------------------------------------------------------------
# Making brain text safe to speak
# ---------------------------------------------------------------------------------------------
_MD = re.compile(r"[*_`#>~|]+")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_BULLET = re.compile(r"^\s*(?:[-•·]|\d+[.)])\s+", re.M)
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⭐✅⚠️️]+", re.UNICODE)
_WA_WORDS = re.compile(r"\b(?:reply|tap|press|click)\b[^.!?]*[.!?]?", re.I)


def speakable(text: str | None, *, max_chars: int = 220) -> str:
    """One or two short sentences with no markdown, emoji, links or 'tap a button' wording."""
    t = text or ""
    t = _URL.sub("", t)
    t = _EMOJI.sub("", t)
    t = _BULLET.sub("", t)
    t = _MD.sub("", t)
    t = _WA_WORDS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("। "), cut.rfind("! "))
    return (cut[: stop + 1] if stop > 40 else cut.rsplit(" ", 1)[0]).strip()


def spoken_goal(goal: str | None, fallback: str = "your request", *, max_chars: int = 140) -> str:
    """The task goal as one short phrase for read-back ('book a haircut at Looks tomorrow')."""
    g = speakable(goal, max_chars=max_chars).rstrip(".!? ")
    return g[:1].lower() + g[1:] if g and g[1:2].islower() else (g or fallback)
