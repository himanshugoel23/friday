# ruff: noqa: E501
"""EVERY line the receptionist may SPEAK to a caller. One module, so the founder reviews one place.

STATUS: PENDING_FOUNDER_APPROVAL for every line (hear-before-change, CLAUDE.md rule 3). No audio has
been generated. Nothing here may go live before the founder hears and approves the audio.

Rules the lines obey (tests enforce them):
* Friday is the user's ASSISTANT, never the user. The user is only ever {user}, a name the user
  chose; no line uses a pronoun for the user (HANDOFF rule 5), only honorific-plural verb forms.
* The AI answer is truthful and given when asked ("Haan, main {user} ki AI assistant hoon"). The intro
  says "virtual assistant" (founder decision 2026-10-10: do not volunteer "AI", never deny it).
* NEVER a promise or commitment for the user: no "call back karenge", no times, no "haan". Only what
  Friday herself does: note the message and pass it on.
* No digits, no private information (location, schedule, number) is ever in a fixed line.
* Female forms in Hindi (rahi hoon, sakti, dungi). Roman for ``hinglish``, Devanagari for ``hi``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "hi", "en")

# key -> language -> text ({slot} placeholders: user, name, reason)
LINES: dict[str, dict[str, str]] = {
    "greet.intro": {
        "hinglish": "Hello, main Friday bol rahi hoon, {user} ki virtual assistant. {user} abhi call nahi utha paye. Main aapka message note kar leti hoon. Aap kaun bol rahe hain, aur kis kaam se call kiya tha?",
        "hi": "हैलो, मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} अभी कॉल नहीं उठा पाए। मैं आपका मैसेज नोट कर लेती हूँ। आप कौन बोल रहे हैं, और किस काम से कॉल किया था?",
        "en": "Hello, this is Friday, {user}'s virtual assistant. {user} could not take the call just now. I can note down your message. Who is speaking, and what is it about?",
    },
    "greet.generic": {
        "hinglish": "Hello, main Friday bol rahi hoon, ek virtual assistant. Aap kisse baat karna chahte the, aur kya kaam tha?",
        "hi": "हैलो, मैं फ्राइडे बोल रही हूँ, एक वर्चुअल असिस्टेंट। आप किससे बात करना चाहते थे, और क्या काम था?",
        "en": "Hello, this is Friday, a virtual assistant. Who were you trying to reach, and what is it about?",
    },
    "ask.name": {
        "hinglish": "Aapka naam kya hai?",
        "hi": "आपका नाम क्या है?",
        "en": "May I have your name?",
    },
    "ask.reason": {
        "hinglish": "Aap kis baare mein baat karna chahte the?",
        "hi": "आप किस बारे में बात करना चाहते थे?",
        "en": "What would you like me to tell them it is about?",
    },
    "ask.reason_named": {
        "hinglish": "Ji {name}, aap kis baare mein baat karna chahte the?",
        "hi": "जी {name}, आप किस बारे में बात करना चाहते थे?",
        "en": "Thank you, {name}. What is it about?",
    },
    "unclear": {
        "hinglish": "Maaf kijiye, mujhe samajh nahi aaya. Kya aap dobara bata sakte hain?",
        "hi": "माफ़ कीजिए, मुझे समझ नहीं आया। क्या आप दोबारा बता सकते हैं?",
        "en": "Sorry, I did not catch that. Could you say it again?",
    },
    "readback": {
        "hinglish": "Theek hai, main note kar rahi hoon: {name}, {reason}. Sahi hai?",
        "hi": "ठीक है, मैं नोट कर रही हूँ: {name}, {reason}। सही है?",
        "en": "Okay, I am noting this down: {name}, {reason}. Is that right?",
    },
    "readback.generic": {
        "hinglish": "Theek hai, main aapka message note kar rahi hoon. Sahi hai?",
        "hi": "ठीक है, मैं आपका मैसेज नोट कर रही हूँ। सही है?",
        "en": "Okay, I am noting your message down. Is that right?",
    },
    "retake": {
        "hinglish": "Theek hai, phir se bataiye.",
        "hi": "ठीक है, फिर से बताइए।",
        "en": "Okay, please tell me again.",
    },
    "callback.noted": {
        "hinglish": "Theek hai, aapka number note kar liya.",
        "hi": "ठीक है, आपका नंबर नोट कर लिया।",
        "en": "Okay, I have noted your number.",
    },
    "close.message": {
        "hinglish": "Theek hai, main aapka message {user} tak pahuncha deti hoon. Thank you.",
        "hi": "ठीक है, मैं आपका मैसेज {user} तक पहुँचा देती हूँ। थैंक यू।",
        "en": "Alright, I will pass your message on to {user}. Thank you.",
    },
    "close.no_details": {
        "hinglish": "Theek hai, main {user} ko bata dungi ki aapne call kiya tha. Thank you.",
        "hi": "ठीक है, मैं {user} को बता दूँगी कि आपने कॉल किया था। थैंक यू।",
        "en": "Alright, I will let {user} know that you called. Thank you.",
    },
    "close.noted": {
        "hinglish": "Theek hai, maine aapki baat note kar li hai. Thank you, goodbye.",
        "hi": "ठीक है, मैंने आपकी बात नोट कर ली है। थैंक यू, गुडबाय।",
        "en": "Alright, I have noted what you said. Thank you, goodbye.",
    },
    "close.declined_notes": {
        "hinglish": "Theek hai, main kuch note nahi karungi, bas itna bataungi ki aapne call kiya tha. Thank you.",
        "hi": "ठीक है, मैं कुछ नोट नहीं करूँगी, बस इतना बताऊँगी कि आपने कॉल किया था। थैंक यू।",
        "en": "Alright, I will not note anything down, only that you called. Thank you.",
    },
    "ai.answer": {
        "hinglish": "Haan, main {user} ki AI assistant hoon.",
        "hi": "हाँ, मैं {user} की एआई असिस्टेंट हूँ।",
        "en": "Yes, I am {user}'s AI assistant.",
    },
    "ai.answer.generic": {
        "hinglish": "Haan, main ek AI assistant hoon.",
        "hi": "हाँ, मैं एक एआई असिस्टेंट हूँ।",
        "en": "Yes, I am an AI assistant.",
    },
    "who": {
        "hinglish": "Main Friday hoon, {user} ki virtual assistant.",
        "hi": "मैं फ्राइडे हूँ, {user} की वर्चुअल असिस्टेंट।",
        "en": "I am Friday, {user}'s virtual assistant.",
    },
    "deflect.user_info": {
        "hinglish": "Maaf kijiye, main {user} ke baare mein yeh jaankari nahi de sakti. Aap apna message bata dijiye.",
        "hi": "माफ़ कीजिए, मैं {user} के बारे में यह जानकारी नहीं दे सकती। आप अपना मैसेज बता दीजिए।",
        "en": "Sorry, I cannot share that about {user}. Please tell me your message.",
    },
    "deflect.connect": {
        "hinglish": "{user} abhi baat nahi kar paa rahe. Aap message bata dijiye, main pahuncha dungi.",
        "hi": "{user} अभी बात नहीं कर पा रहे। आप मैसेज बता दीजिए, मैं पहुँचा दूँगी।",
        "en": "{user} is not able to talk right now. Please tell me your message and I will pass it on.",
    },
    "promise.refuse": {
        "hinglish": "Main koi vaada nahi kar sakti, par aapka message zaroor pahuncha dungi.",
        "hi": "मैं कोई वादा नहीं कर सकती, पर आपका मैसेज ज़रूर पहुँचा दूँगी।",
        "en": "I cannot promise anything, but I will pass your message on.",
    },
    "secret.refuse": {
        "hinglish": "Maaf kijiye, main OTP, PIN ya card jaisi koi jaankari na leti hoon na deti hoon.",
        "hi": "माफ़ कीजिए, मैं ओटीपी, पिन या कार्ड जैसी कोई जानकारी न लेती हूँ न देती हूँ।",
        "en": "Sorry, I never take or give an OTP, PIN or card details.",
    },
    "abuse.end": {
        "hinglish": "Main yeh baat-cheet yahin khatam kar rahi hoon. Goodbye.",
        "hi": "मैं यह बातचीत यहीं खत्म कर रही हूँ। गुडबाय।",
        "en": "I am ending this conversation now. Goodbye.",
    },
    "silence.prompt": {
        "hinglish": "Hello? Kya aap sun pa rahe hain?",
        "hi": "हैलो? क्या आप सुन पा रहे हैं?",
        "en": "Hello? Can you hear me?",
    },
    "silence.end": {
        "hinglish": "Lagta hai line mein dikkat hai. Aap dobara call kar sakte hain. Goodbye.",
        "hi": "लगता है लाइन में दिक्कत है। आप दोबारा कॉल कर सकते हैं। गुडबाय।",
        "en": "The line seems to have a problem. You are welcome to call again. Goodbye.",
    },
    "wrong_number": {
        "hinglish": "Koi baat nahi, shayad galat number lag gaya. Goodbye.",
        "hi": "कोई बात नहीं, शायद गलत नंबर लग गया। गुडबाय।",
        "en": "No problem, you may have dialled the wrong number. Goodbye.",
    },
    "blocked.end": {
        "hinglish": "Abhi message lena possible nahi hai. Thank you, goodbye.",
        "hi": "अभी मैसेज लेना संभव नहीं है। थैंक यू, गुडबाय।",
        "en": "I am not able to take a message right now. Thank you, goodbye.",
    },
    "cap.end": {
        "hinglish": "Abhi main aur message nahi le paa rahi. Aap thodi der baad call kar sakte hain. Goodbye.",
        "hi": "अभी मैं और मैसेज नहीं ले पा रही। आप थोड़ी देर बाद कॉल कर सकते हैं। गुडबाय।",
        "en": "I cannot take more messages right now. Please try again a little later. Goodbye.",
    },
    "timeout.wrapup": {
        "hinglish": "Samay kam hai, main aapka message yahin tak note kar leti hoon. Thank you, goodbye.",
        "hi": "समय कम है, मैं आपका मैसेज यहीं तक नोट कर लेती हूँ। थैंक यू, गुडबाय।",
        "en": "We are running out of time, so I will note your message as it is. Thank you, goodbye.",
    },
    "unrouted.close": {
        "hinglish": "Main aapka message note kar rahi hoon, par pakka nahi keh sakti ki yeh kisi tak pahunchega, kyunki mujhe nahi pata chala ki aap kisse baat karna chahte the. Behtar hoga ki aap unhe seedha message bhej dein. Thank you.",
        "hi": "मैं आपका मैसेज नोट कर रही हूँ, पर पक्का नहीं कह सकती कि यह किसी तक पहुँचेगा, क्योंकि मुझे नहीं पता चला कि आप किससे बात करना चाहते थे। बेहतर होगा कि आप उन्हें सीधे मैसेज भेज दें। थैंक यू।",
        "en": "I am noting your message, but I cannot be sure it will reach anyone, because I could not tell whom you were trying to reach. It is better to message them directly. Thank you.",
    },
}

_SLOT = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class PendingLine:
    id: str
    language: str
    text: str
    status: str = LINE_STATUS


def required_slots(key: str) -> frozenset[str]:
    return frozenset(_SLOT.findall(LINES[key]["hinglish"]))


def say(key: str, lang: str = "hinglish", **slots: str) -> str:
    """The fixed line ``key`` in ``lang`` with its slots filled. Missing slot -> KeyError."""
    text = LINES[key][lang if lang in LANGS else "hinglish"]
    return _SLOT.sub(lambda m: slots[m.group(1)], text)


def all_lines() -> list[PendingLine]:
    return [PendingLine(f"rcp.{k}.{lang}", lang, LINES[k][lang]) for k in LINES for lang in LANGS]
