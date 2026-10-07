"""What simulated businesses / people say, per language, plus the keyword lists the
simulator uses to understand what Friday said. Deterministic, no LLM.

Lookup: ``phrase(lang, key)`` -> (text, language actually used). Missing keys fall back
to Hinglish, then English, and the returned language says which one was used, so the
simulated STT language tag is always honest.
"""

from __future__ import annotations

from friday.core.models import Language

L = Language

PHRASES: dict[Language, dict[str, str]] = {
    L.EN: {
        "ok": "Yes, tell me.",
        "ask_ai": "Wait, am I talking to a real person or a robot?",
        "ai_ack": "Oh okay, an AI assistant. Fine, go ahead.",
        "prices": "The charges are {prices}.",
        "rooms": "Yes, rooms are available: {prices} per night.",
        "slots": "We have {slots} available.",
        "no_slots": "Sorry, we are fully booked for now.",
        "discount": "Okay, for you I can do {price}.",
        "final_price": "{price} is the final price, I can't go lower.",
        "no_discount": "Sorry, our prices are fixed.",
        "hold_ok": "Okay, I'll keep it for you for some time.",
        "room_hold": "Okay, I can hold the room for {hours} hours.",
        "room_no_hold": "Sorry, we can't hold rooms without an advance.",
        "callback_ok": "Okay, call me back once you confirm.",
        "confirmed": "Done, it's booked for {slot}. Your booking number is {booking}.",
        "stock_yes": "Yes, {item} is available.",
        "stock_no": "Sorry, {item} is out of stock.",
        "bye": "Okay, thank you. Bye.",
        "unknown": "Sorry, could you say that again?",
        "hello": "Hello? Hello?",
        "hostile": "We don't talk to robots. Please don't call this number.",
        "advance": "To confirm we need an advance of {amount}.",
        "agent_greeting": "Hello, this is {rep} from {company}. How may I help you?",
        "ticket": (
            "I have registered your request. Your ticket number is {ticket}. It will be "
            "resolved within 48 hours, by {date}."
        ),
        "otp_ask": "For verification, please tell me the OTP sent to the registered mobile number.",
        "otp_insist": (
            "Sorry, I can't proceed without verifying the account holder. "
            "Can the account holder join the call?"
        ),
        "verified": "Thank you, the account holder is verified.",
        "escalate": "Let me transfer you to my supervisor, please hold.",
        "hold_ack": "Sure, take your time.",
        "note": "{note}.",
        "ivr_invalid": "Sorry, that is an invalid option.",
        "ivr_no_input": "We did not receive any input. Goodbye.",
        "ivr_bye": "Thank you for calling. Goodbye.",
        "queue": (
            "Your call is important to us. All our executives are busy. "
            "Estimated wait time is {minutes} minutes."
        ),
        "person_ok": "Yes, tell me.",
        "medicine": "Yes, I took my medicines this morning.",
        "feeling": "I'm feeling fine.",
        "sleep": "I slept well.",
        "food": "Yes, I had breakfast.",
        "needs": "No, I don't need anything.",
        "user_join": "Hi, I'm here.",
        "user_otp": "My OTP is 4 8 2 9 1 3.",
        "user_bye": "Thanks, bye.",
        "callback_greeting": "Hello, I got a call from this number. This is {name}.",
    },
    L.HINGLISH: {
        "ok": "Haan ji, boliye.",
        "ask_ai": "Ek minute, aap insaan ho ya robot?",
        "ai_ack": "Achha, AI assistant. Theek hai, boliye.",
        "prices": "Charges {prices} hai.",
        "rooms": "Haan ji, rooms available hain: {prices} per night.",
        "slots": "{slots} available hai.",
        "no_slots": "Sorry, abhi sab booked hai.",
        "discount": "Theek hai, aapke liye {price} kar dete hain.",
        "final_price": "{price} final hai, isse kam nahi hoga.",
        "no_discount": "Sorry, rate fixed hai.",
        "hold_ok": "Theek hai, thodi der ke liye rakh leta hoon.",
        "room_hold": "Theek hai, room {hours} ghante ke liye hold kar deta hoon.",
        "room_no_hold": "Sorry, advance ke bina room hold nahi kar sakte.",
        "callback_ok": "Theek hai ji, confirm karke call kar dijiye.",
        "confirmed": "Ho gaya, {slot} ke liye book hai. Booking number {booking} hai.",
        "stock_yes": "Haan ji, {item} available hai.",
        "stock_no": "Sorry, {item} abhi stock mein nahi hai.",
        "bye": "Theek hai ji, dhanyavaad. Bye.",
        "unknown": "Sorry, phir se boliye?",
        "hello": "Hello? Hello?",
        "hostile": "Hum robot se baat nahi karte. Is number pe call mat karna.",
        "advance": "Confirm karne ke liye {amount} advance lagega.",
        "agent_greeting": "Hello, {company} se {rep} bol rahi hoon. Bataiye kya help karun?",
        "ticket": (
            "Aapki request register ho gayi hai. Ticket number {ticket} hai. "
            "48 ghante mein, {date} tak resolve ho jayega."
        ),
        "otp_ask": "Verification ke liye registered mobile pe aaya OTP bataiye.",
        "otp_insist": (
            "Sorry, account holder verify kiye bina aage nahi badh sakte. "
            "Kya woh call pe aa sakte hain?"
        ),
        "verified": "Thank you, account holder verify ho gaye.",
        "escalate": "Main aapko supervisor ko transfer kar rahi hoon, please hold kijiye.",
        "hold_ack": "Haan ji, koi baat nahi.",
        "note": "{note}.",
        "person_ok": "Haan beta, bolo.",
        "medicine": "Haan beta, subah dawai le li.",
        "feeling": "Main theek hoon beta.",
        "sleep": "Neend achhi aayi.",
        "food": "Haan, nashta kar liya.",
        "needs": "Nahi beta, kuch nahi chahiye.",
        "user_join": "Haan, main hoon. Boliye.",
        "user_otp": "Mera OTP 4 8 2 9 1 3 hai.",
        "user_bye": "Theek hai, thank you. Bye.",
        "callback_greeting": "Hello, is number se call aaya tha. {name} se bol raha hoon.",
    },
    L.HI: {
        "ok": "हाँ जी, बोलिए।",
        "ask_ai": "एक मिनट, आप इंसान हैं या रोबोट?",
        "ai_ack": "अच्छा, AI असिस्टेंट। ठीक है, बोलिए।",
        "prices": "चार्ज {prices} है।",
        "rooms": "हाँ जी, कमरे उपलब्ध हैं: {prices} प्रति रात।",
        "slots": "{slots} खाली है।",
        "no_slots": "माफ़ कीजिए, अभी सब बुक है।",
        "discount": "ठीक है, आपके लिए {price} कर देते हैं।",
        "final_price": "{price} फाइनल है, इससे कम नहीं होगा।",
        "no_discount": "माफ़ कीजिए, रेट फिक्स है।",
        "hold_ok": "ठीक है, थोड़ी देर के लिए रख लेता हूँ।",
        "room_hold": "ठीक है, कमरा {hours} घंटे के लिए होल्ड कर देता हूँ।",
        "room_no_hold": "माफ़ कीजिए, एडवांस के बिना कमरा होल्ड नहीं कर सकते।",
        "callback_ok": "ठीक है जी, कन्फर्म करके कॉल कर दीजिए।",
        "confirmed": "हो गया, {slot} के लिए बुक है। बुकिंग नंबर {booking} है।",
        "stock_yes": "हाँ जी, {item} उपलब्ध है।",
        "stock_no": "माफ़ कीजिए, {item} अभी स्टॉक में नहीं है।",
        "bye": "ठीक है जी, धन्यवाद। नमस्ते।",
        "unknown": "माफ़ कीजिए, फिर से बोलिए?",
        "hello": "हैलो? हैलो?",
        "hostile": "हम रोबोट से बात नहीं करते। इस नंबर पर कॉल मत करना।",
        "advance": "कन्फर्म करने के लिए {amount} एडवांस लगेगा।",
        "agent_greeting": "नमस्ते, {company} से {rep} बोल रही हूँ। बताइए क्या मदद करूँ?",
        "ticket": "आपकी शिकायत दर्ज हो गई है। टिकट नंबर {ticket} है। {date} तक हल हो जाएगा।",
        "otp_ask": "वेरिफिकेशन के लिए रजिस्टर्ड मोबाइल पर आया OTP बताइए।",
        "otp_insist": "माफ़ कीजिए, खाताधारक को वेरिफाई किए बिना आगे नहीं बढ़ सकते।",
        "verified": "धन्यवाद, खाताधारक वेरिफाई हो गए।",
        "escalate": "मैं आपको सुपरवाइज़र को ट्रांसफर कर रही हूँ, कृपया होल्ड कीजिए।",
        "hold_ack": "हाँ जी, कोई बात नहीं।",
        "person_ok": "हाँ बेटा, बोलो।",
        "medicine": "हाँ बेटा, सुबह दवाई ले ली।",
        "feeling": "मैं ठीक हूँ बेटा।",
        "sleep": "नींद अच्छी आई।",
        "food": "हाँ, नाश्ता कर लिया।",
        "needs": "नहीं बेटा, कुछ नहीं चाहिए।",
        "callback_greeting": "हैलो, इस नंबर से कॉल आया था। {name} से बोल रहा हूँ।",
    },
    L.MR: {
        "ok": "हो, बोला.",
        "ask_ai": "एक मिनिट, तुम्ही माणूस आहात की रोबोट?",
        "ai_ack": "अच्छा, AI असिस्टंट. ठीक आहे, बोला.",
        "prices": "चार्ज {prices} आहे.",
        "rooms": "हो, खोल्या उपलब्ध आहेत: {prices} प्रति रात्र.",
        "slots": "{slots} मिळेल.",
        "no_slots": "माफ करा, सध्या सगळं बुक आहे.",
        "discount": "ठीक आहे, तुमच्यासाठी {price} करतो.",
        "final_price": "{price} फायनल आहे, यापेक्षा कमी नाही होणार.",
        "no_discount": "माफ करा, दर ठरलेला आहे.",
        "callback_ok": "ठीक आहे, कन्फर्म करून फोन करा.",
        "confirmed": "झालं, {slot} साठी बुक केलं आहे. बुकिंग नंबर {booking} आहे.",
        "stock_yes": "हो, {item} आहे.",
        "stock_no": "माफ करा, {item} नाही आहे.",
        "bye": "ठीक आहे, धन्यवाद. नमस्कार.",
        "unknown": "माफ करा, पुन्हा सांगा?",
        "hello": "हॅलो? हॅलो?",
        "hold_ack": "हो, काही हरकत नाही.",
        "person_ok": "हो बाळा, बोल.",
        "medicine": "हो, सकाळी गोळ्या घेतल्या.",
        "feeling": "मी बरी आहे.",
        "sleep": "झोप चांगली लागली.",
        "food": "हो, नाश्ता झाला.",
        "needs": "नाही, काही नको.",
        "user_join": "हो, मी आहे. बोला.",
    },
    L.KN: {
        "ok": "ಹೌದು, ಹೇಳಿ.",
        "ask_ai": "ಒಂದು ನಿಮಿಷ, ನೀವು ಮನುಷ್ಯರಾ ಅಥವಾ ರೋಬೋಟಾ?",
        "ai_ack": "ಸರಿ, AI ಅಸಿಸ್ಟೆಂಟ್. ಹೇಳಿ.",
        "prices": "ಚಾರ್ಜ್ {prices}.",
        "slots": "{slots} ಸಿಗುತ್ತೆ.",
        "no_slots": "ಕ್ಷಮಿಸಿ, ಎಲ್ಲಾ ಬುಕ್ ಆಗಿದೆ.",
        "discount": "ಸರಿ, ನಿಮಗೆ {price} ಮಾಡ್ತೀನಿ.",
        "final_price": "{price} ಫೈನಲ್, ಇದಕ್ಕಿಂತ ಕಡಿಮೆ ಆಗಲ್ಲ.",
        "no_discount": "ಕ್ಷಮಿಸಿ, ರೇಟ್ ಫಿಕ್ಸ್.",
        "callback_ok": "ಸರಿ, ಕನ್ಫರ್ಮ್ ಮಾಡಿ ಕಾಲ್ ಮಾಡಿ.",
        "confirmed": "ಆಯ್ತು, {slot} ಗೆ ಬುಕ್ ಆಗಿದೆ. ಬುಕಿಂಗ್ ನಂಬರ್ {booking}.",
        "stock_yes": "ಹೌದು, {item} ಇದೆ.",
        "stock_no": "ಕ್ಷಮಿಸಿ, {item} ಇಲ್ಲ.",
        "bye": "ಸರಿ, ಧನ್ಯವಾದ.",
        "unknown": "ಕ್ಷಮಿಸಿ, ಇನ್ನೊಮ್ಮೆ ಹೇಳಿ?",
        "hello": "ಹಲೋ? ಹಲೋ?",
    },
    L.TA: {
        "ok": "ஆமா, சொல்லுங்க.",
        "ask_ai": "ஒரு நிமிஷம், நீங்க மனுஷனா ரோபோவா?",
        "ai_ack": "சரி, AI உதவியாளர். சொல்லுங்க.",
        "prices": "கட்டணம் {prices}.",
        "slots": "{slots} இருக்கு.",
        "discount": "சரி, உங்களுக்கு {price} பண்றேன்.",
        "final_price": "{price} தான் கடைசி விலை.",
        "no_discount": "மன்னிக்கவும், விலை நிர்ணயம்.",
        "callback_ok": "சரி, உறுதி பண்ணிட்டு கூப்பிடுங்க.",
        "confirmed": "முடிஞ்சது, {slot} புக் ஆயிடுச்சு. புக்கிங் நம்பர் {booking}.",
        "bye": "சரி, நன்றி.",
        "unknown": "மன்னிக்கவும், மறுபடியும் சொல்லுங்க?",
        "hello": "ஹலோ? ஹலோ?",
    },
}


