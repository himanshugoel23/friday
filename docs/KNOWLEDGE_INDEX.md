# KNOWLEDGE INDEX: the whole of Friday in one document

Built 2026-10-24 (chat B) from a full read of every document in this repo (84 files in `docs/`, plus `README.md`, `CLAUDE.md`,
`tests/e2e/README.md`, `deploy/*.md`, `.github/*`) at branch tip `c93166b`, using seven parallel readers. This is a **digest, not the
source**: when it disagrees with the code, the code wins; when it disagrees with `HANDOFF.md`, the newest dated entry wins.
Read `docs/HANDOFF.md` first (CLAUDE.md rule 1), then use this file to find the right detail document fast.
Contains no secrets (names of keys only). Phone numbers and IDs from the source docs are deliberately not repeated here.

---------------------------------------------------------------------------------------------------------------------------------
## 1. What Friday is, in one paragraph

Friday is a JARVIS/F.R.I.D.A.Y.-style personal assistant for Indian consumers, reached only through WhatsApp, voice calls (and DLT SMS
for links). Its core job: **it phones businesses for you** (salon, clinic, AC/plumber, packers, PG, restaurants...) in Hinglish, collects
quotes or availability, sends ONE comparison, and books only after you approve. Voice is female ("Ritu" on Sarvam). People can also call
Friday's number (the "front door"). Principles: acts rather than chats; outcome-based messaging (one acknowledgement, then silence until an
outcome or a question only the user can answer); safety enforced in code, not by the model (never pays, never takes OTP/PIN/card, never
books without approval/delegation); all processing on OUR servers (nothing depends on the user's phone); per-user data used only for that
user, one-step delete. Business model decided 2026-10-14: businesses pay per completed booking, the fee never affects ranking.

## 2. Scope: which "phase 1" governs (the documents disagree)

| Source | Phase 1 means |
|---|---|
| BRIEF / PRD (early) | vendor calling + customer-care/IVR + hotels + family check-ins + circle/places + front door + number pool + scale |
| VISION / USE_CASES (early) | narrower: promise 1 only, customer care = phase 2, Gmail/Calendar = phase 4 |
| HANDOFF 2026-10-12 | "phase 1 = vendor calling only" (WhatsApp request -> classify -> PM -> scout -> calls -> comparison) |
| FEATURES v2 / CONSUMER_* (10-19) | much wider launch set: calls to ANYONE, receptionist/voicemail, day memory, savings, Google Calendar/Gmail |
| **GO_LIVE_5_DAYS (10-22), newest** | **private pilot**: founder + 5-10 named testers, one WhatsApp number, real calls only to allow-listed numbers |

Newest governing definition = the 22 Oct private pilot (interpretation "live in 5 days = private pilot" still to be confirmed by the founder).
Founder also said 10-12: launch date is set by a QUALITY BAR, not the calendar (>=90% of test requests correct end to end, first reply < 10 s,
comparison < 10 min median, no wrong-booking incident, audio of all scripts approved, per-category kill switch).

## 3. Reality check: built vs verified (as of 2026-10-23/24)

* **Built (offline, with fakes/simulators), mostly default OFF:** front door; playbook engine + salon v6; 6 pending vendor archetypes; scouting
  (agents 5-12); classifier + project manager (agents 1-2); WhatsApp quotes flow; chatbot pilot layer (onboarding/consent/off-topic/wishlist);
  consumer calls W1/W2 (calls to anyone, bounded moves); savings engine W3; life state W4; integration W5 router; Google connector (fake Google);
  receptionist; human-like voice layer; semantic end-of-turn + Silero VAD + speculative understanding; voice notes + Devanagari input; media
  design only; private browser runtime + flows (fake sites); doctor; quality loop; CI files; Supabase schema.
* **Verified live:** essentially nothing. A handful of founder test calls on the old stack (reply gaps 0.6-0.8 s with Sarvam call-turn model on
  one test; 3.6 s earlier on OpenAI), Google Places live scout, synthetic Sarvam probes. No real salon call, real WhatsApp delivery, real
  Google OAuth, real Zomato page, receptionist forwarding, or Meta template approval has happened.
* **Not built:** guardrails module (`friday/guardrails`, designed), inbound-ID code (design only), adaptive persona engine, hold-fighting,
  reminder calls to others, media understanding, real savings rules (only EXAMPLE rows), proactive memory extractor/planner (agents 21-22),
  PM booking/buttons, WhatsApp number capture with read-back, busy-slot Yes/No flow, 30-minute reminder, Gmail/Calendar wiring into flows.
* Verified in the tree on 2026-10-26: 11 migrations (latest `0011_receptionist`), `friday/guardrails` absent, no inbound-ID code, salon v6 live with `ai_disclosure: on_request`, 264 test files.
* Tests: last full run 5925 passed / 13 failed, builder fixed 8; 5 known failures remain (1 sarvam-default LLM test, 2 connectors explore
  [no Chromium], 2 doctor [DB head], 1 stream-STT default). Counts quoted across docs (1102, 1209, 1328, 1758, 4846, 5925) are from
  different dates. Run `uv run pytest -q` and `uv run ruff check .` before trusting any number.
* Known issues found while building this index (2026-10-24): **`uv run friday --help` crashes** (`ValueError: unsupported format character 'w'`,
  bare `%` in the `scout-report` help string at `friday/cli.py:524`, needs `%%`); `.github/` exists (workflows/ci.yml, CODEOWNERS, PR template, scripts/secret_scan.sh) but CI has never run on GitHub and lint currently fails on a few
  ruff errors (deploy probe scripts, `core/config.py`); CODEOWNERS is a placeholder `@OWNER`; `CLAUDE.md` lacked the "reply in English" rule.

## 4. Architecture (docs/ARCHITECTURE.md is the source of truth for HOW)

**Principles:** core is channel-agnostic (only `friday/channels/` knows WhatsApp); every external service is a Protocol with a real and a
simulated implementation (`FRIDAY_MODE=simulator` default runs with no keys); calls are goal-driven via `CallBrief` (task types are data);
trust enforced in code (`friday.core.safety`, `CallBrief.can_commit`, voice runner guards); async + DI via `Container`; the brain is pure (no DB,
no sending); UTC stored, IST shown. `friday/core/` is frozen/additive-only; changes are logged in `docs/CORE_CHANGES.md`.

**Packages under `friday/` (32 directories on 2026-10-26; the EM audit counted 29 earlier; ~140k lines, 11 migrations 0001-0011, ~80 settings in `core/config.py`, 109 `FRIDAY_*` names across code):**
`core` (config, models, interfaces, events, clock, safety, crypto, scale) · `api` (FastAPI, webhooks, runtime, inbound, callbacks, google) ·
`channels` (WhatsApp Cloud, SMS-DLT, simulator, notifier) · `tasks` (engine, fan-out, retries, number pool, outbox) · `proactive` · `discovery`
(Places, geocoder, official numbers, hotels) · `db` (tables, repositories, queue, migrations) · `brain` (LLM, prompts, extraction, front-door
copy) · `voice` (telephony adapters, STT, TTS, runner, front door, VAD) · `playbooks` · `vendors` · `pm` · `scouting` · `quotes` · `calls` (W1) ·
`liveagent` (W2) · `savings` (W3) · `lifestate` (W4) · `integration` (W5) · `google` · `receptionist` · `chatbot` / `chatbot_media` · `connectors` ·
`mcp` · `human` · `lang_dev` · `latency` · `learning` · `quality` · `ops` (doctor) · `simworld`. Top-level: `cli.py`, `pause.py` (kill switch),
`pilot.py`. Dependency rule: `api -> tasks/proactive/channels/discovery -> core`; cross-package access via `container.get` and Protocols.
Known layering violations (EM audit): `receptionist` imports `voice`/`liveagent`; `quotes` imports `api`/`brain`; three orchestrators exist
(`pm`, `quotes/flow.py`, `tasks/engine.py`).

**Main flow:** WhatsApp webhook (signature-verified, idempotent) -> user lookup -> `interpret` -> NEW_TASK -> PLANNING (autonomy, abuse limit,
number verifier, business hours) -> `CallBrief` -> CALLING (runner: disclosure, policy, guard) -> PENDING_APPROVAL -> user taps buttons ->
CONFIRMATION_CALLBACK call with approved terms -> COMPLETED -> summary/reminders. Task states: CREATED, PLANNING, NEEDS_INFO,
AWAITING_APPROVAL, DISCOVERING, WAITING_CHILDREN, AWAITING_CHOICE, SCHEDULED, CALLING, AWAITING_USER, CONFIRMATION_CALLBACK, COMPLETED,
FAILED, CANCELLED. **Approval rule:** default is callback mode (never confirm on the first call); on-call confirm only with an explicit
`Delegation` (time window + price ceiling); a budget alone is NOT delegation.

**Scale:** roles `api|task|voice|proactive|batch` via `FRIDAY_ROLES`; Postgres `jobs` queue (SKIP LOCKED); locks/idempotency/rate limits.
**Current hard limit: one process per VM** (live-call state, media WebSocket, mid-call questions and chatbot session state are in memory; a
restart cuts calls). Load test (simulator): 1000 users, 200 concurrent calls, zero lost/duplicate work. ENG_SCALE_PLAN: Postgres queue enough to
~10,000 users; 5-15 simultaneous calls at 1,000 users; what breaks first: Vobiz concurrency (~100 users), single-process CPU (~1,000).

**Providers:** LLM = OpenAI gpt-5.4-mini today (Anthropic and Sarvam also wired); telephony = Vobiz via the "sarvam" adapter (Twilio/Exotel
code kept disabled); STT = Sarvam saaras:v4 REST (realtime stream OFF by default); TTS = Sarvam bulbul:v3 Ritu (ElevenLabs opt-in); WhatsApp
Cloud API; SMS MSG91/DLT (off); Google Places + Geocoding; Expedia (stub).
**Model routing (founder 2026-10-12):** lane 1 live calls = speed first, Sarvam end to end (`sarvam-105b-conversations`, ~0.3 s vs 2.2 s on
OpenAI; `FRIDAY_LLM_CALL_TURN_PROVIDER=sarvam`, falls back to the backend model); lane 2 backend = accuracy first (GPT or Claude chosen per job
by measured accuracy, then cost). ARCHITECTURE §5's older table (Anthropic Opus/Haiku/Sonnet) is stale.
**EM target (REPO_AND_MCP_EM, not implemented):** layers L0-L5, three services (`api`, `worker`, `voice`), an in-process ToolBus with approval
levels (L0 read, L1 reversible, L2 irreversible), import-linter, ADRs, HANDOFF capped at 150 lines. Refactor deferred until after the pilot.

## 5. The agent roster (docs/AGENT_ROSTER.md, 22 single-job agents; LLM agents get small closed tasks with JSON schemas, code does the rest)

Built: #1 intake classifier (`pm/classifier.py`, LLM + keyword baseline, 104 labelled examples, offline score optimistic), #2 slot extractor
(rules), #3 clarifier (inside PM), #5 query builder (lite), #6 place searcher, #7 eligibility filter, #8 review fetcher (max 5 reviews, memory
only), #9 review authenticity judge (rules + optional LLM), #10 service-evidence extractor (keyword stand-in), #11 fit scorer, #12 ranker
(Bayesian rating prior 4.2x50; weights 0.30/0.25/0.25/0.15/0.05), #16 voice caller (playbooks), #18 comparer, partly #17 result extractor,
#19 reporter. Designed only: #4 location resolver, #13 shortlist explainer, #14 call-task builder, #15 safety/consent gate (real gate exists in
`calls/gate.py`), #21 memory extractor, #22 proactive planner. **Project manager** (`pm/manager.py`): deterministic state machine, turn
interface `handle_turn(task_id, text, channel)` for `whatsapp_text|whatsapp_voice|call|sms`, quiet rule (one ack, then silence), max 2
clarification rounds, booking only with delegation, handoff buckets (confirm, reschedule/cancel, follow-up, complaint) stop with a note.
**Distance rule (hard):** per-category radius default and hard max (salon/gym/florist/PG 5/10 km, clinic/lab/vet 8/15, restaurant 5/12, home
services 10/20, movers/events/cab 20/40...); widening beyond default asks the user first; straight-line distance for now.
**Scope buckets/categories:** Wave 1 = 20 categories (founder: beta launches with ALL 20; PM plan suggests starting with salon, clinic,
AC/plumber), 10 request buckets, complaints out of beta; 22 categories in the vendors pack; no vendor DB (search Google Places live; NCR test:
every category hit the 100 cap, phone present 83-99%).

