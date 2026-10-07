# Friday: Phase 1 PRD ("Friday makes calls")

Status: Draft v2 (includes the founder voice-agent requirements: language mirroring, negotiation, ask-before-booking, discovery, AI voice, goal-driven calls) · Owner: Product · Source of truth for decisions: `docs/BRIEF.md` (the "Founder requirements for the voice agent" section overrides everything else) · North star: `docs/VISION.md`

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

- Customer-care and IVR calls (banks, telcos, airlines). Calls to toll-free or IVR numbers are declined.
- Payments, UPI, deposits, or any money commitment.
- Gmail, Calendar, documents, OAuth integrations.
- Lifeline or emergency features. Friday still always points distressed users to 112/108 (see §7).
- Inbound voice (users calling Friday). The voice pipeline MUST be reusable for P2. P1 only plays a fixed message on inbound calls (US-16).
- Business accounts and dashboards.
- Chat in languages other than Hindi, English and Hinglish. *On calls*, Friday mirrors the business's language, including other Indian languages where STT/TTS supports them (US-13). This follows the founder requirement, which overrides the BRIEF's earlier language exclusion.
- Calls to private individuals (friends, family), with one exception: a phone number the user supplies for a service provider (plumber, maid, tutor) is allowed.
- Agent-to-agent negotiation.
- Any app or website, beyond a one-time T&C link.

## 3. Target users

| Persona | Who | Typical jobs | Notes |
|---|---|---|---|
| **Busy urban professional** | 25–40, Bengaluru, Delhi NCR or Mumbai. On WA all day, hates phone calls, switches between English and Hinglish | Doctor/dentist appointments, salon, restaurant table, AC service, plumber, "is the pharmacy open / do they have X in stock / what's the price", "find me a good AC repair guy near Indiranagar and get the best price" | Core P1 user. Values speed and not having to talk. |
| **NRI managing parents' errands** | 28–50, in the US, UK, Gulf or Singapore. Parents live in an Indian city | Book a doctor for Papa, get the geyser fixed at Mum's flat, confirm a lab test home-collection slot | Number is foreign (+1/+44/+971). Time zone differs. Calls are made "on behalf of" the user *for* a beneficiary (US-3.9). Very high willingness to pay later. |

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
7. **First task**: "Last thing. What's one call you've been avoiding? I'll make it now." An example list (rotated) is included.

**US-1.3** Onboarding is resumable. If the user drops off, the next message resumes at the pending step. After 24h of inactivity mid-onboarding, Friday sends nothing (it is outside the WA window, and P1 sends no re-engagement template).

**US-1.4** The user can skip tone (default Playful) and city. They cannot skip consent or PIN. If a step's answer is unclear, Friday asks for it again, at most twice.

**US-1.5** On completion Friday sends a short capability card: what it can do, the monthly call allowance, and the `help` command. Event `onboarding_completed` is logged with the duration.

**US-1.6** Target: median onboarding completion of 3 minutes or less. Completion rate ≥70% of users who send a valid invite code.

### US-2 Invites and the monthly call cap

- **US-2.1** Each activated user gets **5 invite codes** (`FRI-XXXXXX`, single-use, no expiry in beta). The `invite` command lists the codes and whether each has been used. Founders/admins can mint unlimited codes.
- **US-2.2** Redeeming a code links the invitee to the inviter (`invited_by`). A used, revoked or unknown code is rejected with: "That code doesn't work. Check with whoever gave it to you?"
- **US-2.3** **Cap: 10 call tasks per user per calendar month (IST)**. This is configurable per user and globally.
  - A task counts against the cap when its first attempt **connects** (a human or the business answered).
  - Retries for the same task do not count again.
  - A task where no attempt ever connects does not count.
- **US-2.4** At 8/10 Friday appends one line to a report: "FYI: 2 calls left this month."
- **US-2.5** At 10/10 Friday declines new call tasks politely and states the reset date ("Your calls reset on 1 Nov"). Reminders, memory and nudges keep working. Nudges that would trigger a call are converted to level-1 inform messages.
- **US-2.6** A task already in progress (including scheduled retries) MUST complete even if the cap is reached meanwhile.

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
- Toll-free (1800/1860), premium, short codes, emergency numbers and international numbers are declined, with a reason.

