# Proactive Friday and the inbound call conversation (design, 2026-10-12, for founder review)

Rules that already bind this design (HANDOFF 2b, 8.11, 8.13, 8.14): everything runs on our servers; outcome-based,
low noise; proactive ONLY from what the user told Friday (no outside data, no guessing); transactional, never
marketing; opt-in with channel and quiet hours; max 2 per week; calls 09:00-20:00; one-word stop; hear before change.

## A. The inbound call: how the conversation moves
Principle: **the call is for understanding and agreeing, not for doing.** Friday listens, confirms in one breath, hangs
up happy; the work and the answer happen on the server and arrive on WhatsApp (or a call-back if the user prefers).

1. Friday answers, Ritu, Hinglish: greeting + "main Friday, AI assistant" (fixed lines, already built).
2. User says the request, messy and spoken: "yaar kal mummy ke liye ek achha dentist dekh do, Sector 14 ke paas".
3. Classifier + PM (channel = call): bucket (quote / availability / book...), category (clinic), slots found
   (for whom = mummy, when = kal, where = Sector 14). Missing slot -> ONE very short spoken question
   ("Kaunse sheher ka Sector 14, Gurgaon?"). Max 2 questions; long things (full address, pin) are taken on WhatsApp.
4. **Read-back + consent** in one line: "Theek hai: mummy ke liye kal dentist, Sector 14 Gurgaon, main 3 jagah poochhkar
   WhatsApp pe bhej dungi. Kar doon?" -> spoken yes.
5. Hang up. PM runs in the background (`run_background`); outcome goes to WhatsApp. No stage updates.
6. Anything outside scope (complaint, medical advice, random chat): short polite line, goes to the wishlist, one
   line of small talk allowed, then back to the point. Never pretends to do what it cannot.
7. Phone-quality rules: keep every Friday turn under ~12 words; confirm numbers/names back; if STT confidence is low
   ask once, then move the detail to WhatsApp; barge-in always allowed; silence > 6 s -> "Main sun rahi hoon".

## B. Where proactiveness comes from (only the user's own words)
Two small agents (docs/AGENT_ROSTER.md 21, 22), both with closed outputs, code-verified:

**Agent 21 Memory extractor** reads each finished chat/call and stores items like
`{kind: date|followup|concern|preference, what, when?, quote, source_message_id}`; the quote must really appear in
the conversation (code checks) else the item is dropped. Examples:
- "mummy ka birthday 14 ko hai" -> date item (occasion), asks nothing now.
- "AC mein awaaz aa rahi hai, agle hafte decide karunga" -> concern, follow-up ~7 days.
- "haircut ho gaya, ek mahine baad yaad dila dena" -> reminder 30 days.
- After a booking Friday made: appointment time -> reminder + reschedule offer.

**Agent 22 Proactive planner** (rules, no LLM) turns items into scheduled actions: what, when, channel. Hard rules:
opted in; quiet hours; <= 2 per week per user (booking reminders count 1 per booking, cap still applies; the user's
explicit "remind me" requests never count against the cap); dedupe; drop if the user already did it; one-word STOP.

## C. The proactive moments (all tied to something the user said or booked)
| Moment | Trigger (their own words) | Message | Channel default |
|---|---|---|---|
| Appointment reminder + reschedule | a booking Friday made | "Kal 5 baje saloon mein slot hai. Theek hai ya badalna hai?" [Theek / Badlo] | WhatsApp, call if 2 h before and no reply |
| Asked reminder | "ek mahine baad yaad dilana" | "Aapne kaha tha haircut ke liye yaad dilana. Quotes nikaalun?" [Haan / Baad mein] | WhatsApp |
| Decide-later follow-up | "agle hafte decide karunga" | "AC ke baare mein: ab technician ke rates nikaalun?" | WhatsApp |
| Occasion | "mummy ka birthday 14 ko" | day before: "Kal mummy ka birthday hai. Cake/phool arrange karun?" | WhatsApp |
| Unfinished request | no answer from vendors / user did not choose | "Do jagah ne phone nahi uthaya, kal phir try karun?" | WhatsApp |
| Price/slot opened | user asked "tell me if cheaper slot opens" | only if they asked | WhatsApp |
Everything else is NOT sent. No offers, no "tips", no "we miss you".

## D. How a proactive message is delivered
- WhatsApp: inside the 24 h window free text; outside it only a Meta-approved template (task_update/reminder) with
  buttons. Templates need approval (can take days): submit 3 generic transactional templates early.
