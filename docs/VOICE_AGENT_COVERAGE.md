# Consumer voice agent: coverage map (19 Oct 2026)

Founder: the voice agent must cover every consumer use case, so we can publish it as a complete voice agent. This is the map of "every use case", with status.
Status words: DONE-REAL (tried on a real test phone) / BUILT (tested offline with fakes) / DESIGNED (written, not built) / OPEN (not designed) / PARKED (founder parked).

## A. The user talks to Friday by voice
| ID | Use case | Status | Notes |
|---|---|---|---|
| A1 | Call Friday's number and ask ("aaj mera din kaisa hai", "kaun sa card", "mummy ko call karo") | OPEN | Needs an inbound "user line": recognise the caller as the user, then run the same brain as WhatsApp |
| A2 | WhatsApp voice note in, voice note out (Hinglish) | OPEN | Speech-to-text and text-to-speech exist; channel flow not built |
| A3 | Hands-free voice in a phone app, "Hey Siri, Friday" | PARKED | After the beta |
| A4 | Elder-friendly mode (slower, repeats, simpler confirmations) | OPEN | Setting + line variants |
| A5 | Languages: Hindi, Hinglish, English, regional (Sarvam covers 11) | PARTLY | Hindi/Hinglish/English built; regional scripts not |
| A6 | Corrections and clarifications mid-conversation ("nahi, kal nahi, parso") | PARTLY | Quote flow has it; consumer flow needs it |
## B. Friday calls others for the user
| ID | Use case | Status |
|---|---|---|
| B1 | Businesses: quote, book, enquire (10 scripts, 22 categories) | DONE-REAL (test phone), scripts pending approval |
| B2 | Service providers you already use (plumber, driver, tutor) | BUILT (W1+W2) |
| B3 | Customer care incl. phone menus, hold and hold-fighting (LAUNCH, founder 19 Oct) | BUILT basic; hold-fighting OPEN |
| B4 | Family and friends (late, wishes, plans, check-ins) | BUILT |
| B5 | Officials (school, society office, helpdesks) | BUILT |
| B6 | Unknown person from an ad or message | BUILT |
| B7 | Groups: invite many, collect RSVPs | BUILT (fan-out + one report) |
| B8 | Call-backs and retries | BUILT |
| B9 | Negotiation inside limits | BUILT (business scripts), personal calls OPEN |
| B10 | Reminder calls to others on the user's behalf (parent's medicine, "meeting at 5") with the other person's consent (LAUNCH, founder 19 Oct) | OPEN |
| B11 | Appointment-confirmation and wake-up calls | OPEN |
| B12 | Warm transfer: "connect me when they pick up" | DESIGNED (hook), not built |
## C. Friday receives calls for the user
| ID | Use case | Status |
|---|---|---|
| C1 | Voicemail replacement (no answer, busy, unreachable) via conditional forwarding | DESIGNED (JARVIS_FEEL 8d) |
| C2 | Receptionist during protected events (temporary all-calls) | DESIGNED |
| C3 | Spam and scam callers: end politely, mark, suggest blocking | DESIGNED |
| C4 | Urgent flagging and immediate alert | DESIGNED |
| C5 | Missed-call notes when the caller hangs up | DESIGNED |
| C6 | Identify which user a call is for (shared number, redirecting number) | OPEN (probe test needed) |
| C7 | Forwarding setup and test | DESIGNED (8c) |
## D. Friday calls the user (proactive voice)
| ID | Use case | Status |
|---|---|---|
| D1 | Morning brief by call or voice note (opt-in) | OPEN (text brief BUILT) |
| D2 | After-event check-in ("interview kaisa gaya") by voice note or call | OPEN (text BUILT) |
| D3 | Urgent alerts by call | OPEN |
| D4 | Bill-due and appointment reminders by call (opt-in) | OPEN (text BUILT) |
| D5 | Family safety check: a parent did not answer | OPEN, needs consent design |
## E. Assisting during the user's own call
| ID | Use case | Status |
|---|---|---|
| E1 | Live translation / interpreter | OPEN, needs a conference leg or app |
| E2 | Note-taking and summary of the user's own calls | OPEN, needs a conference leg or app; consent of the other party |
| E3 | Whisper prompts and suggestions | PARKED |
## F. What makes it complete (cross-cutting)
Languages and accents, noisy lines, latency, barge-in, simulated coverage for every use case above, approval of every spoken line, safety gate, legal map signed off, recordings policy, abuse limits,
monitoring and a human support path, cost controls, accessibility (elders, speech difficulties), opt-outs on every proactive voice feature.

## Release criteria: "complete v1 voice agent"
A use case counts as shipped only when all hold: (1) its spoken lines are approved by the founder (audio heard); (2) simulated callees cover it in every launch language with the safety invariants passing;
(3) the legal map row is cleared or the risk accepted in writing; (4) it has run on real test calls to allow-listed numbers; (5) monitoring and an off switch exist; (6) the user can see, undo and delete what it did.
Launch set (confirmed by the founder 19 Oct, plus B3 hold-fighting and B10 reminder calls added the same day): A1, A2, B1-B8, B10, C1, C3, C4, C5, C6, C7, D1, D2, D4. Later: A3-A4 regional languages, B9 personal negotiation, B11-B12, C2, D3, D5, E1-E3.

## Note 21 Oct: ElevenLabs Agents ad (docs/COMPETITORS.md update i)
Use cases seen: after-hours receptionist, caller qualification, booking into the calendar, a spoken morning summary the user asks for by voice ("what did I miss?" -> counts, who asked for you). All are in the launch set (C1, C3-C5, D1, A1). New small item: the morning voice summary must support follow-up questions by voice ("read the urgent one", "call them back").

## Decision 21 Oct: always-on / wake word PARKED
Access to Friday is by a button press (a saved contact 'Friday', Action Button, lock-screen control), WhatsApp text, WhatsApp voice note, calling her number, and Friday speaking first. Desk mode and any wake word (A3) stay parked.