def phrase(language: Language, key: str, **params: object) -> tuple[str, Language]:
    for lang in (language, Language.HINGLISH, Language.EN):
        tpl = PHRASES.get(lang, {}).get(key)
        if tpl is not None:
            return tpl.format(**params), lang
    raise KeyError(key)


# ----------------------------------------------------------------- what Friday said
# Checked in this order by the simulator (first match wins).

KW_HOSTILE_TRIGGER = ("ai assistant", "main friday", "i'm friday", "i am friday", "मैं friday")
KW_BYE = ("bye", "dhanyavaad", "dhanyawad", "thank you", "thanks", "shukriya", "धन्यवाद",
          "goodbye", "alvida", "have a nice day", "नमस्कार")  # fmt: skip
KW_CALLBACK = ("call back", "callback", "call-back", "wapas call", "phir se call", "get back",
               "confirm karke", "check karke", "baad mein call", "पूछकर", "पूछ कर", "वापस",
               "call you back", "call karti hoon", "after checking", "confirm with")  # fmt: skip
KW_HOLDLINE = ("thank you for holding", "hold karne", "intezaar", "one moment", "ek minute",
               "ek second", "please hold", "kripya hold", "checking with", "check kar rahi",
               "होल्ड करने", "इंतज़ार", "still waiting")  # fmt: skip
