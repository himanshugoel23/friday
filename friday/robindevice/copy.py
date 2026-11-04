"""Every parent-facing line of the device side, in English, Roman Hinglish and Devanagari.

ALL LINES ARE PENDING FOUNDER APPROVAL (hear-before-change). Rules the wording follows:
plain and calm; never "this is a scam" as a certainty (say "looks risky"); never "safe" for anything
involving money; the best positive is "no warning signs found" plus "still never share an OTP or PIN".
Placeholders: {brand} (product name), {child} (who to call), {amount}.
"""

from __future__ import annotations

from typing import Final

LANGS: Final = ("en", "hinglish", "hi")
STATUS: Final = "PENDING founder approval"

CHILD: Final[dict[str, str]] = {
    "en": "your son or daughter",
    "hinglish": "apne bete ya beti",
    "hi": "अपने बेटे या बेटी",
}

# ----------------------------------------------------------------------------- parent prompts
PROMPTS: Final[dict[str, dict[str, str]]] = {
    "s1_watch": {
        "en": "This call has been going on for a while. If anyone talks about arrest, police or an investigation on a call, it is very often a scam. You can hang up at any time.",
        "hinglish": "Ye call kaafi der se chal rahi hai. Agar koi call par arrest, police ya jaanch ki baat kare, to aksar ye scam hota hai. Aap kabhi bhi phone kaat sakte hain.",
        "hi": "यह कॉल काफ़ी देर से चल रही है। अगर कोई कॉल पर गिरफ़्तारी, पुलिस या जाँच की बात करे, तो अक्सर यह धोखाधड़ी होती है। आप कभी भी फ़ोन काट सकते हैं।",
    },
    "s1_high": {
        "en": "This looks risky. Please hang up and call {child} now. Do not send any money and do not share any OTP or PIN.",
        "hinglish": "Ye risky lag raha hai. Please phone kaat dijiye aur abhi {child} ko call kijiye. Koi paisa mat bhejiye aur OTP ya PIN kisi ko mat bataiye.",
        "hi": "यह जोखिम भरा लग रहा है। कृपया फ़ोन काट दीजिए और अभी {child} को कॉल कीजिए। कोई पैसा न भेजें और OTP या PIN किसी को न बताएँ।",
    },
    "s2_watch": {
        "en": "An app that lets someone control a phone from far away was added to your phone. If someone asked you to install it, please do not open it, and tell {child}.",
        "hinglish": "Aapke phone par ek aisa app aaya hai jisse koi door se phone control kar sakta hai. Agar kisi ne kehkar lagwaya ho to use mat kholiye aur {child} ko bataiye.",
        "hi": "आपके फ़ोन पर एक ऐसा ऐप आया है जिससे कोई दूर से फ़ोन चला सकता है। अगर किसी ने कहकर लगवाया हो तो उसे न खोलें और {child} को बताएँ।",
    },
    "s2_high": {
        "en": "An app that lets someone control your phone is open. If someone asked you to open it, please close it now and call {child}.",
        "hinglish": "Ek aisa app khula hai jisse koi aapka phone control kar sakta hai. Agar kisi ne kholne ko kaha ho to ise abhi band kijiye aur {child} ko call kijiye.",
        "hi": "एक ऐसा ऐप खुला है जिससे कोई आपका फ़ोन चला सकता है। अगर किसी ने खोलने को कहा हो तो इसे अभी बंद करें और {child} को कॉल करें।",
    },
    "s3_watch": {
        "en": "Did someone on a call ask you to open a bank or payment app? Banks do not usually ask for this on a call. Please wait before you do anything.",
        "hinglish": "Kya call par kisi ne aapse bank ya payment app kholne ko kaha? Bank aam taur par call par aisa nahi kehta. Kuch bhi karne se pehle ruk jaiye.",
        "hi": "क्या कॉल पर किसी ने आपसे बैंक या पेमेंट ऐप खोलने को कहा? बैंक आम तौर पर कॉल पर ऐसा नहीं कहता। कुछ भी करने से पहले रुक जाइए।",
    },
    "s3_high": {
        "en": "Please stop. A caller asking you to use a bank or payment app is a very common trick. Do not send money and do not share an OTP or PIN. Call {child}.",
        "hinglish": "Please ruk jaiye. Call par bank ya payment app chalwana ek bahut aam chaal hai. Paisa mat bhejiye, OTP ya PIN mat bataiye. {child} ko call kijiye.",
        "hi": "कृपया रुक जाइए। कॉल पर बैंक या पेमेंट ऐप चलवाना एक बहुत आम चाल है। पैसा न भेजें, OTP या PIN न बताएँ। {child} को कॉल करें।",
    },
    "s4_watch": {
        "en": "Please wait a moment. Did the caller ask for money? Voices can be copied. Hang up and call {child} on the number you already have.",
        "hinglish": "Ek minute ruk jaiye. Kya call karne wale ne paise maange? Awaaz nakli ho sakti hai. Phone kaat kar {child} ko unke purane number par call kijiye.",
        "hi": "एक मिनट रुक जाइए। क्या कॉल करने वाले ने पैसे माँगे? आवाज़ नकली हो सकती है। फ़ोन काटकर {child} को उनके पुराने नंबर पर कॉल कीजिए।",
    },
    "s4_high": {
        "en": "Please stop. If someone asked for money, do not send it. Call {child} first, on the number you already have.",
        "hinglish": "Please ruk jaiye. Agar kisi ne paise maange hain to mat bhejiye. Pehle {child} ko unke purane number par call kijiye.",
        "hi": "कृपया रुक जाइए। अगर किसी ने पैसे माँगे हैं तो न भेजें। पहले {child} को उनके पुराने नंबर पर कॉल कीजिए।",
    },
    "s5_high": {
        "en": "A payment of {amount} just left your account. Was this you? If not, call your bank's helpline or 1930 now.",
        "hinglish": "Abhi aapke account se {amount} ka payment hua hai. Kya ye aapne kiya? Agar nahi, to abhi bank ki helpline ya 1930 par call kijiye.",
        "hi": "अभी आपके खाते से {amount} का भुगतान हुआ है। क्या यह आपने किया? अगर नहीं, तो अभी बैंक की हेल्पलाइन या 1930 पर कॉल कीजिए।",
    },
    "s6_watch": {
        "en": "Your phone camera was in use late at night. If that was not you, please tell {child}.",
        "hinglish": "Raat ko der se aapke phone ka camera chal raha tha. Agar ye aapne nahi kiya, to {child} ko bata dijiye.",
        "hi": "रात को देर से आपके फ़ोन का कैमरा चल रहा था। अगर यह आपने नहीं किया, तो {child} को बता दीजिए।",
    },
    "s8_info": {
        "en": "If anyone calls or messages about your pension or life certificate, never share an OTP or PIN. A real office should not ask for them.",
        "hinglish": "Agar koi aapki pension ya jeevan praman ke baare mein call ya message kare, to OTP ya PIN kabhi mat bataiye. Asli daftar ye nahi maangta.",
        "hi": "अगर कोई आपकी पेंशन या जीवन प्रमाण के बारे में कॉल या मैसेज करे, तो OTP या PIN कभी न बताएँ। असली दफ़्तर ये नहीं माँगता।",
    },
    "sos_ack": {
        "en": "I have told {child}. If you need an ambulance or the police, tap Call 112.",
        "hinglish": "Maine {child} ko bata diya hai. Agar ambulance ya police chahiye to 112 call dabaiye.",
        "hi": "मैंने {child} को बता दिया है। अगर एम्बुलेंस या पुलिस चाहिए तो 112 कॉल दबाइए।",
    },
    "fine_ack": {
        "en": "Thank you. I will remember that.",
        "hinglish": "Shukriya. Main ye yaad rakhungi.",
        "hi": "शुक्रिया। मैं यह याद रखूँगी।",
    },
    "ok_ack": {
        "en": "Thank you. I have told {child} that you are fine.",
        "hinglish": "Shukriya. Maine {child} ko bata diya hai ki aap theek hain.",
        "hi": "शुक्रिया। मैंने {child} को बता दिया है कि आप ठीक हैं।",
    },
}