**US-3.3 Missing info.** Before calling, Friday asks for at most **2** clarifying questions, combined into one message where possible. Required fields are: a business (or a discovery request), service, and a date or date window. Anything else is optional. Friday works out the rest on the call, within the stated flexibility.

**US-3.4 Confirm before dialling.** The user's request is their approval, so Friday does not ask "shall I call?". It sends: "Calling Looks Salon now for a haircut, Sat 11 Oct, 9 AM–12 PM. I'll ping you if they ask anything."
- If the business-call window is closed (outside **09:00–20:30 IST**, or outside known hours for that business), Friday schedules the call for the next window and says so.

**US-3.5 The call** is goal-driven, using the call brief in §5. The booking is **successful** only when all of these hold:
- the user has approved the slot and price (US-3.11);
- the business has explicitly confirmed date, time and service;
- Friday has read them back and received a "yes".

**US-3.6** If no slot fits the constraints, Friday collects the nearest alternatives and asks the user mid-call (US-5). If the user is unavailable, Friday ends the call with "I'll check with Ankit and call you back" and reports the alternatives.

**US-3.11 Ask before booking (founder requirement; it overrides autonomy settings).** Friday MUST NOT confirm any booking until the user has approved the specific slot and price.
- **Pre-approval counts** only if the user approved an *exact* slot (date + time) before the call, and the business's price is at or below the user's budget (or the known usual price if no budget was given). Examples: tapping `Book it` on "Looks, Sat 11 AM like usual?", or "book exactly 6 PM Friday, under ₹1,000". Anything else needs a mid-call question (US-5): a time range, a different slot, a higher price, a changed inclusion, or a different staff member when the user asked for a specific one.
- When the user can't be reached in time, Friday asks the business to hold the slot and calls back after approval (US-5.5). It never confirms "provisionally".
- The approval message (WA reply/button ID, timestamp) is stored on the task and in the action log.

**US-3.7 Info sharing.**
- Friday may share the user's booking name and, for bookings, their registered mobile number. The user can turn the number off.
- For home services Friday may share the address only if the user gave it for this task or approved a stored address ("Use your Indiranagar address?").
- Nothing else is shared.

**US-3.8** Friday never agrees to pay, prepay, put down a deposit or give card/UPI details. If the business requires an advance, Friday says "I'll confirm with <name> and get back to you", ends the call and escalates.

**US-3.9 On behalf of (NRI).** If `beneficiary` ≠ user, the opening says: "…calling on behalf of Ankit Verma, to book an appointment for his father, Mr. Suresh Verma." The beneficiary's name, age, number and address are stored as a **linked person** in the user's memory and can be reused.

**US-3.10** On success, Friday creates an **appointment** in memory (business, datetime, service, address if known, beneficiary). It then schedules the reminder (US-8.1) and, where applicable, the follow-up (US-8.2).

### US-4 Enquiry call

*As a user I want to ask "is Apollo Pharmacy Koramangala open and do they have Dolo 650?" and get an answer.*

- **US-4.1** The task spec has `type=enquiry`, the business and a list of **questions** (max 5 per call; extras are queued as a second task or trimmed after asking the user).
- **US-4.2** Friday asks every question and records an answer for each one: `answered` with the value, `unknown` ("they didn't know"), or `refused`. The call is successful when ≥1 question is answered and none was skipped by Friday.
- **US-4.3** Prices are recorded verbatim with units ("₹450 per visit, ₹150 extra if parts"). Friday never treats a quote as a commitment.
- **US-4.4** If the answer makes a natural next action obvious ("they have stock and close at 10"), the report offers one-tap actions: `Book it` / `Remind me at 7` / `Done`.
- **US-4.5** Enquiries about multiple businesses ("call these 3 plumbers, who's cheapest for a tap fix tomorrow?") follow the compare flow in US-17.4–17.6, whether the user supplied the numbers or Friday discovered them.

### US-5 Mid-call question to the user

*As a user, if the business offers options, I want to choose them in real time without being on the call.*

