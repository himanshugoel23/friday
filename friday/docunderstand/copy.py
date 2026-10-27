# ruff: noqa: E501
"""Every user-facing line of the document feature. STATUS: PENDING_FOUNDER_APPROVAL for all of it.

Hear-before-change (CLAUDE.md rule 3): none of this wording may reach a real user until the
founder has approved it; ``FRIDAY_DOCS_ENABLED`` stays OFF until then. There are no spoken lines.
Three languages per line: ``hinglish`` (default, Roman), ``en`` and ``hi`` (Devanagari). Document
text is NEVER interpolated except the structured, sanitised field values listed in ``labels``.
Button titles are at most 20 characters (WhatsApp).
"""

from __future__ import annotations

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
PENDING_FOUNDER_APPROVAL = True
LANGS = ("hinglish", "en", "hi")
DEFAULT_LANGUAGE = "hinglish"
BUTTON_PREFIX = "doc:"

TEXTS: dict[str, dict[str, str]] = {
    "head.flight_ticket": {
        "hinglish": "Yeh flight ticket lag raha hai:",
        "en": "This looks like a flight ticket:",
        "hi": "यह फ्लाइट टिकट लग रहा है:",
    },
    "head.train_ticket": {
        "hinglish": "Yeh train ticket lag raha hai:",
        "en": "This looks like a train ticket:",
        "hi": "यह ट्रेन टिकट लग रहा है:",
    },
    "head.hotel_confirmation": {
        "hinglish": "Yeh hotel booking lag rahi hai:",
        "en": "This looks like a hotel booking:",
        "hi": "यह होटल बुकिंग लग रही है:",
    },
    "head.passport": {
        "hinglish": "Yeh passport lag raha hai:",
        "en": "This looks like a passport:",
        "hi": "यह पासपोर्ट लग रहा है:",
    },
    "head.bill": {
        "hinglish": "Yeh bill lag raha hai:",
        "en": "This looks like a bill:",
        "hi": "यह बिल लग रहा है:",
    },
    "head.generic": {
        "hinglish": "Yeh maine samjha:",
        "en": "Here is what I understood:",
        "hi": "यह मैंने समझा:",
    },
    "ask": {"hinglish": "Sahi hai?", "en": "Is this right?", "hi": "सही है?"},
    "unsure": {"hinglish": "pakka nahi", "en": "not sure", "hi": "पक्का नहीं"},
    "btn.ok": {"hinglish": "Haan, sahi hai", "en": "Yes, correct", "hi": "हाँ, सही है"},
    "btn.fix": {"hinglish": "Galat hai", "en": "Something is wrong", "hi": "गलत है"},
    "btn.drop": {"hinglish": "Rehne do", "en": "Skip it", "hi": "रहने दो"},
    "note.passport": {
        "hinglish": "Passport number ke sirf aakhri 3 akshar dikhati hoon. Photo save nahi karti.",
        "en": "I show only the last 3 characters of the passport number. I do not keep the photo.",
        "hi": "पासपोर्ट नंबर के सिर्फ़ आखिरी 3 अक्षर दिखाती हूँ। फोटो सेव नहीं करती।",
    },
    "note.injection": {
        "hinglish": "Is file mein aise lafz the jo hukm jaise lagte the. Maine unhe nahi mana; sirf details padhi hain. Dhyan se check kar lo.",
        "en": "This file had text that sounded like instructions. I ignored it and only read the details. Please check them carefully.",
        "hi": "इस फ़ाइल में हुक्म जैसे शब्द थे। मैंने उन्हें नहीं माना, सिर्फ़ जानकारी पढ़ी है। ध्यान से देख लो।",
    },
    "note.arrival_before_departure": {
        "hinglish": "Pahunchne ka time nikalne ke time se pehle dikh raha hai. Check kar lo.",
        "en": "The arrival time looks earlier than the departure. Please check.",
        "hi": "पहुँचने का समय निकलने के समय से पहले दिख रहा है। देख लो।",
    },
    "note.same_place": {
        "hinglish": "Shuru aur aakhri jagah ek jaisi dikh rahi hai. Check kar lo.",
        "en": "The start and end look like the same place. Please check.",
        "hi": "शुरू और आखिरी जगह एक जैसी दिख रही है। देख लो।",
    },
    "note.date_out_of_range": {
        "hinglish": "Yeh tareekh bahut door ya bahut purani hai. Check kar lo.",
        "en": "This date looks very far off or very old. Please check.",
        "hi": "यह तारीख़ बहुत दूर या बहुत पुरानी है। देख लो।",
    },
    "note.checkout_before_checkin": {
        "hinglish": "Check-out check-in se pehle dikh raha hai. Check kar lo.",
        "en": "Check-out looks earlier than check-in. Please check.",
        "hi": "चेक-आउट चेक-इन से पहले दिख रहा है। देख लो।",
    },
    "note.expiry_before_issue": {
        "hinglish": "Expiry date issue date se pehle dikh rahi hai. Check kar lo.",
        "en": "The expiry date looks earlier than the issue date. Please check.",
        "hi": "एक्सपायरी तारीख़ जारी होने की तारीख़ से पहले दिख रही है। देख लो।",
    },
    "note.dob_in_future": {
        "hinglish": "Janam tareekh aage ki dikh rahi hai. Check kar lo.",
        "en": "The date of birth is in the future. Please check.",
        "hi": "जन्म तारीख़ आगे की दिख रही है। देख लो।",
    },
    "note.issue_before_dob": {
        "hinglish": "Issue date janam tareekh se pehle dikh rahi hai. Check kar lo.",
        "en": "The issue date looks earlier than the date of birth. Please check.",
        "hi": "जारी होने की तारीख़ जन्म तारीख़ से पहले दिख रही है। देख लो।",
    },
    "note.expires_soon": {
        "hinglish": "Dhyan do: passport 6 mahine ke andar expire ho raha hai (ya ho chuka hai).",
        "en": "Heads up: this passport expires within 6 months (or already has).",
        "hi": "ध्यान दो: पासपोर्ट 6 महीने के अंदर एक्सपायर हो रहा है (या हो चुका है)।",
    },
    "note.min_due_above_total": {
        "hinglish": "Minimum due total se zyada dikh raha hai. Check kar lo.",
        "en": "The minimum due looks higher than the total. Please check.",
        "hi": "मिनिमम ड्यू टोटल से ज़्यादा दिख रहा है। देख लो।",
    },
    "note.no_amount_or_due": {
        "hinglish": "Amount aur due date dono nahi mile. Check kar lo.",
        "en": "I could not find the amount or the due date. Please check.",
        "hi": "अमाउंट और ड्यू डेट दोनों नहीं मिले। देख लो।",
    },
    "fix.ask": {
        "hinglish": 'Kaunsi cheez galat hai? Aise likho: naam: sahi value (jaise "{example}"). Ya "rehne do" likho.',
        "en": 'What is wrong? Write it like this: name: correct value (for example "{example}"). Or write "skip".',
        "hi": 'क्या गलत है? ऐसे लिखो: नाम: सही वैल्यू (जैसे "{example}")। या "रहने दो" लिखो।',
    },
    "fix.passport_hint": {
        "hinglish": "Passport number poora mat bhejo, sirf aakhri 3 akshar.",
        "en": "Do not send the full passport number, only the last 3 characters.",
        "hi": "पासपोर्ट नंबर पूरा मत भेजो, सिर्फ़ आखिरी 3 अक्षर।",
    },
    "fix.bad_value": {
        "hinglish": '"{label}" ki yeh value samajh nahi aayi. Dobara likho, ya "rehne do".',
        "en": 'I could not understand that value for "{label}". Please write it again, or "skip".',
        "hi": '"{label}" की यह वैल्यू समझ नहीं आई। दोबारा लिखो, या "रहने दो"।',
    },
    "fix.refused": {
        "hinglish": "Aadhaar ya aisi sarkari ID ke number main nahi rakhti. Yeh value nahi li.",
        "en": "I do not keep Aadhaar or other government-ID numbers. I did not take that value.",
        "hi": "आधार या ऐसी सरकारी ID के नंबर मैं नहीं रखती। यह वैल्यू नहीं ली।",
    },
    "saved": {
        "hinglish": "Theek hai, yeh details save kar li.",
        "en": "Done, I saved these details.",
        "hi": "ठीक है, ये जानकारी सेव कर ली।",
    },
    "saved.bill": {
        "hinglish": "Theek hai, bill yaad rakh liya. Due date se pehle yaad dilaungi.",
        "en": "Done, I noted the bill. I will remind you before the due date.",
        "hi": "ठीक है, बिल याद रख लिया। ड्यू डेट से पहले याद दिलाऊँगी।",
    },
    "dropped": {
        "hinglish": "Theek hai, kuch save nahi kiya.",
        "en": "Okay, I did not save anything.",
        "hi": "ठीक है, कुछ सेव नहीं किया।",
    },
    "already": {
        "hinglish": "Yeh pehle hi ho chuka hai.",
        "en": "That is already done.",
        "hi": "यह पहले ही हो चुका है।",
    },
    "gone": {
        "hinglish": "Yeh file ab meri yaad mein nahi hai. Phir se bhej do.",
        "en": "I no longer have that file's details. Please send it again.",
        "hi": "यह फ़ाइल अब मेरी याद में नहीं है। फिर से भेज दो।",
    },
    "refuse.gov_id": {
        "hinglish": "Yeh Aadhaar ya sarkari ID lag rahi hai. Main inke number padhti ya rakhti nahi hoon, isliye maine kuch save nahi kiya.",
        "en": "This looks like an Aadhaar or other government ID. I never read or keep those numbers, so I saved nothing.",
        "hi": "यह आधार या सरकारी ID लग रही है। मैं इनके नंबर पढ़ती या रखती नहीं, इसलिए कुछ सेव नहीं किया।",
    },
    "refuse.bad_type": {
        "hinglish": "Main sirf photo (JPG, PNG, WebP) ya PDF padh sakti hoon.",
        "en": "I can only read photos (JPG, PNG, WebP) or PDFs.",
        "hi": "मैं सिर्फ़ फोटो (JPG, PNG, WebP) या PDF पढ़ सकती हूँ।",
    },
    "refuse.too_big": {
        "hinglish": "Yeh file bahut badi hai. Chhoti photo ya PDF bhej do.",
        "en": "This file is too big. Please send a smaller photo or PDF.",
        "hi": "यह फ़ाइल बहुत बड़ी है। छोटी फोटो या PDF भेज दो।",
    },
    "refuse.too_many_pages": {
        "hinglish": "Is PDF mein bahut pages hain. Sirf zaroori page bhej do.",
        "en": "This PDF has too many pages. Please send only the page that matters.",
        "hi": "इस PDF में बहुत पेज हैं। सिर्फ़ ज़रूरी पेज भेज दो।",
    },
    "refuse.limit": {
        "hinglish": "Aaj ke liye itni files padh li. Kal phir bhej dena.",
        "en": "That is all the files I can read today. Please send more tomorrow.",
        "hi": "आज के लिए इतनी फ़ाइलें पढ़ लीं। कल फिर भेज देना।",
    },
    "refuse.unreadable": {
        "hinglish": "Yeh saaf padh nahi paayi. Roshni mein, seedhi photo phir se bhej do.",
        "en": "I could not read this clearly. Please send a straight photo in good light.",
        "hi": "यह साफ़ पढ़ नहीं पाई। रोशनी में सीधी फोटो फिर से भेज दो।",
    },
    "refuse.unavailable": {
        "hinglish": "Abhi main files nahi padh sakti. Thodi der baad try karo.",
        "en": "I cannot read files right now. Please try again a little later.",
        "hi": "अभी मैं फ़ाइलें नहीं पढ़ सकती। थोड़ी देर बाद कोशिश करो।",
    },
    "refuse.sensitive": {
        "hinglish": "Is file mein card ya PIN jaisi private cheezein dikh rahi hain. Maine kuch save nahi kiya. Aisi cheezein mat bhejna.",
        "en": "This file shows private things like card or PIN details. I saved nothing. Please do not send those.",
        "hi": "इस फ़ाइल में कार्ड या PIN जैसी निजी चीज़ें दिख रही हैं। कुछ सेव नहीं किया। ऐसी चीज़ें मत भेजना।",
    },
    "refuse.failed": {
        "hinglish": "Yeh file padhte waqt gadbad ho gayi. Phir se bhej do.",
        "en": "Something went wrong reading this file. Please send it again.",
        "hi": "यह फ़ाइल पढ़ते समय गड़बड़ हो गई। फिर से भेज दो।",
    },
    "money": {"hinglish": "Rs {amount}", "en": "Rs {amount}", "hi": "₹{amount}"},
    "yes": {"hinglish": "haan", "en": "yes", "hi": "हाँ"},
    "no": {"hinglish": "nahi", "en": "no", "hi": "नहीं"},
}

