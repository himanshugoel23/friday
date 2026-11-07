# Robin: every spoken and chat line (ALL PENDING_FOUNDER_APPROVAL)

Generated from `friday/robin/lines.py` by `uv run python -m friday.robin.linesdoc` (a test keeps this file in sync). **No audio has been
generated.** The real dial adapter (`friday/robin/telephony.py`) REFUSES to ring while `LINE_STATUS` is not `APPROVED`; a reviewed commit
flips it after the founder has heard the audio (hear-before-change, CLAUDE.md rule 3). `{brand}` is filled from the one brand setting
(`FRIDAY_BRAND_NAME`; the Robin pilot sets `Robin`); the name is never typed into a line. Other slots: `{parent}` (how the family calls the parent,
e.g. Papa), `{child}` (the admin's name), `{medicine}`, `{amount}`, `{why}`, `{time}`.

Parent-facing spoken lines exist in English (`en`), Roman Hinglish (`hinglish`) and Devanagari Hindi (`hi`). Chat lines to the child (admin)
exist in `en` and `hinglish`. Female forms are used in Hindi (the voice is female); the founder to confirm the persona.

Items for the founder to look at first: `intro.*` and `notify.*` (the AI disclosure and the notification of the parent), `nudge.*` (wording on a
possible scam call; never says a call IS a scam), `sos.*`, `screen.*` and `listen.*` (stubs, switches off), `fest.greeting` and the festival names.

Total lines: **552** (252 spoken, 300 chat). Status of each: PENDING_FOUNDER_APPROVAL.


## Spoken to the parent, the child or the second contact (on a call, or as a voice note)

| Id | Language | Text | Status |
|---|---|---|---|
| robin.intro.greet.en | en | Hello {parent}. I am {brand}. I am an AI assistant, not a person. {child} asked me to keep in touch with you and look after you. | PENDING |
| robin.intro.greet.hinglish | hinglish | Namaste {parent}. Main {brand} bol rahi hoon. Main ek AI assistant hoon, koi insaan nahi. {child} ne mujhe aapse baat karne aur aapka khayal rakhne ke liye kaha hai. | PENDING |
| robin.intro.greet.hi | hi | नमस्ते {parent}। मैं {brand} बोल रही हूँ। मैं एक AI असिस्टेंट हूँ, कोई इंसान नहीं। {child} ने मुझसे कहा है कि मैं आपसे बात करूँ और आपका ख़याल रखूँ। | PENDING |
| robin.intro.will.en | en | Each day I can call to ask how you are, remind you about your medicines, and tell {child} if something looks risky, like a suspicious call. | PENDING |
| robin.intro.will.hinglish | hinglish | Main roz ek chhota phone karke poochh sakti hoon ki aap kaise hain, dawai yaad dila sakti hoon, aur agar koi sandehi call ya paise ka maamla dikhe to {child} ko bata sakti hoon. | PENDING |
| robin.intro.will.hi | hi | मैं रोज़ एक छोटा फ़ोन करके पूछ सकती हूँ कि आप कैसे हैं, दवाई याद दिला सकती हूँ, और अगर कोई संदिग्ध कॉल या पैसे का मामला दिखे तो {child} को बता सकती हूँ। | PENDING |
| robin.intro.wont.en | en | I do not record your calls. I do not read your messages. I will never ask you for an OTP, a PIN or a password. I do not send money, and I do not give medical advice; for that, ask your doctor. | PENDING |
| robin.intro.wont.hinglish | hinglish | Main aapki call record nahi karti. Main aapke messages nahi padhti. Main aapse OTP, PIN ya password kabhi nahi maangungi. Main paise nahi bhejti, aur dawai ke baare mein salaah nahi deti; wo doctor se poochhiye. | PENDING |
| robin.intro.wont.hi | hi | मैं आपकी कॉल रिकॉर्ड नहीं करती। मैं आपके मैसेज नहीं पढ़ती। मैं आपसे OTP, PIN या पासवर्ड कभी नहीं माँगूँगी। मैं पैसे नहीं भेजती, और दवाई के बारे में सलाह नहीं देती; वो डॉक्टर से पूछिए। | PENDING |
| robin.intro.no.en | en | You can say no to anything, and you can say 'stop' at any time and I will stop. {child} can see what I do, and so can you. | PENDING |
| robin.intro.no.hinglish | hinglish | Aap kisi bhi cheez ke liye na bol sakte hain, aur kabhi bhi 'ruk jao' bol dijiye, main ruk jaungi. Main jo bhi karti hoon wo {child} ko bhi dikhta hai, aur aapko bhi. | PENDING |
| robin.intro.no.hi | hi | आप किसी भी चीज़ के लिए ना बोल सकते हैं, और कभी भी 'रुक जाओ' बोल दीजिए, मैं रुक जाऊँगी। मैं जो भी करती हूँ वो {child} को भी दिखता है, और आपको भी। | PENDING |
| robin.intro.ask.daily_checkin_calls.en | en | May I call you once a day to ask how you are? Please say yes or no. | PENDING |
| robin.intro.ask.daily_checkin_calls.hinglish | hinglish | Kya main roz ek baar phone karke aapka haal poochh sakti hoon? Kripya haan ya na boliye. | PENDING |
| robin.intro.ask.daily_checkin_calls.hi | hi | क्या मैं रोज़ एक बार फ़ोन करके आपका हाल पूछ सकती हूँ? कृपया हाँ या ना बोलिए। | PENDING |
| robin.intro.ask.medicine_reminders.en | en | May I remind you about your medicines? Yes or no? | PENDING |
| robin.intro.ask.medicine_reminders.hinglish | hinglish | Kya main aapko dawai ka yaad dila sakti hoon? Haan ya na? | PENDING |
| robin.intro.ask.medicine_reminders.hi | hi | क्या मैं आपको दवाई का याद दिला सकती हूँ? हाँ या ना? | PENDING |
| robin.intro.ask.scam_check.en | en | If you want me to check a call or a message that looks strange, may I help? Yes or no? | PENDING |
| robin.intro.ask.scam_check.hinglish | hinglish | Agar aap chahein ki main kisi ajeeb call ya message ko check karun, to kya main madad kar sakti hoon? Haan ya na? | PENDING |
| robin.intro.ask.scam_check.hi | hi | अगर आप चाहें कि मैं किसी अजीब कॉल या मैसेज को चेक करूँ, तो क्या मैं मदद कर सकती हूँ? हाँ या ना? | PENDING |
| robin.intro.ask.share_summary_with_child.en | en | May I tell {child} a short summary each day, such as whether you are well? Yes or no? | PENDING |
| robin.intro.ask.share_summary_with_child.hinglish | hinglish | Kya main {child} ko roz ek chhota saar bata sakti hoon, jaise ki aap theek hain ya nahi? Haan ya na? | PENDING |
| robin.intro.ask.share_summary_with_child.hi | hi | क्या मैं {child} को रोज़ एक छोटा सार बता सकती हूँ, जैसे कि आप ठीक हैं या नहीं? हाँ या ना? | PENDING |
| robin.intro.thanks.en | en | Thank you. I will do only what you said yes to. You can call this number and say 'stop' at any time. | PENDING |
| robin.intro.thanks.hinglish | hinglish | Dhanyavaad. Main sirf wahi karungi jis par aapne haan kaha. Aap kabhi bhi is number par phone karke 'ruk jao' bol sakte hain. | PENDING |
| robin.intro.thanks.hi | hi | धन्यवाद। मैं सिर्फ़ वही करूँगी जिस पर आपने हाँ कहा। आप कभी भी इस नंबर पर फ़ोन करके 'रुक जाओ' बोल सकते हैं। | PENDING |
| robin.intro.declined.en | en | That is fine. I will not call you again unless you ask me to. Thank you for your time. | PENDING |
| robin.intro.declined.hinglish | hinglish | Theek hai. Main aapko dobara phone nahi karungi jab tak aap na kahein. Aapka samay dene ke liye dhanyavaad. | PENDING |
| robin.intro.declined.hi | hi | ठीक है। मैं आपको दोबारा फ़ोन नहीं करूँगी जब तक आप न कहें। आपका समय देने के लिए धन्यवाद। | PENDING |
| robin.intro.not_now.en | en | Sorry to disturb you. I will not call again unless you or {child} ask me to. | PENDING |
| robin.intro.not_now.hinglish | hinglish | Disturb karne ke liye maaf kijiye. Main dobara phone nahi karungi jab tak aap ya {child} na kahein. | PENDING |
| robin.intro.not_now.hi | hi | परेशान करने के लिए माफ़ कीजिए। मैं दोबारा फ़ोन नहीं करूँगी जब तक आप या {child} न कहें। | PENDING |
| robin.checkin.greet.en | en | Hello {parent}, this is {brand}, your AI assistant. Just a short check-in. | PENDING |
| robin.checkin.greet.hinglish | hinglish | Namaste {parent}, main {brand} bol rahi hoon, aapki AI assistant. Bas ek chhota sa haal-chaal. | PENDING |
| robin.checkin.greet.hi | hi | नमस्ते {parent}, मैं {brand} बोल रही हूँ, आपकी AI असिस्टेंट। बस एक छोटा सा हाल-चाल। | PENDING |
| robin.checkin.q.ate.en | en | Have you eaten today? | PENDING |
| robin.checkin.q.ate.hinglish | hinglish | Aapne aaj kuch khaya? | PENDING |
| robin.checkin.q.ate.hi | hi | आपने आज कुछ खाया? | PENDING |
| robin.checkin.q.slept.en | en | Did you sleep well last night? | PENDING |
| robin.checkin.q.slept.hinglish | hinglish | Raat ko neend achhi aayi? | PENDING |
| robin.checkin.q.slept.hi | hi | रात को नींद अच्छी आई? | PENDING |
| robin.checkin.q.pain.en | en | Is there any pain or discomfort today? | PENDING |
| robin.checkin.q.pain.hinglish | hinglish | Aaj kisi tarah ka dard ya takleef hai? | PENDING |
| robin.checkin.q.pain.hi | hi | आज किसी तरह का दर्द या तकलीफ़ है? | PENDING |
| robin.checkin.q.mood.en | en | In one word, how is your mood today? | PENDING |
| robin.checkin.q.mood.hinglish | hinglish | Ek shabd mein bataiye, aaj mann kaisa hai? | PENDING |
| robin.checkin.q.mood.hi | hi | एक शब्द में बताइए, आज मन कैसा है? | PENDING |
| robin.checkin.q.strange.en | en | Did anyone call you today asking for money, or did anything feel strange? | PENDING |
| robin.checkin.q.strange.hinglish | hinglish | Aaj kisi ne paise maange ya kuch ajeeb laga? | PENDING |
| robin.checkin.q.strange.hi | hi | आज किसी ने पैसे माँगे या कुछ अजीब लगा? | PENDING |
| robin.checkin.q.meds.en | en | Have you taken your medicines today? | PENDING |
| robin.checkin.q.meds.hinglish | hinglish | Aapne aaj ki dawai li? | PENDING |
| robin.checkin.q.meds.hi | hi | आपने आज की दवाई ली? | PENDING |
| robin.checkin.pain_ack.en | en | Thank you for telling me. I will let {child} know. For pain, please speak to your doctor. | PENDING |
| robin.checkin.pain_ack.hinglish | hinglish | Batane ke liye dhanyavaad. Main {child} ko bata dungi. Dard ke liye doctor se zaroor milein. | PENDING |
| robin.checkin.pain_ack.hi | hi | बताने के लिए धन्यवाद। मैं {child} को बता दूँगी। दर्द के लिए डॉक्टर से ज़रूर मिलें। | PENDING |
| robin.checkin.strange_ack.en | en | Thank you. Please do not share any OTP, PIN or password, and do not send money. I will tell {child}. | PENDING |
| robin.checkin.strange_ack.hinglish | hinglish | Dhanyavaad. Kripya koi OTP, PIN ya password mat batayein aur paise mat bhejein. Main {child} ko bata dungi. | PENDING |
| robin.checkin.strange_ack.hi | hi | धन्यवाद। कृपया कोई OTP, PIN या पासवर्ड मत बताएँ और पैसे मत भेजें। मैं {child} को बता दूँगी। | PENDING |
| robin.checkin.bye.en | en | Thank you, {parent}. Take care. Goodbye. | PENDING |
| robin.checkin.bye.hinglish | hinglish | Dhanyavaad {parent}. Apna khayal rakhiye. Namaste. | PENDING |
| robin.checkin.bye.hi | hi | धन्यवाद {parent}। अपना ख़याल रखिए। नमस्ते। | PENDING |
| robin.med.remind.en | en | {parent}, it is time for {medicine}. Have you taken it? | PENDING |
| robin.med.remind.hinglish | hinglish | {parent}, {medicine} ka time ho gaya hai. Aapne li? | PENDING |
| robin.med.remind.hi | hi | {parent}, {medicine} का समय हो गया है। आपने ली? | PENDING |
| robin.med.thanks.en | en | Thank you. | PENDING |
| robin.med.thanks.hinglish | hinglish | Dhanyavaad. | PENDING |
| robin.med.thanks.hi | hi | धन्यवाद। | PENDING |
| robin.med.later.en | en | All right. Please take it when you can. I will tell {child} if it is missed. | PENDING |
| robin.med.later.hinglish | hinglish | Theek hai. Jab ho sake tab le lijiye. Agar chhoot gayi to main {child} ko bata dungi. | PENDING |
| robin.med.later.hi | hi | ठीक है। जब हो सके तब ले लीजिए। अगर छूट गई तो मैं {child} को बता दूँगी। | PENDING |
| robin.med.count_ask.en | en | How many tablets of {medicine} are left? Please count and tell me the number. | PENDING |
| robin.med.count_ask.hinglish | hinglish | {medicine} ki kitni goliyan bachi hain? Kripya ginkar number bataiye. | PENDING |
| robin.med.count_ask.hi | hi | {medicine} की कितनी गोलियाँ बची हैं? कृपया गिनकर नंबर बताइए। | PENDING |
| robin.med.count_thanks.en | en | Thank you, I have noted it. | PENDING |
| robin.med.count_thanks.hinglish | hinglish | Dhanyavaad, maine note kar liya. | PENDING |
| robin.med.count_thanks.hi | hi | धन्यवाद, मैंने नोट कर लिया। | PENDING |
| robin.nudge.generic.en | en | {parent}, please pause for a moment. If anyone asks you for money, an OTP, a PIN or to open an app, do not do it. Call {child} first. Is everything fine? | PENDING |
| robin.nudge.generic.hinglish | hinglish | {parent}, zara rukiye. Agar koi paise, OTP, PIN maange ya koi app kholne ko kahe, to bilkul mat kijiye. Pehle {child} ko phone kijiye. Kya sab theek hai? | PENDING |
| robin.nudge.generic.hi | hi | {parent}, ज़रा रुकिए। अगर कोई पैसे, OTP, PIN माँगे या कोई ऐप खोलने को कहे, तो बिल्कुल मत कीजिए। पहले {child} को फ़ोन कीजिए। क्या सब ठीक है? | PENDING |
| robin.nudge.remote_access.en | en | {parent}, an app that lets someone control your phone seems to be open. Please close it, and call {child}. Are you fine? | PENDING |
| robin.nudge.remote_access.hinglish | hinglish | {parent}, aisa lagta hai ki koi app khula hai jisse koi aapka phone control kar sakta hai. Use band kar dijiye aur {child} ko phone kijiye. Aap theek hain? | PENDING |
| robin.nudge.remote_access.hi | hi | {parent}, ऐसा लगता है कि कोई ऐप खुला है जिससे कोई आपका फ़ोन कंट्रोल कर सकता है। उसे बंद कर दीजिए और {child} को फ़ोन कीजिए। आप ठीक हैं? | PENDING |
| robin.nudge.money.en | en | {parent}, did you just send money? If not, please call your bank's helpline right now and tell {child}. Was it you? | PENDING |
| robin.nudge.money.hinglish | hinglish | {parent}, kya aapne abhi paise bheje? Agar nahi, to turant apne bank ki helpline ko phone kijiye aur {child} ko bataiye. Kya wo aap the? | PENDING |
| robin.nudge.money.hi | hi | {parent}, क्या आपने अभी पैसे भेजे? अगर नहीं, तो तुरंत अपने बैंक की हेल्पलाइन को फ़ोन कीजिए और {child} को बताइए। क्या वो आप थे? | PENDING |
| robin.nudge.safe_word.en | en | {parent}, if someone says they are a relative and asks for money, ask them for the family safe word. If they cannot say it, hang up and call {child}. Is everything fine? | PENDING |
| robin.nudge.safe_word.hinglish | hinglish | {parent}, agar koi khud ko rishtedar bataye aur paise maange, to usse family safe word poochhiye. Wo na bata sake to phone kaat dijiye aur {child} ko phone kijiye. Kya sab theek hai? | PENDING |
| robin.nudge.safe_word.hi | hi | {parent}, अगर कोई ख़ुद को रिश्तेदार बताए और पैसे माँगे, तो उससे फ़ैमिली सेफ़ वर्ड पूछिए। वो न बता सके तो फ़ोन काट दीजिए और {child} को फ़ोन कीजिए। क्या सब ठीक है? | PENDING |
| robin.nudge.fine_ack.en | en | Thank you. I will tell {child} that you are fine. | PENDING |
| robin.nudge.fine_ack.hinglish | hinglish | Dhanyavaad. Main {child} ko bata dungi ki aap theek hain. | PENDING |
| robin.nudge.fine_ack.hi | hi | धन्यवाद। मैं {child} को बता दूँगी कि आप ठीक हैं। | PENDING |
| robin.nudge.not_fine_ack.en | en | I am telling {child} right now. Please stay safe and do not share anything. | PENDING |
| robin.nudge.not_fine_ack.hinglish | hinglish | Main abhi {child} ko bata rahi hoon. Kripya surakshit rahiye aur kuch bhi mat batayein. | PENDING |
| robin.nudge.not_fine_ack.hi | hi | मैं अभी {child} को बता रही हूँ। कृपया सुरक्षित रहिए और कुछ भी मत बताइए। | PENDING |
| robin.sos.parent.en | en | {parent}, I am {brand}. I have told {child} right now. Please stay on the line or keep your phone near you. If you need an ambulance or the police, press 112 on your phone. | PENDING |
| robin.sos.parent.hinglish | hinglish | {parent}, main {brand} hoon. Maine abhi {child} ko khabar kar di hai. Kripya line par rahiye ya phone paas rakhiye. Ambulance ya police chahiye to apne phone par 112 dabaiye. | PENDING |
| robin.sos.parent.hi | hi | {parent}, मैं {brand} हूँ। मैंने अभी {child} को ख़बर कर दी है। कृपया लाइन पर रहिए या फ़ोन पास रखिए। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए। | PENDING |
| robin.sos.ask.en | en | Can you tell me in a few words what happened? | PENDING |
| robin.sos.ask.hinglish | hinglish | Kya aap thode shabdon mein bata sakte hain ki kya hua? | PENDING |
| robin.sos.ask.hi | hi | क्या आप थोड़े शब्दों में बता सकते हैं कि क्या हुआ? | PENDING |
| robin.sos.noted.en | en | Thank you. I have passed this on to {child}. | PENDING |
| robin.sos.noted.hinglish | hinglish | Dhanyavaad. Maine yeh {child} tak pahuncha diya hai. | PENDING |
| robin.sos.noted.hi | hi | धन्यवाद। मैंने यह {child} तक पहुँचा दिया है। | PENDING |
| robin.inbound.hello.en | en | Hello {parent}, this is {brand}. I am here. Say 'help' if you need help, or 'stop' to pause me. | PENDING |
| robin.inbound.hello.hinglish | hinglish | Namaste {parent}, main {brand} hoon. Madad chahiye to 'madad' boliye, ya mujhe rokne ke liye 'ruk jao' boliye. | PENDING |
| robin.inbound.hello.hi | hi | नमस्ते {parent}, मैं {brand} हूँ। मदद चाहिए तो 'मदद' बोलिए, या मुझे रोकने के लिए 'रुक जाओ' बोलिए। | PENDING |
| robin.widget.sos.en | en | {parent}, I have told {child} right now. If you need an ambulance or the police, press 112 on your phone. | PENDING |
| robin.widget.sos.hinglish | hinglish | {parent}, maine abhi {child} ko khabar kar di hai. Ambulance ya police chahiye to apne phone par 112 dabaiye. | PENDING |
| robin.widget.sos.hi | hi | {parent}, मैंने अभी {child} को ख़बर कर दी है। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए। | PENDING |
| robin.widget.sos_failed.en | en | I could not reach {child} just now. If you need an ambulance or the police, press 112 on your phone. | PENDING |
| robin.widget.sos_failed.hinglish | hinglish | Main abhi {child} tak khabar nahi pahuncha payi. Ambulance ya police chahiye to apne phone par 112 dabaiye. | PENDING |
| robin.widget.sos_failed.hi | hi | मैं अभी {child} तक ख़बर नहीं पहुँचा पाई। एम्बुलेंस या पुलिस चाहिए तो अपने फ़ोन पर 112 दबाइए। | PENDING |
| robin.widget.unclear.en | en | I could not hear you clearly. Please press the button and say it once more. | PENDING |
| robin.widget.unclear.hinglish | hinglish | Mujhe aawaz saaf nahi aayi. Kripya button dabakar ek baar phir boliye. | PENDING |
| robin.widget.unclear.hi | hi | मुझे आवाज़ साफ़ नहीं आई। कृपया बटन दबाकर एक बार फिर बोलिए। | PENDING |
| robin.inbound.unclear.en | en | Sorry {parent}, this is {brand}. I could not hear that. Please say it again. | PENDING |
| robin.inbound.unclear.hinglish | hinglish | Maaf kijiye {parent}, main {brand} hoon. Mujhe woh sunai nahi diya. Kripya dobara boliye. | PENDING |
| robin.inbound.unclear.hi | hi | माफ़ कीजिए {parent}, मैं {brand} हूँ। मुझे वह सुनाई नहीं दिया। कृपया दोबारा बोलिए। | PENDING |
| robin.scam.high.en | en | {verdict} {why} {parent}, please do not click anything, do not pay and do not share any OTP or PIN. Call {child} first. | PENDING |
| robin.scam.high.hinglish | hinglish | {verdict} {why} {parent}, kripya kuch bhi click mat kijiye, paise mat bhejiye aur OTP ya PIN kisi ko mat bataiye. Pehle {child} ko call kijiye. | PENDING |
| robin.scam.high.hi | hi | {verdict} {why} {parent}, कृपया कुछ भी क्लिक मत कीजिए, पैसे मत भेजिए और OTP या PIN किसी को मत बताइए। पहले {child} को कॉल कीजिए। | PENDING |
| robin.scam.risky.en | en | {verdict} {why} Please do not click and do not pay. Call {child} before you do anything. | PENDING |
| robin.scam.risky.hinglish | hinglish | {verdict} {why} Kripya click mat kijiye aur paise mat bhejiye. Kuch bhi karne se pehle {child} ko call kijiye. | PENDING |
| robin.scam.risky.hi | hi | {verdict} {why} कृपया क्लिक मत कीजिए और पैसे मत भेजिए। कुछ भी करने से पहले {child} को कॉल कीजिए। | PENDING |
| robin.scam.unsure.en | en | {verdict} Please do not click and do not pay yet. Show it to {child} first. | PENDING |
| robin.scam.unsure.hinglish | hinglish | {verdict} Kripya abhi click mat kijiye aur paise mat bhejiye. Pehle yeh {child} ko dikhaiye. | PENDING |
| robin.scam.unsure.hi | hi | {verdict} कृपया अभी क्लिक मत कीजिए और पैसे मत भेजिए। पहले यह {child} को दिखाइए। | PENDING |
| robin.scam.nosigns.en | en | {verdict} That does not mean everything is fine. If it asks for money, an OTP or a click, please call {child} first. | PENDING |
| robin.scam.nosigns.hinglish | hinglish | {verdict} Iska matlab yeh nahi ki sab theek hai. Agar isme paise, OTP ya click maanga jaye to pehle {child} ko call kijiye. | PENDING |
| robin.scam.nosigns.hi | hi | {verdict} इसका मतलब यह नहीं कि सब ठीक है। अगर इसमें पैसे, OTP या क्लिक माँगा जाए तो पहले {child} को कॉल कीजिए। | PENDING |
| robin.scam.unreadable.en | en | I could not read this. Please do not click and do not pay. Show it to {child}. | PENDING |
| robin.scam.unreadable.hinglish | hinglish | Main ise padh nahi payi. Kripya click mat kijiye aur paise mat bhejiye. Yeh {child} ko dikhaiye. | PENDING |
| robin.scam.unreadable.hi | hi | मैं इसे पढ़ नहीं पाई। कृपया क्लिक मत कीजिए और पैसे मत भेजिए। यह {child} को दिखाइए। | PENDING |
| robin.scam.repeat.en | en | This sender has written before. Please do not reply. | PENDING |
| robin.scam.repeat.hinglish | hinglish | Is bhejne wale ne pehle bhi likha hai. Kripya jawab mat dijiye. | PENDING |
| robin.scam.repeat.hi | hi | इस भेजने वाले ने पहले भी लिखा है। कृपया जवाब मत दीजिए। | PENDING |
| robin.scam.no_consent.en | en | {parent}, I cannot check messages yet, because {child} has not switched this on. Please show it to {child}, and do not click or pay until then. | PENDING |
| robin.scam.no_consent.hinglish | hinglish | {parent}, main abhi messages nahi jaanch sakti, kyunki {child} ne yeh chalu nahi kiya hai. Kripya yeh {child} ko dikhaiye, aur tab tak click mat kijiye aur paise mat bhejiye. | PENDING |
| robin.scam.no_consent.hi | hi | {parent}, मैं अभी मैसेज नहीं जाँच सकती, क्योंकि {child} ने यह चालू नहीं किया है। कृपया यह {child} को दिखाइए, और तब तक क्लिक मत कीजिए और पैसे मत भेजिए। | PENDING |
| robin.pause.ack.en | en | All right, I have stopped. I will not call you until you tell me to start again. | PENDING |
| robin.pause.ack.hinglish | hinglish | Theek hai, main ruk gayi. Jab tak aap dobara shuru karne ko na kahein, main phone nahi karungi. | PENDING |
| robin.pause.ack.hi | hi | ठीक है, मैं रुक गई। जब तक आप दोबारा शुरू करने को न कहें, मैं फ़ोन नहीं करूँगी। | PENDING |
| robin.resume.ack.en | en | All right, I am back. I will do what you agreed to. | PENDING |
| robin.resume.ack.hinglish | hinglish | Theek hai, main wapas aa gayi. Main wahi karungi jis par aap raazi hue the. | PENDING |
| robin.resume.ack.hi | hi | ठीक है, मैं वापस आ गई। मैं वही करूँगी जिस पर आप राज़ी हुए थे। | PENDING |
| robin.delete.ack.en | en | Done. I have deleted everything about you. Goodbye. | PENDING |
| robin.delete.ack.hinglish | hinglish | Ho gaya. Maine aapke baare mein sab kuch hata diya. Namaste. | PENDING |
| robin.delete.ack.hi | hi | हो गया। मैंने आपके बारे में सब कुछ हटा दिया। नमस्ते। | PENDING |
| robin.child.ring.en | en | Hello {child}, this is {brand}. There is an important message about {parent} on WhatsApp. Please look at it now. | PENDING |
| robin.child.ring.hinglish | hinglish | Hello {child}, main {brand} bol rahi hoon. {parent} ke baare mein WhatsApp par ek zaroori message hai. Kripya abhi dekh lijiye. | PENDING |
| robin.child.ring.hi | hi | हैलो {child}, मैं {brand} बोल रही हूँ। {parent} के बारे में WhatsApp पर एक ज़रूरी मैसेज है। कृपया अभी देख लीजिए। | PENDING |
| robin.child.ring_sos.en | en | Hello {child}, this is {brand}. {parent} pressed the help button. Please call {parent} now. | PENDING |
| robin.child.ring_sos.hinglish | hinglish | Hello {child}, main {brand} bol rahi hoon. {parent} ne madad ka button dabaya hai. Kripya abhi unhe phone kijiye. | PENDING |
| robin.child.ring_sos.hi | hi | हैलो {child}, मैं {brand} बोल रही हूँ। {parent} ने मदद का बटन दबाया है। कृपया अभी उन्हें फ़ोन कीजिए। | PENDING |
| robin.child.ring_unreached.en | en | Hello {child}, this is {brand}. {parent} did not answer today's check-in. Please see WhatsApp and call {parent}. | PENDING |
| robin.child.ring_unreached.hinglish | hinglish | Hello {child}, main {brand} bol rahi hoon. {parent} ne aaj ka check-in nahi uthaya. Kripya WhatsApp dekhiye aur {parent} ko phone kijiye. | PENDING |
| robin.child.ring_unreached.hi | hi | हैलो {child}, मैं {brand} बोल रही हूँ। {parent} ने आज का चेक-इन नहीं उठाया। कृपया WhatsApp देखिए और {parent} को फ़ोन कीजिए। | PENDING |
| robin.second.ring.en | en | Hello, this is {brand}, an AI assistant. {child} named you as someone to contact about {parent}. Please call {child} or {parent} now. | PENDING |
| robin.second.ring.hinglish | hinglish | Hello, main {brand} bol rahi hoon, ek AI assistant. {child} ne aapko {parent} ke liye sampark ke roop mein bataya tha. Kripya abhi {child} ya {parent} ko phone kijiye. | PENDING |
| robin.second.ring.hi | hi | हैलो, मैं {brand} बोल रही हूँ, एक AI असिस्टेंट। {child} ने आपको {parent} के लिए संपर्क के रूप में बताया था। कृपया अभी {child} या {parent} को फ़ोन कीजिए। | PENDING |
| robin.bridge.child.en | en | Hello {child}, this is {brand}. I am connecting you with {parent} now. | PENDING |
| robin.bridge.child.hinglish | hinglish | Hello {child}, main {brand} hoon. Main aapko abhi {parent} se jod rahi hoon. | PENDING |
| robin.bridge.child.hi | hi | हैलो {child}, मैं {brand} हूँ। मैं आपको अभी {parent} से जोड़ रही हूँ। | PENDING |
| robin.bridge.parent.en | en | {parent}, {child} wants to talk to you. I am connecting you now. | PENDING |
| robin.bridge.parent.hinglish | hinglish | {parent}, {child} aapse baat karna chahte hain. Main aapko abhi jod rahi hoon. | PENDING |
| robin.bridge.parent.hi | hi | {parent}, {child} आपसे बात करना चाहते हैं। मैं आपको अभी जोड़ रही हूँ। | PENDING |
| robin.safeword.prompt.en | en | {parent}, ask the person you are talking to for the family safe word. If they cannot say it, hang up and call {child}. | PENDING |
| robin.safeword.prompt.hinglish | hinglish | {parent}, jis se aap baat kar rahe hain unse family safe word poochhiye. Wo na bata sake to phone kaat dijiye aur {child} ko phone kijiye. | PENDING |
| robin.safeword.prompt.hi | hi | {parent}, जिससे आप बात कर रहे हैं उनसे फ़ैमिली सेफ़ वर्ड पूछिए। वो न बता सके तो फ़ोन काट दीजिए और {child} को फ़ोन कीजिए। | PENDING |
| robin.monthly.reminder.en | en | {parent}, this is {brand}, your AI assistant, with a monthly reminder. These are switched on: {items}. You can pause me or switch any of them off at any time. | PENDING |
| robin.monthly.reminder.hinglish | hinglish | {parent}, main {brand} hoon, aapki AI assistant, mahine ki yaad dilane. Yeh chalu hain: {items}. Aap kabhi bhi mujhe rok sakte hain ya inmein se kuch band kar sakte hain. | PENDING |
| robin.monthly.reminder.hi | hi | {parent}, मैं {brand} हूँ, आपकी AI असिस्टेंट, महीने की याद दिलाने। ये चालू हैं: {items}। आप कभी भी मुझे रोक सकते हैं या इनमें से कुछ बंद कर सकते हैं। | PENDING |
| robin.notify.stop.en | en | To stop me, just say '{brand}, stop' in a voice message or write it, or tap the stop button on the widget. I do not read your chats and I do not record your phone. | PENDING |
| robin.notify.stop.hinglish | hinglish | Mujhe rokne ke liye bas voice message mein '{brand}, band karo' bol dijiye ya likh dijiye, ya widget par stop dabaiye. Main aapki chats nahi padhti aur aapka phone record nahi karti. | PENDING |
| robin.notify.stop.hi | hi | मुझे रोकने के लिए बस वॉइस मैसेज में '{brand}, बंद करो' बोल दीजिए या लिख दीजिए, या विजेट पर स्टॉप दबाइए। मैं आपकी चैट नहीं पढ़ती और आपका फ़ोन रिकॉर्ड नहीं करती। | PENDING |
| robin.notify.set_up_by.en | en | Hello {parent}. I am {brand}, an AI assistant. {child} set me up to look after you. | PENDING |
| robin.notify.set_up_by.hinglish | hinglish | Namaste {parent}. Main {brand} hoon, ek AI assistant. {child} ne mujhe aapka khayal rakhne ke liye set up kiya hai. | PENDING |
| robin.notify.set_up_by.hi | hi | नमस्ते {parent}। मैं {brand} हूँ, एक AI असिस्टेंट। {child} ने मुझे आपका ख़याल रखने के लिए सेट अप किया है। | PENDING |
| robin.gm.greet.en | en | Good morning {parent}! Today is {date}. | PENDING |
| robin.gm.greet.hinglish | hinglish | Suprabhat {parent}! Aaj {date} hai. | PENDING |
| robin.gm.greet.hi | hi | सुप्रभात {parent}! आज {date} है। | PENDING |
| robin.gm.meds.en | en | Your medicine times today: {meds}. | PENDING |
| robin.gm.meds.hinglish | hinglish | Aaj ki dawai ka samay: {meds}. | PENDING |
| robin.gm.meds.hi | hi | आज की दवाई का समय: {meds}। | PENDING |
| robin.fest.greeting.en | en | Happy {festival}, {parent}! Wishing you and your family joy and good health. | PENDING |
| robin.fest.greeting.hinglish | hinglish | {festival} ki bahut shubhkamnayein, {parent}! Aapko aur parivar ko khushi aur achhi sehat mile. | PENDING |
| robin.fest.greeting.hi | hi | {festival} की बहुत शुभकामनाएँ, {parent}! आपको और परिवार को ख़ुशी और अच्छी सेहत मिले। | PENDING |
| robin.gm.share.en | en | You can share this greeting with your family group. | PENDING |
| robin.gm.share.hinglish | hinglish | Aap yeh shubhkamna apne family group mein bhej sakte hain. | PENDING |
| robin.gm.share.hi | hi | आप यह शुभकामना अपने फ़ैमिली ग्रुप में भेज सकते हैं। | PENDING |
| robin.missed.ask_who.en | en | Hello, this is {brand}, an AI assistant answering for {parent}. {parent} cannot take the call right now. Who is calling, and what is it about? | PENDING |
| robin.missed.ask_who.hinglish | hinglish | Namaste, main {brand} bol rahi hoon, {parent} ki AI assistant. {parent} abhi call nahi le sakte. Aap kaun bol rahe hain aur kis baare mein? | PENDING |
| robin.missed.ask_who.hi | hi | नमस्ते, मैं {brand} बोल रही हूँ, {parent} की AI असिस्टेंट। {parent} अभी कॉल नहीं ले सकते। आप कौन बोल रहे हैं और किस बारे में? | PENDING |
| robin.missed.ask_urgent.en | en | Is it urgent or an emergency? Please say yes or no. | PENDING |
| robin.missed.ask_urgent.hinglish | hinglish | Kya yeh zaroori ya emergency hai? Kripya haan ya na boliye. | PENDING |
| robin.missed.ask_urgent.hi | hi | क्या यह ज़रूरी या इमरजेंसी है? कृपया हाँ या ना बोलिए। | PENDING |
| robin.missed.urgent_ack.en | en | Thank you. I am telling {parent} it is urgent and I will keep trying to reach them. | PENDING |
| robin.missed.urgent_ack.hinglish | hinglish | Dhanyavaad. Main {parent} ko bata rahi hoon ki yeh zaroori hai aur main unse sampark karti rahungi. | PENDING |
| robin.missed.urgent_ack.hi | hi | धन्यवाद। मैं {parent} को बता रही हूँ कि यह ज़रूरी है और मैं उनसे संपर्क करती रहूँगी। | PENDING |
| robin.missed.normal_ack.en | en | Thank you. I will pass your message to {parent}. | PENDING |
| robin.missed.normal_ack.hinglish | hinglish | Dhanyavaad. Main aapka sandesh {parent} tak pahuncha dungi. | PENDING |
| robin.missed.normal_ack.hi | hi | धन्यवाद। मैं आपका संदेश {parent} तक पहुँचा दूँगी। | PENDING |
| robin.missed.msg.en | en | {who} called you at {time}. They said: {summary}. | PENDING |
| robin.missed.msg.hinglish | hinglish | {who} ne aapko {time} baje phone kiya tha. Unhone kaha: {summary}. | PENDING |
| robin.missed.msg.hi | hi | {who} ने आपको {time} बजे फ़ोन किया था। उन्होंने कहा: {summary}। | PENDING |
| robin.missed.msg_urgent.en | en | {who} called you at {time} and says it is URGENT. They said: {summary}. Please call back now. | PENDING |
| robin.missed.msg_urgent.hinglish | hinglish | {who} ne aapko {time} baje phone kiya aur kehte hain ki yeh ZAROORI hai. Unhone kaha: {summary}. Kripya abhi wapas phone kijiye. | PENDING |
| robin.missed.msg_urgent.hi | hi | {who} ने आपको {time} बजे फ़ोन किया और कहते हैं कि यह ज़रूरी है। उन्होंने कहा: {summary}। कृपया अभी वापस फ़ोन कीजिए। | PENDING |
| robin.missed.emergency_ring.en | en | Hello {parent}, this is {brand}. {who} called and says it is an emergency. Please call {who} now. | PENDING |
| robin.missed.emergency_ring.hinglish | hinglish | Hello {parent}, main {brand} bol rahi hoon. {who} ne phone kiya aur kehte hain ki emergency hai. Kripya abhi {who} ko phone kijiye. | PENDING |
| robin.missed.emergency_ring.hi | hi | हैलो {parent}, मैं {brand} बोल रही हूँ। {who} ने फ़ोन किया और कहते हैं कि इमरजेंसी है। कृपया अभी {who} को फ़ोन कीजिए। | PENDING |
| robin.missed.caller_told.en | en | {missed} has been told that you called and what you said. | PENDING |
| robin.missed.caller_told.hinglish | hinglish | {missed} ko bata diya gaya hai ki aapne phone kiya tha aur aapne kya kaha. | PENDING |
| robin.missed.caller_told.hi | hi | {missed} को बता दिया गया है कि आपने फ़ोन किया था और आपने क्या कहा। | PENDING |
| robin.missed.caller_told_urgent.en | en | {missed} has been told that you called and that it is urgent. {brand} keeps trying to reach them. | PENDING |
| robin.missed.caller_told_urgent.hinglish | hinglish | {missed} ko bata diya gaya hai ki aapne phone kiya aur yeh zaroori hai. {brand} unse sampark karti rahegi. | PENDING |
| robin.missed.caller_told_urgent.hi | hi | {missed} को बता दिया गया है कि आपने फ़ोन किया और यह ज़रूरी है। {brand} उनसे संपर्क करती रहेगी। | PENDING |
| robin.authority.countdown.en | en | {parent}, I am about to ask for emergency help for you in one minute. If you are fine, say 'I am fine' now. | PENDING |
| robin.authority.countdown.hinglish | hinglish | {parent}, main ek minute mein aapke liye emergency madad maangne wali hoon. Agar aap theek hain to abhi 'main theek hoon' boliye. | PENDING |
| robin.authority.countdown.hi | hi | {parent}, मैं एक मिनट में आपके लिए इमरजेंसी मदद माँगने वाली हूँ। अगर आप ठीक हैं तो अभी 'मैं ठीक हूँ' बोलिए। | PENDING |
| robin.authority.what.medical.en | en | a possible medical emergency | PENDING |
| robin.authority.what.medical.hinglish | hinglish | ek sambhavit medical emergency | PENDING |
| robin.authority.what.medical.hi | hi | एक संभावित मेडिकल इमरजेंसी | PENDING |
| robin.authority.what.threat.en | en | a possible threat to their safety | PENDING |
| robin.authority.what.threat.hinglish | hinglish | unki suraksha ko sambhavit khatra | PENDING |
| robin.authority.what.threat.hi | hi | उनकी सुरक्षा को संभावित ख़तरा | PENDING |
| robin.authority.what.unknown.en | en | a possible emergency | PENDING |
| robin.authority.what.unknown.hinglish | hinglish | ek sambhavit emergency | PENDING |
| robin.authority.what.unknown.hi | hi | एक संभावित इमरजेंसी | PENDING |
| robin.authority.script_112.en | en | This is an automated call from {brand}, an AI assistant, for {name}. There may be {what}. The address is {address}. Please send help. The callback number is {callback}. I will repeat once. | PENDING |
| robin.authority.script_112.hinglish | hinglish | Yeh {brand} ki taraf se ek automatic call hai, ek AI assistant, {name} ke liye. Wahan {what} ho sakti hai. Pata hai {address}. Kripya madad bhejiye. Callback number hai {callback}. Main ek baar dohraungi. | PENDING |
| robin.authority.script_112.hi | hi | यह {brand} की तरफ़ से एक ऑटोमैटिक कॉल है, एक AI असिस्टेंट, {name} के लिए। वहाँ {what} हो सकती है। पता है {address}। कृपया मदद भेजिए। कॉलबैक नंबर है {callback}। मैं एक बार दोहराऊँगी। | PENDING |
| robin.authority.bridge_1930.en | en | {child}, I am connecting you to the cyber-fraud helpline 1930 for {parent}. You will speak to them yourself; I will stay quiet. | PENDING |
| robin.authority.bridge_1930.hinglish | hinglish | {child}, main {parent} ke liye aapko cyber-fraud helpline 1930 se jod rahi hoon. Aap khud unse baat karenge; main chup rahungi. | PENDING |
| robin.authority.bridge_1930.hi | hi | {child}, मैं {parent} के लिए आपको साइबर-फ़्रॉड हेल्पलाइन 1930 से जोड़ रही हूँ। आप ख़ुद उनसे बात करेंगे; मैं चुप रहूँगी। | PENDING |
| robin.screen.ask.en | en | Hello, this is {brand}, an AI assistant answering for {parent}. May I know who is calling and what it is about? | PENDING |
| robin.screen.ask.hinglish | hinglish | Namaste, main {brand} bol rahi hoon, {parent} ki AI assistant. Kya main jaan sakti hoon ki aap kaun bol rahe hain aur kis baare mein? | PENDING |
| robin.screen.ask.hi | hi | नमस्ते, मैं {brand} बोल रही हूँ, {parent} की AI असिस्टेंट। क्या मैं जान सकती हूँ कि आप कौन बोल रहे हैं और किस बारे में? | PENDING |
| robin.screen.connect.en | en | Thank you. I am connecting you to {parent} now. | PENDING |
| robin.screen.connect.hinglish | hinglish | Dhanyavaad. Main aapko abhi {parent} se jod rahi hoon. | PENDING |
| robin.screen.connect.hi | hi | धन्यवाद। मैं आपको अभी {parent} से जोड़ रही हूँ। | PENDING |
| robin.screen.decline.en | en | {parent} cannot take this call. I will pass on that you called. Goodbye. | PENDING |
| robin.screen.decline.hinglish | hinglish | {parent} yeh call nahi le sakte. Main bata dungi ki aapne phone kiya tha. Namaste. | PENDING |
| robin.screen.decline.hi | hi | {parent} यह कॉल नहीं ले सकते। मैं बता दूँगी कि आपने फ़ोन किया था। नमस्ते। | PENDING |
| robin.listen.disclose.en | en | Hello, this is {brand}, an AI assistant. {parent} asked me to listen in on this call to help keep them safe. I do not record it. | PENDING |
| robin.listen.disclose.hinglish | hinglish | Namaste, main {brand} hoon, ek AI assistant. {parent} ne mujhe is call par saath rehne ko kaha hai taaki wo surakshit rahein. Main call record nahi karti. | PENDING |
| robin.listen.disclose.hi | hi | नमस्ते, मैं {brand} हूँ, एक AI असिस्टेंट। {parent} ने मुझे इस कॉल पर साथ रहने को कहा है ताकि वो सुरक्षित रहें। मैं कॉल रिकॉर्ड नहीं करती। | PENDING |
| robin.listen.warn.en | en | {parent}, this call looks risky. Please do not send money or share any OTP or PIN. You can hang up and call {child}. | PENDING |
| robin.listen.warn.hinglish | hinglish | {parent}, yeh call risky lag rahi hai. Kripya paise mat bhejiye aur OTP ya PIN mat batayein. Aap phone kaat kar {child} ko phone kar sakte hain. | PENDING |
| robin.listen.warn.hi | hi | {parent}, यह कॉल रिस्की लग रही है। कृपया पैसे मत भेजिए और OTP या PIN मत बताइए। आप फ़ोन काटकर {child} को फ़ोन कर सकते हैं। | PENDING |

## Chat lines to the child (admin)

| Id | Language | Text | Status |
|---|---|---|---|
| robin.scam.child_high.en | en | {parent} sent {brand} a message to check, and it looks very risky. {what} I told {parent} not to click, not to pay and to call you. I did not keep the message. Please call {parent} now. | PENDING |
| robin.scam.child_high.hinglish | hinglish | {parent} ne {brand} ko jaanchne ke liye ek message bheja, aur wo bahut risky lag raha hai. {what} Maine {parent} ko click aur payment na karne aur aapko call karne ko kaha hai. Maine message rakha nahi hai. Kripya abhi {parent} ko call kijiye. | PENDING |
| robin.scam.child_repeat.en | en | {parent} sent {brand} another message from a sender that has now written {n} times. {what} I told {parent} not to reply. I did not keep the message. Please call {parent}. | PENDING |
| robin.scam.child_repeat.hinglish | hinglish | {parent} ne {brand} ko ek aur message bheja, jis bhejne wale ne ab {n} baar likha hai. {what} Maine {parent} ko jawab na dene ko kaha hai. Maine message rakha nahi hai. Kripya {parent} ko call kijiye. | PENDING |
| robin.scam.child_no_consent.en | en | {parent} tried to send {brand} a message to check, but scam check is not switched on, so I did not look at it. I told {parent} to show it to you. To switch it on, write: enable scam check. | PENDING |
| robin.scam.child_no_consent.hinglish | hinglish | {parent} ne {brand} ko jaanchne ke liye message bhejna chaha, lekin scam check chalu nahi hai, isliye maine use dekha nahi. Maine {parent} ko aapko dikhane ko kaha hai. Chalu karne ke liye likhiye: enable scam check. | PENDING |
| robin.scam.child_playbook.en | en | If money was already sent, a code was shared or a link was opened, act in the first hour: 1) call your bank's helpline and ask them to block or freeze the payment; 2) call 1930, the cyber fraud helpline; 3) write down the amount, the time and the transaction ids; 4) file a report at cybercrime.gov.in; 5) be kind to {parent}, this happens to many careful people. | PENDING |
| robin.scam.child_playbook.hinglish | hinglish | Agar paise bhej diye gaye hain, code bata diya gaya hai ya link khol liya gaya hai, to pehle ghante mein yeh kijiye: 1) apne bank ki helpline par call karke payment block ya freeze karwayiye; 2) 1930 par call kijiye, yeh cyber fraud helpline hai; 3) rakam, samay aur transaction id likh lijiye; 4) cybercrime.gov.in par report darj kijiye; 5) {parent} se pyaar se baat kijiye, yeh bahut samajhdar logon ke saath bhi hota hai. | PENDING |
| robin.setup.start.en | en | Let me set up {brand} for your {rel}. What is their mobile number? | PENDING |
| robin.setup.start.hinglish | hinglish | {rel} ke liye {brand} set up karte hain. Unka mobile number kya hai? | PENDING |
| robin.setup.bad_number.en | en | That does not look like a mobile number. Please send 10 digits or a number with +91. | PENDING |
| robin.setup.bad_number.hinglish | hinglish | Yeh mobile number jaisa nahi lag raha. Kripya 10 digit ya +91 ke saath number bhejiye. | PENDING |
| robin.setup.same_number.en | en | That is your own number. Please send your {rel}'s number. | PENDING |
| robin.setup.same_number.hinglish | hinglish | Yeh aapka apna number hai. Kripya apne {rel} ka number bhejiye. | PENDING |
| robin.setup.ask_language.en | en | Which language should I speak with {parent}? Hindi, Hinglish or English? | PENDING |
| robin.setup.ask_language.hinglish | hinglish | {parent} se main kis bhasha mein baat karun? Hindi, Hinglish ya English? | PENDING |
| robin.setup.ask_time.en | en | At what time should I make the daily check-in call? For example, 9 am. | PENDING |
| robin.setup.ask_time.hinglish | hinglish | Roz check-in call kis samay karun? Jaise subah 9 baje. | PENDING |
| robin.setup.bad_time.en | en | I could not understand the time. Please send something like 9 am or 18:30. | PENDING |
| robin.setup.bad_time.hinglish | hinglish | Samay samajh nahi aaya. Kripya aisa bhejiye: 9 am ya 18:30. | PENDING |
| robin.setup.time_in_quiet.en | en | That time falls inside quiet hours ({start} to {end}). Please choose another time. | PENDING |
| robin.setup.time_in_quiet.hinglish | hinglish | Yeh samay quiet hours ({start} se {end}) ke andar hai. Kripya koi aur samay chuniye. | PENDING |
| robin.setup.ask_quiet.en | en | I will not call {parent} between {start} and {end} (except real emergencies). Reply 'ok' or send other hours like 10pm-7am. | PENDING |
| robin.setup.ask_quiet.hinglish | hinglish | Main {parent} ko {start} se {end} ke beech phone nahi karungi (sirf asli emergency chhodkar). 'ok' likhiye ya doosre ghante bhejiye, jaise 10pm-7am. | PENDING |
| robin.setup.bad_quiet.en | en | Please send hours like 10pm-7am, or 'ok'. | PENDING |
| robin.setup.bad_quiet.hinglish | hinglish | Kripya aise ghante bhejiye: 10pm-7am, ya 'ok'. | PENDING |
| robin.setup.ask_second.en | en | Is there a second person I may contact if I cannot reach you? Send their number, or 'no'. I will only contact someone you name now. | PENDING |
| robin.setup.ask_second.hinglish | hinglish | Agar main aap tak na pahunch paun to koi doosra vyakti hai jisse sampark karun? Unka number bhejiye, ya 'no'. Main sirf unhi ko contact karungi jinka naam aap abhi dein. | PENDING |
| robin.setup.ask_sensitivity.en | en | How careful should I be? Calm (fewer alerts), Balanced, or Careful (more alerts). | PENDING |
| robin.setup.ask_sensitivity.hinglish | hinglish | Main kitni satark rahun? Calm (kam alerts), Balanced, ya Careful (zyada alerts). | PENDING |
| robin.setup.bad_sensitivity.en | en | Please reply Calm, Balanced or Careful. | PENDING |
| robin.setup.bad_sensitivity.hinglish | hinglish | Kripya Calm, Balanced ya Careful likhiye. | PENDING |
| robin.setup.ask_child_call.en | en | May I ring you (on this number) for urgent things about {parent}? yes or no. | PENDING |
| robin.setup.ask_child_call.hinglish | hinglish | Kya main {parent} ke baare mein zaroori baaton ke liye aapko (is number par) phone kar sakti hoon? yes ya no. | PENDING |
| robin.setup.done.en | en | All set. I will NOT call {parent} until they agree. My first call is a short introduction: I say I am an AI assistant called {brand}, who asked me, what I will and will not do, and how to say no. Please tell {parent} to expect it. I will tell you what they say. | PENDING |
| robin.setup.done.hinglish | hinglish | Ho gaya. Main {parent} ko tab tak phone NAHI karungi jab tak wo haan na kahein. Meri pehli call ek chhota parichay hoga: main bataungi ki main {brand} naam ki AI assistant hoon, mujhe kisne kaha, main kya karungi aur kya nahi, aur na kaise kehna hai. Kripya {parent} ko batayein ki call aayegi. Wo jo bolenge main aapko bataungi. | PENDING |
| robin.setup.not_allowed.en | en | In this pilot I can only call numbers that are explicitly allow-listed, and {parent}'s number is not on the list yet. Nothing will ring until it is added. | PENDING |
| robin.setup.not_allowed.hinglish | hinglish | Is pilot mein main sirf wahi number dial kar sakti hoon jo allow-list mein ho, aur {parent} ka number abhi list mein nahi hai. Jab tak jodta nahi, kuch nahi bajega. | PENDING |
| robin.setup.intro_started.en | en | I will make the introduction call to {parent} now. | PENDING |
| robin.setup.intro_started.hinglish | hinglish | Main abhi {parent} ko parichay wali call kar rahi hoon. | PENDING |
| robin.setup.intro_pending_line.en | en | The introduction call wording is waiting for approval, so I cannot make it yet. I have saved the setup. | PENDING |
| robin.setup.intro_pending_line.hinglish | hinglish | Parichay call ka wording abhi approval ka intezaar kar raha hai, isliye main abhi call nahi kar sakti. Setup save ho gaya hai. | PENDING |
| robin.setup.no_family.en | en | I have not set up {brand} for anyone yet. Say 'set up {brand} for my father' (or mother) to start. | PENDING |
| robin.setup.no_family.hinglish | hinglish | Maine abhi kisi ke liye {brand} set up nahi kiya. Shuru karne ke liye likhiye: 'set up {brand} for my father' (ya mother). | PENDING |
| robin.setup.cancelled.en | en | Okay, I stopped the setup. Nothing was saved except what you already sent. | PENDING |
| robin.setup.cancelled.hinglish | hinglish | Theek hai, setup rok diya. | PENDING |
| robin.intro.result.consented.en | en | {parent} heard the introduction. Switched on: {items}. Not switched on: {declined}. | PENDING |
| robin.intro.result.consented.hinglish | hinglish | {parent} ne parichay suna. Chalu: {items}. Chalu nahi: {declined}. | PENDING |
| robin.intro.result.declined.en | en | {parent} asked {brand} to stop. I will not call again. | PENDING |
| robin.intro.result.declined.hinglish | hinglish | {parent} ne {brand} ko rokne ko kaha. Main dobara phone nahi karungi. | PENDING |
| robin.intro.result.no_answer.en | en | {parent} did not pick up the introduction call. I will try once more later; nothing else will be started. | PENDING |
| robin.intro.result.no_answer.hinglish | hinglish | {parent} ne parichay call nahi uthayi. Main baad mein ek baar aur koshish karungi; aur kuch shuru nahi hoga. | PENDING |
| robin.intro.result.refused.en | en | I could not place the introduction call ({why}). | PENDING |
| robin.intro.result.refused.hinglish | hinglish | Parichay call nahi lag saki ({why}). | PENDING |
| robin.status.line.en | en | {parent}: {state}. Check-in at {time}. Today: {today}. Medicines: {meds}. Open alerts: {alerts}. | PENDING |
| robin.status.line.hinglish | hinglish | {parent}: {state}. Check-in {time} par. Aaj: {today}. Dawaiyan: {meds}. Khule alerts: {alerts}. | PENDING |
| robin.status.waiting_consent.en | en | waiting for their consent | PENDING |
| robin.status.waiting_consent.hinglish | hinglish | unki sahmati ka intezaar | PENDING |
| robin.status.active.en | en | active | PENDING |
| robin.status.active.hinglish | hinglish | chalu | PENDING |
| robin.status.paused.en | en | paused by {parent} | PENDING |
| robin.status.paused.hinglish | hinglish | {parent} ne roka hai | PENDING |
| robin.checkin.result.ok.en | en | {parent} checked in: {summary}. | PENDING |
| robin.checkin.result.ok.hinglish | hinglish | {parent} ne check-in kiya: {summary}. | PENDING |
| robin.checkin.result.concern.en | en | {parent} checked in, with something to note: {summary}. | PENDING |
| robin.checkin.result.concern.hinglish | hinglish | {parent} ne check-in kiya, dhyan dene wali baat: {summary}. | PENDING |
| robin.checkin.result.missed.en | en | {parent} did not pick up today's check-in after {n} tries. I am following your plan. | PENDING |
| robin.checkin.result.missed.hinglish | hinglish | {parent} ne aaj ka check-in {n} koshish ke baad bhi nahi uthaya. Main aapki yojana ke hisaab se aage badh rahi hoon. | PENDING |
| robin.checkin.result.fine_later.en | en | Update: {parent} is fine. They spoke to me just now. | PENDING |
| robin.checkin.result.fine_later.hinglish | hinglish | Update: {parent} theek hain. Unhone abhi mujhse baat ki. | PENDING |
| robin.callnow.started.en | en | Calling {parent} now for a check-in. I will tell you how it goes. | PENDING |
| robin.callnow.started.hinglish | hinglish | Main abhi {parent} ko check-in ke liye phone kar rahi hoon. Kya hua, aapko bataungi. | PENDING |
| robin.callnow.refused.en | en | I cannot call {parent} now ({why}). | PENDING |
| robin.callnow.refused.hinglish | hinglish | Main abhi {parent} ko phone nahi kar sakti ({why}). | PENDING |
| robin.digest.daily.en | en | Today with {parent}: {summary} | PENDING |
| robin.digest.daily.hinglish | hinglish | Aaj {parent} ke saath: {summary} | PENDING |
| robin.digest.weekly.en | en | This week with {parent}: {summary} | PENDING |
| robin.digest.weekly.hinglish | hinglish | Is hafte {parent} ke saath: {summary} | PENDING |
| robin.digest.empty.en | en | nothing to report | PENDING |
| robin.digest.empty.hinglish | hinglish | batane layak kuch nahi | PENDING |
| robin.med.added.en | en | Saved {medicine} at {times}. Stock about {days} days. I do not give medical advice; ask the doctor about any change. | PENDING |
| robin.med.added.hinglish | hinglish | {medicine} {times} par save ho gayi. Stock lagbhag {days} din. Main medical salaah nahi deti; kisi bhi badlav ke liye doctor se poochhiye. | PENDING |
| robin.med.confirm.en | en | I read this from the prescription: {list}. Save these reminders? yes or no. Please check the names and times; I cannot judge doses. | PENDING |
| robin.med.confirm.hinglish | hinglish | Prescription se maine yeh padha: {list}. Kya yeh reminders save karun? yes ya no. Naam aur samay dekh lijiye; main dose ka faisla nahi kar sakti. | PENDING |
| robin.med.confirm_saved.en | en | Saved {n} medicine(s). | PENDING |
| robin.med.confirm_saved.hinglish | hinglish | {n} dawai save ho gayi. | PENDING |
| robin.med.confirm_dropped.en | en | Okay, I did not save anything. | PENDING |
| robin.med.confirm_dropped.hinglish | hinglish | Theek hai, kuch save nahi kiya. | PENDING |
| robin.med.rx_unreadable.en | en | I could not read the medicines or their times on that photo, so I saved nothing. You can add one yourself: add medicine <name> <dose> at 8am, 8pm. | PENDING |
| robin.med.rx_unreadable.hinglish | hinglish | Us photo mein dawai ya unke samay padh nahi paayi, isliye kuch save nahi kiya. Aap khud jod sakte hain: add medicine <naam> <dose> at 8am, 8pm. | PENDING |
| robin.med.rx_partial.en | en | I could not read the times for: {list}. Those are not in the list above; add them yourself if you want reminders. | PENDING |
| robin.med.rx_partial.hinglish | hinglish | In ke samay padh nahi paayi: {list}. Yeh upar ki list mein nahi hain; reminders chahiye to khud jodiye. | PENDING |
| robin.med.rx_nothing_open.en | en | There is no prescription waiting for your answer. | PENDING |
| robin.med.rx_nothing_open.hinglish | hinglish | Abhi koi prescription aapke jawab ka intezaar nahi kar rahi. | PENDING |
| robin.med.ordered_ack.en | en | Noted that {medicine} is ordered. I do not order or pay for anything. When it arrives, send the count: pills left <name> <number>. | PENDING |
| robin.med.ordered_ack.hinglish | hinglish | Note kar liya ki {medicine} order ho gayi. Main kuch order ya payment nahi karti. Aane par ginti bhejiye: pills left <naam> <sankhya>. | PENDING |
| robin.med.format.en | en | To add a medicine write: add medicine <name> <dose> at 8am, 8pm, <strips> strips of <pills> bought <date>. Example: add medicine Amlodipine 5mg at 8am strips 2 of 10 bought 2026-11-01. | PENDING |
| robin.med.format.hinglish | hinglish | Dawai jodne ke liye likhiye: add medicine <naam> <dose> at 8am, 8pm strips 2 of 10 bought 2026-11-01. | PENDING |
| robin.med.list_item.en | en | {medicine} {dose} at {times}: about {days} days left | PENDING |
| robin.med.list_item.hinglish | hinglish | {medicine} {dose} {times} par: lagbhag {days} din bachi | PENDING |
| robin.med.list_empty.en | en | No medicines saved for {parent}. | PENDING |
| robin.med.list_empty.hinglish | hinglish | {parent} ke liye koi dawai save nahi hai. | PENDING |
| robin.med.removed.en | en | Removed {medicine}. | PENDING |
| robin.med.removed.hinglish | hinglish | {medicine} hata di. | PENDING |
| robin.med.not_found.en | en | I could not find that medicine. | PENDING |
| robin.med.not_found.hinglish | hinglish | Yeh dawai nahi mili. | PENDING |
| robin.med.missed.en | en | {parent} did not take {medicine} ({time}). | PENDING |
| robin.med.missed.hinglish | hinglish | {parent} ne {medicine} ({time}) nahi li. | PENDING |
| robin.med.refill.en | en | {medicine} has about {days} days of stock left. Time to buy more. Ask the doctor if the prescription needs a change. | PENDING |
| robin.med.refill.hinglish | hinglish | {medicine} ka stock lagbhag {days} din ka bacha hai. Aur kharidne ka samay. Prescription badalni ho to doctor se poochhiye. | PENDING |
| robin.med.paused.en | en | Medicine reminders are paused until {until}. | PENDING |
| robin.med.paused.hinglish | hinglish | Dawai ke reminders {until} tak ruke hain. | PENDING |
| robin.med.resumed.en | en | Medicine reminders are back on. | PENDING |
| robin.med.resumed.hinglish | hinglish | Dawai ke reminders phir chalu. | PENDING |
| robin.med.consent_missing.en | en | {parent} has not agreed to medicine reminders yet, so I saved the schedule but will not call about it. | PENDING |
| robin.med.consent_missing.hinglish | hinglish | {parent} ne abhi dawai ke reminders ke liye haan nahi kaha, isliye schedule save kiya hai par uske liye phone nahi karungi. | PENDING |
| robin.alert.head.watch.en | en | Heads up about {parent}: {why} | PENDING |
| robin.alert.head.watch.hinglish | hinglish | {parent} ke baare mein dhyan dein: {why} | PENDING |
| robin.alert.head.high.en | en | Important: {parent}. {why} | PENDING |
| robin.alert.head.high.hinglish | hinglish | Zaroori: {parent}. {why} | PENDING |
| robin.alert.head.emergency.en | en | EMERGENCY: {parent}. {why} | PENDING |
| robin.alert.head.emergency.hinglish | hinglish | EMERGENCY: {parent}. {why} | PENDING |
| robin.alert.money_note.en | en | Money may be involved, so please check with {parent} yourself even if they say they are fine. | PENDING |
| robin.alert.money_note.hinglish | hinglish | Paise ka maamla ho sakta hai, isliye {parent} ke theek kehne par bhi aap khud unse baat kijiye. | PENDING |
| robin.alert.hint.en | en | Reply 'details' to see more, or 'I have it' to take over. | PENDING |
| robin.alert.hint.hinglish | hinglish | Zyada dekhne ke liye 'details' likhiye, ya sambhalne ke liye 'I have it'. | PENDING |
| robin.alert.details.en | en | Alert details: {why}. Scenario {scenario}. Level {tier}. Raised {at}. Steps so far: {steps}. | PENDING |
| robin.alert.details.hinglish | hinglish | Alert ka vivaran: {why}. Scenario {scenario}. Level {tier}. Samay {at}. Ab tak ke kadam: {steps}. | PENDING |
| robin.alert.safe.en | en | Marked safe. I have stopped everything for this alert. | PENDING |
| robin.alert.safe.hinglish | hinglish | Safe mark kar diya. Is alert ke liye sab kuch rok diya. | PENDING |
| robin.alert.taken.en | en | Okay, you have it. I have stopped calling. | PENDING |
| robin.alert.taken.hinglish | hinglish | Theek hai, aap sambhal rahe hain. Maine phone karna rok diya. | PENDING |
| robin.alert.parent_fine.en | en | {parent} says they are fine. I have stopped calling. | PENDING |
| robin.alert.parent_fine.hinglish | hinglish | {parent} kehte hain ki wo theek hain. Maine phone karna rok diya. | PENDING |
| robin.alert.call_parent.en | en | Call {parent} on {phone}. I will keep going on my plan until you tap Mark safe or write 'I have it'. | PENDING |
| robin.alert.call_parent.hinglish | hinglish | {parent} ko {phone} par phone kijiye. Jab tak aap Mark safe na dabayein ya 'I have it' na likhein, main apni yojana par chalti rahungi. | PENDING |
| robin.alert.join_started.en | en | I am calling you now and will connect you with {parent}. | PENDING |
| robin.alert.join_started.hinglish | hinglish | Main abhi aapko phone kar rahi hoon aur {parent} se jod dungi. | PENDING |
| robin.alert.join_refused.en | en | I could not set up the joined call ({why}). | PENDING |
| robin.alert.join_refused.hinglish | hinglish | Joined call nahi ban saki ({why}). | PENDING |
| robin.alert.unknown.en | en | I could not find that alert; it may have ended already. | PENDING |
| robin.alert.unknown.hinglish | hinglish | Yeh alert nahi mila; shayad khatam ho chuka hai. | PENDING |
| robin.alert.followup.en | en | Still open: {why}. I have called {n} time(s). | PENDING |
| robin.alert.followup.hinglish | hinglish | Abhi bhi khula hai: {why}. Maine {n} baar phone kiya hai. | PENDING |
| robin.alert.flood_summary.en | en | Many alerts today about {parent} ({n} so far). To keep your phone usable I will not message each new minor one; they stay in 'what {brand} did today'. An EMERGENCY or an SOS is always sent at once. | PENDING |
| robin.alert.flood_summary.hinglish | hinglish | {parent} ke baare mein aaj bahut alerts aaye ({n} ab tak). Aapka phone na bhare, isliye chhote alerts par ab alag message nahi bhejungi; ve 'what {brand} did today' mein rahenge. EMERGENCY ya SOS hamesha turant bhejungi. | PENDING |
| robin.alert.second.en | en | {child} named you as a contact for {parent}. Alert: {why}. Please call {child} or {parent}. | PENDING |
| robin.alert.second.hinglish | hinglish | {child} ne aapko {parent} ke sampark ke roop mein bataya hai. Alert: {why}. Kripya {child} ya {parent} ko phone kijiye. | PENDING |
| robin.sos.child.en | en | SOS: {parent} pressed the help button{loc}. I am ringing you now. {brand} cannot call 112 for you; please call {parent}, and call 112 if needed. | PENDING |
| robin.sos.child.hinglish | hinglish | SOS: {parent} ne madad ka button dabaya{loc}. Main abhi aapko phone kar rahi hoon. Main 112 nahi laga sakti; kripya {parent} ko phone kijiye, aur zaroorat ho to 112. | PENDING |
| robin.sos.loc.en | en |  (location: {lat}, {lon}) | PENDING |
| robin.sos.loc.hinglish | hinglish |  (jagah: {lat}, {lon}) | PENDING |
| robin.sos.second.en | en | SOS for {parent} (named by {child}): {parent} pressed the help button{loc}. Please call {child} or {parent} now. | PENDING |
| robin.sos.second.hinglish | hinglish | {parent} ke liye SOS ({child} ne aapka naam diya hai): {parent} ne madad ka button dabaya{loc}. Kripya abhi {child} ya {parent} ko phone kijiye. | PENDING |
| robin.safeword.set.en | en | Family safe word saved (only a scrambled version is kept; I cannot read it back). Share it with {parent} in person. | PENDING |
| robin.safeword.set.hinglish | hinglish | Family safe word save ho gaya (sirf scrambled roop mein; main use wapas padh nahi sakti). Use {parent} ko aamne-saamne batayein. | PENDING |
| robin.safeword.format.en | en | To set it write: safe word <word>. Do it together with {parent}, in person. Do not send it on a call. | PENDING |
| robin.safeword.format.hinglish | hinglish | Set karne ke liye likhiye: safe word <shabd>. {parent} ke saath mil kar karein. Call par mat bhejiye. | PENDING |
| robin.safeword.none.en | en | No safe word set yet. | PENDING |
| robin.safeword.none.hinglish | hinglish | Abhi koi safe word set nahi hai. | PENDING |
| robin.safeword.check_ok.en | en | That matches the safe word. | PENDING |
| robin.safeword.check_ok.hinglish | hinglish | Yeh safe word se match karta hai. | PENDING |
| robin.safeword.check_no.en | en | That does not match. | PENDING |
| robin.safeword.check_no.hinglish | hinglish | Yeh match nahi karta. | PENDING |
| robin.view.child.head.en | en | What {brand} sees and does for {parent} (the same page {parent} can see): | PENDING |
| robin.view.child.head.hinglish | hinglish | {brand} {parent} ke liye kya dekhti aur karti hai (wahi page jo {parent} bhi dekh sakte hain): | PENDING |
| robin.view.item.on.en | en | - {item}: agreed on {when} ({source}) | PENDING |
| robin.view.item.on.hinglish | hinglish | - {item}: {when} ko haan ({source}) | PENDING |
| robin.view.item.off.en | en | - {item}: not agreed | PENDING |
| robin.view.item.off.hinglish | hinglish | - {item}: haan nahi | PENDING |
| robin.view.item.withdrawn.en | en | - {item}: withdrawn on {when} | PENDING |
| robin.view.item.withdrawn.hinglish | hinglish | - {item}: {when} ko wapas liya | PENDING |
| robin.view.never.en | en | {brand} never records calls, never reads messages, notifications or SMS from this part, never asks for OTP, PIN or passwords, and never pays. | PENDING |
| robin.view.never.hinglish | hinglish | {brand} call record nahi karti, messages, notifications ya SMS nahi padhti, OTP, PIN ya password nahi maangti, aur paise nahi bhejti. | PENDING |
| robin.view.shared.en | en | Shared with {child}: {shared} | PENDING |
| robin.view.shared.hinglish | hinglish | {child} ko dikhta hai: {shared} | PENDING |
| robin.view.audit_head.en | en | What {brand} did today: | PENDING |
| robin.view.audit_head.hinglish | hinglish | {brand} ne aaj kya kiya: | PENDING |
| robin.view.audit_empty.en | en | Nothing yet. | PENDING |
| robin.view.audit_empty.hinglish | hinglish | Abhi tak kuch nahi. | PENDING |
| robin.pause.parent.en | en | {parent} asked {brand} to stop, so I stopped everything. Please talk to {parent}. Only {parent} can start the sensitive items again; you can ask them. | PENDING |
| robin.pause.parent.hinglish | hinglish | {parent} ne {brand} ko rokne ko kaha, isliye maine sab kuch rok diya. Kripya {parent} se baat kijiye. Sensitive cheezein sirf {parent} dobara chalu kar sakte hain; aap unse keh sakte hain. | PENDING |
| robin.resume.parent.en | en | {parent} resumed {brand}. | PENDING |
| robin.resume.parent.hinglish | hinglish | {parent} ne {brand} dobara shuru kiya. | PENDING |
| robin.consent.withdrawn.en | en | {parent} withdrew consent for {item}. I stopped that. | PENDING |
| robin.consent.withdrawn.hinglish | hinglish | {parent} ne {item} ki sahmati wapas li. Maine wo band kar diya. | PENDING |
| robin.consent.given.en | en | {parent} agreed to {item}. | PENDING |
| robin.consent.given.hinglish | hinglish | {parent} ne {item} ke liye haan kaha. | PENDING |
| robin.cmd.checkin_set.en | en | Check-in time for {parent} is now {time}. | PENDING |
| robin.cmd.checkin_set.hinglish | hinglish | {parent} ka check-in samay ab {time} hai. | PENDING |
| robin.cmd.sensitivity_set.en | en | Sensitivity is now {level}. This changes how soon I alert you, not what is looked at. | PENDING |
| robin.cmd.sensitivity_set.hinglish | hinglish | Sensitivity ab {level} hai. Isse alert kitni jaldi aaye wo badalta hai, kya dekha jaata hai wo nahi. | PENDING |
| robin.cmd.delete_ask.en | en | This deletes everything {brand} holds about {parent} and the family setup: consents, medicines, check-ins and the log. Reply DELETE to confirm. | PENDING |
| robin.cmd.delete_ask.hinglish | hinglish | Isse {parent} aur family setup ke baare mein {brand} ke paas jo kuch hai sab hat jayega: sahmatiyan, dawaiyan, check-in aur log. Confirm karne ke liye DELETE likhiye. | PENDING |
| robin.cmd.delete_done.en | en | Deleted everything about {parent}. | PENDING |
| robin.cmd.delete_done.hinglish | hinglish | {parent} ke baare mein sab kuch hata diya. | PENDING |
| robin.cmd.delete_cancelled.en | en | Okay, nothing was deleted. | PENDING |
| robin.cmd.delete_cancelled.hinglish | hinglish | Theek hai, kuch nahi hata. | PENDING |
| robin.cmd.help.en | en | {brand} commands: set up {brand} for my father / parent status / call papa / add medicine ... / medicines / remove medicine <name> / check-in time 9am / sensitivity calm/balanced/careful / what does {brand} see / pause reminders 3 days / resume reminders / digest / pair phone for papa / what is on / what {brand} did today / delete everything for my parent | PENDING |
| robin.cmd.help.hinglish | hinglish | {brand} ke commands: set up {brand} for my father / parent status / call papa / add medicine ... / medicines / remove medicine <naam> / check-in time 9am / sensitivity calm/balanced/careful / what does {brand} see / pause reminders 3 days / resume reminders / digest / safe word <shabd> / pair phone for papa / what is on / what {brand} did today / delete everything for my parent | PENDING |
| robin.cmd.care_active.en | en | I am keeping calls and nudges quiet right now. | PENDING |
| robin.cmd.care_active.hinglish | hinglish | Main abhi calls aur nudges shaant rakh rahi hoon. | PENDING |
| robin.pair.steps.en | en | To connect {parent}'s phone: 1) install the {brand} app on {parent}'s phone. 2) Open it, press and hold the {brand} name, and enter this code: {code}. Or open this link on {parent}'s phone and tap Connect: {link}. The code works once and expires in {minutes} minutes. {parent} does not have to type anything. Do not share the code with anyone else. | PENDING |
| robin.pair.steps.hinglish | hinglish | {parent} ka phone jodne ke liye: 1) {parent} ke phone par {brand} app lagayiye. 2) Use kholkar {brand} naam ko dabaye rakhiye aur yeh code daliye: {code}. Ya {parent} ke phone par yeh link kholkar Connect dabaiye: {link}. Code sirf ek baar chalta hai aur {minutes} minute mein khatam ho jata hai. {parent} ko kuch type nahi karna padega. Code kisi aur ko mat dijiye. | PENDING |
| robin.pair.off.en | en | Phone pairing is not switched on yet, so I cannot make a code. | PENDING |
| robin.pair.off.hinglish | hinglish | Phone jodna abhi chalu nahi hai, isliye main code nahi bana sakti. | PENDING |
| robin.pair.not_ready.en | en | First finish setting up {brand} for {parent} (their number is needed), then ask me again. | PENDING |
| robin.pair.not_ready.hinglish | hinglish | Pehle {parent} ke liye {brand} ka setup poora kijiye (unka number chahiye), phir dobara poochhiye. | PENDING |
| robin.inbox.head.en | en | {brand} could not reach your phone earlier and held these messages for you: | PENDING |
| robin.inbox.head.hinglish | hinglish | {brand} pehle aapke phone tak nahi pahunch saki aur ye messages aapke liye rakh liye the: | PENDING |
| robin.cmd.escalation_unnamed.en | en | No second contact was named, so I will not contact anyone else. | PENDING |
| robin.cmd.escalation_unnamed.hinglish | hinglish | Koi doosra sampark nahi diya gaya, isliye main kisi aur ko contact nahi karungi. | PENDING |
| robin.consent.request_sent.en | en | I noted your request for {item}. {parent} asked {brand} to stop, so only {parent} can start it again. | PENDING |
| robin.consent.request_sent.hinglish | hinglish | Maine {item} ke liye aapki request note kar li. {parent} ne {brand} ko rokne ko kaha hai, isliye ise sirf {parent} dobara chalu kar sakte hain. | PENDING |
| robin.consent.parent_paused.en | en | {parent} asked {brand} to stop, so I cannot switch {item} on. I noted your request; please talk to {parent}. | PENDING |
| robin.consent.parent_paused.hinglish | hinglish | {parent} ne {brand} ko rokne ko kaha hai, isliye main {item} chalu nahi kar sakti. Aapki request note kar li; kripya {parent} se baat kijiye. | PENDING |
| robin.guardian.set.en | en | Guardian basis recorded for {parent}: {basis}. {brand} does not verify it; it is flagged for legal review. | PENDING |
| robin.guardian.set.hinglish | hinglish | {parent} ke liye guardian karan darj: {basis}. {brand} ise verify nahi karti; legal review ke liye flag hai. | PENDING |
| robin.guardian.bad_basis.en | en | Please write the basis, for example: guardian mode <short reason such as court order or medical incapacity>. | PENDING |
| robin.guardian.bad_basis.hinglish | hinglish | Kripya karan likhiye, jaise: guardian mode <chhota karan, jaise court order ya medical incapacity>. | PENDING |
| robin.guardian.off.en | en | Guardian mode is off for {parent}. | PENDING |
| robin.guardian.off.hinglish | hinglish | {parent} ke liye guardian mode band. | PENDING |
| robin.consent.admin_given.en | en | Recorded: you agreed to {item} on behalf of {parent}. {parent} is told and can stop me at any time. | PENDING |
| robin.consent.admin_given.hinglish | hinglish | Note kiya: aapne {parent} ki taraf se {item} ke liye haan kaha. {parent} ko bataya jayega aur wo kabhi bhi mujhe rok sakte hain. | PENDING |
| robin.coadmin.added.en | en | Added a co-admin. They get the same alerts and can use the same commands. | PENDING |
| robin.coadmin.added.hinglish | hinglish | Co-admin jod diya. Unhe wahi alerts milenge. | PENDING |
| robin.gm.on.en | en | Good-morning messages for {parent} are on. | PENDING |
| robin.gm.on.hinglish | hinglish | {parent} ke liye good-morning message chalu. | PENDING |
| robin.gm.off.en | en | Good-morning messages for {parent} are off. | PENDING |
| robin.gm.off.hinglish | hinglish | {parent} ke liye good-morning message band. | PENDING |
| robin.fest.on.en | en | Festival greetings for {parent} are on. | PENDING |
| robin.fest.on.hinglish | hinglish | {parent} ke liye tyohaar ki shubhkamnayein chalu. | PENDING |
| robin.fest.off.en | en | Festival greetings for {parent} are off. | PENDING |
| robin.fest.off.hinglish | hinglish | {parent} ke liye tyohaar ki shubhkamnayein band. | PENDING |
| robin.enable.done.en | en | Switched on: {item}. {parent} will be told. | PENDING |
| robin.enable.done.hinglish | hinglish | Chalu kiya: {item}. {parent} ko bataya jayega. | PENDING |
| robin.enable.unknown.en | en | I do not know that item. Items: {items}. | PENDING |
| robin.enable.unknown.hinglish | hinglish | Yeh item mujhe nahi pata. Items: {items}. | PENDING |
| robin.missed.child_note.en | en | {who} called you but you missed it ({time}). They said: {summary}. | PENDING |
| robin.missed.child_note.hinglish | hinglish | {who} ne aapko phone kiya par aap utha nahi paye ({time}). Unhone kaha: {summary}. | PENDING |
| robin.missed.child_note_urgent.en | en | URGENT: {who} called you ({time}) and says it is an emergency. They said: {summary}. I am ringing you every {minutes} minutes (up to {tries} tries) until you answer. | PENDING |
| robin.missed.child_note_urgent.hinglish | hinglish | ZAROORI: {who} ne aapko phone kiya ({time}) aur kehte hain emergency hai. Unhone kaha: {summary}. Main aapko har {minutes} minute mein phone kar rahi hoon (zyada se zyada {tries} baar) jab tak aap na uthayein. | PENDING |
| robin.missed.unknown_caller.en | en | an unknown caller | PENDING |
| robin.missed.unknown_caller.hinglish | hinglish | ek anjaan caller | PENDING |
| robin.missed.no_summary.en | en | nothing clear | PENDING |
| robin.missed.no_summary.hinglish | hinglish | kuch saaf nahi | PENDING |
| robin.forward.ask.en | en | Optional: let {brand} answer when {who} cannot pick up. It needs call forwarding on the phone. Reply 'forwarding jio', 'forwarding airtel' or 'forwarding vi' for the steps. | PENDING |
| robin.forward.ask.hinglish | hinglish | Optional: jab {who} phone na utha payein to {brand} jawab de. Iske liye phone par call forwarding chahiye. Steps ke liye likhiye 'forwarding jio', 'forwarding airtel' ya 'forwarding vi'. | PENDING |
| robin.forward.codes.en | en | Forwarding for {who} on {carrier} (dial these on {who}'s phone, one at a time; the codes are standard but NOT verified on a real SIM [U]):
{codes}
To check: {status}. To undo everything: {cancel}.
{notes}
Then use 'test forwarding' to try it. | PENDING |
| robin.forward.codes.hinglish | hinglish | {carrier} par {who} ke phone ke liye forwarding (ye codes {who} ke phone se ek ek karke dial karein; codes standard hain par asli SIM par VERIFIED NAHI [U]):
{codes}
Check karne ke liye: {status}. Sab band karne ke liye: {cancel}.
{notes}
Phir 'test forwarding' likhiye. | PENDING |
| robin.forward.unknown_carrier.en | en | I know Jio, Airtel and Vi. Which one is it? | PENDING |
| robin.forward.unknown_carrier.hinglish | hinglish | Main Jio, Airtel aur Vi jaanti hoon. Kaun sa hai? | PENDING |
| robin.forward.unavailable.en | en | The number that answers forwarded calls is not set up yet, so I cannot give you codes. I have told the team. | PENDING |
| robin.forward.unavailable.hinglish | hinglish | Forwarded calls ka number abhi set nahi hai, isliye codes nahi de sakti. Team ko bata diya hai. | PENDING |
| robin.forward.test.en | en | To test forwarding (this is a supervised step, only with the founder's number during the pilot): 1) from another phone, ring {who}'s phone; 2) do not pick up; 3) after about {seconds} seconds {brand} should answer and ask who is calling; 4) say a name and 'no' to urgent; 5) {who} or you should get a message within a minute. Nothing is dialled by {brand} for this test. | PENDING |
| robin.forward.test.hinglish | hinglish | Forwarding test (supervised step, pilot mein sirf founder ke number par): 1) kisi doosre phone se {who} ke phone par call karein; 2) uthaiye mat; 3) lagbhag {seconds} second baad {brand} uthaye aur poochhe kaun bol raha hai; 4) naam boliye aur urgent par 'nahi'; 5) {who} ya aapko ek minute mein message milna chahiye. Is test mein {brand} khud koi call nahi karti. | PENDING |
| robin.authority.complaint.en | en | Draft for cybercrime.gov.in (check every fact before you submit it yourself): On {when}, {parent} may have been defrauded. What happened: {why}. Amount: {amount}. Please also call 1930 now and ask your bank to freeze the transaction. {brand} did not file anything and cannot. | PENDING |
| robin.authority.complaint.hinglish | hinglish | cybercrime.gov.in ke liye draft (khud submit karne se pehle har baat check kijiye): {when} ko {parent} ke saath dhokha hua ho sakta hai. Kya hua: {why}. Rakam: {amount}. Kripya abhi 1930 par phone kijiye aur bank se transaction freeze karne ko kahiye. {brand} ne kuch file nahi kiya aur nahi kar sakti. | PENDING |
| robin.authority.dry_run.en | en | DRY RUN (nothing was dialled): for {parent} the emergency desk would have called {who}. | PENDING |
| robin.authority.dry_run.hinglish | hinglish | DRY RUN (kuch dial nahi hua): {parent} ke liye emergency desk {who} ko phone karti. | PENDING |
| robin.authority.refused.en | en | The emergency desk did not contact the authorities for {parent}: {why}. | PENDING |
| robin.authority.refused.hinglish | hinglish | Emergency desk ne {parent} ke liye authorities ko phone nahi kiya: {why}. | PENDING |
| robin.authority.distress.en | en | {parent} may be in distress. I am not calling anyone official; please call {parent} yourself. This has been handed to the care protocol. | PENDING |
| robin.authority.distress.hinglish | hinglish | {parent} pareshan ho sakte hain. Main kisi sarkari number par phone nahi kar rahi; kripya {parent} ko khud phone kijiye. Yeh care protocol ko de diya gaya hai. | PENDING |
| robin.authority.countdown_child.en | en | In {seconds} seconds the emergency desk will contact the authorities for {parent} unless {parent} says they are fine or you tap Mark safe. | PENDING |
| robin.authority.countdown_child.hinglish | hinglish | {seconds} second mein emergency desk {parent} ke liye authorities ko phone karegi jab tak {parent} na kahein ki wo theek hain ya aap Mark safe na dabayein. | PENDING |
| robin.authority.set_address.en | en | Address saved for the emergency script. | PENDING |
| robin.authority.set_address.hinglish | hinglish | Emergency script ke liye pata save ho gaya. | PENDING |
| robin.authority.set_name.en | en | Parent name saved for the emergency script. | PENDING |
| robin.authority.set_name.hinglish | hinglish | Emergency script ke liye parent ka naam save ho gaya. | PENDING |
| robin.screen.child_note.en | en | Screened an unknown caller for {parent}: {verdict}. Reason: {why} | PENDING |
| robin.screen.child_note.hinglish | hinglish | {parent} ke liye anjaan caller ko screen kiya: {verdict}. Wajah: {why} | PENDING |
| robin.sum.yes.en | en | yes | PENDING |
| robin.sum.yes.hinglish | hinglish | haan | PENDING |
| robin.sum.no.en | en | no | PENDING |
| robin.sum.no.hinglish | hinglish | nahi | PENDING |
| robin.sum.unclear.en | en | no clear answer | PENDING |
| robin.sum.unclear.hinglish | hinglish | saaf jawab nahi | PENDING |
| robin.sum.ate.en | en | ate: {v} | PENDING |
| robin.sum.ate.hinglish | hinglish | khaya: {v} | PENDING |
| robin.sum.slept.en | en | slept well: {v} | PENDING |
| robin.sum.slept.hinglish | hinglish | neend achhi: {v} | PENDING |
| robin.sum.pain.en | en | pain: {v} | PENDING |
| robin.sum.pain.hinglish | hinglish | dard: {v} | PENDING |
| robin.sum.mood.en | en | mood: {v} | PENDING |
| robin.sum.mood.hinglish | hinglish | mann: {v} | PENDING |
| robin.sum.strange.en | en | strange call or money request: {v} | PENDING |
| robin.sum.strange.hinglish | hinglish | ajeeb call ya paise ki maang: {v} | PENDING |
| robin.sum.meds.en | en | medicines taken: {v} | PENDING |
| robin.sum.meds.hinglish | hinglish | dawai li: {v} | PENDING |
| robin.sum.answered_only.en | en | picked up the call | PENDING |
| robin.sum.answered_only.hinglish | hinglish | call uthayi | PENDING |
| robin.dg.checkins.en | en | {n} of {total} check-ins answered | PENDING |
| robin.dg.checkins.hinglish | hinglish | {total} mein se {n} check-in uthe | PENDING |
| robin.dg.concerns.en | en | {n} check-in(s) with something to note | PENDING |
| robin.dg.concerns.hinglish | hinglish | {n} check-in mein dhyan dene wali baat | PENDING |
| robin.dg.meds.en | en | medicine reminders: {taken} taken, {missed} missed | PENDING |
| robin.dg.meds.hinglish | hinglish | dawai reminders: {taken} li, {missed} chhooti | PENDING |
| robin.dg.alerts.en | en | {n} alert(s) | PENDING |
| robin.dg.alerts.hinglish | hinglish | {n} alert | PENDING |

