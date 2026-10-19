# Consumer Friday: every problem, listed before we build (19 Oct 2026)

Scope the founder set: (A) a complete calling agent the CUSTOMER can use to call anyone, (B) a complete savings engine,
(C) a Friday that remembers the whole day, and everything around them. All voice work so far is for the business use case; this
is the consumer use case. Rule for this document: problems only. Solutions are decided later, area by area, with the founder.
Each point: P-number, the problem, why it is hard.

## Founder decisions that shape this list (19 Oct 2026)
- Gmail, Calendar and the other personal sources are CORE: the user connects them so Friday knows them. (C1 below is therefore a MUST.)
- ORDERING through browsers and platforms is PARKED for now (the browser connector stays in the repo, off by default).
- Everything else (calling anyone, savings engine, remembering the day, voice-first, bills, memory, trust) is in scope.
- Google review path: test mode with named testers for the beta (verify the tester limit), start verification and the Gmail security assessment in parallel.

## A. The calling agent for the customer (call anyone)

### A1. What the user wants to call about (the request space)
- A1.1 Call a business (done): quote, book, enquire. Needs to extend to follow-ups, complaints, cancellations, refunds.
- A1.2 Call a service provider the user already uses (plumber, driver, cook, maid, tutor, landlord): relationship, not a cold call.
- A1.3 Call customer care (telecom, bank, utility, courier): IVR menus, hold music, authentication questions, escalations.
- A1.4 Call family and friends: remind, wish, "I'm running late", check in, confirm plans. Tone and relationship matter most.
- A1.5 Call officials (school, RWA, society office, government help desks, doctor's clinic desk).
- A1.6 Call an unknown person from a message or number (a seller on a classifieds ad, a lost-and-found).
- A1.7 Group calls or many calls at once (invite 10 people, collect RSVPs).
- A1.8 Call back someone who called the user (missed call handling), and call back at a scheduled time.
- A1.9 Calls that need the user to join midway (warm transfer): "connect me when they pick up".
- A1.10 Request vagueness: "call Sharma ji about the thing" (which Sharma ji? what thing?).

### A2. Before the call (understand, confirm, decide)
- A2.1 Identify who to call: contacts access, nicknames ("mummy", "bhaiya"), duplicates, wrong number risk.
- A2.2 Extract the goal and the limits: what to say, what to ask, what must NOT be said, budget, deadlines, deal-breakers.
- A2.3 Missing facts: ask the user only what is needed, one question at a time, in their language.
- A2.4 The user must approve the goal and first words (draft), especially for personal calls.
- A2.5 Choose when to call: the recipient's likely availability, quiet hours, time zones, user's busy time.
- A2.6 Choose whether a call is the right channel (a text may be better); warn when a call is a bad idea.
- A2.7 Refuse unsafe or abusive requests (harassment, threats, scams, impersonation, pranks, calling emergency numbers).
- A2.8 Cost and limits per user (minutes, number of calls), fairness, abuse prevention.

### A3. During the call (conversation quality)
- A3.1 Scripted vs free-form: business calls use approved scripts; personal calls cannot be fully scripted. How much freedom, with what guardrails.
- A3.2 The first 5 seconds: "who is this?", wrong person, suspicion that it is a bot or spam, instant hang-up.
- A3.3 Natural Hindi/Hinglish/English and regional languages, accents, code-switching, noisy lines, speech-to-text errors.
- A3.4 Turn-taking: interruptions, overlaps, silences, filler sounds, speaking speed for elders, latency.
- A3.5 Emotion and tact: bad news, anger, grief, sarcasm, jokes, politeness levels (aap/tum/tu), family hierarchies.
- A3.6 Answering questions about the user without inventing facts or leaking private details (health, money, location).
- A3.7 Staying on goal when the other person goes off topic, asks something unexpected, or asks for money or personal details.
- A3.8 Negotiation: stay inside the user's range, never agree above the maximum, never commit money or time without approval.
- A3.9 Commitments made on the call: a promise to pay, a visit, a time. Who confirms, how it is recorded, how it is undone.
- A3.10 Handling voicemail, call waiting, IVR, "press 1", hold queues, call drops, wrong numbers, busy tones.
- A3.11 Knowing when to stop: recipient says stop, is distressed, asks for a human, or the goal is impossible.
- A3.12 Escalation to the user live: whisper or message mid-call ("they are asking X, what should I say?") with a time limit.
- A3.13 Multi-party calls and speakerphone, children or elderly answering, other languages in the background.

### A4. After the call (outcome and follow-up)
- A4.1 Report in plain words: what was agreed, what was refused, what remains open, with a transcript and a short summary.
- A4.2 Turn outcomes into actions: calendar entry, reminder, payment prompt, next call.
- A4.3 Retry rules: no answer, busy, call back later, max attempts, the recipient asked not to be called again.
- A4.4 Mistakes: wrong person reached, wrong thing said; how the user and the recipient are told and how it is corrected.
- A4.5 Recording and transcript storage: who may see them, how long they are kept, deletion, sharing.

### A5. Trust, consent and legal (calling real people)
- A5.1 Disclosure: tell the recipient it is an assistant calling for the user; when, in what words; what if they ask "are you AI?".
- A5.2 Impersonation: Friday must never pretend to be the user or clone the user's voice; family members may be confused or alarmed.
- A5.3 Recipient consent and opt-out: "do not call me again" must be honoured across all users (shared do-not-call).
- A5.4 TRAI and DLT rules for automated and AI calls, caller ID display, calling windows, spam classification risk.
- A5.5 Recording consent laws and the stored-recording question (we store but do not announce): legal read required.
- A5.6 Caller ID: which number the recipient sees, trust of a new number, being blocked or flagged as spam by Truecaller and carriers.
- A5.7 Data protection (DPDP): personal data of the recipient who never signed up; purpose, retention, rights.
- A5.8 Abuse by users (stalking, harassment, scams, social engineering): detection, limits, bans, reporting channel.
- A5.9 Sensitive categories: medical, legal, financial, minors, mental health, emergencies; what Friday must refuse or route to a human.
- A5.10 Liability: who is responsible when Friday says something wrong or a commitment is misunderstood.

### A6. Voice, telephony and engineering
- A6.1 Telephony provider limits: number pool, outbound caller ID per user, call volumes, cost per minute, regional carriers.
- A6.2 One voice for everyone vs the user choosing a voice; consistency, pronunciation of names, regional names.
- A6.3 Latency budget: speech-to-text, model, text-to-speech; barge-in; streaming; dead air.
- A6.4 Cost control: model per call, long calls, runaway loops, maximum duration, per-user and global caps.
- A6.5 Reliability: call drops, provider outages, retries without duplicate calls, idempotency, kill switch.
- A6.6 Testing without calling real people: simulated personas, scripted listeners, replay of real calls (masked), regression sets.
- A6.7 Observability: per-call trace, quality score, failure categories, human review queue, learning loop labels.
- A6.8 Safety net in code: allow-list for testing, per-category switches, red-line phrases, spend and commitment checks that do not rely on the model.
- A6.9 Inbound side: the user's own incoming calls (screening, divert to Friday, receptionist), per-user numbers, which user was this for.

## B. The savings engine
- B1 Which spending to cover first (food, grocery, fuel, bills, travel, shopping) so users see money saved in week one.
- B2 Knowing the user's cards and offers without card numbers: card names only, spend caps used, billing dates, point balances.
- B3 Offer and reward rules for each card are complicated, change often and have exclusions (wallets, rent, fuel, caps, MCC codes); wrong advice destroys trust.
- B4 Data source for card rules and offers: public pages, partner data, manual verification; "last checked" date; who verifies.
- B5 Prices of groceries, food and travel across platforms: no public APIs, per-pincode prices, rapid changes, bot protection, platform terms.
- B6 Stacking offers (bank offer + coupon + wallet + membership) only when they truly combine; showing the final price.
- B7 Calculator must be code, tested, with every rupee figure from a trusted source; the model only explains.
- B8 Bills: due dates, amounts, billers, bill fetch via BBPS (licensed partner), reminders, autopay confusion, late fee avoidance.
- B9 Subscriptions: detect recurring debits, find unused ones, cancel (steps or a call), refund follow-ups.
- B10 Insurance, loans and investments: regulated; comparison of facts only, no advice or selling without licences.
- B11 Neutrality: no commissions that change ranking, disclose any revenue, explain every recommendation in one clause.
- B12 Measuring and showing savings honestly (counterfactual): "saved Rs X" must be believable and auditable.
- B13 Getting the user's data in: forwarded bills and SMS, screenshots, Gmail, Account Aggregator; each with consent, cost and effort.
- B14 Acting on a recommendation: deep links, QR, "use this card" at checkout moment; the user pays, Friday never does.
- B15 Fairness and bias: no pushing premium cards, no unsafe credit advice; vulnerable users.

## C. A Friday that remembers the whole day
- C1 Sources of the day: what the user says, calendar, bookings, forwarded bills, messages, call outcomes; each needs consent.
- C2 A per-user life state: events, commitments, open tasks, people, places, preferences; structure, versions, conflicts.
- C3 Understanding time and context: "kal shaam", time zones, recurring items, duration of an event, "in an interview now".
- C4 Proactive timing: when to speak first (after the interview, before the meeting), quiet hours, protected events, message caps.
- C5 Channel choice for nudges: WhatsApp text, voice note, call; opt-in per topic; escalation for urgent items.
- C6 Being useful without nagging: relevance scoring, "why am I seeing this" in one clause, learning from "stop" and ignores.
- C7 Memory accuracy: remembering wrong things, outdated facts, contradictions, the user correcting Friday.
- C8 Privacy of memory: per-user only, encryption, view/edit/delete/export, never used for ads or for other users.
- C9 Consistency across channels: the same context on WhatsApp, voice, calls, web; no "who are you again".
- C10 The user's family and others in the memory (parents, children): their consent, what is shared, who can see.
- C11 Device and voice-first access: iPhone limits, Siri shortcuts, Action Button, voice sessions; Android assistant role.
- C12 Daily brief design: what goes in, how long, when, language, and not becoming spam.

## D. Everything around it (cross-cutting)
- D1 Onboarding: first minute value, asking for permissions gradually, explaining what Friday can and cannot do.
- D2 Identity: how Friday knows it is the right user (phone number, WhatsApp), account sharing, SIM changes.
- D3 Language and personality: Hinglish voice and text that feels like a person, consistent across channels.
- D4 Payments and approvals: the user approves exact amounts; QR and UPI deep links; Friday never holds money.
- D5 Credentials and OTP: login codes only through the secure page; never payment OTP, PIN or card; session storage rules.
- D6 Platform limits: WhatsApp template rules and 24-hour window, Apple and Google policies, telecom rules.
- D7 Growth: sharing loop, referral, outcome pages, trust marks, press, creators, offices and housing societies.
- D8 Money: free vs paid, business-pays-for-booking guardrails, cost per user per month, unit economics.
- D9 Support and recovery: when Friday fails, how the user reaches a human, refunds, apologising to a recipient.
- D10 Legal and compliance map: TRAI/DLT, DPDP, RBI/BBPS/UPI, IRDAI/SEBI, consumer protection, WhatsApp Business policy.
- D11 Quality and learning: labelling real calls, approval of any spoken line, regression tests, never changing words unreviewed.
- D12 Team and build order: what ships in the beta vs later, ownership, and how decisions are recorded.

## Next step (agreed way of working)
Walk through the areas one at a time (A first), mark each problem as MUST for the beta, LATER, or NEVER, then write the design for
the MUST items. Nothing is built until its problems are marked. Start with A1 (what people will ask Friday to call), because it
decides everything else.