- **US-5.1** Friday always asks before confirming a booking, unless it was pre-approved (US-3.11). For non-booking details that the spec already covers ("any time after 4" when choosing which slots to ask about, "either branch is fine"), Friday decides without asking.
- **US-5.2** On the call, Friday says plainly: "One moment please, I'm checking with Ankit." ("Ek minute ji, main Ankit se confirm kar rahi hoon.") If the wait exceeds 20 s, it gives one factual status line ("Still waiting for Ankit's reply. Thank you for holding."). There are no filler sounds or fake hesitations (US-19).
- **US-5.3** On WA (inside the 24h window), Friday sends an interactive message headed with the business name:
  - ≤3 options use reply buttons. 4–10 options use a list message.
  - "None of these" is always available as the last button or row.
  - Free-text and voice-note replies are also parsed ("6 wala", "later one", "neither, ask for Sunday").
- **US-5.4** If the 24h window has closed (rare, e.g. a retry the next day), Friday sends the `friday_call_question` template (fixed button `Answer now`). Tapping it opens the window, and the interactive options follow immediately.
- **US-5.5 Timeout.** Friday waits up to **45 s** for an answer.
  - If no answer arrives, Friday tells the business: "Sorry for the wait. Could you hold <best option> for 15 minutes? I'll call back to confirm." It then ends the call politely.
  - Friday sends the user: "They offered 4 PM or 6 PM. I've asked them to hold 4 PM. Tap to confirm and I'll call back."
  - If the user replies within 30 minutes, Friday places a **confirmation call** (part of the same task; it does not count against the cap again).
  - After 30 minutes the options expire, and Friday tells the user it can call again for fresh slots.
- **US-5.6** A maximum of **2 mid-call questions per call**. After that, Friday wraps up with the best info it has and asks the user afterwards.
- **US-5.7** A reply to an expired question gets: "That call has ended. Want me to call them back with '6 PM'?" with buttons `Yes, call` / `No`.
- **US-5.8** If the user has 2 concurrent calls, each question clearly names its business, and replies are matched by the WA `context.message_id`. Free text that can't be matched triggers a clarifying question.

### US-6 Call outcomes and retry policy

Every attempt ends with exactly one `outcome`. Retries are automatic. The user is informed according to the "User message" column.

| Outcome | Detection | Retry policy | User message |
|---|---|---|---|
| `success` | Goal confirmed and read back | None | Result report (US-7) |
| `partial` | Some goal met (e.g. an enquiry with some answers unknown) | None, but offer a follow-up action | Report listing what's missing |
| `busy` | Busy signal / SIP 486 | Retry at +10 min and +30 min (3 attempts total) | Only after the final failure, or if the user asks for status |
| `no_answer` | Ringing ≥30 s with no pickup / SIP 480/408 | Retry at +20 min and +90 min (3 attempts) | As above |
| `unreachable` | Switched off, out of coverage, or network error | Retry at +30 min and +2 h (3 attempts) | As above |
| `voicemail_or_ivr` | Answering machine or IVR detected | Treated as `no_answer`. Friday never leaves a voicemail in P1 | As above |
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
- **US-6.5 Call limits.** Max call duration is **6 min**. If the business puts Friday on hold for more than 2 min, Friday ends the call and treats it as `call_back_later` (+30 min).

### US-7 Result report

- **US-7.1** Friday sends the report within **60 s** of call end (p95). Format:
  - **Line 1, the headline outcome**: "Booked. Looks Salon, Sat 11 Oct, 11:00 AM, haircut with Priya."
  - **Details block**: date, time, service, person, price quoted, address, reference number if given, any notes the business gave ("come 10 min early", "cash only").
  - **Next steps**: what Friday will do ("Reminder Sat 9 AM") and one-tap actions (`Add note` / `Reschedule` / `Cancel booking`).
- **US-7.2 Recording**: sent as a WA audio message (voice note) if it is ≤16 MB and ≤5 min. Otherwise Friday sends a one-time, expiring (24 h) link. Recordings are kept for **30 days** (open question Q5), then deleted. The user can say "send recording" for any call in the last 30 days.
- **US-7.3** A **transcript** is available on request ("transcript?"). Friday sends it as a text message, split if needed.
- **US-7.4** Failed or partial reports always say *why*, in one line, and offer the next action.
- **US-7.5** Every task writes an **action log** entry: who, what, when, numbers dialled, outcome, info shared. "What did you do this week?" returns a summary of the log.
- **US-7.6** Booking cancellation or reschedule ("cancel my salon booking") is a new task of type `booking` with subtype `cancel`/`reschedule`, and follows the same flow.

