# Friday — Founding Brief (source of truth for all decisions so far)

## Vision
Friday is a JARVIS-style personal AI assistant for **Indian consumers**. It doesn't just answer —
it **acts in the real world** (makes phone calls for you), **remembers you**, and is **proactive**.
No app, no website: users reach Friday only via **WhatsApp, voice call, and SMS**.

## Decisions already made
- **Consumers first.** Business side comes later; every outbound call is a lead-gen touch for it.
- **Channels:** WhatsApp (primary chat), voice call (backbone, works without internet/feature phones), SMS (DLT-templated notifications only — no free-form outbound SMS in India).
  - Meta's Jan-2026 WhatsApp Business policy bans "AI-is-the-product" assistants → architecture must be **channel-agnostic** so WhatsApp can be lost without killing the product.
  - WhatsApp: free-form replies only within **24h of the user's last message**; outside that, only **pre-approved template messages**.
- **No web exceptions:** one-time links only for OAuth (later phases) and full T&C text.
- **Language:** Hindi, English, Hinglish.
- **Personality:** consistent character — witty, warm, concise, calm in crises. User can choose formal/playful tone.
- **Trust > autonomy:** never pay or commit without approval; AI always discloses itself on calls
  ("Hi, I'm Friday, an AI assistant calling on behalf of <name>"); full action log; delete-my-data by chat.
- **Identity:** phone number + 4-digit Friday PIN for sensitive actions.
- **Compliance:** DPDP Act 2023 consent (record user's "I agree"), data stored in India, TRAI/DLT for SMS.
- **Invite-only:** 5 invites per user; no usage cap in beta (see founder decisions).

## Phase 1 scope (what we are building now)
1. **Outbound calling agent** — user asks on WhatsApp (text or voice note); Friday places a real phone call
   to a business in Hindi/English/Hinglish; handles busy / no answer / call-back-later.
   Task types: **bookings** (clinic, salon, restaurant, service providers) and **enquiries** (open? price? stock?).
2. **Ask the user** on WhatsApp ("4pm or 6pm?") with reply buttons — default is call-back-after-confirmation (see founder decisions).
3. **Result report**: summary, booking details, call recording (as voice note/link), next steps.
4. **Memory**: name, city, language, tone, businesses called, facts/dates extracted from chats
   ("rent due on 5th", "insurance expires March").
5. **Proactive v1**:
   - reminders for Friday's own tasks (appointment in 2h), auto follow-ups (plumber didn't come?)
   - date-based nudges from extracted facts
   - pattern nudges ("4 weeks since haircut — book usual?")
   - opt-in morning briefing
   - **Autonomy levels per category**: 1 inform, 2 suggest, 3 act-with-approval, 4 act-automatically (explicit opt-in)
   - **Guardrails**: max 3 unprompted msgs/day (except urgent), quiet hours 22:00–08:00 IST (except safety),
     learn from ignores, every nudge offers an action, proactive WA msgs outside 24h use templates.
6. **Onboarding via chat**: name, city, language, consent, PIN, first task ("one call you've been avoiding").
7. **Invite-only access** with invite codes (no usage cap in beta; internal cost tracking only).
8. **End-of-call business touch**: after each call, templated SMS/WA to the business
   ("Booking for X confirmed via Friday …") — groundwork for B2B.

## Founder requirements for the voice agent (added — these override anything above)
1. **Language mirroring.** Default opening in **Hinglish**. Detect the language the business representative
   actually speaks, turn by turn, and **switch to match it** (Hindi, English, Hinglish; other Indian languages
   such as Tamil/Telugu/Kannada/Marathi/Bengali when the STT/TTS provider supports them). If the rep switches
   mid-call, Friday switches too.
2. **Price quotations & negotiation.** Friday can ask for a quote, clarify what's included, and **negotiate**
   (ask for discounts, compare with other quotes it has gathered, ask for package deals) — strictly within the
   user's stated budget/limits. It never agrees to pay or commits money; it brings the best offer back.
