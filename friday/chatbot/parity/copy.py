# ruff: noqa: E501
"""ALL user-facing text of the slice-7 parity features lives here (and only here).

PENDING_FOUNDER_APPROVAL: nothing below has been approved. No spoken/voice line is touched.
Three variants of every line: ``hinglish`` (default), ``hi`` (Devanagari), ``en``.
Placeholders are ``{name}`` format fields.
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True
LANGS = ("hinglish", "hi", "en")

LINES: dict[str, dict[str, str]] = {
    "digest_head": {
        "hinglish": "Aapka inbox aur calendar dekh liya (sirf padha, kuch bheja nahi):",
        "hi": "आपका इनबॉक्स और कैलेंडर देख लिया (सिर्फ़ पढ़ा, कुछ भेजा नहीं):",
        "en": "I looked at your inbox and calendar (read only, nothing sent):",
    },
    "digest_leads": {
        "hinglish": "Jawab ka intezaar: {items}",
        "hi": "जवाब का इंतज़ार: {items}",
        "en": "Waiting for your reply: {items}",
    },
    "digest_phishing": {
        "hinglish": "Savdhan: '{subject}' PAN/KYC jaisi detail maang raha hai. Link mat kholiye, kuch mat bhejiye; yeh thagi ho sakti hai.",
        "hi": "सावधान: '{subject}' PAN/KYC जैसी जानकारी माँग रहा है। लिंक न खोलें, कुछ न भेजें; यह ठगी हो सकती है।",
        "en": "Careful: '{subject}' asks for PAN/KYC style details. Don't open the link or send anything; it may be a scam.",
    },
    "digest_storage": {
        "hinglish": "Storage {pct}% bhar chuka hai.",
        "hi": "स्टोरेज {pct}% भर चुका है।",
        "en": "Storage is {pct}% full.",
    },
    "digest_renewals": {
        "hinglish": "Renewal: {items}",
        "hi": "रिन्यूअल: {items}",
        "en": "Renewals: {items}",
    },
    "digest_empty": {
        "hinglish": "Abhi koi zaroori cheez nahi mili. Kuch naya aaya toh bataungi.",
        "hi": "अभी कोई ज़रूरी चीज़ नहीं मिली। कुछ नया आया तो बताऊँगी।",
        "en": "Nothing important found right now. I'll tell you if something new comes up.",
    },
    "digest_correction": {
        "hinglish": "Sudhaar: maine pehle kaha tha '{old}', par sahi yeh hai: '{new}'. Galti ke liye maaf kijiye.",
        "hi": "सुधार: मैंने पहले कहा था '{old}', पर सही यह है: '{new}'। गलती के लिए माफ़ कीजिए।",
        "en": "Correction: I earlier said '{old}', but the right answer is '{new}'. Sorry for the mistake.",
    },
    "memory_empty": {
        "hinglish": "Abhi mujhe aapke baare mein kuch yaad nahi hai.",
        "hi": "अभी मुझे आपके बारे में कुछ याद नहीं है।",
        "en": "I don't remember anything about you yet.",
    },
    "memory_head": {
        "hinglish": "Mujhe aapke baare mein yeh yaad hai:",
        "hi": "मुझे आपके बारे में यह याद है:",
        "en": "Here is what I remember about you:",
    },
    "memory_offer": {
        "hinglish": "Kuch bhulana ho toh likhiye 'forget <number>', ya 'forget all'.",
        "hi": "कुछ भुलाना हो तो लिखें 'forget <नंबर>', या 'forget all'।",
        "en": "To drop something, write 'forget <number>', or 'forget all'.",
    },
    "memory_forgot": {
        "hinglish": "Theek hai, bhool gayi: {what}",
        "hi": "ठीक है, भूल गई: {what}",
        "en": "Okay, forgotten: {what}",
    },
    "memory_forgot_all": {
        "hinglish": "Maine aapke baare mein sab bhula diya.",
        "hi": "मैंने आपके बारे में सब भुला दिया।",
        "en": "I forgot everything I knew about you.",
    },
    "memory_unknown": {
        "hinglish": "Yeh number list mein nahi hai. Pehle 'what do you remember' likhiye.",
        "hi": "यह नंबर सूची में नहीं है। पहले 'what do you remember' लिखें।",
        "en": "That number isn't on the list. Write 'what do you remember' first.",
    },
    "invite_status": {
        "hinglish": "Aapke paas {left} invite bache hain (kul {total}). Dost ko yeh link bhejiye: {link}",
        "hi": "आपके पास {left} इनवाइट बचे हैं (कुल {total})। दोस्त को यह लिंक भेजें: {link}",
        "en": "You have {left} invites left (of {total}). Send this link to a friend: {link}",
    },
    "invite_none": {
        "hinglish": "Abhi aapke paas koi invite nahi bacha.",
        "hi": "अभी आपके पास कोई इनवाइट नहीं बचा।",
        "en": "You have no invites left right now.",
    },
    "ride_uber": {
        "hinglish": "Uber ka link (login ki zaroorat nahi, app mein khulega): {link}",
        "hi": "Uber का लिंक (लॉगिन की ज़रूरत नहीं, ऐप में खुलेगा): {link}",
        "en": "Uber link (no login needed, opens in the app): {link}",
    },
    "ride_no_link": {
        "hinglish": "{app} ka koi official link nahi hai jo mujhe pakka pata ho, isliye galat link nahi bhejungi. App kholkar pickup aur drop daal dijiye.",
        "hi": "{app} का कोई आधिकारिक लिंक मुझे पक्का पता नहीं है, इसलिए गलत लिंक नहीं भेजूँगी। ऐप खोलकर पिकअप और ड्रॉप डाल दीजिए।",
        "en": "I don't know an official {app} link for sure, so I won't send a guessed one. Please open the app and enter pickup and drop.",
    },
    "status_working": {
        "hinglish": "Abhi kaam chal raha hai, lagbhag {eta} aur lagega. Pura hote hi bataungi.",
        "hi": "अभी काम चल रहा है, लगभग {eta} और लगेगा। पूरा होते ही बताऊँगी।",
        "en": "Still working on it, about {eta} more. I'll tell you as soon as it's done.",
    },
    "status_unknown_eta": {
        "hinglish": "Abhi kaam chal raha hai, time pakka nahi bata sakti. Pura hote hi bataungi.",
        "hi": "अभी काम चल रहा है, समय पक्का नहीं बता सकती। पूरा होते ही बताऊँगी।",
        "en": "Still working on it; I can't give a firm time. I'll tell you as soon as it's done.",
    },
    "price_usd_refused": {
        "hinglish": "Yeh route sirf dollar mein ya US card se chalta hai. Main sirf rupaye (INR) wale tareeke batati hoon; koi Indian option dhoondh dun?",
        "hi": "यह रास्ता सिर्फ़ डॉलर या US कार्ड से चलता है। मैं सिर्फ़ रुपये (INR) वाले तरीके बताती हूँ; कोई भारतीय विकल्प ढूँढूँ?",
        "en": "This route works only in dollars or with a US card. I only suggest rupee (INR) options; shall I look for an Indian one?",
    },
    "forgery_reference": {
        "hinglish": "Nakli bill ya document main nahi bana sakti, na sample de sakti hoon. Asli bill chahiye toh pump/dukaan se duplicate bill maang lijiye; main uske liye message ya call kar sakti hoon.",
        "hi": "नकली बिल या दस्तावेज़ मैं नहीं बना सकती, न नमूना दे सकती हूँ। असली बिल चाहिए तो पंप/दुकान से डुप्लीकेट बिल माँग लीजिए; मैं उसके लिए मैसेज या कॉल कर सकती हूँ।",
        "en": "I can't make a fake bill or document, or give a sample. If you need the real bill, ask the pump or shop for a duplicate; I can message or call them for you.",
    },
    "secure_page": {
        "hinglish": "{what} chat mein mat bhejiye. Is surakshit page par daaliye: {link}",
        "hi": "{what} चैट में न भेजें। इस सुरक्षित पेज पर डालें: {link}",
        "en": "Please don't send {what} in chat. Enter it on this secure page: {link}",
    },
    "secure_pasted": {
        "hinglish": "Lagta hai aapne {what} chat mein bhej diya. Ise dobara mat bhejiye; main ise save nahi karti. Zaroorat ho toh surakshit page use kijiye: {link}",
        "hi": "लगता है आपने {what} चैट में भेज दिया। इसे दोबारा न भेजें; मैं इसे सेव नहीं करती। ज़रूरत हो तो सुरक्षित पेज इस्तेमाल करें: {link}",
        "en": "It looks like you sent {what} in chat. Please don't send it again; I don't save it. If needed, use the secure page: {link}",
    },
    "field_otp": {"hinglish": "OTP", "hi": "OTP", "en": "an OTP"},
    "field_dob": {"hinglish": "janm tithi", "hi": "जन्म तिथि", "en": "your date of birth"},
    "field_address": {"hinglish": "pata (address)", "hi": "पता", "en": "your address"},
    "field_card": {"hinglish": "card ki detail", "hi": "कार्ड की जानकारी", "en": "card details"},
    "clash_head": {
        "hinglish": "Heads-up: {a} aur {b} ek hi time par hain ({when}).",
        "hi": "ध्यान दें: {a} और {b} एक ही समय पर हैं ({when})।",
        "en": "Heads-up: {a} and {b} overlap ({when}).",
    },
    "new_invite": {
        "hinglish": "Calendar mein naya invite aaya hai: {title} ({when}).",
        "hi": "कैलेंडर में नया इनवाइट आया है: {title} ({when})।",
        "en": "A new invite landed on your calendar: {title} ({when}).",
    },
    "escalate_ack_ask": {
        "hinglish": "Reminder: {what}. Dekh liya ho toh 'done' likhiye.",
        "hi": "रिमाइंडर: {what}। देख लिया हो तो 'done' लिखें।",
        "en": "Reminder: {what}. Reply 'done' once you've seen it.",
    },
}


def line(key: str, lang: str = "hinglish", **kw: str) -> str:
    variants = LINES[key]
    text = variants.get(lang) or variants["hinglish"]
    return text.format(**kw) if kw else text


def all_ids() -> list[str]:
    return [f"parity.line.{k}" for k in LINES]
