# HANDOFF: read this first (living context for any new chat or agent)

Founder instruction (verbatim intent): keep everything we discuss and decide in the repository, so a new chat can
read it and continue without losing context. **At the START of every task, update this file first** (what was just
asked, any decision, any mistake or lesson), commit and push it, **then** do the task. Never put secrets in it.

Last updated: 2026-10-12 (read section 8 "START HERE" at the END of this file first: it is the newest summary).

---

## 1. What we are building
**Friday**: a JARVIS/F.R.I.D.A.Y.-style, proactive AI personal assistant for Indian consumers. Channels are WhatsApp,
voice calls and SMS only (no app, no web). The core product: Friday makes real phone calls to businesses for the
user (bookings, price quotes, discovery, IVR customer-care, hotels, parents' wellbeing check-ins), AND people can
call Friday's number and talk to her (inbound "front door"). Voice: female, calm, Hinglish. Docs: `docs/BRIEF.md`
(founder decisions, source of truth), `PRD.md`, `VISION.md`, `ARCHITECTURE.md`, `SECURITY.md`.

## 2. Standing rules from the founder (obey always)
1. **Hear before change.** Before ANY code change to spoken lines, voices, pace or pronunciation, generate audio
   (`friday say`, or the Sarvam TTS API from the sandbox) and send it to the founder with `SendUserFile`; change the
   code only after they approve the sound. (Said on 2026-10-10.)
2. **Update this file first** at the start of each task (above).
3. **The repository is PUBLIC (founder made it public on 2026-10-10) and must NEVER contain keys, tokens, passwords, private keys or .env content.** Secrets live only in the git-ignored `.env` / typed on the server. Names of keys may be mentioned, never values. Before any commit, make sure no secret is staged. (Phone numbers and the server IP already appear in docs; avoid adding more personal data.)
3b. Never read or print `.env`; keys live only in the git-ignored `.env` (sandbox) or typed on the server; never in
   chat or git. Never commit `.env` or `var/`. Keys pasted in chat earlier must be rotated after testing.
4. No real calls except to the allow-listed founder number (+918607549916) and only with the founder's approval.
5. Founder speaks Hindi/Hinglish/English mixed (often dictating); the founder's own wording of the script is the
   authority. Do not assume pronouns for people.
6. Keep AI cost low; keep the user experience good.
7. Show scripts and results plainly; the founder is non-technical about servers/AWS.

## 2b. Architecture principle (founder, 2026-10-12; applies to everything we build)
**All processing happens on OUR backend servers. Nothing depends on the user's phone being online, awake or running anything.**
No app, no on-phone processing, no background work on the user's device, no using the user's internet/data for our work.
After the user sends a request (WhatsApp text, call, SMS) the server finishes the whole job by itself (search, vendor calls,
follow-ups) even if the phone is switched off or idle, and delivers the result later through channels the network queues:
WhatsApp (queued until the phone is online), SMS and voice call as fallbacks. This is also the base for the future safety product
(check-ins, alerts, calls to the user and their contacts from the server). Honest limits: we cannot read the phone's GPS or location
without the user sharing it; a switched-off phone cannot receive anything until it is back on.

## 3. Product decisions made (see BRIEF.md for the older ones)
- Voice agent speaks **Hinglish only** (Roman script; Indian names/business names are written in **Devanagari**
  inside the text for better pronunciation).
- **Approval rule**: Friday books only if the owner (user) gave an explicit instruction to book (delegation, within
  limits); a budget alone is not delegation; otherwise she only collects a quote and reports back.
- **AI disclosure (changed on 2026-10-10 by the founder)**: she introduces herself as "Himanshu sir ki *virtual
  assistant*", does not volunteer "AI", but if the business asks in ANY form (AI/robot/insaan/real person...) she
  answers truthfully next reply: "Haan ji, main <user> sir ki personal AI assistant hoon." She never denies being an
  AI. (Founder should check Sarvam/Vobiz terms; other flows still disclose up front.)
- **Salon call script** (first playbook), founder's design:
  1. "Hello, kya meri baat <salon name> se ho rahi hai?" then WAIT for "haan ji".
  2. "Main Friday baat kar rahi hoon, <user> sir ki virtual assistant. <user> sir ko <services> karwana hai, toh
     unki booking ke regarding call kiya hai."
  3. Price FIRST: "Toh sir, ek baar bata sakte hain inke kya charges rahenge?" (no duration question, no
     read-back, no advance/cancellation question unless the salon raises it, no negotiation unless the owner says).
  4. BOOK mode: "Kya <date/time> ka slot mil sakta hai?" If no: "Achha, nahi ho sakta. Toh kya kal ka slot
     available rahega?" then close: "Theek hai sir, phir kal ka 5 baje ka slot book kar lete hain. <user> sir aane
     se pehle aapko ek baar call kar lenge. Thank you." (If today is free: "...aaj shaam 5 baje ka slot book kar
     lijiye...").
  5. QUOTE-ONLY mode (owner only asked for a price): no slot question; after the price: "Theek hai sir, main <user>
     sir ko bata deti hoon. Thank you."
  - Business name, user name and services are VARIABLES (services joined like "haircut aur beard trim").
  - Wording rejected by the founder: "slot milega" (not how people talk), "kitna time lagega", "arrive hone se
    pehle" (use "aane se pehle"), long openings, repeating things at the close.
- **Pronunciation**: "salon" is spoken as **saloon** (founder picked by ear). Names are converted to Devanagari with
  Sarvam's transliteration API, cached, with an overrides file and a generic-business-word glossary; a
  speak-then-listen check flags names needing review. Sarvam's pronunciation dictionary (bulbul:v3, `dict_id`) is
  wired in (`friday tts-dict sync`, `friday/voice/tts/pronunciations.json`).
- **Voice/speed (DECIDED 2026-10-10)**: Sarvam bulbul:v3 speaker `ritu`, pace 0.9. The founder compared v4-flash
  Hinglish voices (Ishita, Shalini, Simran): they pause at random places; Ritu pauses sensibly in conversation, so
  **Ritu stays**. Speed is fine. Tone (DECIDED 2026-10-10): the founder compared 4 files (baseline temp 0.6, phrase pauses, temp 0.75, temp 0.9) and picked #4 = **temperature 0.9** (assumed from 'Voice 4 sounds better than rest'; the founder's message was cut off, confirm if unsure). Phrase pauses were not chosen.
- **Latency facts (measured 2026-10-10, real credits)**: Sarvam TTS REST for a ~150-char two-sentence line takes
  3.7-5.7 s; the streaming endpoint (`POST /text-to-speech/stream`, `output_audio_codec: wav`, 8 kHz) gives first
  audio in about 1.1 s. v4-flash is no faster than v3. Do NOT trust latency numbers taken while the API returns 402
  (errors return fast). Streaming TTS in the call path: founder said GO on 2026-10-10 ("build around Ritu"); DONE (see section 7 and docs/LATENCY.md). STT in use:
  Sarvam saaras:v4 REST per utterance (streaming STT not used).
- **Cost of a 1-minute call (Sarvam list prices)**: TTS Rs 3 per 1,000 chars (about Rs 1.4-1.8 per salon call),
  STT Rs 30/hour (about Rs 0.5/min), Vobiz about Rs 0.38/min, GPT near zero for scripted calls: about Rs 2.5-3 per
  minute. Sarvam credits ran out once during sampling (402): keep the account topped up.
- Scale plan: one playbook per business type (8 types drafted offline: clinic, restaurant, car service, home
  services, hotel, gym, dentist, pharmacy); `friday playbook draft/promote`; dry-run simulation before any real
  call; quality loop stores consented, redacted, encrypted transcripts for later review and fine-tuning.

## 4. Where things are (code map)
- `friday/` Python 3.13/uv, FastAPI, SQLAlchemy. LLM: GPT (OpenAI) is the brain for now (`FRIDAY_LLM_PROVIDER=openai`,
  gpt-5.4-mini; call turns with no reasoning because `minimal` is rejected by that model).
- Voice: Vobiz telephony (`friday/voice/telephony/sarvam.py` = Vobiz adapter), Sarvam STT/TTS, front door
  (`friday/voice/frontdoor.py`, `friday/brain/frontdoor.py`), barge-in + early STT + sentence-by-sentence TTS.
- Playbooks: `friday/playbooks/` (data/salon_booking.yaml, engine, validator, dry-run simulator, authoring agent).
  Docs: `docs/PLAYBOOKS.md`, `docs/playbooks/salon_booking.md`. Quality loop: `friday/quality/`, `docs/QUALITY_LOOP.md`.
- Useful commands: `uv run friday playbook validate|dry-run|draft|promote|types`, `friday say "text" --pace 0.9
  --out f.wav`, `friday tts-dict show|sync`, `friday eval`, `friday review`, `friday livecall --playbook
  salon_booking ...`, `friday listen` (front door), `friday doctor`.
- Tests: `uv run pytest -q` (about 1750+ pass), `uv run ruff check .`.

## 5. Infrastructure (no secrets here)
- Server: DigitalOcean droplet, Bangalore, Ubuntu 24.04, 1 GB, IP **64.227.183.183**, HTTPS at
  `https://64-227-183-183.sslip.io`, code in `/opt/friday`, systemd service `friday` (runs `friday listen`),
  installer `deploy/small-server.sh`, one-command salon test call `deploy/call-me.sh`.
- Update the server: `git -C /opt/friday pull --ff-only` then `systemctl restart friday` (restart relinks the
  number in ~1 min). Test call: `bash /opt/friday/deploy/call-me.sh ...` (stops the service, calls, restarts it).
- Numbers: Friday's Vobiz number **+91 80 6426 7861** (inbound + outbound). Allow-listed test number
  +918607549916 (founder). Pilot profile: only allow-listed numbers; real businesses are blocked until the founder
  approves a specific number.
- The AI sandbox cannot SSH to the server; the founder runs commands in the DigitalOcean Web Console (it
  disconnects on tab switch; use `tmux new -As friday`, or the Termius app).
- Open items: Sarvam credits must stay topped up (a 402 "No credits" crashed a call once); ask Vobiz to turn
  **call queue OFF**; rotate all keys that were pasted in chat; decide whether the GitHub repo becomes private;
  check Sarvam/Vobiz terms on AI disclosure; domain/WhatsApp Business/legal pages for beta.

## 6. Lessons and mistakes (so we do not repeat them)
- Do not guess call problems: ask for `journalctl -u friday --since "10 min ago" --no-pager | tail -40`.
- Third-party apt repos can break (Caddy repo returned 402): use Ubuntu's own package.
- `reasoning_effort: minimal` is rejected by gpt-5.4-mini; valid: none/low/medium/high.
- When making audio samples, never put stage directions in the spoken text (it gets spoken).
- Keep agents on disjoint files; do not commit another agent's half-finished work; run the FULL suite before push.
- Sarvam docs are readable with `curl https://docs.sarvam.ai/<path>.md` from the sandbox (WebFetch cannot resolve it).

## 7. Current state and next steps (update every task)
- DONE 2026-10-10: founder picked "voice 4" = Ritu, temperature 0.9 (pace 0.9, no extra pauses). `Settings.sarvam_tts_temperature` (FRIDAY_SARVAM_TTS_TEMPERATURE, 0.01-1.0, default 0.9) is sent in REST and streaming requests and is part of the TTS cache key (old cached audio is not replayed).
- DONE 2026-10-10: streaming TTS in the call path. `SarvamTTS.synthesize_stream` (`/text-to-speech/stream`, WAV parsed incrementally), `SarvamCallLeg` streams uncached sentences to Vobiz as chunks arrive, fills the TTS cache after a complete line, falls back to REST on failure, barge-in cancels the request. Switch: `FRIDAY_SARVAM_TTS_STREAMING` (default true). Measured with `deploy/tts_stream_probe.py`: REST 2.1-3.3 s, stream first audio 0.4-0.5 s (total 1.8-2.0 s). Details: `docs/LATENCY.md`. Untested on a live call: run the founder test call and read the `tts stream first-audio` log lines.
- DONE and pushed: front door (conversational), quality loop, playbook engine + salon v0.2, script author
  (offline), TTS pronunciation dictionary support, faster turns, droplet deployed and answering calls, HANDOFF.md +
  CLAUDE.md.
- DONE (v6, 2026-10-10, committed and pushed together): salon playbook v6 = price first, `quote_only` (default; outcome
  `QUOTE_COLLECTED`) and `book` modes (booking only with a delegation + `check_commit`; `--fallback-when` second time via
  `Delegation.slot_windows`), AI disclosure ON REQUEST (`ai_disclosure: on_request`: validator + `asks_if_ai` engine override +
  forced AI line + dry-run check; recorded in docs/CORE_CHANGES.md and docs/PLAYBOOKS.md; founder to check Sarvam/Vobiz terms),
  names as variables (`friday/voice/names.py`: Sarvam transliteration + disk cache `var/names/cache.json` + overrides file
  `friday/voice/name_overrides.json` + glossary, salon -> saloon, Roman fallback), services list, `friday tts-check`
  (speak-then-listen name QA), `friday playbook preview` (the real script into one wav), `deploy/call-me.sh` new arguments,
  47 new personas in the dry-run baseline. Docs: docs/PLAYBOOKS.md, docs/playbooks/salon_booking.md. `tests/e2e` now runs with
  playbooks off (they test the generic approval flows). NOT tested live: the real transliteration API call from this code, the
  real TTS/STT in `tts-check` and `preview`, a live call with the new script.
- NEXT after v6 lands: (1) send the founder the preview audio from the real code (hear-before-change); (2) voice is decided (Ritu); (3) update server and run the test call to the founder's phone (`call-me.sh`); (4) first real salon only
  with explicit approval; (5) clinic/restaurant playbooks via `friday playbook draft --live`; (6) WhatsApp channel.
- **2026-10-10 founder ask: PUBLIC BETA in ~6 days** (Gurgaon + Bangalore, calling businesses, landing page, WhatsApp Business (applied), Google Places for numbers, Supabase for data, measure users + business pickup rate). Plan in `docs/BETA_LAUNCH_PLAN.md`. Founder also asked to keep the context window small: keep chat replies short, push heavy work to builder agents, avoid long outputs.

- 2026-10-11 founder ask: brand-name research (needs .com and .in free, buyable on GoDaddy, tech-savvy generation). Results in docs/BRAND_NAMES.md.
- 2026-10-11 brand research done: shortlist in `docs/BRAND_NAMES.md` (top: Batiyaan, Oyeping, Haanio). Avoid Pucho (competitor Puch AI). Founder to choose; then buy .com + .in at GoDaddy and check IP India trademark search.
- 2026-10-11 round 2 names (agent-character first names: Zoya, Misha, Kiara, Nyra, Aarya) in docs/BRAND_NAMES.md; founder to pick.
- 2026-10-11 round 3: foreign agent names (Ziva, Sloane, Dani...) in docs/BRAND_NAMES.md; name audio samples sent; founder to pick.
- 2026-10-11 round 4 names (Thursday, July, Rei, Ziva, Sloane; avoid IP characters) in docs/BRAND_NAMES.md; audio samples of names sent; founder to pick.
- 2026-10-11 round 5 creative names (Tell Tilly, Dial Dixie, Ping Pippa, Ring Roxie...) in docs/BRAND_NAMES.md; audio sent.
- 2026-10-11 round 6 day/month names (Avril, Abril, Lunes, July, Thursday, October) in docs/BRAND_NAMES.md; audio sent.
- 2026-10-11 round 7 creative day/month names (Mercuri, Monami, Octavia, Dessa, Jovia, Sundae) in docs/BRAND_NAMES.md; audio sent.
- 2026-10-12 founder decisions: VOICE FINAL (Ritu, pace 0.9, temp 0.9); KEEP the name "Friday" for now (brand/agent-name search paused; research in docs/BRAND_NAMES.md). NEXT focus: inbound customer calls (user calls Friday and gives instructions, incl. random requests); proactive calls later. Plan: scope router (closed intents) + fixed lines + short chit-chat + wishlist capture.
- 2026-10-12 founder: START WITH WHATSAPP MESSAGING (not inbound voice): user texts "book a parlour (for self/other), give me quotes" -> Friday asks missing info (location, when, for whom) -> Google Places nearby shortlist -> user approves -> Friday calls vendors (salon playbook, quote-only) -> sends comparison + book buttons. Google Places key and WhatsApp (Meta) credentials go ONLY into the server .env (never chat/repo). Builder started; spec in docs/WHATSAPP_QUOTES_FLOW.md.
- 2026-10-12 founder ask (builder task): build the WhatsApp-first vendor QUOTES slice end to end (text in Hinglish/English/Hindi -> missing-info questions -> Google Places shortlist of 3 -> approve buttons -> sequential salon-playbook calls in quote_only -> one comparison message with Book buttons -> booking call). Decisions: test redirect mode `FRIDAY_VENDOR_CALL_REDIRECT_TO` (empty default) dials a test number instead of the vendor while keeping the real vendor name in the script; allow-list rule stays (real vendor numbers refused while it is active); all WhatsApp copy lives in one module and docs/WHATSAPP_QUOTES_FLOW.md; voice lines untouched.
- 2026-10-12 founder: onboarding FORM (link sent on WhatsApp) where the user selects their own location and their parents location (also office/college/hostel) as saved places; Friday uses them as references for vendor search ("haircut for mummy" -> parents area). Server-side storage, tokenized single-use link, separate browser-restricted Maps key (never the server key). Spec to be written in docs/ONBOARDING_PLACES_FORM.md.
- 2026-10-12 founder idea: CONNECTED APPS (user connects Gmail, Calendar, other apps via OAuth; processed on our servers). My recommendation: NOT in the 6-day beta; start Google OAuth consent-screen/verification now (lead time); Phase 1 after beta = Google Calendar (add booking events, avoid clashes); Gmail later (restricted scopes need Google security assessment); phone-local apps are unreachable without an app. Tokens encrypted server-side, least scopes, disconnect + audit log, email text is untrusted input.
- 2026-10-12 founder: build the ENTIRE vendor calling flow covering almost all JustDial-type vendors. Approach: ~6 call ARCHETYPES (quote+slot, stock/price check, home-service visit quote, table/venue booking, rental, enquiry) x category packs (vocabulary), NOT one script per category. Data source = Google Places (JustDial data is proprietary: do not scrape it). Excluded categories: emergency, adult, loans/insurance cold-sell, legal; medical = fees/availability only. New voice lines are written as PENDING playbooks (not live) until the founder hears audio and approves (hear-before-change).
- 2026-10-12 builder task started (vendor-calling archetypes): founder ask = 6 archetype playbooks (quote_and_slot, stock_and_price, home_service_visit, table_or_venue, rental, enquiry) x category packs (~60 categories, Hinglish synonyms, Google Places queries, price sanity), excluded/restricted categories, `friday vendors list|show|match`. New voice lines go ONLY to `friday/playbooks/pending/` (not loaded by production); `friday playbook promote` needs the founder-approval marker `pending/<id>.approved` (markers are NOT created by the builder; founder hears audio first). Lesson to keep: new spoken lines never go live before the founder hears them.

## Decision note (2026-10-12): scope = vendor categories + request buckets
Founder clarified: NOT scraping JustDial; only look at which vendor categories and offerings it shows, to size the scope. Next: identify the top 10/20/30 vendor categories, then define "buckets" of user requests (quote, booking, booking confirmation, availability, general request...). A classifier routes each user request to a bucket; each bucket has its own call agent/playbook. Deliverable: docs/SCOPE_BUCKETS.md.

## Decision note (2026-10-12): Wave 1 = at least 20 categories
Founder: Wave 1 must have >= 20 vendor categories (10 is too small). docs/SCOPE_BUCKETS.md updated: wave 1 = 20 (old wave 1 + 10 from wave 2).

## Decision note (2026-10-12): no vendor DB for now
Founder: do NOT build a vendor database yet. Search Google Places live on each request. Only after we see Google returns good data (right category, phone numbers, open hours) do we consider a vendor DB. Overture/FSQ seeding pipeline is shelved. Measure instead: per category, % of Google results with a phone number and correct type.

## Decision note (2026-10-12): many small single-job agents; "best", not just nearest
Founder: build a separate scouting agent for Google (find vendors, fetch numbers) and in general MANY small agents, each with one narrow job, handing structured output to the next, so none hallucinates. Vendor selection must be about the BEST, not just nearest: read Google reviews, judge whether they look genuine, and what service the place really provides. Design: docs/AGENT_ROSTER.md. Build: friday/scouting/ (new package). Rule: LLM agents only get small closed tasks with JSON schemas; code does everything deterministic (distance, ranking math, phone validation).

## Task note (2026-10-12): scouting package (agents 6-12)
Founder/orchestrator ask: build `friday/scouting/` = place searcher, eligibility filter, review fetcher, review authenticity judge (rules first, optional LLM hook), service-evidence extractor (LLM behind interface; every claim needs a quote + review id verified by code), fit scorer, ranker; category table for the 20 Wave 1 categories; CLI `friday scout` and `friday scout-report`; docs/SCOUTING.md. Wraps (does not edit) discovery/google_places.py and google_geocoder.py. Tests use fixtures and fakes only. Raw review text stays in memory only.

## Decision note (2026-10-12): Delhi NCR vendor-count research
Founder asked: run the 20 Wave 1 categories in Delhi NCR only and see how many vendors Google returns. Script in scratchpad (not committed), results summarized in docs/NCR_VENDOR_COUNTS.md.

## Decision note (2026-10-12): nearest AND best, and a Project Manager agent
Founder: "best" must never be far away (no 100 km or 10 km best). Distance is a HARD limit per category (default radius, widened step by step only up to a hard max, and the user is told/asked before showing anything beyond the default). Agent 1 = classifier (bucket + category). Agent 2 = PROJECT MANAGER: asks clarifying questions when the request is unclear, identifies bucket/category, builds the plan and starts the other agents. Founder invites brainstorming on the framework. Spec: docs/AGENT_ROSTER.md section "Project manager and distance rule".

## Task note (2026-10-12): PM package (agents 1 and 2)
Orchestrator ask: build `friday/pm/` = Agent 1 classifier (closed lists, LLM behind an interface, fake/keyword baseline, labelled Hinglish fixture, `friday classify`) and Agent 2 project manager (deterministic state machine on a resumable task record, YAML plan templates per bucket x category, one clarifying question at a time max 2 rounds, step-agent Protocol with fakes, failure handling, cancel/change re-plan, decision log, `friday pm-sim`). Never touches quotes/api/tasks/scouting/playbooks/discovery; PM never calls vendors or writes vendor-facing words. Docs: docs/PROJECT_MANAGER.md.

## Note (2026-10-12): MCP of Indian apps
Founder asked about Zepto/Blinkit/Zomato/Swiggy MCP. Findings: Swiggy has official MCP servers (Food, Instamart, Dineout; builders page mcp.swiggy.com/builders); Zomato has an official MCP server (food ordering); Blinkit/Zepto only unofficial projects found. Idea: use these as "connected apps" tools (orders/table booking) instead of phone calls where available.

## Decision note (2026-10-12): PHASE 1 = vendor calling only
Founder: phase 1 is based on calling vendors only. Build it scalable, with proper experience for BOTH users and vendors. Out of phase 1: MCP/app integrations (Swiggy/Zomato), connected apps (Gmail/Calendar), proactive/safety features, vendor database, inbound random-request router. In: WhatsApp request -> classify -> project manager -> scout best-and-near vendors -> calls -> comparison/booking reply; vendor-side experience (respectful short calls, call-back/opt-out, calling hours, optional vendor info page); scale (queues, concurrency limits, retries, per-vendor rate limits, cost tracking, monitoring).
- DONE 2026-10-12 (builder): WhatsApp quotes flow, `friday/quotes/` + `docs/WHATSAPP_QUOTES_FLOW.md` (state machine, every message in 3 languages, delivery/fallback rules, edge cases). Text request -> one question at a time -> Places shortlist of 3 -> Haan/Badlo -> calls one at a time (salon playbook quote_only; book mode only if the first message says book + exact time + budget) -> ONE comparison with Book buttons -> booking task limited to that vendor/time/quoted price. State in DB table `quote_conversations`; restart-safe (`QuotesFlow.tick`, 30 s loop in Runtime); result sent on WhatsApp, SMS summary if the send fails or no delivery receipt in 20 min (`FRIDAY_QUOTES_DELIVERY_RECEIPT_WAIT_MIN`), voice call-back only if `FRIDAY_QUOTES_VOICE_FALLBACK=true` (records the request; the call itself is NOT wired); `status` text returns the stored result. Calls only 09:00-19:00 IST, 3 requests/user/day, 8 Places calls/request, DNC, kill switch, allow-list. TEST REDIRECT: `FRIDAY_VENDOR_CALL_REDIRECT_TO=+918607549916` dials that number instead of the vendor (real vendor name in the script). Offline chat: `uv run friday whatsapp-sim`. `friday doctor` prints the webhook URL. NOT tested live: real WhatsApp Cloud delivery/receipts, real Places in this flow, a real redirect call, the out-of-window `task_update` template (must be approved by Meta), DLT SMS template text.

## Decision note (2026-10-12): outcome-based messaging, no stage updates
Founder: do NOT send the user a message at every stage. Friday is outcome-based: one acknowledgement when the request is understood, then silence until there is an outcome (quotes ready, booking needs approval, a real problem, or a question only the user can answer). Optional per-request "send me updates" switch, off by default. Applies to WhatsApp quotes flow and project manager (no progress pings; failures are handled by the PM and only surfaced if the user must decide).

## Decision note (2026-10-12): classifier is channel-agnostic (WhatsApp AND inbound calls)
Founder: the classifier (and project manager) must not be WhatsApp-only. Users will also CALL the Friday number; the same classifier + PM handle the spoken request. Input = text from any channel (WhatsApp text, WhatsApp voice note transcript, live call STT transcript, SMS). Call-specific needs: short utterances, STT errors, Hinglish, ask clarifying questions by voice (one short question), hand off to WhatsApp for long details (address, pin) and for the final outcome.
- 2026-10-12 DONE (scouting): `friday/scouting/` (agents 6-12 + category table with radii, distance hard-filter rule), CLI `friday scout` / `friday scout-report`, docs/SCOUTING.md, tests/scouting (51 tests). Live smoke run of `friday scout` used the real Google key from env (a handful of calls; key never printed). Lesson: a loose name-match marked chain-style neighbours as duplicates; duplicates now need same phone or same distinctive name core within 150 m. Not yet wired: a real LLM for EvidenceLLM / TextPatternJudge.


## 8. START HERE (newest summary, written 2026-10-12 before the chat ran out of credits)

### 8.1 What the founder wants now (phase 1 = vendor calling only)
Flow: user request (WhatsApp text/voice OR a call to the Friday number) -> Agent 1 classifier (bucket + category) -> Agent 2 project manager (clarifying questions, plan, dispatch) -> scouting (best AND near, hard radius per category) -> consent/safety gate -> voice calls to vendors -> result extraction -> comparison/booking reply on WhatsApp. Full roster of 20 single-job agents: docs/AGENT_ROSTER.md. Wave 1 = 20 categories + buckets: docs/SCOPE_BUCKETS.md. Google Places live search, NO vendor DB for now. Messaging is outcome-based: one acknowledgement, then silence until an outcome or a question only the user can answer (optional per-request updates switch, default off). Parked: MCP/app integrations (Swiggy/Zomato/others), connected apps (Gmail/Calendar), proactive/safety features, inbound random-request router, vendor DB. Vendor-side experience (vendor info page, call-back number, opt-out list) proposed, founder has not yet said yes. Brand: keep "Friday". Voice final: Ritu, pace 0.9, temp 0.9.

### 8.2 Facts measured
Google Places live search, Delhi NCR (5 areas x 20 categories): every category hit the 100-result cap; phone present 83-99%, hours present mostly (PG/rental 68%); table docs/NCR_VENDOR_COUNTS.md. Scouting `friday scout-report` live run per category still TODO (types per category are guesses).

### 8.3 Builders (background agents) and their state at this moment
1. WhatsApp quotes flow (friday/quotes/*, friday/channels/*, api, tasks; docs/WHATSAPP_QUOTES_FLOW.md): RUNNING/unfinished. Last full suite: 3 failures in tests/quotes/test_flow.py (2) and tests/api/test_pipeline.py (1). Told to remove stage-update messages (outcome-based).
2. Vendor archetypes + category packs (friday/vendors/*, friday/playbooks/pending/*, docs/VENDOR_CALLING.md): RUNNING/unfinished. New spoken lines are PENDING, never live until the founder hears audio.
3. Scouting agents 5-12 (friday/scouting/*, docs/SCOUTING.md): DONE, 51 tests pass. Open: real LLM for evidence/text judge not wired; Google gives max 5 reviews and no reviewer history.
4. Classifier + project manager (friday/pm/*, docs/PROJECT_MANAGER.md): RUNNING/unfinished. Must be channel-agnostic (whatsapp_text | whatsapp_voice | call | sms), turn-based interface handle_turn(task_id, text, channel), no progress pings.
Stop-hook note: auto "WIP: builders in progress" commits sweep unfinished builder files onto branch claude/friday-phase-1 (pushed). Nothing is promoted or live because of them.
If the builders are gone in the new chat: read each doc above and the git log, run `uv run pytest -q` and `uv run ruff check .`, fix remaining failures, then finish the missing parts.

### 8.4 First things the next chat should do
1. Run full tests + ruff; list failures per area; finish or delegate fixes.
2. Wire scouting into the quotes flow (call friday.scouting.pipeline.scout; ask the user before using beyond_default_radius items); connect PM to channels.
3. Run `friday scout-report` live (limited calls) to verify Google types per category.
4. When vendor scripts are ready: generate AUDIO of all pending lines (hear-before-change), send to founder, wait for approval before `friday playbook promote`.
5. Show the founder all WhatsApp message texts for review.
6. Server update and live test call (pull, alembic upgrade head, friday tts-dict sync, deploy/call-me.sh).

### 8.5 Open founder decisions / questions not yet answered
- Wave 1 list OK? Which categories live first in beta (suggest salon, clinic, AC/plumber)? Booking/reschedule/cancel only with explicit delegation? Complaints out of beta?
- Add vendor-side experience pieces now? First supervised real vendor calls (with approval) before 30-50 users?
- Per-request updates switch: keep (default off) or drop?
- Onboarding places form and connected apps decisions; beta decisions in docs/BETA_LAUNCH_PLAN.md (size, domain, grievance email).

### 8.6 Founder-side to-dos (not code)
Restrict/rotate the Google key pasted in chat (and set budget alerts), type the new one into the server .env; delete leftover GitHub deploy key/token; ask Vobiz to switch call queue OFF; rotate other keys pasted earlier (Sarvam, OpenAI, Anthropic, Vobiz); check Meta WhatsApp test number and a Supabase project (Mumbai) when the DB phase starts; check Sarvam/Vobiz terms on AI disclosure.

### 8.7 Standing rules (unchanged, obey)
HEAR BEFORE CHANGE (audio first for any spoken line/voice/pace/pronunciation); update this file at the start of every task, commit, push; PUBLIC repo: no keys/tokens/passwords ever, never read or print .env, never commit .env or var/; no real calls except allow-listed founder number +918607549916 and only with approval; short chat replies, heavy work to builder agents; founder writes Hindi/Hinglish/English mixed, reply in English; do not assume pronouns.

### 8.8 Go-live estimate (2026-10-12, my estimate, not a promise)
Original target (Oct 16) is NOT realistic after scope grew (agents, 20 categories). Estimate: internal + founder/friends supervised beta ~Oct 22-24; invite-only public beta (30-50 users, salon + 2-3 categories) ~Oct 30 - Nov 3. Gates: builders finished and integrated; full suite green; live test call confirmed; Meta WhatsApp Business verification and message templates approved (outside our control, can take days to weeks); legal/consent pages + grievance email; audio of all new lines approved; supervised real vendor calls; Sarvam/Vobiz AI-disclosure terms checked; Vobiz call queue off; keys rotated.

### 8.9 Decision (2026-10-12): beta launches with ALL 20 Wave 1 categories
Founder: the 30-50 beta users will not only use salon; launch with all 20 categories live. Consequences: (a) all 6 archetype scripts + 20 category packs need founder AUDIO approval before promote (hear-before-change); (b) supervised test calls needed per archetype (not per category) plus a smoke call for each category pack; (c) per-category kill switch in config so one bad category can be turned off without redeploy; (d) unknown/unsupported request -> polite WhatsApp reply + wishlist; (e) go-live estimate moves to ~Nov 5-10 (was Oct 30-Nov 3) because approval of more audio and more real-call testing; internal supervised beta stays ~Oct 22-26.

### 8.10 Founder (2026-10-12): the beta must have a WOW factor
Not a thin demo: every user should think "what is this, this is awesome". Candidate wow moments (phase 1, vendor calling only): (1) human-like Hinglish voice Ritu on calls; (2) answer in minutes, a single comparison message with best-and-near picks and one-line reasons from reviews; (3) works by WhatsApp text, voice note OR a call to Friday; (4) remembers places (self, parents) and people ("for mummy"); (5) one-tap booking with delegation and reminders; (6) short proof of the call (summary, what the vendor said); (7) handles messy real requests across 20 categories; (8) zero chatter, only outcomes. Founder to pick the top 2-3 to polish first.

### 8.11 Founder (2026-10-12): the beta bot must be PROACTIVE too
Proactive is part of the wow factor. Must respect: outcome-based/low-noise rule (rare, high value), user opt-in, WhatsApp rules (outside the 24h window only approved templates; opt-in; quality rating), DPDP consent, quiet hours. Candidate proactive moments within vendor calling: appointment reminder + reschedule offer; "slot opened / price dropped" re-check; recurring services (haircut every ~4 weeks, AC service before summer, car service due, pest control cycle); occasions the user told us (mummy's birthday -> florist/cake/salon); unanswered/failed request follow-up ("two salons did not pick up, retry tomorrow?"); weekly "your saved places" nudge NO. Proactive voice calls to users = later; WhatsApp first. Founder to choose which 2-3.
- 2026-10-12 founder rules for the PM (built in `friday/pm/`, docs/PROJECT_MANAGER.md): (1) NO progress/stage messages: one acknowledgement when understood, then silence until an outcome or a question only the user can answer; per-request `updates_on` flag, default off. (2) Channel-agnostic: classifier and PM take `channel` (whatsapp_text | whatsapp_voice | call | sms); on a call ONE very short spoken question at a time, long inputs are requested on WhatsApp afterwards, the final outcome always goes to WhatsApp; turn interface `handle_turn(task_id, text, channel)`. DONE: classifier (104 labelled examples), PM, `friday classify`, `friday pm-sim`. The spoken question lines in `friday/pm/data/plans.yaml` (`spoken:`) must be played to the founder before the voice layer uses them (hear-before-change).

### 8.12 Founder (2026-10-12): ALL 8 wow items matter for the beta (momentum)
Founder: all 8 wow items (8.10) plus proactive (8.11) are wanted in the beta; a weak start would kill momentum. Decision: launch date is set by a QUALITY BAR, not the calendar. Revised estimate (mine): supervised internal beta ~Oct 26-30; public invite-only beta ~Nov 12-20. Launch gate (all must pass in supervised testing): >=90% of test requests across the 20 categories reach a correct outcome end to end; first reply < 10 s; comparison message in < 10 min median (target 5); vendor-call script approved by founder audio; no wrong-booking or wrong-price incident in testing; proactive messages limited (<= 2/user/week, opt-in, templates approved); per-category kill switch. Waves of invites (10, then 30, then 50) so problems are caught before everyone sees them.

### 8.13 Founder (2026-10-12): proactive = WhatsApp AND voice calls to the user; NOT marketing
Proactive contact is only about things the user booked or asked for (reminders, reschedule, follow-up on an unfinished request, repeat service tied to a past booking, an occasion they told us). No promotions, no cold suggestions. Channel: WhatsApp message or a call from Friday to the user (user chooses; default WhatsApp, call for time-critical or when the user prefers calls). Rules: explicit opt-in at onboarding with channel + quiet hours chosen by user, transactional wording only, max 2/week, calls only 9:00-20:00 unless the user chose otherwise, easy "stop" in one word (WhatsApp) or by voice, DPDP consent record, no real calls except allow-listed founder number until the founder approves more; all new user-facing spoken lines need founder AUDIO approval first (hear-before-change). Proactive user-call playbook = new playbook "user_notify" (short, Ritu voice, offers one-tap WhatsApp follow-up).

### 8.14 Founder (2026-10-12): proactiveness comes ONLY from the user's own conversations with Friday
Friday acts proactively only around what the user said/asked/worried about in chats and calls with Friday (e.g. "mummy's birthday on the 14th", "my AC is making noise, will decide next week", "haircut done, remind me in a month"). No outside data, no guessing from other apps (connected apps are out of phase 1). Design: new agents in docs/AGENT_ROSTER.md: #21 Memory extractor (reads each finished conversation/call, extracts follow-ups/dates/concerns/preferences with the quote and message id; stored server-side; validated), #22 Proactive planner (turns stored follow-ups into scheduled actions with channel + time, within the 8.13 limits). User controls: "what do you remember" shows the list, delete one or all, switch proactive off (DPDP).

### 8.15 Builder 4 (classifier + PM) DONE 2026-10-12
friday/pm/ built: classifier (104 labelled examples; offline baseline 104/104 is optimistic, real LLM not measured), PM state machine (resumable JSON task record, YAML plan templates 5 types x 20 categories), `friday classify`, `friday pm-sim`, docs/PROJECT_MANAGER.md; 153 tests pass. Full suite had 4 failures outside pm: tests/api/test_pipeline.py::test_voice_note_transcribed_for_brain, tests/e2e/test_bugs.py::test_named_business_is_the_one_that_gets_dialled, tests/quotes/test_flow.py (2 tests); 1 ruff error friday/playbooks/dryrun.py:216 (other builders' files). Spoken question lines in plans.yaml need founder audio approval. NOT built: adapters from PM to scouting/quotes/voice, DB task store, agents 21-22 (memory extractor, proactive planner), "fewer than N -> offer to widen".

- 2026-10-12 founder ask (new chat): "can you see the latest work done in Friday?" Answered by reading HANDOFF and git log; no code change.

- 2026-10-12 founder ask (new chat): pick up pending next actions from 8.4 (full tests + ruff, fix failures, wire scouting/PM, finish missing parts). Starting with tests/ruff.
- 2026-10-12 DONE (this chat): full suite 2222 passed + ruff clean (earlier failures were already fixed). Scouting wired into the quotes flow: `friday/quotes/scout_finder.py` (`ScoutingVendorFinder`, same interface as `VendorFinder`), switch `FRIDAY_QUOTES_USE_SCOUTING` (default false; needs the real Google directory; beyond-default-radius vendors are never shown until the flow can ask the user). Tests: tests/quotes/test_scout_finder.py. Not yet live-tested. NEXT: PM-to-channels adapter, `friday scout-report` live run, audio of pending lines, WhatsApp copy review, server update + test call.

- 2026-10-12 founder ask: use the Google key (shown in a screenshot) for a live scout-report now; founder rotates it later. Used only as an inline env var for one command, never written to a file or the repo.
- 2026-10-12 DONE: live `friday scout-report` ran (key accepted; key never stored). Results in docs/SCOUTING.md: type lists are wrong for pest_control, driving_school, coaching_classes, appliance_repair, event_services (0-20% match): NEXT fix `friday/scouting/categories.py` types by inspecting real results. Founder will rotate the key later.

- 2026-10-12 founder ask: gave the Sarvam key (typed "server" = Sarvam) to generate audio of the pending vendor-call lines for approval (hear-before-change). Used inline env only, never stored.
- 2026-10-12 DONE: audio of pending archetype lines (10 samples, one per call type) sent to the founder for approval (hear-before-change); NOT approved yet, nothing promoted. Script issues found while previewing: table_or_venue says "4 logon ke liye table for chahiye" (stray "table for"; also used for banquet and hotel room: "150 logon ke liye table for", "ek raat ka room rate" after "table for"); fix wording template before promote. Founder also gave GPT and Sarvam keys in chat (used inline only, not stored) and asked to store keys on his iPad: answer = put them in the cloud environment's settings (Edit environment: variables/secrets), never the repo.

- 2026-10-12 founder ask: founder will write the calling scripts later (give him ONE place to enter script/way of talk); Ritu voice is good. Do the TECH work completely: automatic vendor calls end to end, proactive, call quality, call speed. Work through it on branch claude/friday-phase-1.
- 2026-10-12 DONE (tech pass 1): NOTE `friday/vendors/` from the earlier builder was never committed (lost); rebuilt as `friday/vendors/packs.py` = data only, one pack per Wave 1 category -> archetype playbook + price sanity + fee unit (no spoken words). `playbooks/select.py` routes non-salon categories to the archetype playbook ONLY when it is promoted into data/ (pending never used by calls) and fills inputs (`_vendor_inputs`); table needs `party_size:`/date else normal policy. `Conv.category` + `calls.py` carry the category. Founder script entry file: docs/CALL_SCRIPTS_EDIT_HERE.md. Tests tests/vendors. NEXT: PM->channels adapter (real StepAgents), proactive agents 21/22, call speed/quality.
- 2026-10-12 DONE (tech pass 2, full suite 2238 pass, ruff clean): `friday/pm/adapters.py` (RealStepAgents: locate, scouting search/rank, consent policy = call window + pause switch, per-vendor call via EnginePlacer/EngineVendorCalls with polling, collect/compare/report), `friday/pm/gateway.py` (PMGateway: WhatsApp front door for NON-salon categories; salon stays in quotes flow; each turn runs in a background task; replies sent when ready; `resume_all` after restart), hooked in api/inbound.py after quotes. Switches (all default OFF): FRIDAY_PM_ENABLED, FRIDAY_PM_USE_LLM_CLASSIFIER, FRIDAY_QUOTES_USE_SCOUTING; FRIDAY_PM_STORE_DIR=var/pm. Archetype calls only run after the founder approves + `friday playbook promote`. NOT live-tested. Gaps: resume_all not yet called at startup; PM replies are plain text (no buttons); booking from PM not built (quote-only).
- 2026-10-12 founder ask: brainstorm proactiveness + the inbound call conversation (user calls Friday's number). Design written to docs/PROACTIVE_AND_INBOUND_DESIGN.md.
- 2026-10-12 founder (brainstorm): proactive should feel like JARVIS with Tony Stark: asks questions, suggests, anticipates, talks like a partner. Claude's proposal: two layers. (1) IN-CONVERSATION proactivity (suggestions, smart questions, next-step offers, tradeoffs, heads-ups) is rich and uncapped because the user is already talking; (2) OUTBOUND proactivity (Friday starts the contact) stays rare and tied to the user's own words/bookings (rules 8.13/8.14) until trust is earned. Detail added to docs/PROACTIVE_AND_INBOUND_DESIGN.md section H. Founder to react.
- 2026-10-12 FOUNDER VISION (changes the long-term scope; supersedes 8.14 for the later phases): Friday is a full personal assistant with access to EVERYTHING THE USER GRANTS (mail, calendar, etc.), and proactively highlights things like an unanswered email whose escalations keep coming, and gives suggestions across daily life. Claude's plan: Phase 1 stays vendor calling; start Google OAuth verification NOW (lead time); Phase 2 = Gmail+Calendar read-only "attention engine" (signals, escalations, deadlines, daily digest, draft replies sent only after the user approves); design in docs/PROACTIVE_AND_INBOUND_DESIGN.md section I. Phone-local data (WhatsApp chats, SMS, photos) is unreachable without an app; finance via RBI Account Aggregator later.
- 2026-10-12 founder: a generic AI product will not work; brainstorm ALL use cases and build the product AROUND them (wow factor). Result: docs/USE_CASES.md (catalogue by life area, scored on frequency x pain x wow x feasibility, hero picks, building blocks). Founder to pick the hero use cases; beta and build order follow from them.
- 2026-10-12 founder decision: Gmail/mail/calendar "chief of staff" = PHASE 2. BUT all proactiveness around VENDORS must be COMPLETE in PHASE 1 (appointment reminders + reschedule, retry unanswered vendors, follow-up after quotes, slot/price re-check, recurring services, occasions, post-visit feedback, reconfirmation). Building `friday/proactive/` now (extractor agent 21 from the user's words, planner agent 22 with caps/quiet hours/opt-in, scheduler tick, one messages module). Defaults used until founder answers 5 questions: opt-in asked in context at the first proactive item; explicit "remind me" and appointment reminders do not count against the 2/week cap; calls to user only for time-critical.
- 2026-10-12 founder rule: proactive contact limited to MAX 3 messages per day, OR one morning digest bundling them; decided from what the user has done on the platform with Friday (their own requests, bookings, reminders). Supersedes the 2/week default for vendor proactiveness.
- 2026-10-12 DONE (proactive, phase 1 vendors): the proactive engine (friday/proactive/) already existed (daily cap 3, quiet hours, autonomy, ignore-learning, briefing). Added founder rule: over the cap (or `FRIDAY_PROACTIVE_DIGEST_ONLY=true`) a normal nudge becomes a line of the next MORNING DIGEST (guardrails verdict "digest"; briefing is sent even if the user never switched it on; digest lines marked delivered after it goes out); appointment reminders/results/urgent stay outside the cap. New `friday/proactive/vendor_triggers.py`: category cadence (salon 4 wk, car 6 mo, pest 3 mo, vet 1 yr), open quotes follow-up (20-48 h, nothing booked), unanswered-vendors retry offer. Tests in tests/proactive. Still open: per-user digest-only switch (global setting for now), the 5 founder answers on proactive (docs/PROACTIVE_AND_INBOUND_DESIGN.md G), user-facing wording to review, PM (non-salon) tasks are not tasks in the engine so their nudges depend on the quote tasks created by calls.
- 2026-10-12 founder: continue and complete the tech task today (fix category type lists from real Google data, table wording, PM resume at startup, call speed/quality).
- 2026-10-12 DONE: category type lists fixed from real Google data (name_keywords fallback in scouting/categories.py + eligibility.py; measured 59-100% type match, docs/SCOUTING.md). CORRECTION: the earlier "table for" wording issue in table_or_venue was MY preview input (--services 'table for 4'), not a script bug; with service='dinner' the lines read correctly. Pending lines still need founder approval.
- 2026-10-12 DONE: PM jobs resume at runtime start (Runtime._resume_pm); adaptive end-of-speech wait (650 ms for short answers, FRIDAY_VOICE_SHORT_END_SILENCE_MS, docs/LATENCY.md; not live-tested); product-manager agent defined in .claude/agents/product-manager.md and first competitor report requested into docs/COMPETITORS.md (background agent).
- 2026-10-12 PM agent: first competitor report exists at docs/COMPETITORS.md (closest "Instinct" = US agent with Concierge calling; Puch AI, Google, Meta Muse covered; founder to confirm which Instinct).
- 2026-10-12 founder ask: place a real test call to his allow-listed number (+918607549916). Approval given by the founder for this call.
- 2026-10-12 founder test call: first reply lag (had to repeat 'hello'); transcript showed one Hello, Friday's opening line, then callee 'haan ji bataiye' and hang-up. Timing logs go to the livecall terminal, not journalctl; call-me.sh now tees output to var/livecalls/last-run.log so the next run can be diagnosed. Candidate causes: slow STT of first utterance, first utterance lost, TTS first audio.
- 2026-10-12 founder test call 2: after 'haan ji bataiye' the turn took 4.85 s: log shows llm purpose=call_turn gpt-5.4-mini latency 2160 ms (intent understanding by LLM), p95 turn latency 4852ms. Fix: deterministic fast path for common acknowledgements before the LLM (playbooks/understand.py).
- 2026-10-12 DONE (call speed, general): relaxed call schema ON (model writes only filled keys; benchmark 824->672 ms p50, 0 repairs), LLM connection warm-up (core/warmup.py) at runtime start + livecall, confident rules for 'haan ji bataiye' family. Founder wants a GENERAL speed fix, not hard-coded replies: plan in docs/LATENCY.md (speculative understanding, streaming STT, small intent classifier, backchannel needs audio approval). Next: founder re-runs the test call; read var/livecalls/last-run.log.
- 2026-10-12 founder: test call 3 was faster and good. Ask: ideas to humanize calls so businesses do not hang up because it is an AI. Ideas in docs/HUMANIZING_CALLS.md. Rule kept: humanize = quality, never deny being an AI. Also pending: a call dropped in the middle (waiting for last-run.log).
- 2026-10-12 founder: keep 'virtual assistant'; worried businesses cut the call on hearing an AI voice; asks about other vendors (ElevenLabs). ElevenLabs adapter already exists (friday/voice/tts/elevenlabs.py, Flash v2.5, REST pcm_16000, not streaming in the call path). Added `friday say --provider elevenlabs --phone` (phone-quality bake-off). Plan: blind A/B on 8 kHz audio before any switch (hear-before-change); needs ELEVENLABS_API_KEY + voice ids in env.
- 2026-10-12 founder gave an ElevenLabs key in chat to render voice samples (inline env only, never stored). Rotate after.
- 2026-10-12 ElevenLabs bake-off #1 sent (phone quality): Ritu vs EL premade Jessica/Bella/Sarah. ElevenLabs FREE plan cannot use library (Indian/Hindi) voices via API (HTTP 402: needs $5 credit or Starter); account voice list has only premade English voices + 1 library Hindi voice. Candidate Hindi library voices found (shared library, conversational): Zara OtEfb2LVzIE45wdYe54M, Pari 06llJPvI62CjqSWOX9Gp, Neha P X1aCu8g69vgtNfFwu68G (added to founder's account as friday-test-*). Founder key must be rotated (pasted in chat). Cost/latency/data-residency caveats in chat.
- 2026-10-12 CORRECTION to my earlier claim: ElevenLabs Flash v2.5 is NOT slower than Sarvam (first audio 170 ms stream / 321 ms REST vs Sarvam stream 260 ms / REST 1387 ms, measured from the sandbox; re-measure from the Bangalore server). Quality/cost/data-residency still decide. Table in docs/LATENCY.md.
- 2026-10-12 founder bought ElevenLabs paid plan; render Indian/Hindi library voices (Zara, Pari, Neha P, Sara) in phone quality for comparison with Ritu.
- 2026-10-12 founder: Zara and Neha P (ElevenLabs) sound much better than Ritu on phone-quality samples. Next: wire ElevenLabs Flash into the live call (streaming ulaw_8000, Sarvam fallback, voice ids in settings, default OFF until founder flips it); founder to pick Zara vs Neha P by a test call. Hear-before-change: voice switch only via env on the test call.
- 2026-10-12 DONE: ElevenLabs wired into the live call, opt-in: streaming (synthesize_stream, pcm_8000), FallbackTTS (Sarvam spare), settings FRIDAY_TTS_PROVIDER / ELEVENLABS_VOICE_ID / FRIDAY_TTS_FALLBACK / FRIDAY_ELEVENLABS_MODEL / _STREAMING; tests/voice/test_elevenlabs_stream.py; smoke test first audio 176 ms. Founder to try Zara (OtEfb2LVzIE45wdYe54M) and Neha P (X1aCu8g69vgtNfFwu68G) on the server .env via test calls; pick one. Cost/data-residency still to decide. Voice choice stays env-only until the founder confirms.
- 2026-10-12 founder: wants replies within ~1 s like a human, without hard-coding every script. DONE: reply-gap logging in the call leg (true caller-felt latency), early commit of short complete answers (FRIDAY_VOICE_EARLY_COMMIT_WORDS, default 6, 0 = off). Plan table in docs/LATENCY.md; NEXT biggest: Sarvam realtime streaming STT (wss speech-to-text-realtime), speculative understanding on partials, stream the model reply into TTS, approved backchannel 'ji'. Founder to re-run the test call and send last-run.log (grep 'reply gap').
- 2026-10-12 founder: yes, build STREAMING SPEECH-TO-TEXT (Sarvam realtime wss speech-to-text-realtime, saaras:v3-realtime) next; also asked how to deploy (answered: git pull --ff-only, uv sync, .env edits, systemctl restart friday).
- 2026-10-12 founder pasted the ElevenLabs lines into the SERVER SHELL instead of .env (screenshot): no effect + key in scrollback/history; gave safe commands (append to .env with read -rs, history -c, rotate key). Streaming STT: client written (friday/voice/stt/sarvam_stream.py); probe results: partials give the full sentence ~250 ms after speech end, final ~900 ms after; plan = act on a stable partial for short answers, else final; integration into SarvamCallLeg in progress (opt-in FRIDAY_VOICE_STREAM_STT).
- 2026-10-12 STREAMING STT FINDINGS (measured): Sarvam REST STT only ~450-550 ms; Sarvam realtime final ~780-900 ms after speech end and its partials drift until ~730 ms (and language_code=auto mistranslates Hindi partials to English), so Sarvam streaming gives NO gain over REST+speculation. ElevenLabs Scribe v2 realtime (ulaw_8000, language hi, vad 0.3 s): committed 620-880 ms, partials stable (full text often available before/at speech end) -> acting on a stable partial can save 300-600 ms. Decision: provider-agnostic streaming client; ElevenLabs default when its key is set; Sarvam kept as option; REST fallback always.
- 2026-10-12 DONE: streaming STT built, opt-in (FRIDAY_VOICE_STREAM_STT, provider auto = ElevenLabs if keyed, else Sarvam, REST fallback). HONEST numbers in docs/LATENCY.md: typical gain 0-300 ms (up to ~650 ms), not a 1 s fix alone. NEXT for <1 s: speculative understanding on the stable partial, faster model host / small classifier, stream model words to TTS, approved 'ji' acknowledgement.
- 2026-10-12 founder read: Puch AI = general chatbot on WhatsApp (Claude-like), not an acting assistant; Instinct = the real personal-assistant comparison. Added to docs/COMPETITORS.md (threat of Puch to core job: medium-low until it adds actions). Positioning: avoid 'AI on WhatsApp'; say 'Friday phones the shops for you'.
- 2026-10-12 PM agent: deep-dive on Instinct, Meta Muse and Google (calling flow, privacy, India angle, lessons, 5 founder decisions) exists as 'Update 2026-10-12 (b)' at the bottom of docs/COMPETITORS.md.
- 2026-10-12 founder test call 4: ElevenLabs returned HTTP 401 invalid_api_key on the server (old/rotated key); fallback to Sarvam kept the call alive (reply gap 534 ms, p50 188 ms). Founder provided a new key in chat (checked once from the sandbox, never stored); he must type it into the server .env via the hidden prompt.
- 2026-10-12 test call 5 (Zara + streaming STT live): no ElevenLabs errors, stream stt ready; reply gaps 1303 ms (hello) and 3637 ms (second turn: call_turn LLM 2161 ms with only out=28 tokens => network/host latency, not output length; sandbox measures ~650 ms). Added deploy/latency_probe.sh to measure server->OpenAI/ElevenLabs/Sarvam latency. Need founder to run it and send the transcript file to see why the model was called for the second utterance.
- 2026-10-12 founder asked (as a question) whether Sarvam can be the brain too. Findings: server probe (Bangalore): OpenAI tiny completion 1.3-1.5 s, ElevenLabs TTS first byte ~280 ms, Sarvam TTS first byte ~100 ms. Sarvam chat: /v2 endpoint needs beta access (not available), /v1 works with models sarvam-105b (reasoning, slow, empty content at small max_tokens) and sarvam-105b-conversations (direct, supports json_schema): 10/10 correct on the playbook intent task, p50 ~455 ms from the US sandbox. Plan: SarvamLLM provider routed ONLY for purpose call_turn (understanding), opt-in setting; other purposes stay on OpenAI/Claude. Also: ElevenLabs STT mis-heard the founder (got 'जी यह उधर है' instead of 'haan ji bataiye'): streaming STT with ElevenLabs is NOT accurate enough on real phone speech; recommend FRIDAY_VOICE_STREAM_STT=false (keep Sarvam REST STT) until compared on real audio.
- 2026-10-12 DONE: Sarvam call-turn model route built (friday/brain/sarvam_llm.py; FRIDAY_LLM_CALL_TURN_PROVIDER=sarvam, opt-in, OpenAI fallback), deploy/setenv.sh + latency_probe updated. Founder to set FRIDAY_LLM_CALL_TURN_PROVIDER=sarvam and FRIDAY_VOICE_STREAM_STT=false on the server and re-test; read 'reply gap' and 'llm sarvam' log lines.
- 2026-10-12 21:39 TEST CALL RESULT (Zara voice + Sarvam call-turn model + streaming STT off): reply gaps 624 / 779 ms (first sub-second), Sarvam model call 305 ms vs OpenAI 2161 ms on this server, call latency p50 269 ms p95 577 ms. Next: full-script test, decide to make Sarvam call-turn + ElevenLabs voice the default, benchmark Sarvam for request reading/classification (founder has not answered yet).
- 2026-10-12 FOUNDER DECISION (model routing): Sarvam for the real-time call lane (call-turn model, speech-to-text, voice); GPT or Claude for the backend brain where accuracy matters and speed does not. Implemented: llm_call_turn_provider now defaults to sarvam (needs key; skipped for the fake LLM); policy written in docs/ARCHITECTURE.md. Next: pick GPT vs Claude per backend job by accuracy on labelled examples (PM classifier has 104 labelled Hinglish examples).
- 2026-10-12 founder: when the business asks Friday something, she must not give one-line canned replies; AI should understand the question fully and answer properly using what she knows (the request facts), not hard-coded. Plan: grounded answerer (fact sheet + guardrails + fast Sarvam call-turn model), validated in code, fallback to the existing safe line; audio samples of Q&A for founder approval before enabling (hear-before-change).
- 2026-10-12 DONE: open-question answerer built (friday/playbooks/answerer.py; brain.answer_question; engine hook; switch FRIDAY_PLAYBOOKS_OPEN_QUESTIONS, OFF). Samples (Zara, phone quality) sent for approval; design in docs/OPEN_QUESTIONS.md. Waiting for founder approval before enabling.
- 2026-10-12 founder PRIORITY: the bot must not hallucinate and must not repeat herself again and again; handle all such cases (open-question answers can wait). Plan: (1) ground every extracted number/time against the vendor's actual words, (2) generic repeat guard (never the same line more than twice, no duplicate callee utterances), (3) validator for LLM-written call lines (numbers/claims must come from the brief/transcript), (4) adversarial dry-run tests.
- 2026-10-12 DONE (founder priority: no hallucination, no repeating): grounding of model-extracted values against the vendor's words (understand.ground), repeat guard in the script engine, duplicate-utterance drop at the leg, number/time grounding + repeat guard for LLM-written lines (brain/guards.py), docs/PLAYBOOKS.md section, tests/playbooks/test_grounding_and_repeats.py; dry-run baselines unchanged. Not yet checked: front-door (inbound) conversation guards, STT mishearing (e.g. 'हैटर ₹300') beyond price sanity ranges.

### Fix note (anti-hallucination guards)
Commit ccd9526 was pushed with 23 failing tests (my mistake: I chained commit after `tail`). Fixed: number guard now ignores durations ("10-15 minute"), thousands commas and times inside text; repeat guard allows a re-ask after "are you a bot?"; duplicate-utterance drop only for 3+ word sentences, never in hold mode. Full suite green. Rule: never chain commit/push after a piped test run; use `&&` on the pytest exit code.

### Task: WhatsApp number setup (founder, 13 Oct)
Founder bought a new SIM for WhatsApp and has an account on "Helter" (probably Heltar, a WhatsApp Business API provider). Asked for step-by-step setup. Our code speaks Meta WhatsApp Cloud API directly (WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET). Open: confirm whether Heltar gives a Meta-compatible token/phone-number-id/webhook, or we need a Heltar adapter.

### Task: founder asks what open items to focus on (business name not final, so WhatsApp business setup parked)
Answer given in chat: founder-only items list below (13 Oct). WhatsApp number/Meta verification waits for the business name; the simulator keeps working meanwhile.

### Task: founder reports live call was very bad: Friday did not stop when he spoke (no barge-in), kept finishing her sentences (13 Oct)
Investigating. Suspects: barge-in/echo gating in voice/telephony/sarvam.py, streaming TTS (ElevenLabs/Sarvam) cancel, hold/echo gate changes this week.
- 13 Oct FIX: barge-in never fired on real speech. Cause: needed 15 CONSECUTIVE loud frames at 2.5x the speech threshold; real phone speech dips between syllables and is quieter. Now: 7 loud frames within a sliding 12-frame window at 1.6x (sarvam.py BARGE_IN_*). Test: test_speech_with_gaps_and_a_moderate_voice_still_interrupts_her. Needs live re-test; if she now cuts herself on her own echo, raise BARGE_IN_LEVEL (e.g. 2.0). Lesson: barge-in thresholds were only unit-tested with synthetic loud tones.

### Task: founder test call 13 Oct after barge-in fix: interruptions fine; scripts not good (she does not ask the question / how to communicate missing); words unclear, pieces of words missing (13 Oct)
Investigating clipped audio (suspects: odd-byte PCM chunk boundaries in streamed TTS, false barge-in from echo at 1.6x, chunk send pacing) and the script flow (needs transcript file var/livecalls/livecall-*.txt).
- 13 Oct DECISION (founder): voice = Ritu on Sarvam (clearer than Zara/Neha on the phone line). All real-time call lane stays on Sarvam. Server setting: FRIDAY_TTS_PROVIDER=sarvam (ElevenLabs stays as optional spare, not default).

### Task: bug 13 Oct: vendor asked "Himanshu sir kaun hai?" and Friday kept repeating "Main Friday hoon, Himanshu sir ki virtual assistant" (identity question answered with the intro line every time)
Fix: separate intent for "who is <user>" with a real answer (what the user wants and why Friday is calling), not the intro; never repeat the same answer, second ask gets a different/short follow-up.
- 13 Oct FIX: "X sir kaun hai?" no longer loops the intro. Salon playbook WHO_IS_THIS: 1st = reintro + why line (intro_book/intro_quote, both already approved lines), 2nd = why line only. Engine `_pick`: options of a conditional list count max_uses separately (key `#i`).
- 13 Oct FOUNDER REQUEST: review call scripts ONE USE CASE AT A TIME in chat: I paste the full script of each use case, founder approves or gives changes, I (script agent) update, then move to the next. Start: salon_booking. Nothing is promoted without his approval.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon): opening "Hello, kya meri baat Shreya Salon se ho rahi hai?" stays. After his "haan": state the PURPOSE FIRST, in one short line, to keep the vendor's hook (long AI-voice speech makes them hang up): "Ji sir, maine aapko haircut aur beard trim ki booking ke regarding call kiya hai." Wait for "haan ji, bataiye". Only then the details (price/slot question). Who-she-is intro moves out of the first turn (said only when asked, or after the hook). DRAFT only: engine/playbook NOT changed until he approves the text and hears the audio.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), booking close: once price and slot are confirmed she says "Theek hai sir, aap ek booking kar lijiye {user full name, e.g. Himanshu Goyal} ke naam se, {kal} {5 baje} ka. Thank you." Needs a new input `user_full_name` (booking name, spoken in Devanagari) next to `user_first_name`. DRAFT: not yet in the playbook (text + audio approval first).
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), price question wording: "Sir, {haircut aur beard trim} ke estimated kya charges rahenge?" (adds "estimated"). DRAFT, not in the playbook yet.
- 13 Oct FOUNDER: add natural FILLER words to the call script (humans use them). NOTE: `friday/voice/text.py strip_fillers` and `brain/guards.py strip_fillers` currently REMOVE disfluencies ("um", "hmm", ellipsis hesitation) before TTS, so fillers written in lines are dropped. To do after text + audio approval: allow-list the approved fillers (e.g. "Ji", "Achha", "Haan", "Toh") so they survive, keep removing the rest. Draft filler placement is in chat (use case 1).
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), slot question wording: "Toh sir, kal shaam ko paanch baje ka slot booking ke liye available rahega?" (Roman: "Toh sir, {kal} {shaam ko paanch baje} ka slot booking ke liye available rahega?"). DRAFT only.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon): do NOT use the word "rahega" in the slot question; use "hai": "Achha theek hai sir, toh sir {kal} {paanch baje} ka slot booking ke liye available hai?" General style rule: present tense "hai" not future "rahega" in questions (the price question "kya charges rahenge" was his own wording, keep it). DRAFT only.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), booking close (replaces the earlier close): "Achha theek hai sir, aap booking confirm kar lijiye {user_full_name} ke naam se, {kal} {paanch baje} ka. {Kal} aapko ek baar confirmation ke liye main dobara call kar lungi. Thank you." (his dictation read "Himanshu girl": taken as Goyal.) IMPLICATION: Friday herself promises a confirmation call, so the system MUST schedule a reconfirm call (day before / same day) for every booked slot; check the existing reconfirm task and make it default for salon bookings. DRAFT only.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), busy slot: (a) if the asked slot is busy she asks for a nearby slot: "Koi aas paas ka slot available hai? {4 baje} ya {6 baje} ke aas paas?" (around the requested time); (b) if the salon offers a time within +/-1-2 hours of the requested time ("4 baje ka hai") she CONFIRMS it (same booking close with the new time); (c) if it is further (another day: "kal nahi, parso") she does NOT book: "Achha theek hai sir, ek baar main {user} {sir} se confirm karke poochh kar aapko call back karti hoon. Thank you." (outcome SLOT_OFFERED / call back). Implementation: the +/-2 h window must be a code rule in the slot/commit check (and inside the user's delegation), not model judgement. DRAFT only.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon): the confirmation call is made BEFORE THE SLOT TIME ("paanch baje se pehle"), not "kal". New close line: "Achha theek hai sir, aap booking confirm kar lijiye {user_full_name} ke naam se, {kal paanch baje} ka. {Paanch baje} se pehle main aapko ek baar confirmation ke liye call kar lungi. Thank you." So the reconfirm call is scheduled shortly before the slot (lead time to decide, e.g. 1-2 h before; ask founder). His "yes yes" before this was not tied to a specific question: re-ask the open items.
- 13 Oct FOUNDER SCRIPT FEEDBACK, use case 1 (salon), busy slot refined: if the asked time is not free she first asks for a time within 1-2 hours on the SAME DAY; if none, she asks for the NEAREST possible time (any day); then, if that is outside the +/-1-2 h window, she says "Theek hai sir, main {user} {sir} se confirm karke aapko 5 minute mein call back karti hoon." (promise: callback in ~5 minutes). IMPLICATION: the user must be asked live (WhatsApp/call) and Friday must call the salon back within 5 minutes; define what happens if the user does not answer in time (call the salon: "abhi confirm nahi ho paya, thodi der mein", or WhatsApp). Needs founder decision. DRAFT only.
- 13 Oct FOUNDER DECISION (use case 1, salon) SUPERSEDES the +/-1-2 h auto-confirm: Friday NEVER books a time different from the one the user asked, even 1 hour off, without the user's OK. Busy slot flow: ask nearby time (same day, 1-2 h around) -> if none, ask nearest possible -> in BOTH cases she does not book; she says she will confirm with the user and call back in ~5 minutes. Friday then asks the user on WhatsApp: "5 baje ka slot nahi tha, 4 baje ka hai, book kar dun?" (Yes/No buttons) = the WOW moment; on Yes she calls the salon back and books (commit under the user's fresh approval). The code-level commit check already requires user approval for non-requested times; keep it.
- 13 Oct FOUNDER: keep the filler "actually" (he liked it; I had dropped it in draft 5 on my own). Hook line: "Ji sir, actually maine aapko {haircut aur beard trim} ki booking ke regarding call kiya hai." Fillers stay (Ji, Achha, Toh, actually). Lesson: do not remove wording he did not ask to remove; ask first.
- 13 Oct FOUNDER CLARIFICATION (use case 1, salon): "paanch minute mein call back" is only a figure of speech (what people say), NOT a timer. Friday calls the salon back ONLY AFTER the user answers (Yes/No on WhatsApp). No 5-minute deadline logic and no "abhi confirm nahi ho paya" call. Open: what if the user never answers (one WhatsApp nudge? expire the slot?). Supersedes the 5-minute implication notes above.
- 13 Oct FOUNDER GLOBAL SCRIPT RULES (apply to ALL use cases, all 6 archetypes): (1) ALWAYS add filler words (Ji, Achha, Toh, actually, ...). (2) Order of every call: first confirm the business name ("Hello, kya meri baat X se ho rahi hai?"), then ALWAYS the purpose of the call in one short line ("actually maine aapko ... ke regarding call kiya hai") = the hook. (3) Sentence ENDINGS must sound like how people really talk in Hinglish ("... rahega?", "... rahegi", "... kar dun?", "... ho jayega na?"), not stiff/formal, otherwise it sounds like AI. (He earlier asked to avoid "rahega" in ONE slot question; the new rule is about natural endings: ask him per line.) Added to docs/CALL_SCRIPTS_EDIT_HERE.md.
- 13 Oct FOUNDER WORDING RULE (all scripts): prefer everyday English words inside Hinglish over formal Hindi words (not "nazdeek": use "nearest"). Nearest-slot question: "Toh sabse nearest kaun sa slot available hoga?" Ending "hoga" is fine here.

### Task (13 Oct): founder wants a "script style model" so he does not correct every script one by one
Build: `friday/playbooks/style/` = style dictionary (his rules: word swaps, banned words, preferred fillers, call structure, natural endings, approved golden examples) + a checker/auto-fixer for every playbook line + a learn command that adds each correction he gives (before -> after) to the dictionary. Not ML training: a rules + examples file that grows with his corrections, and a drafter prompt that uses the golden examples. Output is DRAFTS only (hear-before-change still applies; nothing is promoted by the tool).
- 13 Oct FOUNDER FINAL booking close (use case 1, salon; replaces earlier closes): "Achha theek hai sir, toh kal aap {paanch baje} ka booking {Himanshu Goyal} ke naam se book kar lijiye. {Paanch baje} se pehle main ek baar confirmation ke liye call kar lungi. Thank you." (his own words: "book kar lijiye", not "kar dijiye"; I had changed that wrongly). Added as golden example in friday/playbooks/style/style.yaml. Style tool (friday/playbooks/style/) being wired: style-check / style-learn.
- 13 Oct FOUNDER: "aas paas" -> "around" ("4 baje ya 6 baje ke around"); "estimate" word is fine; generally use English words (it is natural Hinglish). Added to style.yaml swaps. Style tool done: `friday playbook style-check <name> [--pending] [--fix]` (lists issues, never edits), `friday playbook style-learn "BEFORE" "AFTER"` (adds swaps + golden example to friday/playbooks/style/learned.yaml), `StyleBook.prompt_block()` for drafting prompts. Tests: tests/playbooks/test_style.py. salon_booking live script currently shows 15 style issues (it predates his rules); apply after he approves the text + audio.
- 13 Oct FOUNDER: yes to ONE WhatsApp reminder after 30 min if the user has not answered the busy-slot question; then the slot is let go (tell the user). Founder asked for the consolidated TEXT of salon draft 15 first (review text, THEN audio). Draft 15 final text sent in chat; waiting for his review. Nothing in the playbook changed.
- 13 Oct FOUNDER, use case 1 step 4 (slot question) FINAL: "Achha theek hai sir, toh {kal paanch baje} ka slot booking ke liye aapke paas available hoga?" ("hoga" ending, "aapke paas" added). Replaces "available hai"/"mil jayega na".
- 13 Oct FOUNDER, use case 1 busy slot (restated, final): salon says the 5 baje slot is busy -> "Achha okay. Toh koi {5 baje} ke around ka slot available ho, {4 baje} ka, {6 baje} ka?" -> if nothing nearby: "Toh sabse nearest kaun sa slot available hoga?" -> she does NOT book: "Achha theek hai sir, main {Himanshu sir} se confirm karke aapko {paanch minute} mein call back karti hoon. Thank you." ("paanch minute mein" stays IN the line as everyday speech; it is not a timer: she calls back after the user answers.)
- 13 Oct FOUNDER, use case 1 PRICE-CHECK close (final): "Achha theek hai sir, main ek baar {Himanshu sir} ko bata deti hoon, aur aapko {das minute} mein ek baar booking confirmation ke liye call karti hoon." Again "das minute" is everyday speech, not a timer: the confirmation call happens after the user decides (needs a rule: if the user says book, call the salon back; if no, thank them / no call). Replaces "main {user} ko bata deti hoon. Thank you."
- 13 Oct FOUNDER RULE (use case 1, and the pattern for all): "5 / 10 minute" in a close is only a polite phrase ("thodi der mein confirm karke batati hoon"), NOT a promise of a time. Friday calls the business back ONLY when the user confirms (whenever that is, even hours later): the user's "yes" = confirmation initiation -> NEW CALL 2 to the business: "kya karna hai, booking confirm kar lijiye ab is samay ki". If the user says no / never answers: no call to the business (one WhatsApp reminder after 30 min, then let go). So salon needs a second script, "booking confirmation call" (draft in chat). Same pattern for quote_only calls of every archetype.
- 13 Oct FOUNDER APPROVED THE TEXT of salon scripts A (first call) and B (confirmation call), as pasted in chat (13 Oct). NEXT: (1) write them as PENDING playbooks (not live), validate + dry-run, (2) founder command to render the AUDIO (`friday playbook preview ... --pending`), (3) founder hears + approves audio, (4) only then promote (.approved marker). Also to build: WhatsApp busy-slot message with Haan/Nahi buttons, 30-min reminder, the confirmation-call trigger on Haan, `user_full_name` input. Then paste script 2 (quote_and_slot).
- 13 Oct BUILT (pending, not live): friday/playbooks/pending/salon_booking.yaml = approved salon script A. New flow: S0 name check -> S1 hook (purpose line, waits "haan ji bataiye") -> S3 price ("estimated") -> price-check close OR S2 slot -> busy: S2b "around" -> S2n "nearest" -> S7 close WITHOUT booking (flag alt_offered; never books a time different from the asked one). Engine/intents: new condition `alt_offered`, settable flag, placeholders `slot_time`, `user_full_name`, `user_full_spoken`. NOTE to confirm with founder: with the hook first she no longer says "virtual assistant" until asked (she still answers truthfully when asked; ARE_YOU_BOT unchanged). Next: dry run, audio, script B playbook, WhatsApp busy-slot flow + 30 min reminder.
- 13 Oct FOUNDER: wants to HEAR the pending salon script on a real call instead of a wav file. Built: `friday livecall --pending-test [--full-name "Himanshu Goyal"]` (uses the pending playbook for that one call to the allow-listed founder number only; `model.use_pending_for_test()`), and `PENDING=1 FULLNAME="Himanshu Goyal" bash deploy/call-me.sh ...`. Production never loads pending. Real call needs the founder's approval = his request "initiate a call" + he runs it on the server (the sandbox cannot place calls).
- 13 Oct FOUNDER: "let's review the other scripts". Next: script 2 of 7 = quote_and_slot (pending). I pre-apply his style rules (name, then purpose hook, fillers, natural endings, English words) and paste the whole call in chat for his review; he approves or edits; nothing promoted without audio approval.
- 13 Oct FOUNDER on script 2 (quote_and_slot): price word = "fees" for clinic (and vet, to confirm), "charges" for the others. Needs a per-category `price_word` in the pack. Still open: slot vs appointment for doctors; ask a rough range once on "aake dekhna padega"; final approval of script 2 text.
- 13 Oct FOUNDER on script 2: doctor/clinic uses "appointment" ("{kal paanch baje} ki appointment aapke paas available hogi?"), others keep "slot". Needs per-category `slot_word` in the pack (like `price_word`).
- 13 Oct FOUNDER on script 2: yes, ask a rough range ONCE when they say "aake dekhna padega". Script 2 overall approval not yet explicit. Moving to script 3 (enquiry) review.
- 13 Oct FOUNDER: "yes build the script" = approval of script 2 (quote_and_slot) text. Building pending v7 of quote_and_slot (same flow as salon v7: hook S1, estimated {price_word}, appointment wording via q_appointment, range asked once on visit needed, nearest-slot, no booking of a different time, full-name close). Script 3 (enquiry) to be pasted next.
- 13 Oct BUILT (pending, not live): friday/playbooks/pending/quote_and_slot.yaml v7 (same flow as salon v7; `price_word` fees/charges and `q_appointment` from the category pack: clinic = fees + appointment, vet = fees; range asked once on visit-needed (S3r); WHO_IS_THIS = reintro + hook, then hook only). Dry run 100%.
- 13 Oct FOUNDER QUESTION: "model that can be fine-tuned on my script changes and real business data: a model, a prompt, or a workflow?" Answer given in chat: today it is a rules-and-examples dictionary + workflow (style.yaml/learned.yaml, style-check). The only part that CAN be trained is the listening side (classifying what the vendor said); Friday's spoken words stay scripted. Plan: log real call transcripts -> founder/labeler corrects intent labels -> eval set -> prompt/few-shot tuning first, fine-tune a small model only after ~1-2k labelled vendor utterances. Needs call-recording consent policy (DPDP) before storing real data.
- 13 Oct FOUNDER DECISION: no recording-consent step with businesses ("every business operates the same way"); right now record EVERY call and keep the transcript of everything; revisit only if an issue comes up. State of the code: transcripts are written already; AUDIO recording is OFF by design in the pilot profile and in live needs an object store (FRIDAY_OBJECT_STORE_URL, settings `call_record`). I flagged once: recording without telling the vendor may conflict with DPDP/TRAI rules (legal read still on the list); the spoken `recording_notice` line ("Yeh call quality ke liye record ho sakta hai") is spoken only when recording is on, and the founder has to say keep or drop. TODO after his answer: turn recording on with an object store; make the notice line follow his decision.
- 13 Oct FOUNDER: "paste the script 3" -> pasting enquiry (script 3 of 7) draft in chat for review. Recording notice line decision still pending.
- 13 Oct FOUNDER on script 3 (enquiry), demo class line: "Achha toh sir, kuch demo class bhi mil sakti hai?" (his alternative: "...koi demo class bhi provide kar sakte hain?"). Open: fees/rate/charges for events and weddings; extra question (event date available?) for events/weddings; final approval of script 3.
- 13 Oct FOUNDER RULE (all scripts, WHATSAPP_PLEASE): never say "WhatsApp possible nahi hai". When the business says "WhatsApp pe bhej do / details bhej dete hain": Friday asks them to confirm the WhatsApp number: "Theek hai sir, ek baar aap please WhatsApp ka number confirm kar sakte hain?"; if they say "yahi number hai" or give a new number -> "Okay sir, main aapko WhatsApp kar deti hoon." Then Friday sends the business a WhatsApp TEMPLATE message (to be written + approved by Meta; business replies with the details) and the details are collected for the user. Needs: number capture from speech (digit read-back to avoid errors), `whatsapp_number` output, template send to the vendor (WhatsApp Business rules for first contact: template + opt-in?), flagged to legal read. DRAFT only, not built.
- 13 Oct FOUNDER RULE (all scripts, NEEDS_ADVANCE: the business raises an advance / booking amount): Friday asks how much: "Achha theek hai sir, ek baar advance ya booking amount kitna hoga?"; then: "Theek hai sir, main ek baar {Himanshu sir} ko bata deti hoon, wo aapko advance payment initiate kar denge. Thank you." (replaces "Advance main abhi nahi de sakti..."). Implementation notes: collect `deposit_inr` (exists for archetypes), outcome ADVANCE_ASKED/SLOT_OFFERED with the amount for the user's approval; Friday NEVER pays and the user decides, so the line "wo ... initiate kar denge" is a promise on the user's behalf: raised with founder (softer wording proposed). DRAFT only.
- 13 Oct FOUNDER on WhatsApp number capture: when they give the number Friday says "Theek hai sir, ek baar number reconfirm kar dijiye", then she SPEAKS the number back to them: "{digits} ... yahi number hai na?"; on yes -> "Okay sir, main aapko WhatsApp kar deti hoon." Needs a digits-to-speech line (digit by digit in Hindi/English, 5+5 grouping) and a yes/no check; if "yahi number" she uses the calling number (no read-back).
- 13 Oct FOUNDER: keep the ORIGINAL advance line ("wo aapko advance payment initiate kar denge"); it is normal human speech and the owner decides whether to pay. Do not raise such concerns again (founder preference: do not over-flag ordinary phrasing).
- 13 Oct FOUNDER: advance line is FINAL (original wording). Plan: review scripts 4-7 as text first, then build the global rules (WhatsApp number capture + read-back + template, advance question, recording notice decision) across all scripts in one pass. Script 3 defaults used unless he corrects: events/weddings say "charges", no extra date question.
- 13 Oct FOUNDER on script 3: events and weddings also say "charges" (so only coaching/gym/driving say "fees"). Extra "date available" question NOT answered: default none. Script 4 (home_service_visit) text pasted for review.
- 13 Oct FOUNDER on script 3 (enquiry), events + weddings: the event DATE is already fixed by the user. Order for these two categories: hook -> "Toh sir, {date} ko aap available hain?" -> if available: "Achha, toh {services} ke estimated kya charges rahenge?" -> close; if not available: close (no price needed). Needs: input `event_date` (the user's date), pack switch q_date for event_services + wedding_vendors, new step in enquiry. Batch/demo not asked for them.
- 13 Oct FOUNDER on events/weddings: businesses usually ask "event kya hai, kab hai, kahan hai". Friday must collect these 3 from the USER before calling: event type, date, venue/city (plus guest count already asked). PM plans (friday/pm/data/plans.yaml: event_services, wedding_vendors) currently ask only date + (event: guests/type). TODO: PM asks `when`, `details` (type + guests) and a NEW `where` (venue/city) for both; the enquiry playbook gets inputs event_type, event_date, event_venue and a new intent ASKS_EVENT_DETAILS answered ONLY from those facts ("{event_type}, {event_date} ko, {event_venue} mein"), never invented. Script text for this answer is pending founder approval.
- 13 Oct FOUNDER CLARIFICATION (all scripts): Friday does NOT ask about advance / booking amount upfront (conventional, finalised later once charges are within budget). She asks it ONLY if the USER says so in the request ("booking amount confirm karna hai, kitna lenge"): new input `ask_advance` (default no) + question line "Achha theek hai sir, ek baar booking amount kitna lenge?". If the VENDOR raises an advance herself, the earlier rule applies (ask how much, then "wo aapko advance payment initiate kar denge").
- 13 Oct FOUNDER: for events/weddings the VENUE NAME is also required (not only the city): PM asks "venue ka naam aur city"; answer line: "{event_type} hai, {event_date} ko, {venue name}, {city} mein."
- 13 Oct FOUNDER: parlour/makeup booking for events (esp. women): a parlour person comes TO THE VENUE / home to do makeup. Needs the same event details as events/weddings: what event, date, venue name + city, (number of people to do). Proposal sent: when the request is "makeup/parlour at my venue/home" route to the event-style flow (date availability -> charges -> answer event details) instead of the in-salon flow; PM asks `where` (salon or at venue), event type, date, venue name+city, number of people. Founder to confirm routing.
- 13 Oct FOUNDER RULE (EVERY script/bucket): when the user answers "book kar do" (Yes) after the result, Friday CALLS THE BUSINESS BACK and finalizes (booking, visit, date, table, hold ...). One generic confirmation-call script per archetype (salon version approved as script B). Needs: a user "Haan/book kar do" trigger (WhatsApp button) -> new call task `confirm_booking` with the vendor's quoted terms (price, slot) + commit under the user's fresh approval; same code-level commit checks. Generic text pasted in chat for approval.
- 13 Oct FOUNDER on script 4 (home_service_visit), PACKERS & MOVERS (and others with room to negotiate): the vendor asks "kitna saman, kitne kilo, kitne bag, kahan se kahan". PM must collect from the user before calling: items/quantity (bags/kg/rooms), from address, to address, floor/lift, date. Vendor gives an ESTIMATE -> told to the user. If the user says "thoda kam karao / negotiate": Friday CALLS BACK and negotiates inside the user's range: if the vendor's new price <= the user's target -> finalize; else push toward the user's minimum with at most 1-2 pushbacks; if the vendor will not move, RECORD the final amount and close: "main {user} se confirm karke thodi der mein call back karti hoon for the final booking". Needs: user's target + max price, pushback counter (max 2), negotiation lines (draft in chat), never exceed the user's max without a fresh user OK. Hear-before-change applies to the negotiation lines.
- 13 Oct FOUNDER on home-service confirmation call: "Theek hai sir, {Himanshu sir} ne confirm kar diya hai, main aapko WhatsApp pe final address aur location share kar deti hoon. Ek baar WhatsApp number confirm karenge?" -> they say "yahi hai" (or a new number: read-back rule) -> "Theek hai sir, main aapko WhatsApp pe final details share kar deti hoon." So the address is NEVER spoken on the call; it goes by WhatsApp (template) after the number is confirmed.
- 13 Oct FOUNDER APPROVED script 4 (home_service_visit) text incl. negotiation lines (push 1 and 2 as pasted) and the confirmation call. Push-1 target = a little BELOW the user's stated budget (~90-95%, leaves room; never above the user's max). Scripts approved so far (text): 1 salon (A+B), 2 quote_and_slot, 3 enquiry, 4 home_service_visit. Next: script 5 rental.
- 13 Oct FOUNDER on script 5 (rental): PG and cab are TWO DIFFERENT use cases (split: 5a PG, 5b cab). PG call: name check "kya meri baat is PG se ho rahi hai?" -> hook "PG ke room ki enquiry ke regarding call kiya tha" -> ask room rent -> owner asks single/double/triple sharing: answer from the USER's requirement ("single sharing") -> ask charges for that sharing -> ask what is included: furnishing, food/mess included or not, electricity bill -> owner may ask who it's for: name, where from, where works, where living now (from the user's profile/data: PM must have/collect them) -> move-in date ("1 January se, single sharing") -> final price -> close "Himanshu sir se confirm karke thodi der mein call back karti hoon". Cab script (5b) still to be dictated.
- 13 Oct FOUNDER on 5a PG, CALLBACK (second call, after the user decides): negotiation allowed: Friday states the user's budget ("Sir, hamara budget {X} ke around rahega, isme manage ho payega?") with up to TWO pushbacks; then asks to VISIT the room: "Room dekhne ke liye kab aa sakte hain?" -> confirm visit DATE and TIME -> close "Theek hai sir, dhanyavaad. Main visit se pehle ek baar call kar lungi." So for PG the final step is a scheduled VISIT (not a booking); a reminder call before the visit.
- 13 Oct FOUNDER on 5a PG first call: ALSO confirm SECURITY DEPOSIT and NOTICE PERIOD (besides rent, furnishing, food/mess, electricity). Lines: "Aur security deposit kitna rahega?" / "Aur notice period kitna rehta hai?" (to be approved).
- 13 Oct FOUNDER RULE (all scripts): VARY the acknowledgement fillers, do not say "Achha theek hai sir" every time ("okay sir", "ji sir", ...). Plan: an acknowledgement POOL in style.yaml (`ack_pool`) + a `{ack}` placeholder in lines; the engine picks one that is not among the last two used. Pool proposed in chat, needs his approval + audio. Mechanism to build after approval.
- 13 Oct FOUNDER (all scripts): say "thank you", never "dhanyavad" (swap added to style.yaml; the PG callback close uses "Thank you"). PG food question wording: "Aur usme khana ya mess include rahega?" (khana / mess included or not).
- 13 Oct FOUNDER REQUIREMENT (all scripts): (1) if the business interrupts / asks questions mid-call and Friday has answered them, she then RESUMES with the questions still unanswered (checklist), not from the start; (2) if the call drops or the owner says "abhi busy hoon", Friday calls BACK later keeping the context: the retry call carries what was already answered and does NOT repeat answered questions (asks only the missing ones, short "pehle baat hui thi" hook). Never repeat the same question again and again. Design + lines pending founder approval.
- 13 Oct FOUNDER DECISIONS retries: retry hook line approved. If the owner says "busy hoon" she ALWAYS asks "kab call kar sakti hoon?" (also at the start). If the owner cuts/does not answer: attempt 1 = the original call; retry at +1 hour; retry at +3 hours; MAX 3 attempts in a day, then drop that business and tell the USER: "Maine {Business} ko 3 baar call kiya, abhi tak unhone call nahi uthaya" (message text to be approved); a stated callback time wins over the schedule.
- 13 Oct FOUNDER: (a) "shukriya" -> "thank you" in all scripts (style swap added); (b) PG callback push 2 = a number slightly higher than push 1 but within the USER's range (never above the user's max); (c) 5a PG first call + callback APPROVED (text); (d) acknowledgement pool APPROVED, all six variants, chosen randomly as fits (not the same as the last two): "Achha theek hai sir", "Okay sir", "Ji sir", "Theek hai sir", "Achha okay sir", "Samajh gayi sir"; (e) retry policy built: no-answer retries +1 h and +3 h, busy 60 min, max 3 attempts; final message to the user "I called X n times and they still haven't picked up". Next: 5b cab.
- 13 Oct BUILT: acknowledgement pool (`intents.ACK_POOL`, `{ack}` placeholder, never one of the last two; used in the pending salon_booking + quote_and_slot), "shukriya" -> "Thank you" in those pending scripts, retry delays (+1 h, +3 h; tests updated), final "called n times" message. Push-2 negotiation rule (slightly higher than push 1, within the user's range) to be built with the negotiation call.
- 13 Oct FOUNDER on 5b cab: hook = "Ji sir, actually maine aapko cab booking ke regarding call kiya tha." then, after "haan ji bataiye", Friday VOLUNTEERS the trip: "Ji, hamko {Jaipur} se {Delhi} jana hai, {kal subah 6 baje} ki cab book karani hai, hum {4} log hain." (from the user's details), THEN asks the price/estimate. Order: hook -> trip details -> price -> car type / toll / driver charges -> availability -> close.
- 13 Oct FOUNDER on 5b cab, QUESTION ORDER (final): price "Toh sir, iska total estimated kitna charge rahega?" -> car "Aur kaun si gaadi milegi isme?" -> inclusions "Toh sir, is charge mein sab kuch include rahega na? Toll, khana-peena, driver ka khana, charges wagairah?" -> if toll (or others) NOT included: "Toh sir, estimated kitna toll lagta hai isme, kuch andaza hai?" -> availability "Toh sir, {kal} {6 baje} ke liye cab available hogi na?" -> close "Theek hai sir, main ek baar {Himanshu sir} se confirm karke aapko thodi der mein call back karti hoon. Thank you."
- 13 Oct FOUNDER on 5b cab CALLBACKS (final): NEGOTIATION call: "Toh sir, {Himanshu sir} se baat ho gayi hai, price thoda humare budget se upar hai. Humara budget {X} ka hai, toh isme bataiye kuch ho sakta hai kya?" (push 1, and push 2 once more, slightly higher within the user's range); if not agreed: "Theek hai sir, main ek baar {Himanshu sir} se final confirmation leke aapko call back karti hoon." CONFIRMATION call: "{Himanshu sir} ne final confirm kar diya hai, toh hum {price} pe final karte hain. Toh sir {kal subah 6 baje} ki booking aap {Himanshu Goyal} ke naam se kar lijiye. Main aapko WhatsApp par pickup address share kar deti hoon. Ek baar apna WhatsApp number confirm kar dijiye." (then the number read-back rule). 5b text treated as approved for BUILD as pending (audio approval still required before live).
- 13 Oct FOUNDER on script 6 (stock_and_price), electronics: do NOT say "warranty aur bill ke saath milega"; ask the warranty period instead: "Aur isme warranty kitni hogi?" (only if the user asked / for electronics).
- 13 Oct FOUNDER on script 6 (stock_and_price): FLORIST: ask "Home delivery provide karte ho kya?" first; only if they ask where, say the area ("{Vaishali Nagar} mein"). ELECTRONICS/PHONES: NO negotiation, just ask the price. CONFIRMATION call after "book kar do": "{Himanshu sir} ne confirm kar diya hai, toh ek baar aap hamare liye {item} hold kar dijiye {Himanshu} ke naam se, woh {shaam} tak aake pick kar lenge." (hold + pickup time, no negotiation). Open: offers question, approval.
- 13 Oct FOUNDER: warranty line final wording: "Aur isme warranty kitni mil jayegi?" (electronics).
- 13 Oct FOUNDER on script 6, HOLD with booking payment: when Friday asks to hold the item, the shop may ask for a booking payment. Flow: shop asks -> "Theek hai sir, booking amount kitna karna hoga?" -> shop gives the amount -> "Theek hai sir, aap apna UPI number de dijiye, main {Himanshu sir} ko bolke aapko ek baar booking amount pay kara deti hoon." (Friday only collects the shop's UPI number/id and tells the USER; the USER pays; Friday never pays). If the shop will NOT hold without payment: CALLBACK with the user's answer: "Sir, booking amount thoda issue hai, hum {shaam} tak aake ise pick kar lenge, wahin pe poora payment aapko kar denge." Needs: UPI id/number capture + read-back (same rule as the WhatsApp number), a user decision step (pay / pick up in person / drop) over WhatsApp, `payment_requested` outcome with amount + UPI for the user. Draft only.
- 13 Oct FOUNDER on script 6, EXCHANGE OFFER (only if the user asked for exchange): Friday asks the shop for the exchange offer; the shop will ask "kaun sa phone hai, kab ka hai, sab chalta hai ya nahi?" -> Friday answers ONLY from the user's old-phone details (model, year, working condition, damage) which the PM must collect from the user BEFORE calling (when the request mentions exchange); then she asks the exchange value and the final price after exchange; missing detail -> "poochh kar bataungi". Lines drafted in chat.
- 13 Oct FOUNDER on booking payment (script 6 and every hold): the USER pays the shop himself/herself, to the UPI number/ID Friday gives; Friday CONFIRMS the UPI id/number on the call (read-back). If the shop says "WhatsApp kar do, QR bhej dete hain": Friday sends the shop a WhatsApp message (template), the shop replies with the QR, Friday forwards the QR to the USER for payment; after the user has paid, Friday tells the shop payment is done (proof/screenshot: to decide). Engineering: inbound WhatsApp media from vendors (QR image) -> forward to the user; reply window (24 h) and template rules; a `payment_pending/payment_done` state per task.
- 13 Oct FOUNDER: yes, Friday also sends the payment SCREENSHOT to the vendor (the user shares it; she forwards it on WhatsApp with "Payment ho gaya hai, {user} {item} shaam tak pick kar lenge"). Script 6 flow otherwise as pasted; approval of script 6 not stated explicitly, building pending anyway (audio approval still needed). Next: script 7 (table_or_venue).
- 13 Oct FOUNDER APPROVED script 6 (stock_and_price) text incl. exchange, hold, UPI/QR payment flow, screenshot to vendor. Text approved so far: 1, 2, 3, 4, 5a, 5b, 6. LEFT: script 7 (table_or_venue). After the text review: build all approved text as pending playbooks + global rules (WhatsApp number capture/read-back, QR/UPI, negotiation calls, confirmation calls, resume/retry memory, event/PG/exchange inputs in the PM), then audio approval, then promote.
- 13 Oct FOUNDER on script 7 (table_or_venue): the request line already states the booking ("hamko {kal raat 8 baje} ke liye {4} logon ka table chahiye"), so NO separate availability question; Friday waits for the business to say "available hai / nahi hai" and reacts: available -> price; not available -> around slot, then nearest slot, no booking of a different time.
- 13 Oct FOUNDER on script 7: for RESTAURANT/CAFE TABLE bookings do NOT ask the cost (depends on what they eat); price ("per plate ka estimated kitna rahega?") only for BANQUETS. Pack switch needed: q_price off for restaurant/cafe table, on for banquet.
- 13 Oct FOUNDER: script 7 splits: TABLE booking (restaurant/cafe) / HOTEL booking is one kind of form, BANQUET is a SEPARATE form (different use case). Understood as 7a restaurant+cafe table (pasted, no price), 7b banquet (own script, per plate, capacity, min spend, event details like script 3 events), hotel room booking = to confirm with founder (own form or with the table form). Archetype table_or_venue splits into two playbooks.
- 13 Oct FOUNDER: table booking, hotel room booking and banquet booking are THREE separate use cases/forms: 7a table (pasted, no price), 7b hotel room, 7c banquet. Scripts left to review: 7b hotel, 7c banquet (+ approval of 7a). The table_or_venue archetype splits into three playbooks (table, hotel, banquet).
- 13 Oct FOUNDER: asked for THREE complete separate scripts: 7a table booking, 7b hotel room booking, 7c banquet booking. Pasted in chat (full call + callbacks + extras). Banquet extras: veg/non-veg and budget answered from the user's details; per plate rate, hall capacity, min spend/cover, decoration/DJ if the user asked.
- 13 Oct FOUNDER on 7b hotel room booking: after the request the hotel usually says "multiple options available" -> Friday: "Ek baar options bata dijiye, unka estimated price kya hoga?" ; if NO room for the dates: "Theek hai sir, thank you. Main {Himanshu sir} se alternate days ke liye confirm karke aapko call back karti hoon." (no booking, no other-date guess); if available: ask tax inclusive/exclusive and breakfast included, check-in/check-out time, cancellation policy (nice to have); if a room fits the budget: close with call back; negotiation only if the user asks (push 1, 2); then confirmation call.
- 13 Oct FOUNDER on 7c BANQUET: ask the estimated cost simply; if NOT available: "Okay sir, thank you. Main {Himanshu sir} se update karke aapko dobara call karti hoon."; ask what is included (decoration, DJ ...); if the user needs rooms: state the need and ask how many rooms are available; ask when a VISIT is possible ("visit karne hum kab aa sakte hain?") and confirm the visit date/time ("{Himanshu sir} {kal} visit karne aa jayenge"); NO NEGOTIATION for banquets (too high for an AI: it happens face to face). Banquet callback = visit confirmation only (no push 1/2).
- 13 Oct FOUNDER on 7b hotel: confirmation call needs NO WhatsApp details: just "{Himanshu sir} ne confirm kar diya hai, toh aap {dates} ka room {Himanshu Goyal} ke naam se book kar lijiye." If the hotel asks a booking amount: same pattern as the shop (ask how much; the USER pays the hotel directly); payment details can arrive as UPI number, UPI ID, QR (via WhatsApp) or BANK ACCOUNT details -> handle each: UPI number/ID spoken + read-back, QR/bank details via WhatsApp message to the hotel (hotel replies with text/image), forwarded to the user. Bank account numbers are too long/risky to read by voice: propose ask for WhatsApp.
- 13 Oct FOUNDER on bank details (all payment cases): Friday: "Theek hai sir, main aapko ek baar WhatsApp message kar deti hoon, isi number pe WhatsApp karna hai ya kuch aur?" -> confirm number (read-back rule) -> "Theek hai sir, main aapko is number pe WhatsApp kar deti hoon, aap bank details bhej dijiye, {Himanshu sir} aapko pay kar denge." If the business says they have NO WhatsApp: details on the CALL ONLY (they say account number + IFSC, Friday repeats them back in small groups to confirm; they are then passed to the user as text).
- 13 Oct FOUNDER: "just start building for everything" + wants a FULL TRAINABLE SELF-LEARNING model that keeps upgrading from customer-call feedback, accommodating questions/answers and the style users ask in. Design (honest): layered learning loop with human gate (docs/LEARNING_AND_BUILD_PLAN.md): (1) style dictionary (built), (2) listening model: every real call logs vendor utterance + predicted intent + confidence + unhandled -> review queue -> labels -> eval set -> prompt/few-shot update, later a fine-tuned small classifier, (3) answer bank: vendor questions + grounded answers from user facts, proposals generated automatically; NOTHING spoken changes without founder approval + tests (hear-before-change, safety). Build order: shared engine pieces, then pending playbooks (pg_rental, cab_booking, table_booking, hotel_booking, banquet_booking + the 5 earlier), then global rules, then learning-loop tooling.
- 13 Oct BUILD STATUS: done by lead: engine pieces (facts as inputs + has_<fact>, GIVES_NUMBER/SAME_NUMBER + {captured_spoken}, push2_price/vendor_price + price_le_target/max, resume/prior_* seeding + is_resume, modes negotiate/confirm, alt_offered, {ack}), learning tooling (friday/learning, `friday learn report|label|eval|fewshot`, engine logs every vendor utterance masked to var/learning), docs/SCRIPTS_SPEC.md (source of truth for all approved text), docs/LEARNING_AND_BUILD_PLAN.md. Running: category split + PM questions (worker); playbook workers launched next for all 10 forms.
- 13 Oct BUILT + PUSHED: category split (22 categories: restaurant_table, hotel_stay, banquet_hall), archetypes pg_rental/cab_booking/table_booking/hotel_booking/banquet_booking in ARCHETYPES (playbooks not written yet), PM fact questions (friday/pm/factslots.py), facts -> brief constraints -> playbook inputs (select.py), engine pieces, learning tooling. The 5 playbook workers hit the account's session limit before writing anything: pending playbooks still need the v7 rewrite for enquiry, home_service_visit, stock_and_price + NEW pg_rental, cab_booking, table_booking, hotel_booking, banquet_booking, and confirm/negotiate/resume modes on salon + quote_and_slot (spec: docs/SCRIPTS_SPEC.md, brief: scratchpad playbook_brief.md).
- 13 Oct FOUNDER asked again for the product-manager agent's competitor outcome: summarised from docs/COMPETITORS.md (players, threats, copy/avoid lessons, 5 decisions, research gaps). Open: decisions 1-5 in section B7 still unanswered; research gaps (reviews, primary sources, Puch AI hands-on test) still open.
- 13 Oct FOUNDER PRINCIPLES (new): (1) user data trains/personalises ONLY for that user, never cross-user (no shared learning from one user's private facts); (2) Friday is a PERSONAL ASSISTANT that acts for the user ("Instinct"-style), NOT a generic ask-anything chatbot like Puch AI: out-of-scope questions get a polite redirect + wishlist; (3) founder asked for the FULL FEATURE LIST: written in docs/FEATURES.md (status: built / pending approval / planned / decision needed). Learning-loop note: shared learning uses only anonymised, de-personalised vendor-side utterances (what businesses say), never user facts.
- 13 Oct FOUNDER DECISIONS: (1) she says "virtual assistant" ONLY when asked, never up front (current scripts already do this); (2) recordings ARE stored but NEVER announced on the call: the spoken recording notice is removed (engine: condition `recording` is always false). Recording storage bucket still to set up.
- 13 Oct BUILT (pending, not live): ALL 10 pending playbooks exist and validate + dry-run 100%: salon_booking, quote_and_slot, enquiry, home_service_visit, pg_rental, cab_booking, stock_and_price, table_booking, hotel_booking, banquet_booking (+ personas + tests/playbooks/test_<id>_script.py). Engine additions this round: lakh/crore prices (ceiling 5,000,000), placeholders with digits ({push2_price}), prior_* inputs kept raw, push-2 rounding, validator exemptions (number confirm, ne confirm kar diya, final confirmation, "UPI number/id"), heard WhatsApp numbers may be read back (safety.allow_spoken_number), "book karana hai" is a request not a commitment, price-free table commit (delegation_slot_only), recording notice never spoken, dry-run callback modes. GLUE LINES the founder has NOT approved yet (workers added; listed in their reports, to be shown in the audio review): resume hooks, busy close ("main tab call kar leti hoon"), wa_decline ("abhi WhatsApp possible nahi hai" CONTRADICTS his rule: never say it, must be replaced), neg_final_ask, extras_ask, est_ask_again, occupant/exchange answer lines, payment-in-call lines, cab confirm order (WhatsApp ask before the commit line). KNOWN GAPS: heuristic misses (free-text answers, 'no WhatsApp' intent, 60000+ prices w/o rupaye), callback time not stored for the retry scheduler, no condition for prior notes on retry (batch/demo/warranty re-asked), payment details on the call (account/IFSC) not capturable, commit line cannot be followed by number capture.
- 13 Oct FOUNDER: "let's proceed with everything discussed above. I have already approved it and now let's build the system." => next build phase: (1) callback tasks wired end to end (negotiate / confirm / retry-with-context) incl. WhatsApp buttons, stored callback time, retry skipping of noted steps; (2) audio-review kit for all scripts (promote only with his .approved marker: never created by me); (3) recording storage, vendor-side package, user memory/delete, proactive wiring; (4) honest status after each step.
- 13 Oct FOUNDER: added the Supabase MCP to the server; asked: create a Supabase organization called "Friday" and start deploying the DBs there. Plan: list organizations/projects (read-only), check whether the MCP can create an organization (tool list has none: orgs may need the dashboard), create the project in the right org (region Mumbai ap-south-1) only after confirming cost, then apply the schema as migrations (alembic models -> SQL), never print keys; DB URL goes into the server .env by the founder (never committed).
- 13 Oct SUPABASE: the MCP sees ONE org ("pmpmjobs", free plan) with 8 old paused projects; it has NO create-organization tool, so the founder must create org "Friday" in the dashboard (https://supabase.com/dashboard/new). NOTHING was created in Supabase yet. Prepared: deploy/supabase/schema.sql (Postgres DDL of all Alembic migrations, 92 CREATE TABLE incl. partitions; regenerate with `uv run python -m friday.db.regen_supabase_sql`; alembic env.py now supports `--sql` offline mode), rls.sql (RLS on all 39 tables, no policies, so the public Data API reads nothing), set-database-url.sh (hidden password prompt -> FRIDAY_DATABASE_URL in /opt/friday/.env), README.md. NEXT once the org exists: create project friday-prod (ap-south-1), apply schema.sql + rls.sql via MCP, run get_advisors (security), then the founder runs set-database-url.sh on the server.
- 13 Oct FOUNDER: created org "Friday" (and a project) in Supabase; asked me to do the rest: find the org/project, create/confirm project in ap-south-1 if missing, apply deploy/supabase/schema.sql + rls.sql via the MCP, run security advisors, give the founder the one server command (set-database-url.sh).
- 13 Oct SUPABASE STATUS: the MCP still lists ONLY org "pmpmjobs" (checked twice): the connector was authorised before the Friday org existed, so it cannot see it; nothing created in pmpmjobs. Two paths given to the founder: (A) reconnect the Supabase connector and tick the Friday org, then I apply schema.sql/rls.sql via MCP; (B) server path with no MCP: set-database-url.sh then `python -m friday.db.migrate up` and `... migrate rls` (new command, enables RLS on every table).
- 13 Oct FOUNDER: "you take care of the complete Supabase, I don't know anything about it." Third check: the MCP still lists only org pmpmjobs, so the new Friday org is not authorised for this connector; the ONLY thing needed from the founder is to reconnect the Supabase connector and tick the Friday org. Everything else (project, schema, RLS, advisors, server connection command) is mine.
- 13 Oct SUPABASE DONE (MCP re-authorised): org "Friday" id ibmbiecfqsdssraxotkp, project zxbiapcppbfnctndmnab (ap-southeast-1 Singapore, PG17, free plan; creating a Mumbai project failed: free-project limit of the account). Applied: extension http (temporary), schema 0001-0005 (verified by md5 of the repo file; 88 tables incl. partitions, alembic_version=0005_quote_conversations), RLS ON for all 88 tables, security advisors: only INFO "RLS enabled, no policies" (intended). `drop extension http` hangs through the SQL API: disable it in the dashboard. Server connection: deploy/supabase/set-database-url.sh (tries direct + aws-0/aws-1 pooler, hidden password prompt). NEXT: founder resets the DB password in the dashboard, runs the script + restart; later Pro plan + Mumbai.
- 13 Oct FIX: set-database-url.sh failed on the server ("failed to create /root/.cache/uv": sudo -E kept HOME=/root); now runs `sudo -E -u friday env HOME=/home/friday uv run ...`. Founder must pull and rerun, re-entering the DB password (reset in dashboard: Database > Settings, new Supabase layout; Project Settings has no DB password).
- 13 Oct FOUNDER: "Analyse ghost.ai as well and see what can we take from it": product-manager agent launched to identify which product "ghost.ai" is (several share the name), research it (features, pricing, channel, India angle, reviews) and append "Update 2026-10-13 (c): ghost.ai" to docs/COMPETITORS.md with what Friday can take / avoid. Also pending: founder to re-run set-database-url.sh after pulling the HOME fix.
- 13 Oct ghost.ai ANALYSIS DONE (docs/COMPETITORS.md "Update 2026-10-13 (c)"): ghost.ai = Ghost (SF), Core = $3,499 screenless local "personal AI computer", $11M seed a16z (2026-10-05), ships late Oct; no calling/WhatsApp/India; threat LOW. Takeaways: privacy promise ("used only for you", never "never leaves"), "what do you remember / delete", visible autonomy setting (ask first / book within Rs X / never pay), every nudge says why in one clause, stay on "Friday phones the shops for you" (don't chase memory-across-everything or hardware). Asked founder to confirm he meant ghost.ai (Ghosty and HateToCall are other products; HateToCall may be a real outbound-calling competitor: look at next run). Not yet done: privacy promise copy + "what Friday never does" list for his approval.
- 13 Oct FOUNDER: "If we avoid hardware for now but keep the features": decision = NO hardware; take the software versions of Ghost's features. Added a "Ghost-inspired, software only" section to docs/FEATURES.md (privacy promise, what-you-remember/delete, autonomy dial, nudge reasons, credential firewall, always-on background agents, per-user memory from Gmail/calendar/files in Phase 2, health/smart-home out of scope). Awaiting founder's pick for the beta.

## Task note (2026-10-13): analyse typesafe ai
Founder asked: "Analyse typesafe ai as well". Product-manager agent launched to identify the product
and append "Update 2026-10-13 (d): typesafe ai" to docs/COMPETITORS.md.

## Decision note (2026-10-14): differentiators
Founder: big companies already build AI assistants, so Friday must find differentiators. Writing
docs/DIFFERENTIATORS.md (proposal, founder to choose).

## Task note (2026-10-14): moat and fundability
Founder asked: what more can we add, like why Ghost and Instinct will survive and get funding.
Adding a "moat and fundability" section to docs/DIFFERENTIATORS.md (proposal, founder to choose).

## Decision note (2026-10-14): founder wants a wider beta
Founder: beta should also include food and grocery comparison and ordering, bill payments and basic
connectors; otherwise Friday will struggle to survive and onboarding will be hard. This widens the
earlier "Phase 1 = vendor calling only" decision and touches "Friday never pays". Proposal written in
docs/BETA_SCOPE_PROPOSAL.md; awaiting founder choices on payment model and which apps first.

## Decision note (2026-10-14): customers need wow beyond calls
Founder clarified ("Cx" = customers): customers will not adopt Friday for calls alone; the beta needs a
wow factor too. Added a wow section to docs/BETA_SCOPE_PROPOSAL.md; founder to pick the wow features.

## Decision note (2026-10-14): positioning = the unbiased assistant
Founder: credit card apps, card recommendations, insurance and many other categories each sit on
multiple platforms with different prices and sales pitches. Friday should be free of all of that:
neutral, no sales pitch. Added to docs/DIFFERENTIATORS.md; legal limits noted (insurance, finance).

## Decision note (2026-10-14): the savings engine
Founder: Friday knows the user, so for every purchase it should say which of the user's cards to use
for maximum savings and which app to buy each grocery item from; "and everything". Designed in
docs/BETA_SCOPE_PROPOSAL.md (savings engine). Never store card numbers; card names only.

## Decision note (2026-10-14): future device connection and family care
Founder: in future connect a device with the agent too: reminders to people, taking care of parents,
and more. Not for now (no-hardware decision stands). Recorded as a roadmap item in
docs/FEATURES.md section 13; design for it now (consent, per-person data) so it is not rebuilt later.

## Question (2026-10-14): on-device model like Ghost
Founder asked whether we can add a model on the user's device like Ghost. Answer given: possible later
as a phone app for sensitive parts only; not for the beta (WhatsApp and calls run in the cloud).
Recorded in docs/FEATURES.md section 13.

## Question (2026-10-14): do Zepto, Blinkit, Instamart have MCP?
Founder asked. Researching with web search; result to be added to docs/COMPETITORS.md if confirmed.

## Question (2026-10-14): do cab and hotel booking have MCP or APIs?
Founder asked. Researching Ola, Uber, Rapido, MakeMyTrip, Booking.com, etc. Result goes to docs/COMPETITORS.md.

## Decision note (2026-10-14): Friday will charge businesses for bookings
Founder: "We will charge business for booking definitely." This changes the earlier suggestion of
user-only revenue. Guardrails written in docs/DIFFERENTIATORS.md so the neutral, no-sales-pitch promise
survives (fee never changes ranking, disclosed, flat). Open: fee model, which categories, legal read.

## Question (2026-10-14): electricity and gas bill APIs
Founder asked. Researching BBPS and aggregators (Bharat Connect, Setu, Razorpay, etc.). Result goes to docs/BETA_SCOPE_PROPOSAL.md.

## Question (2026-10-14): what do Instinct and Muse provide?
Founder asked; answered from docs/COMPETITORS.md (B2, B3).

## Task note (2026-10-14): Google Suite connector in Friday
Founder asked: can we add the Google Suite (Gmail, Calendar, Drive) connector now. Checking what exists
in the code and the Google verification requirements; plan goes to docs/BETA_SCOPE_PROPOSAL.md.

## Question (2026-10-14): how to do Muse-style email, one-time cards, bank connection, subscriptions in Friday
Founder asked how Friday can do what Muse does (email/calendar, one-time cards, bank connections for
expenses and cancelling subscriptions, phone calls). Researching India equivalents: Account Aggregator,
UPI Circle/AutoPay, virtual cards. Plan goes to docs/BETA_SCOPE_PROPOSAL.md.

## Question (2026-10-14): can Friday use the Google MCP like Claude does?
Answered: Claude's Gmail/Drive connectors are tied to the founder's own Claude account and cannot serve
Friday's users. Friday needs its own per-user Google OAuth (MCP or direct API, same Google verification).

## Clarification (2026-10-14): users authorize their own Gmail
Founder: each user will authorize their own Gmail when asked to connect the app. Confirmed: this is the
per-user OAuth flow in docs/BETA_SCOPE_PROPOSAL.md; the Gmail restricted-scope review still applies
before public launch (testing mode with named testers until then).

## Task note (2026-10-16): life admin scope and state report
Founder: "Need this as well" (Instinct-style life admin: books travel and restaurants, buys groceries and
tickets, cancels subscriptions, sends email, builds shareable comparison pages) and asked for the current
state of Friday and everything done to date. Writing docs/STATE_OF_FRIDAY.md.

## Question (2026-10-16): ElevenLabs viral Instagram ad (HR with a device calling candidates)
Founder asked whether the ad can be fetched. Searching the web; Instagram video itself is not viewable.

## Decision note (2026-10-16): Jarvis feel (always-on, one shared context)
Founder: Friday still feels like call/WhatsApp-to-get-a-result, not Jarvis/Siri. Wants an always-available
agent that knows what is happening in the user's day (example: interview at 2, Friday asks "how did it go?"
at 3; if the user calls at 2:30 Friday already knows and answers in context), ideally also on a device 24x7.
Design written in docs/JARVIS_FEEL.md. Hardware stays later; the feel comes from shared context + proactive
timing + presence.

## Decision note (2026-10-16): voice-first on the user's phone (Siri / OK Google style)
Founder: not follow-ups; wants Friday to work like Siri/OK Google/Alexa, using the phone as the device,
the user speaks ("Friday, aaj haircut book kar do") and talks by voice, not messages. Plan: Friday phone app
(Android first) + web voice, reusing the Sarvam voice stack; iOS via Siri shortcuts. Written in
docs/JARVIS_FEEL.md section 6. Platform rules from knowledge, to verify.

## Decision note (2026-10-16): iPhone-first voice, Friday must also speak first
Founder: major users will be iPhone users; not "Hey Siri" only; Friday should be active and be able to start
the conversation, voice-first. iOS cannot do always-on background mic or replace Siri; workaround = layered
reach (Friday speaks first by call/WhatsApp call/VoIP call screen/voice note/Live Activity; user speaks by
Siri shortcut, Action Button, widget, AirPods, voice-session mode). Written in docs/JARVIS_FEEL.md section 7.
Platform rules are from general knowledge, verify. India note: Android is the large majority of phones; plan both.

## Decision note (2026-10-16): divert the user's incoming calls to Friday (call screening / receptionist)
Founder: when a call comes to the user, the user should be able to divert it to Friday. Plan in
docs/JARVIS_FEEL.md section 8: carrier call forwarding (conditional: busy/no answer/unreachable, or unconditional
for a protected event) to a Friday number; Friday answers as the user's assistant, takes a message,
sends a summary on WhatsApp, rings the user for urgent. Needs per-user forwarding numbers or reliable
original-number info; new receptionist playbook needs founder-approved lines; legal read. Carrier details from
general knowledge, to verify.

## Decision question (2026-10-16): hardware product like ghost.ai?
Founder asked whether to plan a ghost.ai-style product: small hardware, own GPU, own model, training on the
user's device. Recommendation given: not now (earlier no-hardware decision stands); software + phone app first;
per-user personalisation in the cloud (memory/retrieval, later small per-user adapters) instead of on-device
training; revisit a thin-client device or home box only after triggers (active users, demand, funding).
Recorded in docs/FEATURES.md section 13c.

## Question (2026-10-16): how does Meta Muse operate?
Answered from docs/COMPETITORS.md B3 (secondary sources, unverified).

## Task note (2026-10-16): deep research on Meta Muse architecture
Founder asked for a fresh search on how Muse works under the hood. product-manager agent launched; it appends
"Update 2026-10-16 (g): Muse architecture" to docs/COMPETITORS.md.

## Decision question (2026-10-17): browser agent like Instinct (cab, food, movie, hotel via private browser)
Founder's hands-on with Instinct: it books cab/food/movie/hotel through a private web browser, asks the user for
credentials (OTP, email), and at payment asks for a UPI ID (collect), a saved card in a vault, or shows a QR
screenshot. Founder asks: can we build it? Answer: yes technically, but build the safer shape: Friday searches,
compares and fills the cart in a private cloud browser; the user does login OTP and the payment themselves
(takeover view / UPI intent / QR); never relay OTP through chat or the model; official MCP/APIs first, deep links
second, browser last. Plan in docs/BROWSER_AGENT_PLAN.md. Standing rule kept: Friday never sees OTP/PIN/card.

## Clarification (2026-10-17): login OTP only, payment by QR to the user's own UPI app
Founder: not asking for payment OTP; only the login OTP for the user's Uber/Zomato account. Payment: send a QR to
the user who pays from PhonePe/other PSP app. Accepted shape: login via secure one-time field or takeover, session
kept encrypted and revocable; the model never sees the OTP; payment OTP/PIN/card never touched. Recorded in
docs/BROWSER_AGENT_PLAN.md (clarification section).

## Decision (2026-10-17): start with the browser, wrapped as internal MCP servers per site/use case
Founder: start with the browser; many platforms will ship official MCPs later and we will integrate those then.
Meanwhile build an INTERNAL MCP per website per use case that drives the browser, so Friday only ever calls typed
tools and the backend (browser now, official MCP/API later) can be swapped. Design in docs/BROWSER_AGENT_PLAN.md
section "Internal MCP connectors".

## Task (2026-10-17): first browser use case = order Domino's pizza via Zomato (build + test)
Founder: "Let's build a simple use case. Order pizza from Domino's from Zomato. Take care. Let's do the testing."
Plan: connector contract + registry (friday/connectors), fake Zomato test site, Zomato food connector (public
steps first: search Domino's, read menu/prices; login via secure OTP page; cart build; stop at pay -> QR/handoff),
action gate, tests. Real login/order only with the founder's explicit go-ahead and his own OTP; no secrets in git.

## Done (2026-10-17): connectors foundation + fake-site pizza flow (pushed)
friday/connectors (contract, registry, action gate, scrub, one-time OTP channel, browser port + Playwright, fake site,
Zomato food connector with selectors in 3 dicts, pizza flow, step recorder, watch pages with expiring tokens,
`friday connectors list|demo-pizza --fake [--watch] [--out]`). Tests: 37 connector tests; full suite 2531 passed.
NOT verified: real Zomato pages/login/checkout/QR, anti-bot behaviour from cloud IPs (this sandbox cannot load
zomato/swiggy in Chromium), secure OTP page, session encryption. Default registry has Zomato scripted_browser OFF.
NEXT: run on the founder's server with a headed Chromium in a virtual screen, founder-supervised, stop before any order.

## Task (2026-10-17): start the real Zomato test (founder-supervised)
Founder: "Let's start with the Zomato. Use my same number which you used for calling me here." Rules: the number is the
founder's allow-listed number from the SERVER env (never read/printed/committed; Claude has no copy). First run is
EXPLORE mode on the founder's server: headed Chromium in a virtual screen, watch page for the founder, he types his own
login OTP on the secure one-time page, stops before any order; screenshots/trace used to tune selectors.

## Done (2026-10-17): Zomato explore run built (fake site only), pushed
`friday connectors zomato-explore` + secure OTP page + pack-run + deploy/zomato-explore.sh + docs/ZOMATO_EXPLORE.md.
72 connector tests; full suite 2566 passed. NEVER run against real zomato.com yet; all real-site locators are guesses.
NEXT: founder runs `sudo bash /opt/friday/deploy/zomato-explore.sh` on the server (his number from
FRIDAY_PILOT_ALLOWED_NUMBERS), types his own OTP on the code page, sends back the pack-run zip; Claude tunes selectors.

## Decision (2026-10-17): founder approved the /explore HTTPS route for the Zomato explore run
`deploy/explore-https.sh` adds Caddy `handle_path /explore/*` -> 127.0.0.1:8765 (token-protected pages; `--off` removes it).
Founder is on an iPad and runs commands in the DigitalOcean web console inside tmux. Open: his phone number appears in
several committed files of the public repo (old); founder to decide redaction / making the repo private.

## Done (2026-10-17): `--probe` mode + first real-site observation
Added `friday connectors zomato-explore --probe` (no login/number/OTP). Sandbox probe: zomato.com home loaded (HTTP 200) but is an
"Order on app" promo page with no search box; city/restaurant pages reset the connection (ERR_HTTP2_PROTOCOL_ERROR);
swiggy.com returned a challenge. Open question: does Zomato's WEBSITE allow ordering at all (it pushes the app)? If not, the
Zomato web connector is pointless and food goes via Swiggy MCP/Zepto/deep links. Founder to run the probe on the server.

## Task note (2026-10-17): how Muse and Instinct place orders on platforms
Founder asked the product-manager agent to research in detail how Muse and Instinct place orders (browser agent vs
APIs/MCP vs deals; login, anti-bot, payment handling). Result: "Update 2026-10-17 (h)" in docs/COMPETITORS.md.

## Done (2026-10-17): research on how Muse/Instinct place orders (COMPETITORS.md update (h))
Neither publishes how; Instinct = cloud machine + stored logins ("Vault") + browser, Stripe Link one-time cards, Shopify checkout;
Muse = per-user Secure VM with Chromium where no API, Sentinel gate, Stripe Link; Amazon blocked Muse 2026-09-20. India: Swiggy
official MCP (4 servers/66 tools), Zomato has an internal MCP ordering system not in products; Razorpay+NPCI agentic UPI
(UPI Reserve Pay, pilot, Zomato/Swiggy/Zepto launch merchants). Recommendation: official MCP first, browser fallback from an
Indian/residential route or the user's device, calls + deep links for the rest, exact-amount approval per purchase.

## Done (2026-10-17): `--login-page` mode (zomato.com/login only)
Founder: use zomato.com/login for testing. Sandbox: /login is cut off (ERR_HTTP2_PROTOCOL_ERROR) like the other pages. Added
`zomato-explore --login-page` (open /login, number masked, founder's own code via the secure page, stop). 74 connector tests pass.
Founder to run it on the server (needs the /explore HTTPS route for the code page).

## Question (2026-10-17): how can we read the user's SMS?
Answered: no blanket SMS reading. Android: SMS User Consent API (user taps to share one message) in a future app;
READ_SMS is restricted by Google Play. iPhone: no SMS access for apps; the secure code page already uses
autocomplete="one-time-code" so Safari suggests the code from the Messages SMS; Shortcuts automation is opt-in only.
Bills: forward / Gmail. Recorded in docs/BROWSER_AGENT_PLAN.md. Platform rules from general knowledge, verify.

## Question (2026-10-17): how do grocery/quick-commerce price comparison sites work?
Founder noticed many comparison sites (Blinkit/Zepto/Instamart etc.). Searching how they get prices; result goes to docs/BETA_SCOPE_PROPOSAL.md.

## Question (2026-10-19): the key five things to build in the beta for high adoption
Answered with a recommendation, recorded in docs/BETA_SCOPE_PROPOSAL.md ("Beta: the five things"). Zomato login test still waiting on the
founder's choice about giving the login code in chat (option 1/2/3 in the last answer).

## Decision (2026-10-19): build the CONSUMER calling agent + savings engine + day memory; list every problem first
Founder: build a complete calling agent for the customer: the user can ask Friday to call ANYONE (not only businesses); plus a complete
savings engine and "remembers the whole day". Before building: list every problem as multiple points, then decide how to build each.
Reason: all voice work so far is for the business use case; now the consumer use case. Problem list: docs/CONSUMER_PROBLEMS.md.

## Decision (2026-10-19): Gmail + Calendar are core; ordering parked
Founder: for Friday to know the user, Gmail, Calendar and the rest should be connected; keep ORDERING (browser/Zomato etc.) parked for now,
build everything else. Implication: Google connector (Calendar + Gmail read) moves into the beta using Google's testing mode with named
testers (about 100, to verify) while verification / the Gmail security assessment starts in parallel. The Zomato login test is paused.
Browser connector code stays in the repo, off by default.

## Task (2026-10-19): problem list as an approval artifact, prioritised; start building the decided parts meanwhile
Founder: put the ~120 problems in an artifact with approve options (he reads them over time), priorities from my view, and start working
meanwhile. Plan: artifact with per-problem decision (Must for beta / Later / Never / Needs discussion) + comment, state saved so Claude can
read it; builder starts on what is already decided (Google connector with per-user OAuth + Calendar, life-state store).

## Question (2026-10-19): link the user's Facebook, LinkedIn, Instagram, X accounts to know the user better
Answered: technically possible via each platform's login, but the APIs give little (Meta, LinkedIn restricted; X paid), users resist, DPDP purpose limits,
low value vs Gmail/Calendar. Recommendation: LATER; at most optional LinkedIn for professional context. Added as problem D13 in the register.
Note: the register has 95 problems (earlier said ~120).

## Done (2026-10-19): problem register artifact published
https://claude.ai/artifact/UXSu1w778JegYvANQXS5PC (95 problems: 56 priority 1, 28 priority 2, 11 priority 3). Founder's choices are saved in the
artifact db collection `decisions` (doc id = problem id with "." -> "-", fields decision: must|soon|later|never|discuss, note); read with ArtifactData.
Meanwhile building (already decided by the founder): Google connector with per-user OAuth + Calendar + Gmail read (fakes only until the founder creates the Google Cloud project).

## Done (2026-10-19): Google connector foundation built against a fake Google, pushed
friday/google (oauth with PKCE + signed single-use state, encrypted per-user tokens, Calendar read/write/clash/idempotent create, Gmail narrow
read-only search behind FRIDAY_GOOGLE_GMAIL_ENABLED=false, router /google, migration 0006, DataPurger covers it). 105 tests; full suite 2673 passed.
Unverified: real Google; Testing-mode tester limit and 7-day refresh-token expiry (testers hit needs_reconnect weekly); Gmail CASA before public launch;
migration/RLS not applied to live Supabase. Founder to: create the Google Cloud project per docs/GOOGLE_CONNECTOR.md, approve friday/google/consent_copy.py,
decide who calls the routes (admin bearer now), Gmail switch for testers, confirm redirect URI https://64-227-183-183.sslip.io/google/callback (assumed).
Note: the server (droplet) may no longer exist ("I do not have any server right now"): the redirect URI and hosting need re-deciding.

## Decision (2026-10-19): proceed with Claude's priority-1 problems + the founder's own Musts
Founder: "the priority one which you have mentioned, let's proceed with that." The register (artifact UXSu1w778JegYvANQXS5PC) already shows his explicit
choices: A1.1-A1.8 = Must (so calls to service providers, customer care, family/friends, officials, unknown persons, group calls and call-backs are all in scope,
beyond my priority 1). Design and build plan: docs/CONSUMER_BETA_DESIGN.md. Builders run in separate git worktrees (W1 call brief+safety, W2 live call engine,
W3 savings engine, W4 life state+proactive). Open decision flagged for the founder: how free-form personal calls may be (A3.1).

## Done (2026-10-19): four consumer workstreams merged and pushed (full suite 4678 passed)
W1 friday/calls (brief, gate, DNC, approval, retries, reports, recordings; migration 0007; docs/CALLS_W1.md, docs/LEGAL_MAP.md),
W2 friday/liveagent (moves, 297 PENDING lines, callee intents, slot guards, IVR/voicemail, 37 personas x 3 languages simulated 111/111; docs/LIVE_AGENT.md),
W3 friday/savings (wallet by card name, rules table with only EXAMPLE rows, calculator, bills + reminders, ledger; migration 0008; docs/SAVINGS_ENGINE.md),
W4 friday/lifestate (events, capture, Hinglish dates, now status, follow-ups, morning brief, memory controls; migration 0009; docs/LIFE_STATE.md).
Migration chain 0006 -> 0007_consumer_calls -> 0008_savings_engine -> 0009_life_state; supabase schema regenerated; NOT applied to the live DB.
NOT wired: front door, task-engine adapter for calls, W1<->W2 model unification (adapter), proactive tick, notifier, button dispatch. NEXT: an integration builder.
All new user-facing/spoken text is PENDING_FOUNDER_APPROVAL (calls/copy.py, liveagent/lines.py, savings/copy.py, lifestate/copy.py, google/consent_copy.py).
Founder decisions collected from the builders are listed in docs/CONSUMER_DECISIONS.md.

## Question (2026-10-19): what are the final functionalities Friday has?
Answered from the merged code; summary written to docs/STATE_OF_FRIDAY.md (updated). Integration builder (W5) still running.

## Decision (2026-10-19): incoming-call receptionist is IN scope (forward to Friday, take message, summarise, flag urgent)
Founder: when the user allows, their incoming calls forward to Friday; Friday takes the message, summarises it, shares it with the user and flags anything urgent.
Added as problem group E (E1-E15) to docs/CONSUMER_PROBLEMS.md and to the register artifact; design starts in docs/JARVIS_FEEL.md section 8. Build as workstream W6 after W5 lands.

## Decision (2026-10-19): NO per-user forwarding numbers (cost too high) for the receptionist
Founder: a number per user is too expensive. Plan: ONE shared inbound number (or a very small pool); identify the user from the carrier's redirecting/original-called number
(SIP Diversion / History-Info / provider "forwarded from" field) -- to be verified with a test using the founder's own phone; fallback: ask the caller "kisse baat karni hai?" with
name matching on a small pool, or a paid tier with a dedicated number. Recorded in docs/JARVIS_FEEL.md section 8.

## Question (2026-10-19): one-click way to forward calls to Friday
Answered: near one-tap: WhatsApp button -> Friday setup page -> carrier choice -> tap-to-dial link with the carrier's forwarding code; user presses call once; Friday verifies with a test call.
Android app could send the code in one tap later; iPhone: tel: link then Settings fallback. Codes/behaviour from general knowledge, to verify per carrier. Recorded in docs/JARVIS_FEEL.md 8c.

## Decision (2026-10-19): Friday as the user's voicemail (conditional forwarding), not all calls
Founder: not all calls forwarded; Friday should handle only unanswered calls, spam, etc. Design: carrier CONDITIONAL forwarding (no answer, busy, unreachable) to the shared Friday number
is exactly how voicemail works, so Friday replaces voicemail; optional temporary all-calls mode for protected events; spam handled after the ring (Friday ends it politely, flags, suggests
blocking) and by phone settings (iPhone Silence Unknown Callers routes unknown callers to voicemail; verify). Recorded in docs/JARVIS_FEEL.md 8d.

## Decision (2026-10-19): the consumer voice agent must cover every use case ("complete" before publishing)
Founder: a voice agent for consumers should cover every use case so it can be published as a complete voice agent. Created docs/VOICE_AGENT_COVERAGE.md (use-case matrix by direction: user talks to Friday,
Friday calls others, Friday receives calls, Friday calls the user, assist during the user's own call), status per use case, gaps, and the release criteria for "complete".

## Decision (2026-10-19): founder AGREES the proposed launch set for the consumer voice agent
Launch set: A1, A2, B1-B8, C1, C3, C4, C5, C6, C7, D1, D2, D4 (docs/VOICE_AGENT_COVERAGE.md). Founder asked for the full feature list: rewritten docs/FEATURES.md (v2, 19 Oct 2026).

## Decision (2026-10-19): hold-fighting for customer care (B3) and reminder calls to others (B10) join the LAUNCH set
Founder: include both in this phase. Added problem group F (F1-F16) to docs/CONSUMER_PROBLEMS.md and the register artifact; launch set in docs/VOICE_AGENT_COVERAGE.md and docs/FEATURES.md updated. Build as workstream W7 after W5 (integration) and W6 (receptionist).

## Question (2026-10-19): how to connect LinkedIn, Instagram, X, Facebook accounts of the user
Answered with concrete routes (general knowledge, verify current API terms and prices): OAuth sign-in gives little (LinkedIn name/email; Facebook public profile/email; Instagram API business/creator only; X paid tiers);
practical route = user uploads each platform's "download your data" export, parsed with consent into a few derived facts; skip API integrations until value is proven. Problem D13 stays priority 3 in the register. Recorded in docs/BETA_SCOPE_PROPOSAL.md.

## Decision (2026-10-19): NO social account integration (LinkedIn, Facebook, Instagram, X)
Founder: avoid account integration. Register problem D13 marked Never (written to the artifact db on the founder's instruction). Not built, not planned; only Google (Calendar, Gmail read-only) connects.

## Done (2026-10-19): W5 integration merged and pushed (full suite 4807 passed)
friday/integration: bridge W1<->W2, QueueTaskPort (consumer.call job, retries, periodic jobs in Runtime), router hooked into InboundPipeline before the quotes flow, button registry
(callap/callact/led/bill/life), proactive registration (bill reminders, life follow-ups, morning brief), `friday consumer demo`, docs/CONSUMER_INTEGRATION.md.
Four switches default OFF: FRIDAY_CONSUMER_CALLS_ENABLED, FRIDAY_SAVINGS_ENABLED, FRIDAY_LIFESTATE_ENABLED, FRIDAY_GOOGLE_ENABLED. Production telephony factory refuses consumer calls (no TelephonyFactory yet = nothing can dial).
NEXT workstreams (launch set): W6 receptionist/voicemail (inbound), W7 hold-fighting + reminder calls, W8 voice channels (call Friday's number, voice notes, voice nudges), plus a TelephonyFactory for consumer calls.
Open founder decisions from W5 added to docs/CONSUMER_DECISIONS.md (items 19-26).

## Question (2026-10-19): do AI calls have signatures that identify them as AI?
Answered from general knowledge (verify): no standard telephony marker; detection is by behaviour (latency, no backchannels, uniform prosody), call patterns (volume, short calls, caller ID reputation) and
audio deepfake detectors; we never hide it: fixed disclosure, truthful "are you AI?", dedicated caller ID, optional verified business profile (Truecaller) naming Friday as an assistant.

## Decision (2026-10-19): build ONE slice at a time, finish it 100% before the next
Founder: stop building many things in parallel; complete each to 100% and then move on. Agreed. Board with slices and a definition of done: docs/BUILD_BOARD.md. Order: 0 foundation (server, DB, WhatsApp), 1 call someone for me end to end,
2 voicemail/receptionist, 3 hold-fighting + reminder calls, 4 voice channels, 5 savings with real rules, 6 your day + Google. No new parallel builders.

## Task (2026-10-19): Slice 0 foundation (founder: "Let's do 0")
Goal: Friday running on a server with migrations applied and WhatsApp replying, health check and off switches. Founder has no server now. Claude cannot SSH or create cloud servers; Claude prepares scripts, a runbook and a health check; founder runs steps from the iPad console.

## Clarification (2026-10-19): the founder already has a DigitalOcean server
Slice 0 updates the existing droplet (small-server.sh is re-runnable; now restarts the service and checks out the current branch). Runbook section added.

## Clarification (2026-10-19): founder has the new SIM; needs to register it on Meta (WhatsApp Cloud API)
Guide added to docs/SLICE0_RUNBOOK.md (general knowledge; verify in Meta's current screens): Business portfolio + WhatsApp Business Account, add the number (must not be active on WhatsApp / WhatsApp Business), verify by SMS/voice OTP typed by the founder on Meta's page,
display name approval (needs a brand name), System User permanent token, webhook; unverified business has low daily limits; business name still undecided.

## Clarification (2026-10-20): founder has no Facebook/Meta account; WhatsApp setup from zero
Added "From zero" section to docs/SLICE0_RUNBOOK.md (Facebook account, Business portfolio, developer account, app, WhatsApp product, test number first, own SIM later). The `friday doctor` builder stopped on the weekly usage limit (resets 3am UTC); resume it with SendMessage afterwards (agent aecd00cb9b077ebf2, branch worktree-agent-aecd00cb9b077ebf2).