ACTIONS: Final[dict[str, dict[str, str]]] = {
    "this_was_fine": {"en": "This was fine", "hinglish": "Ye theek tha", "hi": "यह ठीक था"},
    "yes_me": {"en": "Yes, it was me", "hinglish": "Haan, maine kiya", "hi": "हाँ, मैंने किया"},
    "call_child": {"en": "Call family", "hinglish": "Ghar par call karo", "hi": "परिवार को कॉल करें"},
    "dismiss": {"en": "OK", "hinglish": "Theek hai", "hi": "ठीक है"},
}

# which buttons a prompt shows: (action id, label key, ack kind sent back)
PROMPT_ACTIONS: Final[dict[str, list[tuple[str, str]]]] = {
    "s5_high": [("this_was_fine", "yes_me"), ("call_son_tapped", "call_child")],
    "s8_info": [("dismissed", "dismiss")],
    "s6_watch": [("this_was_fine", "this_was_fine"), ("dismissed", "dismiss")],
}
DEFAULT_ACTIONS: Final = [("this_was_fine", "this_was_fine"), ("call_son_tapped", "call_child"), ("dismissed", "dismiss")]

# ----------------------------------------------------------------------------- scam-check lines
VERDICT_LABEL: Final[dict[str, dict[str, str]]] = {
    "SCAM_LIKELY": {
        "en": "This looks very risky.",
        "hinglish": "Ye bahut risky lag raha hai.",
        "hi": "यह बहुत जोखिम भरा लग रहा है।",
    },
    "RISKY": {"en": "This looks risky.", "hinglish": "Ye risky lag raha hai.", "hi": "यह जोखिम भरा लग रहा है।"},
    "UNSURE": {"en": "I am not sure about this.", "hinglish": "Mujhe iske baare mein pakka nahi pata.", "hi": "मुझे इसके बारे में पक्का नहीं पता।"},
    "NO_SIGNS_FOUND": {"en": "I found no warning signs.", "hinglish": "Mujhe koi khatre ke nishaan nahi mile.", "hi": "मुझे कोई ख़तरे के निशान नहीं मिले।"},
}

