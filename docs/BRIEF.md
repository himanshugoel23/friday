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
- **Invite-only:** 5 invites per user; cap free calls (e.g. 10/month in beta).

## Phase 1 scope (what we are building now)
1. **Outbound calling agent** — user asks on WhatsApp (text or voice note); Friday places a real phone call
   to a business in Hindi/English/Hinglish; handles busy / no answer / call-back-later.
   Task types: **bookings** (clinic, salon, restaurant, service providers) and **enquiries** (open? price? stock?).
2. **Mid-call question to user** on WhatsApp ("4pm or 6pm?") with reply buttons; call continues on answer.
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
7. **Invite-only access** with invite codes and per-user call cap.
8. **End-of-call business touch**: after each call, templated SMS/WA to the business
   ("Booking for X confirmed via Friday …") — groundwork for B2B.

## NOT in Phase 1
Customer-care/IVR calls, payments/UPI, Gmail/Calendar, Lifeline/emergency, users calling Friday's number
(inbound voice — Phase 2, but voice pipeline must be reusable for it), business accounts, regional languages
beyond Hindi/English/Hinglish, agent-to-agent.

## Success metrics for Phase 1
>80% call task success, ≥2 requests/user/week by week 3, cost per successful call < ₹15, business hang-up rate < 20%.

## Engineering constraints
- Python 3.11+ (3.13 available), FastAPI, SQLAlchemy (SQLite for dev, Postgres-ready), pytest. Use `uv`.
- LLM: Anthropic Claude via the official `anthropic` SDK.
- Every external provider (WhatsApp Cloud API, telephony e.g. Twilio/Exotel/Plivo, STT, TTS, SMS/DLT, LLM)
  sits behind an interface with a real implementation **and** a local simulator/fake, so the whole product
  runs end-to-end locally and in tests **without any API keys**.
- Secrets only via environment variables (`.env.example` documents them). Never commit secrets.
