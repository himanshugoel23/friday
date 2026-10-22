# State of Friday (22 Oct 2026): full read of all 71 docs + HANDOFF

Compiled from eight reader reports. Legend: BUILT = code + tests with fakes/simulators; VERIFIED = real world. Nothing below is verified on a real vendor or user call except where stated.

## 1. The big picture
Friday = AI assistant for Indian consumers over WhatsApp + phone, Hinglish female voice (Ritu on Sarvam; Vobiz carrier), approval-first, never pays, never sees OTP/PIN/card. Direction history: 10-12 vendor-calling beta (20 categories, wow + proactive) -> 10-14..19 widened (savings engine, life state, Google Calendar/Gmail, consumer calls to anyone, receptionist) -> 10-22 founder: LIVE IN 5 DAYS as a private pilot (docs/GO_LIVE_5_DAYS.md, 5-10 testers). Parked: ordering via browser (Zomato), wake word, social accounts (NEVER), hardware, payments by Friday.

## 2. What is built (switches mostly OFF, ~5,600 tests pass offline)
Salon + 9 other pending playbooks (22 categories, scripts in docs/SCRIPTS_SPEC.md, founder-approved text for 7 types on 10-13), live call engine (297 fixed lines, guards, 111 simulated calls), WhatsApp quotes flow, scouting (best + near, hard radius), classifier + project manager, consumer calls (brief, gate, DNC, caps), savings engine (example rows only), life state + morning brief, Google connector (fake Google), front door (inbound), chatbot pilot (onboarding, consent, menu), voice notes + Devanagari input, voice latency switches (speculative understanding, streamed replies, semantic end-of-turn, Silero VAD), consumer telephony factory + `friday consumer call-test`, receptionist (builder running), doctor command, kill switch.

## 3. What is actually verified in the real world
Live test calls to the founder's phone earlier (Sarvam voice + STT, Vobiz, barge-in fix, first reply gaps 624-779 ms, Sarvam call-turn model 305 ms); Google Places counts for Delhi NCR (20 categories hit the 100 cap, phone 83-99%) and scout-report; Supabase schema applied; ElevenLabs ad analysed. NOT verified: any call with the new engine/consumer calls, WhatsApp Cloud delivery, Meta templates, Hindi STT quality, voicemail/IVR, caller-ID acceptance, Postgres/Redis stack, migrations 0006-0010 on the live DB, real Google OAuth, ffmpeg/TTS on the server, the 21-Oct latency switches on a real call.

## 4. Decisions waiting for the founder (grouped)
1. Wording/audio approval: every spoken line (live engine, 297), chatbot 78 copy ids, 18 WhatsApp templates (draft 6), the call-test message, voice-note copy, Script 7 final OK; "Way of talk" section empty in CALL_SCRIPTS_EDIT_HERE.
2. Confirm: "live in 5 days" = private pilot; pilot-only real calls; kill switch ends a call; no retry on test call; limits 3/day 6/week; local test user.
3. docs/CONSUMER_DECISIONS.md (32 questions), CHATBOT_GUARDRAILS (5), LIFE_STATE (6), PROACTIVE (G: 5, I.6: 4), consumer problems MUST/LATER/NEVER, bounded moves (A3.1), voicemail on/off, 112 in distress line, voice-note default.
4. Product: 3 lead promises, fee model (businesses pay per booking), first categories (suggest salon, clinic, AC/plumber), customer care and hold-fighting in the pilot or not, vendor verified programme, say "AI assistant" upfront or "virtual assistant" only on request.
5. Business/legal: business name + brand (Friday vs candidates; trademark unchecked), Meta number/templates/display name, domain, privacy + consent pages, grievance officer, lawyer read (LEGAL_MAP: 7 launch blockers), DLT, DPIA, vendor zero-retention/DPAs, Sarvam/Vobiz terms on AI disclosure, real card rules (10-15), Google Cloud project + consent screen.
6. Ops (founder-only): Vobiz top-up/upgrade + call queue OFF + caller ID, server env keys, rotate all keys pasted in chat, Supabase password + apply migrations, remove phone number/IP from public docs or make repo private, Apple Developer account (later).