### US-8 Memory

- **US-8.1 Profile**: name, booking name, city, language, tone, quiet-hours override (none in P1), briefing opt-in and time, autonomy settings, linked persons, saved addresses.
- **US-8.2 Businesses**: for each business Friday has called it stores name, number(s), city/area, category, hours learned, staff names, prices quoted (with dates), last visit, and call outcomes. On a later request, "Looks" resolves to the known business. If more than one candidate matches, Friday asks.
- **US-8.3 Facts and dates.** Friday extracts facts from any user message, including messages not about tasks: "rent due on 5th", "insurance expires in March", "Maa's birthday is 12 Dec", "I'm vegetarian".
  - Each fact stores `subject`, `predicate`, `value`, `recurrence` (none/monthly/yearly), the `source_message_id`, a `confidence` score and `created_at`.
  - Facts with confidence ≥0.8 are saved, and Friday acknowledges them inline in ≤1 short line ("Noted: rent due on the 5th, I'll remind you on the 4th.").
  - Facts below 0.8 are confirmed with a question first.
  - Facts are never extracted from call audio of the business side beyond the task's own results.
- **US-8.4 "What do you know about me?"** returns a grouped list (profile, people, places, dates, preferences). Each item can be removed via "forget …" (US-11).
- **US-8.5** Memory is per user. A beneficiary's data belongs to the user who added it.
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
- For home-service bookings Friday sends a check at slot end + 1 h: "Did the plumber come?" with `Yes, all done` / `No-show, call them` / `Still waiting`.
  - `No-show` triggers a call task that asks for an ETA or reschedules.
- For enquiries with an obvious next step left untaken, Friday sends at most one follow-up after 24 h, then drops it.
- After service appointments, Friday may optionally ask once "How was it?" to learn preferences. This counts as unprompted.

**US-9.3 Date nudges from facts.**
- Recurring and one-off dates trigger a nudge at a configurable lead time. Defaults:
  - bills/rent: 1 day before
  - renewals/expiries: 30 days and 7 days before
  - birthdays/anniversaries: 3 days before
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
| 4 | Act automatically | Friday starts the action without asking, then reports. Requires **explicit opt-in and the PIN** for that category. **Booking confirmation still requires the user's approval of the slot and price (US-3.11)**, so in practice level 4 means "place the call and come back with options". Fully automatic results apply only to enquiries, reminders and follow-up calls |

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

## 5. Outbound call script structure

The call agent runs as a state machine with an LLM inside each state. The task spec, the allowed-to-share info and the constraints are injected. Speech is Hinglish by default (US-13.2).

**States:** `OPENING → PURPOSE → GOAL_PURSUIT ⇄ (OBJECTION | USER_QUESTION | HOLD) → CONFIRM → CLOSING`

1. **OPENING (AI disclosure, mandatory, always the first sentence)**
   - EN: "Hi, I'm Friday, an AI assistant calling on behalf of Ankit Sharma."
   - Hinglish: "Namaste ji, main Friday bol rahi hoon, ek AI assistant, Ankit Sharma ki taraf se call kar rahi hoon."
   - Then a business check: "Kya yeh Looks Salon hai?" ("Is this Looks Salon?") If the answer is no, the outcome is `wrong_number`.
   - Recording notice (pending Q4): "Yeh call record ho rahi hai." ("This call is being recorded.")
2. **PURPOSE (one sentence, the ask first)**: "Mujhe Saturday subah ke liye ek haircut appointment book karna tha." ("I wanted to book a haircut appointment for Saturday morning.")
3. **GOAL_PURSUIT**
   - Ask for options, match them against the constraints and choose within the stated flexibility.
   - For enquiries, ask the questions in order, one at a time.
   - Use short turns of ≤2 sentences, "ji" for politeness, and numbers spoken clearly ("saade gyaarah baje", i.e. "half past eleven").
   - If Friday doesn't catch something, it asks once for a repeat ("Sorry ji, ek baar phir bolenge?", i.e. "Sorry, could you say that once more?"). After a second miss it rephrases as a yes/no question.
   - Friday never invents a fact it wasn't given. If it is asked something it doesn't know: "Main confirm karke batati hoon." ("I'll check and let you know.") It then logs this as a follow-up for the user.
