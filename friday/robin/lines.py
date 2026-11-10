# ruff: noqa: E501
"""EVERY line Robin may SPEAK to a parent (and every chat line to the child). One module, so the founder
reviews one place (docs/ROBIN_LINES.md is generated from it and checked by a test).

STATUS: PENDING_FOUNDER_APPROVAL for every line (hear-before-change, CLAUDE.md rule 3). No audio has been
generated. ``LINE_STATUS`` is checked by the real dial adapter (``telephony.py``): while it is not
``APPROVED`` the real call REFUSES to dial, so nothing can ring a parent before the founder has heard the
audio and a reviewed commit flips this constant (and the docs table).

The product name is NEVER typed here: every line carries ``{brand}`` where the name is needed and ``say``
fills it from the one brand setting (``FRIDAY_BRAND_NAME``). Other slots: {parent} how the family calls
the parent ('Papa'), {child} the child's name, {medicine}, {amount}, {why}, {time}.

Rules the lines obey (tests enforce them):
* Spoken lines say it is an AI assistant (the intro), never ask for an OTP, PIN, password, card or Aadhaar
  number (the words appear only inside a refusal), give no medical advice (only 'ask the doctor').
* Spoken lines are short and calm, female forms in Hindi; Roman for ``hinglish``, Devanagari for ``hi``.
* Kind ``spoken`` lines exist in en, hinglish and hi. Kind ``chat`` lines (to the child) in en and hinglish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
APPROVED = "APPROVED"
LANGS = ("hinglish", "hi", "en")
CHAT_LANGS = ("hinglish", "en")

SPOKEN: dict[str, dict[str, str]] = {}
CHAT: dict[str, dict[str, str]] = {}


def _s(key: str, en: str, hl: str, hi: str) -> None:
    SPOKEN[key] = {"en": en, "hinglish": hl, "hi": hi}


def _c(key: str, en: str, hl: str) -> None:
    CHAT[key] = {"en": en, "hinglish": hl}


# ============================================================================ spoken: introduction / consent call
_s("intro.greet",
   "Hello {parent}. I am {brand}. I am an AI assistant, not a person. {child} asked me to keep in touch with you and look after you.",
   "Namaste {parent}. Main {brand} bol rahi hoon. Main ek AI assistant hoon, koi insaan nahi. {child} ne mujhe aapse baat karne aur aapka khayal rakhne ke liye kaha hai.",
   "नमस्ते {parent}। मैं {brand} बोल रही हूँ। मैं एक AI असिस्टेंट हूँ, कोई इंसान नहीं। {child} ने मुझसे कहा है कि मैं आपसे बात करूँ और आपका ख़याल रखूँ।")
_s("intro.will",
   "Each day I can call to ask how you are, remind you about your medicines, and tell {child} if something looks risky, like a suspicious call.",
   "Main roz ek chhota phone karke poochh sakti hoon ki aap kaise hain, dawai yaad dila sakti hoon, aur agar koi sandehi call ya paise ka maamla dikhe to {child} ko bata sakti hoon.",
   "मैं रोज़ एक छोटा फ़ोन करके पूछ सकती हूँ कि आप कैसे हैं, दवाई याद दिला सकती हूँ, और अगर कोई संदिग्ध कॉल या पैसे का मामला दिखे तो {child} को बता सकती हूँ।")
_s("intro.wont",
   "I do not record your calls. I do not read your messages. I will never ask you for an OTP, a PIN or a password. I do not send money, and I do not give medical advice; for that, ask your doctor.",
   "Main aapki call record nahi karti. Main aapke messages nahi padhti. Main aapse OTP, PIN ya password kabhi nahi maangungi. Main paise nahi bhejti, aur dawai ke baare mein salaah nahi deti; wo doctor se poochhiye.",
   "मैं आपकी कॉल रिकॉर्ड नहीं करती। मैं आपके मैसेज नहीं पढ़ती। मैं आपसे OTP, PIN या पासवर्ड कभी नहीं माँगूँगी। मैं पैसे नहीं भेजती, और दवाई के बारे में सलाह नहीं देती; वो डॉक्टर से पूछिए।")
_s("intro.no",
   "You can say no to anything, and you can say 'stop' at any time and I will stop. {child} can see what I do, and so can you.",
   "Aap kisi bhi cheez ke liye na bol sakte hain, aur kabhi bhi 'ruk jao' bol dijiye, main ruk jaungi. Main jo bhi karti hoon wo {child} ko bhi dikhta hai, aur aapko bhi.",
   "आप किसी भी चीज़ के लिए ना बोल सकते हैं, और कभी भी 'रुक जाओ' बोल दीजिए, मैं रुक जाऊँगी। मैं जो भी करती हूँ वो {child} को भी दिखता है, और आपको भी।")
_s("intro.ask.daily_checkin_calls",
   "May I call you once a day to ask how you are? Please say yes or no.",
   "Kya main roz ek baar phone karke aapka haal poochh sakti hoon? Kripya haan ya na boliye.",
   "क्या मैं रोज़ एक बार फ़ोन करके आपका हाल पूछ सकती हूँ? कृपया हाँ या ना बोलिए।")
_s("intro.ask.medicine_reminders",
   "May I remind you about your medicines? Yes or no?",
   "Kya main aapko dawai ka yaad dila sakti hoon? Haan ya na?",
   "क्या मैं आपको दवाई का याद दिला सकती हूँ? हाँ या ना?")
_s("intro.ask.scam_check",
   "If you want me to check a call or a message that looks strange, may I help? Yes or no?",
   "Agar aap chahein ki main kisi ajeeb call ya message ko check karun, to kya main madad kar sakti hoon? Haan ya na?",
   "अगर आप चाहें कि मैं किसी अजीब कॉल या मैसेज को चेक करूँ, तो क्या मैं मदद कर सकती हूँ? हाँ या ना?")
_s("intro.ask.share_summary_with_child",
   "May I tell {child} a short summary each day, such as whether you are well? Yes or no?",
   "Kya main {child} ko roz ek chhota saar bata sakti hoon, jaise ki aap theek hain ya nahi? Haan ya na?",
   "क्या मैं {child} को रोज़ एक छोटा सार बता सकती हूँ, जैसे कि आप ठीक हैं या नहीं? हाँ या ना?")
_s("intro.thanks",
   "Thank you. I will do only what you said yes to. You can call this number and say 'stop' at any time.",
   "Dhanyavaad. Main sirf wahi karungi jis par aapne haan kaha. Aap kabhi bhi is number par phone karke 'ruk jao' bol sakte hain.",
   "धन्यवाद। मैं सिर्फ़ वही करूँगी जिस पर आपने हाँ कहा। आप कभी भी इस नंबर पर फ़ोन करके 'रुक जाओ' बोल सकते हैं।")
_s("intro.declined",
   "That is fine. I will not call you again unless you ask me to. Thank you for your time.",
   "Theek hai. Main aapko dobara phone nahi karungi jab tak aap na kahein. Aapka samay dene ke liye dhanyavaad.",
   "ठीक है। मैं आपको दोबारा फ़ोन नहीं करूँगी जब तक आप न कहें। आपका समय देने के लिए धन्यवाद।")
_s("intro.not_now",
   "Sorry to disturb you. I will not call again unless you or {child} ask me to.",
   "Disturb karne ke liye maaf kijiye. Main dobara phone nahi karungi jab tak aap ya {child} na kahein.",
   "परेशान करने के लिए माफ़ कीजिए। मैं दोबारा फ़ोन नहीं करूँगी जब तक आप या {child} न कहें।")

# ============================================================================ spoken: daily check-in
_s("checkin.greet",
   "Hello {parent}, this is {brand}, your AI assistant. Just a short check-in.",
   "Namaste {parent}, main {brand} bol rahi hoon, aapki AI assistant. Bas ek chhota sa haal-chaal.",
   "नमस्ते {parent}, मैं {brand} बोल रही हूँ, आपकी AI असिस्टेंट। बस एक छोटा सा हाल-चाल।")
_s("call.repeat",
   "Sorry, I could not hear that. Could you say it once more?",
   "Maaf kijiye, mujhe sunai nahi diya. Kya aap ek baar phir bol sakte hain?",
   "माफ़ कीजिए, मुझे सुनाई नहीं दिया। क्या आप एक बार फिर बोल सकते हैं?")
_s("checkin.q.ate", "Have you eaten today?", "Aapne aaj kuch khaya?", "आपने आज कुछ खाया?")
_s("checkin.q.slept", "Did you sleep well last night?", "Raat ko neend achhi aayi?", "रात को नींद अच्छी आई?")
_s("checkin.q.pain", "Is there any pain or discomfort today?", "Aaj kisi tarah ka dard ya takleef hai?", "आज किसी तरह का दर्द या तकलीफ़ है?")
_s("checkin.q.mood", "In one word, how is your mood today?", "Ek shabd mein bataiye, aaj mann kaisa hai?", "एक शब्द में बताइए, आज मन कैसा है?")
_s("checkin.q.strange", "Did anyone call you today asking for money, or did anything feel strange?", "Aaj kisi ne paise maange ya kuch ajeeb laga?", "आज किसी ने पैसे माँगे या कुछ अजीब लगा?")
_s("checkin.q.meds", "Have you taken your medicines today?", "Aapne aaj ki dawai li?", "आपने आज की दवाई ली?")
_s("checkin.pain_ack",
   "Thank you for telling me. I will let {child} know. For pain, please speak to your doctor.",
   "Batane ke liye dhanyavaad. Main {child} ko bata dungi. Dard ke liye doctor se zaroor milein.",
   "बताने के लिए धन्यवाद। मैं {child} को बता दूँगी। दर्द के लिए डॉक्टर से ज़रूर मिलें।")
_s("checkin.strange_ack",
   "Thank you. Please do not share any OTP, PIN or password, and do not send money. I will tell {child}.",
   "Dhanyavaad. Kripya koi OTP, PIN ya password mat batayein aur paise mat bhejein. Main {child} ko bata dungi.",
   "धन्यवाद। कृपया कोई OTP, PIN या पासवर्ड मत बताएँ और पैसे मत भेजें। मैं {child} को बता दूँगी।")
_s("checkin.bye", "Thank you, {parent}. Take care. Goodbye.", "Dhanyavaad {parent}. Apna khayal rakhiye. Namaste.", "धन्यवाद {parent}। अपना ख़याल रखिए। नमस्ते।")

# ============================================================================ spoken: medicine
_s("med.remind", "{parent}, it is time for {medicine}. Have you taken it?", "{parent}, {medicine} ka time ho gaya hai. Aapne li?", "{parent}, {medicine} का समय हो गया है। आपने ली?")
_s("med.thanks", "Thank you.", "Dhanyavaad.", "धन्यवाद।")
_s("med.later", "All right. Please take it when you can. I will tell {child} if it is missed.", "Theek hai. Jab ho sake tab le lijiye. Agar chhoot gayi to main {child} ko bata dungi.", "ठीक है। जब हो सके तब ले लीजिए। अगर छूट गई तो मैं {child} को बता दूँगी।")
_s("med.count_ask", "How many tablets of {medicine} are left? Please count and tell me the number.", "{medicine} ki kitni goliyan bachi hain? Kripya ginkar number bataiye.", "{medicine} की कितनी गोलियाँ बची हैं? कृपया गिनकर नंबर बताइए।")
_s("med.count_thanks", "Thank you, I have noted it.", "Dhanyavaad, maine note kar liya.", "धन्यवाद, मैंने नोट कर लिया।")

# ============================================================================ spoken: alert nudges to the parent
_s("nudge.generic",
   "{parent}, please pause for a moment. If anyone asks you for money, an OTP, a PIN or to open an app, do not do it. Call {child} first. Is everything fine?",
   "{parent}, zara rukiye. Agar koi paise, OTP, PIN maange ya koi app kholne ko kahe, to bilkul mat kijiye. Pehle {child} ko phone kijiye. Kya sab theek hai?",
   "{parent}, ज़रा रुकिए। अगर कोई पैसे, OTP, PIN माँगे या कोई ऐप खोलने को कहे, तो बिल्कुल मत कीजिए। पहले {child} को फ़ोन कीजिए। क्या सब ठीक है?")
_s("nudge.remote_access",
   "{parent}, an app that lets someone control your phone seems to be open. Please close it, and call {child}. Are you fine?",
   "{parent}, aisa lagta hai ki koi app khula hai jisse koi aapka phone control kar sakta hai. Use band kar dijiye aur {child} ko phone kijiye. Aap theek hain?",
   "{parent}, ऐसा लगता है कि कोई ऐप खुला है जिससे कोई आपका फ़ोन कंट्रोल कर सकता है। उसे बंद कर दीजिए और {child} को फ़ोन कीजिए। आप ठीक हैं?")
_s("nudge.money",
   "{parent}, did you just send money? If not, please call your bank's helpline right now and tell {child}. Was it you?",
   "{parent}, kya aapne abhi paise bheje? Agar nahi, to turant apne bank ki helpline ko phone kijiye aur {child} ko bataiye. Kya wo aap the?",
   "{parent}, क्या आपने अभी पैसे भेजे? अगर नहीं, तो तुरंत अपने बैंक की हेल्पलाइन को फ़ोन कीजिए और {child} को बताइए। क्या वो आप थे?")
_s("nudge.safe_word",
   "{parent}, if someone says they are a relative and asks for money, ask them for the family safe word. If they cannot say it, hang up and call {child}. Is everything fine?",
   "{parent}, agar koi khud ko rishtedar bataye aur paise maange, to usse family safe word poochhiye. Wo na bata sake to phone kaat dijiye aur {child} ko phone kijiye. Kya sab theek hai?",
   "{parent}, अगर कोई ख़ुद को रिश्तेदार बताए और पैसे माँगे, तो उससे फ़ैमिली सेफ़ वर्ड पूछिए। वो न बता सके तो फ़ोन काट दीजिए और {child} को फ़ोन कीजिए। क्या सब ठीक है?")
_s("nudge.fine_ack",
   "Thank you. I will tell {child} that you are fine.",
   "Dhanyavaad. Main {child} ko bata dungi ki aap theek hain.",
   "धन्यवाद। मैं {child} को बता दूँगी कि आप ठीक हैं।")
_s("nudge.not_fine_ack",
   "I am telling {child} right now. Please stay safe and do not share anything.",
   "Main abhi {child} ko bata rahi hoon. Kripya surakshit rahiye aur kuch bhi mat batayein.",
   "मैं अभी {child} को बता रही हूँ। कृपया सुरक्षित रहिए और कुछ भी मत बताइए।")

# ============================================================================ spoken: SOS and the parent phoning the number
_s("sos.parent",
   "{parent}, I am {brand}. I have told {child} right now. Please stay on the line or keep your phone near you. If you need an ambulance or the police, press 112 on your phone.",
   "{parent}, main {brand} hoon. Maine abhi {child} ko khabar kar di hai. Kripya line par rahiye ya phone paas rakhiye. Ambulance ya police chahiye to apne phone par 112 dabaiye.",
   "{parent}, मैं {brand} हूँ। मैंने अभी {child} को ख़बर कर दी है। कृपया लाइन पर रहिए या फ़ोन पास रखिए। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए।")
_s("sos.ask", "Can you tell me in a few words what happened?", "Kya aap thode shabdon mein bata sakte hain ki kya hua?", "क्या आप थोड़े शब्दों में बता सकते हैं कि क्या हुआ?")
_s("sos.noted", "Thank you. I have passed this on to {child}.", "Dhanyavaad. Maine yeh {child} tak pahuncha diya hai.", "धन्यवाद। मैंने यह {child} तक पहुँचा दिया है।")
_s("inbound.hello",
   "Hello {parent}, this is {brand}. I am here. Say 'help' if you need help, or 'stop' to pause me.",
   "Namaste {parent}, main {brand} hoon. Madad chahiye to 'madad' boliye, ya mujhe rokne ke liye 'ruk jao' boliye.",
   "नमस्ते {parent}, मैं {brand} हूँ। मदद चाहिए तो 'मदद' बोलिए, या मुझे रोकने के लिए 'रुक जाओ' बोलिए।")
# T09: replies on the parent's widget (press-to-talk). No 'stay on the line' (this is not a call). 112 is SHOWN, never dialled by Robin.
_s("widget.sos",
   "{parent}, I have told {child} right now. If you need an ambulance or the police, press 112 on your phone.",
   "{parent}, maine abhi {child} ko khabar kar di hai. Ambulance ya police chahiye to apne phone par 112 dabaiye.",
   "{parent}, मैंने अभी {child} को ख़बर कर दी है। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए।")
_s("widget.sos_failed",
   "I could not reach {child} just now. If you need an ambulance or the police, press 112 on your phone.",
   "Main abhi {child} tak khabar nahi pahuncha payi. Ambulance ya police chahiye to apne phone par 112 dabaiye.",
   "मैं अभी {child} तक ख़बर नहीं पहुँचा पाई। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए।")
_s("widget.unclear",
   "I could not hear you clearly. Please press the button and say it once more.",
   "Mujhe aawaz saaf nahi aayi. Kripya button dabakar ek baar phir boliye.",
   "मुझे आवाज़ साफ़ नहीं आई। कृपया बटन दबाकर एक बार फिर बोलिए।")
_s("inbound.unclear",
   "Sorry {parent}, this is {brand}. I could not hear that. Please say it again.",
   "Maaf kijiye {parent}, main {brand} hoon. Mujhe woh sunai nahi diya. Kripya dobara boliye.",
   "माफ़ कीजिए {parent}, मैं {brand} हूँ। मुझे वह सुनाई नहीं दिया। कृपया दोबारा बोलिए।")  # PENDING founder approval of wording (T08): unreadable parent audio
# T13: the verdict on something the parent forwarded (text, link or screenshot). PENDING founder approval of wording. Never the word "safe":
# the best answer is "no warning signs found". {verdict} is the scam-check headline (friday/robindevice/copy.py), {why} its one-line reason.
_s("scam.high",
   "{verdict} {why} {parent}, please do not click anything, do not pay and do not share any OTP or PIN. Call {child} first.",
   "{verdict} {why} {parent}, kripya kuch bhi click mat kijiye, paise mat bhejiye aur OTP ya PIN kisi ko mat bataiye. Pehle {child} ko call kijiye.",
   "{verdict} {why} {parent}, कृपया कुछ भी क्लिक मत कीजिए, पैसे मत भेजिए और OTP या PIN किसी को मत बताइए। पहले {child} को कॉल कीजिए।")
_s("scam.risky",
   "{verdict} {why} Please do not click and do not pay. Call {child} before you do anything.",
   "{verdict} {why} Kripya click mat kijiye aur paise mat bhejiye. Kuch bhi karne se pehle {child} ko call kijiye.",
   "{verdict} {why} कृपया क्लिक मत कीजिए और पैसे मत भेजिए। कुछ भी करने से पहले {child} को कॉल कीजिए।")
_s("scam.unsure",
   "{verdict} Please do not click and do not pay yet. Show it to {child} first.",
   "{verdict} Kripya abhi click mat kijiye aur paise mat bhejiye. Pehle yeh {child} ko dikhaiye.",
   "{verdict} कृपया अभी क्लिक मत कीजिए और पैसे मत भेजिए। पहले यह {child} को दिखाइए।")
_s("scam.nosigns",
   "{verdict} That does not mean everything is fine. If it asks for money, an OTP or a click, please call {child} first.",
   "{verdict} Iska matlab yeh nahi ki sab theek hai. Agar isme paise, OTP ya click maanga jaye to pehle {child} ko call kijiye.",
   "{verdict} इसका मतलब यह नहीं कि सब ठीक है। अगर इसमें पैसे, OTP या क्लिक माँगा जाए तो पहले {child} को कॉल कीजिए।")
_s("scam.unreadable",
   "I could not read this. Please do not click and do not pay. Show it to {child}.",
   "Main ise padh nahi payi. Kripya click mat kijiye aur paise mat bhejiye. Yeh {child} ko dikhaiye.",
   "मैं इसे पढ़ नहीं पाई। कृपया क्लिक मत कीजिए और पैसे मत भेजिए। यह {child} को दिखाइए।")
_s("scam.repeat",
   "This sender has written before. Please do not reply.",
   "Is bhejne wale ne pehle bhi likha hai. Kripya jawab mat dijiye.",
   "इस भेजने वाले ने पहले भी लिखा है। कृपया जवाब मत दीजिए।")
_s("scam.no_consent",
   "{parent}, I cannot check messages yet, because {child} has not switched this on. Please show it to {child}, and do not click or pay until then.",
   "{parent}, main abhi messages nahi jaanch sakti, kyunki {child} ne yeh chalu nahi kiya hai. Kripya yeh {child} ko dikhaiye, aur tab tak click mat kijiye aur paise mat bhejiye.",
   "{parent}, मैं अभी मैसेज नहीं जाँच सकती, क्योंकि {child} ने यह चालू नहीं किया है। कृपया यह {child} को दिखाइए, और तब तक क्लिक मत कीजिए और पैसे मत भेजिए।")
_c("scam.child_high",
   "{parent} sent {brand} a message to check, and it looks very risky. {what} I told {parent} not to click, not to pay and to call you. I did not keep the message. Please call {parent} now.",
   "{parent} ne {brand} ko jaanchne ke liye ek message bheja, aur wo bahut risky lag raha hai. {what} Maine {parent} ko click aur payment na karne aur aapko call karne ko kaha hai. Maine message rakha nahi hai. Kripya abhi {parent} ko call kijiye.")
_c("scam.child_repeat",
   "{parent} sent {brand} another message from a sender that has now written {n} times. {what} I told {parent} not to reply. I did not keep the message. Please call {parent}.",
   "{parent} ne {brand} ko ek aur message bheja, jis bhejne wale ne ab {n} baar likha hai. {what} Maine {parent} ko jawab na dene ko kaha hai. Maine message rakha nahi hai. Kripya {parent} ko call kijiye.")
_c("scam.child_no_consent",
   "{parent} tried to send {brand} a message to check, but scam check is not switched on, so I did not look at it. I told {parent} to show it to you. To switch it on, write: enable scam check.",
   "{parent} ne {brand} ko jaanchne ke liye message bhejna chaha, lekin scam check chalu nahi hai, isliye maine use dekha nahi. Maine {parent} ko aapko dikhane ko kaha hai. Chalu karne ke liye likhiye: enable scam check.")
_c("scam.child_playbook",
   "If money was already sent, a code was shared or a link was opened, act in the first hour: 1) call your bank's helpline and ask them to block or freeze the payment; 2) call 1930, the cyber fraud helpline; 3) write down the amount, the time and the transaction ids; 4) file a report at cybercrime.gov.in; 5) be kind to {parent}, this happens to many careful people.",
   "Agar paise bhej diye gaye hain, code bata diya gaya hai ya link khol liya gaya hai, to pehle ghante mein yeh kijiye: 1) apne bank ki helpline par call karke payment block ya freeze karwayiye; 2) 1930 par call kijiye, yeh cyber fraud helpline hai; 3) rakam, samay aur transaction id likh lijiye; 4) cybercrime.gov.in par report darj kijiye; 5) {parent} se pyaar se baat kijiye, yeh bahut samajhdar logon ke saath bhi hota hai.")
_s("pause.ack",
   "All right, I have stopped. I will not call you until you tell me to start again.",
   "Theek hai, main ruk gayi. Jab tak aap dobara shuru karne ko na kahein, main phone nahi karungi.",
   "ठीक है, मैं रुक गई। जब तक आप दोबारा शुरू करने को न कहें, मैं फ़ोन नहीं करूँगी।")
_s("resume.ack", "All right, I am back. I will do what you agreed to.", "Theek hai, main wapas aa gayi. Main wahi karungi jis par aap raazi hue the.", "ठीक है, मैं वापस आ गई। मैं वही करूँगी जिस पर आप राज़ी हुए थे।")
_s("delete.ack", "Done. I have deleted everything about you. Goodbye.", "Ho gaya. Maine aapke baare mein sab kuch hata diya. Namaste.", "हो गया। मैंने आपके बारे में सब कुछ हटा दिया। नमस्ते।")

# ============================================================================ spoken: calls to the child / second contact
_s("child.ring",
   "Hello {child}, this is {brand}. There is an important message about {parent} on WhatsApp. Please look at it now.",
   "Hello {child}, main {brand} bol rahi hoon. {parent} ke baare mein WhatsApp par ek zaroori message hai. Kripya abhi dekh lijiye.",
   "हैलो {child}, मैं {brand} बोल रही हूँ। {parent} के बारे में WhatsApp पर एक ज़रूरी मैसेज है। कृपया अभी देख लीजिए।")
_s("child.ring_sos",
   "Hello {child}, this is {brand}. {parent} pressed the help button. Please call {parent} now.",
   "Hello {child}, main {brand} bol rahi hoon. {parent} ne madad ka button dabaya hai. Kripya abhi unhe phone kijiye.",
   "हैलो {child}, मैं {brand} बोल रही हूँ। {parent} ने मदद का बटन दबाया है। कृपया अभी उन्हें फ़ोन कीजिए।")
_s("child.ring_unreached",
   "Hello {child}, this is {brand}. {parent} did not answer today's check-in. Please see WhatsApp and call {parent}.",
   "Hello {child}, main {brand} bol rahi hoon. {parent} ne aaj ka check-in nahi uthaya. Kripya WhatsApp dekhiye aur {parent} ko phone kijiye.",
   "हैलो {child}, मैं {brand} बोल रही हूँ। {parent} ने आज का चेक-इन नहीं उठाया। कृपया WhatsApp देखिए और {parent} को फ़ोन कीजिए।")
_s("second.ring",
   "Hello, this is {brand}, an AI assistant. {child} named you as someone to contact about {parent}. Please call {child} or {parent} now.",
   "Hello, main {brand} bol rahi hoon, ek AI assistant. {child} ne aapko {parent} ke liye sampark ke roop mein bataya tha. Kripya abhi {child} ya {parent} ko phone kijiye.",
   "हैलो, मैं {brand} बोल रही हूँ, एक AI असिस्टेंट। {child} ने आपको {parent} के लिए संपर्क के रूप में बताया था। कृपया अभी {child} या {parent} को फ़ोन कीजिए।")
_s("bridge.child", "Hello {child}, this is {brand}. I am connecting you with {parent} now.", "Hello {child}, main {brand} hoon. Main aapko abhi {parent} se jod rahi hoon.", "हैलो {child}, मैं {brand} हूँ। मैं आपको अभी {parent} से जोड़ रही हूँ।")
_s("bridge.parent", "{parent}, {child} wants to talk to you. I am connecting you now.", "{parent}, {child} aapse baat karna chahte hain. Main aapko abhi jod rahi hoon.", "{parent}, {child} आपसे बात करना चाहते हैं। मैं आपको अभी जोड़ रही हूँ।")
_s("safeword.prompt",
   "{parent}, ask the person you are talking to for the family safe word. If they cannot say it, hang up and call {child}.",
   "{parent}, jis se aap baat kar rahe hain unse family safe word poochhiye. Wo na bata sake to phone kaat dijiye aur {child} ko phone kijiye.",
   "{parent}, जिससे आप बात कर रहे हैं उनसे फ़ैमिली सेफ़ वर्ड पूछिए। वो न बता सके तो फ़ोन काट दीजिए और {child} को फ़ोन कीजिए।")

# ============================================================================ chat lines to the child (en + hinglish)
_c("setup.start", "Let me set up {brand} for your {rel}. What is their mobile number?", "{rel} ke liye {brand} set up karte hain. Unka mobile number kya hai?")
_c("setup.bad_number", "That does not look like a mobile number. Please send 10 digits or a number with +91.", "Yeh mobile number jaisa nahi lag raha. Kripya 10 digit ya +91 ke saath number bhejiye.")
_c("setup.same_number", "That is your own number. Please send your {rel}'s number.", "Yeh aapka apna number hai. Kripya apne {rel} ka number bhejiye.")
_c("setup.ask_language", "Which language should I speak with {parent}? Hindi, Hinglish or English?", "{parent} se main kis bhasha mein baat karun? Hindi, Hinglish ya English?")
_c("setup.ask_time", "At what time should I make the daily check-in call? For example, 9 am.", "Roz check-in call kis samay karun? Jaise subah 9 baje.")
_c("setup.bad_time", "I could not understand the time. Please send something like 9 am or 18:30.", "Samay samajh nahi aaya. Kripya aisa bhejiye: 9 am ya 18:30.")
_c("setup.time_in_quiet", "That time falls inside quiet hours ({start} to {end}). Please choose another time.", "Yeh samay quiet hours ({start} se {end}) ke andar hai. Kripya koi aur samay chuniye.")
_c("setup.ask_quiet", "I will not call {parent} between {start} and {end} (except real emergencies). Reply 'ok' or send other hours like 10pm-7am.", "Main {parent} ko {start} se {end} ke beech phone nahi karungi (sirf asli emergency chhodkar). 'ok' likhiye ya doosre ghante bhejiye, jaise 10pm-7am.")
_c("setup.bad_quiet", "Please send hours like 10pm-7am, or 'ok'.", "Kripya aise ghante bhejiye: 10pm-7am, ya 'ok'.")
_c("setup.ask_second", "Is there a second person I may contact if I cannot reach you? Send their number, or 'no'. I will only contact someone you name now.", "Agar main aap tak na pahunch paun to koi doosra vyakti hai jisse sampark karun? Unka number bhejiye, ya 'no'. Main sirf unhi ko contact karungi jinka naam aap abhi dein.")
_c("setup.ask_sensitivity", "How careful should I be? Calm (fewer alerts), Balanced, or Careful (more alerts).", "Main kitni satark rahun? Calm (kam alerts), Balanced, ya Careful (zyada alerts).")
_c("setup.bad_sensitivity", "Please reply Calm, Balanced or Careful.", "Kripya Calm, Balanced ya Careful likhiye.")
_c("setup.ask_child_call", "May I ring you (on this number) for urgent things about {parent}? yes or no.", "Kya main {parent} ke baare mein zaroori baaton ke liye aapko (is number par) phone kar sakti hoon? yes ya no.")
_c("setup.done",
   "All set. I will NOT call {parent} until they agree. My first call is a short introduction: I say I am an AI assistant called {brand}, who asked me, what I will and will not do, and how to say no. Please tell {parent} to expect it. I will tell you what they say.",
   "Ho gaya. Main {parent} ko tab tak phone NAHI karungi jab tak wo haan na kahein. Meri pehli call ek chhota parichay hoga: main bataungi ki main {brand} naam ki AI assistant hoon, mujhe kisne kaha, main kya karungi aur kya nahi, aur na kaise kehna hai. Kripya {parent} ko batayein ki call aayegi. Wo jo bolenge main aapko bataungi.")
_c("setup.not_allowed", "In this pilot I can only call numbers that are explicitly allow-listed, and {parent}'s number is not on the list yet. Nothing will ring until it is added.", "Is pilot mein main sirf wahi number dial kar sakti hoon jo allow-list mein ho, aur {parent} ka number abhi list mein nahi hai. Jab tak jodta nahi, kuch nahi bajega.")
_c("setup.intro_started", "I will make the introduction call to {parent} now.", "Main abhi {parent} ko parichay wali call kar rahi hoon.")
_c("setup.intro_pending_line", "The introduction call wording is waiting for approval, so I cannot make it yet. I have saved the setup.", "Parichay call ka wording abhi approval ka intezaar kar raha hai, isliye main abhi call nahi kar sakti. Setup save ho gaya hai.")
_c("setup.no_family", "I have not set up {brand} for anyone yet. Say 'set up {brand} for my father' (or mother) to start.", "Maine abhi kisi ke liye {brand} set up nahi kiya. Shuru karne ke liye likhiye: 'set up {brand} for my father' (ya mother).")
_c("setup.cancelled", "Okay, I stopped the setup. Nothing was saved except what you already sent.", "Theek hai, setup rok diya.")

_c("intro.result.consented", "{parent} heard the introduction. Switched on: {items}. Not switched on: {declined}.", "{parent} ne parichay suna. Chalu: {items}. Chalu nahi: {declined}.")
_c("intro.result.declined", "{parent} asked {brand} to stop. I will not call again.", "{parent} ne {brand} ko rokne ko kaha. Main dobara phone nahi karungi.")
_c("intro.result.no_answer", "{parent} did not pick up the introduction call. I will try once more later; nothing else will be started.", "{parent} ne parichay call nahi uthayi. Main baad mein ek baar aur koshish karungi; aur kuch shuru nahi hoga.")
_c("intro.result.refused", "I could not place the introduction call ({why}).", "Parichay call nahi lag saki ({why}).")

_c("status.line", "{parent}: {state}. Check-in at {time}. Today: {today}. Medicines: {meds}. Open alerts: {alerts}.", "{parent}: {state}. Check-in {time} par. Aaj: {today}. Dawaiyan: {meds}. Khule alerts: {alerts}.")
_c("status.waiting_consent", "waiting for their consent", "unki sahmati ka intezaar")
_c("status.active", "active", "chalu")
_c("status.paused", "paused by {parent}", "{parent} ne roka hai")
_c("checkin.result.ok", "{parent} checked in: {summary}.", "{parent} ne check-in kiya: {summary}.")
_c("checkin.result.concern", "{parent} checked in, with something to note: {summary}.", "{parent} ne check-in kiya, dhyan dene wali baat: {summary}.")
_c("checkin.result.missed", "{parent} did not pick up today's check-in after {n} tries. I am following your plan.", "{parent} ne aaj ka check-in {n} koshish ke baad bhi nahi uthaya. Main aapki yojana ke hisaab se aage badh rahi hoon.")
_c("checkin.result.fine_later", "Update: {parent} is fine. They spoke to me just now.", "Update: {parent} theek hain. Unhone abhi mujhse baat ki.")
_c("callnow.started", "Calling {parent} now for a check-in. I will tell you how it goes.", "Main abhi {parent} ko check-in ke liye phone kar rahi hoon. Kya hua, aapko bataungi.")
_c("callnow.refused", "I cannot call {parent} now ({why}).", "Main abhi {parent} ko phone nahi kar sakti ({why}).")
_c("digest.daily", "Today with {parent}: {summary}", "Aaj {parent} ke saath: {summary}")
_c("digest.weekly", "This week with {parent}: {summary}", "Is hafte {parent} ke saath: {summary}")
_c("digest.empty", "nothing to report", "batane layak kuch nahi")

_c("med.added", "Saved {medicine} at {times}. Stock about {days} days. I do not give medical advice; ask the doctor about any change.", "{medicine} {times} par save ho gayi. Stock lagbhag {days} din. Main medical salaah nahi deti; kisi bhi badlav ke liye doctor se poochhiye.")
_c("med.confirm", "I read this from the prescription: {list}. Save these reminders? yes or no. Please check the names and times; I cannot judge doses.", "Prescription se maine yeh padha: {list}. Kya yeh reminders save karun? yes ya no. Naam aur samay dekh lijiye; main dose ka faisla nahi kar sakti.")
_c("med.confirm_saved", "Saved {n} medicine(s).", "{n} dawai save ho gayi.")
_c("med.confirm_dropped", "Okay, I did not save anything.", "Theek hai, kuch save nahi kiya.")
_c("med.rx_unreadable", "I could not read the medicines or their times on that photo, so I saved nothing. You can add one yourself: add medicine <name> <dose> at 8am, 8pm.", "Us photo mein dawai ya unke samay padh nahi paayi, isliye kuch save nahi kiya. Aap khud jod sakte hain: add medicine <naam> <dose> at 8am, 8pm.")
_c("med.rx_partial", "I could not read the times for: {list}. Those are not in the list above; add them yourself if you want reminders.", "In ke samay padh nahi paayi: {list}. Yeh upar ki list mein nahi hain; reminders chahiye to khud jodiye.")
_c("med.rx_nothing_open", "There is no prescription waiting for your answer.", "Abhi koi prescription aapke jawab ka intezaar nahi kar rahi.")
_c("med.ordered_ack", "Noted that {medicine} is ordered. I do not order or pay for anything. When it arrives, send the count: pills left <name> <number>.", "Note kar liya ki {medicine} order ho gayi. Main kuch order ya payment nahi karti. Aane par ginti bhejiye: pills left <naam> <sankhya>.")
_c("med.format", "To add a medicine write: add medicine <name> <dose> at 8am, 8pm, <strips> strips of <pills> bought <date>. Example: add medicine Amlodipine 5mg at 8am strips 2 of 10 bought 2026-11-01.", "Dawai jodne ke liye likhiye: add medicine <naam> <dose> at 8am, 8pm strips 2 of 10 bought 2026-11-01.")
_c("med.list_item", "{medicine} {dose} at {times}: about {days} days left", "{medicine} {dose} {times} par: lagbhag {days} din bachi")
_c("med.list_empty", "No medicines saved for {parent}.", "{parent} ke liye koi dawai save nahi hai.")
_c("med.removed", "Removed {medicine}.", "{medicine} hata di.")
_c("med.not_found", "I could not find that medicine.", "Yeh dawai nahi mili.")
_c("med.missed", "{parent} did not take {medicine} ({time}).", "{parent} ne {medicine} ({time}) nahi li.")
_c("med.refill", "{medicine} has about {days} days of stock left. Time to buy more. Ask the doctor if the prescription needs a change.", "{medicine} ka stock lagbhag {days} din ka bacha hai. Aur kharidne ka samay. Prescription badalni ho to doctor se poochhiye.")
_c("med.paused", "Medicine reminders are paused until {until}.", "Dawai ke reminders {until} tak ruke hain.")
_c("med.resumed", "Medicine reminders are back on.", "Dawai ke reminders phir chalu.")
_c("med.consent_missing", "{parent} has not agreed to medicine reminders yet, so I saved the schedule but will not call about it.", "{parent} ne abhi dawai ke reminders ke liye haan nahi kaha, isliye schedule save kiya hai par uske liye phone nahi karungi.")

_c("alert.head.watch", "Heads up about {parent}: {why}", "{parent} ke baare mein dhyan dein: {why}")
_c("alert.head.high", "Important: {parent}. {why}", "Zaroori: {parent}. {why}")
_c("alert.head.emergency", "EMERGENCY: {parent}. {why}", "EMERGENCY: {parent}. {why}")
_c("alert.money_note", "Money may be involved, so please check with {parent} yourself even if they say they are fine.", "Paise ka maamla ho sakta hai, isliye {parent} ke theek kehne par bhi aap khud unse baat kijiye.")
_c("alert.hint", "Reply 'details' to see more, or 'I have it' to take over.", "Zyada dekhne ke liye 'details' likhiye, ya sambhalne ke liye 'I have it'.")
_c("alert.details", "Alert details: {why}. Scenario {scenario}. Level {tier}. Raised {at}. Steps so far: {steps}.", "Alert ka vivaran: {why}. Scenario {scenario}. Level {tier}. Samay {at}. Ab tak ke kadam: {steps}.")
_c("alert.safe", "Marked safe. I have stopped everything for this alert.", "Safe mark kar diya. Is alert ke liye sab kuch rok diya.")
_c("alert.taken", "Okay, you have it. I have stopped calling.", "Theek hai, aap sambhal rahe hain. Maine phone karna rok diya.")
_c("alert.parent_fine", "{parent} says they are fine. I have stopped calling.", "{parent} kehte hain ki wo theek hain. Maine phone karna rok diya.")
_c("alert.call_parent", "Call {parent} on {phone}. I will keep going on my plan until you tap Mark safe or write 'I have it'.", "{parent} ko {phone} par phone kijiye. Jab tak aap Mark safe na dabayein ya 'I have it' na likhein, main apni yojana par chalti rahungi.")
_c("alert.join_started", "I am calling you now and will connect you with {parent}.", "Main abhi aapko phone kar rahi hoon aur {parent} se jod dungi.")
_c("alert.join_refused", "I could not set up the joined call ({why}).", "Joined call nahi ban saki ({why}).")
_c("alert.unknown", "I could not find that alert; it may have ended already.", "Yeh alert nahi mila; shayad khatam ho chuka hai.")
_c("alert.followup", "Still open: {why}. I have called {n} time(s).", "Abhi bhi khula hai: {why}. Maine {n} baar phone kiya hai.")
_c("alert.flood_summary", "Many alerts today about {parent} ({n} so far). To keep your phone usable I will not message each new minor one; they stay in 'what {brand} did today'. An EMERGENCY or an SOS is always sent at once.", "{parent} ke baare mein aaj bahut alerts aaye ({n} ab tak). Aapka phone na bhare, isliye chhote alerts par ab alag message nahi bhejungi; ve 'what {brand} did today' mein rahenge. EMERGENCY ya SOS hamesha turant bhejungi.")  # PENDING founder approval of wording (T06)
_c("alert.second", "{child} named you as a contact for {parent}. Alert: {why}. Please call {child} or {parent}.", "{child} ne aapko {parent} ke sampark ke roop mein bataya hai. Alert: {why}. Kripya {child} ya {parent} ko phone kijiye.")

_c("sos.child", "SOS: {parent} pressed the help button{loc}. I am ringing you now. {brand} cannot call 112 for you; please call {parent}, and call 112 if needed.", "SOS: {parent} ne madad ka button dabaya{loc}. Main abhi aapko phone kar rahi hoon. Main 112 nahi laga sakti; kripya {parent} ko phone kijiye, aur zaroorat ho to 112.")
_c("sos.loc", " (location: {lat}, {lon})", " (jagah: {lat}, {lon})")
_c("sos.second", "SOS for {parent} (named by {child}): {parent} pressed the help button{loc}. Please call {child} or {parent} now.", "{parent} ke liye SOS ({child} ne aapka naam diya hai): {parent} ne madad ka button dabaya{loc}. Kripya abhi {child} ya {parent} ko phone kijiye.")

_c("safeword.set", "Family safe word saved (only a scrambled version is kept; I cannot read it back). Share it with {parent} in person.", "Family safe word save ho gaya (sirf scrambled roop mein; main use wapas padh nahi sakti). Use {parent} ko aamne-saamne batayein.")
_c("safeword.format", "To set it write: safe word <word>. Do it together with {parent}, in person. Do not send it on a call.", "Set karne ke liye likhiye: safe word <shabd>. {parent} ke saath mil kar karein. Call par mat bhejiye.")
_c("safeword.none", "No safe word set yet.", "Abhi koi safe word set nahi hai.")
_c("safeword.check_ok", "That matches the safe word.", "Yeh safe word se match karta hai.")
_c("safeword.check_no", "That does not match.", "Yeh match nahi karta.")

_c("view.child.head", "What {brand} sees and does for {parent} (the same page {parent} can see):", "{brand} {parent} ke liye kya dekhti aur karti hai (wahi page jo {parent} bhi dekh sakte hain):")
_c("view.item.on", "- {item}: agreed on {when} ({source})", "- {item}: {when} ko haan ({source})")
_c("view.item.off", "- {item}: not agreed", "- {item}: haan nahi")
_c("view.item.withdrawn", "- {item}: withdrawn on {when}", "- {item}: {when} ko wapas liya")
_c("view.never", "{brand} never records calls, never reads messages, notifications or SMS from this part, never asks for OTP, PIN or passwords, and never pays.", "{brand} call record nahi karti, messages, notifications ya SMS nahi padhti, OTP, PIN ya password nahi maangti, aur paise nahi bhejti.")
_c("view.shared", "Shared with {child}: {shared}", "{child} ko dikhta hai: {shared}")
_c("view.audit_head", "What {brand} did today:", "{brand} ne aaj kya kiya:")
_c("view.audit_empty", "Nothing yet.", "Abhi tak kuch nahi.")

_c("pause.parent", "{parent} asked {brand} to stop, so I stopped everything. Please talk to {parent}. Only {parent} can start the sensitive items again; you can ask them.", "{parent} ne {brand} ko rokne ko kaha, isliye maine sab kuch rok diya. Kripya {parent} se baat kijiye. Sensitive cheezein sirf {parent} dobara chalu kar sakte hain; aap unse keh sakte hain.")
_c("resume.parent", "{parent} resumed {brand}.", "{parent} ne {brand} dobara shuru kiya.")
_c("consent.withdrawn", "{parent} withdrew consent for {item}. I stopped that.", "{parent} ne {item} ki sahmati wapas li. Maine wo band kar diya.")
_c("consent.given", "{parent} agreed to {item}.", "{parent} ne {item} ke liye haan kaha.")

_c("cmd.checkin_set", "Check-in time for {parent} is now {time}.", "{parent} ka check-in samay ab {time} hai.")
_c("cmd.sensitivity_set", "Sensitivity is now {level}. This changes how soon I alert you, not what is looked at.", "Sensitivity ab {level} hai. Isse alert kitni jaldi aaye wo badalta hai, kya dekha jaata hai wo nahi.")
_c("cmd.delete_ask", "This deletes everything {brand} holds about {parent} and the family setup: consents, medicines, check-ins and the log. Reply DELETE to confirm.", "Isse {parent} aur family setup ke baare mein {brand} ke paas jo kuch hai sab hat jayega: sahmatiyan, dawaiyan, check-in aur log. Confirm karne ke liye DELETE likhiye.")
_c("cmd.delete_done", "Deleted everything about {parent}.", "{parent} ke baare mein sab kuch hata diya.")
_c("cmd.delete_cancelled", "Okay, nothing was deleted.", "Theek hai, kuch nahi hata.")
_c("cmd.help", "{brand} commands: set up {brand} for my father | parent status | call papa | add medicine ... | medicines | remove medicine <name> | check-in time 9am | sensitivity calm|balanced|careful | what does {brand} see | pause reminders 3 days | resume reminders | digest | pair phone for papa | what is on | what {brand} did today | delete everything for my parent", "{brand} ke commands: set up {brand} for my father | parent status | call papa | add medicine ... | medicines | remove medicine <naam> | check-in time 9am | sensitivity calm|balanced|careful | what does {brand} see | pause reminders 3 days | resume reminders | digest | safe word <shabd> | pair phone for papa | what is on | what {brand} did today | delete everything for my parent")
_c("cmd.care_active", "I am keeping calls and nudges quiet right now.", "Main abhi calls aur nudges shaant rakh rahi hoon.")
_c("pair.steps",
   "To connect {parent}'s phone: 1) install the {brand} app on {parent}'s phone. 2) Open it, press and hold the {brand} name, and enter this code: {code}. Or open this link on {parent}'s phone and tap Connect: {link}. The code works once and expires in {minutes} minutes. {parent} does not have to type anything. Do not share the code with anyone else.",
   "{parent} ka phone jodne ke liye: 1) {parent} ke phone par {brand} app lagayiye. 2) Use kholkar {brand} naam ko dabaye rakhiye aur yeh code daliye: {code}. Ya {parent} ke phone par yeh link kholkar Connect dabaiye: {link}. Code sirf ek baar chalta hai aur {minutes} minute mein khatam ho jata hai. {parent} ko kuch type nahi karna padega. Code kisi aur ko mat dijiye.")  # PENDING founder approval of wording (T08)
_c("pair.off", "Phone pairing is not switched on yet, so I cannot make a code.", "Phone jodna abhi chalu nahi hai, isliye main code nahi bana sakti.")
_c("pair.not_ready", "First finish setting up {brand} for {parent} (their number is needed), then ask me again.", "Pehle {parent} ke liye {brand} ka setup poora kijiye (unka number chahiye), phir dobara poochhiye.")
_c("inbox.head", "{brand} could not reach your phone earlier and held these messages for you:", "{brand} pehle aapke phone tak nahi pahunch saki aur ye messages aapke liye rakh liye the:")
_c("cmd.escalation_unnamed", "No second contact was named, so I will not contact anyone else.", "Koi doosra sampark nahi diya gaya, isliye main kisi aur ko contact nahi karungi.")

_s("monthly.reminder",
   "{parent}, this is {brand}, your AI assistant, with a monthly reminder. These are switched on: {items}. You can pause me or switch any of them off at any time.",
   "{parent}, main {brand} hoon, aapki AI assistant, mahine ki yaad dilane. Yeh chalu hain: {items}. Aap kabhi bhi mujhe rok sakte hain ya inmein se kuch band kar sakte hain.",
   "{parent}, मैं {brand} हूँ, आपकी AI असिस्टेंट, महीने की याद दिलाने। ये चालू हैं: {items}। आप कभी भी मुझे रोक सकते हैं या इनमें से कुछ बंद कर सकते हैं।")
_c("consent.request_sent", "I noted your request for {item}. {parent} asked {brand} to stop, so only {parent} can start it again.", "Maine {item} ke liye aapki request note kar li. {parent} ne {brand} ko rokne ko kaha hai, isliye ise sirf {parent} dobara chalu kar sakte hain.")
_c("consent.parent_paused", "{parent} asked {brand} to stop, so I cannot switch {item} on. I noted your request; please talk to {parent}.", "{parent} ne {brand} ko rokne ko kaha hai, isliye main {item} chalu nahi kar sakti. Aapki request note kar li; kripya {parent} se baat kijiye.")
_c("guardian.set", "Guardian basis recorded for {parent}: {basis}. {brand} does not verify it; it is flagged for legal review.", "{parent} ke liye guardian karan darj: {basis}. {brand} ise verify nahi karti; legal review ke liye flag hai.")
_c("guardian.bad_basis", "Please write the basis, for example: guardian mode <short reason such as court order or medical incapacity>.", "Kripya karan likhiye, jaise: guardian mode <chhota karan, jaise court order ya medical incapacity>.")
_c("guardian.off", "Guardian mode is off for {parent}.", "{parent} ke liye guardian mode band.")
_c("consent.admin_given", "Recorded: you agreed to {item} on behalf of {parent}. {parent} is told and can stop me at any time.", "Note kiya: aapne {parent} ki taraf se {item} ke liye haan kaha. {parent} ko bataya jayega aur wo kabhi bhi mujhe rok sakte hain.")
_c("coadmin.added", "Added a co-admin. They get the same alerts and can use the same commands.", "Co-admin jod diya. Unhe wahi alerts milenge.")

_s("notify.stop",
   "To stop me, just say '{brand}, stop' in a voice message or write it, or tap the stop button on the widget. I do not read your chats and I do not record your phone.",
   "Mujhe rokne ke liye bas voice message mein '{brand}, band karo' bol dijiye ya likh dijiye, ya widget par stop dabaiye. Main aapki chats nahi padhti aur aapka phone record nahi karti.",
   "मुझे रोकने के लिए बस वॉइस मैसेज में '{brand}, बंद करो' बोल दीजिए या लिख दीजिए, या विजेट पर स्टॉप दबाइए। मैं आपकी चैट नहीं पढ़ती और आपका फ़ोन रिकॉर्ड नहीं करती।")
_s("notify.set_up_by",
   "Hello {parent}. I am {brand}, an AI assistant. {child} set me up to look after you.",
   "Namaste {parent}. Main {brand} hoon, ek AI assistant. {child} ne mujhe aapka khayal rakhne ke liye set up kiya hai.",
   "नमस्ते {parent}। मैं {brand} हूँ, एक AI असिस्टेंट। {child} ने मुझे आपका ख़याल रखने के लिए सेट अप किया है।")
_s("gm.greet", "Good morning {parent}! Today is {date}.", "Suprabhat {parent}! Aaj {date} hai.", "सुप्रभात {parent}! आज {date} है।")
_s("gm.meds", "Your medicine times today: {meds}.", "Aaj ki dawai ka samay: {meds}.", "आज की दवाई का समय: {meds}।")
_s("fest.greeting", "Happy {festival}, {parent}! Wishing you and your family joy and good health.", "{festival} ki bahut shubhkamnayein, {parent}! Aapko aur parivar ko khushi aur achhi sehat mile.", "{festival} की बहुत शुभकामनाएँ, {parent}! आपको और परिवार को ख़ुशी और अच्छी सेहत मिले।")
_s("gm.share", "You can share this greeting with your family group.", "Aap yeh shubhkamna apne family group mein bhej sakte hain.", "आप यह शुभकामना अपने फ़ैमिली ग्रुप में भेज सकते हैं।")
_c("gm.on", "Good-morning messages for {parent} are on.", "{parent} ke liye good-morning message chalu.")
_c("gm.off", "Good-morning messages for {parent} are off.", "{parent} ke liye good-morning message band.")
_c("fest.on", "Festival greetings for {parent} are on.", "{parent} ke liye tyohaar ki shubhkamnayein chalu.")
_c("fest.off", "Festival greetings for {parent} are off.", "{parent} ke liye tyohaar ki shubhkamnayein band.")
_c("enable.done", "Switched on: {item}. {parent} will be told.", "Chalu kiya: {item}. {parent} ko bataya jayega.")
_c("enable.unknown", "I do not know that item. Items: {items}.", "Yeh item mujhe nahi pata. Items: {items}.")

# --- missed calls, either direction (Robin answers the forwarded call and takes who/why/urgent)
_s("missed.ask_who",
   "Hello, this is {brand}, an AI assistant answering for {parent}. {parent} cannot take the call right now. Who is calling, and what is it about?",
   "Namaste, main {brand} bol rahi hoon, {parent} ki AI assistant. {parent} abhi call nahi le sakte. Aap kaun bol rahe hain aur kis baare mein?",
   "नमस्ते, मैं {brand} बोल रही हूँ, {parent} की AI असिस्टेंट। {parent} अभी कॉल नहीं ले सकते। आप कौन बोल रहे हैं और किस बारे में?")
_s("missed.ask_urgent", "Is it urgent or an emergency? Please say yes or no.", "Kya yeh zaroori ya emergency hai? Kripya haan ya na boliye.", "क्या यह ज़रूरी या इमरजेंसी है? कृपया हाँ या ना बोलिए।")
_s("missed.urgent_ack", "Thank you. I am telling {parent} it is urgent and I will keep trying to reach them.", "Dhanyavaad. Main {parent} ko bata rahi hoon ki yeh zaroori hai aur main unse sampark karti rahungi.", "धन्यवाद। मैं {parent} को बता रही हूँ कि यह ज़रूरी है और मैं उनसे संपर्क करती रहूँगी।")
_s("missed.normal_ack", "Thank you. I will pass your message to {parent}.", "Dhanyavaad. Main aapka sandesh {parent} tak pahuncha dungi.", "धन्यवाद। मैं आपका संदेश {parent} तक पहुँचा दूँगी।")
_s("missed.msg",
   "{who} called you at {time}. They said: {summary}.",
   "{who} ne aapko {time} baje phone kiya tha. Unhone kaha: {summary}.",
   "{who} ने आपको {time} बजे फ़ोन किया था। उन्होंने कहा: {summary}।")
_s("missed.msg_urgent",
   "{who} called you at {time} and says it is URGENT. They said: {summary}. Please call back now.",
   "{who} ne aapko {time} baje phone kiya aur kehte hain ki yeh ZAROORI hai. Unhone kaha: {summary}. Kripya abhi wapas phone kijiye.",
   "{who} ने आपको {time} बजे फ़ोन किया और कहते हैं कि यह ज़रूरी है। उन्होंने कहा: {summary}। कृपया अभी वापस फ़ोन कीजिए।")
_s("missed.emergency_ring",
   "Hello {parent}, this is {brand}. {who} called and says it is an emergency. Please call {who} now.",
   "Hello {parent}, main {brand} bol rahi hoon. {who} ne phone kiya aur kehte hain ki emergency hai. Kripya abhi {who} ko phone kijiye.",
   "हैलो {parent}, मैं {brand} बोल रही हूँ। {who} ने फ़ोन किया और कहते हैं कि इमरजेंसी है। कृपया अभी {who} को फ़ोन कीजिए।")
_s("missed.caller_told",
   "{missed} has been told that you called and what you said.",
   "{missed} ko bata diya gaya hai ki aapne phone kiya tha aur aapne kya kaha.",
   "{missed} को बता दिया गया है कि आपने फ़ोन किया था और आपने क्या कहा।")
_s("missed.caller_told_urgent",
   "{missed} has been told that you called and that it is urgent. {brand} keeps trying to reach them.",
   "{missed} ko bata diya gaya hai ki aapne phone kiya aur yeh zaroori hai. {brand} unse sampark karti rahegi.",
   "{missed} को बता दिया गया है कि आपने फ़ोन किया और यह ज़रूरी है। {brand} उनसे संपर्क करती रहेगी।")
_c("missed.child_note", "{who} called you but you missed it ({time}). They said: {summary}.", "{who} ne aapko phone kiya par aap utha nahi paye ({time}). Unhone kaha: {summary}.")
_c("missed.child_note_urgent", "URGENT: {who} called you ({time}) and says it is an emergency. They said: {summary}. I am ringing you every {minutes} minutes (up to {tries} tries) until you answer.", "ZAROORI: {who} ne aapko phone kiya ({time}) aur kehte hain emergency hai. Unhone kaha: {summary}. Main aapko har {minutes} minute mein phone kar rahi hoon (zyada se zyada {tries} baar) jab tak aap na uthayein.")
_c("missed.unknown_caller", "an unknown caller", "ek anjaan caller")
_c("missed.no_summary", "nothing clear", "kuch saaf nahi")

# --- missed-call forwarding setup in the child's chat (T10). Codes come from friday/receptionist/carriers.py; [U] = unverified on a real SIM
_c("forward.ask", "Optional: let {brand} answer when {who} cannot pick up. It needs call forwarding on the phone. Reply 'forwarding jio', 'forwarding airtel' or 'forwarding vi' for the steps.", "Optional: jab {who} phone na utha payein to {brand} jawab de. Iske liye phone par call forwarding chahiye. Steps ke liye likhiye 'forwarding jio', 'forwarding airtel' ya 'forwarding vi'.")
_c("forward.codes", "Forwarding for {who} on {carrier} (dial these on {who}'s phone, one at a time; the codes are standard but NOT verified on a real SIM [U]):\n{codes}\nTo check: {status}. To undo everything: {cancel}.\n{notes}\nThen use 'test forwarding' to try it.", "{carrier} par {who} ke phone ke liye forwarding (ye codes {who} ke phone se ek ek karke dial karein; codes standard hain par asli SIM par VERIFIED NAHI [U]):\n{codes}\nCheck karne ke liye: {status}. Sab band karne ke liye: {cancel}.\n{notes}\nPhir 'test forwarding' likhiye.")
_c("forward.unknown_carrier", "I know Jio, Airtel and Vi. Which one is it?", "Main Jio, Airtel aur Vi jaanti hoon. Kaun sa hai?")
_c("forward.unavailable", "The number that answers forwarded calls is not set up yet, so I cannot give you codes. I have told the team.", "Forwarded calls ka number abhi set nahi hai, isliye codes nahi de sakti. Team ko bata diya hai.")
_c("forward.test", "To test forwarding (this is a supervised step, only with the founder's number during the pilot): 1) from another phone, ring {who}'s phone; 2) do not pick up; 3) after about {seconds} seconds {brand} should answer and ask who is calling; 4) say a name and 'no' to urgent; 5) {who} or you should get a message within a minute. Nothing is dialled by {brand} for this test.", "Forwarding test (supervised step, pilot mein sirf founder ke number par): 1) kisi doosre phone se {who} ke phone par call karein; 2) uthaiye mat; 3) lagbhag {seconds} second baad {brand} uthaye aur poochhe kaun bol raha hai; 4) naam boliye aur urgent par 'nahi'; 5) {who} ya aapko ek minute mein message milna chahiye. Is test mein {brand} khud koi call nahi karti.")

# --- authority module (policy-gated; DRY-RUN logs these scripts, nothing is dialled)
_s("authority.countdown",
   "{parent}, I am about to ask for emergency help for you in one minute. If you are fine, say 'I am fine' now.",
   "{parent}, main ek minute mein aapke liye emergency madad maangne wali hoon. Agar aap theek hain to abhi 'main theek hoon' boliye.",
   "{parent}, मैं एक मिनट में आपके लिए इमरजेंसी मदद माँगने वाली हूँ। अगर आप ठीक हैं तो अभी 'मैं ठीक हूँ' बोलिए।")
_s("authority.what.medical", "a possible medical emergency", "ek sambhavit medical emergency", "एक संभावित मेडिकल इमरजेंसी")
_s("authority.what.threat", "a possible threat to their safety", "unki suraksha ko sambhavit khatra", "उनकी सुरक्षा को संभावित ख़तरा")
_s("authority.what.unknown", "a possible emergency", "ek sambhavit emergency", "एक संभावित इमरजेंसी")
_s("authority.script_112",
   "This is an automated call from {brand}, an AI assistant, for {name}. There may be {what}. The address is {address}. Please send help. The callback number is {callback}. I will repeat once.",
   "Yeh {brand} ki taraf se ek automatic call hai, ek AI assistant, {name} ke liye. Wahan {what} ho sakti hai. Pata hai {address}. Kripya madad bhejiye. Callback number hai {callback}. Main ek baar dohraungi.",
   "यह {brand} की तरफ़ से एक ऑटोमैटिक कॉल है, एक AI असिस्टेंट, {name} के लिए। वहाँ {what} हो सकती है। पता है {address}। कृपया मदद भेजिए। कॉलबैक नंबर है {callback}। मैं एक बार दोहराऊँगी।")
_s("authority.bridge_1930",
   "{child}, I am connecting you to the cyber-fraud helpline 1930 for {parent}. You will speak to them yourself; I will stay quiet.",
   "{child}, main {parent} ke liye aapko cyber-fraud helpline 1930 se jod rahi hoon. Aap khud unse baat karenge; main chup rahungi.",
   "{child}, मैं {parent} के लिए आपको साइबर-फ़्रॉड हेल्पलाइन 1930 से जोड़ रही हूँ। आप ख़ुद उनसे बात करेंगे; मैं चुप रहूँगी।")
_c("authority.complaint", "Draft for cybercrime.gov.in (check every fact before you submit it yourself): On {when}, {parent} may have been defrauded. What happened: {why}. Amount: {amount}. Please also call 1930 now and ask your bank to freeze the transaction. {brand} did not file anything and cannot.", "cybercrime.gov.in ke liye draft (khud submit karne se pehle har baat check kijiye): {when} ko {parent} ke saath dhokha hua ho sakta hai. Kya hua: {why}. Rakam: {amount}. Kripya abhi 1930 par phone kijiye aur bank se transaction freeze karne ko kahiye. {brand} ne kuch file nahi kiya aur nahi kar sakti.")
_c("authority.dry_run", "DRY RUN (nothing was dialled): for {parent} the emergency desk would have called {who}.", "DRY RUN (kuch dial nahi hua): {parent} ke liye emergency desk {who} ko phone karti.")
_c("authority.refused", "The emergency desk did not contact the authorities for {parent}: {why}.", "Emergency desk ne {parent} ke liye authorities ko phone nahi kiya: {why}.")
_c("authority.distress", "{parent} may be in distress. I am not calling anyone official; please call {parent} yourself. This has been handed to the care protocol.", "{parent} pareshan ho sakte hain. Main kisi sarkari number par phone nahi kar rahi; kripya {parent} ko khud phone kijiye. Yeh care protocol ko de diya gaya hai.")
_c("authority.countdown_child", "In {seconds} seconds the emergency desk will contact the authorities for {parent} unless {parent} says they are fine or you tap Mark safe.", "{seconds} second mein emergency desk {parent} ke liye authorities ko phone karegi jab tak {parent} na kahein ki wo theek hain ya aap Mark safe na dabayein.")
_c("authority.set_address", "Address saved for the emergency script.", "Emergency script ke liye pata save ho gaya.")
_c("authority.set_name", "Parent name saved for the emergency script.", "Emergency script ke liye parent ka naam save ho gaya.")

# --- screening unknown callers and listening in (both OFF by default; stubs only, docs/ROBIN_FAMILY_CORE.md section 9)
_s("screen.ask",
   "Hello, this is {brand}, an AI assistant answering for {parent}. May I know who is calling and what it is about?",
   "Namaste, main {brand} bol rahi hoon, {parent} ki AI assistant. Kya main jaan sakti hoon ki aap kaun bol rahe hain aur kis baare mein?",
   "नमस्ते, मैं {brand} बोल रही हूँ, {parent} की AI असिस्टेंट। क्या मैं जान सकती हूँ कि आप कौन बोल रहे हैं और किस बारे में?")
_s("screen.connect", "Thank you. I am connecting you to {parent} now.", "Dhanyavaad. Main aapko abhi {parent} se jod rahi hoon.", "धन्यवाद। मैं आपको अभी {parent} से जोड़ रही हूँ।")
_s("screen.decline", "{parent} cannot take this call. I will pass on that you called. Goodbye.", "{parent} yeh call nahi le sakte. Main bata dungi ki aapne phone kiya tha. Namaste.", "{parent} यह कॉल नहीं ले सकते। मैं बता दूँगी कि आपने फ़ोन किया था। नमस्ते।")
_s("listen.disclose",
   "Hello, this is {brand}, an AI assistant. {parent} asked me to listen in on this call to help keep them safe. I do not record it.",
   "Namaste, main {brand} hoon, ek AI assistant. {parent} ne mujhe is call par saath rehne ko kaha hai taaki wo surakshit rahein. Main call record nahi karti.",
   "नमस्ते, मैं {brand} हूँ, एक AI असिस्टेंट। {parent} ने मुझे इस कॉल पर साथ रहने को कहा है ताकि वो सुरक्षित रहें। मैं कॉल रिकॉर्ड नहीं करती।")
_s("listen.warn",
   "{parent}, this call looks risky. Please do not send money or share any OTP or PIN. You can hang up and call {child}.",
   "{parent}, yeh call risky lag rahi hai. Kripya paise mat bhejiye aur OTP ya PIN mat batayein. Aap phone kaat kar {child} ko phone kar sakte hain.",
   "{parent}, यह कॉल रिस्की लग रही है। कृपया पैसे मत भेजिए और OTP या PIN मत बताइए। आप फ़ोन काटकर {child} को फ़ोन कर सकते हैं।")
_c("screen.child_note", "Screened an unknown caller for {parent}: {verdict}. Reason: {why}", "{parent} ke liye anjaan caller ko screen kiya: {verdict}. Wajah: {why}")

# --- fragments that build the one-line check-in result and the digests (chat, to the child)
_c("sum.yes", "yes", "haan")
_c("sum.no", "no", "nahi")
_c("sum.unclear", "no clear answer", "saaf jawab nahi")
_c("sum.ate", "ate: {v}", "khaya: {v}")
_c("sum.slept", "slept well: {v}", "neend achhi: {v}")
_c("sum.pain", "pain: {v}", "dard: {v}")
_c("sum.mood", "mood: {v}", "mann: {v}")
_c("sum.strange", "strange call or money request: {v}", "ajeeb call ya paise ki maang: {v}")
_c("sum.meds", "medicines taken: {v}", "dawai li: {v}")
_c("sum.answered_only", "picked up the call", "call uthayi")
_c("dg.checkins", "{n} of {total} check-ins answered", "{total} mein se {n} check-in uthe")
_c("dg.concerns", "{n} check-in(s) with something to note", "{n} check-in mein dhyan dene wali baat")
_c("dg.meds", "medicine reminders: {taken} taken, {missed} missed", "dawai reminders: {taken} li, {missed} chhooti")
_c("dg.alerts", "{n} alert(s)", "{n} alert")


# ============================================================================ API
_SLOT = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class PendingLine:
    id: str
    kind: str  # spoken | chat
    language: str
    text: str
    status: str = LINE_STATUS


def _table(key: str) -> dict[str, str]:
    if key in SPOKEN:
        return SPOKEN[key]
    return CHAT[key]


def required_slots(key: str) -> frozenset[str]:
    slots: set[str] = set()
    for text in _table(key).values():
        slots |= set(_SLOT.findall(text))
    slots.discard("brand")
    return frozenset(slots)


def say(key: str, lang: str = "hinglish", *, brand: str = "Friday", **slots: object) -> str:
    """The fixed line ``key`` in ``lang`` with its slots filled; ``brand`` comes from the one brand setting."""
    t = _table(key)
    text = t.get(lang) or t.get("hinglish") or t["en"]
    values = {"brand": brand, **{k: str(v) for k, v in slots.items()}}
    return _SLOT.sub(lambda m: values[m.group(1)], text)


def all_lines() -> list[PendingLine]:
    out = [PendingLine(f"robin.{k}.{lang}", "spoken", lang, t) for k, v in SPOKEN.items() for lang, t in v.items()]
    out += [PendingLine(f"robin.{k}.{lang}", "chat", lang, t) for k, v in CHAT.items() for lang, t in v.items()]
    return out


def approved() -> bool:
    return LINE_STATUS == APPROVED
