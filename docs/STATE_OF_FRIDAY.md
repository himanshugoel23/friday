# State of Friday (16 Oct 2026)

## What Friday is
A proactive personal assistant for Indian users on WhatsApp, calls and SMS that acts for the user.
Phase 1 = calling vendors. Positioning: the assistant with no sales pitch, free of platform bias.

## Built and tested (in the repo, pushed)
- **Voice call stack:** Ritu voice on Sarvam (STT, TTS streaming, call-turn LLM), Vobiz telephony,
  barge-in that stops her when the business speaks, latency about 1 s per turn, droplet deployed and
  answering calls.
- **Playbook engine:** scripted (never improvised) call flows with facts, intents, switches, a pool of
  6 acknowledgements, resume after interruption, negotiate and confirm modes, price parsing (lakh/crore),
  code-level safety (no invented numbers, no OTP/PIN, user limits, never books a different time).
- **10 call scripts as PENDING playbooks** (validate and dry-run 100%): salon, quote and slot,
  enquiry, home service visit, PG, cab, stock and price, table, hotel, banquet. Not live until the
  founder hears audio and approves.
- **22 vendor categories** mapped to these archetypes; project manager asks only missing facts.
- **WhatsApp-first quotes flow:** text in, missing-info questions, Google Places shortlist ("best AND
  near", hard radius), approval buttons, sequential calls, one comparison message, booking call.
  Onboarding places form spec (home, parents, office).
- **Scouting agents:** place search, eligibility, review authenticity, fit scoring, ranker.
- **Retries:** +1 h then +3 h, max 3 attempts, then tells the user.
- **Proactive engine:** nudges, caps, quiet hours.
- **Learning loop (never changes spoken words on its own):** style dictionary, masked utterance log,
  review queue, 125 synthetic labels (baseline 74.4%), `friday learn report|label|eval|fewshot`.
- **Data:** Supabase schema with row-level security applied to the Singapore project.
- **Research and decisions:** competitors (Puch, Instinct, Muse, Google, ghost.ai, typesafe ai/Jev),
  differentiators, wider beta scope, savings engine, bill/payment/cab/hotel/quick-commerce API
  availability, Google connector plan, family-care and on-device notes.

## Waiting on the founder
1. Supabase: reset the database password, pull the latest code, run `deploy/supabase/set-database-url.sh`,
   restart the service, disable the `http` extension. Then Claude verifies the connection.
2. Approvals: worker-added glue lines in the scripts; audio review of each pending playbook.
3. Business name, privacy policy page, company registration (needed for Google, WhatsApp number,
   partners).
4. WhatsApp Business number (new SIM bought; applied).
5. Decisions listed in BETA_SCOPE_PROPOSAL.md and DIFFERENTIATORS.md: wow features, revenue model
   (business pays per booking, fee model open), payment model (user pays by link), first apps.
6. Legal read: TRAI/DLT, DPDP, RBI/BBPS, IRDAI/SEBI, Account Aggregator, call consent.

## Not built yet
- Callback tasks end to end (negotiate and confirm wired to WhatsApp buttons); 30-minute user reminder;
  storing the business's call-back time; skipping already-answered steps on retry.
- Audio-review kit and promotion of pending scripts; recording storage bucket; vendor-side info page
  and opt-out; user memory view and delete; proactive wiring to new callbacks.
- Everything in the wider beta: Google sign-in and Calendar/Gmail, bill reminders, food and grocery
  comparison, card/app savings engine, subscription finder, email sending, shareable comparison pages,
  travel and ticket booking, family care, devices.
- Mumbai Pro Supabase project before real users.

## Life admin (founder ask, 16 Oct): Instinct-style scope
Books travel and restaurants, buys groceries and tickets, cancels subscriptions, sends email, builds
shareable comparison pages. Map to Friday: restaurants (table playbook, built), travel (hotel/cab
playbooks built; flights and trains need partner APIs), groceries (comparison + link-out first),
tickets (link-out), cancel subscriptions (detect + call or guide), email (draft and send only after
the user approves), comparison pages (outcome page per request, the first one to build because it is
cheap and also serves as proof).
