# Beta build plan (EM, 2026-10-27): scalability, build order, founder task list, timeline

Status: PLAN ONLY, no code. Scope = the FINAL BETA FEATURE SET in docs/HANDOFF.md (F trip timeline, C refunds, G check-in/arrival forms, calling Friday from WhatsApp, password page mounting, guardrails module, voice polish bundle, BBPS bill payment via licensed partner, Paisa collector, customer care/hold-fighting, Wrapped card; Gift Rio EXCLUDED), on top of what is already merged (chat, calls, B proof, D documents, E family Drive, urgent escalation, receptionist, savings).
Labels: [V] verified in repo or a vendor doc this EM read; [A] ASSUMPTION; [U] UNVERIFIED (vendor blog or memory). Every price, limit and duration below that is not [V] is a guess to be replaced by a real number. Public repo: no keys, numbers or personal data here (env names only).

---
## 1. SCALABILITY

### 1.1 Today's architecture (what the code does) [V]
One Python process (`serve`, roles api+task+voice) on one small VM: webhooks, task engine, live-call audio (Vobiz media WebSocket, Sarvam STT/TTS), and in-process loops started in `friday/api/runtime.py` (worker, quotes, consumer, receptionist, urgent-escalation, retention). SQLite by default (Postgres/Supabase optional), Redis optional (backends exist: `cache_backend`, `rate_limit_backend`, `friday/db/queue.py` Postgres job queue with SKIP LOCKED, `locks.py`, `idempotency.py`, `partitions.py`, `kms.py`). The role split (`FRIDAY_ROLES`) and proactive sharding exist but are OFF. Live-call state is in memory, so a restart cuts calls. Defaults: `max_concurrent_calls=5`, `number_max_concurrent=2`, `worker_concurrency` task 32/voice 50, provider limits set generously (telephony 200, sarvam 200). The runbook now says a 2 GB droplet; `deploy/small-server.sh` has NO swap step (grep found none).
Existing plan to build on: docs/ENG_SCALE_PLAN.md (P1/P2/P3). This section adds the beta features, vendor limits and costs.

### 1.2 What breaks first, by user count
Rule of thumb [A]: 30-50% of beta users active per day (higher than the 10% in ENG_SCALE_PLAN because testers are invited and hand-held); 1 call per active user per day on average; peak = 5x average; at most 5-15 simultaneous calls at 1,000 users.

| Users | Breaks first | Then | Why / evidence |
|---|---|---|---|
| 10 | (1) Memory: Python + Silero VAD + Redis on 1 GB, no swap, OOM kill mid-call. (2) Meta test number only messages allow-listed recipients; a real number is needed for testers. (3) Google "Testing" mode: ~100 test users, refresh tokens may lapse in ~7 days so `needs_reconnect` is frequent [U]. (4) Founder attention: reviewing transcripts and approving wording. | Vobiz trial limits: 3 concurrent calls, CPS 1 [V SARVAM_QUESTIONS Q6]. Sarvam/OpenAI spend visible only by hand. | Nothing is load-bound. Fix is ops hygiene (swap, 2 GB, restart policy, alerts), not code. |
| 100 | (1) SQLite single writer + in-process loops sharing one event loop with live audio: a slow retention/quotes/receptionist tick stalls reply latency (p95 target 1.5 s). (2) Vobiz concurrency/CPS and `max_concurrent_calls=5`: 10-20 active callers collide. (3) Deploys and crashes drop live calls and pending mid-call questions. (4) WhatsApp: a new, unverified number has a small initial business-initiated limit [U: ~250 unique recipients per 24 h until verification] and out-of-window messages need approved templates (docs/WHATSAPP_TEMPLATES.md lists 5 families x 3 languages, none approved yet). (5) Sarvam STT/TTS rate limits unknown (docs/SARVAM_QUESTIONS.md). | LLM spend per user (section 1.4) and abuse by one user (no per-user token budget). | Needs Postgres, per-user limits, a queue for outbound sends, and Vobiz account upgrade. |
| 1,000 | (1) One process for audio decode/VAD/TTS on 2 vCPU: ~10-20 calls per vCPU [A, ENG_SCALE_PLAN]; WhatsApp-call media (aiortc) adds CPU; `FRIDAY_WA_CALLING_MAX_CONCURRENT` default 2 is a guess [U]. (2) Postgres connections without a pooler (`db_pool_size=10`). (3) Provider 429s from Sarvam/LLM without backpressure tuning. (4) Meta messaging tier (1K then 10K per 24 h, Meta-controlled [U]) and template quality rating: a few "block" taps can throttle the number. (5) Proactive engine (morning brief, followups, Paisa reminders, refund chasers, trip nudges) all fire in the same few minutes (06:00-09:00 IST herd). | Template spend becomes visible. DPDP requests (export/delete) become real work. | Needs worker split, Redis for locks/limits/idempotency, PgBouncer, proactive sharding and jitter. |
| 10,000 | Multi-worker voice with sticky routing and call state in Redis; hot tables (`call_turns`, messages, evidence) need partitions; Vobiz and Sarvam enterprise contracts (concurrency, CPS, SIP trunk); Meta tier upgrade, several numbers, quality management; BBPS partner volume pricing; a support function (human fallback, complaints, grievance officer SLAs). | Per-region failover. | Multi-region is NOT needed: India-only users, one Mumbai/Bangalore region with a warm standby is enough. |

