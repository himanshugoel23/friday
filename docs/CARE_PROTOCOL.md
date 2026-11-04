# Care protocol (`friday/care/`), built 2026-11-04

**Not a clinical tool. It does not diagnose, treat or replace a person. A mental-health professional should review all the wording and the rules before any wide launch.** Every line below is PENDING founder approval (CLAUDE.md rule 3: hear before change).

Status: BUILT, ALWAYS ON. No feature switch turns it off. The only switch is `FRIDAY_CARE_KILL_SWITCH`, for tests, honoured only when `FRIDAY_ENV` is `dev` or `test` (ignored in `prod`).

## What it does
1. **Detection** (`detect.py`, rules only, no model, no network). Roman Hinglish, Devanagari Hindi, English. Two tiers:
   - **HIGH**: thoughts of suicide or self-harm, explicit ("I want to die", "mujhe jeene ka mann nahi", "मैं मरना चाहता हूँ") or indirect ("better if I was not born", "no point living", "end it", "sab khatam", "मेरे जाने से किसी को फर्क नहीं पड़ेगा"), methods ("I took all my pills", "zeher kha lunga"). Judgement call: a bare short "sab khatam" or "end it" counts as HIGH (a false alarm costs one gentle message).
   - **ELEVATED**: distress without ideation. One strong signal (hopeless, worthless, "can't take this anymore", "koi umeed nahi") or two different weak kinds (job loss + "failure" + sleeplessness; money worry, loneliness, crying). A single weak signal ("I lost my job", "can't sleep") does nothing.
   - **Not triggered**: negation ("I don't want to die", "marna nahi chahta"), information or product talk ("suicide prevention app idea", "essay on suicide"), jokes and hyperbole ("I will die laughing", "bhookh se mar jaunga", "to die for"), ordinary "end it with my landlord". **Third person** ("my friend says he wants to die") is ELEVATED with its own line (112 for them, 14416 to learn how to support them).
   - Evasions folded: case, full-width letters, zero-width characters, spaced letters, repeated letters, light leet-speak.
2. **Reply protocol** (`service.py`, `copy.py`), 2 to 4 short lines, mirrors the user's language:
   - HIGH, first reply: acknowledge, the direct question ONCE ("do you have thoughts of hurting yourself?"), Tele-MANAS 14416 (free, 24x7, Hindi and English) and 112, an offer to DRAFT a message to a trusted person (Friday cannot send it; the user sends it).
   - After the answer (yes or no): 14416 / 112 again, then ONE question: may Friday tell the family to call them? Default is no sharing. A trusted-person draft is written when the user names one ("my sister", "Riya"). An offer to call the user's OWN number appears only if the existing call rules allow it (allow-listed own number, a call hook wired) and happens only on an explicit "call me". By default no hook is wired, so it is never offered.
   - Never: diagnosis, arguing feelings against facts, pep talk, promises about outcomes, product, work or shopping talk, feature offers.
   - ELEVATED: acknowledge, one gentle question, 14416 mentioned once (a second ELEVATED message gets a shorter acknowledgement with no number), no product chatter that turn. ELEVATED does not stop any feature.
3. **Follow-up** (`CareService.tick`, called from the proactive tick, deterministic, tested on a fake clock): if the user went quiet after HIGH, one check-in the same IST day (4 hours after their last message, at most 23:30, at least 45 minutes; quiet hours do NOT apply to it), one the next morning at 09:00 IST (never in quiet hours), then stop. Cancelled the moment the user says they are okay ("I'm okay", "main theek hoon") or "stop". A new HIGH message starts a new episode.
4. **Protection** (the gate):
   - `InboundPipeline._handle` runs the care screen FIRST (before the throttle, onboarding, chatbot, intents, planner, shopping, steps, browser agent). While HIGH is active every message is answered by the protocol; the brain and all task agents never see it. Neutral messages get one of two "everything else is paused" lines; after two such lines (or a check-in answered) the user is let through, so nobody is trapped. "I'm okay" or "stop" releases at once. The hold also ends 36 hours after the last HIGH message.
   - `ProactiveEngine` (every nudge, reminder, briefing and life-state follow-up goes through `process`) creates and sends nothing while HIGH is active.
   - An open request waiting for the user is left paused (their answer cannot reach it) and a pending confirmation is cleared so a later "yes" cannot confirm a payment; the user gets one plain line.
   - Distress text is never written to: the message log (stored copy is replaced by a placeholder), the webhook job queue (`try_care` runs before queueing), the reply log (`ReplyLog.record` refuses it), the evidence ledger (`from_user_text` stores "[withheld]"), logs (only `care_tier=high user=<hash>`). "Delete everything" erases the care state.