- Call: user opted in to calls; Friday calls (outbound playbook `user_notify`, short, Ritu), offers a one-tap WhatsApp
  follow-up; if no answer, ONE WhatsApp message instead, never repeated calling.
- Everything logged with consent id; "what do you remember" lists items; delete one/all; "proactive band karo" stops.

## E. Onboarding choices (once)
Channel (WhatsApp default / call), quiet hours (default 21:00-09:00), saved places (self, parents) via the form. The
user can change by text/voice any time.

## F. Build order
1. Memory extractor + store (offline fakes, quote verification) 2. Planner + scheduler tick + cap/quiet-hours tests
3. Reminder + reschedule for Friday-made bookings (first and safest moment) 4. WhatsApp templates + delivery
5. `user_notify` call playbook (pending, audio first) 6. Inbound call -> PM (`handle_turn`, channel=call, spoken lines pending audio).

## G. Decisions needed from the founder
1. Which 2-3 moments first (suggest: appointment reminder+reschedule, asked reminder, decide-later follow-up).
2. Opt-in moment: at first chat, or only when the first proactive item appears ("Shall I remind you? Haan/Nahi")? (suggest the second: less friction, consent in context.)
3. Do user's explicit "remind me" requests count against the 2/week cap? (suggest: no.)
4. Call as a channel: only for time-critical (appointment in < 2 h) or whenever user chose calls?
5. Inbound call: should Friday ever start a vendor search ON the call (spoken yes) or always only confirm and run after hang-up? (suggest: after hang-up.)

## H. The JARVIS model (founder reference, 2026-10-12)
What makes JARVIS feel alive: he (1) knows the context, (2) anticipates the next step, (3) raises a risk before it bites,
(4) offers options with a recommendation, (5) asks only the question that matters, (6) reports briefly, (7) has a
personality. Mapped to Friday, in two layers so the "no noise, no marketing" rules still hold:

**Layer 1: in-conversation proactivity (rich, no cap: the user is already talking to her)**
- *Anticipate the next step:* after quotes, "Sabse kam Style Hub, Rs 450, 2 km. Kal 6 baje ka slot pooch lun?"
- *Smart question, not a form:* "Mummy ke liye hai, toh ghar ke paas wala dekhun? (Unka area: Sector 14, sahi?)"
- *Heads-up:* "Is salon ki recent reviews mein wait time ki shikayat hai. Doosra option 300 rupaye zyada, par jaldi."
- *Recommend with reason:* one pick + one-line why, never a menu of ten.
- *Connect memory:* "Pichli baar aapne beard trim bhi karwaya tha, wo bhi pooch lun?"
- *Notice gaps:* "Budget 500 hai par quotes 600 se shuru. Thoda badhaun ya door ka dekhun?"
- *Summarise the call proof:* "Unhone bola Rs 450, aaj shaam free hain, advance nahi."