3. **Book only after asking the user ("owner") first.** Before confirming any appointment/booking, Friday
   checks with the user (mid-call question, or puts the business on a brief hold / calls back) and only
   confirms after the user approves the slot/price.
4. **Discovery → shortlist → call.** When the user doesn't name a business ("find me a good AC repair guy
   near Indiranagar"), Friday searches businesses (places/maps provider), **reads ratings & reviews**,
   **shortlists the best few** (with short reasons), gets their **phone numbers**, and **calls them** —
   one after another or comparing quotes — then reports a comparison to the user and books the chosen one.
5. **Clearly an AI — never pretends to be human.** Discloses it's an AI at the start of every call and
   answers honestly if asked. Voice is **clean, calm, polished and confident — like JARVIS / F.R.I.D.A.Y.**:
   no fake fillers ("umm", "uh", fake breaths, fake typing sounds), no pretend hesitations.
6. **Goal-driven, not scripted.** No hand-written Q&A trees per business type. The call agent is given a
   **goal + constraints + user context** (what to achieve, budget, preferred times, what it may/may not
   disclose) and converses freely with an LLM to achieve it, handling whatever the rep says.
   Only safety rules and the disclosure line are fixed.

## Founder requirements: people & places (added — Phase 1 scope)
Users book for **themselves and for others** — parents, spouse, kids, friends. NRIs managing their parents'
errands in India are a core segment, so this must work from day one.
1. **People (circle).** The user can create profiles for people they take care of: name, relation
   (mom, dad, spouse, friend…), phone, preferred language, addresses, and optional notes
   (e.g. "dad is diabetic, prefers morning appointments", "mom only speaks Marathi").
   Tasks have a **beneficiary** (who the booking is for) separate from the **requester** (the user).
2. **Places.** Saved, labelled addresses: Home, Office, "Mom & Dad's home", "Priya's place", etc.,
   geocoded (lat/lng) and linked to people. Created by typed/spoken address, a pasted Google Maps link, or a
   **WhatsApp location pin**. No app → no background GPS; location comes only from what the user shares
   (in chat or by voice), plus "current location" pins shared in the moment.