# field -> (hinglish, en, hi) label
LABELS: dict[str, tuple[str, str, str]] = {
    "passengers": ("Yatri", "Passengers", "यात्री"),
    "airline": ("Airline", "Airline", "एयरलाइन"),
    "flight_no": ("Flight", "Flight", "फ्लाइट"),
    "from_iata": ("Kahan se", "From", "कहाँ से"),
    "to_iata": ("Kahan tak", "To", "कहाँ तक"),
    "dep_local": ("Nikalna", "Departs", "निकलना"),
    "arr_local": ("Pahunchna", "Arrives", "पहुँचना"),
    "terminal": ("Terminal", "Terminal", "टर्मिनल"),
    "pnr": ("PNR", "PNR", "PNR"),
    "seat": ("Seat", "Seat", "सीट"),
    "baggage": ("Saamaan", "Baggage", "सामान"),
    "fare_paise": ("Kiraya", "Fare", "किराया"),
    "cancellation_note": ("Cancel note", "Cancellation note", "कैंसल नोट"),
    "train_no": ("Train number", "Train number", "ट्रेन नंबर"),
    "train_name": ("Train", "Train", "ट्रेन"),
    "from_station": ("Kahan se", "From", "कहाँ से"),
    "to_station": ("Kahan tak", "To", "कहाँ तक"),
    "boarding_station": ("Chadhne ka station", "Boarding station", "चढ़ने का स्टेशन"),
    "travel_class": ("Class", "Class", "क्लास"),
    "coach_berth": ("Coach/berth", "Coach/berth", "कोच/बर्थ"),
    "property_name": ("Hotel", "Hotel", "होटल"),
    "address": ("Pata", "Address", "पता"),
    "phone": ("Phone", "Phone", "फोन"),
    "check_in_date": ("Check-in", "Check-in", "चेक-इन"),
    "check_in_time": ("Check-in time", "Check-in time", "चेक-इन समय"),
    "check_out_date": ("Check-out", "Check-out", "चेक-आउट"),
    "check_out_time": ("Check-out time", "Check-out time", "चेक-आउट समय"),
    "guests": ("Mehmaan", "Guests", "मेहमान"),
    "room_type": ("Room", "Room", "कमरा"),
    "confirmation_no": ("Booking number", "Booking number", "बुकिंग नंबर"),
    "amount_paise": ("Amount", "Amount", "रकम"),
    "prepaid": ("Pehle se paid", "Prepaid", "पहले से पेड"),
    "cancellation_deadline": ("Free cancel tak", "Free cancellation until", "फ्री कैंसल तक"),
    "platform": ("Platform", "Platform", "प्लेटफ़ॉर्म"),
    "given_name": ("Naam", "Given name", "नाम"),
    "surname": ("Surname", "Surname", "सरनेम"),
    "nationality": ("Nagrikta", "Nationality", "नागरिकता"),
    "dob": ("Janam tareekh", "Date of birth", "जन्म तारीख़"),
    "number_masked": ("Passport number", "Passport number", "पासपोर्ट नंबर"),
    "issue_date": ("Issue date", "Issue date", "जारी तारीख़"),
    "expiry_date": ("Expiry date", "Expiry date", "एक्सपायरी तारीख़"),
    "place_of_issue": ("Kahan se bana", "Place of issue", "कहाँ से बना"),
    "biller": ("Biller", "Biller", "बिलर"),
    "kind": ("Kism", "Type", "किस्म"),
    "due_date": ("Due date", "Due date", "ड्यू डेट"),
    "min_due_paise": ("Minimum due", "Minimum due", "मिनिमम ड्यू"),
    "account_last4": ("Account (aakhri 4)", "Account (last 4)", "अकाउंट (आखिरी 4)"),
    "title": ("Kya hai", "What it is", "क्या है"),
    "summary": ("Sar", "Summary", "सार"),
}
_IDX = {"hinglish": 0, "en": 1, "hi": 2}


def lang_of(language: str | None) -> str:
    """Map a User.language value (en, hi, hinglish, ...) to one of the three copy languages."""
    v = (language or "").lower()
    return "en" if v == "en" else "hi" if v == "hi" else "hinglish"


def t(key: str, language: str = DEFAULT_LANGUAGE, **kw: str) -> str:
    table = TEXTS[key]
    text = table.get(lang_of(language)) or table[DEFAULT_LANGUAGE]
    return text.format(**kw) if kw else text


def label(field: str, language: str = DEFAULT_LANGUAGE) -> str:
    row = LABELS.get(field)
    return row[_IDX[lang_of(language)]] if row else field


def button_id(action: str, doc_id: str) -> str:
    return f"{BUTTON_PREFIX}{action}:{doc_id}"


def parse_button_id(button_id_: str) -> tuple[str, str] | None:
    parts = (button_id_ or "").split(":")
    if len(parts) == 3 and parts[0] + ":" == BUTTON_PREFIX and parts[1] in ("ok", "fix", "drop"):
        return parts[1], parts[2]
    return None
