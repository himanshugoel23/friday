# HANDOFF: read this first (living context for any new chat or agent)

Founder instruction (verbatim intent): keep everything we discuss and decide in the repository, so a new chat can
read it and continue without losing context. **At the START of every task, update this file first** (what was just
asked, any decision, any mistake or lesson), commit and push it, **then** do the task. Never put secrets in it.

Last updated: 2026-10-10 (two chats, A and B, have worked on this repo; read sections 6-9 before touching anything).

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
3. Never read or print `.env`; keys live only in the git-ignored `.env` (sandbox) or typed on the server; never in
   chat or git. Never commit `.env` or `var/`. Keys pasted in chat earlier must be rotated after testing.
4. No real calls except to the allow-listed founder number (+918607549916) and only with the founder's approval.
5. Founder speaks Hindi/Hinglish/English mixed (often dictating); the founder's own wording of the script is the
   authority. Do not assume pronouns for people.
6. Keep AI cost low; keep the user experience good.
7. Show scripts and results plainly; the founder is non-technical about servers/AWS.
8. **Language: the founder may write in Hindi, Hinglish or English (often dictated); the assistant ALWAYS replies in English.**
   (Said on 2026-10-10. This is about the chat only; the bot's spoken language on calls stays Hinglish.)

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
  4. BOOK mode: "Sir, kya <date/time> ka slot available hoga aapke paas?"
     a. **Requested slot is free** -> close: "Theek hai sir, aaj shaam 5 baje ka slot book kar lijiye. <user> sir ya main aapko
        ek baar <slot time> se pehle call kar lenge, booking confirm karne ke liye. Thank you." (books only if the owner
        delegated and the code-level check passes; otherwise she says she will confirm with the owner and call back.)
     b. **Requested slot is NOT free** (founder, 2026-10-10): ask once for the nearest slot of the SAME part of the day:
        "Achha, aaj nahi ho sakta. Toh sir, nearest kaun sa slot available hoga <part of day>?" where <part of day> follows the
        time the owner asked for: 2-3 baje -> "din ka"; a morning time -> "subah ka"; 5 baje or later -> "shaam ka".
        - If the salon offers another slot (same day): "Theek hai sir, main ek baar <user> sir se confirm karke aapko call back
          karti hoon. Thank you."  (outcome: slot offered, NOT booked.)
        - If the salon says nothing today but names other days/times ("aaj nahi hai, kal subah ka hai / kal shaam ka hai"): take it
          as information only (store the offered slots) and ALWAYS say: "Theek hai, main ek baar <user> sir se confirm karke aapko
          call back karti hoon final booking ke liye. Thank you."  (outcome: slot offered, NOT booked.)
        - She never books a different slot on her own. The earlier line "phir kal ka 5 baje ka slot book kar lete hain" is
          REMOVED (replaced by this branch).
  5. QUOTE-ONLY mode (owner only asked for a price): no slot question; after the price: "Theek hai sir, main <user>
     sir ko bata deti hoon. Thank you."
  - Business name, user name and services are VARIABLES (services joined like "haircut aur beard trim").
  - Wording rejected by the founder: "slot milega" (not how people talk), "kitna time lagega", "arrive hone se
    pehle" (use "aane se pehle"), long openings, repeating things at the close.
- **Pronunciation**: "salon" is spoken as **saloon** (founder picked by ear). Names are converted to Devanagari with
  Sarvam's transliteration API, cached, with an overrides file and a generic-business-word glossary; a
  speak-then-listen check flags names needing review. Sarvam's pronunciation dictionary (bulbul:v3, `dict_id`) is
  wired in (`friday tts-dict sync`, `friday/voice/tts/pronunciations.json`).
- **Voice/speed**: Sarvam bulbul:v3 speaker `ritu`, **pace 0.9** (founder is happy with the speed). Founder said
  the tone still feels robotic: samples of other voices (v4-flash Hinglish customer voices Ishita/Shalini/Simran,
  higher temperature, phrase pauses) were sent; **the founder has not yet chosen a voice**.
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