4. **OBJECTION handling.** Friday gets one polite, short attempt per objection, then accepts the answer:
   - *"Hum robot se baat nahi karte" / "We don't talk to robots"*: "Bilkul samajh sakti hoon ji. Bas 30 second ka kaam hai, Ankit ji ke liye ek appointment chahiye tha." ("Completely understand. It's a 30-second job, I just need an appointment for Ankit.") If they refuse again: "Koi baat nahi, thank you ji." ("No problem, thank you.") Then end the call → `business_refused`.
   - *"Are you a real person?"*: Always answer truthfully: "Nahi ji, main AI assistant hoon, Ankit ji ki taraf se." ("No, I'm an AI assistant calling for Ankit.")
   - *"Tell him to call himself" / "Give me his number"*: Offer the booking name and, if allowed (US-3.7), the number. Otherwise: "Main unhe aapka message de dungi." ("I'll pass your message on to him.") Then → `escalated`.
   - *"Who gave you this number?"*: "Ankit ji ne diya, woh aapke customer hain / aana chahte hain." ("Ankit gave it to me. He's your customer / wants to visit.")
   - *"Call later" / "Busy hoon"*: Ask "Kab call karun?" ("When should I call?") → `call_back_later`.
   - *"Don't call this number again"*: Apologise → `do_not_call`.
   - *Rude or abusive*: Stay polite, make one attempt, then end → `business_refused`.
5. **USER_QUESTION / HOLD**: see US-5 and US-6.5.
6. **CONFIRM (mandatory before success)**: read back every key detail and get an explicit yes.
   - "Toh confirm kar leti hoon: Ankit Sharma, haircut, is Saturday 11 October, subah 11 baje, Priya ke saath. Sahi hai?" ("Let me confirm: Ankit Sharma, haircut, this Saturday 11 October, 11 in the morning, with Priya. Is that right?")
   - For enquiries: "Toh Dolo 650 available hai, aur dukaan raat 10 baje tak khuli hai. Theek?" ("So Dolo 650 is in stock and the shop is open until 10 at night. Right?")
7. **CLOSING**: "Bahut shukriya ji! Aapko confirmation ka SMS aa jayega. Have a nice day." ("Thank you so much! You'll get a confirmation SMS.") The SMS line is said only if US-12 will send one.

**Hard rules** (enforced in the system prompt **and** by output filters plus post-call audit):
- Never say or ask for a PIN, OTP, password, card, UPI or bank details, Aadhaar or PAN.
- Never agree to pay, prepay, put down a deposit, accept cancellation charges or give any money commitment. Never accept "pay on arrival" terms on the user's behalf beyond noting them.
- Never claim to be human. Never deny being an AI. Never impersonate the user.
- Never share info beyond US-3.7.
- **Escalate to the user** (mid-call if possible, otherwise after) when any of these happen: a deposit or advance is asked for; a price exceeds the user's stated limit; no option fits the constraints; the business asks something Friday doesn't know; there is a medical or legal question; or Friday is unsure what the user would want. *When uncertain, ask; don't guess.*
- Stay on task. Decline unrelated conversation politely.
- Max 6 min per call.

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

### 6.2 Booking with a mid-call question (Hinglish)

```
User:   Looks salon indiranagar mein sat ko haircut book kar do, 080 4123 4567
Friday: Calling Looks Salon now, haircut, Sat 11 Oct. Koi time preference?
        Nahi toh main subah ka try karti hoon.
User:   subah 11 ke aaspaas
Friday: Theek hai, calling now. Kuch poochna hua toh yahin ping karungi.
        ...
Friday: 📞 Looks Salon is asking: 11 baje full hai. Kaunsa chalega?
        [10:00 AM] [12:30 PM] [None of these]
User:   12:30 wala
Friday: ...
Friday: Ho gaya! ✅
        Looks Salon, Indiranagar
        Sat 11 Oct, 12:30 PM · Haircut with Priya
        Price: ₹600 (pay at salon)
        Note: 10 min pehle aana
        Main Sat 10:30 baje remind karungi.
        🎧 [recording voice note]
        [Add note] [Reschedule] [Cancel booking]
```

### 6.3 Mid-call question timeout

