# ruff: noqa: E501
"""Wording of the care protocol. PENDING_FOUNDER_APPROVAL: every line below is a first draft.

Rules the wording follows (docs/CARE_PROTOCOL.md): 2 to 4 short lines; mirror the user's language
(English, Roman Hinglish, Devanagari Hindi); the direct safety question is asked once; Tele-MANAS
14416 and 112 are named; no diagnosis, no arguing with feelings, no pep talk, no promise about how
things will turn out, no product, work or shopping talk. Friday cannot send a message to anyone:
the user sends the draft. Helpline numbers (14416, 112) must be verified against the official
pages by the founder before launch; a mental-health professional should review all of this.

Tests check structure and forbidden words, never the exact wording.
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True
LANGUAGES = ("en", "hinglish", "hi")
DEFAULT_LANGUAGE = "hinglish"

HELPLINE = "14416"
EMERGENCY = "112"

LINES: dict[str, dict[str, str]] = {
    # first reply to a HIGH message: acknowledge, ask the direct question ONCE, helplines, offer a draft
    "high_first": {
        "en": "I'm really sorry you're hurting this much. I'm here with you.\nDo you have thoughts of hurting yourself?\nYou can call Tele-MANAS on 14416 any time: free, 24x7, in Hindi and English. If you might act on it right now, call 112.\nIf you want, tell me who you trust and I'll draft a message for you to send.",
        "hinglish": "Mujhe bahut afsos hai ki aap itna dard sah rahe hain. Main yahin hoon.\nKya aapko khud ko nuksan pahunchane ke khayal aa rahe hain?\nTele-MANAS 14416 par kabhi bhi call kar sakte hain: free, 24x7, Hindi aur English mein. Abhi khatra lage toh 112.\nChahein toh bataiye aap kis par bharosa karte hain, main unke liye ek message likh dungi; bhejna aapko hoga.",
        "hi": "मुझे बहुत अफ़सोस है कि आप इतना दर्द सह रहे हैं। मैं यहीं हूँ।\nक्या आपको खुद को नुकसान पहुँचाने के ख़याल आ रहे हैं?\nTele-MANAS 14416 पर कभी भी कॉल कर सकते हैं: मुफ़्त, 24x7, हिंदी और अंग्रेज़ी में। अभी ख़तरा लगे तो 112।\nचाहें तो बताइए आप किस पर भरोसा करते हैं, मैं उनके लिए एक मैसेज लिख दूँगी; भेजना आपको होगा।",
    },
    # the user answered the safety question with yes
    "answer_yes": {
        "en": "Thank you for telling me.\nPlease call Tele-MANAS on 14416 now (free, 24x7), or 112 if you might act on it.",
        "hinglish": "Bataane ke liye shukriya.\nPlease abhi Tele-MANAS 14416 par call kijiye (free, 24x7), ya agar aap kuch kar baithne wale hain toh 112.",
        "hi": "बताने के लिए शुक्रिया।\nकृपया अभी Tele-MANAS 14416 पर कॉल कीजिए (मुफ़्त, 24x7), या अगर आप कुछ कर बैठने वाले हैं तो 112।",
    },
    # the user answered the safety question with no
    "answer_no": {
        "en": "Thank you for telling me. I'm staying right here.\nIf that changes, 14416 is free any hour, and 112 if you're in danger.",
        "hinglish": "Bataane ke liye shukriya. Main yahin hoon.\nAgar yeh badle toh 14416 kabhi bhi free hai, aur khatre mein 112.",
        "hi": "बताने के लिए शुक्रिया। मैं यहीं हूँ।\nअगर यह बदले तो 14416 कभी भी मुफ़्त है, और ख़तरे में 112।",
    },
    # the user keeps writing in distress (the question is not asked again)
    "stay": {
        "en": "I'm here, and I'm listening.\n14416 is free any hour, and 112 if you're in danger.",
        "hinglish": "Main yahin hoon, aur sun rahi hoon.\n14416 kabhi bhi free hai, aur khatre mein 112.",
        "hi": "मैं यहीं हूँ, और सुन रही हूँ।\n14416 कभी भी मुफ़्त है, और ख़तरे में 112।",
    },
    "person_ask": {
        "en": "Who would you like to reach? Tell me their name, or who they are to you (a sister, a friend), and I'll write it out.",
        "hinglish": "Aap kisse baat karna chahenge? Unka naam batayein, ya woh aapke kaun hain (behen, dost), main likh dungi.",
        "hi": "आप किससे बात करना चाहेंगे? उनका नाम बताइए, या वे आपके कौन हैं (बहन, दोस्त), मैं लिख दूँगी।",
    },
    # {who}: what the user called the person; {body}: the draft
    "draft": {
        "en": "Here is a draft you can send to {who}:\n\"{body}\"\nI can't send it myself: please copy it and send it from your phone. Want me to change anything?",
        "hinglish": "{who} ko bhejne ke liye draft:\n\"{body}\"\nMain ise khud nahi bhej sakti: aap ise copy karke apne phone se bhejiye. Kuch badalna hai?",
        "hi": "{who} को भेजने के लिए ड्राफ़्ट:\n\"{body}\"\nमैं इसे खुद नहीं भेज सकती: आप इसे कॉपी करके अपने फ़ोन से भेजिए। कुछ बदलना है?",
    },
    # {name}: " Riya" or empty
    "draft_body": {
        "en": "Hi{name}, I'm having a really hard time right now and I don't want to be alone. Can you call me or come over?",
        "hinglish": "Hi{name}, abhi mera din bahut bhaari hai aur mujhe kisi ka saath chahiye. Kya aap mujhe call kar sakte hain ya aa sakte hain?",
        "hi": "नमस्ते{name}, अभी मेरा समय बहुत भारी है और मुझे किसी का साथ चाहिए। क्या आप मुझे कॉल कर सकते हैं या आ सकते हैं?",
    },
    # offered only when a call to the user's OWN allow-listed number is possible
    "offer_call": {
        "en": "If you'd like to hear a voice, I can call your own number. Say \"call me\" and I'll try.",
        "hinglish": "Agar aap kisi ki aawaz sunna chahein, main aapke apne number par call kar sakti hoon. 'Call karo' kahein toh koshish karti hoon.",
        "hi": "अगर आप किसी की आवाज़ सुनना चाहें, मैं आपके अपने नंबर पर कॉल कर सकती हूँ। 'कॉल करो' कहें तो कोशिश करती हूँ।",
    },
    "call_placed": {
        "en": "Okay, I'm calling your number now.",
        "hinglish": "Theek hai, abhi aapke number par call kar rahi hoon.",
        "hi": "ठीक है, अभी आपके नंबर पर कॉल कर रही हूँ।",
    },
    "call_unavailable": {
        "en": "I can't place that call from here right now. Tele-MANAS 14416 is free, any hour.",
        "hinglish": "Main abhi yahan se woh call nahi laga sakti. Tele-MANAS 14416 kabhi bhi free hai.",
        "hi": "मैं अभी यहाँ से वह कॉल नहीं लगा सकती। Tele-MANAS 14416 कभी भी मुफ़्त है।",
    },
    # a message that is not about the distress while the protocol is active (two variants, alternated)
    "hold_a": {
        "en": "I'm keeping everything else paused for now. Tell me when you feel steadier. I'm here, and 14416 is free any hour.",
        "hinglish": "Abhi baaki sab kuch maine roka hua hai. Jab aap thoda theek mehsoos karein, bata dijiye. Main yahin hoon, aur 14416 kabhi bhi free hai.",
        "hi": "अभी बाकी सब कुछ मैंने रोक रखा है। जब आप थोड़ा ठीक महसूस करें, बता दीजिए। मैं यहीं हूँ, और 14416 कभी भी मुफ़्त है।",
    },
    "hold_b": {
        "en": "Still here. Everything else can wait. Say \"I'm okay\" whenever you want to carry on.",
        "hinglish": "Main yahin hoon. Baaki sab ruk sakta hai. Jab aage badhna ho, \"main theek hoon\" bol dijiye.",
        "hi": "मैं यहीं हूँ। बाकी सब रुक सकता है। जब आगे बढ़ना हो, \"मैं ठीक हूँ\" कह दीजिए।",
    },
    "steady": {
        "en": "I'm glad. I'm here if you want to talk again, and 14416 is free any hour.",
        "hinglish": "Mujhe achha laga. Phir baat karni ho toh main yahin hoon, aur 14416 kabhi bhi free hai.",
        "hi": "मुझे अच्छा लगा। फिर बात करनी हो तो मैं यहीं हूँ, और 14416 कभी भी मुफ़्त है।",
    },
    "stopped": {
        "en": "Okay, I won't check in. I'm here whenever you want me, and 14416 is free any hour.",
        "hinglish": "Theek hai, main message nahi karungi. Jab chahein main yahin hoon, aur 14416 kabhi bhi free hai.",
        "hi": "ठीक है, मैं मैसेज नहीं करूँगी। जब चाहें मैं यहीं हूँ, और 14416 कभी भी मुफ़्त है।",
    },
    # one plain line when an open request is paused
    "paused_task": {
        "en": "I've paused your open request. Nothing will be booked or paid until you tell me to carry on.",
        "hinglish": "Maine aapka khula hua kaam roka hai. Jab tak aap na kahein, kuch book ya pay nahi hoga.",
        "hi": "मैंने आपका खुला हुआ काम रोक दिया है। जब तक आप न कहें, कुछ बुक या पे नहीं होगा।",
    },
    "checkin_same_day": {
        "en": "Hi, just checking in. How are you doing now? I'm here if you want to talk.",
        "hinglish": "Hi, bas haal poochh rahi thi. Ab aap kaisa mehsoos kar rahe hain? Baat karni ho toh main yahin hoon.",
        "hi": "नमस्ते, बस हाल पूछ रही थी। अब आप कैसा महसूस कर रहे हैं? बात करनी हो तो मैं यहीं हूँ।",
    },
    "checkin_morning": {
        "en": "Good morning. I was thinking of you. How are you feeling today? I'm here if you want to talk, and 14416 is free any hour.",
        "hinglish": "Good morning. Aapka khayal aaya. Aaj aap kaisa mehsoos kar rahe hain? Baat karni ho toh main yahin hoon, aur 14416 kabhi bhi free hai.",
        "hi": "सुप्रभात। आपका ख़याल आया। आज आप कैसा महसूस कर रहे हैं? बात करनी हो तो मैं यहीं हूँ, और 14416 कभी भी मुफ़्त है।",
    },
    # ELEVATED: acknowledge, one gentle question, the helpline once
    "elevated_first": {
        "en": "That sounds really heavy, and I'm glad you told me.\nWhat has been the hardest part today?\nIf it ever feels like too much, Tele-MANAS 14416 is free, 24x7, in Hindi and English.",
        "hinglish": "Yeh sach mein bahut bhaari lagta hai, aur aapne bataya, achha kiya.\nAaj sabse mushkil kya raha?\nAgar kabhi bahut zyada lage, Tele-MANAS 14416 free hai, 24x7, Hindi aur English mein.",
        "hi": "यह सच में बहुत भारी लगता है, और आपने बताया, अच्छा किया।\nआज सबसे मुश्किल क्या रहा?\nअगर कभी बहुत ज़्यादा लगे, Tele-MANAS 14416 मुफ़्त है, 24x7, हिंदी और अंग्रेज़ी में।",
    },
    "elevated_again": {
        "en": "I hear you. That's a lot to carry.\nWhat's on your mind right now?",
        "hinglish": "Main sun rahi hoon. Yeh bahut zyada hai.\nAbhi aapke mann mein kya chal raha hai?",
        "hi": "मैं सुन रही हूँ। यह बहुत ज़्यादा है।\nअभी आपके मन में क्या चल रहा है?",
    },
    # the distress is about someone else
    "third_party": {
        "en": "That sounds hard, for them and for you.\nIf they are in danger right now, please call 112. Tele-MANAS 14416 (free, 24x7) can also advise you on how to support them.\nI'm here if you want to talk about it.",
        "hinglish": "Yeh un dono ke liye mushkil lagta hai, unke liye bhi aur aapke liye bhi.\nAgar woh abhi khatre mein hain toh please 112. Tele-MANAS 14416 (free, 24x7) bhi bata sakta hai unhe kaise sambhalein.\nBaat karni ho toh main yahin hoon.",
        "hi": "यह उनके लिए भी मुश्किल लगता है और आपके लिए भी।\nअगर वे अभी ख़तरे में हैं तो कृपया 112। Tele-MANAS 14416 (मुफ़्त, 24x7) भी बता सकता है कि उन्हें कैसे सँभालें।\nबात करनी हो तो मैं यहीं हूँ।",
    },

    # ---- sharing with the family (asked ONCE; the default is that nothing is shared) ----
    "family_ask": {
        "en": "Would you like me to tell your family to call you? I will not share what you wrote. Please reply yes or no.",
        "hinglish": "Kya main aapke parivar ko aapko call karne ke liye bata dun? Aapne jo likha, woh main nahi bataungi. Kripya haan ya nahi kahiye.",
        "hi": "क्या मैं आपके परिवार को आपको कॉल करने के लिए बता दूँ? आपने जो लिखा, वह मैं नहीं बताऊँगी। कृपया हाँ या नहीं कहिए।",
    },
    "family_yes": {
        "en": "Okay. I will tell them to call you. I will not share what you wrote.",
        "hinglish": "Theek hai. Main unhe aapko call karne ke liye bata dungi. Aapne jo likha, woh nahi bataungi.",
        "hi": "ठीक है। मैं उन्हें आपको कॉल करने के लिए बता दूँगी। आपने जो लिखा, वह नहीं बताऊँगी।",
    },
    "family_no": {
        "en": "Okay. I will not tell anyone. I am here, and 14416 is free any hour.",
        "hinglish": "Theek hai. Main kisi ko nahi bataungi. Main yahin hoon, aur 14416 kabhi bhi free hai.",
        "hi": "ठीक है। मैं किसी को नहीं बताऊँगी। मैं यहीं हूँ, और 14416 कभी भी मुफ़्त है।",
    },
    # the ONLY text that may ever go to the other family member ({name}: the speaker's display name)
    "family_line": {
        "en": "{name} may need you, please call.",
        "hinglish": "{name} ko aapki zarurat ho sakti hai, please call kijiye.",
        "hi": "{name} को आपकी ज़रूरत हो सकती है, कृपया कॉल कीजिए।",
    },
    # ---- ELDER speaker (60+): short plain sentences, no jargon ----
    "high_first_elder": {
        "en": "I am sorry you are in so much pain. I am here with you.\nAre you thinking of hurting yourself?\nPlease call 14416. It is free, day and night. If you are in danger now, call 112.",
        "hinglish": "Mujhe afsos hai ki aap itne dukhi hain. Main aapke saath hoon.\nKya aap apne aap ko nuksan pahunchane ka soch rahe hain?\nKripya 14416 par call kijiye. Yeh muft hai, din raat. Abhi khatra ho toh 112.",
        "hi": "मुझे अफ़सोस है कि आप इतने दुखी हैं। मैं आपके साथ हूँ।\nक्या आप खुद को नुकसान पहुँचाने की सोच रहे हैं?\nकृपया 14416 पर कॉल कीजिए। यह मुफ़्त है, दिन-रात। अभी ख़तरा हो तो 112।",
    },
    "answer_yes_elder": {
        "en": "Thank you for telling me.\nPlease call 14416 now. It is free. If you are in danger, call 112.\nI am here.",
        "hinglish": "Bataane ke liye shukriya.\nAbhi 14416 par call kijiye. Yeh muft hai. Khatra ho toh 112.\nMain yahin hoon.",
        "hi": "बताने के लिए शुक्रिया।\nअभी 14416 पर कॉल कीजिए। यह मुफ़्त है। ख़तरा हो तो 112।\nमैं यहीं हूँ।",
    },
    "answer_no_elder": {
        "en": "Thank you. I am here.\nIf your heart feels heavy, call 14416. It is free.",
        "hinglish": "Shukriya. Main yahin hoon.\nAgar mann bhaari ho, 14416 par call kijiye. Yeh muft hai.",
        "hi": "शुक्रिया। मैं यहीं हूँ।\nअगर मन भारी हो, 14416 पर कॉल कीजिए। यह मुफ़्त है।",
    },
    "stay_elder": {
        "en": "I am here. I am listening.\n14416 is free, day and night. If you are in danger, call 112.",
        "hinglish": "Main yahin hoon. Main sun rahi hoon.\n14416 muft hai, din raat. Khatra ho toh 112.",
        "hi": "मैं यहीं हूँ। मैं सुन रही हूँ।\n14416 मुफ़्त है, दिन-रात। ख़तरा हो तो 112।",
    },
    "elevated_first_elder": {
        "en": "That sounds very heavy. You did well to tell me.\nHow are you feeling right now?\nIf you need, call 14416. It is free.",
        "hinglish": "Yeh bahut bhaari lagta hai. Aapne bataya, achha kiya.\nAbhi aap kaisa mehsoos kar rahe hain?\nZarurat ho toh 14416 par call kijiye. Yeh muft hai.",
        "hi": "यह बहुत भारी लगता है। आपने बताया, अच्छा किया।\nअभी आप कैसा महसूस कर रहे हैं?\nज़रूरत हो तो 14416 पर कॉल कीजिए। यह मुफ़्त है।",
    },
    "checkin_same_day_elder": {
        "en": "Namaste. I am asking how you are. How are you now? I am here.",
        "hinglish": "Namaste. Main haal poochh rahi hoon. Ab aap kaise hain? Main yahin hoon.",
        "hi": "नमस्ते। मैं हाल पूछ रही हूँ। अब आप कैसे हैं? मैं यहीं हूँ।",
    },
    "checkin_morning_elder": {
        "en": "Good morning. I was thinking of you. How are you today? I am here. 14416 is free.",
        "hinglish": "Suprabhat. Aapka khayal aaya. Aaj aap kaise hain? Main yahin hoon. 14416 muft hai.",
        "hi": "सुप्रभात। आपका ख़याल आया। आज आप कैसे हैं? मैं यहीं हूँ। 14416 मुफ़्त है।",
    },
}


def _lang(lang: str | None) -> str:
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def line(key: str, lang: str | None = None, *, elder: bool = False, **fmt: str) -> str:
    """The wording; for an ELDER speaker the ``<key>_elder`` variant when one exists."""
    if elder and f"{key}_elder" in LINES:
        key = f"{key}_elder"
    text = LINES[key][_lang(lang)]
    return text.format(**fmt) if fmt else text


def ids() -> list[str]:
    """Every id the founder must approve (one id = the line in all three languages)."""
    return [f"care.line.{k}" for k in LINES]


def count_texts() -> int:
    return sum(len(v) for v in LINES.values())