## 6. Lessons, mistakes and sandbox facts (so we do not repeat them)
**Workflow lessons**
- **Two chats, one repo = duplicated work.** Before ANY task: `git fetch`, read `git log HEAD..origin/claude/friday-phase-1` and this
  file. (2026-10-09 chat B redid a "less helpdesk / witty call-back" tone pass, `305b40a`, that chat A had already done in
  `4eff9d2` + `d5e778c`; the founder asked not to repeat similar changes; chat B's commit was reverted in `ca1a714`.) Check git log
  for the topic before starting a tone/copy/prompt pass.
- Do not guess call problems: ask for `journalctl -u friday --since "10 min ago" --no-pager | tail -40` (and `| grep "reply gap"`).
- Keep agents on disjoint files; do not commit another agent's half-finished work; run the FULL suite (`uv run pytest -q`) before push.
- Never put stage directions in text that will be spoken (it gets spoken). Never put secrets in chat or git.
- Third-party apt repos can break (Caddy repo returned 402): use Ubuntu's own package.
- `reasoning_effort: minimal` is rejected by gpt-5.4-mini; valid: none/low/medium/high.
- Sarvam docs are readable with `curl https://docs.sarvam.ai/<path>.md` from the sandbox (WebFetch cannot resolve it).
- A `pkill -f "pytest -q"` inside a command containing that text kills its own shell; start test runs with `run_in_background`.

**The founder has no laptop (iPad/phone browser only):** give copy-paste steps for the DigitalOcean Web Console; never ask for secrets
in chat; keys go in the server `.env` (typed hidden) or the Claude environment settings, never in chat or git.

**AWS is a dead end for this founder.** Both AWS accounts offered (066899195555, 405449670622) were managed sandbox accounts inside
AWS Organizations with an SCP that explicitly denies Lightsail. Do not retry AWS. Hosting = the DigitalOcean droplet (section 5).

**What the AI sandbox can and cannot do** (it is a temporary cloud container): it can edit/run/test code, `uv run pytest`, build the
Docker image (`deploy/build_sandbox.sh`, because `ghcr.io` is blocked and Docker Hub rate-limits), run Postgres 16 / Redis locally for
tests, and read Sarvam docs. It cannot SSH to the droplet (outbound port 22 blocked), has NO provider keys (no Vobiz/Sarvam/OpenAI,
no `.env`), so it cannot place calls or generate audio unless the founder adds `SARVAM_API_KEY` etc. to the environment settings
(by name; never in chat). The founder runs server commands in the DigitalOcean Web Console (`tmux new -As friday`).

## 7. Current state (update every task)
**Running now (as last reported by the founder, 2026-10-10):** DigitalOcean Bangalore droplet (64.227.183.183, HTTPS via sslip.io),
systemd service `friday` running `friday listen` (front door: people can call +91 80 6426 7861), pilot profile (only the allow-listed
founder number is served/called), brain = OpenAI gpt-5.4-mini, Sarvam STT/TTS (bulbul:v3, ritu, pace 0.9), Vobiz telephony. The server
runs whatever was last `git pull`ed (`call-me.sh` pulls first).

**Done and pushed:** front door (conversational, voice onboarding, limits, result call-backs); quality loop (consented redacted encrypted
transcripts, review labels, scripted-caller eval); playbook engine + salon booking v0.2 + offline script author (8 business types
drafted) + dry-run simulator; Sarvam pronunciation dictionary; faster turns (early STT, sentence-by-sentence TTS, barge-in);
small-server installer; Codespaces trial path; Docker image + compose stack verified in the sandbox (image builds/boots, Alembic
migrations to head `0003_task_role` on Postgres 16, Postgres/Redis contract tests 52/52; the compose stack itself and the repo
Dockerfile (needs ghcr.io) were never run live). Full suite: **1758 passed, 28 skipped** (Postgres/Redis variants), ruff clean.

**Reported by the founder on the test call (2026-10-10), being fixed:**
1. Pause of 5+ seconds after the salon says "yes"; the salon says "hello, hello, hello". Target: reply starts within **1 second**.
   Status: code-side fixes pushed in `a435f2a` (warm TTS in call order and 3 at a time; bare price answers need no LLM; new
   `reply gap` log line). **Unverified on a real call.** The 900 ms end-of-speech wait (`SarvamCallLeg._segmenter.end_silence_ms`) is a
   floor; if the log shows warm audio and no LLM yet the gap is >1 s, shorten it for short answers (idea: close the utterance at ~500 ms
   when the early-STT guess is a short confirmation like "haan ji"). Do this only after reading the `reply gap` lines.
2. The latest finalized salon script (section 3, "salon v6") is NOT what the bot says; the repo has v0.2 (see the table below).
   **Not in the repo:** Devanagari-names pipeline, `friday tts-check`, `friday playbook preview`, quote-only mode, services variable,
   price-first order, fallback day, AI-on-request policy. Chat A reported a builder working on these (uncommitted). **Ask the founder
   whether chat A still has them before rebuilding** (avoid the duplication in section 6).

| | repo today (v0.2) | founder's final (section 3) |
|---|---|---|
| opening | "Hello, main Friday, ek AI assistant... Kya meri baat X se ho rahi hai?" | "Hello, kya meri baat X se ho rahi hai?" |
| intro | "...ki AI assistant hoon... appointment ke regarding" | "Main Friday... <user> sir ki virtual assistant... <services>... booking ke regarding" |
| order | slot question, then price | price first, then slot (book mode) |
| modes | one | book mode and quote-only mode |
| no slot | asks one alternative time | asks the nearest slot of the same part of the day (subah/din/shaam); any offer or other-day info is NOT booked: "main ek baar <user> sir se confirm karke aapko call back karti hoon. Thank you." |
| close | one short line | "Theek hai sir, phir kal ka 5 baje ka slot book kar lete hain. <user> sir ya main aapko ek baar <slot time> se pehle call kar lenge, booking confirm karne ke liye. Thank you." |
| AI mention | said first | not volunteered; "Haan ji, main <user> sir ki personal AI assistant hoon." when asked |
Note: the playbook validator currently rejects Devanagari in lines and tests enforce "AI disclosure first"; v6 changes both on purpose
(founder decision 2026-10-10), so those tests/validators must be updated together with the script.

**Open questions for the founder:** (a) is chat A still building v6? (b) add `SARVAM_API_KEY` to the Claude environment settings so the
sandbox can make preview audio (hear-before-change rule)? (c) which voice (robotic tone issue; samples sent, none chosen)? (d) check
Sarvam/Vobiz terms on not volunteering "AI". (e) turn Vobiz call queue OFF; keep Sarvam credits topped up (a 402 crashed a call);
rotate every key ever pasted in chat; decide whether the GitHub repo becomes private.

**Next steps, in order:** read `reply gap` lines from a new test call -> tune endpointing if needed -> settle v6 ownership (a) -> audio
preview of the real script -> founder picks voice -> server update + test call to the founder -> first real salon only with explicit
approval -> clinic/restaurant playbooks (`friday playbook draft --live`) -> WhatsApp channel -> beta plan (see section 9).

## 7b. Keys and where they live (NAMES ONLY: never write a value, a prefix or a screenshot of a key into the repo or chat)
Secrets are never committed (the repo may become public; `.env` and `var/` are git-ignored). Where each one lives:
| Name | Used for | Lives in |
|---|---|---|
| `SARVAM_API_KEY` | speech (STT/TTS), preview audio | droplet `/opt/friday/.env`; sandbox: Claude environment settings (needed for audio previews) |
| `OPENAI_API_KEY` | the brain (gpt-5.4-mini) | droplet `.env`; sandbox: Claude environment settings if live brain tests are wanted |
| `SARVAM_TELEPHONY_AUTH_ID`, `SARVAM_TELEPHONY_AUTH_TOKEN`, `SARVAM_CALLER_IDS` / `FRIDAY_NUMBERS` | Vobiz telephony (historical names) | droplet `.env` only |
| "helper" key (service and env var name to be confirmed by the founder; pasted in chat 2026-10-10 for sandbox messaging) | sandbox helper messaging | Claude environment settings once its name is known; treat the pasted value as exposed and rotate it |
Rules: add/rotate secrets in the droplet `.env` (typed hidden) or in the Claude environment settings (Edit environment -> variable by NAME);
a new session picks them up. If a key is pasted in chat it is considered exposed: rotate it after testing. This table is the reference a
new chat should use to know WHAT exists and WHERE; it contains no values.

## 8. History: who did what (newest last). Chat A = the main builder chat; chat B = the second chat (planning/hardening)
**Chat A (summary from git; see `git log` for detail):** conversational front door (`0a6a037`), quality loop (`2461d47`), playbook engine +
salon booking (`275c2bd`, `23d1882`, `3fe3029`, `5c78491`, `a3d7cb0`), `deploy/call-me.sh`, Sarvam pronunciation dictionary (`3d75f2b`),
offline script author (`054f34a`), Vobiz leg: barge-in, sentence-by-sentence TTS, early STT, persona cadence, shorter front-door lines,
small-server installer (`dffb809`...), Codespaces devcontainer + `deploy/codespace_call.sh`, GPT as an alternative brain, live-tuned.
**Chat B (this repo, 2026-10-08 to 10-10):**
- Reviewed the whole repo/docs; wrote the 3-day beta plan (`docs/BETA_PLAN.md`, decisions D1-D16): calls + WhatsApp, SMS off; scope =
  bookings/enquiries; hotels, care/IVR calls, transfer, recordings stay off until Vobiz TODOs are confirmed; calls-only product is not
  feasible (PIN/approvals cannot be taken by voice: Vobiz has no DTMF inside a media stream).
- Built and verified in the sandbox: Docker image, Alembic migrations on Postgres 16, Postgres/Redis contract tests, full suite; fixed
  2 lint errors and a stale config test; `deploy/build_sandbox.sh`, AWS/CloudShell provisioning scripts (unused: AWS blocked),
  provider-neutral `lightsail-launch.sh`, `backup.sh` S3-compatible endpoint.
- Decided: LLM for the beta = Anthropic (Haiku 5.5 background, Sonnet 5.5 live turns) on cost grounds, but the trial/pilot runs on
  OpenAI because that is the key the founder has; re-decide for the beta from measured cost/quality.
- Answered (no code): what is stored. User context = profile, facts, people, places, vendor history, identifiers (encrypted), autonomy
  limits, recent chat turns, open tasks (rebuilt into a snapshot before each brain call). Calls = call rows + encrypted per-turn
  transcripts, call_memory (which number called which business), quotes; recordings off in beta (30-day retention if on); pre-consent
  users purged after 7 days; "delete everything" erases a user's rows. Front-door voice conversations are NOT stored beyond name/
  language/consent and tasks created (plus the consented, redacted quality-loop transcripts). Gap proposed, not built: a short summary
  of each front-door call as memory.
- Answered (no code): fine-tuning now is premature (no real-call data; Anthropic models in use are not fine-tunable; playbooks +
  quality loop are the chosen route; fine-tune later from reviewed transcripts).
- Redid a "less helpdesk / witty call-back" tone pass (duplicate of chat A, reverted).
- Placed the first test call path (`call-me.sh`), received the founder's feedback, fixed the latency causes found in code (section 7).

## 9. Decision register (condensed from `docs/BETA_PLAN.md`; this file wins where they differ)
| Topic | Decision | Status |
|---|---|---|
| Channels | voice + WhatsApp; SMS off (no DLT/MSG91) | WhatsApp not built into the pilot; Meta templates/verification are the long pole |
| Hosting | DigitalOcean Bangalore droplet, pilot profile (SQLite, `friday listen`, no Docker) | live; Docker + Postgres + Redis compose stack is the later beta route, never run live |
| Brain | OpenAI gpt-5.4-mini now; Anthropic recommended for beta on cost | re-decide after real-call cost/quality |
| Scope of beta | bookings and enquiries; no hotels, care/IVR, transfer, recordings | until Vobiz TODOs are confirmed (`docs/LAUNCH_CHECKLIST.md` s.2) |
| Approval rule | never book without explicit owner delegation; budget alone is not delegation | enforced in code |
| Beta gates | privacy/terms/Grievance Officer pages, vendor ZDR/DPA, verified official care numbers, key rotation, spend limits | open (`docs/PRODUCTION_CHECKLIST.md`) |
| Fine-tuning | later, from reviewed consented transcripts | not started |

## 10. Document map: current vs stale
**Current:** this file; `CLAUDE.md`; `BRIEF.md`; `PLAYBOOKS.md` + `playbooks/salon_booking.md`; `QUALITY_LOOP.md`; `FRONT_DOOR.md`;
`LATENCY.md` (why replies pause, how to measure, levers); `SECURITY.md`/`SECURITY_FIXES.md`; `PRODUCTION_CHECKLIST.md` (beta go/no-go); `ARCHITECTURE.md`.
**Older planning docs (written before the droplet existed; trust section 5 of this file instead where they differ):** `BETA_PLAN.md`,
`DEPLOY_AWS.md`, `TRIAL_CODESPACES.md`, `LAUNCH_CHECKLIST.md`, `LIVE_TEST_WINDOWS.md`, `deploy/aws/*`, `deploy/lightsail-launch.sh`.

## 11. How to start a new chat (paste this as the first message)
"Read CLAUDE.md and docs/HANDOFF.md fully, then run `git fetch` and `git log HEAD..origin/claude/friday-phase-1`. Tell me in 10
lines where we are, what is running, what is open, and which question you need me to answer. Do not change anything yet. Then follow
the rules in section 2 (update HANDOFF first, hear before change, no `.env`, no real calls except to my number with my approval)."
- 2026-10-10 founder edit to the v6 script (chat B): the slot question is now **"Sir, kya <date/time> ka slot available hoga aapke
  paas?"** (was "Kya <date/time> ka slot mil sakta hai?"). Spec updated in section 3 step 4 only. The bot's code (v0.2 `s2_ask`:
  "Kya {date_window} ka appointment mil sakta hai?") is NOT changed: hear-before-change applies and v6 is not in the repo; when v6 is
  built, use this wording and send the audio first.
