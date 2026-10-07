# Friday: Phase 1 PRD ("Friday makes calls")

Status: Draft v3 (includes all founder addenda: voice agent, people & places, real-world footwork A1–A13 / B14–B20, customer-care/IVR C21–C26, hotel & stay bookings D27–D29; founder decisions on §10 applied: approval/call-back rule, B16/B17 → Priority 1, no user-facing cap, female voice) · Owner: Product · Source of truth for decisions: `docs/BRIEF.md` (the "Founder requirements for the voice agent" section overrides everything else) · North star: `docs/VISION.md`

Conventions: all times are IST. "WA" means WhatsApp. A **task** is one user goal, for example "book a haircut". A task may involve several **call attempts**. **MUST**, **SHOULD** and **MAY** are used in the RFC sense. Requirement IDs (`US-x.y`) are referenced in tests and tickets.

---

## 1. Goals

| # | Goal | Measured by (see §9) |
|---|---|---|
| G1 | Friday reliably completes real-world phone tasks (bookings and enquiries) | >80% call-task success |
| G2 | Friday becomes a habit, not a novelty | ≥2 requests/user/week by week 3 |
| G3 | Unit economics work | cost per successful call < ₹15 |
| G4 | Businesses tolerate (and later welcome) an AI caller | business hang-up rate < 20% |
| G6 | Friday finds and gets good deals, not just slots | discovery→booking conversion; % of quotes improved by negotiation (§9.2) |
| G5 | Users trust Friday | zero unapproved commitments; every action logged; deletion completed within SLA |

## 2. Non-goals (Phase 1)

- Payments, UPI, deposits, advances, or any money commitment (→ P4). Phone orders are COD, or the user pays the shop directly (A3).
- Physical errands via human runners (→ P3). Government portals and paperwork (→ P4).
- *Customer-care and IVR calls are **in** scope (founder decision; US-30–US-36). Hotel and stay bookings are **in** scope (US-37–US-39), pay-at-hotel or the user's own payment only.*
- Unofficial scraping tools/MCPs for hotels or listings (ToS risk). Only official APIs behind provider interfaces are used.
- Gmail, Calendar, documents, OAuth integrations.
- Lifeline or emergency features (SOS, emergency dispatch). Friday still always points distressed users to 112/108 (US-15). Opt-in wellbeing check-in calls (A13) are in scope, and they are *not* an emergency service.
- Inbound voice (users calling Friday). The voice pipeline MUST be reusable for P2. P1 only plays a fixed message on inbound calls (US-16).
- Business accounts and dashboards.
- Chat in languages other than Hindi, English and Hinglish. *On calls*, Friday mirrors the business's language, including other Indian languages where STT/TTS supports them (US-13). This follows the founder requirement, which overrides the BRIEF's earlier language exclusion.
- Calls to arbitrary private individuals (friends, exes, family, for messages). The allowed exceptions are: service providers' personal mobiles (plumber, maid, tutor), brokers/landlords (A8), and opted-in circle members for check-ins and reminders (A13, US-22).
- Agent-to-agent negotiation.
- Any app or website, beyond a one-time T&C link.

## 3. Target users

| Persona | Who | Typical jobs | Notes |
|---|---|---|---|
| **Busy urban professional** | 25–40, Bengaluru, Delhi NCR or Mumbai. On WA all day, hates phone calls, switches between English and Hinglish | Doctor/dentist appointments, salon, restaurant table, AC service, plumber, "is the pharmacy open / do they have X in stock / what's the price", "find me a good AC repair guy near Indiranagar and get the best price" | Core P1 user. Values speed and not having to talk. |
| **NRI managing parents' errands** | 28–50, in the US, UK, Gulf or Singapore. Parents live in an Indian city | Book a doctor for Papa, get the geyser fixed at Mum's flat, confirm a lab test home-collection slot | Number is foreign (+1/+44/+971). Time zone differs. Calls are made "on behalf of" the user *for* a beneficiary (US-20). Parents may get their own reminders in Hindi or their language (US-22). Very high willingness to pay later. |

Beta launch population: invite-only, about 500–2,000 users seeded from the founders' networks in the three metros.

---

## 4. User stories and acceptance criteria

### US-1 Onboarding via chat

*As a new user I want to set Friday up in under 3 minutes on WA, so I can hand it my first call.*

**US-1.1 Entry.** The first inbound message from an unknown number starts onboarding.
- If there is no valid invite code on the user (see US-2), Friday asks for one: "Friday is invite-only right now. Have an invite code?" A message matching `FRI-[A-Z0-9]{6}` (case-insensitive, spaces/hyphens tolerated) is validated.
- If the user has no code, Friday adds them to the waitlist and replies once. It then sends no further messages until a code arrives or the user is admitted.

**US-1.2 Steps, in order.** Each step is one message. Each step accepts free text or voice notes. Interactive buttons or list messages are used where listed.
1. **Language**: buttons `English` / `हिंदी` / `Hinglish`. If the user simply types in a language, Friday infers it and confirms.
2. **Name**: "What should I call you?" Friday stores the display name and asks for the full name used on bookings: "And the name for bookings?" The default is the display name.
3. **City**: free text, normalised to one of {Bengaluru, Delhi NCR, Mumbai, Other(text)}. "Other" is accepted with a note that P1 works best in the three metros.
4. **Tone**: buttons `Playful` (default) / `Formal`, each shown with a one-line sample.
5. **Consent (DPDP)**: Friday sends a consent summary (§8 `consent_summary`) and a one-time T&C link. The user MUST reply `I agree`, `I AGREE`, `agree`, `मैं सहमत हूँ` or `haan, agree`, or tap the `I agree` button. The message also confirms that the user is 18+.
   - Friday stores: user_id, consent text version, T&C version, the exact message text or button ID, the WA message ID, a timestamp and the channel.
   - If the user replies anything else, Friday re-asks up to 2 times. After that it pauses onboarding ("No problem. Say 'start' whenever you're ready.").
   - No data beyond language, name and city is stored before consent. Anything captured before consent is deleted if the user never consents within 7 days.
6. **PIN**: "Set a 4-digit Friday PIN. I'll ask for it before sensitive things like deleting your data."
   - Friday rejects `0000`–`9999` repdigits, `1234`, `4321`, `1212`, `2580` and `0852`, and asks again.
   - The user confirms by re-entering the PIN.
   - The PIN is stored only as a salted hash (argon2id). It is never echoed back or logged in plaintext. Friday advises the user to delete the PIN message from their chat.
7. **Circle and places (optional, skippable with one tap)**:
   - "Do you look after anyone else, like parents, spouse or kids? I can book for them too." `Add someone` / `Skip`. Adding someone collects name, relation, phone and language (US-20).
   - "Save your home and office? Share a location pin or type the area." `Share` / `Skip` (US-21).
   - Each prompt is one message. For non-Indian numbers (likely NRIs), Friday asks about family first.
8. **First task**: "Last thing. What's one call you've been avoiding? I'll make it now." An example list (rotated) is included.

**US-1.3** Onboarding is resumable. If the user drops off, the next message resumes at the pending step. After 24h of inactivity mid-onboarding, Friday sends nothing (it is outside the WA window, and P1 sends no re-engagement template).

**US-1.4** The user can skip tone (default Playful), city, and circle/places. They cannot skip consent or PIN. If a step's answer is unclear, Friday asks for it again, at most twice.

**US-1.5** On completion Friday sends a short capability card: what it can do, examples of how to delegate ("any slot 5–7 pm under ₹800, you decide"), and the `help` command. Event `onboarding_completed` is logged with the duration.

**US-1.6** Target: median onboarding completion of 3 minutes or less. Completion rate ≥70% of users who send a valid invite code.

### US-2 Invites, cost tracking and abuse limits

- **US-2.1** Each activated user gets **5 invite codes** (`FRI-XXXXXX`, single-use, no expiry in beta). The `invite` command lists the codes and whether each has been used. Founders/admins can mint unlimited codes.
- **US-2.2** Redeeming a code links the invitee to the inviter (`invited_by`). A used, revoked or unknown code is rejected with: "That code doesn't work. Check with whoever gave it to you?"
- **US-2.3 No user-facing usage cap in the beta (founder decision).** Friday never mentions calls left, limits or resets to users, and there are no cap templates.
- **US-2.4 Internal cost tracking.** Every task records its cost per leg (telephony, STT, TTS, LLM, WA/SMS, places/hotel API) in paise. Per-user daily and monthly totals feed an ops dashboard. Ops is alerted when a user exceeds configurable thresholds (default ₹500/day or ₹3,000/month) or when cost per successful task drifts above target.
- **US-2.5 Abuse rate-limit (ops-configurable, off by default for invited users).** When ops enables it for a user or globally, it limits tasks per hour/day and call legs per day. A limited user gets a neutral message ("I'm handling a lot right now. I'll pick this up at 2:30 PM.") with the task queued, never a "cap reached" message. The anti-abuse rules per target number (US-6.4) always apply.
- **US-2.6** In-flight tasks (including scheduled retries and call-backs) always complete, even if a rate-limit is switched on mid-task.

### US-3 Booking call

*As a user I want to say "book a haircut at Looks Salon Saturday morning" and have Friday call and book it.*

**US-3.1 Intake.** The user may send text or a voice note (transcribed; if STT confidence is low, Friday echoes its interpretation). Friday extracts a **task spec** with these fields:
- `type=booking`
- `business` (name, phone)
- `service`
- `date/time window` (normalised to absolute IST datetimes)
- `party_size` (restaurants)
- `constraints` (e.g. "female stylist")
- `budget` (max acceptable price, a target price if given, and what must be included). See US-18
- `flexibility` (e.g. "any time after 4")
- `beneficiary` (default: the user)
- `shareable_info` (see US-3.7)

**US-3.2 Phone number resolution**, in priority order:
1. A number in the message or a shared contact card (vCard).
2. A business previously called, from memory (fuzzy name match).
3. If the user named a business but no number: a places-provider lookup by name and city. Friday confirms the match ("Looks Salon, 100 Ft Rd Indiranagar, 4.4★?") before dialling.
4. If the user named no business ("find me a good salon nearby"): the discovery flow (US-17).
5. Otherwise, ask the user: "What's their number? You can share the contact too."