## 6. Calls and voice

**Telephony (Vobiz direct):** outbound `POST /Account/{id}/Call/` with `answer_url`; audio as bidirectional `<Stream>` mu-law 8 kHz;
**no inbound DTMF or stop events inside the stream** (so no PIN by voice; DTMF can be sent, received only via `<Gather>`); transfer is a
transfer not a 3-way call; recording and delete endpoints exist (unverified); callbacks must answer in 3 s. Account facts 2026-10-08: prepaid
trial, small balance, 3 concurrent calls, `call_queue` was ON (must be turned OFF), stream rate ~Rs 0.44/min. Adapter:
`friday/voice/telephony/sarvam.py` (open TODO markers: DTMF/record/transfer bodies, hangup causes, codec details, delete-recording).

**Playbooks (scripted calls; the LLM only classifies the vendor's reply into ~29 closed intents, it never writes Friday's words).** Data files
`friday/playbooks/data/<name>.yaml` + personas + baselines; validator rejects OTP/PIN/card words, Devanagari in lines, lines >240 chars, human
claims, booking claims outside the commit line, unreachable steps. Guards: `understand.ground` drops model-returned price/time/stylist not in the
vendor's words; a line may repeat once; duplicate speech within 1.5 s dropped. CLI `friday playbook list|validate|dry-run|preview|types|draft|promote`.
Live: **`salon_booking` v6** only. Pending (in `friday/playbooks/pending/`, NOT live until the founder hears audio; `promote` needs a
`<id>.approved` marker the builder never creates; verified in the tree 2026-10-26): banquet_booking, cab_booking, enquiry, home_service_visit, hotel_booking, pg_rental,
quote_and_slot, stock_and_price, table_booking (plus a pending copy of salon_booking), matching the script names in `SCRIPTS_SPEC.md`. The 6 archetype names in
`CALL_SCRIPTS_EDIT_HERE.md` (rental, table_or_venue...) are an older grouping.
Selection: a booking at a salon/parlour/barber/spa (or haircut/facial/waxing request) uses the playbook; otherwise an AI-driven call; a
confirmation call-back is never scripted.