- 2026-10-10 founder edit to the v6 script (chat B): the close's call-back sentence is now **"<user> sir ya main aapko ek baar
  <slot time> se pehle call kar lenge, booking confirm karne ke liye. Thank you."** (<slot time> = the booked time, e.g. "5 baje").
  Spec only (section 3 step 4 and the section 7 table); the bot's code is unchanged (v0.2 close is "Theek hai, aap {slot} ka book
  kar lijiye. Thank you."), audio first when v6 is built. Note for the engine: "main call kar lungi" means the call-back task must
  exist; if the confirmation call is not implemented for a slot, do not promise it.
- 2026-10-10 founder edit to the v6 script (chat B): **slot-not-free branch** defined (section 3 step 4b): ask the nearest slot of the
  same part of the day; salon offers a slot -> "confirm karke call back karti hoon", other-day info -> take it as information and
  always say the call-back line; never book a different slot herself; the fallback-day booking line is removed. Proposed boundaries
  for <part of day> (to confirm with the founder): before 12:00 = subah, 12:00-16:59 = din, 17:00 or later = shaam. Engine notes for
  when v6 is built: store `offered_slots` even when the salon names other days; outcome = SLOT_OFFERED (pending approval) with the
  call-back task created; the engine needs a `part_of_day` value derived from the requested time (today `slots.find_period` exists).
  Spec only; the bot's code is unchanged (hear-before-change).
