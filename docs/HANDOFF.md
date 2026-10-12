# HANDOFF: read this first (living context for any new chat or agent)

Founder instruction (verbatim intent): keep everything we discuss and decide in the repository, so a new chat can
read it and continue without losing context. **At the START of every task, update this file first** (what was just
asked, any decision, any mistake or lesson), commit and push it, **then** do the task. Never put secrets in it.

Last updated: 2026-10-10 (salon v6 built; read this file first).

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
