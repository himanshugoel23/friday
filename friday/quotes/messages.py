# ruff: noqa: E501
"""EVERY user-facing WhatsApp text of the quotes flow, in one table (en / hinglish / hi).

Edit copy HERE only; docs/WHATSAPP_QUOTES_FLOW.md lists the same texts (a test keeps them in
sync). Rules: short, one question at a time, no emoji, honest that Friday is an AI.
Languages mirror the user: ``en`` English, ``hinglish`` Roman Hindi, ``hi`` Devanagari.
Placeholders use ``str.format`` names. Button titles are at most 20 characters.
"""

from __future__ import annotations

LANGS = ("en", "hinglish", "hi")

MESSAGES: dict[str, dict[str, str]] = {
    "ask_services": {
        "en": "Which service do you need? For example haircut, beard trim, facial, waxing.",
        "hinglish": "Kaunsi service chahiye? Jaise haircut, beard trim, facial, waxing.",
        "hi": "कौन सी सर्विस चाहिए? जैसे हेयरकट, बीयर्ड ट्रिम, फेशियल, वैक्सिंग।",
    },
    "ask_for_name": {
        "en": "Who is it for? Please tell me their name.",
        "hinglish": "Kiske liye hai? Unka naam bata dijiye.",
        "hi": "किसके लिए है? उनका नाम बता दीजिए।",
    },
    "ask_when": {
        "en": "When do you want it? For example: tomorrow evening 6pm.",
        "hinglish": "Kab chahiye? Jaise: kal shaam 6 baje.",
        "hi": "कब चाहिए? जैसे: कल शाम 6 बजे।",
    },
    "ask_location": {
        "en": "Where are you? Send a location pin, or type it like 'Sector 56 Gurgaon'.",
        "hinglish": "Aap kahan hain? Location pin bhejiye, ya likhiye jaise 'Sector 56 Gurgaon'.",
        "hi": "आप कहाँ हैं? लोकेशन पिन भेजिए, या लिखिए जैसे 'Sector 56 Gurgaon'।",
    },
    "ask_book_time": {
        "en": "What time should I book? For example: 6pm.",
        "hinglish": "Kitne baje ka slot book karun? Jaise: 6 baje.",
        "hi": "कितने बजे का स्लॉट बुक करूँ? जैसे: 6 बजे।",
    },
    "wrong_city": {
        "en": "For now I only work in Gurgaon and Bangalore. More cities soon.",
        "hinglish": "Abhi sirf Gurgaon aur Bangalore mein kaam karti hoon. Jaldi aur shehar aayenge.",
        "hi": "अभी सिर्फ़ गुड़गाँव और बेंगलुरु में काम करती हूँ। जल्दी और शहर आएँगे।",
    },
    "location_unclear": {
        "en": "I could not find that place. Type the area and city, like 'Indiranagar Bangalore'.",
        "hinglish": "Yeh jagah mujhe nahi mili. Area aur city likhiye, jaise 'Indiranagar Bangalore'.",
        "hi": "यह जगह मुझे नहीं मिली। एरिया और शहर लिखिए, जैसे 'Indiranagar Bangalore'।",
    },
    "searching": {
        "en": "Okay, looking for places near you.",
        "hinglish": "Theek hai, aas-paas ke parlour dhoondh rahi hoon.",
        "hi": "ठीक है, आस-पास के पार्लर ढूँढ रही हूँ।",
    },
    "shortlist": {
        "en": (
            "Found {n} places near {where}:\n{lines}\n"
            "I am Friday, an AI assistant. Shall I call them for you and ask the price of "
            "{services}?"
        ),
        "hinglish": (
            "{where} ke paas {n} jagah mili:\n{lines}\n"
            "Main Friday hoon, AI assistant. Kya main inhe aapki taraf se call karke "
            "{services} ka rate puchun?"
        ),
        "hi": (
            "{where} के पास {n} जगह मिलीं:\n{lines}\n"
            "मैं Friday हूँ, एक AI असिस्टेंट। क्या मैं इन्हें आपकी तरफ़ से कॉल करके "
            "{services} का रेट पूछूँ?"
        ),
    },
    "btn_call": {"en": "Yes, call them", "hinglish": "Haan, call karo", "hi": "हाँ, कॉल करो"},
    "btn_change": {"en": "Change", "hinglish": "Badlo", "hi": "बदलो"},
    "btn_retry": {"en": "Try again", "hinglish": "Dobara try karo", "hi": "फिर से कोशिश"},
    "btn_others": {"en": "Other places", "hinglish": "Doosre dekho", "hi": "दूसरे देखो"},
    "no_vendors": {
        "en": "I could not find a place with a phone number near there. Try another area?",
        "hinglish": "Wahan aas-paas koi aisi jagah nahi mili jiska number ho. Doosra area bataiye?",
        "hi": "वहाँ आस-पास ऐसी कोई जगह नहीं मिली जिसका नंबर हो। दूसरा एरिया बताइए?",
    },
    "no_more_vendors": {
        "en": "No more places to show in that area. Tell me another area?",
        "hinglish": "Is area mein aur options nahi hain. Doosra area bataiye?",
        "hi": "इस एरिया में और विकल्प नहीं हैं। दूसरा एरिया बताइए?",
    },
    "calling": {  # sent ONLY when the user switched "updates on" (founder rule: no stage pings)
        "en": "Okay, calling them now. I will send all the quotes together.",
        "hinglish": "Theek hai, call kar rahi hoon. Saare quotes ek saath bhejungi.",
        "hi": "ठीक है, कॉल कर रही हूँ। सारे कोट्स एक साथ भेजूँगी।",
    },
    "queued": {
        "en": "They are closed for calls now. I will call at {when} and send the quotes.",
        "hinglish": "Abhi unhe call karne ka time nahi hai. {when} call karungi, phir quotes bhejungi.",
        "hi": "अभी उन्हें कॉल करने का समय नहीं है। {when} कॉल करूँगी, फिर कोट्स भेजूँगी।",
    },
    "comparison_head": {
        "en": "Quotes for {services} ({when}):",
        "hinglish": "{services} ke quotes ({when}):",
        "hi": "{services} के कोट्स ({when}):",
    },
    "quote_line": {
        "en": "{name}: Rs {price}",
        "hinglish": "{name}: Rs {price}",
        "hi": "{name}: Rs {price}",
    },
    "unpriced_line": {
        "en": "{name}: they did not give a price",
        "hinglish": "{name}: unhone price nahi bataya",
        "hi": "{name}: उन्होंने कीमत नहीं बताई",
    },
    "no_answer_tail": {
        "en": "{n} did not pick up.",
        "hinglish": "{n} ne phone nahi uthaya.",
        "hi": "{n} ने फ़ोन नहीं उठाया।",
    },
    "declined_tail": {
        "en": "{n} could not help.",
        "hinglish": "{n} ne mana kiya.",
        "hi": "{n} ने मना किया।",
    },
    "book_prompt": {
        "en": "Tap to book:",
        "hinglish": "Book karna ho to dabaiye:",
        "hi": "बुक करना हो तो दबाइए:",
    },
    "book_btn": {"en": "Book {name} {time}", "hinglish": "Book {name} {time}", "hi": "बुक {name} {time}"},
    "none_worked": {
        "en": "No quotes this time: {why}. Try again, or see other places?",
        "hinglish": "Is baar koi quote nahi mila: {why}. Dobara try karun ya doosre dekhun?",
        "hi": "इस बार कोई कोट नहीं मिला: {why}। फिर कोशिश करूँ या दूसरे देखूँ?",
    },
    "why_no_answer": {
        "en": "nobody picked up",
        "hinglish": "kisi ne phone nahi uthaya",
        "hi": "किसी ने फ़ोन नहीं उठाया",
    },
    "why_declined": {
        "en": "they could not help",
        "hinglish": "sabne mana kiya",
        "hi": "सबने मना किया",
    },
    "why_mixed": {
        "en": "no price was given",
        "hinglish": "kisi ne price nahi bataya",
        "hi": "किसी ने कीमत नहीं बताई",
    },
    "book_calling": {
        "en": "Okay, calling {name} to book {when}.",
        "hinglish": "Theek hai, {name} ko {when} ke liye book karne call kar rahi hoon.",
        "hi": "ठीक है, {name} को {when} के लिए बुक करने कॉल कर रही हूँ।",
    },
    "booked": {
        "en": "Booked: {name}, {when}, Rs {price}.",
        "hinglish": "Booking pakki: {name}, {when}, Rs {price}.",
        "hi": "बुकिंग पक्की: {name}, {when}, Rs {price}।",
    },
    "book_failed": {
        "en": "Could not book {name}: {why}.",
        "hinglish": "{name} mein booking nahi ho payi: {why}.",
        "hi": "{name} में बुकिंग नहीं हो पाई: {why}।",
    },
    "bwhy_no_slot": {
        "en": "that time was not free",
        "hinglish": "us time ka slot khali nahi tha",
        "hi": "उस समय का स्लॉट खाली नहीं था",
    },
    "bwhy_price": {
        "en": "the price was higher than the quote",
        "hinglish": "price quote se zyada tha",
        "hi": "कीमत कोट से ज़्यादा थी",
    },
    "bwhy_no_answer": {
        "en": "they did not pick up",
        "hinglish": "unhone phone nahi uthaya",
        "hi": "उन्होंने फ़ोन नहीं उठाया",
    },
    "bwhy_other": {
        "en": "the call did not finish properly",
        "hinglish": "baat poori nahi ho payi",
        "hi": "बात पूरी नहीं हो पाई",
    },
    "cancelled": {
        "en": "Okay, cancelled. Message me anytime for a new request.",
        "hinglish": "Theek hai, cancel kar diya. Nayi request kabhi bhi bhej dijiye.",
        "hi": "ठीक है, कैंसल कर दिया। नई रिक्वेस्ट कभी भी भेज दीजिए।",
    },
    "stopped": {
        "en": "Stopped everything. Message me again whenever you want to start.",
        "hinglish": "Sab kuch band kar diya. Dobara shuru karna ho to kabhi bhi likhiye.",
        "hi": "सब कुछ बंद कर दिया। दोबारा शुरू करना हो तो कभी भी लिखिए।",
    },
    "voice_note": {
        "en": "I cannot listen to voice notes yet. Please type it.",
        "hinglish": "Abhi main voice note nahi sun paati. Text mein likh dijiye please.",
        "hi": "अभी मैं वॉइस नोट नहीं सुन पाती। कृपया टेक्स्ट में लिखिए।",
    },
    "daily_cap": {
        "en": "You have used {n} requests today. Please ask again tomorrow.",
        "hinglish": "Aaj ki {n} requests ho chuki hain. Kal phir bhejiye.",
        "hi": "आज की {n} रिक्वेस्ट हो चुकी हैं। कल फिर भेजिए।",
    },
    "busy": {
        "en": "Your last request is still running. Type 'cancel' to stop it.",
        "hinglish": "Pichli request abhi chal rahi hai. Rokni ho to 'cancel' likhiye.",
        "hi": "पिछली रिक्वेस्ट अभी चल रही है। रोकनी हो तो 'cancel' लिखिए।",
    },
    "paused": {
        "en": "I am on a short break and cannot make calls right now. Please try later.",
        "hinglish": "Main thodi der ke break par hoon, abhi calls nahi kar sakti. Baad mein try kijiye.",
        "hi": "मैं थोड़ी देर के ब्रेक पर हूँ, अभी कॉल नहीं कर सकती। बाद में कोशिश कीजिए।",
    },
    "places_failed": {
        "en": "I cannot search places right now. Please try again in a while.",
        "hinglish": "Abhi parlour search nahi ho pa raha. Thodi der baad dobara try kijiye.",
        "hi": "अभी पार्लर सर्च नहीं हो पा रहा। थोड़ी देर बाद फिर कोशिश कीजिए।",
    },
    "calls_failed": {
        "en": "I could not place the calls. Please try again in a while.",
        "hinglish": "Call lagane mein dikkat aayi. Thodi der baad dobara try kijiye.",
        "hi": "कॉल लगाने में दिक्कत आई। थोड़ी देर बाद फिर कोशिश कीजिए।",
    },
    "test_mode_blocked": {
        "en": "In test mode I cannot call real places. Nothing was called.",
        "hinglish": "Test mode mein asli jagah ko call nahi kar sakti. Kisi ko call nahi gaya.",
        "hi": "टेस्ट मोड में असली जगहों को कॉल नहीं कर सकती। किसी को कॉल नहीं गया।",
    },
    "stale": {
        "en": "That option is no longer valid. Send a new request.",
        "hinglish": "Yeh option ab valid nahi hai. Nayi request bhejiye.",
        "hi": "यह विकल्प अब मान्य नहीं है। नई रिक्वेस्ट भेजिए।",
    },
    "tap_choice": {
        "en": "Please tap one of the buttons, or tell me a different area.",
        "hinglish": "Button dabaiye, ya doosra area bataiye.",
        "hi": "बटन दबाइए, या दूसरा एरिया बताइए।",
    },
    "status_working": {
        "en": "Still working on it. I will message you when the quotes are ready.",
        "hinglish": "Abhi kaam chal raha hai. Quotes aate hi message karungi.",
        "hi": "अभी काम चल रहा है। कोट्स आते ही मैसेज करूँगी।",
    },
    "status_queued": {
        "en": "Calls start {when}. I will message you when the quotes are ready.",
        "hinglish": "Calls {when} shuru hongi. Quotes aate hi message karungi.",
        "hi": "कॉल {when} शुरू होंगी। कोट्स आते ही मैसेज करूँगी।",
    },
    "updates_on": {
        "en": "Okay, I will send progress updates for this request.",
        "hinglish": "Theek hai, is request ke progress updates bhejungi.",
        "hi": "ठीक है, इस रिक्वेस्ट के प्रोग्रेस अपडेट भेजूँगी।",
    },
    "updates_off": {
        "en": "Okay, no progress updates. I will message you with the result.",
        "hinglish": "Theek hai, updates nahi bhejungi. Result aate hi message karungi.",
        "hi": "ठीक है, अपडेट नहीं भेजूँगी। रिज़ल्ट आते ही मैसेज करूँगी।",
    },
    "status_none": {
        "en": "No request yet. Tell me what you need, like 'haircut tomorrow evening'.",
        "hinglish": "Abhi koi request nahi hai. Bataiye kya chahiye, jaise 'kal shaam haircut'.",
        "hi": "अभी कोई रिक्वेस्ट नहीं है। बताइए क्या चाहिए, जैसे 'कल शाम हेयरकट'।",
    },
    "sms_summary": {
        "en": "Friday: {text}",
        "hinglish": "Friday: {text}",
        "hi": "Friday: {text}",
    },
}