**Salon v6 script (founder's design; wording authority = founder):** opening "Hello, kya meri baat <salon> se ho rahi hai?" then wait ->
"Main Friday baat kar rahi hoon, <user> sir ki virtual assistant... charges ke regarding call kiya hai" + price question ("Toh sir, ek baar bata
sakte hain inke kya charges rahenge?") -> `quote_only` close "Theek hai sir, main <user> sir ko bata deti hoon. Thank you." (default; outcome
QUOTE_COLLECTED) or `book` mode (needs delegation + exact time): stylist ask, slot ask, commit line, busy -> fallback day or nearest slots (only
OFFERED), `NO_SLOT`, may-not-book close. AI disclosure is **on request** (founder 2026-10-10): she says "virtual assistant", never volunteers
"AI", answers truthfully in her next reply to any form of the question ("Haan ji, main <user> sir ki personal AI assistant hoon"), never denies.
Founder rules for ALL scripts (10-13): natural fillers (Ji, Achha, Toh, actually), name check first then a one-line purpose hook, natural
Hinglish endings, everyday English words (nearest, slot, booking), "thank you" not "dhanyavad". Rejected wording: "slot milega", "kitna time
lagega", "arrive hone se pehle". Approved-as-text scripts 1-7c exist in `SCRIPTS_SPEC.md` (a "v7" with `{ack}` variation pool, WhatsApp number
read-back, negotiation pushes at ~90-95% of budget, retries +1 h/+3 h max 3, user pays advance never Friday) but are NOT the live text; the
single place the founder edits lines is `CALL_SCRIPTS_EDIT_HERE.md`. Names are spoken from Devanagari (override file, glossary salon->saloon,
Sarvam transliteration, Roman fallback), resolved at call setup.