KW_CONNECT = ("connecting you", "connect kar rahi", "joining now", "patch", "conference",
              "line par la rahi", "connect karti")  # fmt: skip
KW_HOLD_REQ = ("hold the room", "hold a room", "hold karke", "hold kar sakte", "hold kar dijiye",
               "block kar", "keep the slot", "hold the slot", "rok ke", "रोक", "होल्ड")  # fmt: skip
KW_CONFIRM = ("please confirm", "confirm kar dijiye", "confirm kijiye", "book kar dijiye",
              "book kar do", "pakka kar", "go ahead and book", "please book", "lock kar",
              "confirm the booking", "i confirm", "confirm it", "बुक कर दीजिए",
              "कन्फर्म कर दीजिए", "yes, book", "haan, book", "book it", "confirm karti hoon",
              "order kar dijiye", "place the order")  # fmt: skip
KW_DISCOUNT = ("discount", "kam ", "kam?", "kam kar", "less", "best price", "reduce", "lower",
               "better price", "package", "kuch kam", "कम", "quoted", "best rate", "final rate",
               "match", "negotiate", "thoda kam")  # fmt: skip
KW_PRICE = ("price", "rate", "kitna", "kitne", "charge", "cost", "fees", "fee", "quote",
            "कितना", "कितने", "दाम", "rent", "tariff", "किती", "kitni")  # fmt: skip