## Festival names used by `fest.greeting` (data file `friday/robin/data/festivals.json`; PENDING; a festival is sent only when its date is marked verified)

| Id | en | hinglish | hi | Date | Verified |
|---|---|---|---|---|---|
| new_year | New Year | Naya Saal | नया साल | 01-01 | yes |
| sankranti_pongal | Makar Sankranti and Pongal | Makar Sankranti aur Pongal | मकर संक्रांति और पोंगल | 01-14 | yes |
| republic_day | Republic Day | Ganatantra Diwas | गणतंत्र दिवस | 01-26 | yes |
| baisakhi | Baisakhi | Baisakhi | बैसाखी | 04-14 | yes |
| independence_day | Independence Day | Swatantrata Diwas | स्वतंत्रता दिवस | 08-15 | yes |
| gandhi_jayanti | Gandhi Jayanti | Gandhi Jayanti | गांधी जयंती | 10-02 | yes |
| christmas | Christmas | Christmas | क्रिसमस | 12-25 | yes |
| ugadi | Ugadi | Ugadi | उगादी | 2026-03-19 | NO |
| holi | Holi | Holi | होली | 2026-03-04 | NO |
| eid_ul_fitr | Eid | Eid | ईद | 2026-03-20 | NO |
| onam | Onam | Onam | ओणम | 2026-08-26 | NO |
| raksha_bandhan | Raksha Bandhan | Raksha Bandhan | रक्षा बंधन | 2026-08-28 | NO |
| ganesh_chaturthi | Ganesh Chaturthi | Ganesh Chaturthi | गणेश चतुर्थी | 2026-09-14 | NO |
| navratri | Navratri | Navratri | नवरात्रि | 2026-10-11 | NO |
| dussehra | Dussehra | Dussehra | दशहरा | 2026-10-20 | NO |
| diwali | Diwali | Diwali | दिवाली | 2026-11-08 | NO |
| guru_nanak_jayanti | Guru Nanak Jayanti | Guru Nanak Jayanti | गुरु नानक जयंती | 2026-11-24 | NO |