- 2026-10-10 founder ask (chat B): "Give audio preview first" (of the v6 script lines). **Blocked: no `SARVAM_API_KEY` in the sandbox
  environment** (Sarvam is reachable; the key is not set; no `.env`). Prepared: `docs/playbooks/salon_v6_preview.txt` (the 12 lines with example
  inputs, "saloon" spelled as spoken) and `deploy/preview_script.py` (renders them with the same voice code as `friday say`, pace 0.9, to
  `var/preview/salon_v6/*.wav` plus `all.wav`; `--dry-run` lists lines). To unblock: founder adds `SARVAM_API_KEY` in the Claude environment
  settings (by name, never in chat) and starts a new session; then run `uv run python deploy/preview_script.py` and send the files with
  SendUserFile. Alternative: run the same command on the droplet (it has the key) and download the WAVs. Preview text is a draft; edit
  the .txt and re-run until approved, then build v6 with the approved wording.
- 2026-10-10 founder ask (chat B): test a "helper" key pasted in chat and "store the keys in GitHub so the other chat has them".
  Decision: **keys are NOT stored in git** (standing rule 3; repo may go public). Added section 7b: a names-only registry of what exists and
  where it lives. The pasted helper key was not used (the service/endpoint is unknown to the repo) and is treated as exposed.

- 2026-10-10 founder ask (chat C): "Create a new repository on my GitHub called `amazon`" for a thorough research of Amazon's e-commerce
  business, to start our own e-commerce store. The new repo is the **source of truth** for that work (it will span multiple chats). This is
  a separate project from Friday; Friday's rules (no secrets, English replies, update the handoff first) carry over. The new repo gets its own
  `CLAUDE.md` and `docs/HANDOFF.md` so any new chat can continue. Created as a private repo (default; founder can change).