### 1.3 Changes in order (each step has a trigger; do not build ahead of it)
1. **Ops hygiene before the first tester (founder + EM, 0.5 unit):** 2 GB droplet, 2 GB swap, systemd `Restart=always` and memory cap, `friday doctor` in cron with a failure ping, balance alarms (Vobiz, Sarvam, OpenAI) set in each console. Add a swap step to `deploy/small-server.sh` (EM task, tiny).
2. **Postgres before tester 10-20 (EM, 1 unit):** switch to Supabase/managed Postgres through `deploy/supabase/` scripts; run the full suite on Postgres once (several features were never run there: B says "not run on Postgres"). Keep SQLite for dev.
3. **Per-user rate limits (EM, 2 units):** on inbound messages per minute, LLM tokens per user per day, voice-note minutes per day, vision documents per day, WhatsApp-call minutes per day, bill-payment attempts, Paisa reminders sent per collection. Reuse the `RateLimiter` contract in `friday/core/scale.py`; limits are settings; over-limit gives one polite fixed line (wording to approve). NO per-user rupee spend cap on user actions (founder dropped A); this is abuse protection and cost control, a different thing: say so in the doc to avoid confusion.
4. **Idempotency on every new side effect (inside each feature build, enforced by the guardrails module):** key = (user, feature, natural id) for bill payment attempts, Paisa reminders, refund chasers, check-in submissions, outbound templates, urgent calls. Webhook de-duplication already exists (`webhook_idempotency_ttl_h=72`). Rule: a retried job or a double tap never pays, sends or dials twice. Test with a duplicate-delivery fixture per feature.
5. **Outbound queue for WhatsApp/SMS (EM, 2 units):** all proactive and template sends go through the Postgres `JobQueue` with `PROACTIVE` priority and a 70/s ceiling (`provider_rate_per_s`), jittered morning herd, per-recipient daily cap, template-quality counters (blocks, failures) shown on the doctor.
6. **Worker split (EM, 3-4 units, trigger: p95 reply > 1.5 s or > 100 users):** run `api` (ack webhooks fast), `worker` (task, proactive, batch, all `friday-*` loops) and `voice` (one call pinned per worker) as separate systemd units from the same code via `FRIDAY_ROLES`; loops move out of the voice process first. Needs Postgres + Redis. Still one VM at first (2 vCPU), second VM at ~500 users.
7. **Observability and alerts (EM, 3 units, start at step 1 with the minimum):** minimum now: structured logs without secrets (grep test), `friday doctor` JSON, uptime ping to the public URL, dead-man ping from `backup.sh` (`HEALTHCHECK_URL`). Next: per-call trace (STT/decide/TTS ms, p50/p95), queue depth and dead letters, provider 429/5xx counters, template send/fail/block counts, cost ledger per user per day (exists: `friday/api/costs.py`, alert at Rs 1,500 per user-month, tune to section 1.4), balance of each vendor. Alerts go to the founder by WhatsApp to his own allow-listed number plus email. Define 6 alerts: process down, doctor FAIL, p95 reply latency, dead letters > 0, vendor balance low, cost per user > 2x plan.
8. **Backups and restore (EM 1 unit + founder 0.5):** nightly `deploy/backup.sh` exists (pg_dump to S3-compatible, 30-day lifecycle). Add: Supabase point-in-time recovery if on a paid plan [U], a monthly RESTORE DRILL into a scratch database with `friday doctor` against it, and the encryption-key copy kept offline by the founder (backups do not include `/etc/friday/.env`; losing the field key makes the data unreadable).
9. **Secrets handling (EM 1 unit + founder 1):** names only in git and chat; `.env` chmod 600; rotate every key ever pasted in chat (PRODUCTION_CHECKLIST 1.3); separate keys per environment (lab, pilot); KMS wrapper (`friday/db/kms.py`) before real families; BBPS partner credentials and webhook secret get their own env names and are never logged; weekly `grep` of `journalctl` and logs for token fragments; GitHub secret scanning on; password page (credential vault) stays the only place a user types a secret.
10. **Beyond 1,000 (not now):** Redis call state and sticky routing, partitions, second number, enterprise vendor contracts, SIP trunk. Multi-region: not needed.