Number rules:
- Indian landlines need an STD code, and Friday asks for it if missing (it may be inferred from the user's city).
- Indian mobiles are accepted.
- Toll-free (1800/1860) and short codes (e.g. 121, 198) are allowed **only** for verified customer-care numbers from the official directory (US-35).
- Premium-rate numbers, emergency numbers and international numbers are declined, with a reason.
- Numbers that are not user-supplied pass the scam check (US-25) before Friday calls them or shares details.

**US-3.3 Missing info.** Before calling, Friday asks for at most **2** clarifying questions, combined into one message where possible. Required fields are: a business (or a discovery request), service, and a date or date window. Anything else is optional. Friday works out the rest on the call, within the stated flexibility.

**US-3.4 Confirm before dialling.** The user's request is their approval, so Friday does not ask "shall I call?". It sends: "Calling Looks Salon now for a haircut, Sat 11 Oct, 9 AM–12 PM. I'll come back to you with their options before confirming." If the user delegated, Friday echoes the limits instead (US-3.11).
- If the business-call window is closed (outside **09:00–20:30 IST**, or outside known or learned hours for that business, US-28), Friday queues the call for the next good window and says so.

**US-3.5 The call** is goal-driven, using the call brief in §5. The booking is **successful** only when all of these hold:
- the user approved the slot and price, either on the call-back route or within an explicit delegation (US-3.11);
- the business has explicitly confirmed date, time and service;
- Friday has read them back and received a "yes".

**US-3.6** If no slot fits the constraints, Friday collects the nearest alternatives and uses the call-back route (US-3.11).

**US-3.11 Approval rule: call back by default, confirm on the call only with explicit delegation (founder decision; overrides autonomy settings).**
- **Default: call-back route.**
  1. When the business offers slot(s) and a price, Friday does **not** confirm on the call. She collects the options, price, inclusions and how long they can keep the slot. She asks the business to keep it if possible, and says: "Main Ankit ji se confirm karke aapko 10–15 minute mein call back karti hoon." ("I'll confirm with Ankit and call you back in 10–15 minutes.") She then ends the call politely.
  2. Within 60 s Friday sends the user the options as buttons (US-5.3 format), e.g. `[10:00 AM] [12:30 PM] [None]`.
  3. On approval she places a **confirmation call-back**, part of the same task. She re-checks the slot and price, confirms, reads back the details and gets a "yes". If the user picked something different ("ask for Sunday"), she relays that instead, and any new offer goes back through this route.
  4. If the slot was lost in the meantime, she offers the business's next options to the user, again via call-back.
  5. Options expire after 2 h, or at the business's stated keep-time if shorter. Friday then says: "The offer may have lapsed. Call again for fresh slots?"
- **Exception: delegated decision.** Friday may confirm on the call itself only if the user **explicitly** gave authority when giving the task, as a window and/or ceiling or a "you decide". Examples:
  - "book any slot between 5–7 pm under ₹800, you decide";
  - "Saturday morning, whatever's free, up to ₹600, just book it";
  - tapping `Book it` on a nudge or option that names an exact slot and price ("Looks, Sat 11 AM, ₹600, like usual?").
  Within those limits Friday chooses the best option (earliest by default) and confirms on the call. **Anything outside the limits** (time, price, inclusions, staff, an advance) falls back to the call-back route.
  - Delegation is captured at intake as `delegation: {windows, max_price_inr, other_limits, source_message_id}` and echoed back before dialling: "I'll book any slot 5–7 pm under ₹800 without checking back."
  - A budget alone ("under ₹600") is a negotiation limit, **not** delegation.
- **Recurring bookings** (A12): explicit delegation for the rule (time window + price ceiling) is authority for each instance. Deviations take the call-back route.
- The autonomy level never substitutes for delegation: level 4 means Friday places the call unprompted, not that she confirms on it.
- Friday never confirms "provisionally". The approval or delegation source (WA message or button ID, timestamp) is stored on the task and in the action log.

**US-3.7 Info sharing.**
- Friday may share the user's booking name and, for bookings, their registered mobile number. The user can turn the number off.
- For home services Friday may share the address only if the user gave it for this task or approved a stored address ("Use your Indiranagar address?").
- Nothing else is shared.

**US-3.8** Friday never agrees to pay, prepay, put down a deposit or give card/UPI details. If the business requires an advance, Friday says "I'll confirm with <name> and get back to you", ends the call and escalates.

**US-3.9 On behalf of someone else.** If `beneficiary` ≠ user, the disclosure names both: "…calling on behalf of Ankit Verma, for his father Mr. Suresh Verma." The beneficiary is resolved from, or saved into, the user's circle (US-20). Their linked place gives the default search area and home-visit address (US-21). What Friday shares follows US-22.4.

**US-3.10** On success, Friday creates an **appointment** in memory (business, datetime, service, address if known, beneficiary). It then schedules the reminder (US-9.1) and, where applicable, the follow-up (US-9.2). If the beneficiary has opted in, the beneficiary's confirmation and reminders follow US-22.3.

### US-4 Enquiry call

*As a user I want to ask "is Apollo Pharmacy Koramangala open and do they have Dolo 650?" and get an answer.*

- **US-4.1** The task spec has `type=enquiry`, the business and a list of **questions** (max 5 per call; extras are queued as a second task or trimmed after asking the user).
- **US-4.2** Friday asks every question and records an answer for each one: `answered` with the value, `unknown` ("they didn't know"), or `refused`. The call is successful when ≥1 question is answered and none was skipped by Friday.
- **US-4.3** Prices are recorded verbatim with units ("₹450 per visit, ₹150 extra if parts"). Friday never treats a quote as a commitment.
- **US-4.4** If the answer makes a natural next action obvious ("they have stock and close at 10"), the report offers one-tap actions: `Book it` / `Remind me at 7` / `Done`.
- **US-4.5** Enquiries about multiple businesses ("call these 3 plumbers, who's cheapest for a tap fix tomorrow?") follow the compare flow in US-17.4–17.6, whether the user supplied the numbers or Friday discovered them.

### US-5 Mid-call question to the user

*As a user, I want to answer quick clarifying questions without being on the call. Under the approval rule, booking choices are normally made on the call-back route (US-3.11), not mid-call.*

- **US-5.1** Mid-call questions are used only for **clarifications the business needs to continue** that are not a commitment: "male or female stylist?", "which branch?", "does Dad need a wheelchair?", "do you want gas top-up quoted too?". Slot, price and order approvals use the call-back route by default (US-3.11). Details the brief already covers are decided without asking.
- **US-5.2** On the call, Friday says plainly: "One moment please, I'm checking with Ankit." ("Ek minute ji, main Ankit se confirm kar rahi hoon.") If the wait exceeds 20 s, it gives one factual status line ("Still waiting for Ankit's reply. Thank you for holding."). There are no filler sounds or fake hesitations (US-19).
- **US-5.3** On WA (inside the 24h window), Friday sends an interactive message headed with the business name:
  - ≤3 options use reply buttons. 4–10 options use a list message.
  - "None of these" is always available as the last button or row.
  - Free-text and voice-note replies are also parsed ("6 wala", "later one", "neither, ask for Sunday").
- **US-5.4** If the 24h window has closed (rare, e.g. a retry the next day), Friday sends the `friday_call_question` template (fixed button `Answer now`). Tapping it opens the window, and the interactive options follow immediately.
- **US-5.5 Timeout.** Friday waits up to **45 s** for an answer.
  - If no answer arrives, Friday tells the business she'll call back, ends the call politely and continues on the call-back route (US-3.11).
- **US-5.6** A maximum of **2 mid-call questions per call**. After that, Friday wraps up with the best info it has and asks the user afterwards.
- **US-5.7** A reply to an expired option gets: "That offer may have lapsed. Want me to call them back and ask for '6 PM'?" with buttons `Yes, call` / `No`.
- **US-5.8** If the user has concurrent calls (US-23), each question clearly names its business, and replies are matched by the WA `context.message_id`. Free text that can't be matched triggers a clarifying question.

### US-6 Call outcomes and retry policy

Every attempt ends with exactly one `outcome`. Retries are automatic. The user is informed according to the "User message" column.

| Outcome | Detection | Retry policy | User message |
|---|---|---|---|
| `success` | Goal confirmed and read back | None | Result report (US-7) |
| `partial` | Some goal met (e.g. an enquiry with some answers unknown) | None, but offer a follow-up action | Report listing what's missing |
| `busy` | Busy signal / SIP 486 | Retry at +10 min and +30 min (3 attempts total) | Only after the final failure, or if the user asks for status |
| `no_answer` | Ringing ≥30 s with no pickup / SIP 480/408 | Retry at +20 min and +90 min (3 attempts) | As above |
| `unreachable` | Switched off, out of coverage, or network error | Retry at +30 min and +2 h (3 attempts) | As above |
| `voicemail` | Answering machine detected | Treated as `no_answer`. Friday never leaves a voicemail in P1 | As above |
| `ivr` | IVR menu detected | The IVR navigator takes over (US-31). If it can't reach a human, the outcome is `no_answer`, rescheduled per US-28 | As above |
| `hold_timeout` | Max hold exceeded (US-34.4) | Reschedule at the best-known time for that line | Immediate, with the new time |
| `verification_required` | Agent requires the account holder and the patch-in failed (US-33) | None automatic. Friday sends the callback pack | Immediate |
| `call_back_later` | Business says "call after 5", "call tomorrow" or "busy right now" | One callback at the stated time (+5 min), within the call window. If vague ("later"), +2 h. Max 2 callbacks per task | Immediate: "Salon asked me to call after 5. I'll call at 5:05." |
| `business_refused` | "We don't talk to robots" after one polite retry, a hang-up within 15 s of the disclosure, or a refusal of service | **No retry** | Immediate. Friday offers the number so the user can call themselves, plus a `Try another place` option |
| `wrong_number` | "Wrong number" / not the named business | **No retry** | Immediate: "That number isn't Looks Salon. Got the right one?" The number is marked invalid for that business in memory |
| `dropped` | Call disconnected mid-conversation before the outcome was confirmed | One immediate redial ("Sorry ji, call cut ho gaya") and then normal `no_answer` rules | Only if the final result fails |
| `do_not_call` | Business says "don't call this number again" | No retry. The number is added to the **global** Friday DNC list | Immediate, with the number shared |
| `escalated` | Friday needs a user decision it couldn't get (deposit, constraint conflict, unclear) | Waits for the user | Immediate, with options |
| `failed_system` | Telephony, STT or LLM failure | One automatic retry after 5 min, then report | Apology plus `Retry` button |

Rules:
- **US-6.1** All retries happen only within the business-call window (09:00–20:30 IST). Retries that fall outside it roll to 09:30 the next day. That rolled retry counts as an attempt and needs the user's go-ahead if the task is time-sensitive and the original date has passed.
- **US-6.2** After the final failed attempt Friday sends one consolidated message: what happened, the attempt times, and buttons `Try again tomorrow` / `I'll call myself` (sends the number) / `Cancel`.
- **US-6.3** The user can ask "status?" at any time and get the live state of every open task.
- **US-6.4 Anti-abuse.** Max **3 call tasks to the same number per user per day**, and max **10 Friday call attempts to the same number per day across all users**. Numbers on the global DNC list are never called.
- **US-6.5 Call limits.** Max call duration is **6 min** (customer-care calls: US-34.6). If the business puts Friday on hold for more than 2 min, Friday ends the call and treats it as `call_back_later` (+30 min).

### US-7 Result report

- **US-7.1** Friday sends the report within **60 s** of call end (p95). Format:
  - **Line 1, the headline outcome**: "Booked. Looks Salon, Sat 11 Oct, 11:00 AM, haircut with Priya."
  - **Details block**: date, time, service, person, price quoted, address, reference number if given, any notes the business gave ("come 10 min early", "cash only").
  - **Next steps**: what Friday will do ("Reminder Sat 9 AM") and one-tap actions (`Add note` / `Reschedule` / `Cancel booking`).
- **US-7.2 Recording**: sent as a WA audio message (voice note) if it is ≤16 MB and ≤5 min. Otherwise Friday sends a one-time, expiring (24 h) link. Recordings are kept for **30 days** (open question Q5), then deleted. The user can say "send recording" for any call in the last 30 days.
- **US-7.3** A **transcript** is available on request ("transcript?"). Friday sends it as a text message, split if needed.
- **US-7.4** Failed or partial reports always say *why*, in one line, and offer the next action.
- **US-7.5** Every task writes an **action log** entry: who, what, when, numbers dialled, outcome, info shared. "What did you do this week?" returns a summary of the log.
- **US-7.6** Booking cancellation or reschedule ("cancel my salon booking") is task type A1 (§5B).

### US-8 Memory

- **US-8.1 Profile**: name, booking name, city, language, tone, quiet-hours override (none in P1), briefing opt-in and time, autonomy settings. People (US-20) and places (US-21) are memory too, and are covered by "what do you know about me" and "forget".
- **US-8.2 Businesses**: for each business Friday has called it stores name, number(s), city/area, category, hours learned, staff names, prices quoted (with dates), last visit, and call outcomes. On a later request, "Looks" resolves to the known business. If more than one candidate matches, Friday asks. This is extended by vendor memory (US-29).
- **US-8.3 Facts and dates.** Friday extracts facts from any user message, including messages not about tasks: "rent due on 5th", "insurance expires in March", "Maa's birthday is 12 Dec", "I'm vegetarian".
  - Each fact stores `subject`, `predicate`, `value`, `recurrence` (none/monthly/yearly), the `source_message_id`, a `confidence` score and `created_at`.
  - Facts with confidence ≥0.8 are saved, and Friday acknowledges them inline in ≤1 short line ("Noted: rent due on the 5th, I'll remind you on the 4th.").
  - Facts below 0.8 are confirmed with a question first.
  - Facts are never extracted from call audio of the business side beyond the task's own results.
- **US-8.4 "What do you know about me?"** returns a grouped list (profile, people, places, dates, preferences). Each item can be removed via "forget …" (US-11).
- **US-8.5** Memory is per user. A beneficiary's data belongs to the user who added it. Two users who both add the same parent get two separate profiles; there is no sharing in P1.
- **US-8.7** Facts can be about people in the circle ("Dad's BP check every 3 months", "Mom's birthday 12 Dec"). They are stored with `subject=person_id` and drive nudges to the user (US-22.6).
- **US-8.6** Memory is used in calls only to the extent of US-3.7. It is never volunteered to businesses.

### US-9 Proactive v1

Definitions:
- **Unprompted message**: any message Friday starts that is not (a) a reply to the user, (b) a mid-call question, (c) a result or status update of a user-requested task, or (d) a reminder for an appointment Friday booked.
- Unprompted messages are subject to **US-10 guardrails**. Types (c) and (d) are exempt from the daily cap but still respect quiet hours (except `urgent`).

**US-9.1 Task reminders.**
- Reminders are sent for appointments Friday booked: the evening before at 20:00 (if the appointment is before 12:00) and 2 h before. If the 2 h reminder falls in quiet hours, it is sent at 21:00 the previous night instead (if not already covered) or at 08:00.
- Every reminder includes the address and buttons `Got it` / `Running late` / `Reschedule`.
  - `Running late` asks "How late?" and offers to call the business to inform them. This is a new task, which counts as a call and is approved by the tap.

**US-9.2 Follow-ups.**
- For home-service bookings (the full workflow is A5), Friday sends a check at slot end + 1 h: "Did the plumber come?" with `Yes, all done` / `No-show, call them` / `Still waiting`.
  - `No-show` triggers a call task that asks for an ETA or reschedules.
- For enquiries with an obvious next step left untaken, Friday sends at most one follow-up after 24 h, then drops it.
- After service appointments, Friday may optionally ask once "How was it?" to learn preferences. This counts as unprompted.

**US-9.3 Date nudges from facts.**
- Recurring and one-off dates trigger a nudge at a configurable lead time. Defaults:
  - bills/rent: 1 day before
  - renewals/expiries: 30 days and 7 days before
  - birthdays/anniversaries: 3 days before
- Nudges may be about people in the circle, e.g. "Dad's BP check is due next week. Book the usual clinic near their home?" (US-22.6).
- Every nudge MUST offer an action, e.g. "Maa's birthday is Friday. Want me to call Theobroma and order her usual cake?" with `Yes, call` / `Remind me Thursday` / `Not needed`.

**US-9.4 Pattern nudges.**
- Friday detects repeated tasks: ≥2 occurrences of the same category with the same business, with a roughly regular interval (stdev ≤ 30% of the mean).
- It nudges at mean interval + 0–3 days, e.g. "4 weeks since your haircut. Looks, Sat 11 AM like usual?" with `Book it` / `Not now` / `Stop these`.
- Max 1 pattern nudge per category per cycle.

**US-9.5 Morning briefing (opt-in only).**
- Friday offers it once, after the user's 3rd completed task. It never offers it during onboarding.
- Delivery time defaults to 08:00 and can be set between 07:00 and 10:00.
- Contents, ≤6 lines: today's appointments, dates due in the next 3 days, open tasks, and at most one suggestion with an action.
- **If there is nothing to say, Friday skips that day.**
- The briefing does not count towards the 3/day cap. It counts as 1 if it contains a suggestion.
- Outside the 24h window it uses the `friday_morning_briefing` template.
- `briefing off` stops it.

### US-10 Autonomy levels and guardrails

**US-10.1 Levels**, set per category:

| Level | Name | Behaviour |
|---|---|---|
| 1 | Inform | Friday tells the user; no action offered beyond acknowledging |
| 2 | Suggest | Friday tells the user and offers a one-tap action (**default for all categories**) |
| 3 | Act with approval | Friday prepares everything, e.g. "I'll call Looks for Sat 11 AM. Go?"; one tap executes |
| 4 | Act automatically | Friday starts the action without asking, then reports. Requires **explicit opt-in and the PIN** for that category. Level 4 starts calls unprompted. It does **not** grant authority to confirm: bookings follow US-3.11 (call-back unless explicitly delegated; recurring-rule delegation counts). Fully automatic results apply only to enquiries, reminders and follow-up calls |

**Categories (P1):** `health` (doctor, dentist, lab), `personal_care` (salon, spa), `dining`, `home_services`, `enquiries`, `follow_ups` (no-show calls, confirmation calls), `reminders`.

- Level 4 is never allowed for anything involving money. Bookings that require a deposit always escalate.
- Level 4 is not offered for `health` in P1.
- Level 4 actions still respect caps, the call window and guardrails.
- Each level-4 action is reported with an `Undo` button where an undo is possible (e.g. cancel the booking).
- The user sets levels by command ("autonomy", or "always rebook my haircut automatically"). Friday confirms the category and level and asks for the PIN when going to level 4.
- Friday SHOULD suggest raising a level after the user accepts the same kind of nudge 3 times in a row. It suggests this at most once per category per 30 days.

**US-10.2 Guardrails** (enforced in one central policy service; every proactive send goes through it):
1. **Cap**: max **3 unprompted messages per user per IST day**. Messages marked `urgent` are exempt. In P1 only these are `urgent`: a booking cancelled or changed by the business, and an appointment reminder <2 h away.
2. **Quiet hours: 22:00–08:00 IST.** No unprompted or reminder messages. Messages are queued to 08:00, or dropped if stale by then. Exempt: replies to user messages (if the user writes at 23:00, Friday answers), mid-call questions for calls already in progress, and safety messages. Business calls never happen in quiet hours (the call window is 09:00–20:30).
3. **Ignore-learning.**
   - A nudge is `ignored` if the user doesn't interact with it within 24 h. It is `dismissed` if they tap `Not now` / `Not needed`.
   - After **2 consecutive ignores/dismissals** of a nudge type in a category, Friday doubles that type's interval or lead threshold.
   - After **3**, it suppresses that type for 30 days and mentions this once, in the next user-initiated conversation: "I've stopped haircut reminders since you didn't seem to need them. Say 'turn on haircut reminders' anytime."
   - An acceptance resets the counter.
4. **Every nudge is actionable**: it carries ≥1 action button. A nudge with no possible action is not sent. Level-1 inform messages are the exception, and they still carry `Got it` / `Stop these`.
5. **24h window.** Free-form WA messages are sent only within 24 h of the user's last inbound message. Outside that window Friday MUST use an approved template (§8). If no template fits, the message is not sent. It may be queued until the user next writes, if still relevant.
6. **Dedupe**: never send two nudges about the same entity within 24 h. When nudges compete, Friday ranks them by urgency × confidence × user acceptance history and keeps the top 3.

### US-11 User commands

Commands are recognised in any supported language and phrasing (LLM intent classification with the examples below). Each command gets an explicit confirmation.

| Command (examples) | Behaviour | PIN? |
|---|---|---|
| "forget my rent date", "bhool jao Maa ka address" | Finds the matching memory item(s) and shows them: "Forget 'rent due on 5th'?" with `Forget` / `Cancel`. Deletes the item and any scheduled nudges derived from it | No |
| "delete everything", "mera sab data delete karo" | Lists what will be deleted (profile, memory, recordings, transcripts, logs) and asks for the PIN, then for the word `DELETE`. Cancels pending tasks, revokes unused invites and hard-deletes within **24 h** (open question Q7 on retained records). Final message: "Done. Everything's deleted. If you ever come back, just say hi." | **Yes** |
| "stop telling me about haircuts", "birthday wale messages band karo" | Suppresses that nudge topic or category permanently (until turned back on). Confirms with the scope | No |
| "change language to Hindi", "speak English" | Applies immediately to chat, templates and the default language for future calls | No |
| "change tone", "be more formal" | Switches Formal/Playful | No |
| "pause", "pause for a week", "chup raho 2 din" | Pauses all unprompted messages, briefings and level-3/4 actions. Duration options: `1 day` / `1 week` / `Until I say`. Results of in-flight tasks and appointment reminders still arrive. "resume" undoes it | No |
| "status" | Lists open tasks | No |
| "history", "what did you do this week" | Summarises the action log | No |
| "what do you know about me" | Memory summary (US-8.4) | No |
| "send recording" / "transcript" | US-7.2 / US-7.3 | No |
| "autonomy" | Shows the levels per category and lets the user change them | Only for → level 4 |
| "briefing on/off/at 7:30" | US-9.5 | No |
| "invite" | US-2.1 | No |
| "change PIN" | Old PIN, then new PIN twice | **Yes** |
| "help" | Capability card | No |

- **US-11.1** PIN entry: **5 wrong attempts** lock PIN-gated actions for 30 min. After 3 lockouts in 24 h, Friday requires support-assisted reset. PIN reset flow: see Q8.
- **US-11.2** Friday never asks for the PIN in a template and never during a call. It only asks in a direct chat flow the user started.

### US-12 Post-call business touch

- **US-12.1** After a `success` booking, Friday sends the business one confirmation:
  - by **SMS (DLT template `biz_booking_confirmation`)** if the number is a mobile, or
  - by **WA template** if the number is known to be on WA (preferred when available).
  - Landlines get nothing.
- **US-12.2** After a `success` or `partial` enquiry, Friday MAY send `biz_enquiry_thanks`. This is limited to **once per business per 30 days** across all users.
- **US-12.3** Nothing is sent after `business_refused`, `wrong_number` or `do_not_call`, or to DNC numbers. Every message includes an opt-out. "STOP" adds the number to the global DNC list (for business touches **and** calls; the user is told if their future task targets it).
- **US-12.4** The touch must not reveal more than the call did: the customer's booking name, date, time and service only.
- **US-12.5** Friday logs `business_touch_sent` along with the business ID, so the business-acquisition funnel can later be built from it.

### US-13 Language handling

- **US-13.1** Chat language follows the user's setting. Mid-conversation, Friday mirrors the user's language in each reply. If the user switches 3 times in a row, Friday asks whether to update the default.
- **US-13.2 Call language mirroring (founder requirement).**
  - Friday always opens in **Hinglish**. The disclosure line is fixed in Hinglish (§5.1).
  - Friday detects the language of **each** business turn (STT language ID plus an LLM check for code-mixing). If the dominant language differs from the one Friday is speaking for **1 full turn** (≥4 words, confidence ≥0.7), Friday switches on its very next utterance. Supported: Hindi, English, Hinglish, and Tamil, Telugu, Kannada, Marathi and Bengali where the configured STT *and* TTS providers support them (a capability flag per provider).
  - If the rep switches again mid-call, Friday switches again. There is no limit on switches.
  - If the rep's language is unsupported, Friday continues in Hinglish, offers English ("Can we continue in English or Hindi?") and, failing that, ends politely (E20).
  - Every switch is logged (`call_language_switched`). Friday stores the business's preferred language in memory and uses it to open the next call, **after** the fixed Hinglish disclosure line.
  - Reports to the user are always in the user's chat language. Quotes are translated, and the original-language wording is kept in the transcript.
- **US-13.3** Hindi chat is in Devanagari or Roman script, matching the user.

### US-14 Voice notes from the user

- **US-14.1** Inbound WA voice notes up to 3 min are transcribed. Anything longer gets: "That's a long one. Could you split it?"
- **US-14.2** If the transcript confidence is low or the intent is ambiguous, Friday restates its understanding before acting: "You want me to book the dentist for Papa on Saturday, right?"
- **US-14.3** Friday replies in text by default. Voice replies are P2.

### US-15 Safety minimum (P1, not Lifeline)

- **US-15.1** If a message signals danger or distress (medical emergency, violence, self-harm, fire), Friday overrides tone and caps. It replies immediately with 112 (all emergencies), 108 (ambulance) and Tele-MANAS 14416 (mental health) as relevant, and states that it cannot call emergency services.
- **US-15.2** Friday does not attempt calls to emergency numbers. It logs `safety_signal_detected` for review.

### US-16 Inbound calls to Friday's number (P1 stub)

- **US-16.1** Businesses may call back the caller ID Friday used. P1 answers with a fixed bilingual TTS message: "This is Friday, an AI assistant. I called you on behalf of a customer. I'll call you back shortly." The call is then ended. If the caller number matches an active task, Friday notifies the user and schedules a callback within the call window (it counts as a retry).
- **US-16.2** Unknown callers: the call is logged and nothing more happens.
- **US-16.3** The handler MUST use the same voice pipeline interfaces as outbound, so P2 can replace the stub.

---

### US-17 Discovery → shortlist → call → compare → book (founder requirement)

*As a user I want to say "find me a good AC repair guy near Indiranagar, budget ₹600" and have Friday find, vet, call and compare options, then book the one I pick.*

- **US-17.1 Trigger.** Discovery runs when a request has a category or service but no business identified ("a good dentist", "koi achha plumber"). It also runs when the user taps `Find another place` after a failure. The location comes from the request ("near Indiranagar"), a saved place ("near my office", "papa ke ghar ke paas"; see US-21) or a WA location pin. If none of these is available, Friday asks once.
- **US-17.2 Search.** Friday queries the places provider (behind an interface, with a fake for local/tests) for up to 20 candidates within a radius. The default radius is 3 km, widening to 6 km if fewer than 5 results are found. Friday then filters out:
  - candidates that are permanently closed;
  - candidates with no phone number;
  - toll-free/IVR-only numbers;
  - numbers on the global DNC list;
  - businesses the user marked "never again".
- **US-17.3 Vet and shortlist.** Friday reads ratings, review counts and recent reviews (up to 10 most recent and most relevant per candidate). It then shortlists the **top 3** (configurable 2–5).
  - Ranking: rating (Bayesian-adjusted by review count), recency of reviews, review mentions relevant to the task ("on time", "fair price", "overcharged", "rude"), distance, open hours for the requested slot, and the user's history (previously used = boost; bad experience = exclude).
  - Every shortlisted business gets a **≤12-word reason** grounded in the review text ("4.6★ (310), reviews praise on-time visits and fair pricing"). Friday never fabricates a review claim. Each reason must be traceable to stored review snippets.
  - Red flags found in reviews ("asked for advance and never came") are shown to the user as a warning, or exclude the candidate.
- **US-17.4 Shortlist message and approval.** Friday sends the shortlist as a WA list message (name, ★, distance, reason) with `Call all 3` / `Pick which to call` / `Search again`.
  - If the user's autonomy level for the category is ≥3 *and* the request said "just handle it", Friday may skip this step and go straight to calling. It states which businesses it will call.
- **US-17.5 Call and compare.** Friday calls the shortlisted businesses **sequentially** (default; it uses quotes from earlier calls as negotiation leverage, US-18) or in parallel (US-23) when the user is in a hurry. Each call is an enquiry/quote call with a common question set taken from the call brief (price, inclusions, earliest slot, visit charge).
  - **No booking is confirmed during compare calls.** Friday asks each business to hold its offered slot where possible ("Can you hold Saturday 11 AM for an hour while I confirm?").
- **US-17.6 Comparison report** within 60 s of the last call:
  - a table-like message with business, price (incl./excl.), earliest slot, rating and notes;
  - a **recommendation with a one-line reason**;
  - buttons `Book <A>` / `Book <B>` / `Book <C>` (or a list for more options), plus `None, search more`.
  - Businesses that refused or couldn't be reached are listed with their outcome.
- **US-17.7 Book the pick.** The user's tap is the approval. Friday places the confirmation call-back (US-3.11) and re-checks for any change in price or slot. It then follows US-3.5/US-3.10.
- **US-17.8 Cost.** Discovery costs (places API plus all legs) are tracked per task (US-2.4). There is no user-facing cap.
- **US-17.9 Memory.** All shortlisted and called businesses are saved, with quotes and dates. Friday remembers the user's pick and any rejection reason for future ranking.
- **US-17.10 Attribution.** Rating and review data are shown per the provider's attribution requirements ("Ratings from Google"). Raw review text is not stored beyond the provider's caching terms.

### US-18 Price quotes and negotiation (founder requirement)

*As a user I want Friday to get me the best price within my budget without committing me to anything.*

- **US-18.1 Inputs** (from the call brief): `budget.max` (hard ceiling), `budget.target` (optional), `must_include` (e.g. "gas top-up included"), `negotiation_room` (`none` / `polite` (default) / `firm`), and competing quotes already collected in this task (US-17).
- **US-18.2 Quote capture.** For every price, Friday clarifies what is included and excluded, the visit or inspection charge, taxes, parts, and the validity of the quote. It records the quote in a structured form: amount, unit, inclusions, exclusions, conditions and verbatim text.
- **US-18.3 Negotiation tactics.** These are allowed when `negotiation_room` ≠ `none`, at most **2 asks per call** for `polite` and 3 for `firm`, always courteous:
  - asking for a discount ("Kuch kam ho sakta hai? Regular customer ban sakte hain." — "Could you do it for a bit less? They could become a regular customer.");
  - citing competing quotes truthfully, without naming the competitor unless the user allowed it ("Another service quoted ₹450 including gas");
  - asking for package or bundle deals (two ACs, service plus gas top-up);
  - asking for waivers (visit charge waived if the work is done) and off-peak or weekday pricing.
- **US-18.4 Never lie.** Friday never invents competing quotes, budgets, urgency or loyalty. "Regular customer" style lines are used only if true (from memory) or phrased as a possibility.
- **US-18.5 Never commit.** Friday never says "done, we'll pay X". Without delegation, her closing line on a quote is always of the form "Thank you, I'll confirm with Ankit and call you back." Agreement happens only through the approval rule (US-3.11): a call-back after the user approves, or on the call within an explicit delegation ceiling. The price is always stated as the *booking price quoted*, not as a payment commitment.
- **US-18.6 Over budget.** If the best price after negotiation is above `budget.max`, Friday doesn't escalate mid-call by default. It thanks the business, asks them to hold the slot if one is offered, and reports: "Best I got: ₹750 (your limit ₹600). Book anyway / Try others / Leave it."
- **US-18.7 Report.** The result report shows the original quote → the final quote and what changed ("₹700 → ₹600, gas top-up included"). The event `negotiation_outcome` logs both amounts.
- **US-18.8 Respect a firm no.** If the business says the price is fixed, Friday accepts it on the first refusal and moves on.

### US-19 Voice and AI identity (founder requirement)

- **US-19.1** Every call's first utterance is the fixed disclosure line (§5.1). It cannot be modified by the LLM and is inserted by the call engine as pre-rendered TTS.
- **US-19.2** If asked in any form ("aap insaan ho?" — "are you a human?", "is this a recording?", "are you a bot?"), Friday answers truthfully in the rep's language within one turn: it is an AI assistant calling for <name>. A post-call audit flags any transcript where Friday claims or implies being human (`hard_rule_violation_detected`).
- **US-19.3 Voice spec:** a clean, calm, polished, confident voice (JARVIS / F.R.I.D.A.Y.). One consistent voice per language across all calls, with a moderate pace (~150 wpm in English, slightly slower when reading numbers back).
- **US-19.4** No synthetic fillers ("umm", "uh", "hmm"), fake breaths, fake typing or keyboard sounds, or artificial hesitation pauses. The TTS configuration MUST disable any "humanising" disfluency features. LLM output is filtered to strip filler tokens before TTS.
- **US-19.5** Latency is handled by engineering (streaming STT → LLM → TTS; target p50 turn latency < 1.2 s), not by filler words. When a real wait is needed (checking with the user, a slow lookup), Friday says one plain sentence about what it is doing and then stays quiet.
- **US-19.6** Short acknowledgements that carry meaning ("Ji", "Theek hai" — "Okay", "Understood") are allowed, because they are real responses, not fillers.

### US-20 People: the user's circle (founder requirement)

*As a user, especially an NRI, I want Friday to know the people I look after, so I can say "book a doctor for papa" and it just works.*

- **US-20.1 Person profile:** `name`, `relation` (mom, dad, spouse, child, friend, grandparent, other: free text), `aliases` ("papa", "Dad", "pitaji"), `phone`, `preferred_language` (any language Friday can *call or SMS* in, e.g. Marathi), `age` (optional), `linked places` (US-21), `notes` (free text, e.g. "diabetic, prefers morning appointments", "only speaks Marathi"), `beneficiary_consent` status (US-22) and `share_with_business` overrides.
- **US-20.2 Adding people.**
  - **In chat:** "add my dad, +91 98xxxx, lives in Jaipur". Friday extracts the fields, confirms them in one message and asks for at most one missing important field (language, if the phone is given).
  - **Implicitly:** during a task ("book for my mom Sunita"), Friday offers `Save Sunita as Mom?`.
  - **During onboarding** (US-1.2 step 7).
- **US-20.3 Requester vs beneficiary.** Every task has a `requester_id` (always the user) and a `beneficiary_id` (the user, or a person in their circle).
  - On calls, Friday discloses both: "calling on behalf of Ankit Verma, for his father Mr. Suresh Verma".
  - The beneficiary's `preferred_language` sets the language of beneficiary-facing messages. Call language mirroring is unchanged (US-13.2).
  - Beneficiary notes shape the call brief ("prefers morning", "needs wheelchair access", "speaks Marathi; the doctor should be told"), but are shared with the business only as needed (US-22.4).
- **US-20.4 Recognition.** Friday resolves references in English, Hindi and Hinglish: "papa", "mummy", "my wife", "Nani", "his place", "uske liye" ("for him/her") (from conversation context).
  - If 2+ people match, Friday asks once with buttons ("Your dad Suresh or Priya's dad Ramesh?").
  - Friday learns new aliases from corrections and confirmations ("Nani's" = grandma) and stores them on the person.
- **US-20.5 Managing.** Commands: "who's in my circle", "update dad's number", "remove Priya", "forget dad's notes". Removing a person deletes their profile, places that only they use, consent records (except the legally required receipt) and their scheduled nudges. Past action-log entries remain, with the name redacted.
- **US-20.6 Limits:** up to 15 people per user in beta.

### US-21 Places (founder requirement)

- **US-21.1 Place:** `label` ("Home", "Office", "Mom & Dad's home", "PG", "Priya's place"), `aliases`, `address` (text), `lat/lng`, `geocode_confidence`, `linked people`, `notes` ("gate 2, 3rd floor, no lift") and `source`.
- **US-21.2 Creation sources:**
  - a typed or spoken address (geocoded via the places provider; Friday confirms with the formatted address and locality);
  - a pasted Google Maps link (resolved to lat/lng and an address);
  - a **WhatsApp location pin** (lat/lng, reverse-geocoded).
  Friday then asks for the label if it isn't obvious ("Save this as Home, Office, or something else?").
- **US-21.3 No background location.** Friday never assumes the user's current location. "Near me" means the most recently shared live or current pin if it is <2 h old. Otherwise Friday asks: "Share your location or tell me the area?"
- **US-21.4 Recognition.** "near my office", "papa ke ghar ke paas" ("near papa's house"), "their place" and "PG" resolve to a saved place, via people links where needed ("papa's home" = the place linked to Dad with label home). Ambiguity gets one question with buttons ("Mom & Dad's Pune home or the Delhi flat?"). New aliases are learned on confirmation.
- **US-21.5 Use.**
  - Places are used as the discovery search centre (US-17).
  - They are the source of the home-visit address (shared only per US-22.4).
  - They give the city or STD-code context for number resolution.
  - Their address goes in appointment reminders.
- **US-21.6 Commands:** "my places", "update office address", "remove PG".
- Location data is stored in India and deleted with the user's data or the place.

### US-22 Beneficiary communication and consent (founder requirement)

- **US-22.1** Friday sends **nothing** to a beneficiary until that person has **opted in once**. The opt-in request is sent only when the user asks for it ("Want me to send dad the confirmation and reminders too?" → `Yes, ask him`).
- **US-22.2 Opt-in message** to the beneficiary, in their preferred language. Friday uses WA (template `friday_beneficiary_optin`) if the number is on WA, otherwise DLT SMS (`ben_optin`).
  - The message names the requester, explains what Friday will send, and asks the person to reply `HAAN`/`YES` (or `1`). A reply of `NO`/`STOP` declines.
  - For feature-phone parents, the user may choose a **voice opt-in call**. Friday discloses that it is an AI, explains in the parent's language and records a spoken "haan" or a DTMF `1`.
  - Friday stores the consent text version, channel, timestamp and the reply or recording as the consent receipt.
  - With no reply in 72 h, Friday tells the user. It does not resend automatically; one resend is allowed on the user's request.
- **US-22.3 What a consenting beneficiary gets** (each counts toward the *beneficiary's own* 3/day cap and quiet hours):
  - a booking confirmation;
  - reminders (evening before, and 2 h before);
  - changes or cancellations.
  All of these go in the beneficiary's language, through their best channel: WA template, then SMS DLT, then a voice reminder call (≤45 s, with the AI disclosure first and the option to press 1 to repeat).
  - The beneficiary can reply `STOP` anytime. Replies other than STOP/HAAN/repeat are relayed to the requester ("Dad replied: 'thoda late ho jaunga'" — "I'll be a little late") and are **not** treated as commands. Beneficiaries cannot instruct Friday in P1.
- **US-22.4 Minimum sharing with businesses.**
  - Friday shares the beneficiary's name and phone (if the user allowed it).
  - It shares the address only for home visits.
  - It shares age, gender or a medical context only if the business asks *and* it is needed for the booking (e.g. "a senior citizen, needs ground-floor access"), and only from the notes the user wrote.
  - Notes are never read out wholesale.
- **US-22.5 No cross-sharing.** Information about one person is never sent to another person in the circle. For example, mom's notes or appointments are not included in dad's reminders. The only exception is when the user explicitly sets up a shared reminder ("remind both mom and dad").
- **US-22.6 Proactive nudges about people** (US-9.3/9.4) go to the **user** (the requester), not the beneficiary, e.g. "Dad's BP check is due next week. Book the usual clinic near their home?" They obey the user's caps and autonomy. Booking still needs approval (US-3.11).
- **US-22.7 Data rights.** A beneficiary who replies `STOP` or asks "delete my data" has their contact consent revoked. Friday tells the requester. Removal of the profile is the requester's action, unless the beneficiary requests deletion, in which case it is executed and the user is told (see Q18).

---

## 5. The outbound call: call brief, not script

Founder requirement: **goal-driven, not scripted.** There are no hand-written Q&A trees per business type. The call agent is an LLM conversing freely, given a structured **call brief**. Only two things are fixed: the **disclosure line** (§5.1) and the **hard rules** (§5.4). Everything else (phrasing, ordering, objection handling, negotiation) is the model's judgement within the brief. The examples below are illustrative behaviour for prompt design and evals, not scripts.

### 5.1 Fixed disclosure line (pre-rendered TTS, always the first utterance)

- Default (Hinglish): "Namaste, main Friday hoon, ek AI assistant, **<requester name>** ki taraf se call kar rahi hoon." ("Hello, I'm Friday, an AI assistant calling on behalf of <requester name>.")
- If the beneficiary is not the user, Friday appends: "**<beneficiary>** ke liye." ("…for <beneficiary>.")
- Recording notice (pending Q4): "Yeh call record ho rahi hai." ("This call is being recorded.")

For IVR systems, no disclosure is spoken. The line is said to **every human** who picks up (the first agent and each transferred agent or supervisor, US-34.5). For check-in calls (A13), the line is adapted for the member: "Namaste Mummy ji, main Friday hoon, Ankit ki AI assistant." ("Hello Mummy ji, I'm Friday, Ankit's AI assistant.")

After this line, the LLM takes over, and Friday mirrors the rep's language from the next turn onwards (US-13.2).

### 5.2 Call brief (generated per call by the task engine; the input contract for the call agent)

```yaml
call_brief:
  task_id: T-1234
  goal: "Book an AC service visit (split AC, 1.5 ton) at the beneficiary's home"
  success_criteria:            # what must be true to report success
    - business confirms a date and time slot
    - price and inclusions are clearly stated
    - user approved slot + price via call-back, or offer is within delegation (US-3.11)
  business: {name: "CoolCare Services", phone: "+9198xxxxxxx", known_language: "kn", notes: "rated 4.5, used before in Mar"}
  requester: {name: "Ankit Sharma"}
  beneficiary: {name: "Ankit Sharma", relation: self}
  constraints:
    time_windows: ["2026-10-11T09:00/12:00+05:30", "2026-10-12T09:00/12:00+05:30"]
    must_have: ["gas top-up included or quoted separately"]
    avoid: ["advance payment"]
  budget: {max_inr: 600, target_inr: 500, currency: INR}
  negotiation_room: polite        # none | polite | firm
  competing_quotes: [{label: "another service", amount_inr: 450, includes: ["gas check"]}]
  allowed_disclosures:            # the only facts Friday may share
    name: "Ankit Sharma"
    phone: "+91 98xxxxxx"         # only if user allows (Q11)
    address: "12, 4th Cross, Indiranagar"   # home visits only
    other: []                     # e.g. "senior citizen, needs ground-floor access"
  never_disclose: [pin, otp, payment_details, aadhaar, pan, notes_other_than_listed]
  approval_mode: call_back       # call_back (default) | delegated
  delegation: null                # or {windows: ["...T17:00/19:00"], max_price_inr: 800, other_limits: [], source_message_id: "wamid..."}
  call_back_when:                 # end politely, ask the user, call back (US-3.11)
    - "any slot/price/order to confirm and approval_mode = call_back"
    - "offer outside delegation limits"
    - "price after negotiation > budget.max"
    - "advance/deposit requested"
  ask_user_midcall_when:          # non-committing clarifications only (US-5)
    - "business needs a detail not in this brief to continue"
  questions: []                   # enquiries: what to find out
  language: {open: hinglish, mirror: true, user_report_lang: hinglish}
  limits: {max_duration_s: 360, max_user_questions: 2, max_negotiation_asks: 2}
```

**Acceptance criteria for the brief:**
- The task engine MUST produce a brief that validates against the schema before dialling. If required fields are missing, Friday clarifies with the user first (US-3.3).
- The call agent MUST NOT state any fact not in `allowed_disclosures` or in the business's own statements.
- The agent's structured output at call end is: an `outcome` (US-6), `quotes[]` (US-18.2), `offered_slots[]`, `confirmed_booking` (or null), `answers[]` (enquiries), `languages_used[]`, `user_questions[]` and `notes_for_user`.

### 5.3 Behaviour expectations (eval rubric, not script)

- **Lead with the ask** right after the disclosure, in one sentence.
- **Short turns** of ≤2 sentences, with numbers spoken clearly. Friday reads back every key detail before success (date, time, service, price, inclusions, name, address).
- **Objections** get one courteous attempt, then Friday accepts the answer:
  - "we don't talk to robots" → one brief reassurance about the value and time, then a polite exit → `business_refused`;
  - "call later" → get a time → `call_back_later`;
  - "don't call again" → apologise → `do_not_call`;
  - "give me his number" → only if allowed, else take a message → `escalated`.
- **Honesty:** Friday never claims to be human, never invents competing quotes or facts, and says "I'll check with <requester>" when it doesn't know.
- **Negotiation** per US-18, and **language mirroring** per US-13.2.
- **Voice** per US-19: no fillers or fake hesitations.

**Eval set:** at least 40 simulated business personas (cooperative, rushed, hostile to AI, switches to Kannada, quotes above budget, asks for advance, wrong number, puts on hold) run against the call simulator in CI. The pass criteria are: zero hard-rule violations, correct outcome classification ≥95%, and a language switch within 1 turn.

### 5.4 Hard rules (fixed; enforced in the system prompt, by an output filter before TTS, and by post-call audit)

1. The disclosure line is the first utterance. Friday never claims or implies being human, and answers truthfully when asked.
2. Never say or ask for a PIN, OTP, password, card, UPI or bank details, Aadhaar or PAN.
3. Never agree to pay, prepay, put down a deposit, accept cancellation charges or make any money commitment. Quotes are brought back, not accepted.
4. Never confirm a booking or order on the call unless it is within an explicit delegation. Otherwise use the call-back route (US-3.11).
5. Never share information beyond `allowed_disclosures` (US-3.7, US-22.4).
6. Never lie: no invented quotes, urgency, identity or relationships.
7. **Escalate to the user when uncertain.** Ask, don't guess.
8. Stay on task. The call lasts at most 6 minutes (customer care: 20 min active plus hold). Emergency services are never called.
9. Never key in or speak an identifier that is not approved for this call (US-32). Any OTP spoken on a bridged call is redacted from recordings and transcripts (US-33).
10. Never give medical, legal or financial advice of Friday's own. Relay only what the business said.

---

## 5B. Task-type catalogue (A1–A13 founder "real-world footwork" scope, all **Phase 1 · Priority 1**; A14 customer care and A15 stays are defined further below)

Goal: Phase 1 covers every offline task that today needs a human to phone or coordinate with a business or person. Each task type below is a **CallBrief template** (§5.2) on the same engine. It adds a `task_type`, default goal and constraints, success criteria, a report format and type-specific rules. Rules that apply to every type:
- the hard rules (§5.4);
- the approval rule (US-3.11: call back by default, confirm on the call only within explicit delegation; for orders it covers the items and total price);
- the outcome taxonomy (US-6);
- caps and guardrails (US-2, US-10).

For each type, *the "Report" column is what the user sees on WA*. All reports end with ≤3 one-tap next actions.

| # | Task type (`task_type`) | Example request | CallBrief goal / key constraints | Success criteria | Report to user |
|---|---|---|---|---|---|
| A1 | **Reschedule / cancel** (`booking.reschedule`, `booking.cancel`) | "Move my salon to Sunday", "cancel Dr. Mehta" | Goal: change or cancel an existing booking (looked up in memory by business, date and beneficiary). Constraints: new time windows (reschedule); avoid cancellation fees, and if a fee is mentioned, ask the user (never accept it). The new slot follows the approval rule (US-3.11: call back unless delegated) | Business confirms the cancellation, or the new slot is read back and approved | "Cancelled: Looks Salon, Sat 11 AM. No charge." / "Moved to Sun 12 Oct, 11:30 AM." Reminders are updated automatically, and the beneficiary is notified if opted in |
| A2 | **Reconfirm / running late** (`booking.reconfirm`, `booking.late_notice`) | "Is my 7 pm table still on?", "tell the clinic I'm 20 min late" | Reconfirm: verify that the booking exists with the same details. Late notice: inform the business of a new ETA and ask whether the slot still holds. Constraint: don't accept a new slot without asking the user. Auto-offered from the reminder buttons (`Running late`) | Reconfirm: business confirms the details. Late: business acknowledges and states whether the slot is held | "Confirmed: table for 4 at 7 PM, Toit, under Ankit." / "Clinic knows you'll be 20 min late. Dr. Mehta will still see you, but after the 5:30 patient." |
| A3 | **Phone order** (`order.pharmacy`, `order.kirana`, `order.water`, `order.tiffin`) | "Order Dolo 650 ×2 and ORS from Apollo to dad's home", "2 water cans", "tiffin for the week" | Goal: availability, price per item, total, delivery time and charge, payment mode. Constraints: deliver to a saved place (US-21); payment is **COD or the user's own UPI to the shop**, and Friday never pays (§5.4). Prescription items: share the user-provided prescription image only via WA-to-business (US-24) with user approval. Confirm the order on a call-back after the user approves items and total, or on the call if within a delegated ceiling ("order if under ₹300") | Business confirms items, total, delivery ETA and address read-back, with user approval recorded | "Ordered from Apollo Malviya Nagar: Dolo 650 ×2, ORS ×4, ₹186 + ₹0 delivery, COD, ETA 45 min to Dad's home." Follow-up at ETA+30 min: `Arrived?` |
| A4 | **Availability / stock hunt** (`hunt.stock`) | "Which chemist near Dad's home has Insulin Glargine?" | Goal: find the first business that has X (exact item, strength, quantity), near a place, open now or at a time. Uses discovery (US-17) without a shortlist approval step, then **parallel calls** (US-23) in ranked batches. **Stop at first confirmed match**: in-flight calls finish politely, and queued calls are cancelled. Optional: ask the matching shop to hold the item | ≥1 business confirms stock (item + quantity), with price and hours | "Found it: Wellness Forever, 900 m from Dad's home, has 3 pens, ₹780 each, open till 11 PM. Holding 1 till 8 PM. (Checked 4 shops.)" with `Order for delivery` / `Send address to Dad` |
| A5 | **Service-provider coordination** (`service.coordinate`) | "Plumber was supposed to come at 11, chase him", "is the electrician on the way?" | Goal: get an ETA, chase no-shows, confirm arrival and confirm the work is done with the user. Runs as a **workflow** of calls and checks: confirm the day before (A2), ETA call at slot start if not arrived, chase at +30 min, ask the user "Did the work get done?" Constraint: escalate to the user if the provider asks for an advance or a revised price | Provider arrives (user confirms) and the user confirms the work is complete, or a firm new time is agreed | "Ravi (plumber) says he's 20 min away, stuck at Silk Board." → later: "Done? [Yes, all fixed] [Not fixed] [Didn't come]". Price and reliability go to vendor memory (US-29) |
| A6 | **Status chasing** (`status.chase`) | "Is my phone repair done?", "has the tailor finished the blouse?", "where's my refund from the furniture shop?" | Goal: current status, expected ready date, pickup or delivery, any amount due (noted, never agreed). Context from memory (job, date given, receipt number if any). Polite persistence: re-chase at the promised date | Business gives a concrete status and date | "Mobile Care: screen replaced, ready after 6 PM today, ₹2,400 due (as quoted)." Auto-reminder or re-chase is scheduled on the promised date |
| A7 | **Complaint to a local business** (`complaint.local`, non-IVR) | "The dry cleaner ruined my shirt, ask them to fix it" | Goal: state the issue factually and get a remedy (redo, replacement, refund or discount) with a date. Constraints: **calm, firm, never threatening, no legal threats, no abuse**; only the facts the user gave; the remedy the user wants (and the minimum acceptable one) is in the brief; Friday doesn't accept a settlement below the minimum, and asks the user | Business commits to a remedy and a date, or clearly refuses | "Fresh Cleaners agreed to re-clean free and deliver by Fri. If you want a refund instead, I can push." / Refused → options `Escalate in writing (WA)` / `Drop it` |
| A8 | **Rental hunting** (`hunt.rental`) | "2BHK in HSR under ₹35k, bachelors OK, pet-friendly" | Goal: per listing (from user-shared listing numbers or broker/landlord numbers found via discovery): rent, deposit, maintenance, brokerage, bachelors/pets/food rules, availability date, visit slots. Constraints: **no token or advance** (§5.4); only basic disclosures (name, tenant type as given); visit slots need approval. Parallel calling, results compared | ≥1 listing with full answers, and visit slots offered | Comparison table: rent · deposit · brokerage · rules · visit slots, flagging rule mismatches. `Book visit <A>` / `Book visits for top 2` |
| A9 | **Big-ticket quotes and negotiation** (`quote.bigticket`: packers & movers, event or wedding vendors, venues, car service, interiors) | "Get 4 quotes for moving a 2BHK Bengaluru → Pune on 1 Nov" | Goal: comparable quotes on a **standardised spec** (inventory, distance, dates, inclusions such as insurance, packing material, GST) with negotiation per US-18 (`firm` allowed). Accept WA-sent quote PDFs and photos (US-24). Constraint: no advance or booking amount; site-survey visits need approval | ≥3 comparable quotes (or all reachable), normalised with inclusions | Normalised comparison (₹ total incl. GST, inclusions ✓/✗, rating, red flags), initial → negotiated price, and a recommendation. `Book survey with <A>` / `Push <B> lower` |
| A10 | **Family healthcare** (`health.*`: doctor slot, lab home collection, physio, nurse or attendant home visit) | "Lab home collection for Mom's thyroid test tomorrow 7 am", "find a night attendant for Dad" | Goal: slot, practitioner/agency, fees, preparation instructions (fasting etc.), what to bring. Beneficiary from the circle (US-20); minimum medical disclosure (US-22.4). **Never gives or relays medical advice of its own**, only the business's instructions verbatim | Booking confirmed with prep instructions captured, and the user has approved | "Booked: Thyrocare home collection for Mom, Thu 7–7:30 AM, ₹450 COD. **Prep: 10–12 h fasting.**" The prep reminder goes to Mom at 21:00 the previous night if she opted in |
| A11 | **Enquiries: tutors, coaching, admissions, gyms** (`enquiry.education`, `enquiry.fitness`) | "Find maths tutors for class 8 near home, home tuition, under ₹4k/month" | Goal: fee structure, schedule, mode (home/centre/online), trial class, admission process and deadlines, documents. Parallel calling and comparison. Booking a trial class or visit needs approval | Answers to ≥80% of the brief's questions for ≥2 options | Comparison plus key dates ("Admission form due 15 Nov"). Deadlines are saved as facts and drive date nudges |
| A12 | **Recurring bookings** (`booking.recurring`) | "Weekly physio for Dad, Tue & Fri 10 am", "haircut every 4 weeks", "AC service every quarter" | Goal: a booking series. The user explicitly delegates a **recurrence rule (time window) + business + price ceiling** once. This is authority for each instance (US-3.11, founder decision). Each instance is booked on the call ahead of time (lead: weekly → 3 days, monthly → 7 days). Any deviation (slot, price, staff) → call-back route | Each instance is booked within the rule; the series continues until stopped | Per instance: "Booked next physio: Tue 14 Oct 10 AM (series 3 of ∞)." `Skip this one` / `Pause series` / `Stop series`. Series are listed under "my recurring" |
| A13 | **Wellbeing check-in calls** to a circle member (`checkin.wellbeing`) | "Call Mom and Dad every morning at 10 to check in" | Goal: a short, warm call (≤3 min) in the member's language. Friday asks about medicines taken, how they're feeling, sleep and food, and whether anything is needed. **Requires the member's own opt-in** (US-22 mechanism, check-in specific consent). Schedule and frequency are set by the user and agreed by the member. Friday never gives medical advice; health questions → "I'll tell Ankit" (and 112/108 if urgent) | Call connected and answered; summary delivered | Daily summary (≤3 lines): "Mom: took BP meds ✅, slept well, wants coriander and atta (I can order?)." **Alert** (urgent, exempt from quiet hours and cap) if: no answer on 3 attempts across 2 h; distress words; mentions of a fall, chest pain, breathlessness or confusion; or a skipped critical medicine. Format: "⚠ Dad sounded unwell: said he's dizzy since morning. [Call Dad now (warm transfer)] [Call his doctor] [Listen to recording]" |

**Catalogue acceptance criteria:**
- **C.1** Each task type ships with: a brief template, a JSON schema for its structured result, a report formatter, ≥5 simulator personas in the eval set, and an entry in the intent classifier with Hindi, English and Hinglish examples.
- **C.2** The intent classifier maps a request to a type with ≥90% accuracy on the labelled set. If unsure, Friday asks one question ("Want me to order it, or just check who has it?").
- **C.3** A13 calls are to private individuals. They are allowed *only* for opted-in circle members (this updates the non-goal in §2). Check-in calls respect the member's quiet hours (default 09:00–20:00 local IST). The member can say "don't call tomorrow" or "stop calling", and Friday tells the user.
- **C.4** Phone orders (A3) and anything with a price follow US-3.11. The call-back route applies unless the user delegated, e.g. "order it if under ₹300". Friday states the payment mode (COD or the user pays the shop directly) and never pays itself.

### US-23 Parallel calling (B14 · Phase 1 · Priority 1)

- **US-23.1** A task may fan out to N call legs with configurable concurrency. The defaults are **3 per task** and **5 per user**; a global limit applies per telephony number pool. This supersedes the concurrency limit of 2 in US-4.5, US-5.8, US-17.5 and E23.
- **US-23.2 Strategies:**
  - `all` (collect from all: quotes, rentals, A9, A11);
  - `first_match` (stop at the first success: A4);
  - `sequential_leverage` (one at a time, to use quotes as leverage: the US-17 default when negotiating).
  The task engine picks the strategy per type, and the user can override it ("call them all at once").
- **US-23.3** On `first_match`, Friday stops dialling new legs within 2 s of a confirmed match. Live legs end politely within one turn ("Thank you, I've found it elsewhere. Have a good day.").
- **US-23.4** Mid-call questions from parallel legs are **batched** where possible ("2 shops offer delivery: A ₹40 in 30 min, B free in 90 min. Which?"). Each question names its business (US-5.8). Legs waiting on the user hold or call back per US-5.5.
- **US-23.5** The aggregated report comes within 60 s of the last leg. It lists every leg's outcome. Unreached businesses get `Retry these`.
- **US-23.6** Cost is tracked per leg and per task (US-2.4). There is no user-facing cap.

### US-24 WhatsApp-to-business channel with document extraction (B15 · Phase 1 · Priority 1)

- **US-24.1** Friday may message a business on WA, from Friday's WA Business number, when:
  1. the call fails (`no_answer`/`busy` after the 2nd attempt) and the number is on WA;
  2. the business asks "WhatsApp kar do" ("just WhatsApp it") or offers to send a menu, price list or quote;
  3. the brief requires a document (A9 quotes, A3 prescription sharing).
- **US-24.2** The first message is the approved template `friday_biz_request` (AI disclosure, on behalf of <name>, the ask). After the business replies, free-form messages are allowed within 24 h.
  - Friday never sends user-identifying data beyond `allowed_disclosures`.
  - It sends a prescription image only with the user's per-task approval.
- **US-24.3** Inbound business media (images, PDFs, voice notes) are extracted with Claude vision/LLM into structured data: line items, prices, inclusions, validity, dates, totals, and GST yes/no. Each extracted value carries a confidence score. Totals are cross-checked against the line items, and a mismatch is flagged.
- **US-24.4** The extracted data feeds the same report and comparison as call results. The source file is forwarded to the user on request ("show me their quote").
- **US-24.5** Users may also send images and PDFs (prescriptions, quotes, listing screenshots, bills). These are extracted the same way and confirmed before use. This updates E22.
- **US-24.6** Business WA threads are logged in the action log. A business can reply STOP, which applies DNC to the WA channel (US-12.3).

### US-25 Scam / fake-number check (B16 · Phase 1 · Priority 1, founder decision)

- **US-25.1** Before calling a number, or sharing any detail with it, that was not supplied directly by the user or already verified, Friday computes a **trust score**. Signals:
  - the number matches the places-provider listing for that business;
  - the number appears on the official website;
  - there are multiple consistent listings;
  - Friday has past call history with it (vendor memory);
  - it is on the internal known-scam list or matches crowd reports;
  - the listing is very new or has very few reviews;
  - the number is a mobile that claims to be a big brand's "customer care".
- **US-25.2** For scores below the threshold, Friday warns the user before calling ("This number isn't on Blue Dart's official site, and 3 people reported it. Still call?"). Friday never calls "customer care" numbers found only in search snippets.
- **US-25.3** On calls, scam patterns trigger an immediate polite exit and a warning to the user: requests for OTPs, a "refund processing fee", an app install or screen sharing, or KYC updates. The number is added to the internal scam list after review.

### US-26 Warm transfer / three-way call (B17 · Phase 1 · Priority 1, founder decision)

- **US-26.1** When the business insists on speaking to the user, the right person is finally on the line (e.g. the doctor's assistant), or the user taps `Connect me`, Friday asks the business "May I connect Ankit on this call?" Friday then dials the user's registered number (or the beneficiary's, with consent) and bridges the legs.
- **US-26.2** Before bridging, Friday gives the user a **≤15 s whisper brief** on their leg only: "Connecting you to Dr. Meena's receptionist. They need Dad's previous report dates. The slot is Tue 11 AM, ₹1,300."
- **US-26.3** If the user doesn't answer within 25 s, Friday returns to the business: "Ankit isn't available. I'll have him call you back." → `escalated`.
- **US-26.4** After the bridge, Friday stays on silently by default to take notes and produce the report. The user can say "Friday, drop off" to have it leave. The recording continues only while Friday is on the call. The disclosure is repeated to the business at the bridge ("Ankit is joining now; I'm still on the line as his AI assistant").
- **US-26.5** For international users (NRIs) the transfer uses the user's registered number. If cost is above a set threshold, Friday asks first ("This will connect an international call; OK?").

### US-27 Live translator mode (B18 · Phase 1 · Priority 2)

- **US-27.1** The user asks: "Call the Chennai landlord and translate for me", or taps `Translate live` when a business speaks a language the user doesn't. Friday sets up a three-way call (US-26) with translation on.
- **US-27.2** Friday translates each utterance both ways (user language ↔ business language, from the supported set in US-13.2). Latency targets are p50 < 2 s per turn. Friday speaks translations in its own voice, prefixed on the first turn with "I'm Friday, an AI assistant translating for Ankit."
- **US-27.3** Friday translates faithfully and adds nothing. Hard rules still apply to Friday's *own* speech. If the user speaks a PIN or OTP, Friday does not translate it, and it warns the user.
- **US-27.4** The report includes a bilingual transcript and key agreed points.

### US-28 Call timing intelligence (B19 · Phase 1 · Priority 1)

- **US-28.1** For each business, Friday maintains `hours` (from the places provider and learned from calls), lunch closures, weekly off-days (e.g. Sunday or Tuesday closures common for salons), holidays, and **best-time-to-call** (the hour-of-week with the highest historical answer rate across all Friday calls to that business and category).
- **US-28.2** The outer call window (09:00–20:30 IST) remains a hard bound, or 09:00–20:00 for private individuals (A13). Within it, the scheduler:
  - places calls when the business is open;
  - avoids 13:00–14:30 for clinics and small shops unless the business is known to answer then;
  - avoids opening rush for restaurants (19:30–21:00);
  - prefers the best-time slot when the task isn't urgent.
- **US-28.3 Call queue.** Tasks waiting for a window are queued with an ETA shown to the user ("Clinic opens at 5 PM. I'll call at 5:05."). Queued tasks survive restarts and are re-ranked by deadline.
- **US-28.4** Each call result updates the learned hours ("closed on Tuesdays" said by the business → stored).

### US-29 Vendor memory (B20 · Phase 1 · Priority 1)

- **US-29.1** For every business or provider the user has used or quoted, Friday stores per user: prices **quoted** and **paid** (the paid price comes from user confirmation after service), dates, services, reliability (on-time, no-show, rescheduled counts), the user's rating (asked once after service, 1–5 via buttons), notes, the people involved ("Ramesh, electrician") and the preferred language.
- **US-29.2 Used in:**
  - **recommendations**: "your usual electrician Ramesh, ₹400 last time, always on time" ranks first;
  - **negotiation leverage** (US-18): "Last time it was ₹400" (only if true);
  - **discovery ranking** (US-17.3);
  - **scam checks** (US-25).
- **US-29.3** Commands: "my vendors", "who's my usual plumber", "never use FrostFix again" (excluded from discovery and recommendations).
- **US-29.4** Vendor memory is per user and is not shared across users in P1. Aggregate, anonymised answer rates and hours are shared to support US-28.

**Out of Phase 1 (founder):**
- payments and advances → P4;
- physical errands via human runners → P3;
- government portals and paperwork → P4.

### Customer-care / IVR calls (C21–C26, founder decision: **in Phase 1**)

These calls run on the same engine, with an IVR navigator, a hold-listening mode and stricter verification rules. They add catalogue entry **A14** below. Dependencies: the official-number directory (US-35) and the scam check (US-25) are **mandatory** for this flow. Warm transfer (US-26) is needed for account-holder verification. B16 and B17 are Priority 1 (founder decision).

| # | Task type | Example request | CallBrief goal / key constraints | Success criteria | Report to user |
|---|---|---|---|---|---|
| A14 | **Customer care** (`care.complaint`, `care.refund`, `care.dispute`, `care.cancel`, `care.service_request`, `care.ticket_status`, `care.escalate`) for telecom, broadband, banks/cards, insurers, e-commerce/food delivery, airlines, utilities | "Airtel broadband was down 5 days, get me a refund", "cancel my Swiggy One", "status of my HDFC card dispute" | Goal: the specific resolution (refund amount or credit, cancellation, ticket, status). Constraints: the official number only (US-35); `allowed_identifiers` approved for this call (US-32); target and minimum acceptable outcome; escalate if the first agent can't resolve; **never** read OTP/PIN/CVV/passwords; never accept charges | Resolution confirmed by an agent with a **ticket/reference number**, or a ticket raised with a promised date and agent name | "Airtel agreed ₹350 credit on next bill. Ticket 2-58XXXXXX9, agent Neha, credit by 20 Oct. I'll check your bill after that." `Listen` / `Escalate further` / `Done` |

### US-30 Customer-care task intake (C21)

- **US-30.1** Friday identifies the company and the issue type (complaint, refund, dispute, cancellation, service request, ticket status or escalation). It then collects the facts needed: dates, amounts, order/booking/account references, previous ticket numbers and what the user wants (target and minimum).
  - Friday asks at most 3 questions, in one message where possible.
  - It accepts screenshots and PDFs of bills, orders and emails (US-24.5).
- **US-30.2** Friday shows a **pre-call summary** for approval: the company, the official number it will call (US-35), what it will ask for, and **exactly which identifiers it will share**. Buttons: `Go` / `Edit`. No call starts without `Go`. This approval also covers identifier sharing per US-32. The target and minimum outcome in the summary count as an **explicit delegation** (US-3.11): Friday may accept a resolution at or above the minimum on the call. Anything below the minimum, or anything that costs the user money, takes the call-back route.
- **US-30.3** Status updates during long calls: "In the queue for Airtel. Estimated wait ~12 min. I'll ping you when a human picks up." There are at most 3 progress messages per call. These are task-lifecycle messages, so they are exempt from the cap but not from quiet hours. Customer-care calls run 09:00–20:30 unless the line is 24×7 and the user asks.

### US-31 IVR navigation (C22)

- **US-31.1** Friday understands spoken IVR menus in Hindi and English (and other supported languages when offered). It selects options by **DTMF** or by speaking, and chooses the IVR's language option matching the brief (default English for IVRs, for recognition accuracy; configurable).
- **US-31.2** The goal is to reach a human agent via the shortest known path. Friday uses (a) **learned IVR maps** per company number (cached menu trees with the path last used successfully and its date) and (b) live menu understanding. It prefers "talk to an agent" or "other queries" options.
- **US-31.3** For prompts such as "enter your registered mobile number / account number / order ID", Friday keys in **only identifiers approved for this task** (US-32). If a prompt asks for something not approved, or for a secret (OTP/PIN/CVV/password/T-PIN), Friday does not enter it. It tries "press 0 / agent" paths, then pauses and asks the user (US-33).
- **US-31.4 Recovery.** If Friday reaches a wrong branch (detected from the menu content), it uses the "go back / main menu" key or redials. Max 3 recovery attempts and 2 redials. A failure is reported along with the menu path explored, and the IVR map is updated.
- **US-31.5** IVR traversal is logged (menu prompts transcribed, keys pressed) in the action log and used to update IVR maps across users. Only menu structure is shared, never user data.

### US-32 Account identifiers and sharing (C22, C24)

- **US-32.1** Users can save account identifiers per company: registered mobile, customer/account ID, policy number, last 4 digits of a card, order ID, PNR. Saving or viewing them requires the PIN. They are encrypted at rest and never put into nudges or templates.
- **US-32.2** Per call, the pre-call summary (US-30.2) lists the identifiers Friday will share. Only those may be keyed or spoken. Anything new requested mid-call needs a mid-call question to the user (US-5).
- **US-32.3** Full card numbers, CVV, OTP, PIN, T-PIN, passwords, net-banking IDs and full Aadhaar are **never stored, never shared and never spoken**. If the user types one in chat, Friday warns them and does not store it.

### US-33 Verification handling (C24)

- **US-33.1** When the agent insists on account-holder verification (OTP, security questions, voice consent from the account holder), Friday says: "I'm an AI assistant and can't share verification codes. I'll connect the account holder now." It then **patches the user in** via warm transfer (US-26), with a whisper brief covering the context gathered so far.
- **US-33.2** If the user is unavailable or declines, Friday gets everything it can without verification (ticket number, process, timelines). It ends the call and sends the user a **callback pack**: the number, the IVR path or keys, the ticket number, what to say, and the documents needed.
- **US-33.3** If the agent reads out an OTP or asks Friday to repeat one, Friday refuses and does not repeat it. Scam patterns trigger US-25.3.

### US-34 Hold handling (C23)

- **US-34.1** Friday detects hold music, queue announcements ("your call is important to us", "estimated wait time") and silence. It then switches to **listening mode**: no LLM turns and no TTS, with only a lightweight classifier (VAD + a hold/human detector) running. The target is ≤10% of the active-conversation cost per minute.
- **US-34.2** If the IVR announces a wait time or queue position, Friday relays it to the user once (US-30.3).
- **US-34.3** When a human greeting is detected ("Hello, Airtel se Neha bol rahi hoon" — "Hello, this is Neha from Airtel"), Friday resumes full mode within **1.5 s**, opening with the disclosure line adapted for the agent (§5.1) and then the ask.
- **US-34.4** Max hold is configurable, defaulting to **25 min per call**. After it, Friday hangs up and reschedules at the best-known time for that line (US-28; e.g. weekday 10–11 AM). It tells the user. Total hold per task is capped at 75 min/day.
- **US-34.5** Agent-initiated holds ("please hold, checking") also use listening mode. Transfers between departments re-trigger the human-detect logic. Each new agent hears the disclosure again.
- **US-34.6** A customer-care call is exempt from the 6-min limit (US-6.5). Active conversation is capped at **20 min** per call, plus hold.

### US-35 Official numbers only (C26)

- **US-35.1** Customer-care numbers come only from Friday's **curated, verified directory**, which is seeded manually for the top ~150 companies across the C21 categories. Each entry has: a source URL from the company's official site or app, the date verified, IVR language options, 24×7 or not, and grievance-officer and nodal-officer contacts where published.
- **US-35.2** User-supplied customer-care numbers must pass the scam check (US-25). If they don't match the directory, Friday warns the user and uses the directory number instead. Numbers from web search snippets are never used.
- **US-35.3** If a company is not in the directory, Friday tells the user it can't verify the number yet, offers to use an official number the user found in the company's app or on a bill (after the scam check), and logs a directory gap.
- **US-35.4** The directory is re-verified every 90 days or on any `wrong_number` outcome.

### US-36 Escalation, ticket capture and follow-up (C25)

- **US-36.1** On every customer-care call Friday MUST capture: the ticket, complaint or reference number (read back digit by digit to confirm), the agent's name/ID, the promised action and the **promised resolution date**. If no ticket is offered, Friday asks for one explicitly.
- **US-36.2** If the first agent can't resolve the issue, or offers less than the user's minimum, Friday politely requests escalation to a supervisor ("Kya aap ise supervisor ko escalate kar sakti hain?" — "Could you escalate this to a supervisor?"), at most twice per call. The outcome is recorded either way.
- **US-36.3** Friday auto-schedules a **follow-up call** for the promised date + 1 working day (cost tracked per task). If the issue is unresolved at follow-up, Friday re-escalates on the same ticket.
- **US-36.4** After 2 failed follow-ups, or when a promised date is missed by more than 7 days, Friday suggests **formal escalation routes as text guidance**: the company's grievance officer or nodal officer (from the directory), the sector ombudsman or regulator route (e.g. RBI Integrated Ombudsman for banks, TRAI/telecom appellate route for telecom, IRDAI Bima Bharosa for insurers, the National Consumer Helpline), and a draft complaint text with the ticket history. Friday does not file these itself in P1 (portals are P4).
- **US-36.5** All tickets are listed under "my complaints", with status, dates and next follow-up.

### Hotel and stay bookings (D27–D29, founder decision: **in Phase 1**)

Catalogue entry **A15**, on the same engine, plus a `HotelProvider` interface (Expedia Rapid first; Booking.com/Agoda affiliate later) with a simulator for local runs and tests. **Unofficial scraping tools and MCPs are never used** (ToS risk).

| # | Task type | Example request | CallBrief goal / key constraints | Success criteria | Report to user |
|---|---|---|---|---|---|
| A15 | **Stay booking** (`stay.search`, `stay.book`, `stay.reconfirm`, `stay.modify`, `stay.cancel`) | "Homestay in Coorg for Mom & Dad, 14–16 Nov, ground-floor room, under ₹4k/night" | Goal: the best stay matching dates, guests, room type, inclusions and budget. Hybrid: API search plus direct property calls. Constraints: **no payment by Friday**: pay-at-hotel, the user's own payment via the official link, or the property holds against the user's later payment; a hold or booking only after user approval; negotiate the direct rate (US-18); minimum guest data (US-22.4) | Property or API confirms the booking (dates, room, rate, inclusions, cancellation policy, payment mode) **and** written confirmation (WA/SMS/email from the property, or an API confirmation number) is received | "Booked ✅ Misty Woods Homestay, Coorg · 14–16 Nov (2 nights) · Garden cottage, ground floor · ₹3,600/night incl. breakfast (direct; ₹4,200 online) · Pay at check-in · Free cancellation till 11 Nov. Reconfirm call on 13 Nov." |

### US-37 Stay search and compare (D27a)

- **US-37.1 Intake:**
  - required: destination or area, check-in/check-out dates, guests (adults, children with ages), and who the stay is for (a beneficiary from the circle, US-20);
  - optional: budget per night or total, type (hotel/homestay/guesthouse/resort), must-haves (ground floor, lift, veg food, parking, pet-friendly, couple-friendly, early check-in), and refundable vs cheapest.
  Friday asks at most 3 questions. Beneficiary notes apply (e.g. "Dad can't climb stairs" → ground floor or a lift is required).
- **US-37.2 Search.** Friday queries the `HotelProvider` for availability and rates (pay-at-hotel rates are flagged). It enriches results with places-provider ratings and reviews (US-17.3 ranking, with review evidence for must-haves). It adds **offline candidates**: well-rated homestays and guesthouses from the places provider that have a phone number but no API inventory.
- **US-37.3 Shortlist.** Friday presents up to 4 options. Each shows: name, ★, price per night and total, whether the rate is online or "call for direct rate", key inclusions, cancellation policy, and a ≤12-word review-based reason. Buttons: `Call these for direct rates` / `Book <A> online` / `Search again`.
- **US-37.4 Direct-rate calls.** Friday calls shortlisted properties (US-23 parallel, or sequential when it is using leverage). Each call checks:
  - availability for the exact dates and room type;
  - inclusions (breakfast, early check-in/late check-out, extra bed, meals);
  - the cancellation policy;
  - the payment terms (pay at hotel? advance required?).
  Friday then **negotiates the direct rate** within the budget (US-18), e.g. "The online rate is ₹4,200. Can you do better if booked directly?" Calls open in Hinglish and mirror the property's language (e.g. Kannada or English in Coorg, per US-13.2). Properties may send room photos or tariff cards on WA (US-24).
- **US-37.5 Comparison report**: API rates side by side with direct quotes, the recommendation and its reason, and buttons per option. **No booking happens without the user's tap** (call-back route) or an explicit delegation ("any homestay under ₹4k with a ground-floor room, you decide"), per US-3.11.

### US-38 Booking, hold and payment handling (D27b, D28)

- **US-38.1** After the user approves, Friday books through one of these paths, in order of preference:
  1. **Direct, pay at property**: Friday calls back, confirms the room, dates, rate, inclusions, guest name(s) and arrival time, and asks for **written confirmation by WA or SMS** to Friday (or to the guest's number, if approved).
  2. **Direct, held against the user's own payment**: if the property needs an advance, Friday asks them to hold the room for a stated time (e.g. 6 h). Friday relays the property's **official payment details** to the user only after a scam check (US-25: listing match, a payment name consistent with the business, no "pay to personal number" red flags). It then tells the user plainly: "They need ₹3,600 advance. Pay them directly if you're comfortable; I can't pay." The booking is marked confirmed only when the property confirms receipt.
  3. **API booking with pay-at-hotel**, or the user completes the payment via the **official booking or payment link** that Friday sends (a one-time link; Friday never enters card details).
- **US-38.2** Friday never pays, never shares the user's payment details, and never agrees to a non-refundable term without the user's explicit approval of that term.
- **US-38.3** Stored on the booking: property, address, phone, dates, room, rate, inclusions, payment mode and status, cancellation deadline, confirmation number or message, guest(s) and source (API/direct).
- **US-38.4** Reminders:
  - check-in reminder to the user, and to the beneficiary if opted in (US-22), the evening before, with the address, Maps pin, property phone and check-in time;
  - a **cancellation-deadline nudge** 24 h before free cancellation ends, if the trip might change ("Free cancellation ends tomorrow 12 PM. Still going?").

### US-39 Reconfirm, modify, cancel (D28)

- **US-39.1 Reconfirm the day before.** At 11:00 IST on the day before check-in (shifted per US-28), Friday calls the property. It confirms the booking exists with the same room, rate and inclusions, and shares the arrival time. It requests early check-in if wanted.
  - If a discrepancy is found (no record, a different rate, the room is not available), the user gets an **urgent** message with options, and Friday may immediately search for alternatives with `Find alternatives`.
  - API bookings are reconfirmed by calling the property too.
- **US-39.2 Modify** (dates, room, guests, arrival time) by call to the property, or via the API if the booking was made there. Any change to price or policy needs the user's approval before confirming. The new written confirmation is captured.
- **US-39.3 Cancel** by call or API.
  - Before cancelling, Friday states the cancellation policy and any charge to the user, and requires approval if a charge applies.
  - Friday captures a cancellation reference and requests written confirmation.
  - For advances the user paid directly, Friday asks about the refund timeline and records it. A chase follows on the promised date (A6).
- **US-39.4** All stay tasks appear under "my trips".

---

## 6. Sample conversations (WhatsApp)

### 6.1 Onboarding (English, playful)

```
User:   Hi
Friday: Hey! I'm Friday, your assistant who makes calls so you don't have to.
        I'm invite-only right now. Got an invite code?
User:   FRI-7KQ2MX
Friday: You're in 🎉 Which language do you prefer?
        [English] [हिंदी] [Hinglish]
User:   [Hinglish]
Friday: Done. Aapko kya bulaun?
User:   Ankit
Friday: Nice to meet you, Ankit. Bookings ke liye full name? (Default: Ankit)
User:   Ankit Sharma
Friday: Kaunse city mein ho?
User:   blr
Friday: Bengaluru, got it. Mera style kaisa chahiye?
        [Playful: "Ho gaya! Saturday 11 baje."]
        [Formal: "Your appointment is confirmed for Saturday, 11 AM."]
User:   [Playful]
Friday: Ek zaroori cheez. Main aapki details (naam, city, tasks, call recordings)
        India mein store karti hoon, sirf aapke kaam ke liye. Aap kabhi bhi
        "delete everything" bolke sab mita sakte ho. Main har call pe batati hoon
        ki main AI hoon. Full terms: <one-time link>
        Kya aap 18+ ho aur agree karte ho?
        [I agree] [Not now]
User:   [I agree]
Friday: Thanks! Ab ek 4-digit Friday PIN set karo, sensitive kaam ke liye
        (jaise data delete karna).
User:   1234
Friday: Thoda easy hai 😄 Koi aur 4 digits?
User:   7391
Friday: Ek baar aur bhejo confirm karne ke liye.
User:   7391
Friday: PIN set. (Tip: woh message chat se delete kar do.)
        Last cheez: koi ek call jo aap kab se taal rahe ho? Main abhi kar deti hoon.
        e.g. "Dentist appointment Saturday", "AC service ka price poocho"
```

### 6.2 Booking on the default call-back route (Hinglish)

```
User:   Looks salon indiranagar mein sat ko haircut book kar do, 080 4123 4567
Friday: Looks Salon, haircut, Sat 11 Oct. Koi time preference?
User:   subah 11 ke aaspaas
Friday: Theek hai, calling now. Options lekar aapse confirm karungi, phir book.
```
Call 1 (Friday ↔ salon):
```
Friday:   Namaste, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon.
          Saturday subah 11 baje ke aaspaas haircut ka slot mil sakta hai?
Salon:    11 full hai. 10 ya 12:30 hai. ₹600, Priya karegi.
Friday:   Ji, shukriya. Main Ankit ji se confirm karke 10–15 minute mein call back karti hoon.
          Tab tak dono slot rakh sakte hain?
Salon:    12:30 rakh dete hain, 10 ka pakka nahi.
Friday:   Theek hai, thank you ji.
```
WhatsApp:
```
Friday: Looks Salon: 11 full hai. Options (₹600, Priya):
        [10:00 AM (not held)] [12:30 PM (held 15 min)] [None of these]
User:   12:30 wala
Friday: Calling back to confirm…
```
Call 2, the call-back:
```
Friday:   Namaste, main Friday, Ankit Sharma ki AI assistant. Abhi 12:30 ke liye baat hui thi.
          Ankit ji ne 12:30 confirm kiya hai. Toh: Ankit Sharma, haircut, Saturday 11 October, 12:30, Priya ke saath, ₹600. Sahi hai?
Salon:    Haan, done. 10 minute pehle aana.
Friday:   Shukriya ji! Confirmation SMS aa jayega.
```
WhatsApp:
```
Friday: Ho gaya! ✅
        Looks Salon, Indiranagar
        Sat 11 Oct, 12:30 PM · Haircut with Priya
        Price: ₹600 (pay at salon)
        Note: 10 min pehle aana
        Main Sat 10:30 baje remind karungi.
        🎧 [recordings] [Add note] [Reschedule] [Cancel booking]
```

### 6.3 Delegated decision: confirmed on the call (English)

```
User:   Book Dr. Mehta for a cleaning, any slot Thu or Fri between 5 and 7 pm, under ₹1,000. You decide. 080 2345 6789
Friday: Got it. I'll book any slot Thu/Fri 5–7 PM under ₹1,000 without checking back. Calling now.
  (Clinic offers Thu 5:30 PM, ₹800 → within limits → Friday confirms on the call and reads it back.)
Friday: Booked ✅ Dr. Mehta, Thu 9 Oct, 5:30 PM, cleaning, ₹800. Reminder at 3:30.
```
If the clinic had offered only Thu 7:30 PM, or ₹1,200, Friday would have said "I'll confirm with Ankit and call you back" and switched to the call-back route.

### 6.4 Enquiry (English, formal)

```
User:   Can you check if Apollo Pharmacy Koramangala has Dolo 650 and until when they're open? 080 2553 0000
Friday: Calling Apollo Pharmacy, Koramangala now.
Friday: Apollo Pharmacy, Koramangala:
        • Dolo 650: In stock (₹30 per strip of 15)
        • Open until: 10:00 PM today
        [Remind me at 8 PM] [Done]
```

### 6.5 Busy, then retry, then failure

```
Friday: Calling Sharma Plumbing now for a tap repair tomorrow.
        (busy 4:02 → retry 4:12 busy → retry 4:42 no answer)
Friday: Couldn't reach Sharma Plumbing: busy at 4:02 and 4:12, no answer at 4:42.
        [Try again tomorrow 9:30] [I'll call myself] [Cancel]
```

### 6.6 Business refused

```
Friday: Bistro 42 didn't want to talk to an AI assistant, sorry about that.
        Their number is 022 2640 1234 if you'd like to call. Or I can try somewhere else nearby.
        [Find another place] [OK]
```
(`Find another place` runs discovery around the same area, US-17.)

### 6.7 Pattern nudge, with ignore-learning

```
Friday: 4 weeks since your last haircut ✂️ Looks, Sat 11 AM like usual?
        [Book it] [Not now] [Stop these]
User:   [Book it]
Friday: On it, calling Looks now.
```

### 6.8 Date fact capture and nudge (Hinglish)

```
User:   btw mera car insurance march mein expire hota hai
Friday: Noted: car insurance expires in March. Feb mein yaad dila dungi.
        Exact date pata hai?
User:   12 march
Friday: 👍 12 Mar save kar liya.
  …(10 Feb, via template friday_date_nudge since outside the 24h window)…
Friday: Heads up: car insurance expires on 12 Mar. Want me to call your insurer for a renewal quote?
        [Yes, call] [Remind me later] [Not needed]
```

### 6.9 NRI in Dubai: doctor for Dad in Jaipur, Dad gets a Hindi reminder

```
User (+971 50…): Papa ke liye Jaipur mein ek achha cardiologist dhundo, ghar ke paas.
        Next week koi bhi morning. Budget consultation ₹1500 tak.
Friday: Papa = Suresh Verma (68), Jaipur home in Malviya Nagar, right?
        [Haan] [Different person]
User:   [Haan]
Friday: Malviya Nagar ke 3 km mein ye mile:
        1. Dr. R. Gupta Heart Clinic: 4.7★ (520), "explains patiently, on time"
        2. Shalby Hospital Cardiology: 4.4★ (2.1k), big hospital, ECG on-site
        3. Dr. Meena's Clinic: 4.6★ (180), "senior-friendly, ground floor"
        Notes mein likha hai papa morning prefer karte hain aur stairs avoid karte hain. 3 aur 1 best fit lag rahe hain.
        [Call all 3] [Pick which to call] [Search again]
User:   [Call all 3]
Friday: Calling now (Jaipur mein 10:05 AM hai). Slot milte hi poochungi.
  …
Friday: Comparison:
        • Dr. Gupta: ₹1,200 · Tue 14 Oct 10:30 AM · stairs (1st floor, no lift)
        • Shalby: ₹1,000 · Wed 15 Oct 9:00 AM · ECG ₹300 extra
        • Dr. Meena: ₹1,500 → ₹1,300 (senior discount maanga) · Tue 14 Oct 11:00 AM · ground floor
        Recommend: Dr. Meena. Ground floor, papa ke ghar se 1.2 km, budget mein.
        Sab ne slot 1 ghante ke liye hold kiya hai.
        [Book Dr. Meena] [Book Shalby] [Book Dr. Gupta] [None]
User:   [Book Dr. Meena]
Friday: Confirming with Dr. Meena's clinic…
Friday: Booked ✅ Dr. Meena's Clinic, Malviya Nagar, Jaipur
        Tue 14 Oct, 11:00 AM · for Suresh Verma · ₹1,300 at the clinic
        Bring: purani reports aur current medicines ki list
        Papa ko bhi Hindi mein confirmation aur reminder bhejun? Pehle unse ek baar permission leni hogi.
        [Yes, ask him] [No, just me]
User:   [Yes, ask him]
Friday: Sent. Jaise hi papa haan bolenge, bata dungi.
```

Message to Dad (+91 98290…), template `friday_beneficiary_optin`, language `hi`:
```
Friday: नमस्ते सुरेश जी, मैं Friday हूँ, एक AI सहायक। आपके बेटे अंकित ने आपके लिए
        डॉक्टर का अपॉइंटमेंट बुक किया है। क्या मैं आपको इसकी जानकारी और रिमाइंडर भेज सकती हूँ?
        [हाँ] [नहीं]
Dad:    [हाँ]
Friday: धन्यवाद! आपका अपॉइंटमेंट: डॉ. मीना क्लिनिक, मालवीय नगर, मंगलवार 14 अक्टूबर, सुबह 11 बजे।
        पुरानी रिपोर्ट्स साथ लाइएगा।
```
To Ankit: "Papa ne haan bol diya. Unhe Hindi mein reminders milenge."

Mon 13 Oct, 20:00 IST to Dad (template `friday_beneficiary_reminder`, `hi`):
```
Friday: सुरेश जी, याद दिला दूँ: कल मंगलवार सुबह 11 बजे डॉ. मीना क्लिनिक, मालवीय नगर।
        पुरानी रिपोर्ट्स और दवाइयों की लिस्ट साथ रखें।
        [ठीक है] [देर हो जाएगी]
Dad:    [देर हो जाएगी]
```
To Ankit (Dubai, 18:30 GST): "Papa ne bataya kal thoda late ho sakte hain. Clinic ko call karke 11:30 kar dun? [Haan, call karo] [Rehne do]"

(Dad's taps are relayed to Ankit, who decides. Dad cannot instruct Friday in P1, per US-22.3.)

### 6.10 Commands

```
User:   forget my rent date
Friday: Forget "rent due on the 5th"? I'll also stop rent reminders.
        [Forget] [Cancel]
User:   [Forget]
Friday: Gone.

User:   mera sab data delete kar do
Friday: Yeh sab permanently delete hoga: profile, memory, call recordings, transcripts, history.
        2 pending tasks bhi cancel honge. Confirm karne ke liye apna Friday PIN bhejo.
User:   7391
Friday: Last step: type DELETE.
User:   DELETE
Friday: Done. Sab delete ho raha hai (24 ghante mein poora). Kabhi wapas aana ho toh bas "hi" bolna.

User:   pause for a week
Friday: Paused till Wed 14 Oct. No nudges or briefings till then. Results and appointment
        reminders will still come. Say "resume" anytime.
```

### 6.11 Call transcript excerpt with an objection (Friday ↔ business)

```
Friday:   Namaste ji, main Friday bol rahi hoon, ek AI assistant, Ankit Sharma ki taraf se. Kya yeh Looks Salon hai?
Business: Haan… AI? Hum robot se baat nahi karte.
Friday:   Bilkul samajh sakti hoon ji. Bas 30 second ka kaam hai, Saturday ke liye ek haircut book karna tha.
Business: Achha bolo, kitne baje?
Friday:   Subah 11 baje ke aaspaas?
Business: 11 full hai. 10 ya 12:30.
Friday:   Ji. Aur price kitna hoga?
Business: ₹600. Priya karegi.
Friday:   Shukriya. Main Ankit ji se confirm karke 10 minute mein call back karti hoon. Kya tab tak 12:30 rakh sakte hain?
Business: Haan, 10 minute.
Friday:   Thank you ji.
```

### 6.12 Hinglish negotiation call (Friday ↔ AC service, budget max ₹600, target ₹500)

```
Friday:   Namaste, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon.
          Saturday subah AC service ke liye slot chahiye tha, Indiranagar mein, ek split AC.
Rep:      Haan madam, service ka 699 lagega. Gas alag se.
Friday:   Ji. 699 mein kya kya include hai, aur gas top-up ka kitna hoga agar zaroorat padi?
Rep:      Jet wash, filter cleaning. Gas top-up 1500 se start.
Friday:   Samajh gayi. Ek aur service ne 450 quote kiya hai jet wash ke saath gas check included.
          Aap 500 mein kar sakte hain?
Rep:      500 nahi hoga. 600 final, aur visit charge nahi lagega.
Friday:   Theek hai. Toh 600, visit charge waived, gas top-up chahiye toh alag. Saturday kaunsa time free hai?
Rep:      10 baje ya 12 baje.
Friday:   Shukriya. Main Ankit ji se confirm karke 15 minute mein call back karti hoon. Dono slot tab tak rakh sakte hain?
Rep:      Haan, rakh deta hoon.
```
WA to Ankit: "CoolCare: ₹699 → ₹600 (visit charge waived). Gas top-up extra from ₹1,500. Sat slots: [10:00 AM] [12:00 PM] [Don't book]". Ankit taps [10:00 AM].

Call-back:
```
Friday:   Namaste, main Friday, Ankit Sharma ki AI assistant, AC service ke liye abhi baat hui thi.
          Ankit ji ne Saturday subah 10 baje confirm kiya hai. Toh: split AC service, 11 October subah 10 baje,
          12, 4th Cross Indiranagar, ₹600 quoted, visit charge nahi. Sahi hai?
Rep:      Haan, technician Ravi aayega.
Friday:   Shukriya ji. Aapko confirmation SMS bhi aa jayega.
```
Report to Ankit: "Booked. CoolCare, Sat 11 Oct, 10 AM, technician Ravi. ₹699 → **₹600**, visit charge waived (pay after service). Gas top-up only if needed, from ₹1,500; they'll ask you first."

(Friday never said "₹600 done, we'll pay". A budget alone isn't delegation, so she took the call-back route.)

### 6.13 Discovery → shortlist → compare → book (English)

```
User:   Find me a good AC repair guy near my office. AC isn't cooling. Ideally tomorrow, under ₹800.
Friday: Office = Embassy Tech Village, Bellandur? [Yes] [Somewhere else]
User:   [Yes]
Friday: Top 3 within 3 km:
        1. FrostFix: 4.6★ (410), reviews: "diagnosed fast, no upselling"
        2. CoolCare Services: 4.5★ (260), you used them in March
        3. Arctic Home Services: 4.3★ (890), "same-day visits"; ⚠ 2 reviews mention overcharging for gas
        [Call all 3] [Pick which to call] [Search again]
User:   [Call all 3]
Friday: On it. I'll call one by one and use the quotes to bargain.
  …
Friday: Here's what I got for tomorrow (Thu 9 Oct):
        • FrostFix: ₹399 inspection (waived if repaired) · 11 AM–1 PM · gas from ₹1,800
        • CoolCare: ₹600 → ₹500 inspection + basic repair · 4–6 PM
        • Arctic: ₹350 inspection · 10 AM · wouldn't quote for gas over phone
        My pick: FrostFix. Best-reviewed, earliest slot that fits, inspection free if they fix it.
        All three are holding their slots for 1 hour.
        [Book FrostFix] [Book CoolCare] [Book Arctic] [None, search more]
User:   [Book FrostFix]
Friday: Calling FrostFix to confirm…
Friday: Booked ✅ FrostFix · Thu 9 Oct, 11 AM–1 PM at your office (Embassy Tech Village, Block C)
        ₹399 inspection, waived if they repair it. I'll check in at 2 PM to see if they came.
```

### 6.14 Language mirroring mid-call (Friday ↔ salon in Bengaluru)

```
Friday:   Namaste, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon.
          Saturday ke liye haircut appointment chahiye tha.
Rep:      Sorry, Hindi gottilla. Kannada or English?
Friday:   Of course. I'd like to book a haircut for Ankit Sharma this Saturday morning.
Rep:      Saturday 11 ge slot ide, aadre Priya illa.   (Kannada: "There's a slot at 11 on Saturday, but Priya isn't in.")
Friday:   [switches to Kannada] Sari, 11 gantege yaaru irtaare?   ("Okay, who is available at 11?")
          …
```
(The call log shows `languages_used: [hinglish, en, kn]`. The report reaches Ankit in Hinglish. The business's preferred language `kn` is saved for next time.)

### 6.15 Adding people and places

```
User:   add my mom Sunita, +91 98xxxx, she only speaks Marathi, lives in Pune
Friday: Added Mom: Sunita · +91 98xxxx · Marathi · Pune.
        What's her address? Type it, paste a Maps link or share a location pin.
User:   📍 (location pin: Kothrud, Pune)
Friday: Saved as "Mom's home": Kothrud, Pune 411038. Is this Mom & Dad's home or just Mom's?
        [Mom & Dad's home] [Just Mom's]
User:   [Mom & Dad's home]
Friday: Done, linked to Mom and Dad.
User:   mummy ke ghar ke paas koi achha physiotherapist dekho
Friday: Kothrud ke paas dhoondh rahi hoon…
```

### 6.16 Customer care: Airtel broadband refund (Hinglish, with IVR, hold and escalation)

WhatsApp:
```
User:   Airtel broadband 2 se 6 Oct tak band tha, complaint kiya tha phir bhi. Refund dilwao
Friday: 5 din ka outage, samajh gayi. Pichla complaint number hai? Aur bill ki photo bhej do toh plan amount mil jayega.
User:   (bill photo)  complaint no yaad nahi
Friday: Bill se: Plan ₹1,178/mo, Account ID 1-2XXXXXX8.
        Plan: Airtel ke official number 121 pe call (verified, airtel.in). Main maangungi
        5 din ka pro-rata credit (~₹190), minimum ₹150.
        Share karungi: registered mobile +91 98XXXXX210, Account ID 1-2XXXXXX8. Aur kuch nahi.
        [Go] [Edit]
User:   [Go]
Friday: Calling Airtel. IVR se agent tak pahunch ke batati hoon.
```

The call (Friday's own actions are in [brackets]):
```
IVR:      Airtel mein aapka swagat hai. For English press 2…
Friday:   [DTMF 2]
IVR:      For broadband, press 3…
Friday:   [DTMF 3]   (learned IVR map: 2 → 3 → 9 → agent)
IVR:      Please enter your registered mobile number.
Friday:   [DTMF 98XXXXX210 — approved identifier]
IVR:      …To speak to our customer service executive, press 9.
Friday:   [DTMF 9]
IVR:      All our executives are busy. Your estimated wait time is 11 minutes. ♪ (music)
Friday:   [listening mode; WA to user: "Airtel queue mein hoon, ~11 min wait. Human aate hi batati hoon."]
  … 13 min of hold …
Agent:    Hello, Airtel se Neha bol rahi hoon, main aapki kya madad kar sakti hoon?
Friday:   [full mode] Namaste Neha ji, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon.
          Unka broadband 2 se 6 October tak paanch din band tha. Account ID 1-2XXXXXX8. Is outage ka
          pro-rata credit chahiye tha.
Agent:    Ek minute, main check karti hoon… haan sir, area outage tha. Main ₹100 ka goodwill credit de sakti hoon.
Friday:   Shukriya. Lekin paanch din ki service nahi mili, plan ₹1,178 ka hai, toh pro-rata lagbhag ₹190 banta hai.
          Kya poora credit ho sakta hai?
Agent:    Ma'am, mere paas ₹100 tak hi authority hai.
Friday:   Samajh sakti hoon. Kya aap ise supervisor ko escalate kar sakti hain?
Agent:    Please hold. ♪
Friday:   [listening mode]
Supervisor: Hello, main Vikram, team lead.
Friday:   Namaste Vikram ji, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se. Paanch din ke outage
          ke liye pro-rata credit ki baat ho rahi thi, lagbhag ₹190.
Supervisor: Main ₹175 credit approve kar sakta hoon, next bill mein dikhega. Iske liye OTP verify karna hoga jo customer ke number pe aayega.
Friday:   Main AI assistant hoon, OTP share nahi kar sakti. Main abhi Ankit ji ko call pe jod deti hoon, woh khud verify kar denge.
          [WA + dial Ankit; whisper on Ankit's leg only: "Airtel team lead Vikram, ₹175 credit approve. Sirf OTP aapko
          batana hai, main sun rahi hoon."]
Ankit:    Hi Vikram, OTP 4-…
Friday:   [OTP audio redacted from recording and transcript]
Supervisor: Verified. ₹175 credit done. Ticket number 2-58XXXXXX9, 20 October tak bill mein reflect hoga.
Friday:   Confirm kar leti hoon: ₹175 credit, ticket 2-5-8-X-X-X-X-X-X-9, 20 October tak. Sahi hai?
Supervisor: Ji, sahi.
Friday:   Bahut shukriya Vikram ji.
```

Report:
```
Friday: Done ✅ Airtel: ₹175 credit (asked ₹190, first offer ₹100 → escalated to team lead Vikram).
        Ticket 2-58XXXXXX9 · Credit by 20 Oct on your next bill.
        Main 21 Oct ko check karungi. Credit na dikha toh same ticket pe follow-up call.
        Call time: 31 min (24 min on hold).
        [Listen] [Transcript] [Done]
```
(If Ankit hadn't answered the bridge, Friday would have got the ticket raised without verification and sent a callback pack: "Call 121 → 2 → 3 → 9, quote ticket 2-58…, say Vikram approved ₹175 pending OTP.")

### 6.17 Stock hunt with parallel calls (A4 + US-23)

```
User:   Dad ke ghar ke paas kis chemist ke paas Lantus insulin pen hai? Urgent
Friday: Malviya Nagar, Jaipur ke 8 chemists ko 3-3 karke call kar rahi hoon. Mil gaya toh wahin ruk jaungi.
  … (legs 1–3: no stock, busy, no stock; legs 4–5 live; leg 4 confirms) …
Friday: Mil gaya ✅ Gupta Medicos, 700 m from Dad's home: Lantus pen ×3 in stock, ₹780 each, open till 10:30 PM.
        Ek pen 8 baje tak hold karwaya hai. (5 shops checked, 1 call ended early.)
        [Home delivery order] [Send address to Dad] [Done]
```

### 6.18 Wellbeing check-in: summary and alert (A13)

```
Friday (daily, 10:20 IST): Mom & Dad check-in ☀️
        Mom: BP ki dawai li ✅, achhi neend aayi, dhania aur atta chahiye (order karun?)
        Dad: Sugar test kiya (bole 140), walk pe gaye the.
        [Order groceries] [Listen] [OK]

Friday (another day, 10:14 IST, urgent): ⚠ Dad sounded unwell. He said he's been dizzy since morning and didn't take his BP medicine.
        I told him I'd let you know right away. If it gets worse, call 112/108.
        [Call Dad now] [Call his doctor] [Listen to recording]
```

### 6.19 Homestay in Coorg for parents (A15: compare, Kannada/English call, direct rate, hold, pay at hotel, reconfirm, modify)

WhatsApp:
```
User:   Mom-Dad ke liye Coorg mein ek achha homestay, 14 se 16 Nov. Papa stairs nahi chadh sakte. 4k/night tak
Friday: Mom & Dad, 2 adults, 14–16 Nov (2 nights), ground floor ya lift zaroori. Veg khana chahiye?
User:   haan veg
Friday: 4 options:
        1. Misty Woods Homestay: 4.7★ (240) · online ₹4,200/night · "hosts cook great veg food"
        2. Coorg Cliff Resort: 4.4★ (1.8k) · online ₹5,100 (over budget) · lift, refundable
        3. Kaveri Nest Guesthouse: 4.6★ (95) · not online, call for rate · "ground-floor cottages, quiet"
        4. Hillview Stays: 4.3★ (310) · online ₹3,400 · ⚠ reviews mention steep steps
        Recommend calling 1 and 3 for direct rates.
        [Call 1 & 3] [Book 1 online] [Search again]
User:   [Call 1 & 3]
```

Call to Misty Woods (Friday's actions in [brackets]):
```
Friday:   Namaste, main Friday hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon,
          unke parents ke liye.
Owner:    Hello? Hindi swalpa swalpa… English please.   (Kannada mixed in: "only a little")
Friday:   [switches to English] Of course. I'm looking for a ground-floor room for two senior guests,
          14 to 16 November, vegetarian meals. Do you have availability?
Owner:    Garden cottage is free, ground floor. Online it is 4,200 with breakfast.
Friday:   Thank you. Since it's a direct booking for two nights, could you do 3,500 a night including breakfast?
Owner:    [Kannada] ಮೂರು ಸಾವಿರದ ಆರುನೂರು ಕೊಡಿ, ಕೊನೆ.   ("Give 3,600, that's final.")
Friday:   [switches to Kannada] ಸರಿ, ಮೂರು ಸಾವಿರದ ಆರುನೂರು, ತಿಂಡಿ ಸೇರಿ. ರಾತ್ರಿ ಊಟ ಸಸ್ಯಾಹಾರ ಸಿಗುತ್ತಾ?
          ("Okay, 3,600 with breakfast. Is vegetarian dinner available?")
Owner:    ಸಿಗುತ್ತೆ, 300 ರೂ.   ("Yes, ₹300.")
Friday:   Payment and cancellation? Can they pay at check-in?
Owner:    Pay at check-in fine. Free cancel till 3 days before.
Friday:   Could you hold the garden cottage for one hour while I confirm with Ankit?
Owner:    Okay, one hour.
Friday:   Thank you. I'll call back shortly.
```
(The Kaveri Nest call, in parallel: ₹3,000/night, but no meals on site and cash-only advance of 50% to a personal number. Flagged by the scam check, US-38.1.)

```
Friday: Direct rates:
        • Misty Woods: ₹4,200 → ₹3,600/night incl. breakfast · veg dinner ₹300 · ground-floor cottage
          · pay at check-in · free cancellation till 11 Nov
        • Kaveri Nest: ₹3,000, but wants 50% advance to a personal UPI number ⚠ and has no meals
        Recommend Misty Woods (₹1,200 cheaper than online, pay later, parents-friendly). Room held for 1 hour.
        [Book Misty Woods] [Book Kaveri Nest] [Neither]
User:   [Book Misty Woods]
Friday: Calling them back to confirm…
Friday: Booked ✅ Misty Woods Homestay, Coorg
        14–16 Nov · Garden cottage (ground floor) · Suresh & Kamla Verma
        ₹3,600/night incl. breakfast · veg dinner ₹300/person on request · pay at check-in
        Free cancellation till 11 Nov · Owner sent WA confirmation (saved)
        Mom-Dad ko Hindi mein reminder bhejun? (Both opted in earlier) [Yes] [No]
```

Day before (13 Nov, 11:05 IST), reconfirm call → to the user: "Reconfirmed with Misty Woods: cottage ready, they'll keep dinner for 8 PM. Check-in from 12 PM." To Dad (Hindi template): "कल कूर्ग: मिस्टी वुड्स होमस्टे, चेक-इन 12 बजे से। फ़ोन: 08272-XXXXXX।" ("Tomorrow, Coorg: Misty Woods Homestay, check-in from 12 noon. Phone: 08272-XXXXXX.")

Modification:
```
User:   papa ka plan ek din badh gaya, 17 tak kar do
Friday: Calling Misty Woods to extend to 17 Nov…
Friday: Extended ✅ 14–17 Nov (3 nights), same rate ₹3,600. New WA confirmation saved. No other changes.
```

---

## 7. Edge cases and error states

| # | Situation | Expected behaviour |
|---|---|---|
| E1 | Task without a phone number and no memory match | Ask for the number or contact card (US-3.2). Friday never guesses a number |
| E2 | Number is premium, international or an emergency number; or a toll-free/IVR number not in the official directory | Decline with the reason. For emergency numbers: "Please call 112 directly". For unverified care numbers, apply US-35.3 |
| E3 | Request to call a private person (e.g. "call my ex", "call my mom and tell her…") | Decline in P1: "I can only call businesses, service providers, and family who've opted in to check-ins." Exceptions as in §2 |
| E4 | Harassing, prank, illegal or deceptive goal (e.g. "pretend to be police") | Refuse. Log `task_refused_policy`. Repeated abuse → account flagged for review |
| E5 | Ambiguous dates ("kal" sent at 00:30; "Saturday" sent on a Saturday) | Before 04:00, "kal" means the upcoming day after the night. A day name sent on that same day means the next week, unless the user said "aaj"/"today". If confidence is < 0.8, confirm the absolute date |
| E6 | User asks for a call during quiet hours or outside the call window | Friday replies normally and schedules the call for 09:00/09:30 (or the business's opening hours): "They're probably closed. I'll call at 9:30 AM." |
| E7 | Duplicate request (same business and goal within 2 h) | "I'm already on it. Should I call again anyway?" |
| E8 | User sends a new message mid-call that isn't an answer | Friday handles it as a normal chat. If it changes the task ("actually make it Sunday"), Friday relays the change to the live call when possible |
| E9 | User cancels mid-call ("cancel", "stop the call") | Friday politely wraps up with the business ("Sorry ji, plan change ho gaya", i.e. "Sorry, the plans have changed") and ends the call. Outcome `cancelled_by_user`. Counts as a connected call |
| E10 | Business confirms, then later calls back to change it (inbound, US-16) | Notify the user (urgent). Offer to call back and re-confirm |
| E11 | Recording failed | The report is sent without the recording, with the note "Recording unavailable for this call" |
| E12 | STT/LLM latency spike mid-call (>3 s silence) | No filler sounds (US-19). If the gap exceeds 3 s, one plain line ("Sorry, one moment."). After more than 2 consecutive spikes, apologise and end → `failed_system` with an auto-retry |
| E13 | WhatsApp delivery fails, or the account is restricted or banned (policy risk) | Fall back to DLT SMS templates for results and reminders (§8.3). Core state is channel-agnostic (see ARCHITECTURE). An ops alert is raised |
| E14 | User blocks Friday on WA | Delivery failures are detected → pause all proactive messages. Nothing is sent by SMS except results of in-flight tasks |
| E15 | User approves after the offer lapsed, or the business doesn't pick up the call-back | Retry the call-back per US-6. If the slot is gone, offer the next options via call-back (US-3.11) |
| E16 | User account deleted with tasks in flight | Live calls end politely and scheduled retries are cancelled. No business touch is sent |
| E17 | Business gives contradictory info within the call | Friday clarifies once during CONFIRM. If still unclear, the outcome is `partial` with both values reported |
| E18 | User replies "1234" unprompted (looks like a PIN) | Not treated as a PIN outside a PIN flow. If it matches the PIN hash, Friday warns: "Looks like your PIN. Please delete that message. I only ask for it when you start a sensitive action." |
| E19 | Business asks to speak to the customer | Friday offers to pass a message and a callback (if the number is shareable) → `escalated` with the business's request quoted |
| E20 | Business speaks a language the configured STT/TTS doesn't support | Friday continues in Hinglish and offers English or Hindi. If neither works: "Sorry, I'll have Ankit call you", ends the call → `partial`/`failed` with reason `language`. Logged to size language demand. Supported regional languages are mirrored per US-13.2 |
| E25 | Discovery finds <2 viable businesses | Friday widens the radius once (6 km). If still <2, it reports what it found and offers `Call anyway` / `Search different area` / `I'll share a number` |
| E26 | Places data is stale (number disconnected, business closed) | The outcome is `wrong_number`/`unreachable`. The business is flagged in Friday's business table, and the next shortlist candidate is offered automatically within the same task |
| E27 | Held slot is lost before the user picks (compare flow) | On the booking callback, Friday offers the business's next slot to the user mid-call (US-5) |
| E28 | Ambiguous person/place ("papa" when the user has a father and a father-in-law; "home" with two homes) | One question with buttons, then the alias is learned (US-20.4, US-21.4) |
| E29 | Beneficiary hasn't opted in, but the user says "remind dad" | Friday explains the one-time opt-in and offers `Ask him now`. Until then, reminders go only to the user |
| E30 | Beneficiary replies with free text or a voice note | Relayed to the requester verbatim (transcribed); never acted on (US-22.3) |
| E31 | Beneficiary number is the same as another Friday user's number | The opt-in still applies. That person's own Friday account and data stay completely separate |
| E32 | "Near me" without a recent pin | Friday asks for a pin or area. It never guesses from the city alone for discovery |
| E21 | User in another time zone (NRI) | Quiet hours and the briefing use IST in P1 (Q6). Friday shows "(9:40 AM in Delhi)" when it helps |
| E22 | User sends a voice note longer than 3 min, an image or a document | Voice: ask the user to split it. Images/PDFs (bills, prescriptions, quotes, screenshots) are extracted and confirmed (US-24.5). vCards and location pins are parsed |
| E23 | Concurrency limit reached (US-23.1) | Extra legs or tasks are queued with an ETA: "I'll call them as soon as a line frees up." |
| E40 | Property asks for an advance to a personal UPI number, or the details don't match the listing | Scam check (US-25). Warn the user and recommend against it. Never mark the booking confirmed without the property's confirmation of receipt |
| E41 | Reconfirm call finds no record of the booking or a different rate | Urgent message to the user with the written confirmation attached, plus `Call them with me` (warm transfer) / `Find alternatives` |
| E42 | API rate disappears between search and booking | Re-quote and ask the user again. Friday never books at a higher price silently |
| E43 | Property doesn't send written confirmation | Friday asks once more on WA, sends the user the verbal-confirmation recording and flags the booking as "verbal only" |
| E33 | IVR changed since the learned map | Fall back to live menu understanding, then update the map (US-31.2) |
| E34 | Customer-care agent asks Friday for an OTP, PIN or CVV, or to read one back | Refuse. Patch in the user (US-33). Never repeat the value |
| E35 | Call drops after a long hold | Immediate redial with the same IVR path. Friday tells the user the queue was lost and gives the new ETA |
| E36 | Agent promises a callback to the customer | Friday records the date and window, tells the user, and schedules a follow-up if the callback doesn't happen (US-36.3) |
| E37 | Check-in member doesn't answer | 3 attempts across 2 h, then an alert to the user (A13). If the member opted for "skip if I don't answer", only the summary notes it |
| E38 | Stock hunt finds two matches at once | Report the closer or cheaper one as primary and list the other |
| E39 | Business sends a blurry or illegible quote image | Ask the business once for a clearer copy or to type it out. Otherwise report the values with low confidence and flag them |
| E24 | Distress signal | US-15 |

## 8. Templates

### 8.1 WhatsApp templates (submit for Meta approval in `en` and `hi`; Hinglish uses `en` with Romanised Hindi body variants. See Q9)

Category is `UTILITY` unless noted. Every template's footer: "Reply STOP to stop these."

| Name | Category | Body (`{{n}}` = variable) | Buttons (quick reply) |
|---|---|---|---|
| `friday_appointment_reminder` | UTILITY | "Reminder: {{1}} at {{2}}, {{3}}. Address: {{4}}." (1=service/business, 2=time, 3=day/date, 4=address) | `Got it` · `Running late` · `Reschedule` |
| `friday_task_update` | UTILITY | "Update on your request to {{1}}: {{2}}. Tap to see details." (1=task summary, 2=one-line outcome) | `See details` |
| `friday_call_question` | UTILITY | "{{1}} is asking a quick question about your {{2}}. Tap to answer." (1=business, 2=task) | `Answer now` |
| `friday_approval_needed` | UTILITY | "{{1}} offered {{2}} for your {{3}}. Tap to choose and I'll call them back to confirm." | `Choose now` · `Don't book` |
| `friday_followup_check` | UTILITY | "Did {{1}} come for {{2}} on {{3}}?" | `Yes, all done` · `No-show, call them` · `Still waiting` |
| `friday_date_nudge` | UTILITY | "Heads up: {{1}} is on {{2}}. Want me to {{3}}?" (3=offered action) | `Yes, do it` · `Remind me later` · `Not needed` |
| `friday_pattern_nudge` | MARKETING (likely; see Q10) | "It's been {{1}} since your last {{2}} at {{3}}. Book your usual {{4}}?" | `Book it` · `Not now` · `Stop these` |
| `friday_morning_briefing` | UTILITY | "Good morning {{1}}! Today: {{2}}. Coming up: {{3}}." | `See more` · `Briefing off` |
| `friday_business_change` | UTILITY | "{{1}} has changed your booking for {{2}}: {{3}}. What should I do?" | `Accept` · `Call them` · `Cancel it` |
| `friday_beneficiary_optin` (to non-users) | UTILITY | "Namaste {{1}}, I'm Friday, an AI assistant. {{2}} ({{3}}) has booked {{4}} for you. May I send you confirmations and reminders for it?" (1=beneficiary, 2=requester, 3=relation, 4=what) | `Yes` · `No` |
| `friday_beneficiary_reminder` | UTILITY | "{{1}}, reminder: {{2}} on {{3}} at {{4}}, {{5}}. {{6}}" (6=prep note) | `OK` · `I'll be late` · `Stop` |
| `friday_comparison_ready` | UTILITY | "Your quotes for {{1}} are ready: best is {{2}} at {{3}}. Slots are held for a short time." | `See all` · `Book best` |
| `friday_biz_request` (to businesses) | UTILITY | "Hello {{1}}, this is Friday, an AI assistant contacting you on behalf of a customer, {{2}}. {{3}}" (3=the ask, e.g. "Could you share your price list for AC service?") | `Reply` · `Stop messages` |
| `friday_checkin_optin` (to circle member) | UTILITY | "Namaste {{1}}, I'm Friday, an AI assistant. {{2}} would like me to call you {{3}} at {{4}} for a short check-in. Is that okay?" | `Yes` · `No` |
| `friday_checkin_summary` | UTILITY | "Check-in with {{1}} ({{2}}): {{3}}" | `Listen` · `OK` |
| `friday_checkin_alert` | UTILITY (urgent) | "Alert about {{1}}: {{2}}. Please check on them." | `Call now` · `Listen` |
| `friday_care_update` | UTILITY | "{{1}} update: {{2}}. Ticket {{3}}. Next step: {{4}}." | `See details` · `Escalate` |
| `friday_recurring_booked` | UTILITY | "Booked your regular {{1}}: {{2}} at {{3}}." | `OK` · `Skip this one` · `Pause series` |
| `friday_stay_reminder` | UTILITY | "Check-in {{1}}: {{2}}, {{3}}. Check-in from {{4}}. Property phone {{5}}." | `Directions` · `Running late` · `Need changes` |
| `friday_cancel_deadline` | UTILITY | "Free cancellation for {{1}} ends {{2}}. Still going?" | `Yes, keep it` · `Cancel it` |
| `friday_business_touch` (to businesses) | UTILITY | "Booking confirmed via Friday for {{1}}: {{2}} on {{3}} at {{4}}. Friday is an AI assistant that books on behalf of customers." | `OK` · `Stop messages` |

Beneficiary templates are submitted in `hi`, `en`, `mr`, `ta`, `te`, `kn` and `bn`. If a beneficiary's language has no approved template, Friday uses DLT SMS in that language (Unicode) or a voice reminder.

Rule: every template send stores `template_name`, `language`, `variables` and `wa_message_id` in the action log.

### 8.2 Chat-only messages (sent inside the window; listed for copy review)
`consent_summary`, `capability_card`, `rate_limited_notice` (neutral, ops-enabled only), `waitlist_ack`, `delete_confirmation`, `pause_confirmation`.

### 8.3 SMS (DLT-registered; sender ID e.g. `FRIDAI`, principal entity Friday; `{#var#}` = DLT variable)

| Template | Type | Text |
|---|---|---|
| `biz_booking_confirmation` | Service-implicit | "Booking confirmed via Friday: {#var#} on {#var#} at {#var#} for {#var#}. Friday is an AI assistant booking for customers. To stop msgs reply STOP {#var#}" |
| `biz_enquiry_thanks` | Service-implicit | "Thank you for taking a call from Friday (AI assistant) for a customer today. To stop msgs reply STOP {#var#}" |
| `user_task_result` (WA fallback) | Service-implicit | "Friday: {#var#}. {#var#}. Details on WhatsApp." |
| `user_appointment_reminder` (WA fallback) | Service-implicit | "Friday reminder: {#var#} at {#var#} on {#var#}." |
| `ben_optin` | Service-explicit (consent) | "{#var#} ne Friday (AI sahayak) se aapke liye {#var#} book kiya hai. Jaankari aur reminder ke liye HAAN reply karein, rokne ke liye STOP. {#var#}" ("{#var#} has booked {#var#} for you through Friday (AI assistant). Reply HAAN for updates and reminders, STOP to stop.") |
| `ben_reminder` | Service-implicit | "Friday reminder for {#var#}: {#var#} on {#var#} at {#var#}, {#var#}. STOP to stop." (registered in Hindi/Marathi/etc. variants) |
| `user_pin_reset_otp` | Service-explicit / OTP | "{#var#} is your Friday PIN reset code. Valid 10 min. Never share it with anyone, including Friday's calls." |

---

## 9. Metrics and instrumentation

### 9.1 Success metrics (from BRIEF)
| Metric | Definition | Target |
|---|---|---|
| Call-task success rate | tasks with outcome `success` or `partial` ÷ tasks where ≥1 attempt was placed (excluding `cancelled_by_user`) | >80% (`success` alone tracked separately) |
| Engagement | user-initiated requests per active user per week, by cohort week | ≥2 by week 3 |
| Cost per successful call | (telephony + STT + TTS + LLM + WA/SMS spend per task, all attempts) ÷ successful tasks | < ₹15 |
| Business hang-up rate | connected calls ending with a business hang-up before purpose completion (incl. ≤15 s after disclosure) ÷ connected calls | < 20% |

### 9.2 Supporting metrics
- Onboarding: invite-to-start, start-to-consent, consent-to-first-task conversion; median time.
- Time to first task; tasks per user in week 1.
- Mid-call question response rate, median reply latency, timeout rate.
- Retries per task; outcome distribution; connect rate.
- Report latency p50/p95. Call turn latency p50/p95 (target p50 < 1.2 s).
- Proactive: nudge acceptance / dismiss / ignore rate by type; unprompted msgs per user-day (must be ≤3); "stop these" rate; pause rate.
- Memory: facts captured per user, fact-confirmation rejection rate (a proxy for precision).
- Retention D7/D30; invites sent and redeemed per user; internal cost per user (p50/p95) and users above the cost thresholds.
- Approval: % of bookings via call-back vs delegation; median approval latency; call-back success rate (the slot is still available); lapsed offers.
- Trust: deletion requests and completion time (SLA 24 h); hard-rule violations found in post-call audits (target 0).
- Business: touches sent; business STOP rate; DNC additions.
- Discovery: discovery→booking conversion; shortlist acceptance (`Call all` rate); % of discovery tasks where the user booked Friday's recommendation.
- Negotiation: % of quotes improved; median saving (₹ and %); negotiation-linked hang-ups (should be ≈0).
- Language: % of calls with a switch; % of switches within 1 turn; call success by language.
- People and places: % of users with ≥1 person or place; % of tasks for a beneficiary; beneficiary opt-in rate; reference-resolution accuracy (user corrections ÷ resolutions).
- Voice quality: filler-token violations (target 0); human-claim violations (target 0).
- Customer care: resolution rate (ticket + promised action) per company and category; % reaching a human agent; median hold time; IVR map hit rate; cost per care task (hold minutes in listening mode); promised dates kept (follow-up checks).
- Footwork types: success rate and cost **per task type** (A1–A14), first-match hunt time-to-answer, check-in answer rate and alert precision (false alarms ÷ alerts), recurring-series retention.
- Parallel calling: legs per task and wasted legs (ended after a first match).

### 9.3 Events (all events carry `user_id`, `ts`, `channel`, `env`; PII is excluded from properties, with IDs referencing entities)
| Event | Key properties |
|---|---|
| `user_message_received` | type (text/voice/button/list/contact), language_detected, in_window |
| `onboarding_step_completed` | step, attempt_count |
| `consent_recorded` | consent_version, tnc_version, method |
| `onboarding_completed` | duration_s |
| `invite_redeemed` / `invite_rejected` | inviter_id, reason |
| `task_created` | task_id, type, subtype, category, source (user/nudge/auto), beneficiary_is_user |
| `task_clarification_asked` | task_id, missing_fields |
| `task_refused_policy` | reason |
| `call_attempt_started` | task_id, attempt_no, number_type (mobile/landline), scheduled_vs_actual_delay_s |
| `call_connected` | task_id, attempt_no, ring_s |
| `call_disclosure_reaction` | task_id, reaction (proceed/objection/hangup) |
| `call_objection` | task_id, kind |
| `midcall_question_sent` | task_id, n_options, via (interactive/template) |
| `midcall_question_answered` / `midcall_question_timeout` | task_id, latency_s, answer_type (button/text/voice) |
| `call_attempt_ended` | task_id, attempt_no, outcome, duration_s, lang_used, hangup_by |
| `call_cost_recorded` | task_id, telephony_paise, stt_paise, tts_paise, llm_paise, msg_paise |
| `task_completed` | task_id, final_outcome, attempts, total_duration_s, cost_paise |
| `report_sent` | task_id, latency_s, has_recording |
| `recording_requested` / `transcript_requested` | task_id |
| `memory_fact_extracted` | fact_id, kind, confidence, confirmed (auto/asked) |
| `memory_item_forgotten` | kind |
| `nudge_generated` / `nudge_suppressed` | nudge_id, type, category, reason (cap/quiet/ignored/paused/no_template/dedupe) |
| `nudge_sent` | nudge_id, type, via (freeform/template), template_name |
| `nudge_response` | nudge_id, response (accepted/dismissed/stop/ignored_24h) |
| `autonomy_level_changed` | category, from, to |
| `auto_action_executed` | category, task_id |
| `briefing_sent` / `briefing_skipped_empty` | items_count |
| `command_executed` | command, success |
| `pin_attempt` | context, success, lockout |
| `data_deletion_requested` / `data_deletion_completed` | duration_s |
| `cost_threshold_alert` / `rate_limit_applied` | period, cost_paise, limit (ops only) |
| `business_touch_sent` | business_id, channel, template |
| `business_opt_out` | business_id, source |
| `inbound_call_received` | matched_task (bool) |
| `task_type_classified` | task_id, task_type, confidence, asked_user |
| `fanout_started` / `fanout_leg_ended` / `fanout_stopped_first_match` | task_id, strategy, n_legs, concurrency, leg_outcome |
| `biz_wa_sent` / `biz_wa_received` | task_id, business_id, media_type |
| `document_extracted` | source (user/business), doc_kind, fields, min_confidence |
| `scam_check` | number_hash, score, decision (call/warn/block) |
| `warm_transfer` | task_id, reason, user_answered, bridge_s |
| `translator_session` | task_id, langs, turns, p50_latency_ms |
| `call_scheduled_by_timing` | task_id, delay_s, reason (closed/lunch/best_time) |
| `vendor_rated` | business_id, rating |
| `ivr_step` | task_id, prompt_kind, key_or_utterance_kind, map_hit |
| `hold_started` / `hold_ended` | task_id, hold_s, ended_by (human/timeout/drop) |
| `care_ticket_captured` | task_id, company_id, has_promised_date, escalated |
| `care_followup_scheduled` | task_id, due_date |
| `verification_patch_in` | task_id, success |
| `checkin_call_completed` | member_id, answered, summary_flags, alert_sent |
| `recurring_instance_booked` | series_id, deviation (bool) |
| `stay_search_run` | task_id, provider, n_api_results, n_offline_candidates |
| `stay_direct_quote` | task_id, property_id, online_rate_paise, direct_rate_paise, pay_at_hotel |
| `stay_booked` / `stay_modified` / `stay_cancelled` | task_id, path (direct_pay_at_hotel/direct_hold/api), nights, has_written_confirmation |
| `stay_reconfirm_result` | task_id, discrepancy (bool) |
| `discovery_search_run` | task_id, category, radius_km, n_results, n_filtered |
| `shortlist_presented` | task_id, n, ranks_with_reason_ids |
| `shortlist_action` | task_id, action (call_all/pick/search_again) |
| `quote_recorded` | task_id, business_id, amount_paise, includes_count |
| `negotiation_outcome` | task_id, business_id, initial_paise, final_paise, asks, accepted_by_business |
| `comparison_report_sent` | task_id, n_businesses, recommended_business_id |
| `booking_approval` | task_id, mode (call_back/delegated/recurring_rule), latency_s, offer_still_available |
| `callback_confirm_call` | task_id, result (confirmed/slot_lost/changed_price/no_answer) |
| `call_language_switched` | task_id, from, to, turn_no |
| `person_added` / `person_removed` | relation, source (chat/onboarding/task) |
| `place_saved` | source (text/voice/maps_link/pin), geocode_confidence |
| `reference_resolved` | kind (person/place), ambiguous (bool), asked_user (bool) |
| `beneficiary_optin_sent` / `beneficiary_optin_result` | channel, result (yes/no/timeout) |
| `beneficiary_message_sent` | type, channel, language |
| `safety_signal_detected` | severity |
| `hard_rule_violation_detected` | rule, task_id (from the post-call audit) |

---

## 10. Open questions (need founder decision)

| # | Question | PM recommendation |
|---|---|---|
| Q1 | Friday's voice and grammatical gender in Hindi | **Resolved (founder): female** (F.R.I.D.A.Y.-style), feminine verb forms ("karti hoon") and female TTS voices |
| Q2 | ~~Business discovery in P1?~~ **Resolved by founder: yes** (US-17). Remaining question: which provider(s)? Google Places has ratings/reviews but has caching/attribution limits; Justdial has better SMB coverage but no official API | Google Places for P1 behind the interface; evaluate a second source for SMB coverage |
| Q3 | Cap accounting | **Resolved (founder): no user-facing cap in beta.** Internal cost tracking, alerts and an ops abuse rate-limit (US-2) |
| Q4 | Announce call recording in the opening line? It adds ~2 s and may raise the hang-up rate. Indian law is generally one-party consent, but disclosure is the safer trust posture | Yes, announce it; A/B the phrasing |
| Q5 | Retention for recordings and transcripts | 30 days, then auto-delete. Summaries are kept until the user deletes them |
| Q6 | Quiet hours for NRIs: IST (per BRIEF) or user-local? | Keep IST for P1 per BRIEF. Add user-local time zone in P1.1 |
| Q7 | "Delete everything": what may we legally retain (consent log, invite graph, DNC flags, phone-number hash to stop abuse)? | Retain only a salted phone hash, cost counters and consent/deletion receipts. Get legal sign-off |
| Q8 | PIN reset flow (forgotten PIN) | SMS OTP to the registered number, plus a 24 h cool-down before PIN-gated actions. Foreign numbers need support-assisted reset |
| Q9 | Hinglish templates: Meta has no Hinglish locale. Register Romanised Hindi under `en`? | Yes, with separate template names (`*_hinglish`) |
| Q10 | Will Meta classify pattern nudges as MARKETING (higher cost, opt-in rules, possible policy exposure)? | Phrase them as reminders tied to the user's own past bookings to qualify as UTILITY. Accept MARKETING if rejected |
| Q11 | Share the user's mobile number with businesses by default for bookings? | Yes by default, with one-line disclosure at the first booking and an easy off switch |
| Q12 | ~~Default call-opening language~~ **Resolved by founder: always Hinglish, then mirror** (US-13.2). Remaining question: which regional languages to enable at launch, given provider quality? | Launch with Hindi/English/Hinglish + Kannada, Tamil and Marathi (the three metros' needs); enable others behind a flag after evals |
| Q13 | Should level 4 (auto-act) be available at all in the beta? | Yes for `personal_care`, `dining`, `enquiries`, `follow_ups` and `reminders`; not for `health` or `home_services` |
| Q14 | Global DNC: one business's "don't call" blocks all Friday users from calling that number. Is that acceptable for users? | Yes. Respecting businesses matters for P5 Friday for Business |
| Q15 | Caller ID: use one shared number pool or a dedicated number per city? Businesses that save "Friday" may block it | City-level pools with a consistent display name. Monitor block and answer rates |
| Q16 | Cap accounting for discovery | **Resolved (founder): no cap.** Discovery cost is tracked per task. The ₹15 target is reviewed separately for compare tasks |
| Q17 | Pre-approval vs always asking | **Resolved (founder): approval rule.** Call back by default; confirm on the call only within explicit delegation (US-3.11) |
| Q18 | DPDP: Friday stores third-party data (parents' names, phones, health notes) provided by the user, before the beneficiary consents. Lawful basis? Can a beneficiary demand deletion of the profile the user created? | Store minimal data under the user's consent. Health notes are user-entered, encrypted at rest and never shared beyond US-22.4. Honour the beneficiary's deletion requests. Needs legal sign-off |
| Q19 | Negotiation default: `polite` for everyone, or ask the user at the first quote task? | `polite` default; the user can say "bargain hard" (→ `firm`) or "don't bargain" (→ `none`) per task or globally |
| Q20 | Should Friday name competitors when citing quotes? | No, by default ("another service quoted…") |
| Q21 | Recurring bookings approval | **Resolved (founder):** explicit delegation for the rule (window + ceiling) covers each instance; deviations take the call-back route |
| Q22 | Cap accounting for fan-outs, care follow-ups and check-ins | **Resolved (founder): no user-facing cap.** Per-user cost tracking, alerts and an ops rate-limit (off by default for invited users) |
| Q23 | Priority of scam check (B16) and warm transfer (B17) | **Resolved (founder): both Priority 1** |
| Q24 | WA-to-business from Friday's number: Meta policy and template category risk, and whether businesses will reply to an AI | Pilot with utility-category `friday_biz_request`; fall back to SMS link-less requests if rejected |
| Q25 | Check-in alerts (A13): liability if Friday misses a real emergency, and which signals count as an alert. Should a medical professional review the triggers? | Conservative trigger list (A13), clear "not an emergency service" wording in the member opt-in, and medical review of the trigger list before launch |
| Q26 | Customer-care calls can run 30–60 min. Do toll-free and hold minutes break the < ₹15 cost target? | Track care separately with a target of < ₹40 per resolved care task. Listening mode is required |
| Q27 | The curated directory needs ops effort (150 companies, re-verified every 90 days). Who owns it? | One ops owner, plus automated official-site checks |
| Q28 | Hotels: Expedia Rapid requires partner approval and may require merchant-of-record payment flows that conflict with "no payments". Is a pay-at-hotel-only inventory enough for launch? | Launch with direct-property calls plus pay-at-hotel API rates. Apply for Rapid partner access now |
| Q29 | Homestays often insist on a 30–50% advance. Is relaying official payment details (after the scam check) acceptable in P1, given the fraud risk? | Yes, with strict scam-check gating and explicit "pay at your own discretion" wording |
