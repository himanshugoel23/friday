"""ALL new user-facing text of the consumer-call flow (W1). PENDING_FOUNDER_APPROVAL.

Hear-before-change (CLAUDE.md rule 3): nothing in this module may be shown to a real user until the
founder has approved the wording. Every line is keyed; code never builds user text anywhere else.
Languages: "hinglish" (default) and "en". Placeholders use ``{name}`` format fields.

The spoken lines on the call itself (disclosure, stop, opt-out, "are you a bot?") belong to W2 and
to the approved playbooks; only the apology key for a wrong-number call is named here so that W2
can pick it up.
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

DEFAULT_LANGUAGE = "hinglish"

LINES: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- refusals and routes
    "refuse_threat": {
        "hinglish": "Yeh call main nahi kar sakti, kyunki isme kisi ko dhamki ya daraane ki baat hai.",
        "en": "I can't make this call, because it involves threatening or scaring someone.",
    },
    "refuse_harassment": {
        "hinglish": "Main kisi ko baar baar pareshan karne wali call nahi karti.",
        "en": "I don't make calls meant to harass someone.",
    },
    "refuse_scam": {
        "hinglish": "Main OTP, PIN ya paise nikalwane jaisi call nahi karti. Yeh call nahi hogi.",
        "en": "I don't make calls that ask for OTPs, PINs or money under false pretences.",
    },
    "refuse_prank": {
        "hinglish": "Mazak ya prank wali call main nahi karti. Kuch kaam ki baat ho to bataiye.",
        "en": "I don't make prank calls. Tell me if there is something real to sort out.",
    },
    "refuse_impersonation": {
        "hinglish": "Main kisi aur ban ke ya aapki jagah aapki awaaz mein call nahi karti. "
        "Main hamesha apni pehchaan batati hoon: aapki assistant.",
        "en": "I never pretend to be someone else or speak as you. I always say I am your assistant.",
    },
    "refuse_minor": {
        "hinglish": "Bachchon ko akele call karna main nahi karti. Unke mummy-papa ya guardian "
        "ko call kar sakti hoon.",
        "en": "I don't call children directly. I can call a parent or guardian instead.",
    },
    "refuse_emergency_number": {
        "hinglish": "Emergency number par main call nahi karti. Zaroorat ho to khud 112 dial kijiye.",
        "en": "I never call emergency numbers. If it is urgent, please dial 112 yourself.",
    },
    "route_emergency": {
        "hinglish": "Yeh emergency lag rahi hai. Please abhi khud 112 dial kijiye. Main emergency "
        "services ko call nahi kar sakti.",
        "en": "This sounds like an emergency. Please dial 112 yourself now. I can't call "
        "emergency services.",
    },
    "route_medical": {
        "hinglish": "Dawai ya ilaaj ki salah main nahi de sakti. Main doctor ke clinic ko call karke "
        "appointment le sakti hoon.",
        "en": "I can't give medical advice. I can call a clinic and book an appointment.",
    },
    "route_legal": {
        "hinglish": "Kanooni salah main nahi de sakti. Main kisi vakeel ke office se time maang "
        "sakti hoon.",
        "en": "I can't give legal advice. I can ask a lawyer's office for an appointment.",
    },
    "route_selfharm": {
        "hinglish": "Aap jo keh rahe hain woh mere liye bahut zaroori hai. Please kisi apne se abhi "
        "baat kijiye, ya kisi helpline se. Main yahin hoon. (Helpline number: founder verify "
        "karke jodega.)",
        "en": "What you said matters a lot. Please talk to someone you trust right now, or to a "
        "helpline. I am here. (Helpline number to be added by the founder after verifying it.)",
    },
    "deny_dnc": {
        "hinglish": "Is number ne kaha hai ki unhe Friday se call nahi chahiye, isliye main call "
        "nahi karungi.",
        "en": "This number asked not to be called by Friday, so I won't call it.",
    },
    "deny_invalid_number": {
        "hinglish": "Yeh number sahi nahi lag raha. Kya aap poora number phir se bhej sakte hain?",
        "en": "That number doesn't look right. Could you send the full number again?",
    },
    "deny_killed": {
        "hinglish": "Abhi calls band hain. Thodi der baad koshish kijiye.",
        "en": "Calls are switched off right now. Please try again a little later.",
    },
    "deny_kind_off": {
        "hinglish": "Is tarah ki call abhi available nahi hai.",
        "en": "This kind of call isn't available right now.",
    },
    "deny_user_blocked": {
        "hinglish": "Aapke account se calls abhi rok di gayi hain. Support se baat kijiye.",
        "en": "Calls from your account are paused. Please talk to support.",
    },
    "deny_cap_user_calls": {
        "hinglish": "Aaj ki calls ki limit poori ho gayi. Kal phir se try kar sakte hain.",
        "en": "Today's call limit is reached. You can try again tomorrow.",
    },
    "deny_cap_user_minutes": {
        "hinglish": "Aaj ke calling minutes poore ho gaye. Kal phir se try kar sakte hain.",
        "en": "Today's calling minutes are used up. You can try again tomorrow.",
    },
    "deny_cap_number": {
        "hinglish": "Is number par haal hi mein kaafi calls ja chuki hain, isliye abhi call nahi "
        "karungi.",
        "en": "This number has had enough calls lately, so I won't call it now.",
    },
    "deny_generic": {
        "hinglish": "Yeh call abhi nahi ho sakti.",
        "en": "I can't make this call right now.",
    },
    "deny_test_mode": {
        "hinglish": "Test mode mein sirf approved numbers par call hoti hai.",
        "en": "In test mode I only call approved numbers.",
    },
    "deny_group_too_big": {
        "hinglish": "Ek saath itne logon ko call nahi kar sakti. Chhota group bhejiye.",
        "en": "That is too many people for one go. Please send a smaller group.",
    },
    # ---------------------------------------------------------------- one question at a time
    "ask_callee": {
        "hinglish": "Kisko call karni hai? Naam ya number bata dijiye.",
        "en": "Who should I call? Please tell me the name or number.",
    },
    "ask_purpose": {
        "hinglish": "Unse kya kehna ya puchhna hai?",
        "en": "What should I tell or ask them?",
    },
    "ask_details": {
        "hinglish": "Thoda aur bataiye: kya problem hai (amount, kab se, kis bare mein)?",
        "en": "A little more detail please: what is the problem (amount, since when, about what)?",
    },
    "ask_limits": {
        "hinglish": "Kitne paise tak ya kab tak ka kaam chalega? Meri limit yeh rahegi.",
        "en": "What is the most you want to pay, or the latest date? I will stay within it.",
    },
    "ask_number": {
        "hinglish": "{name} ka number bhej dijiye (ya contact card share kijiye).",
        "en": "Please send {name}'s number (or share the contact card).",
    },
    "ask_which_contact": {
        "hinglish": "Kaun sa {ref}? {options}",
        "en": "Which {ref}? {options}",
    },
    "confirm_number_back": {
        "hinglish": "{name} ka number {masked} par khatam hota hai. Sahi hai? Haan likhiye to "
        "call aage badhegi.",
        "en": "{name}'s number ends in {masked}. Is that right? Reply yes to go ahead.",
    },
    "ask_group_members": {
        "hinglish": "Kin kin ko call karni hai? Naam ya number likhiye.",
        "en": "Whom should I call? Please list the names or numbers.",
    },
    # ---------------------------------------------------------------- approval message
    "approval_header": {
        "hinglish": "Call ka plan yeh hai. Approve karne se pehle dekh lijiye:",
        "en": "Here is the call plan. Please check it before approving:",
    },
    "approval_to": {"hinglish": "Kisko: {name}", "en": "To: {name}"},
    "approval_goal": {"hinglish": "Maqsad: {goal}", "en": "Goal: {goal}"},
    "approval_say": {"hinglish": "Zaroor kahungi: {items}", "en": "Will say: {items}"},
    "approval_ask": {"hinglish": "Puchhungi: {items}", "en": "Will ask: {items}"},
    "approval_not_say": {"hinglish": "Nahi kahungi: {items}", "en": "Won't say: {items}"},
    "approval_limits": {"hinglish": "Meri limit: {items}", "en": "My limits: {items}"},
    "approval_when": {"hinglish": "Kab: {when}", "en": "When: {when}"},
    "approval_opening": {
        "hinglish": 'Call ki pehli line: "{line}"',
        "en": 'Opening line: "{line}"',
    },
    "approval_footer": {
        "hinglish": "Approve dabane par hi call hogi. Badalna ho to Edit dabaiye.",
        "en": "The call happens only after you press Approve. Press Edit to change anything.",
    },
    "btn_approve": {"hinglish": "Approve", "en": "Approve"},
    "btn_edit": {"hinglish": "Edit", "en": "Edit"},
    "btn_cancel": {"hinglish": "Cancel", "en": "Cancel"},
    "approval_stale": {
        "hinglish": "Plan badal gaya tha, isliye purana approval nahi chalega. Naya plan:",
        "en": "The plan changed, so the earlier approval no longer counts. New plan:",
    },
    "approval_cancelled": {"hinglish": "Theek hai, call cancel.", "en": "Okay, call cancelled."},
    "approval_edit_prompt": {
        "hinglish": "Kya badalna hai? Bata dijiye, main naya plan bhejti hoon.",
        "en": "What should change? Tell me and I'll send a new plan.",
    },
    # ---------------------------------------------------------------- scheduling notices
    "sched_later": {
        "hinglish": "{name} ko abhi call karna theek nahi (calling time). Main {when} par call "
        "karungi.",
        "en": "This is outside the calling hours for {name}. I'll call at {when}.",
    },
    "sched_retry": {
        "hinglish": "{name} ne phone nahi uthaya. Main {when} par phir try karungi.",
        "en": "{name} didn't pick up. I'll try again at {when}.",
    },
    "sched_callback": {
        "hinglish": "{name} ne baad mein call karne ko kaha. Main {when} par call karungi.",
        "en": "{name} asked me to call later. I'll call at {when}.",
    },
    "sched_group_started": {
        "hinglish": "{n} logon ko call kar rahi hoon. Sab ka jawab ek saath bataungi.",
        "en": "Calling {n} people. I'll send you all the answers together.",
    },
    # ---------------------------------------------------------------- reports
    "report_completed": {
        "hinglish": "{name} se baat ho gayi. {summary}",
        "en": "I spoke to {name}. {summary}",
    },
    "report_partial": {
        "hinglish": "{name} se baat hui, par kaam poora nahi hua. {summary}",
        "en": "I spoke to {name} but it isn't fully done. {summary}",
    },
    "report_declined": {
        "hinglish": "{name} ne mana kar diya. {summary}",
        "en": "{name} said no. {summary}",
    },
    "report_no_answer_final": {
        "hinglish": "{name} ne {n} baar try karne par bhi phone nahi uthaya. Ab main ruk rahi hoon.",
        "en": "{name} didn't pick up after {n} tries. I'm stopping here.",
    },
    "report_busy_final": {
        "hinglish": "{name} ka number {n} baar busy mila. Ab main ruk rahi hoon.",
        "en": "{name}'s line was busy {n} times. I'm stopping here.",
    },
    "report_voicemail_final": {
        "hinglish": "{name} ka phone voicemail par gaya. Koi message nahi chhoda.",
        "en": "{name}'s phone went to voicemail. I did not leave a message.",
    },
    "report_failed_final": {
        "hinglish": "{name} ko call lag nahi paayi (technical dikkat). Aap chahein to phir try karun?",
        "en": "I couldn't connect to {name} (technical problem). Shall I try again?",
    },
    "report_callback_later": {
        "hinglish": "{name} ne kaha baad mein call karo. {summary}",
        "en": "{name} asked me to call back later. {summary}",
    },
    "report_safety_stop": {
        "hinglish": "Call beech mein rok di gayi. {summary}",
        "en": "I ended the call early. {summary}",
    },
    "report_opted_out": {
        "hinglish": "{name} ne kaha ki dobara call na karein. Maine unka number hamesha ke liye "
        "block kar diya hai; ab Friday unhe call nahi karegi.",
        "en": "{name} asked not to be called again. I've blocked the number; Friday won't call "
        "them again.",
    },
    "report_wrong_person": {
        "hinglish": "Maaf kijiye, galat insaan ko call lag gayi ({name}). Maine unse maafi maang "
        "li aur unka number ab aage kabhi call nahi hoga.",
        "en": "Sorry, I reached the wrong person ({name}). I apologised to them and the number "
        "will never be called again.",
    },
    "report_commitments": {
        "hinglish": "Inme aapki haan chahiye: {items}",
        "en": "These need your OK: {items}",
    },
    "report_commitments_done": {
        "hinglish": "Tay hua: {items}",
        "en": "Agreed: {items}",
    },
    "report_answers": {"hinglish": "Unhone bataya: {items}", "en": "They said: {items}"},
    "report_group_header": {
        "hinglish": "Group ka jawab ({done} me se {answered} ne bataya):",
        "en": "Group result ({answered} of {done} answered):",
    },
    "report_group_line": {"hinglish": "{name}: {summary}", "en": "{name}: {summary}"},
    "btn_done": {"hinglish": "Theek hai", "en": "Done"},
    "btn_call_again": {"hinglish": "Phir call karo", "en": "Call again"},
    "btn_call_later": {"hinglish": "Baad mein call", "en": "Call later"},
    "btn_message": {"hinglish": "Message bhejo", "en": "Send a message"},
    "btn_reminder": {"hinglish": "Reminder lagao", "en": "Add reminder"},
    "btn_ok_commit": {"hinglish": "Haan, chalega", "en": "Yes, go ahead"},
    "btn_no_commit": {"hinglish": "Nahi", "en": "No"},
    "btn_stop": {"hinglish": "Dobara nahi", "en": "Don't call again"},
    "btn_delete_rec": {"hinglish": "Recording hatao", "en": "Delete recording"},
    "recording_deleted": {
        "hinglish": "Recording hata di gayi.",
        "en": "The recording has been deleted.",
    },
    "stop_calling_ack": {
        "hinglish": "Theek hai, {name} ko dobara call nahi karungi.",
        "en": "Okay, I won't call {name} again.",
    },
    "word_completed": {"hinglish": "baat ho gayi", "en": "spoke"},
    "word_partial": {"hinglish": "adhoori baat", "en": "partly done"},
    "word_declined": {"hinglish": "mana kiya", "en": "said no"},
    "word_no_answer": {"hinglish": "phone nahi uthaya", "en": "no answer"},
    "word_busy": {"hinglish": "busy mila", "en": "busy"},
    "word_voicemail": {"hinglish": "voicemail", "en": "voicemail"},
    "word_callback_later": {
        "hinglish": "baad mein call karne ko kaha",
        "en": "asked for a call later",
    },
    "word_wrong_person": {"hinglish": "galat insaan", "en": "wrong person"},
    "word_opted_out": {"hinglish": "dobara call nahi chahte", "en": "asked not to be called"},
    "word_safety_stop": {"hinglish": "call rok di", "en": "call stopped"},
    "word_failed": {"hinglish": "call lagi nahi", "en": "could not connect"},
    "word_skipped": {"hinglish": "call nahi ki gayi", "en": "not called"},
    "word_pending": {"hinglish": "abhi baaki hai", "en": "still pending"},
    # ---------------------------------------------------------------- spoken, for W2 to pick up
    "spoken_apology_wrong_person": {
        "hinglish": "Maaf kijiye, galat number lag gaya. Aapko pareshan karne ke liye sorry. "
        "Dobara call nahi aayegi.",
        "en": "I'm sorry, I reached the wrong number. Sorry for the trouble. You won't be "
        "called again.",
    },
}


def line(key: str, lang: str = DEFAULT_LANGUAGE, **fmt: object) -> str:
    """Text for ``key`` in ``lang`` (falls back to Hinglish), formatted. KeyError on a bad key."""
    variants = LINES[key]
    text = variants.get(lang) or variants[DEFAULT_LANGUAGE]
    return text.format(**fmt) if fmt else text