### 1.4 Cost per active user per month: ASSUMPTIONS, not measurements
Unit prices seen in repo docs [V as quoted, not re-checked]: Sarvam STT about Rs 30/hour, TTS about Rs 3 per 1,000 characters, Vobiz about Rs 0.38-0.44/min, whole voice call about Rs 2.5-5/min (HANDOFF, DEPLOY_AWS, FRONT_DOOR). Meta prices, WhatsApp-call media, flight-status API, vision API and BBPS fees are [U] or unknown and are shown as ranges.
| Item (per active user per month) | Assumed usage | Low Rs | Typical Rs | High Rs |
|---|---|---|---|---|
| LLM for chat and routing | 8-20 turns/day | 60 | 150 | 350 |
| Voice notes in (STT) and out (TTS) | 5 in/day, 3 out/day of 300 chars | 20 | 100 | 250 |
| Calls Friday makes for the user (Vobiz + STT + TTS + LLM) | 2-8 calls x 3 min | 10 | 40 | 150 |
| Calling Friday from WhatsApp (Meta inbound free [V design doc]; Sarvam + LLM only) | 0-8 calls x 4 min | 0 | 30 | 120 |
| WhatsApp templates (utility vs marketing) [U] | 4-20 per month | 2 | 8 | 30 |
| Vision/documents (D) and trip data | 2-6 docs, 0-2 trips | 3 | 10 | 40 |
| Customer-care hold calls (long, 10-30 min holds) | 0-2 per month | 0 | 25 | 150 |
| BBPS partner fee per bill [U] | 0-3 bills | 0 | 10 | 40 |
| **Variable total** | | **~95** | **~375** | **~1,130** |
| Fixed infra, spread over users | 1 droplet + managed DB ~Rs 2,000-4,000/month | 400 at 10 users | 40 at 100 | 4 at 1,000 |
Reading: typical is roughly Rs 400 per active user per month, high is near the existing Rs 1,500 alert, and hold-fighting plus long calls are the cost tail. Replace every row with the real ledger after the first 2 weeks (`friday/api/costs.py`). Revenue and pricing are not in scope here.