**Voice settings (decided):** Sarvam bulbul:v3, speaker `ritu`, pace 0.9, temperature 0.9, 8 kHz, pronunciation dictionary on
(`friday tts-dict sync`). Env default for speaking rate is 1.0, so 0.9 must be set explicitly. Streaming TTS in the call path (default on):
first audio ~0.4-0.5 s vs 2-5 s REST. End-of-speech wait 900 ms (650 ms for short utterances). `FRIDAY_VOICE_PROFILE=internal-test` turns on
the audible human layer (backchannels, prosody, number reading, variants, mirror, mood, listener match, pauses, noise adapt: all OFF in
production/pilot); silent switches (intent classifier, speculative understanding, LLM-to-TTS stream, semantic EOT, human resume/metrics) are ON by
default; VAD backend silero with fallback to energy; stream STT OFF. Kill switch for backchannel leakage: `FRIDAY_HUMAN_BACKCHANNELS=false`.
**Latency facts** (see `LATENCY.md`, `VOICE_PROBE_RESULTS.md`): perceived pause = end-of-speech wait + "reply gap" (logged per turn as `reply gap`).
Sarvam realtime STT final p50 ~732 ms vs REST ~1.5 s; TTS first audio HTTP stream ~481 ms; LLM call turn ~0.3 s on Sarvam vs ~2.2 s on OpenAI;
semantic EOT cuts unfinished-utterance cuts 54.8% -> 14.2% (+~0.7 s on those); Silero VAD 92.7% vs 45.2% utterances OK in noise (synthetic).
Only a handful of real turns measured. Target: reply < 1 s, p95 < 1.5 s (`P95_BUDGET_MS`). **Cost:** ~Rs 1.3/min telephony+STT, TTS Rs 3 per 1,000
chars, Rs 0.12 per LLM turn; a 3-minute call ~Rs 7.5; a quote task (3 vendors + retry) ~Rs 30 (all estimates).

**Front door (inbound):** Vobiz number -> `answer_url` -> stream -> `InboundCallReceived` -> `CallbackService.on_inbound_call`; known user beats
business match; unknown caller gets voice onboarding only if allow-listed (pilot) or `FRIDAY_FRONTDOOR_OPEN_SIGNUP=true`; not-allowed gets one fixed
line + hang-up before any DB/AI cost. Conversational by default (`FRIDAY_FRONTDOOR_CONVERSATIONAL`): one structured model call per turn with a
closed action set; code fixes the order (disclosure clip first, exact consent question with deterministic yes/no, read-back + spoken yes before
`TaskEngine.submit`, delete/PIN/bot answers without the LLM). Pilot refuses to phone any number not on the allow-list. Limits: 180 s pilot /
300 s otherwise, 3/hour and 10/day per caller, 40/hour global, spend cap Rs 25 in pilot. Result call-backs at most twice, 08:00-21:00 IST,
in memory only. `friday listen` auto-creates/updates the Vobiz application `friday-front-door`, attaches the number, restores on exit
(`--restore` after a crash); tested only against a fake Vobiz account.

**Receptionist (RECEPTIONIST.md):** Friday answers only calls the user did not pick up; the CARRIER conditional-forwards (no-answer after N rings,
busy, unreachable; GSM codes `**61*`, `**67*`, `**62*` unverified on real SIMs) to ONE shared Vobiz number; the user is identified by the
**redirecting number**, whose Vobiz field name is UNVERIFIED (run `FRIDAY_RECEPTIONIST_PROBE=true` then `friday receptionist probe --show`; until
then forwarded calls take the generic path). Fixed lines only, 90 s / 12 turns max, no audio recorded, snippet kept 30 days, urgent -> WhatsApp
now with buttons, normal/spam -> morning digest. Off by default (`FRIDAY_RECEPTIONIST_ENABLED`). Inbound-ID designs (EM: one open outbound task per
vendor number per channel, reference code like "FR-4829"; PM: short code like "F-42", "Call me" button) differ and are design-only.

**Quality loop (QUALITY_LOOP.md):** no fine-tuning; transcripts kept only with spoken consent, redacted + field-encrypted, 30 days; `friday review
[show|label|rate|purge]`, labels (robotic, too_long, helpline_feel, slow...), `friday eval` (12 scripted callers on the fake model, baseline regression
gate). Fine-tuning is a later option from reviewed consented transcripts.

## 7. WhatsApp: quotes flow, chatbot pilot, persona, guardrails, templates

**Quotes flow (`friday/quotes/`, WHATSAPP_QUOTES_FLOW.md):** COLLECTING (one missing slot at a time) -> CONFIRMING (3 vendors, buttons "Haan, call karo"
/ "Badlo") -> QUEUED (outside 09:00-19:00 IST, kill switch, retry pending) -> CALLING (1 at a time default, max 3, one retry after 10 min) ->
AWAITING_BOOK (ONE comparison with Book buttons) -> BOOKING (delegation for that vendor/time, quoted price as ceiling) -> DONE. Only Gurgaon and
Bangalore served; 3 requests/user/day; 8 Places calls/request; DNC; allow-list. Mode `quote_only` unless the first message says book + exact time +
budget. Outcome-based: per-vendor/progress messages are OFF unless the user types `updates on`. Delivery: WhatsApp, then SMS summary if the send
fails or no receipt in 20 min, voice fallback only recorded (not wired). Test redirect `FRIDAY_VENDOR_CALL_REDIRECT_TO` dials a test number instead of
the vendor (real vendor name kept in the script). State in `quote_conversations`, restart-safe (`tick` every 30 s). All message copy (en/hinglish/hi)
is PENDING founder approval. Scouting is wired behind `FRIDAY_QUOTES_USE_SCOUTING` (default off).

