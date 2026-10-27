# ruff: noqa: E501
"""ALL user-facing text of the WhatsApp chatbot pilot lives here (and only here).

PENDING_FOUNDER_APPROVAL: no line below has been approved. Under the hear-before-change rule
(CLAUDE.md rule 3) nothing here may be shown to a real person until the founder has read and
approved it. Tests check structure (length, one question, button titles, the assistant and
"never" statements, a why-clause on proactive text) and never the exact words, so the words can
change freely after review.

Rules the wording follows:
  * Roman Hinglish by default (``hinglish``), with a Hindi (``hi``, Devanagari) and an English
    (``en``) variant of every line; Friday is female ("karti hoon", "sakti hoon");
  * short: at most about 3 lines a message, one question at most (the intro is the one longer
    message: it must say who she is, what she does and what she never does);
  * no emojis;
  * the intro and every proactive text say plainly that Friday is an assistant and that she never
    asks for payments, OTP, PIN or card numbers, works only with the user's own data and lets the
    user delete it anytime;
  * placeholders are ``{name}`` style format fields.

Ids (used in docs/CHATBOT_PILOT.md for the approval list): ``chatbot.line.<key>``,
``chatbot.button.<key>`` and ``chatbot.row.<key>`` (see :func:`all_ids`).
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

# stored with every consent record (Consent.policy_version, max 20 chars). Bump it whenever the
# wording of ``intro``/``details`` changes after approval, so each consent is tied to the words
# the person actually saw.
WORDING_VERSION = "chatbot-pilot-v0"

DEFAULT_LANGUAGE = "hinglish"
LANGUAGES = ("hinglish", "hi", "en")
LANGUAGE_NAMES = {"hinglish": "Hinglish", "hi": "हिंदी", "en": "English"}

# message kinds for the composer (friday/chatbot/composer.py): which length cap and which
# mandatory statements apply. Anything not listed is "default".
KIND: dict[str, str] = {
    "intro": "intro",
    "details": "intro",
    "waitlist": "intro",
    "done": "disclosure",
    "support_forward": "internal",
}

LINES: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ first run: intro and consent
    "intro": {
        "hinglish": "Namaste! Main Friday hoon, ek AI assistant (insaan nahi).\nMain yeh kar sakti hoon:\n- aapke liye call karna\n- card se bachat batana\n- aapka din yaad rakhna\nMain kabhi payment, OTP, PIN ya card number nahi maangti. Sirf aapka apna data, jab chaho delete.\nAage badhein?",
        "hi": "नमस्ते! मैं Friday हूँ, एक AI असिस्टेंट (इंसान नहीं)।\nमैं यह कर सकती हूँ:\n- आपके लिए कॉल करना\n- कार्ड से बचत बताना\n- आपका दिन याद रखना\nमैं कभी पेमेंट, OTP, PIN या कार्ड नंबर नहीं माँगती। सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।\nआगे बढ़ें?",
        "en": "Hello! I'm Friday, an AI assistant (not a person).\nI can:\n- make calls for you\n- show card savings\n- remember your day\nI never ask for payments, OTP, PIN or card numbers. Only your own data, and you can delete it anytime.\nShall we go on?",
    },
    "details": {
        "hinglish": "Main Friday, ek AI assistant. Aapke messages sirf aapki madad ke liye padhti hoon. Sirf aapka apna data (naam, shehar, jo aap batao) yaad rakhti hoon, kisi ko bechti nahi.\nPayment, OTP, PIN, card number main kabhi nahi maangti. 'delete everything' likho toh sab mita dungi.\nTheek hai?",
        "hi": "मैं Friday, एक AI असिस्टेंट। आपके मैसेज सिर्फ़ आपकी मदद के लिए पढ़ती हूँ। सिर्फ़ आपका अपना डेटा (नाम, शहर, जो आप बताएँ) याद रखती हूँ, किसी को बेचती नहीं।\nपेमेंट, OTP, PIN, कार्ड नंबर मैं कभी नहीं माँगती। 'delete everything' लिखें तो सब मिटा दूँगी।\nठीक है?",
        "en": "I'm Friday, an AI assistant. I read your messages only to help you. I keep only your own data (name, city, what you tell me) and never sell it.\nI never ask for payments, OTP, PIN or card numbers. Write 'delete everything' and I erase it all.\nIs that okay?",
    },
    "consent_reprompt": {
        "hinglish": "Aage badhne se pehle mujhe aapki haan chahiye. Haan, theek hai ya Nahi?",
        "hi": "आगे बढ़ने से पहले मुझे आपकी हाँ चाहिए। हाँ, ठीक है या नहीं?",
        "en": "Before we go on I need your yes. Yes, okay, or No?",
    },
    "refused": {
        "hinglish": "Theek hai, koi baat nahi. Maine kuch save nahi kiya. Kabhi mann ho toh 'hi' bhej dena.",
        "hi": "ठीक है, कोई बात नहीं। मैंने कुछ सेव नहीं किया। कभी मन हो तो 'hi' भेज देना।",
        "en": "Okay, no problem. I saved nothing. Send 'hi' whenever you like.",
    },
    "waitlist": {
        "hinglish": "Namaste, main Friday, ek AI assistant. Abhi sirf kuch testers ke saath chal rahi hoon. Aapka number waitlist mein hai, jagah khulte hi bataungi.\nMain kabhi payment, OTP ya PIN nahi maangti; sirf aapka apna data, jab chaho delete.",
        "hi": "नमस्ते, मैं Friday, एक AI असिस्टेंट। अभी सिर्फ़ कुछ टेस्टर्स के साथ चल रही हूँ। आपका नंबर वेटलिस्ट में है, जगह खुलते ही बताऊँगी।\nमैं कभी पेमेंट, OTP या PIN नहीं माँगती; सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।",
        "en": "Hello, I'm Friday, an AI assistant. I'm only running with a few testers right now. Your number is on the waitlist and I'll tell you when a spot opens.\nI never ask for payments, OTP or PIN; only your own data, and you can delete it anytime.",
    },
    # ------------------------------------------------------------------ first run: the steps
    "ask_name": {
        "hinglish": "Shukriya! Aapko kya bulaun? Apna naam likhiye ya Skip dabaiye.",
        "hi": "शुक्रिया! आपको क्या बुलाऊँ? अपना नाम लिखें या Skip दबाएँ।",
        "en": "Thank you! What should I call you? Write your name or tap Skip.",
    },
    "reprompt_name": {
        "hinglish": "Naam samajh nahi aaya. Sirf naam likhiye, jaise 'Rahul', ya Skip dabaiye.",
        "hi": "नाम समझ नहीं आया। सिर्फ़ नाम लिखें, जैसे 'Rahul', या Skip दबाएँ।",
        "en": "I didn't catch the name. Just write it, like 'Rahul', or tap Skip.",
    },
    "ack_name": {
        "hinglish": "Namaste {name}!",
        "hi": "नमस्ते {name}!",
        "en": "Hello {name}!",
    },
    "ack_name_skip": {
        "hinglish": "Theek hai, bina naam ke.",
        "hi": "ठीक है, बिना नाम के।",
        "en": "Okay, no name for now.",
    },
    "ask_language": {
        "hinglish": "Aap kis bhasha mein baat karna chahenge? Abhi main {current} mein hoon.",
        "hi": "आप किस भाषा में बात करना चाहेंगे? अभी मैं {current} में हूँ।",
        "en": "Which language would you like? Right now I'm using {current}.",
    },
    "reprompt_language": {
        "hinglish": "Bas Hinglish, Hindi ya English chuniye, ya Skip dabaiye.",
        "hi": "बस Hinglish, हिंदी या English चुनें, या Skip दबाएँ।",
        "en": "Just pick Hinglish, Hindi or English, or tap Skip.",
    },
    "ack_language": {
        "hinglish": "Theek hai, ab main {language} mein baat karungi.",
        "hi": "ठीक है, अब मैं {language} में बात करूँगी।",
        "en": "Okay, I'll talk in {language} from now on.",
    },
    "ask_city": {
        "hinglish": "Aap kis shehar mein hain? Shehar ka naam likhiye ya location pin bhejiye.",
        "hi": "आप किस शहर में हैं? शहर का नाम लिखें या लोकेशन पिन भेजें।",
        "en": "Which city are you in? Write the city or send a location pin.",
    },
    "reprompt_city": {
        "hinglish": "Shehar ka naam likhiye (jaise Pune), ya location pin bhejiye, ya Skip dabaiye.",
        "hi": "शहर का नाम लिखें (जैसे पुणे), या लोकेशन पिन भेजें, या Skip दबाएँ।",
        "en": "Write the city (like Pune), send a location pin, or tap Skip.",
    },
    "ack_city": {
        "hinglish": "{city}, achha!",
        "hi": "{city}, अच्छा!",
        "en": "{city}, nice!",
    },
    "ack_city_pin": {
        "hinglish": "Location mil gayi.",
        "hi": "लोकेशन मिल गई।",
        "en": "Got your location.",
    },
    "ack_city_skip": {
        "hinglish": "Theek hai, baad mein bata dena.",
        "hi": "ठीक है, बाद में बता देना।",
        "en": "Okay, tell me later.",
    },
    "ask_win": {
        "hinglish": "Chaliye pehla kaam karte hain. Kya try karein?",
        "hi": "चलिए पहला काम करते हैं। क्या आज़माएँ?",
        "en": "Let's do a first thing together. What would you like to try?",
    },
    "reprompt_win": {
        "hinglish": "Upar se ek chuniye, ya 'menu' likhiye.",
        "hi": "ऊपर से एक चुनें, या 'menu' लिखें।",
        "en": "Pick one above, or write 'menu'.",
    },
    "win_card": {
        "hinglish": "Bas likhiye: 'mere paas HDFC Regalia card hai'. Sirf card ka naam, number kabhi nahi.",
        "hi": "बस लिखें: 'मेरे पास HDFC Regalia कार्ड है'। सिर्फ़ कार्ड का नाम, नंबर कभी नहीं।",
        "en": "Just write: 'I have an HDFC Regalia card'. Only the card name, never the number.",
    },
    "win_day": {
        "hinglish": "Bataiye aage kya hai, jaise 'kal 2 baje interview hai'. Main yaad rakhungi.",
        "hi": "बताइए आगे क्या है, जैसे 'कल 2 बजे इंटरव्यू है'। मैं याद रखूँगी।",
        "en": "Tell me what's coming up, like 'interview tomorrow at 2'. I'll remember it.",
    },
    "win_call": {
        "hinglish": "Likhiye 'mummy ko call karo ki main late hoon'. Call se pehle aapse OK lungi.",
        "hi": "लिखें 'मम्मी को कॉल करो कि मैं लेट हूँ'। कॉल से पहले आपसे OK लूँगी।",
        "en": "Write 'call mummy and say I'm late'. I'll get your OK before any call.",
    },
    "win_soon": {
        "hinglish": "Yeh abhi pilot mein chalu nahi hai, jaldi aayega. Tab tak 'menu' likhiye.",
        "hi": "यह अभी पायलट में चालू नहीं है, जल्दी आएगा। तब तक 'menu' लिखें।",
        "en": "This isn't switched on in the pilot yet, it's coming soon. Write 'menu' for now.",
    },
    "done": {
        "hinglish": "Bas, itna hi! Kabhi bhi 'menu' likhiye.\nMain AI assistant hoon: payment, OTP, PIN kabhi nahi maangti, sirf aapka apna data, jab chaho delete.",
        "hi": "बस, इतना ही! कभी भी 'menu' लिखें।\nमैं AI असिस्टेंट हूँ: पेमेंट, OTP, PIN कभी नहीं माँगती, सिर्फ़ आपका अपना डेटा, जब चाहें डिलीट।",
        "en": "That's it! Write 'menu' any time.\nI'm an AI assistant: I never ask for payment, OTP or PIN, only your own data, and you can delete it anytime.",
    },
    "resume_prefix": {
        "hinglish": "Wapas aaye, achha laga! Chaliye wahin se.",
        "hi": "वापस आए, अच्छा लगा! चलिए वहीं से।",
        "en": "Welcome back! Let's pick up where we stopped.",
    },
    "footer_short": {
        "hinglish": "Friday AI assistant hai; payment, OTP, PIN kabhi nahi maangti.",
        "hi": "Friday AI असिस्टेंट है; पेमेंट, OTP, PIN कभी नहीं माँगती।",
        "en": "Friday is an AI assistant; she never asks for payment, OTP or PIN.",
    },
    # ------------------------------------------------------------------ menu and help
    "menu_header": {
        "hinglish": "Main Friday, aapki AI assistant. Yeh sab kar sakti hoon, chuniye:",
        "hi": "मैं Friday, आपकी AI असिस्टेंट। यह सब कर सकती हूँ, चुनें:",
        "en": "I'm Friday, your AI assistant. Here is what I can do, pick one:",
    },
    "mark_pilot": {"hinglish": "(pilot)", "hi": "(पायलट)", "en": "(pilot)"},
    "mark_soon": {"hinglish": "(jaldi)", "hi": "(जल्दी)", "en": "(soon)"},
    "hint_contact": {
        "hinglish": "Kisi ka WhatsApp contact card bhejiye (attach, Contact). Main poochungi unhe kya bulaun: mummy, bhaiya...",
        "hi": "किसी का WhatsApp कॉन्टैक्ट कार्ड भेजें (attach, Contact)। मैं पूछूँगी उन्हें क्या बुलाऊँ: मम्मी, भैया...",
        "en": "Share someone's WhatsApp contact card (attach, Contact). I'll ask what to call them: mummy, bhaiya...",
    },
    "hint_place": {
        "hinglish": "Location pin bhejiye (attach, Location). Phir bataiye yeh ghar hai ya office.",
        "hi": "लोकेशन पिन भेजें (attach, Location)। फिर बताइए यह घर है या ऑफिस।",
        "en": "Send a location pin (attach, Location). Then tell me if it's home or office.",
    },
    "hint_stop": {
        "hinglish": "'stop' likhiye, main khud se bheje jaane wale messages band kar dungi.",
        "hi": "'stop' लिखें, मैं अपने-आप भेजे जाने वाले मैसेज बंद कर दूँगी।",
        "en": "Write 'stop' and I'll stop sending messages on my own.",
    },
    "hint_human": {
        "hinglish": "'human' likhiye, koi insaan aapko yahin reply karega.",
        "hi": "'human' लिखें, कोई इंसान आपको यहीं जवाब देगा।",
        "en": "Write 'human' and a person will reply to you here.",
    },
    "hint_delete": {
        "hinglish": "'delete everything' likhiye. Do step mein confirm hota hai, tab sab mita dungi.",
        "hi": "'delete everything' लिखें। दो स्टेप में कन्फ़र्म होता है, तब सब मिटा दूँगी।",
        "en": "Write 'delete everything'. You confirm in two steps, then I erase it all.",
    },
    # ------------------------------------------------------------------ stop / resume / human / delete
    "stop_done": {
        "hinglish": "Theek hai, ab main khud se message nahi bhejungi. Aap likhoge tabhi jawab dungi. Dobara chalu karne ke liye 'chalu karo' likhiye.",
        "hi": "ठीक है, अब मैं अपने-आप मैसेज नहीं भेजूँगी। आप लिखेंगे तभी जवाब दूँगी। दोबारा चालू करने के लिए 'chalu karo' लिखें।",
        "en": "Okay, I won't message you on my own any more. I'll only answer when you write. Write 'start' to turn it back on.",
    },
    "stop_already": {
        "hinglish": "Maine pehle se hi khud se messages band kar rakhe hain. 'chalu karo' likhiye toh dobara shuru karungi.",
        "hi": "मैंने पहले से ही अपने-आप भेजे जाने वाले मैसेज बंद कर रखे हैं। 'chalu karo' लिखें तो दोबारा शुरू करूँगी।",
        "en": "My own messages are already off. Write 'start' and I'll turn them back on.",
    },
    "resume_done": {
        "hinglish": "Theek hai, ab main zaroorat par aapko khud se message bhejungi. Kabhi bhi 'stop' likhkar band kar sakte ho.",
        "hi": "ठीक है, अब ज़रूरत पर मैं आपको अपने-आप मैसेज भेजूँगी। कभी भी 'stop' लिखकर बंद कर सकते हैं।",
        "en": "Okay, I'll message you on my own when it helps. You can write 'stop' any time to turn it off.",
    },
    "human_forwarded": {
        "hinglish": "Maine aapki baat team ko bhej di. Koi insaan aapko yahin reply karega.",
        "hi": "मैंने आपकी बात टीम को भेज दी। कोई इंसान आपको यहीं जवाब देगा।",
        "en": "I've passed your message to the team. A person will reply to you here.",
    },
    "human_noted": {
        "hinglish": "Maine note kar liya hai, par abhi support ka number set nahi hai. Jawab aane mein der ho sakti hai.",
        "hi": "मैंने नोट कर लिया है, पर अभी सपोर्ट का नंबर सेट नहीं है। जवाब आने में देर हो सकती है।",
        "en": "I've noted it, but no support number is set up yet. The reply may take a while.",
    },
    "support_forward": {
        "hinglish": "Friday support: {name} ({phone}) insaan se baat karna chahte hain. Unka message: {text}",
        "hi": "Friday सपोर्ट: {name} ({phone}) इंसान से बात करना चाहते हैं। उनका मैसेज: {text}",
        "en": "Friday support: {name} ({phone}) asked to talk to a person. Their message: {text}",
    },
    "delete_confirm": {
        "hinglish": "Yeh aapka sab data hamesha ke liye mita dega: profile, contacts, yaadein. Pakka? Confirm karne ke liye DELETE likhiye.",
        "hi": "यह आपका सारा डेटा हमेशा के लिए मिटा देगा: प्रोफ़ाइल, कॉन्टैक्ट्स, यादें। पक्का? कन्फ़र्म करने के लिए DELETE लिखें।",
        "en": "This erases all your data for good: profile, contacts, memories. Sure? Write DELETE to confirm.",
    },
    "consent_renewed": {
        "hinglish": "Shukriya, aapki haan note kar li. Kabhi bhi 'stop' ya 'delete everything' likh sakte ho.",
        "hi": "शुक्रिया, आपकी हाँ नोट कर ली। कभी भी 'stop' या 'delete everything' लिख सकते हैं।",
        "en": "Thank you, I've noted your yes. You can write 'stop' or 'delete everything' any time.",
    },
    "consent_withdrawn": {
        "hinglish": "Theek hai, ab main khud se message nahi bhejungi. Sab mitana ho toh 'delete everything' likhiye.",
        "hi": "ठीक है, अब मैं अपने-आप मैसेज नहीं भेजूँगी। सब मिटाना हो तो 'delete everything' लिखें।",
        "en": "Okay, I won't message you on my own any more. Write 'delete everything' if you want it all erased.",
    },
    # ------------------------------------------------------------------ contact capture
    "contact_ask_nick": {
        "hinglish": "{name} ko kya bulaun? mummy, bhaiya... ya Skip.",
        "hi": "{name} को क्या बुलाऊँ? मम्मी, भैया... या Skip।",
        "en": "What should I call {name}? mummy, bhaiya... or Skip.",
    },
    "contact_ask_nick_number": {
        "hinglish": "Yeh number kiska hai? mummy, bhaiya ya naam likhiye, ya Skip.",
        "hi": "यह नंबर किसका है? मम्मी, भैया या नाम लिखें, या Skip।",
        "en": "Whose number is this? Write mummy, bhaiya or a name, or Skip.",
    },
    "contact_saved": {
        "hinglish": "{who} save ho gaye: {masked}. Galat lage toh batayiye.",
        "hi": "{who} सेव हो गए: {masked}। गलत लगे तो बताइए।",
        "en": "Saved {who}: {masked}. Tell me if it looks wrong.",
    },
    "contact_invalid": {
        "hinglish": "Yeh number sahi nahi lag raha. Poora 10 digit ka number dobara bhejiye.",
        "hi": "यह नंबर सही नहीं लग रहा। पूरा 10 अंकों का नंबर दोबारा भेजें।",
        "en": "That number doesn't look right. Please send the full 10-digit number again.",
    },
    "contact_emergency": {
        "hinglish": "Emergency number main save ya dial nahi karti. Zaroorat ho toh aap khud 112 par call karein.",
        "hi": "इमरजेंसी नंबर मैं सेव या डायल नहीं करती। ज़रूरत हो तो आप खुद 112 पर कॉल करें।",
        "en": "I don't save or dial emergency numbers. If it's urgent, please call 112 yourself.",
    },
    "contact_dropped": {
        "hinglish": "Theek hai, contact save nahi kiya.",
        "hi": "ठीक है, कॉन्टैक्ट सेव नहीं किया।",
        "en": "Okay, I didn't save the contact.",
    },
    # ------------------------------------------------------------------ place capture
    "place_ask": {
        "hinglish": "Yeh jagah kaunsi hai: ghar, office ya kuch aur?",
        "hi": "यह जगह कौन सी है: घर, ऑफिस या कुछ और?",
        "en": "Which place is this: home, office or something else?",
    },
    "place_reprompt": {
        "hinglish": "Bas ek naam likhiye, jaise ghar ya office, ya Skip dabaiye.",
        "hi": "बस एक नाम लिखें, जैसे घर या ऑफिस, या Skip दबाएँ।",
        "en": "Just write a name, like home or office, or tap Skip.",
    },
    "place_saved": {
        "hinglish": "{label} save ho gaya. Yeh sirf aapke vendor search mein kaam aayega, kisi ko share nahi hoga.",
        "hi": "{label} सेव हो गया। यह सिर्फ़ आपके वेंडर सर्च में काम आएगा, किसी को शेयर नहीं होगा।",
        "en": "Saved {label}. It's only used for your vendor searches and is never shared.",
    },
    "place_skipped": {
        "hinglish": "Theek hai, jagah save nahi ki.",
        "hi": "ठीक है, जगह सेव नहीं की।",
        "en": "Okay, I didn't save the place.",
    },
    # ------------------------------------------------------------------ out of scope
    "offtopic": {
        "hinglish": "Main aapke kaam ke liye hoon: calls, bachat aur aapka din. Yeh sawaal alag hai, par maine note kar liya hai. 'menu' likhiye.",
        "hi": "मैं आपके काम के लिए हूँ: कॉल, बचत और आपका दिन। यह सवाल अलग है, पर मैंने नोट कर लिया है। 'menu' लिखें।",
        "en": "I'm here for your tasks: calls, savings and your day. This one is outside that, but I've noted it. Write 'menu'.",
    },
    # ------------------------------------------------------------------ Instinct review (appendix C): safety, language, quick answers
    "safety_emergency": {
        "hinglish": "Yeh serious ho sakta hai. Abhi 112 par call kijiye ya paas ke hospital jaiye, intezaar mat kijiye. Main doctor nahi hoon, par aapke saath hoon.",
        "hi": "यह गंभीर हो सकता है। अभी 112 पर कॉल कीजिए या पास के अस्पताल जाइए, इंतज़ार मत कीजिए। मैं डॉक्टर नहीं हूँ, पर आपके साथ हूँ।",
        "en": "This could be serious. Please call 112 or go to the nearest hospital now, do not wait. I'm not a doctor, but I'm with you.",
    },
    "safety_medicine": {
        "hinglish": "Main dawai ya dose nahi bata sakti, yeh doctor ya pharmacist hi sahi bata sakte hain. Chahein toh main clinic ka pata karke appointment ke liye call kar sakti hoon.",
        "hi": "मैं दवाई या डोज़ नहीं बता सकती, यह डॉक्टर या फ़ार्मासिस्ट ही सही बता सकते हैं। चाहें तो मैं क्लिनिक का पता करके अपॉइंटमेंट के लिए कॉल कर सकती हूँ।",
        "en": "I can't advise on medicines or doses, a doctor or pharmacist should. If you like, I can find a clinic and call for an appointment.",
    },
    "refuse_forgery": {
        "hinglish": "Nakli bill ya receipt main nahi bana sakti, yeh dhokha hota hai aur aap par bhaari pad sakta hai. Asli kharcha hua ho toh duplicate bill maangiye, uski photo bhejiye, main saaf PDF bana dungi.",
        "hi": "नकली बिल या रसीद मैं नहीं बना सकती, यह धोखा होता है और आप पर भारी पड़ सकता है। असली खर्चा हुआ हो तो डुप्लिकेट बिल माँगिए, उसकी फ़ोटो भेजिए, मैं साफ़ PDF बना दूँगी।",
        "en": "I can't make a fake bill or receipt, it is fraud and could cost you. If the expense was real, ask for a duplicate bill, send me its photo and I'll make a clean PDF.",
    },
    "lang_set": {
        "hinglish": "Theek hai, ab se {language} mein jawab dungi.",
        "hi": "ठीक है, अब से {language} में जवाब दूँगी।",
        "en": "Okay, I'll reply in {language} from now on.",
    },
    "quick_calc": {
        "hinglish": "Jawab: {expr} = {result}",
        "hi": "जवाब: {expr} = {result}",
        "en": "Answer: {expr} = {result}",
    },
    "quick_time": {
        "hinglish": "Abhi India mein {time} (IST) hue hain.",
        "hi": "अभी भारत में {time} (IST) हुए हैं।",
        "en": "It is {time} IST in India right now.",
    },
    "quick_date": {
        "hinglish": "Aaj {date} hai.",
        "hi": "आज {date} है।",
        "en": "Today is {date}.",
    },
    # ------------------------------------------------------------------ proactive: the why-clause
    "why_generic": {
        "hinglish": "Yeh isliye aaya ki aapne Friday se yeh madad maangi thi. Band karne ke liye 'stop' likhiye.",
        "hi": "यह इसलिए आया कि आपने Friday से यह मदद माँगी थी। बंद करने के लिए 'stop' लिखें।",
        "en": "You're getting this because you asked Friday for this help. Write 'stop' to turn it off.",
    },
}

BUTTONS: dict[str, dict[str, str]] = {
    "consent_yes": {"hinglish": "Haan, theek hai", "hi": "हाँ, ठीक है", "en": "Yes, okay"},
    "consent_details": {"hinglish": "Details", "hi": "विवरण", "en": "Details"},
    "consent_no": {"hinglish": "Nahi", "hi": "नहीं", "en": "No"},
    "skip": {"hinglish": "Skip", "hi": "छोड़ें", "en": "Skip"},
    "lang_hinglish": {"hinglish": "Hinglish", "hi": "Hinglish", "en": "Hinglish"},
    "lang_hi": {"hinglish": "हिंदी", "hi": "हिंदी", "en": "हिंदी"},
    "lang_en": {"hinglish": "English", "hi": "English", "en": "English"},
    "win_card": {"hinglish": "Card jodo", "hi": "कार्ड जोड़ें", "en": "Add a card"},
    "win_day": {"hinglish": "Mera din", "hi": "मेरा दिन", "en": "My day"},
    "win_call": {"hinglish": "Kisi ko call", "hi": "किसी को कॉल", "en": "Call someone"},
    "nick_mummy": {"hinglish": "Mummy", "hi": "मम्मी", "en": "Mummy"},
    "nick_papa": {"hinglish": "Papa", "hi": "पापा", "en": "Papa"},
    "place_home": {"hinglish": "Ghar", "hi": "घर", "en": "Home"},
    "place_office": {"hinglish": "Office", "hi": "ऑफिस", "en": "Office"},
    "menu_open": {"hinglish": "Menu dekhein", "hi": "मेनू देखें", "en": "See menu"},
}

# list rows of the menu: key -> language -> (title <= 24 chars, short description)
ROWS: dict[str, dict[str, tuple[str, str]]] = {
    "call": {
        "hinglish": ("Kisi ko call karwao", "Aapke liye call, aapke OK ke baad"),
        "hi": ("किसी को कॉल करवाओ", "आपके लिए कॉल, आपके OK के बाद"),
        "en": ("Call someone", "A call for you, after your OK"),
    },
    "card": {
        "hinglish": ("Card se bachat", "Kaun sa card, bills ke reminders"),
        "hi": ("कार्ड से बचत", "कौन सा कार्ड, बिल के रिमाइंडर"),
        "en": ("Card savings", "Which card, bill reminders"),
    },
    "day": {
        "hinglish": ("Mera din", "Aaj kya hai, yaad rakhna"),
        "hi": ("मेरा दिन", "आज क्या है, याद रखना"),
        "en": ("My day", "What's on today, remembering"),
    },
    "contact": {
        "hinglish": ("Contact jodo", "Contact card bhejo, nickname do"),
        "hi": ("कॉन्टैक्ट जोड़ें", "कॉन्टैक्ट कार्ड भेजें, निकनेम दें"),
        "en": ("Add a contact", "Share a card, give a nickname"),
    },
    "place": {
        "hinglish": ("Jagah save karo", "Ghar ya office ka location pin"),
        "hi": ("जगह सेव करें", "घर या ऑफिस का लोकेशन पिन"),
        "en": ("Save a place", "Location pin for home or office"),
    },
    "stop": {
        "hinglish": ("Messages band karo", "Khud se bheje messages band"),
        "hi": ("मैसेज बंद करें", "अपने-आप भेजे मैसेज बंद"),
        "en": ("Stop my messages", "Turn off messages I send first"),
    },
    "human": {
        "hinglish": ("Insaan se baat", "Team ka koi insaan reply karega"),
        "hi": ("इंसान से बात", "टीम का कोई इंसान जवाब देगा"),
        "en": ("Talk to a person", "Someone from the team replies"),
    },
    "delete": {
        "hinglish": ("Sab delete karo", "Aapka sara data mita dungi"),
        "hi": ("सब डिलीट करें", "आपका सारा डेटा मिटा दूँगी"),
        "en": ("Delete everything", "I erase all your data"),
    },
}

# which menu row is a pilot feature (marked "pilot" when its switch is on, "soon" when off)
PILOT_ROWS = {
    "call": "consumer_calls_enabled",
    "card": "savings_enabled",
    "day": "lifestate_enabled",
}


def _pick(variants: dict[str, str], lang: str) -> str:
    return variants.get(lang) or variants[DEFAULT_LANGUAGE]


def line(key: str, lang: str = DEFAULT_LANGUAGE, **fmt: object) -> str:
    text = _pick(LINES[key], lang)
    return text.format(**fmt) if fmt else text


def button(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    return _pick(BUTTONS[key], lang)


def row(key: str, lang: str = DEFAULT_LANGUAGE) -> tuple[str, str]:
    variants = ROWS[key]
    return variants.get(lang) or variants[DEFAULT_LANGUAGE]


def kind_of(key: str) -> str:
    return KIND.get(key, "default")


def all_ids() -> list[str]:
    """Every copy id the founder must approve, in file order."""
    return (
        [f"chatbot.line.{k}" for k in LINES]
        + [f"chatbot.button.{k}" for k in BUTTONS]
        + [f"chatbot.row.{k}" for k in ROWS]
    )