5. **Family sharing** (ROBIN, family of a parent and their adult child): distress content NEVER goes to family alerts or digests. The only thing that may go to the other family member is the single line `"<name> may need you, please call."` (`CareService.family_line`), once per episode, and only if (a) the speaker answered yes to "may I tell your family to call you?" or (b) explicit danger words were used (112, ambulance, overdose, "took all my pills", method phrases), which override the consent default. ELEVATED never produces it. The name is reduced to letters, at most 3 words.
6. **Elder speaker (60+)**: `*_elder` wording variants (short plain sentences, "free, day and night", no jargon) for the first reply, answers, "stay", ELEVATED and both check-ins. Chosen by `screen(..., elder=True)` or the `CareService.elder_check` hook; ROBIN sets it.
7. **Stable API for `friday/robin`**: `await care.is_active(user_id) -> bool` (also `await care.family_line(user_id, name, lang=None) -> str | None`). Get the service with `container.get("care")` (the inbound pipeline registers it) and call `is_active` before every outbound check-in call, nudge or digest line. Same answer as the gate above; always False when the kill switch is on in dev/test.

## What is stored
Per user, in the shared cache for 4 days: tier, language, timestamps, a few booleans (asked, answered, consent, elder, emergency, check-ins done). Never the user's words, a name or a draft. The cache is in memory in dev and Redis in production; a restart in dev loses the state (and so the pending check-ins).

## New lines, PENDING founder approval
31 ids, each in English, Roman Hinglish and Devanagari (93 texts). Ids are `care.line.<key>` (`friday/care/copy.py`):
`high_first`, `answer_yes`, `answer_no`, `stay`, `person_ask`, `draft`, `draft_body`, `offer_call`, `call_placed`, `call_unavailable`, `hold_a`, `hold_b`, `steady`, `stopped`, `paused_task`, `checkin_same_day`, `checkin_morning`, `elevated_first`, `elevated_again`, `third_party`, `family_ask`, `family_yes`, `family_no`, `family_line`, and the elder variants `high_first_elder`, `answer_yes_elder`, `answer_no_elder`, `stay_elder`, `elevated_first_elder`, `checkin_same_day_elder`, `checkin_morning_elder`.
Example (English `high_first`): "I'm really sorry you're hurting this much. I'm here with you. / Do you have thoughts of hurting yourself? / You can call Tele-MANAS on 14416 any time: free, 24x7, in Hindi and English. If you might act on it right now, call 112. / If you want, tell me who you trust and I'll draft a message for you to send."

## Limits and what is unverified
- The rules were written by engineers and tested on invented examples. Real messages will be missed (slang, spelling, other languages and scripts, long stories, sarcasm, voice-note transcript errors, images) and some harmless ones will trigger. Review the misses and false alarms from the pilot and add them as tests.
- **Helpline numbers (Tele-MANAS 14416, 112) are from memory and not checked against an official page.** The wording ("free, 24x7, Hindi and English") is unverified.
- Hinglish and Hindi feminine voice ("sun rahi hoon", "likh dungi") follows the existing persona; the user's own gender is never assumed in drafts.
- WhatsApp's 24-hour window: a next-morning check-in may fall outside it and then needs an approved template; the notifier's behaviour here is untested. No template is registered.
- The own-number call needs a `pipeline.care_call_hook` that nobody has wired (what would a care call say?). Until then it is never offered. No real call is placed by this code.
- "Paused" for an open request: the task engine has no pause call. A request waiting for the user is effectively paused; a call already in progress or a scheduled retry is NOT stopped.
- Not covered: the voice (call) channel, the receptionist and urgent flows, the other builders' packages (`friday/jobs`, `friday/browser_agent`, `friday/robin`) beyond the central gates above. They must call `care.is_active` themselves.
- A user who is HIGH and sends an unrelated command (e.g. a payment confirmation button) is answered with a pause line; that is intended but may surprise.
- Unknown senders (no account yet) get the first HIGH reply once and nothing is stored; their next message goes to onboarding.
- The legacy guardrail `self_harm`/`emergency` rules still exist in the chatbot but the care screen runs first and wins.
- Elder speaker detection depends on the caller (ROBIN) passing `elder` or setting `elder_check`; nothing here knows a user's age.

## Tests
`tests/care` (detection corpus in three languages, state machine, check-ins on a fake clock, gate, family consent, elder wording, copy structure, pipeline and proactive wiring). Existing guardrails and webchat tests that sent a self-harm message and then another request now say "main theek hoon" in between.