## 5. Contradictions / stale statements to fix in the docs
- Recording: PRD Q4 + SECURITY say announce; founder decision (10-13/19) = never announce; DEPLOY/pilot say recordings off. -> follow founder; fix PRD/SECURITY.
- AI disclosure: ARCHITECTURE/WORKFLOWS/LAUNCH_CHECKLIST say always first; salon playbook = on request ("virtual assistant" in call; "AI assistant" in chat). Needs ONE rule.
- Calls to family/friends: PRD non-goal vs consumer design core.
- Retry timing: PRD +10/+30; WORKFLOWS +5 min/+1 h; quotes flow one retry at 10 min; CALLS_W1/founder 10-13 = +1 h, +3 h, max 3 (use this).
- Call window/caps: PRD 09:00-20:30, 6 min; CALLS_W1 09:00-19:00, 300 s; quotes flow 09:00-19:00; per-number caps differ.
- Name: BRAND_NAMES says avoid "Friday"; everything else uses it; founder said keep for now.
- Stack: BRIEF/TASKS/SECURITY name Anthropic + Twilio; reality = OpenAI gpt-5.4-mini backend, Sarvam live, Vobiz carrier. BRIEF PIN-by-keypad impossible on Vobiz stream -> PIN on WhatsApp.
- Category count 20 vs 22; beta size 5-10 (GO_LIVE) vs 10/30/50 vs 50-100 vs 30-50; go-live dates (8.8 vs 8.12 vs 5 days) -> latest = private pilot in 5 days.
- STATE_OF_FRIDAY (19 Oct) said business calls "VERIFIED"; WORKFLOWS/LAUNCH_CHECKLIST say nothing live; PLAYBOOKS says only salon shipped, others drafts. Treat as UNVERIFIED.
- DEPLOY_AWS/LIVE_TEST_WINDOWS say repo private and AWS; repo is PUBLIC and no AWS (D12).
- SECURITY/SECURITY_FIXES list 27 xfails / Twilio items; QA_REPORT says none open: stale.
- VISION promises free-form talk without trees; live engine uses fixed lines.
- Vobiz numbers differ across docs (+91 80 7158 2175 Sarvam-rented, +918065354620 trial with ~Rs 24, +91 80 6426 7861 current Friday number per HANDOFF).
- WHATSAPP_QUOTES_FLOW prints a real phone number/server URL in a public repo; a builder line "WhatsApp possible nahi" breaks a founder rule.
- Proactive cap: 2/week (10-12) replaced by 3/day or one morning digest (later).
- Unanswered: Hindi line "ek ticket ka rate bata do pehle mere ko".

## 6. Suggested critical path for the 5-day pilot
Pick up GO_LIVE_5_DAYS.md: (1) founder ops (Meta number + business name, Vobiz top-up, keys, server) (2) one audio-approval batch (opening, disclose, stop, voicemail, test message) (3) migrations + doctor PASS (4) `friday consumer call-test` to the founder's phone (5) chatbot with 5-10 named testers, calls only to allow-listed numbers (6) fix doc contradictions above.

---
# Earlier snapshot (19 Oct), kept for reference
# State of Friday (19 Oct 2026, after the four consumer workstreams)

Legend: BUILT+TESTED (offline, fakes) / WIRED (callable from WhatsApp) / VERIFIED (real world) / PARKED.
Full suite: 4678 passed. Nothing below has been exercised with a real recipient, real Google, or the live database.

## 1. Calls
- Business calls (VERIFIED earlier on a test phone, Ritu voice on Sarvam): 10 pending playbooks (salon, quote and slot, enquiry, home service visit, PG, cab, stock and price, table, hotel, banquet), 22 categories, WhatsApp quotes flow, retries (+1 h, +3 h, max 3).
- Consumer calls to anyone (BUILT+TESTED): family/friends, providers, customer care, officials, unknown people, groups, call-backs. Request understanding, contact book, brief, approval of the exact brief and opening line, safety gate, global do-not-call, caps and calling windows, group fan-out, retries, plain-language report, recording retention. Live engine with fixed "moves", 297 pending lines, intent detection, guards (no invented numbers, no private facts, no commitments outside the brief, truthful AI disclosure, hard stops), voicemail/IVR/hold, 37 simulated callee personas x 3 languages. WIRED: no (integration builder running).
## 2. Savings (BUILT+TESTED)
Card wallet by name, verified rules table (only example rows), calculator, "which card" answers with reason, bills (parse forwarded text, reminders, pay link only), monthly saved-Rs ledger, neutrality test (no revenue input).
## 3. Your day (BUILT+TESTED)
Life state, Hinglish capture of events and commitments, now-status and context summary, calendar import and clash check, follow-ups ("kaisa gaya?"), morning brief, quiet hours/caps/mute, "what do you remember / forget / export / delete everything".
## 4. Google (BUILT+TESTED against a fake Google)
Per-user OAuth with PKCE, encrypted tokens, Calendar read/write/clash, Gmail read-only narrow search (switch off), disconnect and delete.
## 5. Trust and control
Approval before calls and actions, code-level gates, do-not-call, DataPurger covers all new tables, secrets scrubbing, per-user data only, no payments by Friday.
## 6. Learning and tooling
Style tool, learning loop (label, evaluate, few-shot), simulation personas, problem register with the founder's decisions, competitor research.
## 7. PARKED
Ordering through platforms (browser connector with fake site and Zomato explore run stays in the repo, off by default), payments by Friday, devices, social accounts, Gmail broad access, voice-first phone app, call screening/divert.
## 8. Not done / needs the founder
Real card rules, approval of all wording and audio, Google Cloud project, Supabase password and applying migrations 0006-0009, business name and legal pages, WhatsApp number/templates, a server to run on, the list in docs/CONSUMER_DECISIONS.md.
