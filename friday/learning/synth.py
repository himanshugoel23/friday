# ruff: noqa: E501
"""Deterministic training-data augmentation for the intent classifier. NO model calls, no network.

Templates (Hinglish / Hindi / English phrasings written by hand for each intent) are expanded with
number, time and name slots and light politeness decorations ("ji", "sir", "achha"...), using a
seeded random generator, so the same seed always gives the same sentences in the same order.

This is synthetic data: it teaches paraphrase and spelling variants, it is NOT real phone speech.
Real accuracy must be measured on recorded, reviewed calls (docs/LATENCY.md says so).

Run ``uv run python -m friday.learning.synth`` to print the sentences (count per intent first).
"""

from __future__ import annotations

import random
import re
import sys

from friday.playbooks.intents import INTENTS

_DEV = re.compile(r"[ऀ-ॿ]")

# short answers get only light decorations (so "nahi" never gains a "haan" in front of it)
_LIGHT_INTENTS = frozenset({"YES", "NO", "CONTINUE", "ACK", "UNCLEAR", "HOLD_ON", "ASKS_REPEAT"})
_PRE = ("", "ji ", "sir ", "achha ", "dekhiye ", "umm ", "arre ", "toh ", "madam ", "actually ")
_SUF = ("", " ji", " sir", " madam", " na", " bhai", " please")
_PRE_LIGHT = ("", "ji ", "achha ", "hmm ")
_SUF_LIGHT = ("", " ji", " sir", " madam")
_PRE_DEV = ("", "जी ", "अच्छा ", "देखिए ")
_SUF_DEV = ("", " जी", " सर", " मैडम")

NUMBERS = (100, 120, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 700, 800, 900, 1000,
           1200, 1500, 2000, 2500, 3000)
HOURS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
NAMES = ("Rohan", "Aman", "Priya", "Sunita", "Imran", "Neha", "Rakesh", "Anjali", "Deepak",
         "Pooja", "Vikram", "Kavita", "Salman", "Meena", "Karan", "Divya")
_WORD_PRICES = ("chaar sau", "paanch sau", "dedh sau", "do sau", "teen sau", "saat sau",
                "dhai sau", "hazaar", "aath sau", "chhe sau", "sau", "do hazaar")