**Chatbot pilot (`friday/chatbot/`, CHATBOT_PILOT/ARCHITECTURE):** built, OFF by default (`FRIDAY_CHATBOT_ONBOARDING`), wording PENDING. Onboarding
consent -> name -> language -> city -> first win; allow-list = `FRIDAY_PILOT_ALLOWED_NUMBERS` + `FRIDAY_CHATBOT_TESTERS` + `FRIDAY_ADMIN_PHONES`, others
waitlisted (hash only); commands menu/help/human/stop/`delete everything` then `DELETE`; contact card -> encrypted contact book; location pin -> Place;
off-topic -> redirect + wishlist. Messages to other people cannot come from the user's own number (options: Friday's number "on behalf of", `wa.me`
handoff, Gmail later). **Persona (CHATBOT_PERSONA v3, 10-23): NO fixed persona; adaptive per-user style dials** (language mix, formality, humour,
energy, length, emoji), mood beats profile; invariants never adapt (honest AI, never OTP/PIN/card, approval before calls/payments, privacy, correct
prices). Earlier "playful + emojis" (v2) superseded. **Guardrails (CHATBOT_GUARDRAILS, designed, not built):** abuse gate -> policy classifier -> router ->
output filter -> review queue; short answers to simple factual questions allowed (decided 10-23); medical/legal/financial/political/essay/homework
redirected + wishlist; `friday/guardrails/` + 300-message red-team set planned.
**Templates (WHATSAPP_TEMPLATES.md, generated from `friday/chatbot/templates.yaml`):** six drafts (morning brief, follow-up, bill reminder, call outcome,
re-engage hello, consent again) in en (Roman Hinglish) and hi, **none submitted to Meta**; older registry templates (`friday_task_update_v1`,
`friday_question_v1`, `friday_nudge_v1`, `friday_reengage_v1`, `friday_biz_request`, `friday_beneficiary_optin`...) live in `friday/core/templates.py`.
Meta business verification, display name, and approval are on the founder's critical path (the founder uses a WhatsApp provider; business name not final).

## 8. Consumer features and connectors

* **Calls to anyone (W1 `friday/calls/`, W2 `friday/liveagent/`):** brief + exact-opening-line approval, safety gate (allow-list, DNC, hours, quotas),
  bounded moves for free-form personal calls, 297 fixed pending lines, 37 personas x 3 languages simulated 111/111; `friday consumer call-test` places ONE
  real call to the founder's own phone (hard cap 150 s, limits 3/day 6/week). Switch `FRIDAY_CONSUMER_CALLS_ENABLED` (off).
* **Savings engine (W3):** card wallet by NAME only (never numbers), `best_card` pure function, integer paise, confidence HIGH/MEDIUM/LOW by rule age,
  ledger counts only user-confirmed "used"; repo ships EXAMPLE rows only (needs 10-15 rules verified by a named person); bills + reminders at 3 d/1 d/day-of.
* **Life state (W4):** per-user timeline, Hinglish capture, follow-ups ("Interview kaisa gaya?"), morning brief text; migration 0009.
* **Google (friday/google):** per-user OAuth, Calendar first (`calendar.events`), Gmail read-only behind `FRIDAY_GOOGLE_GMAIL_ENABLED` (metadata/snippet only,
  no send); Testing mode with named testers (refresh tokens ~7 days there); no Google Cloud project exists yet; Gmail launch needs verification + annual
  CASA assessment. No flow calls it yet.
* **Private browser (PRIVATE_BROWSER*.md, BROWSER_AGENT_PLAN, CONNECTORS):** Friday drives a private browser for food (Zomato) and movies (BookMyShow) with
  per-task isolation, default-deny egress, vault (AES-GCM per user+site), login by takeover/one-time page, **Friday never sees OTP/password/card and has
  no pay tool** (QR / `upi://pay` handoff), irreversible steps need a one-use Grant, page text untrusted, kill switches (`FRIDAY_CONNECTORS_KILL`,
  `PauseWatcher`). Built and tested on FAKE sites only, default OFF (`FRIDAY_BROWSER_ENABLED`). Founder decisions: browser IS in the pilot but real-site
  runs are founder-supervised; never automate IRCTC/Amazon; Swiggy via official MCP; social accounts NEVER; platform ordering/payments parked.
  Unwired: doctor section, central settings, `friday browser-sim`, `/live/*` mount, `PauseWatcher` in `serve`; open EM findings (kill_all not latched,
  repaired selectors not re-checked before click).
* **Parked/Never:** always-on listening, wake word ("Hello Friday"), desk mode, hardware, voice cloning (never), social-account integration (never),
  payments, MCP/app ordering (parked), Account Aggregator/BBPS (later), media understanding (later slice).

## 9. Launch plan, gates, legal, security, infra