SERVICE_LABELS: dict[str, dict[str, str]] = {
    "haircut": {"en": "haircut", "hinglish": "haircut", "hi": "हेयरकट"},
    "beard trim": {"en": "beard trim", "hinglish": "beard trim", "hi": "बीयर्ड ट्रिम"},
    "shave": {"en": "shave", "hinglish": "shave", "hi": "शेव"},
    "hair spa": {"en": "hair spa", "hinglish": "hair spa", "hi": "हेयर स्पा"},
    "hair colour": {"en": "hair colour", "hinglish": "hair colour", "hi": "हेयर कलर"},
    "facial": {"en": "facial", "hinglish": "facial", "hi": "फेशियल"},
    "manicure": {"en": "manicure", "hinglish": "manicure", "hi": "मैनिक्योर"},
    "pedicure": {"en": "pedicure", "hinglish": "pedicure", "hi": "पेडिक्योर"},
    "waxing": {"en": "waxing", "hinglish": "waxing", "hi": "वैक्सिंग"},
    "threading": {"en": "threading", "hinglish": "threading", "hi": "थ्रेडिंग"},
    "keratin": {"en": "keratin", "hinglish": "keratin", "hi": "केराटिन"},
    "massage": {"en": "massage", "hinglish": "massage", "hi": "मसाज"},
    "head massage": {"en": "head massage", "hinglish": "head massage", "hi": "हेड मसाज"},
    "spa": {"en": "spa", "hinglish": "spa", "hi": "स्पा"},
}
AND = {"en": " and ", "hinglish": " aur ", "hi": " और "}


def msg(key: str, lang: str = "hinglish", **kw: object) -> str:
    table = MESSAGES[key]
    text = table.get(lang) or table["hinglish"]
    return text.format(**kw) if kw else text


def services_text(services: list[str], lang: str) -> str:
    names = [SERVICE_LABELS.get(s, {}).get(lang, s) for s in services] or ["haircut"]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + AND.get(lang, " aur ") + names[-1]