3. **Recognition.** The AI resolves natural references to saved people and places, in English and Hinglish:
   "book a doctor for papa near their home", "mummy ke ghar ke paas", "near my office", "his place" (from
   context). If ambiguous, it asks once ("Mom & Dad's Pune home or the Delhi flat?"). It learns new aliases
   ("PG" = Bengaluru home, "Nani's" = grandma's house).
4. **Onboarding.** Optional quick setup: "Who else do you look after?" and "Save your home and office?"
   Users can also add people and places anytime by chat ("add my dad, +91 98xxxx, lives in Jaipur").
5. **Beneficiary communication & consent.** Friday can send booking confirmations and reminders to the
   beneficiary (e.g. dad gets an SMS/WhatsApp/voice reminder in his language) only after that person has
   opted in once (a one-time consent message to them). Share with businesses only the minimum needed
   (name, phone, address for home visits). Never share one family member's notes with another unless the
   user set that up.
6. **Proactive** nudges can be about the people the user cares for ("Dad's BP check is due next week, book
   the usual clinic?").

## Founder requirements: full "real-world footwork" coverage (added — Phase 1 scope)
Goal: Phase 1 covers every offline task that today needs a human to phone/coordinate with a business or person.
Because calls are goal-driven (CallBrief), most of these are **new task types / brief templates**, not new engines.

**A. New task types on the existing call engine (Phase 1, priority 1)**
1. Reschedule / cancel an existing booking.
2. Reconfirm day-before ("is my 7pm table still on?"); running-late notice to a business.
3. Phone orders: pharmacy (availability + home delivery), kirana, water cans, tiffin.
4. Availability/stock hunt across many businesses ("which chemist near Dad's home has X?") — stop at first match.
5. Service-provider coordination: plumber/electrician/carpenter/AC — get ETA, chase no-shows, confirm arrival,
   confirm with user that work was done.
6. Status chasing: repair shop, tailor, dry cleaner, local shop refund/delivery.
7. Complaints to local businesses (non-IVR).
8. Rental hunting: call brokers/landlords — rent, deposit, bachelors/pets allowed, visit slots.
9. Big-ticket quote collection + negotiation: packers & movers, wedding/event vendors, venues, car service, interiors.
10. Healthcare for family: doctor slots, lab home collection, physio/nurse/attendant home visits.
11. Enquiries: tutors, coaching, school admissions, gyms.
12. Recurring bookings (weekly physio, monthly haircut, quarterly AC service) — auto-scheduled.
13. **Daily/regular wellbeing check-in calls to a circle member** (e.g. NRI's parents), only with that person's
    opt-in: friendly call in their language (medicine taken? feeling okay? anything needed?), short summary to
    the user, and alert the user if something sounds wrong. Never gives medical advice.

**B. Engine additions (Phase 1, priority 1: 14, 15, 20, 19; priority 2: 16, 17, 18)**
14. **Parallel calling** — call N businesses concurrently (configurable concurrency), aggregate results.
15. **WhatsApp-to-business channel** — message a business on WhatsApp when it doesn't answer or to receive menus /
    price lists / quote photos; extract structured info from images/PDFs.
16. **Scam / fake-number check** — verify a business number (multiple listings, official site, past call history,
    known-scam list) before calling or sharing any details; warn the user.
17. **Warm transfer / three-way call** — Friday reaches the right person, then patches the user in.
18. **Live translator mode** — user + business on one call, Friday translates both ways.
19. **Call timing intelligence** — business hours, lunch/Sunday closures, best time to call, call queue.
20. **Vendor memory** — every business used: prices quoted/paid, reliability, user rating, notes
    ("your usual electrician Ramesh charged ₹400 last time"); used for recommendations and negotiation leverage.

**C. Customer-care / IVR calls (Phase 1 — founder decision)**
21. Customer-care calls to large companies (telecom e.g. Airtel/Jio/Vi, broadband, banks/cards, insurers,
    e-commerce/food delivery, airlines, utilities): complaints, refunds, disputes, cancellations, escalations,
    service requests, status of existing tickets.
22. **IVR navigation**: understand spoken IVR menus (Hindi/English) and press keys (DTMF) or speak options;
    handle "enter your registered mobile number / account number" prompts using details the user saved and
    approved for this task; recover from wrong branches; prefer the "talk to an agent" path.
23. **Hold handling**: detect hold music / queue announcements and switch to a low-cost listening mode
    (no LLM turns) until a human agent answers; tell the user the expected wait; give up after a configurable
    max hold and retry at a better time.
24. **Verification**: never read out OTPs, PINs, CVV or passwords. When the company insists on account-holder
    verification, Friday **patches the user in** (three-way) or asks the user to call back with the ticket
    context it gathered. Only share account identifiers the user approved for this specific call.
25. **Escalation & outcomes**: capture ticket/complaint numbers, promised resolution dates, agent names;
    request escalation to supervisor / grievance officer when the first agent can't resolve; schedule
    automatic follow-up calls when promised dates pass; suggest formal escalation routes when appropriate
    (e.g. grievance officer, ombudsman) as text guidance.
26. **Official numbers only**: customer-care numbers come from a curated/verified directory + the scam check
    (fake customer-care numbers are a major fraud vector in India).

**D. Hotel & stay bookings (Phase 1 — founder decision)**
27. Hotel/homestay/guesthouse booking for the user or a circle member. Hybrid flow:
    (a) search & compare via an official hotel API (Expedia Rapid first; Booking.com/Agoda affiliate later) plus
    places/reviews for ratings; (b) **call the property directly** for manual bookings — many Indian hotels,
    homestays and guesthouses are offline or give better direct rates: check availability, room type, inclusions
    (breakfast, early check-in), negotiate the direct rate, ask them to hold the room, get confirmation by
    WhatsApp/SMS. Always confirm with the user before booking.
28. No payments in Phase 1: book "pay at hotel" rates, or send the user the official booking/payment link, or have
    the property hold the room against the user's own payment. Reconfirm the booking with the property the day
    before check-in; handle modifications/cancellations by call.
29. Unofficial scraping MCPs are not used (ToS risk). The hotel provider sits behind a `HotelProvider` interface
    with a simulator.

**E. Business call-backs & missed calls to Friday's number (Phase 1 — founder decision)**
30. **Call memory.** Every outbound call records which Friday caller-ID number called which business number, for
    which task/user, when, and the outcome. Caller-ID numbers are **sticky** per business (the same Friday
    number is reused for the same business) so call-backs route back reliably.
31. **Business calls back (answered).** An inbound call to a Friday number is matched by caller ID (+ the
    Friday number dialled) to recent call memory. Friday answers with the disclosure and context:
    "Hi, this is Friday, an AI assistant. We called you earlier on behalf of Rahul about a haircut on Saturday."
    and **resumes the task** with the same CallBrief (quote, slot, availability). The approval rule still applies.
32. **Missed call / unanswered ring from a business.** Friday logs it against the task and **calls back** promptly
    (respecting business hours and the call queue); after N attempts it informs the user. If the task was already
    completed, Friday still answers/calls back and handles it (e.g. "slot freed up", "your order is ready",
    reschedule) — reopening or creating a follow-up task and notifying the user.
33. **Ambiguity.** Several open tasks with the same business → Friday asks the caller which one ("Is this about
    the haircut or the facial booking?"). Unknown caller with no match → polite AI greeting, take a message
    (name, purpose, call-back number), notify ops/log; do not reveal any user's details.
34. **Safety.** Treat inbound callers as unverified: share only what the CallBrief allows for that business,
    and only if caller ID matches the business record; never accept payment demands; flag mismatches to the
    scam check.
35. Same matching for **WhatsApp/SMS replies from businesses**. The inbound call path reuses the same
    CallSessionRunner (groundwork for Phase 2 user inbound calls).

36. **No-answer retry policy.** If a business doesn't pick up: retry automatically — default 3 attempts total
    (e.g. +10 min, +45 min, then the next good calling window within business hours; never outside hours/lunch
    closures). Between attempts, also try other listed numbers for that business and, if it has WhatsApp,
    send a short WhatsApp request. Tell the user only once ("Looks Salon isn't picking up — I'll keep trying,
    next attempt 4:15pm"), not on every attempt. In discovery/compare/stock-hunt tasks, move on to the next
    candidate in parallel instead of waiting. After the final attempt: report to the user with options
    (try later today / tomorrow / pick another business). Busy signal → shorter retry (+5 min).
37. **Late call-backs after the task is already resolved.** When a business calls back or gives a missed call
    after the need was met, Friday decides by state:
    - **Booked elsewhere / need fulfilled / user cancelled / stock already found:** Friday answers or calls back
      once and **politely closes the loop** ("Thank you for calling back — Rahul's requirement has been taken
      care of, so we won't need it this time."), cancels any pending retries for that business, records it in
      vendor memory, and does not bother the user (only mention it in the task summary).
    - **Booked with this same business:** treat it as being about that booking — reconfirmation, reschedule,
      cancellation, "ready for pickup", directions — handle it and notify the user of anything that changes.
    - **Business offers something materially better after the fact** (e.g. much cheaper, earlier slot): mention
      it to the user once only if the existing booking can be changed without penalty; never switch on her own.
    - **Task still open:** resume it normally (item 31).
    All pending retries and scheduled call-backs are cancelled the moment a task resolves, so Friday never
    calls a business about a need that's already been met.

**Out of Phase 1:** payments/advances (P4), physical errands via human runners (P3),
government portals/paperwork (P4).

## NOT in Phase 1
Payments/UPI (incl. hotel prepayment), Gmail/Calendar, Lifeline/emergency service (opt-in wellbeing check-ins
are in scope but are NOT an emergency service), users calling Friday's number (inbound voice — Phase 2, but the
voice pipeline must be reusable for it), business accounts, agent-to-agent, physical errands via runners,
government portals. (IVR customer care, regional-language mirroring on calls, and hotel bookings ARE in Phase 1.)

## Founder decisions on PRD open questions
Default: the PM recommendations in docs/PRD.md §10 are adopted unless overridden below.

- **Voice (Q1):** Friday is **female** (F.R.I.D.A.Y.-style) — feminine Hindi verb forms ("karti hoon"), female TTS voices.
- **Approval before booking (Q17, Q21) — founder rule:**
  - **Default:** when the business offers a slot/price, Friday does NOT confirm on the call. She tells the business
    she will **call back after confirming with the user** (the "owner"), ends the call, asks the user, and on
    approval **calls back to confirm** (or relays a different choice).
  - **Delegated decision:** only if the user **explicitly** gave Friday authority when giving the task
    (e.g. "book any slot between 5–7pm under ₹800, you decide"), Friday may confirm on the call itself,
    strictly within those limits. Anything outside the limits → call-back flow.
  - Recurring bookings: the user's explicit delegation for the rule (time window + price ceiling) counts as
    authority for each instance; deviations → call-back flow.
- **Scam/fake-number check (B16) and warm transfer/three-way (B17): Priority 1.**
- **Usage cap (Q3, Q16, Q22): no user-facing cap in the beta.** Keep internal per-user cost tracking, alerts and an
  abuse rate-limit (ops-configurable, off by default for invited users); no cap messaging to users.
## Success metrics for Phase 1
>80% call task success, ≥2 requests/user/week by week 3, cost per successful call < ₹15, business hang-up rate < 20%.

## Engineering constraints
- Python 3.11+ (3.13 available), FastAPI, SQLAlchemy (SQLite for dev, Postgres-ready), pytest. Use `uv`.
- LLM: Anthropic Claude via the official `anthropic` SDK.
- Every external provider (WhatsApp Cloud API, telephony e.g. Twilio/Exotel/Plivo, STT, TTS, SMS/DLT, LLM,
  business discovery/places & reviews e.g. Google Places API)
  sits behind an interface with a real implementation **and** a local simulator/fake, so the whole product
  runs end-to-end locally and in tests **without any API keys**.
- Secrets only via environment variables (`.env.example` documents them). Never commit secrets.

## Founder requirement: minimum AI / token cost without hurting UX (applies to all phases)
1. **Model routing:** no LLM for deterministic inputs (buttons, yes/no, commands, status); `claude-haiku-5-5` for
   interpretation, extraction, nudge judgement, summaries, reason-writing; `claude-sonnet-5-5` for live call turns;
   `claude-opus-5-5` only as an escalation for rare hard cases. Never Opus by default.
2. **Prompt caching** of stable prefixes (persona, safety rules, CallBrief, user context) on every LLM call.
3. **Compact context:** rolling summary + last N turns instead of full transcripts; short structured outputs with
   tight `max_tokens`.
4. **Code before AI:** zero LLM on hold; learned IVR menu maps per company replayed without LLM (shared across
   users); pre-rendered TTS for fixed lines (disclosure, hold, call-back); deterministic shortlist ranking (LLM only
   for short reasons); rule/template-first nudges.
5. **Shared caches** of non-personal data (business info, review summaries; TTL 7 days); downscale images.
6. **Batch API** for non-real-time work (fact extraction, nudge planning, vendor memory).
7. **Speech/telephony:** VAD (don't send silence to STT), no STT during hold, end calls promptly, cap concurrency.
8. **Budgets & visibility:** per-call token/cost logging by purpose; per-task token budgets with alert + cheaper
   fallback; ₹ per successful task as a tracked metric.
Guardrails: never degrade live-call quality, safety checks, or responsiveness (p95 turn < 1.5 s).

## Founder requirement: caller-ID reputation & number rotation (Phase 1)
Goal: Friday's numbers must never get labelled spam, because pickup rate is the product.
1. **Number pool per city/telecom circle:** multiple Indian 10-digit numbers (never 140-series), local to the
   business's city where possible ("local presence" raises pickup).
2. **Sticky + rotation together:** a business keeps getting the same Friday number (so call-backs work), but NEW
   businesses are spread across the pool by health and load. A business is moved to another number only when its
   number is retired; the first line then says "Friday here — calling from a new number".
3. **Per-number limits & pacing:** max calls per number per hour/day (ops-configurable, conservative defaults),
   spread calls over time (no bursts), limited concurrency per number, respect calling hours.
4. **Warm-up:** new numbers start with low daily volume and ramp up gradually.
5. **Health scoring per number:** answer rate, very-short-call/hang-up rate (<10 s), "don't call" requests, blocks,
   spam-label checks where available. Below threshold → **cool-down** (no outbound, still answers inbound), then
   recover or **retire**. Retired numbers keep receiving/forwarding call-backs for 30 days.
6. **Verified identity:** register Friday as a verified business caller (e.g. Truecaller for Business verified
   name/badge) and use the telecom operator's registered caller-name display (CNAP) where available, so phones show
   "Friday (AI Assistant)" rather than an unknown number.
7. **Behaviour that prevents reports:** AI disclosure up front, short purposeful calls, strict retry caps, business
   hours only, global do-not-call honoured on **every** number in the pool.
8. **Compliance rule:** rotation is for load-spreading and reputation health — NEVER to get around a business that
   blocked Friday or asked not to be called. Blocks/DNC are honoured across the entire pool.
9. Ops dashboard data: per-number health, volume, status (active / warming / cooling / retired).

## Founder requirement: built for scale (Phase 1 architecture, scale-out ready)
Design target (to validate with load tests): 100k+ users, 1,000+ concurrent live calls at peak, bursts of WhatsApp
webhooks; no lost tasks, no duplicate calls, no double-sent messages.
1. **Stateless API tier** (FastAPI replicas behind a load balancer): webhooks verify, store, **ack fast** and enqueue;
   no in-memory per-user state. **Idempotency keys** for every webhook (WhatsApp/telephony retry deliveries).
2. **Durable job queue** replaces the in-process event bus for anything that must not be lost: task steps, calls,
   retries, scheduled call-backs, nudges, outbound messages (transactional outbox). Postgres-backed queue
   (`FOR UPDATE SKIP LOCKED`) for Phase 1; swappable for SQS/Redis later. Priorities: live-call & user replies >
   task steps > proactive > batch.
3. **Separate worker pools:** task workers, **voice/call workers** (long-lived media WebSockets; a call stays pinned to
   one worker; scale by concurrent calls), proactive/scheduler workers, batch workers.
4. **Distributed scheduling:** scheduled jobs live in the DB (due_at index); exactly-once firing across replicas;
   proactive engine sharded by user.
5. **Distributed per-user locks** (Postgres advisory locks or Redis) instead of in-memory locks; one conversation
   turn per user at a time.
6. **Data:** Postgres with connection pooling (PgBouncer), indexes on hot paths, partitioning of large append-only
   tables (messages, call_turns, audit, costs), read replica later; recordings in object storage (S3) — never DB.
7. **Shared cache** (Redis): business info/reviews, learned IVR maps, pre-rendered TTS audio, rate-limit counters.
8. **Provider limits & backpressure:** per-provider concurrency/rate limiters (LLM tokens/min, telephony calls/sec
   and concurrent channels, STT/TTS streams), circuit breakers + failover (already: Sarvam→Exotel→Twilio).
9. **Observability:** metrics (queue depth, call concurrency, p95 turn latency, error rates, ₹/task), tracing per
   task, alerts; autoscaling on queue depth and concurrent calls.
10. **Load testing:** simulator-driven load test (thousands of simulated users and concurrent calls, no real
    providers) proving the targets before launch.

## Founder requirement: public "front door" number — inbound user calls & voice onboarding (pulled forward from Phase 2)
Goal: one memorable Friday number circulated everywhere (marketing). Anyone can call it (or message the same
brand on WhatsApp) and start onboarding; repeat callers are recognised and served as a personal assistant.
1. **Front-door numbers are separate from the outbound pool.** Stable, never rotated, never used to call businesses.
   Toll-free (1800) and/or a local 10-digit number; a missed call to it triggers a call-back to the caller.
2. **First call (unknown caller ID):** answer instantly; short AI-disclosed greeting; detect the caller's language
   from their first words (open in Hinglish) and mirror it; collect name + city; spoken consent (DPDP) with
   "press 1 to agree" fallback; 18+ confirmation; **PIN entered on the keypad only (never spoken, DTMF masked
   in recordings and logs)**; offer WhatsApp (send a DLT SMS / approved template with a wa.me link — a WhatsApp
   chat can only be opened by the user first or via an approved template); then do their first task on the call.
   Onboarding is a deterministic state machine with pre-rendered prompts; the LLM only handles free-form answers
   (cost control). Short sentences, repeat numbers back, tolerate noise/accents/barge-in.
3. **Repeat call (known caller ID):** short greeting by name, surface pending updates ("your Saturday haircut
   is confirmed; the AC quotes are ready"), take the request, run the same task engine. Results come back by
   WhatsApp, SMS, or a call-back (works on feature phones with no data). Mid-call questions to the user that
   can't be answered live become an SMS/WhatsApp question or a "press 1/2" call-back. Caller ID is not
   authentication: sensitive actions (addresses, notes, identifiers, delete data) require the keypad PIN.
4. **Access policy for a public number:** waitlist/batch admission or a daily cap on NEW onboardings (the founder's
   "no usage cap" applies to onboarded users, not anonymous callers); non-onboarded callers get a short max call
   length.
5. **Abuse protection:** per-caller rate limits, repeat-caller blocklist, prank/silence/abuse detection with fast
   hang-up, premium/international call limits, spend alerts on the front-door number.
6. **Marketing assets:** a QR code + short link that opens WhatsApp chat or tel: dial; Truecaller-verified name
   ("Friday (AI Assistant)"); consistent number everywhere.
7. Reuses the existing CallSessionRunner inbound path (run_inbound), user repositories, onboarding state machine,
   PIN module and task engine. New work: caller classification (user / business / unknown), a voice
   onboarding flow, keypad PIN capture with masking, SMS/WhatsApp hand-off, front-door abuse controls.

## Founder decision: Sarvam-only telephony for now (supersedes the Sarvam → Exotel → Twilio routing)
- Live calling uses **Sarvam only** (Sarvam telephony / its BYO-carrier route, plus Sarvam STT/TTS). **No Exotel for now.**
  Set `FRIDAY_TELEPHONY_PROVIDER=sarvam`. Exotel and Twilio code stays in the repo, unconfigured and disabled by default,
  so a provider can be added back later without rework.
- With no fallback, the Sarvam adapter must be explicit about capability gaps: each feature the product needs from
  telephony is either confirmed supported, degraded gracefully, or reported to the user honestly.
  Features to verify with Sarvam: per-turn control by our own brain / raw audio stream, DTMF sending (IVR), inbound and
  missed-call events, multiple numbers with per-call caller-ID selection (number pool + rotation), call recording,
  transfer/conference (join the user in), concurrency limits, Indian number rental, call-back to a caller.
