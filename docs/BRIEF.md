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