REASONS: Final[dict[str, dict[str, str]]] = {
    "digital_arrest": {
        "en": "It sounds like the 'digital arrest' trick: someone pretending to be police, CBI, TRAI or a court and threatening arrest.",
        "hinglish": "Ye 'digital arrest' wali chaal jaisa hai: koi police, CBI, TRAI ya court bankar giraftari ka darr dikha raha hai.",
        "hi": "यह 'डिजिटल अरेस्ट' वाली चाल जैसा है: कोई पुलिस, CBI, TRAI या कोर्ट बनकर गिरफ़्तारी का डर दिखा रहा है।",
    },
    "otp_pin": {
        "en": "It asks for an OTP, PIN or password. A genuine bank or office never needs these from you.",
        "hinglish": "Ismein OTP, PIN ya password maanga ja raha hai. Asli bank ya daftar ye kabhi nahi maangta.",
        "hi": "इसमें OTP, PIN या पासवर्ड माँगा जा रहा है। असली बैंक या दफ़्तर ये कभी नहीं माँगता।",
    },
    "kyc_block": {
        "en": "It says your account or KYC will be blocked unless you act fast. This is a common trick.",
        "hinglish": "Ismein likha hai ki jaldi na karne par aapka account ya KYC band ho jayega. Ye ek aam chaal hai.",
        "hi": "इसमें लिखा है कि जल्दी न करने पर आपका खाता या KYC बंद हो जाएगा। यह एक आम चाल है।",
    },
    "utility": {
        "en": "It threatens to cut your electricity or gas unless you call or pay now. This is a common trick.",
        "hinglish": "Ismein dhamki hai ki abhi call ya payment na karne par bijli ya gas kat jayegi. Ye ek aam chaal hai.",
        "hi": "इसमें धमकी है कि अभी कॉल या भुगतान न करने पर बिजली या गैस कट जाएगी। यह एक आम चाल है।",
    },
    "collect_refund": {
        "en": "It talks of a refund or prize but asks you to approve a request or enter your PIN. Receiving money never needs a PIN.",
        "hinglish": "Ismein refund ya inaam ki baat hai par request approve karne ya PIN daalne ko kaha hai. Paisa lene ke liye PIN nahi lagta.",
        "hi": "इसमें रिफंड या इनाम की बात है पर रिक्वेस्ट मंज़ूर करने या PIN डालने को कहा है। पैसा लेने के लिए PIN नहीं लगता।",
    },
    "remote_access": {
        "en": "It asks you to install or open an app that lets someone control your phone.",
        "hinglish": "Ismein ek aisa app lagane ya kholne ko kaha hai jisse koi aapka phone control kar sake.",
        "hi": "इसमें एक ऐसा ऐप लगाने या खोलने को कहा है जिससे कोई आपका फ़ोन चला सके।",
    },
    "apk_file": {
        "en": "It asks you to install an app file sent on chat (APK, 'wedding card', 'parcel tracking'). Such files can steal money and messages.",
        "hinglish": "Ismein chat par aayi app file (APK, 'shaadi card', 'parcel tracking') install karne ko kaha hai. Aisi files paise aur messages chura sakti hain.",
        "hi": "इसमें चैट पर आई ऐप फ़ाइल (APK, 'शादी का कार्ड', 'पार्सल ट्रैकिंग') लगाने को कहा है। ऐसी फ़ाइलें पैसे और मैसेज चुरा सकती हैं।",
    },
    "pension": {
        "en": "It says your pension or life certificate will stop, and asks you to click, call or pay.",
        "hinglish": "Ismein likha hai ki aapki pension ya jeevan praman ruk jayega, aur click, call ya payment karne ko kaha hai.",
        "hi": "इसमें लिखा है कि आपकी पेंशन या जीवन प्रमाण रुक जाएगा, और क्लिक, कॉल या भुगतान करने को कहा है।",
    },
    "relative_trouble": {
        "en": "It says a family member is in trouble and asks for money. Voices and numbers can be faked.",
        "hinglish": "Ismein kaha hai ki ghar ka koi sadasya musibat mein hai aur paise maange hain. Awaaz aur number nakli ho sakte hain.",
        "hi": "इसमें कहा है कि घर का कोई सदस्य मुसीबत में है और पैसे माँगे हैं। आवाज़ और नंबर नकली हो सकते हैं।",
    },
    "investment": {
        "en": "It promises big or sure profits through a group or app. Such offers are very often frauds.",
        "hinglish": "Ismein group ya app ke zariye bade ya pakke munafe ka waada hai. Aise offer aksar dhokha hote hain.",
        "hi": "इसमें ग्रुप या ऐप के ज़रिए बड़े या पक्के मुनाफ़े का वादा है। ऐसे ऑफ़र अक्सर धोखा होते हैं।",
    },
    "safe_account": {
        "en": "It asks you to move money to a special 'verification' or 'RBI' account. No bank or officer does this.",
        "hinglish": "Ismein paise ek khaas 'verification' ya 'RBI' account mein daalne ko kaha hai. Koi bank ya afsar aisa nahi karta.",
        "hi": "इसमें पैसे एक ख़ास 'वेरिफ़िकेशन' या 'RBI' खाते में डालने को कहा है। कोई बैंक या अफ़सर ऐसा नहीं करता।",
    },
    "prize": {
        "en": "It says you won a prize or lottery. Genuine prizes do not ask you to pay first.",
        "hinglish": "Ismein likha hai ki aapne inaam ya lottery jeeti hai. Asli inaam ke liye pehle paisa nahi maanga jaata.",
        "hi": "इसमें लिखा है कि आपने इनाम या लॉटरी जीती है। असली इनाम के लिए पहले पैसा नहीं माँगा जाता।",
    },
    "link_lookalike": {
        "en": "This web address looks like a copy of an official site but is not the official address.",
        "hinglish": "Ye web address kisi asli site ki nakal jaisa lagta hai, par asli address nahi hai.",
        "hi": "यह वेब पता किसी असली साइट की नकल जैसा लगता है, पर असली पता नहीं है।",
    },
    "link_shortener": {
        "en": "This link hides where it really goes.",
        "hinglish": "Ye link chhupata hai ki andar kahan le jayega.",
        "hi": "यह लिंक छिपाता है कि अंदर कहाँ ले जाएगा।",
    },
    "link_unknown": {
        "en": "I do not recognise this website.",
        "hinglish": "Main is website ko nahi pehchanti.",
        "hi": "मैं इस वेबसाइट को नहीं पहचानती।",
    },
    "urgency_secrecy": {
        "en": "It rushes you and asks you to keep it secret. That is a warning sign.",
        "hinglish": "Ismein jaldi machayi gayi hai aur kisi ko batane se roka gaya hai. Ye khatre ka nishaan hai.",
        "hi": "इसमें जल्दी मचाई गई है और किसी को बताने से रोका गया है। यह ख़तरे का निशान है।",
    },
    "money_request": {
        "en": "It asks for money, and I cannot check who is really asking.",
        "hinglish": "Ismein paise maange gaye hain, aur main check nahi kar sakti ki asal mein kaun maang raha hai.",
        "hi": "इसमें पैसे माँगे गए हैं, और मैं जाँच नहीं सकती कि असल में कौन माँग रहा है।",
    },
    "app_remote": {
        "en": "This app lets someone control a phone from far away.",
        "hinglish": "Is app se koi door se phone control kar sakta hai.",
        "hi": "इस ऐप से कोई दूर से फ़ोन चला सकता है।",
    },
    "app_apk": {
        "en": "This looks like an app file sent outside the Play Store, a common way to steal money.",
        "hinglish": "Ye Play Store ke bahar se aayi app file jaisa hai, paise churane ka aam tareeka.",
        "hi": "यह प्ले स्टोर के बाहर से आई ऐप फ़ाइल जैसा है, पैसे चुराने का आम तरीका।",
    },
    "number_international": {
        "en": "This is a number from outside India. Many scam calls come from such numbers.",
        "hinglish": "Ye India ke bahar ka number hai. Bahut se scam call aise numbers se aate hain.",
        "hi": "यह भारत के बाहर का नंबर है। बहुत से स्कैम कॉल ऐसे नंबरों से आते हैं।",
    },
    "number_marketing": {
        "en": "This is a sales or marketing type of number, not a person's number.",
        "hinglish": "Ye bikri ya marketing wala number hai, kisi insaan ka number nahi.",
        "hi": "यह बिक्री या मार्केटिंग वाला नंबर है, किसी इंसान का नंबर नहीं।",
    },
    "number_other": {
        "en": "A number alone does not tell me who is calling.",
        "hinglish": "Sirf number se mujhe pata nahi chalta ki kaun call kar raha hai.",
        "hi": "सिर्फ़ नंबर से मुझे पता नहीं चलता कि कौन कॉल कर रहा है।",
    },
    "screenshot": {
        "en": "I cannot read pictures yet.",
        "hinglish": "Main abhi tasveerein padh nahi sakti.",
        "hi": "मैं अभी तस्वीरें पढ़ नहीं सकती।",
    },
    "none": {
        "en": "Nothing in it looks like a known trick.",
        "hinglish": "Ismein koi jaani-pehchaani chaal nahi dikhi.",
        "hi": "इसमें कोई जानी-पहचानी चाल नहीं दिखी।",
    },
    "unsure": {
        "en": "There is not enough here for me to tell.",
        "hinglish": "Mere liye yahan itna nahi hai ki main bata sakun.",
        "hi": "मेरे लिए यहाँ इतना नहीं है कि मैं बता सकूँ।",
    },
    "second_opinion": {
        "en": "Parts of it look like a known trick.",
        "hinglish": "Iske kuch hisse jaani-pehchaani chaal jaise lagte hain.",
        "hi": "इसके कुछ हिस्से जानी-पहचानी चाल जैसे लगते हैं।",
    },
}