```
Friday: 📞 Dr. Mehta's clinic offers: [Thu 5 PM] [Fri 6 PM] [None of these]
        (45 s pass, no reply)
Friday: You were busy, no worries. I asked the clinic to hold Thu 5 PM for 15 min.
        [Confirm Thu 5 PM] [Fri 6 PM instead] [Leave it]
User:   [Confirm Thu 5 PM]          (8 min later)
Friday: Calling them back to confirm…
Friday: Confirmed. Dr. Mehta, Thu 9 Oct, 5:00 PM.
```

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
(`Find another place` in P1 asks the user for a number; it does not search. See Q2.)

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

### 6.9 NRI: on behalf of a parent

```
User (+1 415…): Need a cardiologist appointment for my dad Suresh Verma (68) at Fortis
        Vasant Kunj, any weekday morning next week. 011 4277 6222
Friday: Calling Fortis Vasant Kunj for your father Suresh Verma (68), cardiology,
        a weekday morning between 13 and 17 Oct. Which number should the hospital have for him?
User:   +91 98110 12345
Friday: Saved Suresh Verma as your dad. Calling now. (It's 9:40 AM in Delhi.)
Friday: Booked. Fortis Vasant Kunj, Dr. Kapoor (Cardiology)
        Tue 14 Oct, 10:15 AM · Reg. fee ₹1,200, payable at reception
        Bring: previous ECG reports
        Want me to remind your dad too? (P1: I can only message you)
```

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
Friday:   Ek minute ji, Ankit ji se confirm kar leti hoon… 12:30 chalega.
          Toh confirm kar leti hoon: Ankit Sharma, haircut, Saturday 11 October, 12:30 baje. Sahi hai?
