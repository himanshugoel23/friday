# Live call engine (W2): how Friday talks during a consumer call

Package `friday/liveagent/`, tests `tests/liveagent/`. Status: built and simulated offline; NO real call was
placed. Every spoken line is `PENDING_FOUNDER_APPROVAL` (hear-before-change): nothing here may go live before the
founder hears the audio. The repo is public: all personas, names and numbers in the simulation are invented.

## 1. The idea: bounded moves
The conversation is a closed set of MOVES: `greet, disclose, state_purpose, ask, answer_from_brief, confirm,
handle_objection, hold_wait, voicemail, close, stop` (`moves.py`). Each move has fixed lines per relationship
(family_elder, friend, provider, customer_care, official, unknown, business) and language (Hinglish, Hindi, English)
in ONE module, `lines.py`. A policy only picks the next move and fills slots from the brief; code verifies every slot.

* `MovePolicy` interface. Default `RuleBasedPolicy` (deterministic, `rules.py`). `LLMMovePolicy` wraps a `MoveModel`
  (fake in tests): hard stops, the AI answer, secrets, money, commitments, "who is this", questions about the user and
  waiting are decided by code BEFORE the model is asked; the model's reply must be a legal move (transition table), a
  known variant, with slots that come from the brief or the callee's words. Anything else falls back to the rules, and
  the model can never end the call. The model never sees `private_facts` or the money ceiling.
* Transition table (`TRANSITIONS`): nothing but stop/hold/voicemail may follow `greet`; `disclose` is always next.
  Voicemail only for personal callees; IVR navigation only for institutions.