### 1.5 Load and soak test plan (use the simulators; real vendors only for a small final step)
Tools that exist: `uv run friday loadtest --users 1000 --calls 200` (simulator, SQLite), Chat Lab (`friday/lab`, manual on iPad), `friday/simworld` (111 call sims, 47 receptionist callers), `FakeClock`, fakes for every new port.
| Step | What | Pass bar (guesses) |
|---|---|---|
| L1 chat storm | N simulated users (10, 100, 1,000) x scripted conversations through the signed webhook path, fake LLM with realistic delay and 429s | ack < 200 ms, p95 reply < 1.5 s excluding LLM, 0 lost, 0 duplicates |
| L2 call concurrency | simulated calls at 5/20/50 concurrent with the fake telephony; then one real-audio run of 3 concurrent on a staging VM | no starved reply, RSS flat, p95 turn latency held |
| L3 herd | 1,000 users with morning brief, Paisa reminders, refund chasers all due in one 10-minute window | queue drains in < 15 min, per-recipient cap respected, no template send over limit |
| L4 soak | 24 h at 10% of target load on the simulator with the proactive loops on; sample RSS, open files, DB connections, queue depth every minute | RSS slope ~0, no leak, no dead letters |
| L5 chaos | kill -9 mid-task and mid-call; Redis down; Postgres failover; fake Sarvam/LLM 429 and slow; Meta 5xx | nothing lost or doubled, user sees one honest message, recovery < 2 min |
| L6 idempotency | replay every webhook and every job twice; double-tap every approval button | exactly one effect per side effect (payment, send, dial) |
| L7 isolation | two users, every new table: export, delete, purge, cross-read attempts | no leak; delete-everything covers new tables (0017-0023) |
| L8 Postgres run | whole suite plus L1-L2 on Postgres, not just SQLite (hides lock contention) | green, same bars |
Limits of this plan: simulators cannot show Vobiz, Sarvam or Meta limits; those come from vendor answers (founder tasks T4, T9) and the first real week. Run L1, L3, L5, L6, L7 before testers; L2 and L4 before 100 users.

---
## 2. DEPENDENCY AND BUILD ORDER