Business: Haan, Priya karegi. ₹600. 10 minute pehle aana.
Friday:   Perfect, shukriya ji! Aapko confirmation SMS aa jayega.
```

---

## 7. Edge cases and error states

| # | Situation | Expected behaviour |
|---|---|---|
| E1 | Task without a phone number and no memory match | Ask for the number or contact card (US-3.2). Friday never guesses a number |
| E2 | Number is toll-free, IVR, international, a short code or an emergency number | Decline with the reason. For emergency numbers: "Please call 112 directly". For IVR/customer care: "That's coming in a later version" |
| E3 | Request to call a private person (e.g. "call my ex", "call my mom and tell her…") | Decline in P1: "I can only call businesses and service providers for now." Service providers' personal mobiles (maid, tutor, plumber) are allowed for bookings/enquiries |
| E4 | Harassing, prank, illegal or deceptive goal (e.g. "pretend to be police") | Refuse. Log `task_refused_policy`. Repeated abuse → account flagged for review |
| E5 | Ambiguous dates ("kal" sent at 00:30; "Saturday" sent on a Saturday) | Before 04:00, "kal" means the upcoming day after the night. A day name sent on that same day means the next week, unless the user said "aaj"/"today". If confidence is < 0.8, confirm the absolute date |
| E6 | User asks for a call during quiet hours or outside the call window | Friday replies normally and schedules the call for 09:00/09:30 (or the business's opening hours): "They're probably closed. I'll call at 9:30 AM." |
| E7 | Duplicate request (same business and goal within 2 h) | "I'm already on it. Should I call again anyway?" |
| E8 | User sends a new message mid-call that isn't an answer | Friday handles it as a normal chat. If it changes the task ("actually make it Sunday"), Friday relays the change to the live call when possible |
| E9 | User cancels mid-call ("cancel", "stop the call") | Friday politely wraps up with the business ("Sorry ji, plan change ho gaya", i.e. "Sorry, the plans have changed") and ends the call. Outcome `cancelled_by_user`. Counts as a connected call |
| E10 | Business confirms, then later calls back to change it (inbound, US-16) | Notify the user (urgent). Offer to call back and re-confirm |
| E11 | Recording failed | The report is sent without the recording, with the note "Recording unavailable for this call" |
| E12 | STT/LLM latency spike mid-call (>3 s silence) | Filler line ("Ek second ji…", i.e. "One second…"). After more than 2 consecutive spikes, apologise and end → `failed_system` with an auto-retry |
| E13 | WhatsApp delivery fails, or the account is restricted or banned (policy risk) | Fall back to DLT SMS templates for results and reminders (§8.3). Core state is channel-agnostic (see ARCHITECTURE). An ops alert is raised |
| E14 | User blocks Friday on WA | Delivery failures are detected → pause all proactive messages. Nothing is sent by SMS except results of in-flight tasks |
| E15 | Cap reached while retries are pending | Retries continue (US-2.6) |
| E16 | User account deleted with tasks in flight | Live calls end politely and scheduled retries are cancelled. No business touch is sent |
| E17 | Business gives contradictory info within the call | Friday clarifies once during CONFIRM. If still unclear, the outcome is `partial` with both values reported |
| E18 | User replies "1234" unprompted (looks like a PIN) | Not treated as a PIN outside a PIN flow. If it matches the PIN hash, Friday warns: "Looks like your PIN. Please delete that message. I only ask for it when you start a sensitive action." |
| E19 | Business asks to speak to the customer | Friday offers to pass a message and a callback (if the number is shareable) → `escalated` with the business's request quoted |
| E20 | Unsupported language spoken by the business (e.g. Kannada, Marathi) | Friday tries Hindi, then English. If neither works: "Sorry, I'll have Ankit call you", ends the call → `partial`/`failed` with reason `language`. Logged to size P2+ language demand |
| E21 | User in another time zone (NRI) | Quiet hours and the briefing use IST in P1 (Q6). Friday shows "(9:40 AM in Delhi)" when it helps |
| E22 | User sends a voice note longer than 3 min, an image or a document | Voice: ask the user to split it. Image/doc: "I can't read images yet. Could you type it?" (Exception: a contact card vCard is parsed) |
| E23 | Concurrent calls >2 | The 3rd task is queued: "I'll call them right after the current two." |
| E24 | Distress signal | US-15 |

## 8. Templates

### 8.1 WhatsApp templates (submit for Meta approval in `en` and `hi`; Hinglish uses `en` with Romanised Hindi body variants. See Q9)

Category is `UTILITY` unless noted. Every template's footer: "Reply STOP to stop these."

| Name | Category | Body (`{{n}}` = variable) | Buttons (quick reply) |
|---|---|---|---|
| `friday_appointment_reminder` | UTILITY | "Reminder: {{1}} at {{2}}, {{3}}. Address: {{4}}." (1=service/business, 2=time, 3=day/date, 4=address) | `Got it` · `Running late` · `Reschedule` |
| `friday_task_update` | UTILITY | "Update on your request to {{1}}: {{2}}. Tap to see details." (1=task summary, 2=one-line outcome) | `See details` |
| `friday_call_question` | UTILITY | "{{1}} is asking a quick question about your {{2}}. Tap to answer." (1=business, 2=task) | `Answer now` |
| `friday_followup_check` | UTILITY | "Did {{1}} come for {{2}} on {{3}}?" | `Yes, all done` · `No-show, call them` · `Still waiting` |
| `friday_date_nudge` | UTILITY | "Heads up: {{1}} is on {{2}}. Want me to {{3}}?" (3=offered action) | `Yes, do it` · `Remind me later` · `Not needed` |
| `friday_pattern_nudge` | MARKETING (likely; see Q10) | "It's been {{1}} since your last {{2}} at {{3}}. Book your usual {{4}}?" | `Book it` · `Not now` · `Stop these` |
| `friday_morning_briefing` | UTILITY | "Good morning {{1}}! Today: {{2}}. Coming up: {{3}}." | `See more` · `Briefing off` |
| `friday_business_change` | UTILITY | "{{1}} has changed your booking for {{2}}: {{3}}. What should I do?" | `Accept` · `Call them` · `Cancel it` |
| `friday_cap_reset` | UTILITY | "Your Friday calls have reset. You have {{1}} calls for {{2}}." | `Make a call` |
| `friday_business_touch` (to businesses) | UTILITY | "Booking confirmed via Friday for {{1}}: {{2}} on {{3}} at {{4}}. Friday is an AI assistant that books on behalf of customers." | `OK` · `Stop messages` |

Rule: every template send stores `template_name`, `language`, `variables` and `wa_message_id` in the action log.

### 8.2 Chat-only messages (sent inside the window; listed for copy review)
`consent_summary`, `capability_card`, `cap_warning`, `cap_reached`, `waitlist_ack`, `delete_confirmation`, `pause_confirmation`.

### 8.3 SMS (DLT-registered; sender ID e.g. `FRIDAI`, principal entity Friday; `{#var#}` = DLT variable)

| Template | Type | Text |
|---|---|---|
| `biz_booking_confirmation` | Service-implicit | "Booking confirmed via Friday: {#var#} on {#var#} at {#var#} for {#var#}. Friday is an AI assistant booking for customers. To stop msgs reply STOP {#var#}" |
| `biz_enquiry_thanks` | Service-implicit | "Thank you for taking a call from Friday (AI assistant) for a customer today. To stop msgs reply STOP {#var#}" |
| `user_task_result` (WA fallback) | Service-implicit | "Friday: {#var#}. {#var#}. Details on WhatsApp." |
| `user_appointment_reminder` (WA fallback) | Service-implicit | "Friday reminder: {#var#} at {#var#} on {#var#}." |
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
- Retention D7/D30; invites sent and redeemed per user; cap-hit rate.
- Trust: deletion requests and completion time (SLA 24 h); hard-rule violations found in post-call audits (target 0).
- Business: touches sent; business STOP rate; DNC additions.

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
| `task_completed` | task_id, final_outcome, attempts, total_duration_s, counted_against_cap |
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
| `cap_warning_sent` / `cap_reached` | month, used |
| `business_touch_sent` | business_id, channel, template |
| `business_opt_out` | business_id, source |
| `inbound_call_received` | matched_task (bool) |
| `safety_signal_detected` | severity |
| `hard_rule_violation_detected` | rule, task_id (from the post-call audit) |

---

## 10. Open questions (need founder decision)

| # | Question | PM recommendation |
|---|---|---|
| Q1 | Friday's voice and grammatical gender in Hindi (affects TTS voice and every Hindi string) | Female voice and feminine verb forms ("karti hoon"). The copy above assumes this |
| Q2 | Business number discovery: should P1 look up numbers (Google Places / Justdial) for "book a table at Toit"? | Not in the P1 MVP, which requires the user to give the number. Add Places lookup in P1.1, since it hugely reduces friction |
| Q3 | Cap accounting: per connected task (proposed) or per attempt? Is 10/month right? | Per connected task, 10/month. Revisit using cost data |
| Q4 | Announce call recording in the opening line? It adds ~2 s and may raise the hang-up rate. Indian law is generally one-party consent, but disclosure is the safer trust posture | Yes, announce it; A/B the phrasing |
| Q5 | Retention for recordings and transcripts | 30 days, then auto-delete. Summaries are kept until the user deletes them |
| Q6 | Quiet hours for NRIs: IST (per BRIEF) or user-local? | Keep IST for P1 per BRIEF. Add user-local time zone in P1.1 |
| Q7 | "Delete everything": what may we legally retain (consent log, invite graph, DNC flags, phone-number hash to stop cap abuse)? | Retain only a salted phone hash, cap counters and consent/deletion receipts. Get legal sign-off |
| Q8 | PIN reset flow (forgotten PIN) | SMS OTP to the registered number, plus a 24 h cool-down before PIN-gated actions. Foreign numbers need support-assisted reset |
| Q9 | Hinglish templates: Meta has no Hinglish locale. Register Romanised Hindi under `en`? | Yes, with separate template names (`*_hinglish`) |
| Q10 | Will Meta classify pattern nudges as MARKETING (higher cost, opt-in rules, possible policy exposure)? | Phrase them as reminders tied to the user's own past bookings to qualify as UTILITY. Accept MARKETING if rejected |
| Q11 | Share the user's mobile number with businesses by default for bookings? | Yes by default, with one-line disclosure at the first booking and an easy off switch |
| Q12 | Default call-opening language: Hinglish everywhere, or Hindi in NCR and English in Bengaluru? | Hinglish default, plus learned per-business preference |
| Q13 | Should level 4 (auto-act) be available at all in the beta? | Yes for `personal_care`, `dining`, `enquiries`, `follow_ups` and `reminders`; not for `health` or `home_services` |
| Q14 | Global DNC: one business's "don't call" blocks all Friday users from calling that number. Is that acceptable for users? | Yes. Respecting businesses matters for P5 Friday for Business |
| Q15 | Caller ID: use one shared number pool or a dedicated number per city? Businesses that save "Friday" may block it | City-level pools with a consistent display name. Monitor block and answer rates |
