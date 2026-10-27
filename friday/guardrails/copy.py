# ruff: noqa: E501
"""Wording for the NEW guardrail categories. PENDING_FOUNDER_APPROVAL: nothing here may be shown to
a real person before the founder has read and approved it (CLAUDE.md rule 3), which is also why the
new categories are OFF by default. Tests check structure (three languages, variants, length, no
emoji, one question at most) and never the exact words.

The lines for the categories that already existed (emergency, medicine, fake bill, off-topic, quick
facts) stay in ``friday/chatbot/copy.py`` and are looked up from there (:func:`line`), so nothing is
duplicated and no approved wording changes.

Each refusal has two variants per language (the same wording is never sent twice in a row to the
same person) and always names what Friday CAN do instead. Ids for the approval list:
``guardrails.line.<key>`` (see :func:`all_ids`). Helpline numbers (112, Tele-MANAS 14416) MUST be
verified by the founder before launch.
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True
DEFAULT_LANGUAGE = "hinglish"
LANGUAGES = ("hinglish", "hi", "en")

# key -> language -> variants (1 or 2)
LINES: dict[str, dict[str, tuple[str, ...]]] = {
    "self_harm": {
        "hinglish": ("Aap jo mehsoos kar rahe hain woh bahut bhaari hai, aur aap akele nahi hain. Abhi kisi apne se baat kijiye, ya Tele-MANAS 14416 par call kijiye (free, 24 ghante). Khatre mein ho toh 112. Main yahin hoon.",),
        "hi": ("आप जो महसूस कर रहे हैं वह बहुत भारी है, और आप अकेले नहीं हैं। अभी किसी अपने से बात कीजिए, या Tele-MANAS 14416 पर कॉल कीजिए (मुफ़्त, 24 घंटे)। खतरे में हों तो 112। मैं यहीं हूँ।",),
        "en": ("What you are feeling sounds very heavy, and you are not alone. Please talk to someone close to you right now, or call Tele-MANAS on 14416 (free, 24 hours). If you are in danger, call 112. I'm here.",),
    },
    "minors": {
        "hinglish": ("Aap 18 se kam ke hain toh main calls, payment ya booking jaise kaam nahi kar sakti. Parents ya bade ki madad se hi yeh ho paayega. Baaki baat-cheet mein main yahin hoon.",),
        "hi": ("आप 18 से कम के हैं तो मैं कॉल, पेमेंट या बुकिंग जैसे काम नहीं कर सकती। माता-पिता या किसी बड़े की मदद से ही यह हो पाएगा। बाकी बातचीत में मैं यहीं हूँ।",),
        "en": ("Since you are under 18, I can't make calls, payments or bookings for you. A parent or another adult needs to do those with you. I'm still here to chat.",),
    },
    "legal_advice": {
        "hinglish": ("Kanooni salah main nahi de sakti, kyunki galat salah aapko nuksan karwa sakti hai. Kisi vakil se baat karna sahi rahega; chahein toh main vakil ka number dhoondhkar appointment ke liye call kar sakti hoon.",
                     "Case ya kanoon ke sawaal par main raay nahi de sakti. Vakil hi sahi bata sakte hain. Aap kahein toh main kisi vakil se appointment ke liye call kar dun."),
        "hi": ("कानूनी सलाह मैं नहीं दे सकती, क्योंकि गलत सलाह आपको नुकसान करा सकती है। किसी वकील से बात करना सही रहेगा; चाहें तो मैं वकील का नंबर ढूँढकर अपॉइंटमेंट के लिए कॉल कर सकती हूँ।",
               "केस या कानून के सवाल पर मैं राय नहीं दे सकती। वकील ही सही बता सकते हैं। आप कहें तो मैं किसी वकील से अपॉइंटमेंट के लिए कॉल कर दूँ।"),
        "en": ("I can't give legal advice, and a wrong answer could cost you. A lawyer is the right person; if you like, I can find one and call to book an appointment.",
               "I can't give an opinion on a case or the law, a lawyer can. Shall I call a lawyer's office to set up an appointment?"),
    },
    "financial_advice": {
        "hinglish": ("Kahan invest karein, kaun sa loan ya tax ka tareeka, yeh main nahi bata sakti; mere paas iska licence nahi hai. SEBI-registered advisor se baat kijiye. Aapke apne cards ke offers aur bills ke reminders mein main madad kar sakti hoon.",
                     "Paise lagane ya loan ki salah dena mere dayre mein nahi hai. Kisi registered advisor se poochhiye. Aapke bills, due dates aur card offers mein main madad kar deti hoon."),
        "hi": ("कहाँ निवेश करें, कौन सा लोन या टैक्स का तरीका, यह मैं नहीं बता सकती; मेरे पास इसका लाइसेंस नहीं है। SEBI-रजिस्टर्ड सलाहकार से बात कीजिए। आपके अपने कार्ड के ऑफ़र और बिल के रिमाइंडर में मैं मदद कर सकती हूँ।",
               "पैसे लगाने या लोन की सलाह देना मेरे दायरे में नहीं है। किसी रजिस्टर्ड सलाहकार से पूछिए। आपके बिल, ड्यू डेट और कार्ड ऑफ़र में मैं मदद कर देती हूँ।"),
        "en": ("I can't say where to invest or which loan or tax route to pick, I'm not licensed for that. Please ask a SEBI-registered advisor. I can help with your own bills, due dates and card offers.",
               "Advice on investing or loans is outside what I do. A registered advisor can help. I can still help with your bills, due dates and card offers."),
    },
    "fake_documents": {
        "hinglish": ("Nakli ya badla hua document main nahi bana sakti, yeh dhokha hota hai aur aap par bhaari pad sakta hai. Asli document chahiye toh issuer se duplicate maangiye, main uski photo se saaf PDF bana dungi.",
                     "Jaali kaagaz ya scam mein main madad nahi karti. Asli kharcha ya asli document ho toh duplicate maangne mein main help kar sakti hoon."),
        "hi": ("नकली या बदला हुआ दस्तावेज़ मैं नहीं बना सकती, यह धोखा होता है और आप पर भारी पड़ सकता है। असली चाहिए तो जारी करने वाले से डुप्लिकेट माँगिए, मैं उसकी फ़ोटो से साफ़ PDF बना दूँगी।",
               "जाली कागज़ या स्कैम में मैं मदद नहीं करती। असली खर्चा या असली दस्तावेज़ हो तो डुप्लिकेट माँगने में मैं मदद कर सकती हूँ।"),
        "en": ("I can't make or alter a document, that is fraud and could cost you. If you need the real one, ask the issuer for a duplicate and I'll turn its photo into a clean PDF.",
               "I don't help with forged papers or scams. If the document or expense is real, I can help you request a duplicate."),
    },
    "harassment_abuse": {
        "hinglish": ("Kisi ko darane, dhamkane ya pareshan karne wale call ya message main nahi karti. Agar koi aapko pareshan kar raha hai, toh main aapke liye uska number block karne ya complaint ka tareeka dhoondhne mein madad kar sakti hoon.",
                     "Yeh main nahi karungi. Aap kuch pareshani mein hain toh bataiye, main sahi raasta dhoondhne mein madad karungi."),
        "hi": ("किसी को डराने-धमकाने या परेशान करने वाले कॉल या मैसेज मैं नहीं करती। अगर कोई आपको परेशान कर रहा है, तो मैं उसका नंबर ब्लॉक करने या शिकायत का तरीका ढूँढने में मदद कर सकती हूँ।",
               "यह मैं नहीं करूँगी। आप किसी परेशानी में हैं तो बताइए, मैं सही रास्ता ढूँढने में मदद करूँगी।"),
        "en": ("I don't make calls or messages meant to scare or harass anyone. If someone is bothering you, I can help you block their number or find how to complain.",
               "I won't do that. If something is troubling you, tell me and I'll help find the right way."),
    },
    "adult": {
        "hinglish": ("Is tarah ki baat main nahi karti. Aapke din, calls, bills aur cards mein main madad kar sakti hoon.",
                     "Yeh mere kaam ka hissa nahi hai. 'menu' likhiye, main jo kar sakti hoon woh dikha dungi."),
        "hi": ("इस तरह की बात मैं नहीं करती। आपके दिन, कॉल, बिल और कार्ड में मैं मदद कर सकती हूँ।",
               "यह मेरे काम का हिस्सा नहीं है। 'menu' लिखिए, मैं जो कर सकती हूँ वह दिखा दूँगी।"),
        "en": ("I don't do that kind of conversation. I can help with your day, calls, bills and cards.",
               "That isn't something I do. Write 'menu' and I'll show you what I can help with."),
    },
    "illegal": {
        "hinglish": ("Yeh gair-kanooni hai, ismein main madad nahi kar sakti. Kisi jaayaz kaam mein, jaise call, booking ya reminder, toh bataiye.",
                     "Is cheez mein main saath nahi de sakti kyunki yeh kanoon ke khilaaf hai. Koi aur kaam ho toh zaroor bataiye."),
        "hi": ("यह गैरकानूनी है, इसमें मैं मदद नहीं कर सकती। किसी जायज़ काम में, जैसे कॉल, बुकिंग या रिमाइंडर, तो बताइए।",
               "इस चीज़ में मैं साथ नहीं दे सकती क्योंकि यह कानून के खिलाफ़ है। कोई और काम हो तो ज़रूर बताइए।"),
        "en": ("That is against the law, so I can't help with it. If there is something legitimate, like a call, a booking or a reminder, tell me.",
               "I can't take part in that because it is illegal. Tell me if there is something else I can do."),
    },
    "privacy_others": {
        "hinglish": ("Main sirf aapke apne data ke saath kaam karti hoon, kisi aur ki location, chat ya details nahi bata sakti. Aap unhe khud call ya message karna chahein toh main call laga sakti hoon.",
                     "Kisi doosre ki jaankari main nahi deti, yeh unki privacy ka sawaal hai. Aapke apne contacts aur calls mein main madad karungi."),
        "hi": ("मैं सिर्फ़ आपके अपने डेटा के साथ काम करती हूँ, किसी और की लोकेशन, चैट या जानकारी नहीं बता सकती। आप उन्हें खुद कॉल या मैसेज करना चाहें तो मैं कॉल लगा सकती हूँ।",
               "किसी दूसरे की जानकारी मैं नहीं देती, यह उनकी प्राइवेसी का सवाल है। आपके अपने कॉन्टैक्ट और कॉल में मैं मदद करूँगी।"),
        "en": ("I only work with your own data, so I can't share anyone else's location, chats or details. If you want to reach them, I can place a call for you.",
               "I don't share other people's information, that is their privacy. I'm happy to help with your own contacts and calls."),
    },
    "prompt_injection": {
        "hinglish": ("Main apne niyam ya settings nahi badal sakti aur na dikha sakti hoon. Aapka asli kaam bataiye, main usi mein lagi hoon.",
                     "Is tarah ke nirdesh main nahi maanti. Aap kya karwana chahte hain, woh bataiye."),
        "hi": ("मैं अपने नियम या सेटिंग्स न बदल सकती हूँ, न दिखा सकती हूँ। आपका असली काम बताइए, मैं उसी में लगी हूँ।",
               "इस तरह के निर्देश मैं नहीं मानती। आप क्या करवाना चाहते हैं, वह बताइए।"),
        "en": ("I can't change or show my rules and settings. Tell me what you actually need and I'll get on with it.",
               "I don't follow instructions like that. Tell me what you want done."),
    },
    "prohibited_action": {
        "hinglish": ("Main khud kabhi payment nahi karti aur OTP, PIN ya card number nahi sambhalti. Bill ke liye main payment link ya QR bhej dungi, aap apne UPI app se pay kar dijiye.",
                     "Paisa bhejna ya card use karna mere haath mein nahi hai. Main bill dhoondhkar QR ya link bhej sakti hoon, pay aap apne app se karenge."),
        "hi": ("मैं खुद कभी पेमेंट नहीं करती और OTP, PIN या कार्ड नंबर नहीं संभालती। बिल के लिए मैं पेमेंट लिंक या QR भेज दूँगी, आप अपने UPI ऐप से पे कर दीजिए।",
               "पैसे भेजना या कार्ड इस्तेमाल करना मेरे हाथ में नहीं है। मैं बिल ढूँढकर QR या लिंक भेज सकती हूँ, पे आप अपने ऐप से करेंगे।"),
        "en": ("I never make payments myself and I never handle OTPs, PINs or card numbers. For a bill I can send a payment link or QR, and you pay from your own UPI app.",
               "Sending money or using a card isn't something I do. I can find the bill and send a QR or link; you pay in your own app."),
    },
    "sensitive_payment": {
        "hinglish": ("Bank, UPI, card ya Aadhaar ka code, PIN, CVV ya card number yahan mat bhejiye, main inhe kabhi nahi leti. Payment aap apne bank ya UPI app mein hi kijiye; mere paas aaya message hum mita denge.",
                     "Yeh code ya number chat mein bhejna surakshit nahi hai, isliye main ise nahi leti. Apne bank ya UPI app mein hi use kijiye. Koi aur aapse yeh maange toh mat dijiye."),
        "hi": ("बैंक, UPI, कार्ड या आधार का कोड, PIN, CVV या कार्ड नंबर यहाँ मत भेजिए, मैं इन्हें कभी नहीं लेती। पेमेंट आप अपने बैंक या UPI ऐप में ही कीजिए; मेरे पास आया संदेश हम मिटा देंगे।",
               "यह कोड या नंबर चैट में भेजना सुरक्षित नहीं है, इसलिए मैं इसे नहीं लेती। अपने बैंक या UPI ऐप में ही इस्तेमाल कीजिए। कोई और आपसे यह माँगे तो मत दीजिए।"),
        "en": ("Please don't send a bank, UPI, card or Aadhaar code, a PIN, CVV or card number here, I never take them. Do payments in your own bank or UPI app; we will erase the message you just sent.",
               "Sending that code or number in chat isn't safe, so I don't accept it. Use it only in your own bank or UPI app, and never give it to anyone who asks."),
    },
    "sensitive_password": {
        "hinglish": ("Password chat mein mat bhejiye. Main use kabhi nahi leti; surakshit link par hi daalna hota hai. Kahein toh main abhi ek secure link bhej deti hoon.",
                     "Password yahan type karna theek nahi hai. Secure link use kijiye, main bhej sakti hoon."),
        "hi": ("पासवर्ड चैट में मत भेजिए। मैं उसे कभी नहीं लेती; सुरक्षित लिंक पर ही डालना होता है। कहें तो मैं अभी एक सिक्योर लिंक भेज देती हूँ।",
               "पासवर्ड यहाँ टाइप करना ठीक नहीं है। सिक्योर लिंक इस्तेमाल कीजिए, मैं भेज सकती हूँ।"),
        "en": ("Please don't send passwords in chat, I never take them; they go only on a secure link. I can send you a secure link now if you like.",
               "Typing a password here isn't safe. Use the secure link instead, I can send one."),
    },
    "sensitive_unsolicited": {
        "hinglish": ("Abhi main kisi login par code nahi maang rahi, isliye yeh code mere kisi kaam ka nahi. Ise kisi ko bhi mat dijiye. Main kuch login karwana ho toh pehle khud batati hoon.",),
        "hi": ("अभी मैं किसी लॉगिन पर कोड नहीं माँग रही, इसलिए यह कोड मेरे किसी काम का नहीं। इसे किसी को भी मत दीजिए। कुछ लॉगिन करवाना हो तो मैं पहले खुद बताती हूँ।",),
        "en": ("I'm not waiting for a login code right now, so this is of no use to me. Please don't share it with anyone. If I need a code for a login I'll tell you first.",),
    },
    "otp_ack": {
        "hinglish": ("Code mil gaya, login kar rahi hoon. Yeh message hum apne record se hata dete hain.",),
        "hi": ("कोड मिल गया, लॉगिन कर रही हूँ। यह संदेश हम अपने रिकॉर्ड से हटा देते हैं।",),
        "en": ("Got the code, logging in now. We remove this message from our records.",),
    },
    "otp_failed": {
        "hinglish": ("Code aage nahi pahunch paaya. Kripya thodi der mein dobara try kijiye.",),
        "hi": ("कोड आगे नहीं पहुँच पाया। कृपया थोड़ी देर में दोबारा कोशिश कीजिए।",),
        "en": ("The code didn't go through. Please try again in a moment.",),
    },
    "politics": {
        "hinglish": ("Raajneeti ya dharm par main apni raay nahi deti. Aapke kaam, calls aur bills mein madad kar sakti hoon.",),
        "hi": ("राजनीति या धर्म पर मैं अपनी राय नहीं देती। आपके काम, कॉल और बिल में मदद कर सकती हूँ।",),
        "en": ("I don't give opinions on politics or religion. I can help with your tasks, calls and bills.",),
    },
    "identity": {
        "hinglish": ("Main ek AI assistant hoon, insaan nahi. Aapke liye calls, bills aur reminders mein madad karti hoon.",),
        "hi": ("मैं एक AI असिस्टेंट हूँ, इंसान नहीं। आपके लिए कॉल, बिल और रिमाइंडर में मदद करती हूँ।",),
        "en": ("I'm an AI assistant, not a person. I help with calls, bills and reminders.",),
    },
    "rate_limited": {
        "hinglish": ("Aap bahut tezi se messages bhej rahe hain, main thodi der ruk rahi hoon. Kuch der baad dobara likhiye.",),
        "hi": ("आप बहुत तेज़ी से मैसेज भेज रहे हैं, मैं थोड़ी देर रुक रही हूँ। कुछ देर बाद दोबारा लिखिए।",),
        "en": ("You are sending messages very fast, so I'm pausing for a little while. Please write again in a bit.",),
    },
    # output filter (check_reply)
    "reply_fallback": {
        "hinglish": ("Yeh jawab main bhej nahi sakti. Aap kya karwana chahte hain, dobara bataiye.",),
        "hi": ("यह जवाब मैं भेज नहीं सकती। आप क्या करवाना चाहते हैं, दोबारा बताइए।",),
        "en": ("I can't send that answer. Please tell me again what you'd like done.",),
    },
    "unverified_number": {
        "hinglish": ("Mujhe iska pakka number nahi pata. Chahein toh main pata karke batati hoon.",),
        "hi": ("मुझे इसका पक्का नंबर नहीं पता। चाहें तो मैं पता करके बताती हूँ।",),
        "en": ("I don't know the exact figure. I can find out and tell you if you like.",),
    },
    "disclaimer_medical": {
        "hinglish": ("Yeh sirf jaankari hai, doctor ki salah nahi.",),
        "hi": ("यह सिर्फ़ जानकारी है, डॉक्टर की सलाह नहीं।",),
        "en": ("This is information only, not medical advice.",),
    },
    "disclaimer_legal": {
        "hinglish": ("Yeh sirf jaankari hai, kanooni salah nahi.",),
        "hi": ("यह सिर्फ़ जानकारी है, कानूनी सलाह नहीं।",),
        "en": ("This is information only, not legal advice.",),
    },
    "disclaimer_financial": {
        "hinglish": ("Yeh sirf jaankari hai, nivesh ki salah nahi.",),
        "hi": ("यह सिर्फ़ जानकारी है, निवेश की सलाह नहीं।",),
        "en": ("This is information only, not investment advice.",),
    },
}


def _lang(lang: str) -> str:
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def variants(key: str, lang: str) -> tuple[str, ...]:
    if key in LINES:
        v = LINES[key]
        return v.get(_lang(lang)) or v[DEFAULT_LANGUAGE]
    from friday.chatbot import copy as chat_copy  # lazy: chatbot.copy never imports guardrails

    return (chat_copy.line(key, _lang(lang)),)


def line(key: str, lang: str = DEFAULT_LANGUAGE, variant: int = 0) -> str:
    """The wording for ``key``: this module first, then the chatbot's existing approved-pending
    lines (``safety_emergency``, ``safety_medicine``, ``refuse_forgery``, ``offtopic``...)."""
    v = variants(key, lang)
    return v[variant % len(v)]


def n_variants(key: str) -> int:
    return len(LINES[key][DEFAULT_LANGUAGE]) if key in LINES else 1


def all_ids() -> list[str]:
    """Every id the founder must approve, in file order."""
    return [f"guardrails.line.{k}" for k in LINES]