### 2.1 Items, dependencies, parallelism
Migration numbers pre-assigned by the founder decision. "Needs" = hard prerequisite; "Founder gate" = real-world step before it can be turned on (builds with fakes first, switch OFF).
| ID | Feature | Mig | Needs | Founder gate | Rough size [A] |
|---|---|---|---|---|---|
| F | Trip timeline (builder already running) | 0017 | D, E, B merged | flight-status provider (fakes first), buffers, card lounge rows | 8 units (6 + flight watch 2) |
| GR | Guardrails module (shared policy: approvals before money, idempotency keys, lead-spray guard, per-user limits, polling/monitor task type from docs/KEN_TWO_BY_TWO_NOTES.md) | none | engine, CallGate | founder confirms the rule list (task T17); the repo has no spec for this module, so the first unit is a one-page spec from the Ken notes and PRODUCTION_CHECKLIST | 4 |
| PW | Password page mounting + WhatsApp "my logins" | none | HTTPS domain, vault code (exists) | domain + HTTPS (T1) | 2 |
| VP | Voice polish bundle (backchannels, pronunciation lab, voice-note replies; see GO_LIVE "polish bundle") | none | speech/human code exists | audio approvals, listening kit (T13) | 4 |
| C | Refund tracking | 0018 | B | none (wording) | 4 |
| WAC | Calling Friday from WhatsApp (`friday/wacalling`) | none | Meta number on Cloud API, spike first | OBA not needed; India support of user calls UNVERIFIED; spike on Meta test number | 11-14 (design doc) |
| G | Web check-in + arrival forms | 0019 | F (trip_tasks kinds), E, browser connectors | founder supervises first real portals | 4 + 2 per site adapter |
| BP | Bill payment (BBPS via licensed partner port) | 0020 | GR (approval, idempotency), fake partner first | partner signup + legal read (T11, T12); real money OFF until both | 7 with fake partner, +4-8 real adapter [A] |
| PC | Paisa collector (UPI links to organiser's own UPI ID, live tracker, reminders) | 0021 | GR (reminder caps), outbox | legal read on collect/remind non-users (T12); templates for out-of-window reminders | 5 |
| CC | Customer care / hold-fighting (written complaints first, then hold calls) | 0022 | C (shares refund case), calls slice 1 real, GR | first real call proven (T16); legal rows 1, 2, 5, 10 | 7 (3 written + 4 hold) |
| W | Wrapped card (hours saved, money recovered; confirmed items only) | 0023 | B evidence, savings, C, BP, PC data | wording + image style approval | 3 |
| INT | Integration pass: one simulated week of a beta user across all features, docs, doctor, load tests | none | all | none | 6 |

### 2.2 Waves (what can run in parallel)
- **Wave 0, now:** F (running), GR spec + build, PW. Platform items: ops hygiene, Postgres run, rate limits (EM).
- **Wave 1, parallel after GR merges its interfaces:** C, PC, VP, WAC spike (spike is isolated: new package, own test number). Four builders at most; more than 3 at once raised merge pain earlier (lesson in HANDOFF).
- **Wave 2:** G (after F merges), BP (after GR + partner chosen), CC (after C).
- **Wave 3:** W (reads data from C, BP, PC), INT, load/soak L2/L4/L8, then go/no-go.
Critical path: GR -> BP -> W, and F -> G; the longest founder-gated chain is Meta business verification/OBA and the BBPS partner onboarding, so those start TODAY (T2, T11).

### 2.3 Shared files that cause merge conflicts, and the protocol
| Shared file | Why it conflicts | Rule |
|---|---|---|
| `friday/db/migrations/versions/*` | linear chain by `down_revision`; two branches chain off the same head | numbers pre-assigned (0017..0023); builder chains off the latest MERGED head and writes the real `down_revision` at merge, not before; the EM merges in numeric order; if a builder finishes early, still merge in order or re-chain |
| `friday/ops/doctor.py` `EXPECTED_HEAD_CHAIN` (now 0016_family_drive) | every builder edits one line | builders do NOT edit it; the EM sets it at each merge (and fixes doctor tests) |
| `deploy/supabase/schema.sql`, `rls.sql` (generated by `friday/db/regen_supabase_sql.py`) | generated, whole-file diffs | never hand-merge: after merging, re-run the generator and commit |
| `friday/core/config.py` (1,254 lines) | each feature adds settings and switches | each builder appends ONE contiguous block with its own banner comment at the end of its section; no reformatting; on conflict keep both blocks |
| `friday/db/tables.py`, `friday/core/container.py`, repositories | new tables/repos wired by name | one line per feature in alphabetical order; EM resolves |
| `friday/api/runtime.py` (loops), `friday/api/app.py` (routes), `friday/api/inbound.py` | new loops and routes | each feature registers via its own `wiring.py`; touch these files with a single call line |
| `docs/HANDOFF.md` | everyone appends at the end | builders do not edit HANDOFF in their branch; they put a ready-to-paste entry (done, needs founder, lesson) in their final report; the EM appends and commits (CLAUDE.md rule 2 still holds for the EM) |
| `docs/BUILD_BOARD.md`, wording `copy.py` files, `pyproject.toml`/lock | rare | EM edits; new deps need EM approval |
Merge protocol: (1) builder works in its own worktree branch; sync with the integration branch (`claude/friday-phase-1`) before reporting; (2) report = files touched, shared-file hunks, tests run (with the exact command and result), switch name and default OFF, wording list pending; (3) EM merges ONE branch at a time, in migration order, runs the full suite IN CHUNKS (one-go runs were killed) and only pushes after checking the result (lesson: never chain push after tests without reading them); (4) after each merge the other open branches rebase before their next report; (5) every feature ships behind a switch default OFF with a doctor check and an off-equals-old-behaviour test.

---
## 3. FOUNDER TASK LIST (from an iPad; priority order)
Rules for every task: never paste a key, token, OTP or password in chat or the repo; the installer asks with hidden typing; send back only what is listed. "Unblocks" names the build step or test that waits on it. Time = your effort, not waiting time.

### A. Do first (this week; these have the longest waits)
- [ ] **T1 Server.** DigitalOcean web console, tmux, run `deploy/small-server.sh` (docs/SLICE0_RUNBOOK.md); choose the 2 GB size; ask me to add the swap step first, or run the two swap commands I send. Time 45-60 min. Send back: last 20 lines of `friday doctor` (no secrets). Unblocks: slice 0, every real test, password page (needs the HTTPS name), Chat Lab on the server.
- [ ] **T2 Meta (start the slow parts now).** Facebook account + two-factor, Business portfolio, developer app type Business, WhatsApp product with the FREE test number (runbook "From zero" A-F). Then start **business verification** and the **Official Business Account (OBA)** application (needed for WhatsApp groups, and it lifts the daily-recipient limit; takes days to weeks [U]). Add the new SIM as the real number only after the display name is decided. Time 60 min now + 30 min for documents. Send back: "webhook verified: yes/no", the display name you chose, and whether Meta asked for ID. Unblocks: WhatsApp replies (slice 0), templates (T6), WAC spike, testers on a real number.
- [ ] **T3 Vobiz.** Upgrade the trial, top up, buy/assign a dedicated number, turn call queuing OFF, note the per-minute rate, ask in writing: concurrent-call limit, calls-per-second, SIP/inbound options for the receptionist and for forwarding. Time 30 min + a support email. Send back: rate, concurrency and CPS numbers they quote (no account IDs). Unblocks: slice 1 real call, customer care hold calls, scalability limits in section 1.
- [ ] **T4 Keys, names only.** Sarvam, OpenAI (and Anthropic if used), Google Maps; set monthly spend limits in each console; request zero-data-retention/DPA terms in writing (PRODUCTION_CHECKLIST 1.3, 1.8); ask Sarvam for rate limits and an enterprise price sheet. Entered only into the installer prompt. Send back: "keys entered: sarvam, openai ..." and the limits Sarvam states. Unblocks: LLM replies, voice notes, calls, vision.
- [ ] **T5 Business name, privacy policy, grievance officer.** Pick a working business name; I draft the privacy page and grievance contact text, you publish it and send the URL. Time 30 min. Unblocks: Google consent screen, Meta app review/verification, DPDP notice, BBPS partner KYC.

### B. Approvals that gate switching features on (hear/read, then say approve or change)
- [ ] **T6 WhatsApp templates.** Submit/approve the 5 template families in docs/WHATSAPP_TEMPLATES.md (morning brief, followup, bill reminder, call outcome, re-engage) plus new ones I will add: trip nudge, refund update, Paisa reminder, bill due. Time 20 min per batch. Send back: approved/rejected and Meta's reason. Unblocks: any message outside 24 h (F, C, PC, BP, W).
- [ ] **T13 Audio approvals (listening kit).** Play the kit I generate: disclosure/opening, "are you AI", stop/wrong number, close, voicemail rule, urgent escalation line, WhatsApp-call opening line, customer-care hold lines. Say approve/change per line. Time 45 min. Unblocks: slice 1 calls, urgent real dial, WAC, CC, VP.
- [ ] **T14 Wording approvals.** Read and approve the copy modules: `friday/calls/copy.py`, `friday/liveagent/lines.py`, `friday/savings/copy.py` (incl. the no-commission footer), `friday/lifestate/copy.py`, `friday/google/consent_copy.py`, `friday/memory/copy.py`, `friday/evidence/copy.py`, `friday/docunderstand/copy.py`, `friday/familydrive/copy.py`, `friday/urgent/copy.py`, `friday/receptionist/copy.py`, `friday/chatbot/copy.py`, `friday/chatbot/parity/copy.py`, `friday/chatbot_media/copy.py`, `friday/connectors/sites/copy.py`, `friday/integration/copy.py`; new modules for F, C, G, BP, PC, CC, W will be added to this list when built. I send them in small batches of ~20 lines. Time 15 min per batch. Unblocks: switching each feature on.

### C. Accounts to create (each unblocks a named build step)
- [ ] **T7 Google Cloud project.** New project, enable Calendar API and Drive API, OAuth consent screen in Testing mode, add test users (testers' Gmail addresses), add scope `drive.file` (no other Drive scope), create the web OAuth client with the redirect URI I give you. Gmail read stays OFF (restricted scope). Time 45 min. Send back: "done" + redirect URI used (the client id/secret go to the installer, hidden). Unblocks: Calendar, E family Drive spike (14-step checklist in docs/FAMILY_DRIVE.md), F docs.
- [ ] **T8 Vision provider.** Choose one for photos/documents (D adapters are stubs): give me 2 candidates' consent to send test documents with masked data, or pick the one you trust; open the account and enter its key (T4 style). Time 20 min. Unblocks: D real, F/G document reading.
- [ ] **T9 Flight-status provider.** Choose from 2-3 I will list with price per lookup [U]; sign up; key to the installer. Fakes work until then. Unblocks: F flight watch.
- [ ] **T10 UPI details for Paisa tests.** Use your OWN UPI ID in a test collection only; no ID is stored in the repo. Unblocks: PC real test.

### D. Money and legal (long waits; start now)
- [ ] **T11 BBPS partner signup (research + 2-3 calls/emails).** Candidates from docs/BETA_SCOPE_PROPOSAL.md, ALL UNVERIFIED (vendor blogs, not checked by me): Razorpay (BBPS COU), Cashfree, Setu, EnKash, BillAvenue. Ask each: (1) do you onboard a start-up that has no BBPS licence of its own, as your agent/sub-merchant; (2) fees per bill and minimum commitments; (3) which billers support bill fetch, including your city's electricity board, gas, mobile, credit card; (4) who holds the money and who is liable for failed/duplicate payments and refunds; (5) UAT/certification steps and calendar time; (6) documents needed (company, GST, PAN, bank account) and whether a sole proprietorship works; (7) data they keep on our users. Time 2-3 hours over a week. Send back: a short table per partner (answers + the contact person's role, no personal data). Unblocks: BP real adapter; until then BP runs on a fake partner.
- [ ] **T12 Legal reads (one lawyer, batched).** (a) DPDP: notice/consent, children's data in family vault, recipient data, evidence retention; (b) BBPS/RBI: Friday initiating bill payments via a partner, reverses the old "Friday never pays" rule (docs/LEGAL_MAP.md row 11 to be updated); (c) Paisa collector: collect links, reminders to non-users; (d) LEGAL_MAP rows marked "Yes" (TRAI/DLT, AI-voice disclosure, caller ID, recording consent, DPDP recipients, do-not-call, consumer liability) or a written pilot-only risk acceptance (GO_LIVE item 7). Time 1 hour to brief + the lawyer's turnaround. Send back: the written answers. Unblocks: real money (BP, PC), calls to non-consenting parties (CC), family vault with real families.
- [ ] **T15 Company/bank readiness check.** Do you have a registered entity, PAN/GST and a current account? BBPS partners and Meta business verification need them. Send back: yes/no per item. Unblocks: T2 verification, T11.

### E. Decisions already pending in the docs (answer in one sitting; I will send them as tap-to-answer batches)
- [ ] **T17 Guardrails rule list.** Confirm: lead-spray guard (never type the user's number on many vendor sites; cap vendors per request), polling/monitor task type ("check every 20 min"), approval before ANY payment (exact amount, buttons), no payments or OTP by voice, elder safety. (docs/KEN_TWO_BY_TWO_NOTES.md.)
- [ ] **T18 CONSUMER_DECISIONS (docs/CONSUMER_DECISIONS.md, 32 items).** Answer first the GO_LIVE top 8: 1 limits, 2 windows, 4 AI wording, 5 voicemail, 7 helpline number, 15 delete phrase, 25 PIN vs phrase, 27-32 call test rules; the rest can take the recommended default.
- [ ] **T19 TRIP_CONCIERGE_DESIGN decisions.** Decision 1 (spend cap) and 9 (hotel supply) are now MOOT. Remaining 3 buffers (2 h domestic, 3 h international), 2 proof strictness (strict for bookings/orders), 4 Drive actor (owner-only), 5 health documents (exclude), 6 retention + lawyer, 7 Testing mode, 8 trip-day cap (up to 5 messages) and flight provider.
- [ ] **T20 WHATSAPP_CALLING_DESIGN decisions (6).** Spike now; aiortc before a media server; reject unknown callers; Meta test number for the spike; no recording; opening line only after you hear Ritu's sample.
- [ ] **T21 Instinct parity.** Invite loop yes/no, ride deep link yes/no (read as "include"), nudge template wording (same as T6).
- [ ] **T22 E bytes gap.** After a document is shown for confirmation Friday has dropped the file: ask to resend, or upload to an Inbox folder in Friday's Drive folder first. Recommend resend for beta.
- [ ] **T23 D retention and vision.** Confirm 7 days for unconfirmed, 180 for confirmed; whether photos of quotes are in scope; health documents excluded.
- [ ] **T24 Urgent wording.** Approve the spoken escalation line and WhatsApp text; OK that "Acknowledge" replaces "Block" on the alert; default 5 minutes stays.
- [ ] **T25 Memory open questions.** Inferred preferences opt-in or default (recommend opt-in); episodes live 12 months; "last time you used X" in chat yes/no.
- [ ] **T26 Scope notes.** Gift Rio excluded (so "Rio" needs no definition); the morning check-in call and custom assistant name are NOT in the final beta set unless you say so.
- [ ] **T27 Group money rules for Paisa.** Max people per collection, who may be reminded and how often (default: opt-in link, 2 reminders, 24 h apart), what "paid" means (user marks paid; Friday never sees the bank).

### F. People and the first real call
- [ ] **T28 Tester recruitment (5-10).** Names only to me in chat as first names + a note on who they are (family, friend, small business); each gets the consent text (T14) and agrees to be a tester; add their Gmail to the Google test users (T7) and their number to the allow-list. Prefer a mix: 3 who travel, 3 with bills at home, 2 elders (with a child). Time 30 min. Unblocks: pilot week, trip/bill/Paisa real tests.
- [ ] **T16 First real call.** After T1-T4 and T13: run `friday consumer call-test` to YOUR number only; listen; check the transcript; test the off switch (`friday pause`). Time 30 min. Send back: heard/clear/latency feel and anything odd. Unblocks: CC, customer-care real calls, WAC full test, go/no-go.

---
## 4. TIMELINE in WORKING UNITS (1 unit = one focused builder-day; NOT calendar dates)
**All numbers are guesses.** Sources: sizes in the design docs (F 8, G 4+2/site, WAC 11-14, memory 5) and my own guesses for GR, PW, VP, PC, CC, W, BP. Past builds ran faster than design sizes but needed rework after merge; I add a 1.5x overrun allowance on the sum. Founder waits (verification, templates, partner, lawyer) are NOT in builder units and are the likely real critical path.
| Block | Builders | Units each | Parallel? | Elapsed units |
|---|---|---|---|---|
| Wave 0: F (rest), GR, PW + platform (swap, Postgres run, rate limits, alerts min.) | 3 | F ~3 left, GR 4, PW 2, platform 4 | yes | 5 |
| Wave 1: C 4, PC 5, VP 4, WAC spike 3 then build 8-11 | 4 | | yes, merge one at a time | 8 (WAC runs on to ~14) |
| Wave 2: G 4 + 2 per site (start with 1 airline + 1 portal), BP 7, CC 7 | 3 | | yes after prerequisites | 8 |
| Wave 3: W 3, INT 6, observability/worker split 4-7, load/soak L1-L8 3 | 2-3 | | partly | 8 |
| Sum if serial | | about 85 | | |
| **Critical path with 3-4 parallel builders** | | | | **about 30 units, about 45 with the 1.5x allowance** |
Merge and review overhead (EM, one at a time) is inside those numbers; if only ONE builder runs at a time, expect the serial sum (about 85 to 130 units).
What can be live when [A]: after Wave 0 + T1-T5: chat, calls to yourself, trips (documents, timeline with fake flight data) for named testers; after Wave 1: refunds, Paisa (no real money handled by Friday), WhatsApp calling on the test number; after Wave 2 plus T11/T12: real bill payment through the partner (this date is set by the partner and lawyer, not by builders); after Wave 3 and two clean days: wider beta of 10 testers, then 50-100 as in docs/BETA_SCOPE_PROPOSAL.md (needs Meta verification and templates approved, T2/T6).
Go/no-go for widening (all yes): doctor PASS; L1/L3/L5/L6/L7 passed; backups restored once; alerts fire in a test; no secret in logs; off switches tried; legal rows answered or risk accepted in writing; every new feature's wording and audio approved; per-user cost within 2x of section 1.4; the founder has used it for a full day.
Risks that move the dates most: Meta verification/OBA and display-name review; BBPS partner willingness to onboard a start-up; WhatsApp-call media over Meta's SDP/ICE (spike may fail, fallback = skip WAC for beta); flight-status provider choice; Vobiz limits; founder approval latency (many copy modules); tester real-call surprises; merge conflicts if more than 4 builders run at once.