**Layer 2: outbound proactivity (Friday speaks first; rare, from the user's own words or bookings)**
Section C above. Jarvis-style wording ("Sir, mummy ka birthday kal hai") but only for things the user told Friday.
Possible later, only with explicit opt-in per theme: recurring services they chose ("har 4 hafte haircut"), watch
requests ("slot khule toh batana"), weather/traffic only for a booking they have.

**Personality:** calm, slightly dry, brief, never salesy; Hinglish; says "main kar deti hoon" not "I will proceed to".
Honest: "Ye mujhse nahi hoga, par ye kar sakti hoon". Voice approved (Ritu); every new spoken line gets audio first.

**What we deliberately do NOT copy from the movie:** acting without being asked on money/bookings (always the owner's
explicit delegation), reading everything about the user (only what they told Friday; connected apps out of phase 1).

**Build for Layer 1 (needs no new infra, biggest wow per effort):** a "next best step" suggestion step at the end of the
PM report and after each user answer: code picks the candidate (cheapest/nearest/best-reviewed/budget gap/memory hit)
from structured data; the LLM (optional) only rewords one sentence. So she never invents facts.

## I. The full personal assistant: Friday sees what the user connects (founder vision, 2026-10-12)
Founder: Friday has access to everything the user has given access to. Example: a mail arrived, the user has not
replied, escalations are coming in -> Friday highlights it. She sits on top of the user's whole daily life and helps.
This replaces the 8.14 limit ("only the user's own conversations") for LATER phases, with consent per source.

### I.1 What she can see (reachable from our servers, so nothing runs on the phone)
| Source | How | Phase |
|---|---|---|
| Gmail | Google OAuth, read-only scopes first | 2 |
| Google Calendar | OAuth | 2 (easiest, ship first) |
| Outlook / Microsoft 365 mail+calendar | OAuth (Graph) | 2-3 |
| Bank/cards/bills/insurance (India) | RBI Account Aggregator (consent-based), plus bill emails | 3 |
| Food/shopping/travel orders | Swiggy/Zomato MCP, order emails | 3 |
| Documents the user sends on WhatsApp (PDF, photo) | already reachable | 2 |
| WhatsApp chats, SMS, photos, app usage, GPS | NOT reachable without an app (user can forward or share) | no |

### I.2 The attention engine (how "highlight the escalation" works)
1. **Ingest** (server): fetch new mail/events with the stored token. Raw text is treated as UNTRUSTED input (prompt injection) and
   is never given tools.
2. **Signal extractor** (closed JSON schema, quote + message id verified by code): kinds = `needs_reply`, `deadline`, `escalation`,
   `payment_due`, `appointment`, `travel`, `delivery`, `renewal`, `unanswered_follow_up`. Rules do the cheap ones (a thread
   where the user was last to be written to, N days old, sender wrote again = escalation count); a small model only classifies
   the unclear ones.
3. **Attention scorer** (rules): urgency (deadline < 24 h, same sender 3 times, words like "final reminder", money, legal,
   boss/customer), importance (who: VIPs the user marked or Friday learnt from reply history), staleness. Output tier:
   `now` (interrupt) / `today` (digest) / `fyi` (only if asked).
4. **Suggestion builder**: for each item code assembles facts; one reworded sentence + a ready action:
   "Rahul (client) ne 3 din mein 3 baar likha: invoice pending. Draft reply bhej dun?" [Draft dikhao] [Baad mein].
5. **Delivery**: `now` = WhatsApp message immediately (rare); `today` = ONE morning digest the user chose the time for;
   anything else only on "kya pending hai?". The 2/week cap from 8.13 applies to *marketing-like* nudges, not to
   this: user-owned alerts are limited by a **noise budget** (default max 3 interrupts/day, learns from "ignore this
   sender" / "not important").
6. **Act only with approval**: draft replies, calendar holds, bill reminders are SHOWN first; sending an email, paying,
   booking = explicit yes each time (delegation rules as for calls). Never silently deletes or sends.

### I.3 Trust and safety (this is the biggest risk of the product)
- Per-source switch, read-only by default, scopes minimal; "what can you see?" lists sources and the last items she used;
  "forget this source" deletes tokens and derived data; disconnect any time; everything audit-logged; DPDP consent record.
- Stored: extracted facts + pointers (message id), NOT whole bodies; tokens encrypted; no data used to train anything.
- Gmail is a *restricted* scope: Google verification + a security assessment (weeks, some cost). **Start the OAuth consent
  screen now** even though the feature ships after beta.
- Sensitive content (health, legal, finance): shown only as "important, open it" unless the user opted in to summaries.
- Prompt injection: email text can contain instructions; the extractor has no tools and its output is schema-checked.

### I.4 Daily-life suggestions (examples once data exists)
Morning digest ("3 cheezein: client ka invoice reply pending, 4 baje dentist, bijli bill kal due"); travel ("Flight kal
6 AM, cab 3:30 pe book karun?"); renewals ("Car insurance 12 din mein expire, quotes nikaalun?" -> goes to vendor calls!);
conflicts ("Dono meetings 5 baje hain, ek shift karun?"); follow-ups after calls. Vendor calling becomes ONE action
inside a larger assistant: signals create tasks for the project manager.

### I.5 Staging
Phase 1 (now): vendor calling, in-conversation proactivity (H). Start now: OAuth verification, noise-budget and consent design.
Phase 2: Calendar + Gmail read-only, signals needs_reply/deadline/escalation/appointment, morning digest, draft replies (approval).
Phase 3: Outlook, Account Aggregator, order/travel sources, learning what matters per user.

### I.6 Decisions needed
1. OK to put this as Phase 2 (after the beta), and start the Google OAuth/verification paperwork now?
2. First source: Calendar (easy, quick win) then Gmail?
3. Interrupt rule: max 3 "now" alerts/day, everything else in one morning digest: OK?
4. Draft-and-approve only (never auto-send) for the first version: OK?