NEXT_STEPS: Final[dict[str, dict[str, str]]] = {
    "hang_up": {
        "en": "Hang up. Do not press anything and do not install anything.",
        "hinglish": "Phone kaat dijiye. Kuch mat dabaiye, kuch install mat kijiye.",
        "hi": "फ़ोन काट दीजिए। कुछ न दबाएँ, कुछ इंस्टॉल न करें।",
    },
    "no_install": {
        "en": "Do not install or open it. Delete it, and tell {child}.",
        "hinglish": "Ise install ya open mat kijiye. Delete kar dijiye aur {child} ko bataiye.",
        "hi": "इसे इंस्टॉल या ओपन न करें। डिलीट कर दें और {child} को बताएँ।",
    },
    "call_child": {
        "en": "Call {child} on a number you already know before you do anything.",
        "hinglish": "Kuch bhi karne se pehle {child} ko unke purane number par call kijiye.",
        "hi": "कुछ भी करने से पहले {child} को उनके पुराने नंबर पर कॉल कीजिए।",
    },
    "report_1930": {
        "en": "If money has already gone, call 1930 (the cyber crime helpline) at once and tell {child}.",
        "hinglish": "Agar paisa chala gaya hai, to turant 1930 (cyber crime helpline) par call kijiye aur {child} ko bataiye.",
        "hi": "अगर पैसा चला गया है, तो तुरंत 1930 (साइबर क्राइम हेल्पलाइन) पर कॉल करें और {child} को बताएँ।",
    },
    "never_otp": {
        "en": "Never share an OTP or PIN with anyone.",
        "hinglish": "OTP ya PIN kisi ko kabhi mat bataiye.",
        "hi": "OTP या PIN किसी को कभी न बताएँ।",
    },
    "own_bank": {
        "en": "If you are worried, call your bank on the number printed on your card or passbook.",
        "hinglish": "Agar chinta ho, to apne card ya passbook par chhape number par bank ko call kijiye.",
        "hi": "अगर चिंता हो, तो अपने कार्ड या पासबुक पर छपे नंबर पर बैंक को कॉल करें।",
    },
    "type_address": {
        "en": "Do not tap the link. Type the official website address yourself, or ask {child}.",
        "hinglish": "Link par mat dabaiye. Official website ka address khud type kijiye, ya {child} se poochiye.",
        "hi": "लिंक पर न दबाएँ। आधिकारिक वेबसाइट का पता खुद टाइप करें, या {child} से पूछें।",
    },
    "verify_first": {
        "en": "Before sending any money, call the person on a number you already have.",
        "hinglish": "Paise bhejne se pehle, us insaan ko unke purane number par call kijiye.",
        "hi": "पैसे भेजने से पहले, उस इंसान को उनके पुराने नंबर पर कॉल कीजिए।",
    },
    "none_found": {
        "en": "I cannot promise anything. Still never share an OTP or PIN.",
        "hinglish": "Main kuch guarantee nahi de sakti. Phir bhi OTP ya PIN kisi ko mat bataiye.",
        "hi": "मैं कोई गारंटी नहीं दे सकती। फिर भी OTP या PIN किसी को न बताएँ।",
    },
    "ask_child": {
        "en": "Please ask {child} before you do anything.",
        "hinglish": "Kuch bhi karne se pehle {child} se poochh lijiye.",
        "hi": "कुछ भी करने से पहले {child} से पूछ लीजिए।",
    },
    "send_text": {
        "en": "Please send the words or the link as text, or show it to {child}.",
        "hinglish": "Please likhi hui baat ya link text mein bhejiye, ya {child} ko dikhaiye.",
        "hi": "कृपया लिखी हुई बात या लिंक टेक्स्ट में भेजें, या {child} को दिखाएँ।",
    },
}


def lines_by_table() -> dict[str, dict[str, dict[str, str]]]:
    return {
        "PROMPTS": PROMPTS, "ACTIONS": ACTIONS, "VERDICT_LABEL": VERDICT_LABEL,
        "REASONS": REASONS, "NEXT_STEPS": NEXT_STEPS, "CHILD": {"child": CHILD},
    }


def pending_line_count() -> int:
    """Number of distinct spoken/shown lines (each language variant counts as one) awaiting approval."""
    return sum(len(v) for table in lines_by_table().values() for v in table.values())


def pick(table: dict[str, dict[str, str]], key: str, lang: str, **fmt: str) -> str:
    lang = lang if lang in LANGS else "hinglish"
    text = table[key][lang]
    fmt.setdefault("child", CHILD[lang])
    return text.format(**fmt)