**Pilot gates (GO_LIVE_5_DAYS):** doctor PASS, DB at head, WhatsApp reply works and a bad signature is rejected, templates approved for sends after 24 h,
disclosure line approved and heard, stop/opt-out/DNC work, calls only to allow-list, kill switch tried, consent screen + privacy page + grievance contact
live, delete-everything tested, no secrets in logs, cost per call known, balance alarm, founder has used it for a day. **Wave plan (PM_SCALE_PLAN):** 5-10
-> 100 (70% call success, 0 safety incidents, vendor opt-out <5%, cost/task <Rs 30, templates approved, lawyer read) -> 1,000 (retention 30%, success 85%)
-> 10,000. Slice order (BUILD_BOARD, one slice at a time to 100%): 0 foundation, 1 call someone, 2 receptionist, 3 hold-fighting + reminder calls, 4 voice
channels, 5 savings, 6 Google. Founder must provide: server install + doctor PASS, Meta account/app/number/display name, Vobiz upgrade + top-up + number
+ call queue OFF, audio approval of every pending line, top 8 of 26 `CONSUMER_DECISIONS`, privacy policy + Grievance Officer + business name,
a written pilot legal-risk position.
**Legal (LEGAL_MAP, 15 rows, all unverified, none lawyer-checked; 7 block launch):** TRAI/DLT, AI-voice call rules, caller ID/CLI series, recording consent,
DPDP for non-user call recipients, DND scrub + opt-out deadline, consumer-protection liability/terms. Also open: Sarvam/Vobiz terms on not volunteering
"AI"; Meta policy on AI assistants (OPS-10; SMS is off so no fallback); trademark of "Friday".
**Security (SECURITY / SECURITY_FIXES / PRODUCTION_CHECKLIST):** threat model STRIDE + AI threats; code items SECURITY-n all closed; open OPS items:
OPS-1 India hosting/KMS/secrets manager/backups/WAF, OPS-2 ZDR/DPA with each vendor (OpenAI too if it is the brain), OPS-3 pen test + live-call red-team,
OPS-4 Grievance Officer, OPS-5 DPIA, OPS-6 breach runbook/CERT-In, OPS-7 staff access, OPS-9 gitleaks/pip-audit in CI. Controls: webhook HMAC, per-call
tokens on voice URLs, idempotency, field encryption + separate keys (`FRIDAY_PIN_PEPPER`, `FRIDAY_INDEX_KEY`, `FRIDAY_FIELD_KEY`/KMS), kill switch
`friday pause`, `/admin` 404 without token, live mode refuses default secrets. Retention: recordings stored 30 days by founder decision but NEVER
announced on the call (earlier docs say announce; superseded) and "off" in the beta checklist; transcripts 30 days (checklist says up to 90, undecided);
messages 12 months. **The repo is PUBLIC (since 2026-10-10): never commit keys/tokens/passwords; names only.**
**Infra:** pilot server = DigitalOcean droplet, Bangalore, Ubuntu 24.04, `/opt/friday`, systemd `friday` running `friday listen`, HTTPS via Caddy on an
`sslip.io` host, installer `deploy/small-server.sh`, secrets typed hidden into `/opt/friday/.env`; test call `deploy/call-me.sh`; update with
`git pull --ff-only` + `systemctl restart friday`. Optional Supabase (Singapore free project, schema applied, RLS on with no policies; migrate to Mumbai/Pro
before real users). AWS is a dead end for this founder (managed sandbox accounts with SCP denying Lightsail); the Docker/compose/AWS docs
(`DEPLOY_AWS.md`, `deploy/aws/*`) are valid only as an ops reference. A Docker image was built and verified in a sandbox earlier; the compose stack and
`smoke_test.sh` never ran. Free trial path: Codespaces + Cloudflare tunnel (`TRIAL_CODESPACES.md`). The sandbox cannot SSH to the droplet; the founder
uses the DigitalOcean web console (use `tmux new -As friday`).

## 10. Founder decision register (dated, newest wins; wording authority = the founder)

2026-10-07/08 channels voice+WhatsApp, SMS off; approval rule; female voice; Sarvam-only telephony. · 10-10 AI disclosure on request for salon; repo PUBLIC; Ritu +
temp 0.9 + pace 0.9; streaming TTS GO; public beta in ~6 days (later superseded); keep chat replies short, heavy work to builders. · 10-11/12 brand research;
**keep the name "Friday"**; voice final. · 10-12 WhatsApp-first quotes slice; onboarding places form (self/parents); connected apps NOT in beta; ~6 call
archetypes x category packs; no vendor DB; many small single-job agents; best AND near with hard distance limits; PM agent; classifier channel-agnostic;
outcome-based messaging; phase 1 = vendor calling only; beta launches with ALL 20 categories; all 8 wow items + proactive wanted, launch by quality bar;
proactive = WhatsApp and calls, NOT marketing, only from the user's own conversations (cap 3/day or one digest); model routing (Sarvam live lane, GPT/Claude
backend); no hallucination, no repeating. · 10-13 script review one use case at a time (scripts 1-7c approved as text, none promoted); record every call but
never announce; WhatsApp number capture with read-back; retries +1 h/+3 h max 3; "virtual assistant" only when asked; "just start building everything" with
a human gate. · 10-14 businesses pay per completed booking; neutral unbiased assistant; savings engine; users authorize their own Gmail; no sales-pitch
positioning. · 10-16/17 JARVIS feel; iPhone-first; divert incoming calls via receptionist; browser agent shape; no hardware now. · 10-19 build consumer calling
agent + savings + day memory; Gmail+Calendar core; social accounts never; ONE shared inbound number; voicemail only via conditional forwarding; one slice at a
time. · 10-21 always-on/wake word parked; no voice cloning; media understanding wanted later. · 10-22 "live in 5 days" = private pilot; receptionist forwards
only on no-answer/busy/unreachable; human-like voice improvements ON in internal-test first; PILOT FIRST; private browser IN the pilot (supervised); do not
refactor before the pilot except CI + secret scan. · 10-23 persona: NO fixed persona, adaptive; reply to the founder in English.