KW_ROOM = ("room", "kamra", "कमरा", "stay", "check-in", "check in", "night")
KW_SLOT = ("slot", "time", "appointment", "kab", "when", "timing", "samay", "समय", "book",
           "tomorrow", "kal", "today", "aaj", "available", "khali", "visit", "वेळ")  # fmt: skip
KW_COMPLAINT = ("complaint", "issue", "not working", "down", "problem", "refund", "shikayat",
                "शिकायत", "outage", "raise", "register")  # fmt: skip
KW_ESCALATE = ("supervisor", "escalate", "senior", "manager")
KW_OTP_REFUSAL = ("can't share", "cannot share", "nahi bata", "share nahi", "not able to share",
                  "verification codes", "can't read")  # fmt: skip
KW_AI_ANSWER = ("ai", "assistant", "robot", "bot", "एआई")
KW_MEDICINE = ("dawai", "dawa", "medicine", "tablet", "goli", "दवा", "गोळ्या", "meds")
KW_FEELING = ("kaise", "kaisi", "tabiyat", "feeling", "how are you", "तबीयत", "kasa", "kashi",
              "कसे", "theek ho", "health")  # fmt: skip
KW_SLEEP = ("neend", "sleep", "slept", "नींद", "झोप")
KW_FOOD = ("khana", "food", "nashta", "breakfast", "lunch", "eat", "खाना", "नाश्ता")
KW_NEEDS = ("chahiye", "need", "anything", "kuch aur", "चाहिए", "हवं", "नको")