CORES: dict[str, tuple[str, ...]] = {
    "YES": (
        "haan", "haan ji", "ji haan", "ji", "yes", "yes sir", "yeah", "bilkul", "bilkul ji",
        "sahi hai", "theek hai", "thik hai ji", "hmm haan", "haan haan", "ji bilkul", "correct",
        "of course", "sure", "haan chalega", "haan kar denge", "ji kar dungi", "ok", "okay",
        "haan wahi hai", "yes that is right", "haan main hi hoon", "han ji", "jee haan",
        "हाँ जी", "हां", "जी हाँ", "बिल्कुल", "ठीक है जी", "सही है", "जी", "हाँ हाँ", "जी जी",
    ),
    "NO": (
        "nahi", "nahin", "nahi ji", "no", "no sir", "nahi sir", "nahi nahi", "na", "nope",
        "nahi ho payega", "nahi hota", "nahi milega", "sorry nahi", "nahi chahiye", "bilkul nahi",
        "aisa nahi hota", "nahi ho sakta sir", "fixed rate hai discount nahi", "kam nahi hoga",
        "no discount", "nahi ji aisa nahi hai", "nahin nahin", "nai",
        "नहीं", "नहीं जी", "नहीं नहीं", "नहीं हो सकता", "ना जी",
    ),
    "CONTINUE": (
        "boliye", "ji boliye", "haan boliye", "haan ji boliye", "bolo", "haan bolo", "bataiye",
        "haan ji bataiye", "kahiye", "boliye na", "sunaiye", "go ahead", "yes please go ahead",
        "speak", "tell me", "kya kaam hai", "kya baat hai", "kya chahiye", "hello boliye",
        "hello ji boliye", "bolie sir", "ji bataiye", "boliyega", "haan ji kahiye",
        "how can i help you", "yes tell me", "kahiye kya seva kar sakte hain",
        "बोलिए", "हाँ जी बताइए", "बोलो", "जी बोलिए", "क्या काम है", "बताइए",
    ),
    "ACK": (
        "ok thanks", "okay thank you", "thank you", "thanks", "shukriya", "dhanyavaad",
        "ok shukriya", "achha theek hai dhanyavaad", "theek hai thanks", "got it thanks",
        "okay bye thank you", "theek hai shukriya", "thanks a lot", "dhanyawad ji",
        "ठीक है धन्यवाद", "शुक्रिया", "धन्यवाद", "ओके थैंक यू",
    ),
    "BUSY_LATER": (
        "abhi busy hoon", "main busy hoon baad mein baat karte hain", "baad mein call karo",
        "thodi der baad call karna", "abhi time nahi hai", "customer ke saath hoon",
        "abhi free nahi hoon", "shaam ko call kijiye", "kal call karna", "later please",
        "call me later", "i am busy", "i am in a meeting call later", "abhi customer hain baad mein",
        "ek ghante baad call karo", "subah call karna", "abhi thoda busy chal raha hai",
        "abhi rush hai baad mein baat karte hain", "baad mein phone karna abhi kaam hai",
        "अभी व्यस्त हूँ बाद में कॉल करना", "बाद में फोन करिए", "अभी समय नहीं है",
        "अभी टाइम नहीं है बाद में बात करते हैं",
    ),
    "WHO_IS_THIS": (
        "kaun", "kaun bol raha hai", "kaun bol rahi hain", "aap kaun", "aap kaun bol rahe hain",
        "kon hai", "who is this", "who are you", "who is calling", "kahan se bol rahe ho",
        "kis liye call kiya", "kisse baat karni hai", "kya naam hai aapka", "kisne phone kiya",
        "aap kisse baat karna chahte hain", "kyun call kiya hai", "kaun sa number hai ye kaun hai",
        "kaun si company se bol rahe ho", "ji kaun",
        "कौन बोल रहा है", "आप कौन", "किससे बात करनी है", "आप कौन बोल रहे हैं",
    ),
    "ASKS_REPEAT": (
        "kya", "kya kaha", "sorry", "sorry phir se boliye", "phir se boliye", "dobara bolo",
        "ek baar phir bolna", "repeat please", "can you repeat that", "pardon", "samajh nahi aaya",
        "awaaz nahi aa rahi", "sunai nahi diya", "kya bola aapne", "say that again", "what",
        "come again", "fir se bataiye", "ek baar aur boliye", "kya kaha aapne sorry",
        "क्या कहा", "फिर से बोलिए", "सुनाई नहीं दिया", "आवाज़ नहीं आ रही", "दोबारा बोलिए",
    ),
    "ARE_YOU_BOT": (
        "kya aap robot ho", "ye AI hai kya", "robot hai kya", "aap insaan ho ya machine",
        "are you a robot", "are you a human", "is this a recording", "kya yeh recorded hai",
        "real person ho", "computer bol raha hai kya", "kya tum bot ho", "aap asli insaan ho",
        "AI ho kya", "are you an AI", "kya main kisi machine se baat kar raha hoon",
        "क्या आप रोबोट हैं", "ये मशीन है क्या", "आप इंसान हैं या कंप्यूटर",
    ),
    "WRONG_NUMBER": (
        "wrong number", "galat number lagaya hai", "ye salon nahi hai", "yahan salon nahi hai",
        "aapne galat jagah phone kiya", "not a salon", "this is not a salon", "ye shop nahi hai",
        "yahan koi nahi rehta ye ghar ka number hai", "ye clinic hai salon nahi",
        "aapne wrong number dial kiya hai", "yeh salon wala number nahi hai",
        "रॉन्ग नंबर", "ये सैलून नहीं है", "गलत नंबर लगाया है", "आपने गलत नंबर मिलाया है",
    ),
    "HOLD_ON": (
        "ek minute", "ek minute ruko", "ek second", "hold karo", "hold kijiye", "ruko", "rukiye zara",
        "zara ruko", "wait a minute", "one moment", "just a minute", "thoda ruko",
        "line pe rahiye", "ek min hold karna", "main dekh ke batati hoon", "abhi dekh ke batata hoon",
        "ek minute main check karta hoon", "ruko ek second", "hold on please", "ek minute rukna",
        "रुकिए", "एक मिनट", "होल्ड कीजिए", "ज़रा रुकिए", "एक सेकंड", "दो मिनट रुको",
    ),
    "SLOT_FREE": (
        "haan {t} baje free hai", "{t} baje slot mil jayega", "kal {t} baje aa jaiye",
        "slot available hai", "slot khali hai", "aaj shaam free hai", "abhi free hain aa jao",
        "{t} baje ka slot hai", "{t} baje ho jayega", "haan aa sakte ho {t} baje",
        "kal subah koi slot khali hai", "available hai {t} baje", "aa jaiye abhi koi nahi hai",
        "aaj {t} baje slot hai", "yes {t} pm is free", "we are free at {t}",
        "{t} बजे फ्री है", "स्लॉट खाली है", "आ जाइए अभी फ्री हैं", "हाँ {t} बजे स्लॉट मिल जाएगा",
    ),
    "SLOT_BUSY": (
        "full hai", "aaj full hai", "slot nahi hai", "koi slot nahi hai", "kal poora booked hai",
        "housefull hai", "{t} baje slot nahi hai", "free nahi hai abhi", "available nahi hai aaj",
        "fully booked hai", "bahut rush hai jagah nahi hai", "nahi ho payega aaj",
        "kal tak sab full hai", "no slot available", "we are fully booked", "aaj sab booked hain",
        "abhi koi khali nahi hai", "{t} baje full hai",
        "फुल है", "स्लॉट नहीं है", "आज जगह नहीं है",
    ),
    "OFFERS_SLOTS": (
        "{a} baje ya {b} baje", "{a} baje free nahi hai {b} baje aa jao", "{a} ya {b} baje aa sakte ho",
        "{a} baje ya {b} baje dono chalenge", "{a} baje full hai {b} baje ho jayega",
        "either {a} or {b}", "{a} baje nahi {b} baje mil jayega", "{a} baje ya phir {b} baje",
        "{a} बजे या {b} बजे",
    ),
    "GIVES_TIME": (
        "{t} baje", "shaam {t} baje", "kal {t} baje", "subah {t} baje", "{t}:30 baje",
        "saade {t} baje", "dopahar {t} baje", "{t} pm", "{t} am", "raat {t} baje",
        "{t} बजे", "शाम {t} बजे",
    ),
    "NEEDS_APPOINTMENT": (
        "appointment lena padega", "appointment lagta hai", "walk-in nahi hota",
        "bina appointment nahi hota", "pehle se book karna padega", "appointment ke bina nahi hota",
        "walk in allowed nahi hai", "appointment required hai", "appointment hi hota hai",
        "pehle appointment le lijiye", "appointment chahiye hoga", "appointment leni padegi",
        "अपॉइंटमेंट लेना पड़ेगा", "बिना अपॉइंटमेंट नहीं होता",
    ),
    "ASKS_CUSTOMER_PHONE": (
        "customer ka number do", "unka phone number bata dijiye", "aapke customer ka number kya hai",
        "number kya hai unka", "contact number do", "client ka mobile number share karo",
        "unka number bhejiye", "mobile number chahiye", "phone number dijiye", "number bata do",
        "customer ka contact number bataiye", "unka number kya hai",
        "नंबर बताइए", "कस्टमर का नंबर दीजिए",
    ),
    "GIVES_PRICE": (
        "{n} rupaye", "{n} lagega", "{n} lagenge", "{n} ka hai", "haircut {n} ka hai", "{n} rs",
        "rupaye {n}", "sirf {n} rupaye", "{n} rupees", "{n} sir", "{n} rupaye lagenge",
        "{w} rupaye", "{w} lagega", "{w} ka hai", "price {n} hai", "charges {n} hain",
        "{n} रुपये लगेंगे", "{n} रुपये", "सर {n} रुपये लगेंगे", "{w} रुपये",
    ),
    "PRICE_RANGE": (
        "{a} se {b} tak", "{a} to {b}", "{a}-{b}", "{a} se {b} rupaye ke beech", "{a} ya {b}",
        "between {a} and {b}", "{a} se {b} lagta hai", "{a} to {b} depending", "{a} se {b} ke andar",
        "{a} से {b} तक", "{a} से {b} रुपये",
    ),
    "PRICE_DEPENDS": (
        "stylist pe depend karta hai", "depend karta hai", "senior stylist ka alag rate hai",
        "junior ka kam senior ka zyada", "hisaab se alag alag hai", "kaam pe depend karega",
        "length pe depend karta hai", "alag alag stylist ke alag alag rate hain",
        "it depends on the stylist", "depends", "service ke hisaab se rate hai",
        "senior ya junior pe depend karega", "stylist ke hisaab se lagta hai",
        "निर्भर करता है", "स्टाइलिस्ट पर निर्भर है", "हिसाब से अलग अलग है",
    ),
    "REFUSES_PRICE": (
        "phone pe price nahi bata sakte", "aake pooch lo", "aap aa jao phir bataenge",
        "rate phone pe nahi batate", "we do not share rates on phone", "price call pe nahi bata sakte",
        "yahan aakar poochh lijiye", "phone par nahi bata sakte", "come in and ask",
        "aa kar puchh lena", "rate batane ki policy nahi hai phone par aa jao",
        "फोन पर नहीं बता सकते", "आकर पूछ लीजिए",
    ),
    "NEEDS_ADVANCE": (
        "advance dena padega", "{n} rupaye advance dena hoga", "booking ke liye advance lagta hai",
        "deposit lenge pehle", "token amount dena padega", "advance payment chahiye",
        "cancellation charge lagega", "booking amount dena hoga", "pehle payment karna padega",
        "advance ke bina booking nahi hogi", "pay karna padega pehle", "advance required hai",
        "एडवांस देना पड़ेगा", "{n} रुपये एडवांस लगेगा",
    ),
    "NO_ADVANCE": (
        "advance nahi lagega", "koi advance nahi", "advance ki zaroorat nahi hai", "no advance",
        "bina advance ke aa jao", "advance nahi lete hum", "koi deposit nahi", "advance nahi dena padega",
        "no advance needed", "advance wagairah kuch nahi", "advance nahi hai seedha aa jao",
        "एडवांस नहीं लगेगा", "कोई एडवांस नहीं",
    ),
    "GIVES_STYLIST": (
        "{name} karega", "stylist {name} rahega", "{name} ji kar denge", "{name} hai woh kar denge",
        "{name} bhaiya karenge", "{name} available hai", "{name} se karwa lijiye", "{name} sir karenge",
        "{name} karegi", "{name} dekhegi", "{name} will do it", "stylist ka naam {name} hai",
    ),
    "ASKS_OFFTOPIC": (
        "parking hai kya", "aap kaunsa shampoo use karte ho", "kya aap home service dete ho",
        "aapka address kya hai", "kitne log aayenge", "kaun sa product use hota hai",
        "membership hai kya aapke paas", "koi offer chal raha hai", "discount milega kya",
        "aapki location kahan hai", "kaun si brand ka color lagate ho", "kya package hai",
        "wifi hai kya", "kya kids ke liye bhi hai", "parking milegi", "do you have parking",
        "do you offer any packages", "kya aap UPI se payment karoge", "aap kab tak open ho",
        "क्या पार्किंग है", "कोई ऑफर है क्या", "आपका पता क्या है",
    ),
    "ASKS_SECRET": (
        "OTP bata do", "pehle OTP bhejiye", "card number do", "aapka pin kya hai", "CVV bolo",
        "password bata dijiye", "aadhaar number bhejo", "card ka number aur pin bhejiye",
        "OTP aaya hoga wo bataiye", "confirm karne ke liye OTP share karo", "send your card details",
        "ओटीपी बताइए", "आधार नंबर दीजिए", "पिन बताओ",
    ),
    "STOP_CALLING": (
        "dobara call mat karna", "call mat karo", "hamein call karna band karo",
        "number list se hata do", "do not call us again", "stop calling", "phone mat karna dobara",
        "please do not call again", "number delete kar do", "unsubscribe", "calls band karo",
        "aaj ke baad call mat karna", "never call this number again",
        "दोबारा कॉल मत करना", "नंबर हटा दो", "कॉल बंद कर दो", "फोन मत करना",
    ),
    "RUDE": (
        "bakwas band karo", "faltu mein tang mat karo", "pagal ho kya", "shut up", "idiot",
        "stupid calls", "time waste mat karo", "bewakoof ho kya", "chup kar", "tang mat karo",
        "kitna pareshan karoge", "you are an idiot", "faltu ke calls",
        "बकवास बंद करो", "फालतू फोन मत करो", "तुम पागल हो", "तंग मत करो",
    ),
    "OUT_OF_STOCK": (
        "stock mein nahi hai", "out of stock", "khatam ho gaya", "maal khatam hai",
        "abhi available nahi hai", "stock nahi hai", "next week aayega", "mangwana padega",
        "order pe milega", "sold out", "filhal nahi hai", "aaj nahi hai", "wo piece khatam ho gaya",
        "abhi stock mein nahi hai kal tak aayega", "currently not in stock",
        "स्टॉक में नहीं है", "खत्म हो गया है",
    ),
    "VISIT_NEEDED": (
        "aake dekhna padega", "dekh ke hi bata sakte hain", "pehle visit karenge phir quote denge",
        "site visit ke baad batayenge", "bina dekhe nahi bata sakte", "inspection ke baad rate batayenge",
        "aake check karenge tab rate", "problem dekhni padegi", "ghar aake dekhenge",
        "visit karna padega", "without seeing we cannot say", "dekhne ke baad hi price bata payenge",
        "pehle aake dekhenge phir bataunga", "dekhe bina quote nahi de sakte",
    ),
    "WHATSAPP_PLEASE": (
        "WhatsApp pe bhej do", "message kar do", "whatsapp par details bhejiye", "msg kar dijiye",
        "WhatsApp karo", "send it on whatsapp", "price list whatsapp pe bhej do", "details bhej dijiye",
        "whatsapp pe bata dena", "mail kar do", "please message on whatsapp",
        "मैसेज कर दो", "व्हाट्सएप पर भेज दो",
    ),
    "NO_CHARGE": (
        "visit free hai", "koi charge nahi", "free hai", "bilkul free", "demo free hai",
        "inspection ke paise nahi lagte", "no charge", "kuch nahi lagta", "free of charge",
        "paisa nahi lagta", "muft hai", "fees nahi hai", "visit ka koi charge nahi lagta",
        "कोई चार्ज नहीं", "फ्री है", "विज़िट फ्री है",
    ),
    "SAME_NUMBER": (
        "yahi number hai", "isi number pe", "same number hai", "yehi number use kar lo",
        "jis number se call kiya usi pe", "this same number", "yahi wala number",
        "यही नंबर है", "इसी नंबर पर",
    ),
    "UNCLEAR": (
        "hello", "hello hello", "hi", "hello?", "helo", "hmm", "umm", "uh huh", "ahh",
        "[inaudible]", "(noise)", "kkh", "mmm", "uhh", "[static]",
        "हेलो", "हैलो हैलो",
    ),
}