## 11. Standing rules (obey always)

1. **Hear before change:** audio sample to the founder (and approval) before ANY change to spoken lines, voices, pace or pronunciation; new lines stay PENDING.
2. **Update `docs/HANDOFF.md` first** at the start of every task; commit and push.
3. **Public repo:** never commit keys/tokens/passwords/`.env`/`var/`; never read or print `.env`; names of keys only; keys pasted in chat are exposed, rotate.
4. **No real calls** except to the allow-listed founder number and only with approval; pilot refuses other numbers.
5. Reply to the founder **in English**; the founder writes Hindi/Hinglish/English; do not assume pronouns.
6. One session per branch; fetch and read the newest HANDOFF before starting; never `git stash` in a shared folder; builders add only their own files,
   `git pull --rebase --autostash`; run the FULL suite before push and chain commit/push on the pytest exit code.
7. Keep AI cost low; all new user-facing text is PENDING_FOUNDER_APPROVAL; per-category and per-feature kill switches default OFF.

## 12. Contradictions and stale items (which wins)

1. Scope of phase 1: see section 2; newest = 22 Oct pilot.
2. LLM: BRIEF/ARCHITECTURE say Anthropic (Opus/Haiku/Sonnet); BETA_PLAN D9 says Anthropic, D16 and later say OpenAI gpt-5.4-mini; routing policy 10-12 says
   Sarvam for live turns. **Reality: OpenAI backend + Sarvam; re-decide for beta; DPA needed with whichever vendor.**
3. AI disclosure: BRIEF/PRD/ARCHITECTURE "AI first" vs salon "virtual assistant, AI on request" (10-10) vs front door/other flows still disclose first.
   Needs ONE written rule and a check of Sarvam/Vobiz terms.
4. Recording: announce (PRD/SECURITY) vs never announce (founder 10-13/19) vs off in the beta checklist.
5. Retries: PRD +10/+30 min vs founder +1 h/+3 h max 3. Call windows: 09:00-20:30 (PRD) vs 09:00-19:00 (businesses) and 08:00-21:30 (family) vs 08:00-21:00 (call-backs).
6. Proactive cap: 2/week (older) vs 3/day or one digest (10-12 decision); quiet hours 22-08 vs 21-09.
7. PIN: 4-digit PIN for onboarding/delete (older) vs no PIN, delete by typing DELETE (chatbot pilot; open decision 25). Keypad PIN by voice is impossible on Vobiz.
8. Latency docs: LATENCY.md 21-Oct sections say speculative/streamed/classifier/EOT default OFF and VAD energy; HUMAN_VOICE (10-23) says ON with silero. Check
   `friday voice switches` and `friday doctor`. STT path: realtime vs REST is described inconsistently (stream STT flag is OFF).
9. Salon script: v6 is live; SCRIPTS_SPEC "v7" wording differs and is not live. Pending script file names match SCRIPTS_SPEC (9 files + pending salon), so CALL_SCRIPTS_EDIT_HERE's 6-archetype list is the stale one; category count 20 vs 22.
10. Voice/pace: Ritu decided; some live tests used Zara (ElevenLabs); pace 0.9 in docs vs env default 1.0.
11. Stale docs: PRD/BRIEF/TASKS/SECURITY (Twilio+Anthropic), DEPLOY_AWS, PRODUCTION_CHECKLIST (AWS+Docker), BETA_PLAN (3-day plan, D12/D13), BETA_LAUNCH_PLAN (public salon-only beta),
    OPEN_QUESTIONS.md (is a design doc for off-topic answers, not a question list), QA_REPORT numbers, USE_CASES status labels, SECURITY_FIXES "open" tags.
12. Repo visibility: some runbooks say private; it is public. The founder's phone number and server address appear in public docs (consider redacting).
13. Receptionist/quotes layering violations; two onboarding flows coexist (invite-code and chatbot pilot); three orchestrators.
14. Browser docs say `flow.py`/`tests/connectors_sites` "not landed": both now exist.
15. Revenue "businesses pay per booking" vs "no commission" positioning: reconciled by the guardrail that the fee never reaches ranking.

## 13. Open questions and founder to-dos (consolidated)

* Confirm "live in 5 days" = private pilot; answer the top 8 of 26 `CONSUMER_DECISIONS`; PM plan's 10 ranked decisions; `CONSUMER_PROBLEMS` marks.
* Approve by AUDIO: 6 pending archetype scripts + glue lines, 297 liveagent lines, receptionist lines, human-voice lines, chat copy (78 ids), 18 template
  bodies, call-test message, quotes-flow messages, browser flow lines, Google consent copy; fill the blank "Way of talk" in `CALL_SCRIPTS_EDIT_HERE.md`.
* Give/confirm: WhatsApp Business number and provider compatibility, business name (Meta display name), which Vobiz number is live, privacy policy +
  Grievance Officer + terms URLs, a pilot legal-risk position or lawyer read of LEGAL_MAP.
* Ops: top up Vobiz and Sarvam credits; Vobiz call queue OFF; rotate every key ever pasted in chat (Google, Sarvam, OpenAI, Anthropic, ElevenLabs, Vobiz); delete
  the leftover GitHub deploy key/token; set spend limits; run the receptionist forwarding probe per carrier; create the Google Cloud project; set the database URL
  for Supabase; decide recording/retention; vendor DPAs (ZDR).