* First seconds: `greet` + `disclose` are spoken in one utterance ("Hello ... Main Friday bol rahi hoon, <user> ki
  virtual assistant"), then the callee answers, then `state_purpose` + the first must_say/question.
* Fully generated line mode (`EngineConfig(generated_lines=True)` and a `LineModel`): OFF by default, only for a few
  low-risk variants, and the text passes exactly the same guards; on any violation the fixed line is used.

## 2. Guard rules (`slotguard.py`, reusing `friday/brain/guards.py` and `friday/core/safety.py`)
1. Slots: `user`=brief.user_name, `purpose`=goal, `message`=must_say item, `question`=ask_list item, `fact`=a
   shareable value, `value`=the callee's own words or an allowed time. Anything else is rejected.
2. No ungrounded number/time/amount (`ungrounded_numbers`); the money ceiling is never spoken (`max_amount_inr` is not
   in the grounding text). Only constant number: 112 in the distress line.
3. `private_facts` never spoken: value, distinctive words or digits (unless the same text is also shareable).
4. No OTP/PIN/CVV/password/card (check_speech); the callee asking for one gets the fixed refusal; asked twice -> polite end.
5. `must_not_say` phrases never appear. Friday never claims to be the user, never denies being an AI.
6. Commitment guard (`judge_commitment`): a time, visit, booking or amount is accepted only if it is inside the brief
   limits (`allowed_times`, `allowed_commitments`, `max_amount_inr`); otherwise `needs_user_approval` and the line is
   "I will confirm with <user> and call back". Friday never agrees to pay. Open-ended "pakka?" is never accepted.
7. Repeat guard: the same line is never spoken twice in a row (alternate wordings; none left -> loop escalation).
   Acknowledgements rotate (never one of the last two).
8. Questions about the user: only a fact whose key matches the topic AND is marked shareable is answered; everything
   else gets the fixed deflection and is added to `needs_user_approval` (kind `question`).
9. Hard stops (stop calling, wrong number, distress, hostile, "I don't talk to bots / give me a human") end the call with
   one fixed polite line, nothing asked after it.

## 3. Engine (`engine.py`)
`LiveCallEngine(policy, config, user_channel, line_model, clock).run(brief, callee, telephony) -> LiveCallResult`
(outcome, masked transcript, audit events, pending line ids used). Handles voicemail (fixed short message only if
`voicemail_allowed`, personal callees only), carrier "switched off" messages, IVR (single digit from "press N for X"
matched to the goal, never an identifier, step cap), hold queue (silent, capped by `limits.max_hold_seconds`), "ek minute"
requests, line drops, max duration (`limits.max_call_seconds`), turn cap, loop detector, language switch on request,
and the warm-transfer hook: `UserChannel.ask_user(question, timeout_s)` (fake in tests); a reply passes the secret/number/
repeat guards; no reply in time -> call-back + `needs_user_approval`. Telephony is the `TelephonyPort`; the only adapter
is `sarvam_adapter.SarvamLegPort` (wraps the existing `SarvamCallLeg`, voice stack untouched).

## 4. Simulation
`uv run python -m friday.liveagent.simulation` plays 37 personas x 3 languages (111 runs) and prints a pass/fail table;
`tests/liveagent/test_simulation.py` runs the same set as a regression. Invariants per run: disclosure before content,
no private leak, no ungrounded number, no unsafe speech, never the user, never denies AI, truthful AI answer, hard stop in
one turn, no commitments outside limits, only safe keys, duration cap, no repeated line, masked transcript, valid line ids.
`python -m friday.liveagent lines [--lang hi]` lists every pending line (also the audio review kit input).

## 5. How W1's brief plugs in
`contracts.py` holds stand-ins named exactly like the W1 plan. W1's `CallBrief` needs these EXTRA fields (or an adapter):
`user_name`, `goal_spoken` (one short sentence in the call language, approved with the draft), `callee_name`,
`voicemail_allowed`; `limits` needs `allowed_times`, `allowed_commitments` (`time|visit|booking`), `max_amount_inr`,
`max_call_seconds`, `max_hold_seconds`. `shareable_facts` values must be short sentences in the call language.
W1 consumes `CallOutcome` (status, summary, commitments, needs_user_approval, next_actions); retries, do-not-call
registry writes (`DO_NOT_CALL`/`WRONG_NUMBER` + next_actions), the approval and the report are W1's.

## 6. Unverified (nothing here touched a real voice, callee or network)
Real voices and pronunciation of every line (Roman Hinglish and Devanagari Hindi; names in Devanagari not applied),
real callees, STT accuracy on Hindi/Hinglish numbers and times, latency of the extra pieces (lines can be pre-rendered:
they are fixed), Sarvam leg behaviour through the adapter (only a fake leg is tested), real IVR menus, voicemail beep
detection on a live line, hold-music classification, the regex intent banks on real speech (tuned on invented examples),
Hindi register for elders (aap/ji) and gender-neutral phrasing of the user, TRAI/DLT and recording rules (W1 legal map).

## 7. Decisions for the founder
1. Approve (or change) the lines below by listening to audio; start with `disclose.*`, `stop.*`, `voicemail.message`.
2. The distress line speaks 112; confirm. 3. Voicemail message allowed per call only (default off), never for institutions.
4. "Are you AI?" answer says "AI assistant" while the intro says "virtual assistant" (matches the 10 Oct decision).
5. Greeting for elders uses the name from the brief (e.g. "Mummy ji"): W1 must collect how the user addresses them.
6. Language mirroring is NOT built (language comes from the brief; only an explicit "English please" switches).

## 8. Pending lines (every one is PENDING_FOUNDER_APPROVAL)
Id format `<move>.<variant>.<relationship>.<language>.<n>`; `*` = default for every relationship. Total: 297.

| id | text |
|---|---|
| `answer_from_brief.defer.*.hinglish.0` | Yeh mujhe pata nahi hai, main {user} se puchhkar aapko bata dungi. |
| `answer_from_brief.defer.*.hinglish.1` | Is baare mein main abhi kuch keh nahi sakti, {user} se puchhkar batati hoon. |
| `answer_from_brief.defer.*.hi.0` | यह मुझे पता नहीं है, मैं {user} से पूछकर आपको बता दूँगी। |
| `answer_from_brief.defer.*.hi.1` | इस बारे में मैं अभी कुछ कह नहीं सकती, {user} से पूछकर बताती हूँ। |
| `answer_from_brief.defer.*.en.0` | I do not know that, I will check with {user} and let you know. |
| `answer_from_brief.defer.*.en.1` | I cannot say anything about that right now, I will ask {user} and tell you. |
| `answer_from_brief.defer.family_elder.hinglish.0` | Yeh main {user} se puchhkar aapko bata dungi, ji. |
| `answer_from_brief.defer.family_elder.hinglish.1` | Main {user} se poochh kar aapko call karke bata dungi. |
| `answer_from_brief.defer.family_elder.hi.0` | यह मैं {user} से पूछकर आपको बता दूँगी, जी। |
| `answer_from_brief.defer.family_elder.hi.1` | मैं {user} से पूछकर आपको कॉल करके बता दूँगी। |
| `answer_from_brief.defer.family_elder.en.0` | I will ask {user} and let you know. |
| `answer_from_brief.defer.family_elder.en.1` | I will check with {user} and call you back with that. |
| `answer_from_brief.fact.*.hinglish.0` | Mujhe bas itna pata hai: {fact} |
| `answer_from_brief.fact.*.hinglish.1` | {ack}, mere paas yeh jaankari hai: {fact} |
| `answer_from_brief.fact.*.hi.0` | मुझे बस इतना पता है: {fact} |
| `answer_from_brief.fact.*.hi.1` | {ack}, मेरे पास यह जानकारी है: {fact} |
| `answer_from_brief.fact.*.en.0` | All I know is this: {fact} |
| `answer_from_brief.fact.*.en.1` | {ack}, here is what I have: {fact} |
| `answer_from_brief.secret.*.hinglish.0` | Maaf kijiye, main OTP, PIN ya card jaisi details kisi ko nahi batati. Ye mere paas hain bhi nahi. |
| `answer_from_brief.secret.*.hinglish.1` | Yeh details main nahi de sakti, na hi OTP ya PIN kisi ko batati hoon. |
| `answer_from_brief.secret.*.hi.0` | माफ़ कीजिए, मैं ओटीपी, पिन या कार्ड जैसी जानकारी किसी को नहीं बताती। ये मेरे पास हैं भी नहीं। |
| `answer_from_brief.secret.*.hi.1` | यह जानकारी मैं नहीं दे सकती, न ही ओटीपी या पिन किसी को बताती हूँ। |
| `answer_from_brief.secret.*.en.0` | Sorry, I never share an OTP, PIN or card details with anyone. I do not have them either. |
| `answer_from_brief.secret.*.en.1` | I cannot give those details, and I never share OTPs or PINs. |
| `ask.followup.*.hinglish.0` | Maaf kijiye, bas ek baar phir: {question} |
| `ask.followup.*.hinglish.1` | Main dobara poochh leti hoon: {question} |
| `ask.followup.*.hi.0` | माफ़ कीजिए, बस एक बार फिर: {question} |
| `ask.followup.*.hi.1` | मैं दोबारा पूछ लेती हूँ: {question} |
| `ask.followup.*.en.0` | Sorry, just once more: {question} |
| `ask.followup.*.en.1` | Let me ask again: {question} |
| `ask.question.*.hinglish.0` | Mujhe ek cheez poochhni thi: {question} |
| `ask.question.*.hinglish.1` | Ek sawaal hai: {question} |
| `ask.question.*.hi.0` | मुझे एक चीज़ पूछनी थी: {question} |
| `ask.question.*.hi.1` | एक सवाल है: {question} |
| `ask.question.*.en.0` | I had one thing to ask: {question} |
| `ask.question.*.en.1` | One question: {question} |
| `ask.question.family_elder.hinglish.0` | Ek baat poochhni thi: {question} |
| `ask.question.family_elder.hinglish.1` | Aapse ek cheez poochh sakti hoon? {question} |
| `ask.question.family_elder.hi.0` | एक बात पूछनी थी: {question} |
| `ask.question.family_elder.hi.1` | आपसे एक चीज़ पूछ सकती हूँ? {question} |
| `ask.question.family_elder.en.0` | May I ask you one thing? {question} |
| `ask.question.family_elder.en.1` | I wanted to ask: {question} |
| `close.busy_later.*.hinglish.0` | Theek hai, main tab dobara call karti hoon. Shukriya aapka. |
| `close.busy_later.*.hinglish.1` | Koi baat nahi, tab baat karte hain. Namaste. |
| `close.busy_later.*.hi.0` | ठीक है, मैं तब दोबारा कॉल करती हूँ। शुक्रिया आपका। |
| `close.busy_later.*.hi.1` | कोई बात नहीं, तब बात करते हैं। नमस्ते। |
| `close.busy_later.*.en.0` | Alright, I will call again then. Thank you. |
| `close.busy_later.*.en.1` | No problem, we will talk then. Goodbye. |
| `close.declined.*.hinglish.0` | Bilkul theek hai. Aapka time dene ke liye shukriya. Namaste. |
| `close.declined.*.hinglish.1` | Koi baat nahi ji. Shukriya, namaste. |
| `close.declined.*.hi.0` | बिल्कुल ठीक है। आपका समय देने के लिए शुक्रिया। नमस्ते। |
| `close.declined.*.hi.1` | कोई बात नहीं जी। शुक्रिया, नमस्ते। |
| `close.declined.*.en.0` | That is perfectly fine. Thank you for your time. Goodbye. |
| `close.declined.*.en.1` | No problem at all. Thank you, goodbye. |
| `close.done.*.hinglish.0` | Bahut shukriya, aapka time dene ke liye. Main {user} ko bata deti hoon. Namaste. |
| `close.done.*.hinglish.1` | Shukriya, aapki madad ke liye. {user} ko bata dungi. Namaste. |
| `close.done.*.hi.0` | बहुत शुक्रिया, आपका समय देने के लिए। मैं {user} को बता देती हूँ। नमस्ते। |
| `close.done.*.hi.1` | शुक्रिया, आपकी मदद के लिए। {user} को बता दूँगी। नमस्ते। |
| `close.done.*.en.0` | Thank you very much for your time. I will let {user} know. Goodbye. |
| `close.done.*.en.1` | Thanks for your help. I will tell {user}. Goodbye. |
| `close.done.family_elder.hinglish.0` | Bahut bahut shukriya. Apna khayal rakhiye. Namaste. |
| `close.done.family_elder.hinglish.1` | Shukriya ji, main {user} ko bata deti hoon. Apna khayal rakhiye. |
| `close.done.family_elder.hi.0` | बहुत बहुत शुक्रिया। अपना ख़याल रखिए। नमस्ते। |
| `close.done.family_elder.hi.1` | शुक्रिया जी, मैं {user} को बता देती हूँ। अपना ख़याल रखिए। |
| `close.done.family_elder.en.0` | Thank you so much. Please take care. Goodbye. |
| `close.done.family_elder.en.1` | Thank you, I will tell {user}. Please take care. |
| `close.done.friend.hinglish.0` | Thanks yaar, main {user} ko bata deti hoon. Bye! |
| `close.done.friend.hinglish.1` | Shukriya! {user} ko bata dungi. Bye! |
| `close.done.friend.hi.0` | थैंक्स यार, मैं {user} को बता देती हूँ। बाय! |
| `close.done.friend.hi.1` | शुक्रिया! {user} को बता दूँगी। बाय! |
| `close.done.friend.en.0` | Thanks, I will tell {user}. Bye! |
| `close.done.friend.en.1` | Thank you! I will let {user} know. Bye! |
| `close.need_approval.*.hinglish.0` | Theek hai, main {user} se confirm karke aapko call back karti hoon. Shukriya. |
| `close.need_approval.*.hinglish.1` | Main {user} se poochh kar aapko wapas call karungi. Shukriya, namaste. |
| `close.need_approval.*.hi.0` | ठीक है, मैं {user} से कन्फ़र्म करके आपको कॉल बैक करती हूँ। शुक्रिया। |
| `close.need_approval.*.hi.1` | मैं {user} से पूछकर आपको वापस कॉल करूँगी। शुक्रिया, नमस्ते। |
| `close.need_approval.*.en.0` | Alright, I will confirm with {user} and call you back. Thank you. |
| `close.need_approval.*.en.1` | I will check with {user} and call you back. Thank you, goodbye. |
| `close.time_up.*.hinglish.0` | Aapka bahut time le liya, maaf kijiye. Baaki baat main {user} se puchhkar baad mein kar lungi. Shukriya. |
| `close.time_up.*.hinglish.1` | Main aur time nahi lungi. Baaki main {user} se puchhkar baad mein batati hoon. Namaste. |
| `close.time_up.*.hi.0` | आपका बहुत समय ले लिया, माफ़ कीजिए। बाकी बात मैं {user} से पूछकर बाद में कर लूँगी। शुक्रिया। |
| `close.time_up.*.hi.1` | मैं और समय नहीं लूँगी। बाकी मैं {user} से पूछकर बाद में बताती हूँ। नमस्ते। |
| `close.time_up.*.en.0` | I have taken a lot of your time, sorry. I will check the rest with {user} and follow up later. Thank you. |
| `close.time_up.*.en.1` | I will not take more of your time. I will follow up on the rest later. Goodbye. |
| `close.unresolved.*.hinglish.0` | Lagta hai abhi baat nahi ho paa rahi. Main {user} ko bata deti hoon aur dobara koshish karungi. Shukriya. |
| `close.unresolved.*.hinglish.1` | Abhi baat poori nahi ho paayi. Main {user} ko bata kar phir call karungi. Namaste. |
| `close.unresolved.*.hi.0` | लगता है अभी बात नहीं हो पा रही। मैं {user} को बता देती हूँ और दोबारा कोशिश करूँगी। शुक्रिया। |
| `close.unresolved.*.hi.1` | अभी बात पूरी नहीं हो पाई। मैं {user} को बताकर फिर कॉल करूँगी। नमस्ते। |
| `close.unresolved.*.en.0` | It looks like we are not getting through right now. I will tell {user} and try again. Thank you. |
| `close.unresolved.*.en.1` | We could not finish this now. I will tell {user} and call again. Goodbye. |
| `confirm.commit_ok.*.hinglish.0` | Ji, {value} theek hai. |
| `confirm.commit_ok.*.hinglish.1` | {ack}, {value} pakka. |
| `confirm.commit_ok.*.hi.0` | जी, {value} ठीक है। |
| `confirm.commit_ok.*.hi.1` | {ack}, {value} पक्का। |
| `confirm.commit_ok.*.en.0` | Yes, {value} works. |
| `confirm.commit_ok.*.en.1` | {ack}, {value} it is. |
| `confirm.need_user.*.hinglish.0` | Yeh main abhi pakka nahi kar sakti. Main {user} se confirm karke aapko call back karti hoon. |
| `confirm.need_user.*.hinglish.1` | Is par main abhi haan nahi bol sakti. {user} se poochh kar aapko wapas call karungi. |
| `confirm.need_user.*.hi.0` | यह मैं अभी पक्का नहीं कर सकती। मैं {user} से कन्फ़र्म करके आपको कॉल बैक करती हूँ। |
| `confirm.need_user.*.hi.1` | इस पर मैं अभी हाँ नहीं बोल सकती। {user} से पूछकर आपको वापस कॉल करूँगी। |
| `confirm.need_user.*.en.0` | I cannot confirm that right now. I will check with {user} and call you back. |
| `confirm.need_user.*.en.1` | I cannot say yes to that yet. I will ask {user} and call you back. |
| `confirm.readback_check.*.hinglish.0` | Maine {value} suna, sahi hai na? |
| `confirm.readback_check.*.hinglish.1` | {value}, yehi bola na aapne? |
| `confirm.readback_check.*.hi.0` | मैंने {value} सुना, सही है न? |
| `confirm.readback_check.*.hi.1` | {value}, यही बोला न आपने? |
| `confirm.readback_check.*.en.0` | I heard {value}, is that right? |
| `confirm.readback_check.*.en.1` | {value}, did I get that right? |
| `confirm.readback_note.*.hinglish.0` | {ack}, {value}, maine note kar liya. |
| `confirm.readback_note.*.hinglish.1` | {ack}, {value}. Shukriya. |
| `confirm.readback_note.*.hi.0` | {ack}, {value}, मैंने नोट कर लिया। |
| `confirm.readback_note.*.hi.1` | {ack}, {value}। शुक्रिया। |
| `confirm.readback_note.*.en.0` | {ack}, {value}, I have noted that. |
| `confirm.readback_note.*.en.1` | {ack}, {value}. Thank you. |
| `confirm.thanks.*.hinglish.0` | {ack}, shukriya. |
| `confirm.thanks.*.hinglish.1` | {ack}, bahut achha. |
| `confirm.thanks.*.hi.0` | {ack}, शुक्रिया। |
| `confirm.thanks.*.hi.1` | {ack}, बहुत अच्छा। |
| `confirm.thanks.*.en.0` | {ack}, thank you. |
| `confirm.thanks.*.en.1` | {ack}, good. |
| `disclose.are_you_ai.*.hinglish.0` | Ji haan, main ek AI assistant hoon, {user} ki taraf se call kar rahi hoon. |
| `disclose.are_you_ai.*.hinglish.1` | Sach bataun toh haan, main AI assistant hoon. {user} ne mujhe aapko call karne ko kaha hai. |
| `disclose.are_you_ai.*.hi.0` | जी हाँ, मैं एक ए आई असिस्टेंट हूँ, {user} की तरफ़ से कॉल कर रही हूँ। |
| `disclose.are_you_ai.*.hi.1` | सच कहूँ तो हाँ, मैं ए आई असिस्टेंट हूँ। {user} ने मुझे आपको कॉल करने को कहा है। |
| `disclose.are_you_ai.*.en.0` | Yes, I am an AI assistant, calling on behalf of {user}. |
| `disclose.are_you_ai.*.en.1` | To be honest, yes, I am an AI assistant. {user} asked me to call you. |
| `disclose.intro.*.hinglish.0` | Main Friday bol rahi hoon, {user} ki virtual assistant. {user} ki taraf se aapko call kiya hai. |
| `disclose.intro.*.hi.0` | मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} की तरफ़ से आपको कॉल किया है। |
| `disclose.intro.*.en.0` | This is Friday, a virtual assistant calling on behalf of {user}. |
| `disclose.intro.family_elder.hinglish.0` | Main Friday bol rahi hoon, {user} ki assistant. Main ek virtual assistant hoon, aur {user} ki taraf se aapko phone kiya hai. |
| `disclose.intro.family_elder.hi.0` | मैं फ्राइडे बोल रही हूँ, {user} की असिस्टेंट। मैं एक वर्चुअल असिस्टेंट हूँ और {user} की तरफ़ से आपको फ़ोन किया है। |
| `disclose.intro.family_elder.en.0` | Hello, this is Friday, {user}'s virtual assistant. I am calling on {user}'s behalf. |
| `disclose.intro.friend.hinglish.0` | Main Friday, {user} ki virtual assistant bol rahi hoon. {user} ne mujhse aapko call karwaya hai. |
| `disclose.intro.friend.hi.0` | मैं फ्राइडे, {user} की वर्चुअल असिस्टेंट बोल रही हूँ। {user} ने मुझसे आपको कॉल करवाया है। |
| `disclose.intro.friend.en.0` | I am Friday, {user}'s virtual assistant. {user} asked me to call you. |
| `disclose.who.*.hinglish.0` | Main Friday hoon, {user} ki virtual assistant. {user} ki taraf se call kar rahi hoon. |
| `disclose.who.*.hi.0` | मैं फ्राइडे हूँ, {user} की वर्चुअल असिस्टेंट। {user} की तरफ़ से कॉल कर रही हूँ। |
| `disclose.who.*.en.0` | I am Friday, {user}'s virtual assistant, calling on {user}'s behalf. |
| `disclose.who.family_elder.hinglish.0` | Main Friday hoon, {user} ki assistant. {user} ne mujhe aapse baat karne ko kaha hai. |
| `disclose.who.family_elder.hi.0` | मैं फ्राइडे हूँ, {user} की असिस्टेंट। {user} ने मुझे आपसे बात करने को कहा है। |
| `disclose.who.family_elder.en.0` | I am Friday, {user}'s assistant. {user} asked me to speak with you. |
| `greet.named.*.hinglish.0` | Hello, kya meri baat {callee} se ho rahi hai? |
| `greet.named.*.hi.0` | हैलो, क्या मेरी बात {callee} से हो रही है? |
| `greet.named.*.en.0` | Hello, am I speaking with {callee}? |
| `greet.named.family_elder.hinglish.0` | Namaste {callee}. |
| `greet.named.family_elder.hi.0` | नमस्ते {callee}। |
| `greet.named.family_elder.en.0` | Hello {callee}, namaste. |
| `greet.named.friend.hinglish.0` | Hello {callee}! |
| `greet.named.friend.hi.0` | हैलो {callee}! |
| `greet.named.friend.en.0` | Hello {callee}! |
| `greet.plain.*.hinglish.0` | Hello, namaste. |
| `greet.plain.*.hi.0` | हैलो, नमस्ते। |
| `greet.plain.*.en.0` | Hello, good day. |
| `greet.plain.family_elder.hinglish.0` | Namaste ji. |
| `greet.plain.family_elder.hi.0` | नमस्ते जी। |
| `greet.plain.family_elder.en.0` | Hello, namaste. |
| `greet.plain.friend.hinglish.0` | Hello! |
| `greet.plain.friend.hi.0` | हैलो! |
| `greet.plain.friend.en.0` | Hello! |
| `handle_objection.asks_money.*.hinglish.0` | Paise ya payment ke baare mein main kuch tay nahi kar sakti. Yeh {user} se puchhkar hi hoga. |
| `handle_objection.asks_money.*.hinglish.1` | Payment ki baat main nahi kar sakti, yeh {user} khud tay karenge. |
| `handle_objection.asks_money.*.hi.0` | पैसे या पेमेंट के बारे में मैं कुछ तय नहीं कर सकती। यह {user} से पूछकर ही होगा। |
| `handle_objection.asks_money.*.hi.1` | पेमेंट की बात मैं नहीं कर सकती, यह {user} खुद तय करेंगे। |
| `handle_objection.asks_money.*.en.0` | I cannot decide anything about money or payment. That will be for {user} to decide. |
| `handle_objection.asks_money.*.en.1` | I cannot discuss payment; {user} will settle that directly. |
| `handle_objection.asks_personal.*.hinglish.0` | Yeh jaankari mere paas nahi hai. Main {user} se puchhkar aapko bata dungi. |
| `handle_objection.asks_personal.*.hinglish.1` | Iske liye mujhe {user} se puchhna padega, main wapas batati hoon. |
| `handle_objection.asks_personal.*.hi.0` | यह जानकारी मेरे पास नहीं है। मैं {user} से पूछकर आपको बता दूँगी। |
| `handle_objection.asks_personal.*.hi.1` | इसके लिए मुझे {user} से पूछना पड़ेगा, मैं वापस बताती हूँ। |
| `handle_objection.asks_personal.*.en.0` | I do not have that information. I will check with {user} and tell you. |
| `handle_objection.asks_personal.*.en.1` | I need to ask {user} for that; I will get back to you. |
| `handle_objection.busy.*.hinglish.0` | Koi baat nahi. Aap kab free honge? Main tab dobara call kar lungi. |
| `handle_objection.busy.*.hinglish.1` | Theek hai, aapko kab call karun? Jab aapko theek lage. |
| `handle_objection.busy.*.hi.0` | कोई बात नहीं। आप कब फ़्री होंगे? मैं तब दोबारा कॉल कर लूँगी। |
| `handle_objection.busy.*.hi.1` | ठीक है, आपको कब कॉल करूँ? जब आपको ठीक लगे। |
| `handle_objection.busy.*.en.0` | No problem. When will you be free? I will call again then. |
| `handle_objection.busy.*.en.1` | That is fine. When would be a good time to call? |
| `handle_objection.busy_noted.*.hinglish.0` | Theek hai, main {value} par dobara call karti hoon. |
| `handle_objection.busy_noted.*.hinglish.1` | {ack}, {value} par call karungi. |
| `handle_objection.busy_noted.*.hi.0` | ठीक है, मैं {value} पर दोबारा कॉल करती हूँ। |
| `handle_objection.busy_noted.*.hi.1` | {ack}, {value} पर कॉल करूँगी। |
| `handle_objection.busy_noted.*.en.0` | Alright, I will call again at {value}. |
| `handle_objection.busy_noted.*.en.1` | {ack}, I will call at {value}. |
| `handle_objection.clarify.*.hinglish.0` | Maaf kijiye, mujhe theek se samajh nahi aaya. Kya aap ek baar phir bata sakte hain? |
| `handle_objection.clarify.*.hinglish.1` | Sorry, awaaz thodi saaf nahi aayi. Kya aap dobara bol sakte hain? |
| `handle_objection.clarify.*.hi.0` | माफ़ कीजिए, मुझे ठीक से समझ नहीं आया। क्या आप एक बार फिर बता सकते हैं? |
| `handle_objection.clarify.*.hi.1` | सॉरी, आवाज़ थोड़ी साफ़ नहीं आई। क्या आप दोबारा बोल सकते हैं? |
| `handle_objection.clarify.*.en.0` | Sorry, I did not quite catch that. Could you say it once more? |
| `handle_objection.clarify.*.en.1` | Sorry, the line is not clear. Could you repeat that? |
| `handle_objection.off_topic.*.hinglish.0` | Ji, lekin abhi main bas isi kaam ke liye call kar rahi hoon. |
| `handle_objection.off_topic.*.hinglish.1` | Haan ji, par main sirf is baat ke liye call kar rahi hoon. |
| `handle_objection.off_topic.*.hi.0` | जी, लेकिन अभी मैं बस इसी काम के लिए कॉल कर रही हूँ। |
| `handle_objection.off_topic.*.hi.1` | हाँ जी, पर मैं सिर्फ़ इस बात के लिए कॉल कर रही हूँ। |
| `handle_objection.off_topic.*.en.0` | Of course, but right now I am only calling about this. |
| `handle_objection.off_topic.*.en.1` | Sure, but I am only calling for this one thing. |
| `handle_objection.refuses.*.hinglish.0` | Theek hai, koi baat nahi. Main {user} ko bata dungi. |
| `handle_objection.refuses.*.hinglish.1` | Bilkul, jaisa aapko theek lage. |
| `handle_objection.refuses.*.hi.0` | ठीक है, कोई बात नहीं। मैं {user} को बता दूँगी। |
| `handle_objection.refuses.*.hi.1` | बिल्कुल, जैसा आपको ठीक लगे। |
| `handle_objection.refuses.*.en.0` | That is fine, no problem. I will let {user} know. |
| `handle_objection.refuses.*.en.1` | Of course, whatever you prefer. |
| `handle_objection.repeat_prefix.*.hinglish.0` | Ji, main dobara kehti hoon. |
| `handle_objection.repeat_prefix.*.hinglish.1` | Zaroor, phir se bolti hoon. |
| `handle_objection.repeat_prefix.*.hi.0` | जी, मैं दोबारा कहती हूँ। |
| `handle_objection.repeat_prefix.*.hi.1` | ज़रूर, फिर से बोलती हूँ। |
| `handle_objection.repeat_prefix.*.en.0` | Of course, let me say it again. |
| `handle_objection.repeat_prefix.*.en.1` | Sure, once more. |
| `handle_objection.repeat_prefix.family_elder.hinglish.0` | Ji, main dheere se dobara kehti hoon. |
| `handle_objection.repeat_prefix.family_elder.hinglish.1` | Zaroor ji, thoda dheere se phir bolti hoon. |
| `handle_objection.repeat_prefix.family_elder.hi.0` | जी, मैं धीरे से दोबारा कहती हूँ। |
| `handle_objection.repeat_prefix.family_elder.hi.1` | ज़रूर जी, थोड़ा धीरे से फिर बोलती हूँ। |
| `handle_objection.repeat_prefix.family_elder.en.0` | Of course, let me say it again, more slowly. |
| `handle_objection.repeat_prefix.family_elder.en.1` | Sure, I will say it slowly once more. |
| `handle_objection.silence.*.hinglish.0` | Hello? Kya aap meri awaaz sun pa rahe hain? |
| `handle_objection.silence.*.hinglish.1` | Hello, aap line par hain? |
| `handle_objection.silence.*.hi.0` | हैलो? क्या आप मेरी आवाज़ सुन पा रहे हैं? |
| `handle_objection.silence.*.hi.1` | हैलो, आप लाइन पर हैं? |
| `handle_objection.silence.*.en.0` | Hello? Can you hear me? |
| `handle_objection.silence.*.en.1` | Hello, are you still there? |
| `hold_wait.asking_user.*.hinglish.0` | Ek minute, main {user} se puchh leti hoon. |
| `hold_wait.asking_user.*.hinglish.1` | Bas ek minute, {user} se confirm kar leti hoon. |
| `hold_wait.asking_user.*.hi.0` | एक मिनट, मैं {user} से पूछ लेती हूँ। |
| `hold_wait.asking_user.*.hi.1` | बस एक मिनट, {user} से कन्फ़र्म कर लेती हूँ। |
| `hold_wait.asking_user.*.en.0` | One minute, let me check with {user}. |
| `hold_wait.asking_user.*.en.1` | Just a moment, I will confirm with {user}. |
| `hold_wait.still_here.*.hinglish.0` | Ji, main abhi bhi line par hoon. |
| `hold_wait.still_here.*.hinglish.1` | Main yahin hoon, ji. |
| `hold_wait.still_here.*.hi.0` | जी, मैं अभी भी लाइन पर हूँ। |
| `hold_wait.still_here.*.hi.1` | मैं यहीं हूँ, जी। |
| `hold_wait.still_here.*.en.0` | I am still on the line. |
| `hold_wait.still_here.*.en.1` | I am still here. |
| `hold_wait.thanks.*.hinglish.0` | Ji, shukriya. |
| `hold_wait.thanks.*.hinglish.1` | Shukriya, main yahin hoon. |
| `hold_wait.thanks.*.hi.0` | जी, शुक्रिया। |
| `hold_wait.thanks.*.hi.1` | शुक्रिया, मैं यहीं हूँ। |
| `hold_wait.thanks.*.en.0` | Thank you. |
| `hold_wait.thanks.*.en.1` | Thanks, I am here. |
| `hold_wait.wait.*.hinglish.0` | Ji, main line par hoon, aap araam se dekh lijiye. |
| `hold_wait.wait.*.hinglish.1` | Theek hai, main wait karti hoon. |
| `hold_wait.wait.*.hi.0` | जी, मैं लाइन पर हूँ, आप आराम से देख लीजिए। |
| `hold_wait.wait.*.hi.1` | ठीक है, मैं वेट करती हूँ। |
| `hold_wait.wait.*.en.0` | Sure, I am on the line, take your time. |
| `hold_wait.wait.*.en.1` | Alright, I will wait. |
| `state_purpose.message.*.hinglish.0` | Ek baat aur batani thi: {message} |
| `state_purpose.message.*.hinglish.1` | Aur haan, {message} |
| `state_purpose.message.*.hi.0` | एक बात और बतानी थी: {message} |
| `state_purpose.message.*.hi.1` | और हाँ, {message} |
| `state_purpose.message.*.en.0` | One more thing to tell you: {message} |
| `state_purpose.message.*.en.1` | Also, {message} |
| `state_purpose.offer_callback.*.hinglish.0` | Agar abhi time nahi hai, toh main {user} se keh kar baad mein dobara call kar sakti hoon. |
| `state_purpose.offer_callback.*.hi.0` | अगर अभी समय नहीं है, तो मैं {user} से कहकर बाद में दोबारा कॉल कर सकती हूँ। |
| `state_purpose.offer_callback.*.en.0` | If now is not a good time, I can call again later. |
| `state_purpose.purpose.*.hinglish.0` | {user} ki taraf se ek chhoti si baat: {purpose} |
| `state_purpose.purpose.*.hinglish.1` | Mere call karne ki wajah yeh hai: {purpose} |
| `state_purpose.purpose.*.hi.0` | {user} की तरफ़ से एक छोटी सी बात: {purpose} |
| `state_purpose.purpose.*.hi.1` | मेरे कॉल करने की वजह यह है: {purpose} |
| `state_purpose.purpose.*.en.0` | A quick matter from {user}: {purpose} |
| `state_purpose.purpose.*.en.1` | The reason for my call: {purpose} |
| `state_purpose.purpose.family_elder.hinglish.0` | Aapse ek chhoti si baat karni thi. {purpose} |
| `state_purpose.purpose.family_elder.hinglish.1` | {user} ne yeh kehne ko kaha tha. {purpose} |
| `state_purpose.purpose.family_elder.hi.0` | आपसे एक छोटी सी बात करनी थी। {purpose} |
| `state_purpose.purpose.family_elder.hi.1` | {user} ने यह कहने को कहा था। {purpose} |
| `state_purpose.purpose.family_elder.en.0` | I just had a small thing to tell you. {purpose} |
| `state_purpose.purpose.family_elder.en.1` | {user} asked me to say this. {purpose} |
| `state_purpose.purpose.friend.hinglish.0` | {user} ne mujhe yeh bolne ko kaha: {purpose} |
| `state_purpose.purpose.friend.hinglish.1` | Bas ek chhoti si baat: {purpose} |
| `state_purpose.purpose.friend.hi.0` | {user} ने मुझे यह बोलने को कहा: {purpose} |
| `state_purpose.purpose.friend.hi.1` | बस एक छोटी सी बात: {purpose} |
| `state_purpose.purpose.friend.en.0` | {user} asked me to tell you: {purpose} |
| `state_purpose.purpose.friend.en.1` | Just a quick thing: {purpose} |
| `stop.distress.*.hinglish.0` | Aap theek nahi lag rahe. Main abhi {user} ko turant batati hoon. Agar madad chahiye toh 112 par call kijiye. Apna khayal rakhiye. |
| `stop.distress.*.hi.0` | आप ठीक नहीं लग रहे। मैं अभी {user} को तुरंत बताती हूँ। अगर मदद चाहिए तो 112 पर कॉल कीजिए। अपना ख़याल रखिए। |
| `stop.distress.*.en.0` | You do not sound well. I am telling {user} right now. If you need help, please call 112. Take care. |
| `stop.hostile.*.hinglish.0` | Maaf kijiye, aapko pareshani hui. Main call band karti hoon. Namaste. |
| `stop.hostile.*.hi.0` | माफ़ कीजिए, आपको परेशानी हुई। मैं कॉल बंद करती हूँ। नमस्ते। |
| `stop.hostile.*.en.0` | I am sorry for the trouble. I will end the call now. Goodbye. |
| `stop.no_bots.*.hinglish.0` | Samajh gayi, maaf kijiye. Main {user} ko bata deti hoon. Aapko dobara pareshan nahi karungi. Namaste. |
| `stop.no_bots.*.hi.0` | समझ गई, माफ़ कीजिए। मैं {user} को बता देती हूँ। आपको दोबारा परेशान नहीं करूँगी। नमस्ते। |
| `stop.no_bots.*.en.0` | Understood, I am sorry. I will tell {user}. I will not bother you again. Goodbye. |
| `stop.stop_calling.*.hinglish.0` | Bilkul, maaf kijiye. Main dobara call nahi karungi. Namaste. |
| `stop.stop_calling.*.hi.0` | बिल्कुल, माफ़ कीजिए। मैं दोबारा कॉल नहीं करूँगी। नमस्ते। |
| `stop.stop_calling.*.en.0` | Of course, I am sorry. I will not call again. Goodbye. |
| `stop.stop_calling.family_elder.hinglish.0` | Bilkul ji, maaf kijiye. Main dobara phone nahi karungi. Namaste. |
| `stop.stop_calling.family_elder.hi.0` | बिल्कुल जी, माफ़ कीजिए। मैं दोबारा फ़ोन नहीं करूँगी। नमस्ते। |
| `stop.stop_calling.family_elder.en.0` | Of course, I am sorry. I will not call again. Goodbye. |
| `stop.wrong_number.*.hinglish.0` | Oh, maaf kijiye, galat number lag gaya. Pareshani ke liye sorry. Namaste. |
| `stop.wrong_number.*.hi.0` | ओह, माफ़ कीजिए, ग़लत नंबर लग गया। परेशानी के लिए सॉरी। नमस्ते। |
| `stop.wrong_number.*.en.0` | Oh, I am sorry, I dialled the wrong number. Sorry for the trouble. Goodbye. |
| `stop.wrong_number.family_elder.hinglish.0` | Oh, maaf kijiye ji, galat number lag gaya. Pareshani ke liye maafi. Namaste. |
| `stop.wrong_number.family_elder.hi.0` | ओह, माफ़ कीजिए जी, ग़लत नंबर लग गया। परेशानी के लिए माफ़ी। नमस्ते। |
| `stop.wrong_number.family_elder.en.0` | Oh, I am sorry, I have the wrong number. Sorry to have troubled you. Goodbye. |
| `voicemail.message.*.hinglish.0` | Namaste, main Friday bol rahi hoon, {user} ki virtual assistant. {user} ne aapko call kiya tha. Jab time mile, kripya {user} ko wapas call kar lijiye. Dhanyavaad. |
| `voicemail.message.*.hi.0` | नमस्ते, मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} ने आपको कॉल किया था। जब समय मिले, कृपया {user} को वापस कॉल कर लीजिए। धन्यवाद। |
| `voicemail.message.*.en.0` | Hello, this is Friday, {user}'s virtual assistant. {user} tried to call you. Please call {user} back when you can. Thank you. |
| `voicemail.message.friend.hinglish.0` | Namaste, main Friday, {user} ki assistant. {user} ne call kiya tha. Fursat mein unhe ek call kar dijiye. Shukriya. |
| `voicemail.message.friend.hi.0` | नमस्ते, मैं फ्राइडे, {user} की असिस्टेंट। {user} ने कॉल किया था। फ़ुर्सत में उन्हें एक कॉल कर दीजिए। शुक्रिया। |
| `voicemail.message.friend.en.0` | Hello, this is Friday, {user}'s assistant. {user} called you. Please give them a call when you are free. Thank you. |