assert set(CORES) <= INTENTS, set(CORES) - INTENTS


def _expand(core: str, intent: str, rng: random.Random) -> str:
    """Fill the {slots} of one template with seeded choices ({a}/{b}: two hours for offered
    slots, two prices for a price range)."""
    if "{" not in core:
        return core
    pool = HOURS if intent == "OFFERS_SLOTS" else NUMBERS
    a, b = sorted(rng.sample(pool, 2))
    return core.format(
        n=rng.choice(NUMBERS), w=rng.choice(_WORD_PRICES), a=a, b=b, t=rng.choice(HOURS),
        name=rng.choice(NAMES),
    )


def generate(seed: int = 7, per_core: int = 5) -> list[tuple[str, str]]:
    """``(text, intent)`` pairs. Deterministic for a given ``seed``; no duplicates."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for intent in sorted(CORES):
        for core in CORES[intent]:
            rng = random.Random(f"{seed}|{intent}|{core}")
            dev = bool(_DEV.search(core))
            light = intent in _LIGHT_INTENTS
            pre = _PRE_DEV if dev else (_PRE_LIGHT if light else _PRE)
            suf = _SUF_DEV if dev else (_SUF_LIGHT if light else _SUF)
            slotted = "{" in core
            n = per_core + (3 if slotted else 0)
            for k in range(n):
                base = _expand(core, intent, rng)
                if k == 0 and not slotted:
                    text = base
                else:
                    text = f"{rng.choice(pre)}{base}{rng.choice(suf)}".strip()
                key = (text, intent)
                if text and key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def counts(seed: int = 7) -> dict[str, int]:
    c: dict[str, int] = {}
    for _t, i in generate(seed):
        c[i] = c.get(i, 0) + 1
    return c


if __name__ == "__main__":  # pragma: no cover
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    for i, n in sorted(counts(seed).items()):
        print(f"# {i}: {n}")
    for t, i in generate(seed):
        print(f"{i}\t{t}")