* Product: hero use cases (top 2-3 wow items); fee model for businesses; which categories go live first; booking/reschedule/cancel only with delegation?; PIN vs
  DELETE; reference-code style for inbound ID; whether customer care is in the pilot; "Friday" trademark; which "Instinct" is the competitor.
* Engineering: fix `friday --help` crash; clear ruff errors so CI passes; replace CODEOWNERS placeholder; wire the browser pieces; wire scouting into quotes
  (ask before beyond-default radius); finish guardrails; build inbound-ID; re-run the full suite and reconcile the 5 known failures; rename/clarify docs.

## 14. Document map (all 84 docs; C = current, S = stale/superseded in parts, D = design only)

**Start here:** HANDOFF (C, living context, 984+ lines, newest summary in section 8 at the end) · STATE_OF_FRIDAY (C, reality check 10-22) · FEATURES (C, launch
set v2) · GO_LIVE_5_DAYS (C, pilot definition) · BUILD_BOARD (C, slices) · this file.
**Product/strategy:** BRIEF (S, founder addenda) · PRD (S) · VISION (S) · USE_CASES (S) · DIFFERENTIATORS (C) · COMPETITORS (C, append-only research log) ·
JARVIS_FEEL (C) · LIFE_STATE (C) · SAVINGS_ENGINE (C) · BRAND_NAMES (C, paused) · CONSUMER_PROBLEMS / CONSUMER_BETA_DESIGN / CONSUMER_DECISIONS / CONSUMER_INTEGRATION /
CONSUMER_CALL_TEST (C) · OPEN_QUESTIONS (C, off-topic answerer design) · ZOMATO_EXPLORE (parked) · BETA_SCOPE_PROPOSAL (proposal) · LEARNING_AND_BUILD_PLAN (D).
**Plans/launch/ops:** BETA_PLAN (S) · BETA_LAUNCH_PLAN (S) · LAUNCH_CHECKLIST (mostly C) · PRODUCTION_CHECKLIST (gates C, AWS parts S) · PM_SCALE_PLAN / ENG_SCALE_PLAN (C,
proposals) · SLICE0_RUNBOOK (C) · TASKS (S) · QA_REPORT (S numbers) · LEGAL_MAP (C) · SECURITY / SECURITY_FIXES (C stance, S details) · DEPLOY_AWS (S route) · DOCTOR (C) ·
TRIAL_CODESPACES (C, trial) · LIVE_TEST_ISSUES / LIVE_TEST_WINDOWS (C runbooks) · SARVAM_QUESTIONS (C history) · LATENCY (partly S) · NCR_VENDOR_COUNTS (C data).
**Architecture/agents:** ARCHITECTURE (C, §5 model table S) · AGENT_ROSTER · PROJECT_MANAGER · SCOPE_BUCKETS · SCOUTING (C) · CONNECTORS · GOOGLE_CONNECTOR · CORE_CHANGES
(append-only log) · REPO_AND_MCP_EM (D) · WORKFLOWS (C, simulator-tested journeys) · MEDIA_UNDERSTANDING (D) · PROACTIVE_AND_INBOUND_DESIGN (D) · INBOUND_ID_EM / INBOUND_ID_PM (D) ·
RECEPTIONIST (C, built offline).
**Speech (BUILT, 10-26):** SPEECH_UNDERSTANDING (B offline; small LLM between STT and the other LLMs, `friday/speech`, live eval still to run on the server).
**Chatbot:** CHATBOT_ARCHITECTURE · CHATBOT_PERSONA (v3 C) · CHATBOT_GUARDRAILS (D) · CHATBOT_PILOT (C, built) · WHATSAPP_QUOTES_FLOW (C) · WHATSAPP_TEMPLATES (draft).
**Voice/calls:** FRONT_DOOR (C) · PLAYBOOKS (C) · playbooks/salon_booking.md (C) · CALL_SCRIPTS_EDIT_HERE (C, founder edit point) · SCRIPTS_SPEC (approved text, not live) · CALLS_W1 ·
LIVE_AGENT (W2) · HUMAN_VOICE (C) · HUMANIZING_CALLS · VOICE_AGENT_COVERAGE · VOICE_NEXT_STEPS · VOICE_NOTES_AND_DEVANAGARI · VOICE_PROBE_RESULTS · QUALITY_LOOP (C).
**Browser:** PRIVATE_BROWSER (C single doc) · PRIVATE_BROWSER_EM (D) · PRIVATE_BROWSER_FLOWS · PRIVATE_BROWSER_RUNTIME · BROWSER_AGENT_PLAN (C origin).
**Elsewhere:** `README.md` (docs map; does not mention browser or newer docs) · `CLAUDE.md` (rules) · `tests/e2e/README.md` · `deploy/restore.md`, `deploy/supabase/README.md` ·
`.github/` (ci.yml: secret scan, ruff, fast/nightly tests, audit; CODEOWNERS placeholder; PR template) · `.claude/agents/product-manager.md` (competitor-research subagent).

## 15. Git and branch notes

* Working branch: `claude/friday-phase-1` (tip at the time of writing `c93166b`; 458 commits since 2026-10-10, many are automatic "WIP: builders in progress" snapshot commits).
* Chat B's 12 commits from 2026-10-10 (reply-speed fixes `a435f2a`, HANDOFF restructure, audio-preview tool, key registry, v6 spec edits) are NOT on the main line; they are
  preserved on `origin/backup/other-session-2026-10-10`. A local-only branch `backup/vendor-wip-2026-10-22` was mentioned in HANDOFF (not pushed).
* Never rewrite history; add new commits; fetch before push.
