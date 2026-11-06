# Robin Phase 1 backlog (engineering manager, 2026-11-06)

Author: engineering manager agent. Audit of the real code at commit 2628ebc (not of the docs). Elderly-care product, so the order is
SECURITY AND DATA PROTECTION FIRST, then the remaining safety features, then Phase 2 (experience). One developer agent per ticket, one at a
time, each in its own worktree; the lead reviews, merges, runs the affected tests and pushes only if green. The lead updates the status column
in section 3 after each merge. Everything here is a plan: no spoken line, voice, real call or real WhatsApp send is approved or implied.

Scope (founder, final). Phase 1 = every safety feature working end to end for 4-20 pilot families. Phase 2 = good-morning digest, festival
graphics, bill payment, grocery, SMS reading and other experience features (section 7). Hard rules: Robin never pays; no call recording on the
parent's phone; no SMS or WhatsApp content reading; no stealth or proxy; no real 112/1930 call in tests or by default; every line PENDING
founder approval; no real call or WhatsApp send without approval; product name only from `brand_name` (`FRIDAY_BRAND_NAME`).

## 1. State of the code (verified by reading code and running tests)

Baseline: `.venv/bin/pytest tests/robin tests/robindevice tests/care -q` = **528 passed** (44 s). Code: friday/robin (family core, ~4.6k lines),
friday/robindevice (device API + engine, ~3.4k), friday/care (care protocol, ~1k). Migration `0019_robin_family`. All Robin switches default OFF.
Status key: **BUILT** = built and tested with fakes only (no real adapter exists or has been exercised); **PARTIAL**; **NOT BUILT**.

| # | Phase 1 feature | Status | Where | Exact gap (verified) |
|---|---|---|---|---|
| 1 | Consent by child (`admin_on_behalf`), parent notified, parent can stop | PARTIAL | robin/family.py, commands.py, intro.py, ports.py (`ParentChannel`); tests/robin/test_family_consent.py | Logic and audit are built and DB-backed (encrypted JSON). The notification to the parent is only a `ParentChannel` Protocol + `FakeParentChannel`: **no real adapter** (`ctx.parent_channel` is never set in `build_robin`), so with no channel the "notice" sits in a `pending` outbox record that **nothing delivers**. Parent STOP by voice note/text cannot arrive: `RobinHub.parent_said` has **zero callers** outside wiring. Legal review of admin-on-behalf consent still open. |
| 2 | Daily check-in call | PARTIAL | robin/checkin.py, telephony.py (`TelephonyParentCaller`); tests/robin/test_checkin_medicine.py | Plan, 2 retries, ladder, quiet hours, care postponement, digest all tested with `FakeParentCaller`. The real caller uses `CallLeg.speak/listen`, never run against a phone; refuses while `lines.LINE_STATUS` is PENDING (good). No supervised live test, STT quality on Hindi answers unmeasured. |
| 3 | Medicine reminders, refill alerts | PARTIAL | robin/medicine.py, wiring.py `on_document_confirmed` | Reminders, taken/missed, stock estimate, refill at 5 and 2 days, weekly count: tested. Prescription photo: `docunderstand` has **no PRESCRIPTION doc type** (grep: none), so `on_document_confirmed` never fires for a real photo, and the doc sink is wired to `features.on_document_confirmed` (trips) not to Robin. |
| 4 | Missed-call messages both directions + emergency re-ringing | PARTIAL | robin/missedcall.py, alerts.py `open_missed_urgent`; tests/robin/test_desk_missed.py | Message + ring-every-3-min x6 loop tested. **Forwarded-call leg not wired**: friday/api/callbacks.py (`_from_event`) hands forwarded calls only to `receptionist.claims`; nothing calls `RobinHub.on_missed_call` (the file's own header says so). Parent-side message depends on item 1's missing channel. |
| 5 | Scam check by forwarding to Robin on WhatsApp | PARTIAL | robindevice/scamcheck.py (634 lines, rules + optional LLM that can only raise), service.py `share` | Engine tested. Entry path only via the Android share intent (`/robin/device/share`). **No WhatsApp intake**: a forwarded message/image from the parent never reaches `scamcheck`; no image/OCR route; no `llm` port supplied by `build_device_ports` (only alerts/consent/parents). |
| 6 | Unusual-activity detection (Android pack), shadow week | PARTIAL | robindevice/engine.py, rules.py, scenarios.yaml (S1-S8, S4P), service.py | Rules, ceilings, per-parent shadow-week counters, "this was fine" learning: tested. Scenario thresholds are flagged UNVERIFIED. **Device state is in memory** (store.py header, `ParentStore._parents/_by_token/_codes`): a restart forgets pairings, tokens, events, prompts, shadow clock. `DeviceService.sweep()` (S7 unreachable, S8) has **no scheduler**. **No code issues a pairing code** (`create_pairing_code` has no caller): the child cannot pair a phone. The Android app does not exist. |
| 7 | Call-pattern analysis (screen-first / listen-in) | PARTIAL | robindevice/callpattern.py, service.py `feed_call_turn`; robin/screening.py (100 lines) | Analyzer tested on dialogues (tests/robindevice/call_dialogues.yaml). `feed_call_turn` has **no caller**; `screening.py` is a stub (`FRIDAY_ROBIN_SCREEN_UNKNOWN_ENABLED`/`LISTEN_IN` do nothing real). No Vobiz/telephony transcript source, no audible disclosure, no fake bridge. |
| 8 | SOS and "I am being threatened" | PARTIAL, **BUG** | robin/sos.py, alerts.py, answers.py `is_threat`; robindevice/service.py `sos` | Family-side SOS ladder and threat words tested via `SosService`/`parent_said`. **Contract mismatch (verified):** the device package sends tier `"EMERGENCY"/"HIGH"` (uppercase) and scenario `"SOS"`; family `Tier` is lowercase (`"emergency"`), `AlertEngine` tests `scenario == "sos"` and `plan_for` compares `tier == Tier.HIGH`. `_DeviceAlerts` passes strings through unchanged and the only test asserts `tier == "HIGH"` (tests/robin/test_device_ports.py:61), so the bug is baked into the test. Effect: a device HIGH falls into the WATCH plan; a device SOS is not treated as `sos` (consent check applies, refused when the parent paused, wrong ladder). Must be fixed before anything else. Widget voice/SOS hooks (`widget_voice/widget_sos`) have no transport. |
| 9 | Unreachable-parent escalation ladder | BUILT | robin/checkin.py + alerts.py (`checkin_unanswered`: WhatsApp child, call child, second contact) | Tested. **Second-contact sender missing**: `ctx.send` is the child-user notifier only (`build_robin`), so `wa_second`/`call_second` have no way to message a person who is not a Friday user (verify in T08). Ladder state survives restart (records in DB, `cas` on status). |
| 10 | AI emergency desk, policy-gated authority calls, DRY-RUN | BUILT | robin/authority.py; tests/robin/test_desk_missed.py | Preconditions, 60 s cancel window, one call per incident, audit, fraud -> 1930 *bridge* only: tested. No live adapter exists and CallGate refuses emergency numbers (good). `TelephonyParentCaller.bridge` (add_participant + leave) is unverified on Vobiz (exotel/twilio/sarvam implement it; no Vobiz-specific test). |
| 11 | Care protocol for distress | BUILT (child chat) | friday/care/*, wired in api/inbound.py (~l.556); tests/care | Detect + central gate + no distress text in logs: tested. Robin consults `care.is_active` before calls. **Parent's own words are not screened**: `parent_said` never passes through care. Helpline numbers unverified; professional review pending. |
| 12 | Child's WhatsApp alerts with buttons, digests, audit log | PARTIAL | robin/alerts.py `_buttons`, checkin digests, `Ctx.audit`; channels/notifier.py | Buttons ("Mark safe", "I have it", details, call parent/join), digests, audit tested with `RecordingSender`. Real send = existing `Notifier` (WhatsApp Cloud client exists: send, templates, media; **Meta token blocked**). Web chat fallback for alerts: not wired. Outside the 24 h window needs approved templates (none submitted for Robin). |
| 13 | Parent channel on WhatsApp, voice-note first | NOT BUILT (interface only) | robin/ports.py `ParentChannel`, `FakeParentChannel`; channels/whatsapp.py has `send_audio/upload_media/fetch_media` | No adapter combining TTS + `send_audio` + template fallback; no inbound route for a parent's number (parent would fall into the normal Friday chat as a stranger); voice-note STT exists for users (`_media_inbound`) but is not applied to parents. |
| 14 | Thin Android app (widget + SOS) + optional protection pack | NOT BUILT | docs/ROBIN_ANDROID_APP.md (contract), robindevice/api.py (server side done: pair, heartbeat, signals, share, prompts, ack, sos, voice, consent, pause, stop, resume, transparency, erase; strict schemas, rate and size limits) | No Kotlin project. Server `voice` port not connected to STT (`ports.get("voice")` is None, so `/voice` answers `voice_not_available`). |
| 15 | Persistence, observability, ops | PARTIAL | robin/dbmodel.py (encrypted JSON, AES-GCM), purge.py | Family data persists (SQLite in tests; **Postgres untested**: no Robin test targets it). `DataPurger.purge_user` calls `purge_user_robin`, but **robindevice holds no DB rows and is not purged/erased by family `erase`** (in-memory, so a restart is the only "delete"). Doctor has one switch line (`FRIDAY_ROBIN_ENABLED`), **none for device, authority, lines status, migration 0019 present**; opsstatus has waitlist routes only (no Robin counts); no `deploy/enable-robin.sh` (only `enable-robin-waitlist.sh`; Robin switches are in `enable-web-test.sh` ALWAYS_OFF). |
| 16 | Festival graphics PNG/fonts, good-morning, bill payment, grocery, SMS reading | Phase 2 | robin/greetings.py (text only) | No PNG renderer or fonts; festival dates unverified. Not in Phase 1. |

Other facts that matter: rate limiter in the device API is per-process memory (`RateLimiter`); audit retention 30 d via `purge_before("audit")` every 120 ticks;
`robin_records.status` compare-and-set makes the alert ladder safe across restarts and two replicas. Lines: 477 (robin) + 180 (device) + 31 (care) x 3
languages, all PENDING (docs/ROBIN_LINES.md generated).

## 2. What blocks the pilot that only the founder can unblock (separate from engineering)

| Blocker | Needed for | Founder action |
|---|---|---|
| Meta WhatsApp token / provider-hosted WABA (personal Facebook restriction) | any real parent or child message, voice notes, templates | resolve per docs/META_UNBLOCK_PLAN.md; submit Robin templates once T07 lists them |
| Legal review: admin-on-behalf consent (DPDP), Play policy for notification/call roles, automated 112/1930, call listen-in disclosure | onboarding any real family; turning off dry-run | engage counsel; nothing here is legal advice |
| Approval of Hindi/Hinglish/English lines and the voice (hear-before-change) | any real call or voice note (dial adapter refuses while PENDING) | listen to audio samples the lead sends; approve per batch |
| Pilot families (4-5 then 20) and the in-person phone setup for each | T14/T15 field test, T19 | pick and recruit; founder's own family first |
| Domain + privacy policy + grievance officer (waitlist and Play listing need them) | public pages, Play | buy domain, name officer |
| Google Play Console account + declarations (notification access, call screening) | protection pack distribution (closed testing) | create account, pay fee |
| Vobiz: number for Robin's line, top-up, conference/bridge capability confirmed with Vobiz in writing | T10, T11, T16 | account actions; confirm bridge and forwarding with provider |
| Carrier conditional forwarding on the parent's SIM (Jio/Airtel/Vi differ) | missed-call flow | done during in-person setup; tell us the carriers |
| Helpline numbers and wording review; clinical review of care protocol | wide launch | professional reviewer |
| Spend limits on STT/TTS/LLM; cost per family per day | pilot budget | set limits |

## 3. The ordered backlog (19 tickets)

Order logic (founder, 2026-11-06: security first): A. protect data, consent and the alert path (T01-T06); B. parent channel and the remaining
safety flows (T07-T13); C. Android (T14-T15); D. call-pattern (T16); E. founder review and evaluation (T17-T18); F. pilot (T19). Status column is
maintained by the lead (TODO / DOING / MERGED / BLOCKED).

| Ticket | Title | Needs real adapter? | Founder input | Status |
|---|---|---|---|---|
| T01 | Fix the device-to-family alert contract (tier/scenario/SOS) | fakes only | none | TODO |
| T02 | Persist device, pairing and call-pattern state (encrypted DB) + sweep scheduler | fakes only (SQLite; Postgres opt-in) | none | TODO |
| T03 | Consent and delete-everything integrity, retention jobs, encryption-at-rest check, secrets scan | fakes only | none | TODO |
| T04 | End-to-end safety harness with fakes (child chat -> consent notice -> check-in -> alert -> escalation) + PII-free log gate | fakes only | none | TODO |
| T05 | Observability without PII: doctor lines, ops-status counts, `deploy/enable-robin.sh` | fakes only | none | TODO |
| T06 | Authority-call lock (dry-run proofs), rate limits, pairing brute-force defence, abuse tests | fakes only | none | TODO |
| T07 | Parent WhatsApp channel: inbound routing, voice-note STT/TTS, adapter + fake + template interface | fake now; real adapter behind Meta | template wording approval (later) | TODO |
| T08 | Child-side delivery: pairing command, alert delivery with fallback, second-contact sender, outbox drain | fake now; uses Notifier | none | TODO |
| T09 | Device voice/SOS intake into the family package (STT port, SosService path) | fakes only | none | TODO |
| T10 | Missed-call forwarding integration (callbacks -> Robin) both directions | fake telephony; real needs Vobiz | none | TODO |
| T11 | Live telephony readiness for check-in/alert calls (supervised, founder number only) | real adapter, one supervised call | audio approval + go-ahead | TODO |
| T12 | Medicine: prescription doc type, doc sink to Robin, refill flow to the child | fakes only (vision reader fake) | none | TODO |
| T13 | Scam check by WhatsApp forward (text, link, screenshot) with voice-note verdict | fake now | none | TODO |
| T14 | Android app part 1: Kotlin project, pure modules, press-to-talk widget, SOS, pairing | build on CI; device test needs founder | none (later: phone) | TODO |
| T15 | Android app part 2: protection pack (call-screening role, notification listener, camera, remote-access queries) | device-only verification | pilot phone | TODO |
| T16 | Call-pattern screen-first / listen-in on Vobiz: design + fake bridge + wiring to `feed_call_turn` | fake bridge; real needs Vobiz | disclosure wording, legal OK | TODO |
| T17 | Shadow-week report and false-alarm review page for the founder (read-only, counts only) | fakes only | none | TODO |
| T18 | Safety evaluation set and regression gate | fakes only | none | TODO |
| T19 | Pilot readiness: dry run with the founder's own family and the checklist | real | everything in section 2 | TODO |

**Dispatch NOW, in this order: T01, T02, T03.** T04 follows immediately (it needs T01's fix to be meaningful, and gains from T02/T03).

---------------------------------------------------------------------------------------------------------------------

### T01 Fix the device-to-family alert contract
- **Why (safety):** today a device HIGH is planned as WATCH and a device SOS is not an SOS (section 1, row 8). An elderly user's SOS must always ring the child, even paused or without signal consent.
- **Scope in:** normalise tier and scenario at the single seam (`robin/wiring.py::_DeviceAlerts.raise_alert`): lowercase tier -> `Tier`, unknown tier -> HIGH (never lower), scenario `SOS` -> `sos`, `THREAT` -> `threat`. Make `AlertEngine.raise_alert` itself defensive (accepts str tiers/scenarios case-insensitively, logs and raises HIGH on garbage). Route the device SOS through the `sos` plan including location rules. Add a contract test shared by both packages (a table of every tier/scenario `robindevice` can emit vs the plan `robin` makes).
- **Scope out:** voice intake (T09), persistence (T02).
- **Files:** friday/robin/wiring.py, friday/robin/alerts.py, friday/robin/models.py (Tier parsing helper), friday/robindevice/ports.py (document the enum), tests/robin/test_device_ports.py (fix the baked-in `== "HIGH"` assertion), new tests/robin/test_alert_contract.py.
- **Depends on:** none.
- **Acceptance tests (`.venv/bin/pytest tests/robin tests/robindevice -q`):** test_alert_contract.py asserts (a) every (tier, scenario) from `robindevice/scenarios.yaml` produces the plan of its tier (HIGH has call_child steps, EMERGENCY has authority step); (b) device SOS creates an incident with `scenario == "sos"`, rings the child, and works when the parent is paused and with no `device_signals` consent; (c) device WATCH stays an app nudge; (d) unknown tier string -> HIGH; (e) dedupe key still idempotent.
- **Flag:** fakes only. **Risks:** other callers relied on uppercase; grep all `raise_alert(` callers first. **Founder inputs:** none.

### T02 Persist device, pairing and call-pattern state
- **Why:** after any restart (every deploy, the droplet has autoupdate) pairings, tokens, signals, prompts and the shadow-week clock vanish: the child's protection silently stops and the shadow counters reset, so false-alarm data is lost.
- **Scope in:** `DeviceStore` interface with two implementations (in-memory for tests, DB-backed); migration `0020_robin_device` with encrypted JSON (`EncryptedJSON`, same pattern as robin/dbmodel.py): devices (token HASH only), pair codes (hash, expiry), events (enums/counts/timestamps only), prompts, fired-ranks and shadow clock, counters, trusted-number hashes, audit of what the child was told. Bounded sizes already in store.py (`MAX_EVENTS` etc.). Wire `DeviceService.sweep()` into the Robin scheduler (`RobinHub.tick`) so S7 (unreachable) and S8 run. Postgres: add a test module that runs the store tests against Postgres when `FRIDAY_TEST_POSTGRES_URL` is set (skipped otherwise) and say plainly that it was not run in CI here.
- **Scope out:** consent/erase hooks (T03). Never store message text, contact names or digits (existing rule; add a test that scans stored JSON).
- **Files:** friday/robindevice/store.py (split interface/impl), new friday/robindevice/dbmodel.py, friday/db/migrations/versions/0020_robin_device.py, friday/db/tables.py, friday/robindevice/wiring.py, friday/robin/wiring.py (tick), friday/ops/doctor.py (EXPECTED_HEAD_CHAIN), tests.
- **Depends on:** T01 (same wiring files; avoid conflict).
- **Acceptance tests:** tests/robindevice/test_store_persistence.py: pair -> new service instance on the same DB -> token still authenticates, events/prompts/shadow clock survive; pair code single-use + expiry survives restart; stored rows contain no plaintext token, phone or text (assert on raw column bytes); migration up/down on SQLite; tests/robindevice/test_sweep_scheduler.py: S7 fires after N missed heartbeats through `RobinHub.tick`, once (idempotent across two services); doctor expects head `0020_robin_device`.
- **Flag:** fakes only. **Risks:** migration chain conflicts (doctor constant, other migrations in flight: check `versions/` first); event volume growth; Postgres unverified. **Founder inputs:** none.

### T03 Consent and delete-everything integrity, retention, encryption, secrets scan
- **Why:** consent is the legal and ethical core. Parent STOP, withdrawal and erase must provably remove access and data in all three packages.
- **Scope in:** (1) `FamilyService.erase` and `DataPurger.purge_user` also erase `robindevice` rows and live in-memory analyzers (call `DeviceService.erase_parent` per parent; add a registry so purge needs no import cycle); (2) consent audit completeness: every grant/withdraw/pause/resume has actor (`admin_on_behalf`, `user`, `guardian`), time, source; admin cannot resume a parent-paused family; paused parent => device signals dropped server-side (test through the HTTP API); (3) retention jobs: device events 7 d, call-pattern cues per `call_text_retain_days`, audit 30 d, incident records after N days (setting), run from the scheduler, tested with a fake clock; (4) encryption-at-rest test: introspect every Robin/RobinDevice table column that holds personal data and assert it is `EncryptedJSON` or a keyed hash; fail when a new plaintext column appears; (5) secrets scan test: a pytest that greps the repo tree (excluding `.venv`, `var`, `.env*`) for key-shaped strings and phone-number-shaped strings in docs/tests/fixtures, with an allow-list file; add `deploy`-time check to the lead's pre-push list. Never read `.env`.
- **Scope out:** legal opinion (docs only).
- **Files:** friday/robin/family.py, friday/robindevice/service.py, friday/db/repositories/purge.py, friday/robin/wiring.py, tests/robin/test_erase_all.py, tests/security/test_robin_at_rest.py, tests/security/test_no_secrets_in_repo.py.
- **Depends on:** T02.
- **Acceptance tests:** test_erase_all.py: build a full family with device pairing, events, incidents, medicines, audit; run `erase` and separately `purge_user`; assert zero rows in all Robin/RobinDevice tables, device token rejected (401), analyzers dropped, child told once; test_at_rest.py as above; retention test deletes only rows older than the limit; secrets test passes on a clean tree and FAILS on an injected fixture string (negative control inside the test).
- **Flag:** fakes only. **Risks:** purge ordering/foreign keys; false positives in the secrets scan (allow-list). **Founder inputs:** retention periods (propose defaults in the PR; they stay as settings).

### T04 End-to-end safety harness with fakes
- **Why:** components are tested alone; nobody has driven the whole chain. This is the regression net for everything after it and the demo for the founder.
- **Scope in:** `tests/e2e/robin/` harness building a real `InboundPipeline` + container + `RobinHub` on SQLite with a fake clock, `FakeParentCaller`, `FakeParentChannel`, `RecordingSender`, fake Notifier; DSL steps: child says "set up Robin for my father" -> answers -> admin consents -> parent receives notice (voice note + text) -> parent says "band karo" -> family PAUSED, child told, device signals dropped, only parent resumes -> check-in at time -> unanswered x3 -> ladder (child WhatsApp, child call, second contact) -> parent answers -> ladder closes. Scenarios: device HIGH with money -> child buttons -> "Mark safe"; SOS with unreachable child -> authority dry-run log (no call); missed call urgent -> re-ring x6; care-protocol phrase from the child suppresses non-urgent nudges. Assertion helper `assert_no_pii(logs)`: captured log records and audit never contain a full phone number, medicine name, transcript or distress text.
- **Files:** tests/e2e/robin/{harness.py,test_family_lifecycle.py,test_alert_escalation.py,test_sos_authority_dry_run.py,test_missed_urgent.py,test_no_pii_in_logs.py}; small test-only seams in friday/robin/wiring.py if the pipeline cannot take injected fakes (prefer none).
- **Depends on:** T01 (T02/T03 improve it).
- **Acceptance tests:** the files above, `.venv/bin/pytest tests/e2e/robin -q`; each scenario asserts message count and order, call count caps (3 per incident, 3 per person per day), and that `authority` only wrote a dry-run record. Runtime under 60 s.
- **Flag:** fakes only. **Risks:** pipeline needs many components (fix with the existing test container helpers; do not mock the Robin classes). **Founder inputs:** none.

### T05 Observability without PII
- **Why:** we need to know the pilot is alive and safe (switches, dry-run, lines status, queue health) without ever seeing a parent's data.
- **Scope in:** doctor lines (`friday doctor`): Robin on/off, device on/off, authority calls on + dry-run state (FAIL if live), lines status PENDING/APPROVED, migration 0019/0020 present, care component present, scheduler task running, parent channel configured, last tick age. Ops-status routes under the existing token pattern: `/ops-status/<token>/robin` (counts only: families by status, active incidents, alerts by tier last 24 h, check-ins done/unanswered, devices paired, heartbeats missed, outbox pending, errors) + JSON; never ids, names, numbers, text. Metrics counters via the existing logging layer. `deploy/enable-robin.sh` modelled on enable-robin-waitlist.sh: turns on `FRIDAY_ROBIN_ENABLED` and `FRIDAY_ROBIN_DEVICE_ENABLED` only, leaves authority and listen-in off, refuses if `FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false`, prints a plain summary; add to ALWAYS_OFF/KEPT list correctly.
- **Files:** friday/ops/doctor.py, friday/api/opsstatus.py, friday/robin/wiring.py (counts query on `RobinStore`), deploy/enable-robin.sh, docs/ROBIN_FAMILY_CORE.md, tests/ops/test_doctor_robin.py, tests/robin/test_opsstatus_counts.py.
- **Depends on:** T02. **Acceptance:** doctor flags authority-live as failure; route returns 404 for bad token, JSON with only integer fields (test walks the response and rejects any string longer than a status word or any digit run of 10+); script test in dry mode (shellcheck-style test used by other deploy scripts).
- **Flag:** fakes only. **Risks:** accidental leakage by a debug field (the digit-run test). **Founder inputs:** none.

### T06 Authority lock, rate limits, abuse defence
- **Why:** the worst failures are an AI dialling 112 by mistake, someone guessing a pairing code, or flooding the child with alerts.
- **Scope in:** (1) prove dry-run: a test that constructs the container with every Robin switch on and asserts no object in the graph can place a call to 112/100/101/102/108/1930 (CallGate refusal + `TelephonyParentCaller` refuses those numbers independently); `FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false` with no live adapter must refuse and alert the founder, not silently work; (2) persist rate limits for the device API (shared across replicas via the DB or cache) and add limits on pairing attempts (per code and per source), code length/entropy check, lockout after N bad codes, token rotation on re-pair; (3) alert-flood protection: per-family daily cap on child WhatsApp alerts with a "many alerts" summary instead of silence for EMERGENCY; (4) payload fuzz tests for `/robin/device/*` (oversize, wrong content-type, extra fields, unicode).
- **Files:** friday/robin/authority.py, friday/robin/telephony.py, friday/robin/gate.py, friday/robindevice/api.py, store.py, tests/robin/test_authority_lock.py, tests/robindevice/test_ratelimit_pairing.py, tests/robindevice/test_api_fuzz.py.
- **Depends on:** T02, T03. **Acceptance:** all above with names; EMERGENCY is never rate-limited away.
- **Flag:** fakes only. **Risks:** over-limiting a real SOS (SOS exempt, tested). **Founder inputs:** none.

### T07 Parent WhatsApp channel (voice-note first)
- **Why:** this is the parent's only normal door. Without it the consent notice, STOP, "I am fine", scam forwards and missed-call messages cannot happen.
- **Scope in:** `WhatsAppParentChannel` implementing `ParentChannel` over `channels/whatsapp.py` (`send`, `upload_media`, `send_audio`) + TTS (existing voice stack, language per parent) and template fallback outside the 24 h window; a `ParentChannelPort` fake with the same behaviour. Inbound: in `InboundPipeline`, before user resolution, if the sender phone hashes to a Robin PARENT member -> voice note: fetch media, STT, delete audio, `RobinHub.parent_said(phone, text, via="voice")`; text/forwarded content handed to T13; everything else from a parent never reaches the general Friday assistant. Parent words also pass the care protocol (distress -> care path, family told per consent). Stop/start/help/fine/threat already exist in `parent_said`. List the template names and parameters in docs (for Meta approval). Build `ctx.parent_channel` in `build_robin` only when the WhatsApp channel is configured; otherwise the outbox drain from T08.
- **Scope out:** real Meta send (blocked); real TTS voice choice (founder approves audio).
- **Files:** new friday/robin/channel.py, friday/robin/wiring.py, friday/api/inbound.py (one early hook; keep diff tiny), friday/robin/ports.py, docs/ROBIN_FAMILY_CORE.md section 10, tests/robin/test_parent_channel.py, tests/api/test_inbound_parent_route.py.
- **Depends on:** T01, T03. **Acceptance:** parent voice note "Robin band karo" (fake STT) pauses the family and the audio bytes are not retained; unknown number is not treated as a parent; outside 24 h window the template is used; send failure falls to the outbox and is retried; the parent never gets the generic Friday menu; `no_pii` assertion.
- **Flag:** fake now, **real adapter interface ready for Meta**. **Risks:** hot path in inbound.py (conflict with other work: only one dev works at a time, still keep to a single hook); STT accuracy for Hindi elders. **Founder inputs:** later, template wording and voice audio approval.

### T08 Child-side delivery and second contact
- **Why:** an alert nobody receives is not an alert. Today delivery is the child's WhatsApp only; the second contact and pairing are missing.
- **Scope in:** chat command "pair phone for papa" -> `DeviceService.create_pairing_code` shown to the child with plain instructions; alert delivery with fallback chain per `Notifier` (WhatsApp -> SMS fallback exists in channels/notifier.py -> webchat) and a delivery-failed flag that escalates the ladder one step earlier; a `SecondContactSender` (WhatsApp/SMS to a number that is not a Friday user, only to a contact named in advance, alert-only text, no data beyond the alert line); drain the `pending` outbox records (parent messages queued when no channel); child's "what is on" and "what Robin did today" confirmed in webchat.
- **Files:** friday/robin/commands.py, friday/robin/wiring.py, friday/robin/context.py (`send` seam), friday/robin/family.py, friday/channels/notifier.py (only a thin helper, if needed), tests/robin/test_second_contact.py, test_outbox_drain.py, test_pairing_command.py.
- **Depends on:** T02, T07. **Acceptance:** second contact receives exactly the alert line and never an unnamed number; unreachable child (send raises) causes earlier escalation; outbox drains once; pairing code single-use.
- **Flag:** fake now, uses Notifier. **Risks:** SMS content rules (DLT) unverified. **Founder inputs:** none.

### T09 Device voice and SOS intake into the family package
- **Why:** the widget is the parent's emergency button and microphone; the server end must work before the app exists.
- **Scope in:** implement `VoiceIntake` port in `build_device_ports` (`voice`): audio bytes -> existing speech path (STT) -> delete bytes -> `RobinHub.widget_voice` -> reply text (+ TTS URL optional); `llm` port for scamcheck (optional, can only raise); device SOS -> `RobinHub.widget_sos` with optional location (consent `location`); fake STT in tests; heartbeat-missed already via T02.
- **Files:** friday/robin/wiring.py, friday/robindevice/ports.py (no change to the contract), tests/robin/test_widget_voice.py, tests/robindevice/test_api.py additions.
- **Depends on:** T01, T07. **Acceptance:** `/voice` returns reply for "madad karo" and raises an SOS; works while paused; audio never written to disk (monkeypatched file APIs); `no_consent:voice_messages` path tested.
- **Flag:** fakes only (real STT behind existing speech provider). **Risks:** latency on 2 GB droplet. **Founder inputs:** none.

### T10 Missed-call forwarding integration
- **Why:** the missed-call flow is the most natural safety net and today is not connected.
- **Scope in:** in `api/callbacks.py::_from_event` (forwarded call answered), before `receptionist.claims`: if the dialled/forwarded number belongs to a Robin member, run `MissedCallService.steps_for` over the telephony leg (reuse receptionist `serve` style loop with the 60-90 s cap), collect answers, call `RobinHub.on_missed_call`; the caller gets a WhatsApp "X has been told" (when they are a known family member only). Parent-missed and child-missed both. Setup text per carrier (Jio/Airtel/Vi forwarding codes) in the child's onboarding, with a "test the forwarding" call to the founder number only. Urgent: ring loop already built.
- **Files:** friday/api/callbacks.py, friday/robin/missedcall.py, friday/robin/wiring.py, friday/receptionist/carriers.py (reuse), tests/robin/test_forwarded_call_wiring.py (fake leg from receptionist/sim.py).
- **Depends on:** T07, T08. **Acceptance:** simulated forwarded call from a stranger -> child/parent message, urgent -> 6 rings max 3 minutes apart, stops on ack; a non-Robin number still goes the old receptionist path (regression test); switches off = no change.
- **Flag:** fake telephony; real needs Vobiz number + forwarding. **Risks:** forwarded caller-id/dialled-number fields differ per carrier (`probe.py` exists). **Founder inputs:** Vobiz number, carrier list.

### T11 Live telephony readiness (check-in, alert and intro calls)
- **Why:** the check-in call is the core daily safety feature and has never touched a phone.
- **Scope in:** a supervised live-test command (`friday robin call-test`) that places ONE call to the allow-listed founder number using the QA pending-lines override, speaks the check-in plan, listens, prints a PII-free result (outcome, step timings, STT confidence); STT tuning for short Hindi answers (yes/no, "theek hoon") with an acceptance corpus; barge-in/silence handling; ring timeout and voicemail detection (VOICEMAIL must not count as reached); the dial remains refused while lines are PENDING unless the founder-number QA override is on; call cost estimate per family per day logged.
- **Files:** friday/robin/telephony.py, friday/robin/answers.py, friday/cli.py (command), tests/robin/test_telephony_live_fake.py (fake leg incl. voicemail, hang-up, silence), docs/ROBIN_FAMILY_CORE.md.
- **Depends on:** T05, T06. **Acceptance:** fake-leg tests for each outcome; refusal tests unchanged; the live call itself is a founder-supervised step in T19, not a CI test.
- **Flag:** NEEDS A REAL ADAPTER run (one call, founder's number, founder present). **Risks:** Vobiz latency; elderly speech recognition. **Founder inputs:** approval of audio and of the single test call.

### T12 Medicine: prescription type, refill flow
- **Why:** missed medicines and running out are the most common real harm for elderly parents.
- **Scope in:** add PRESCRIPTION to `docunderstand` (fields: medicine, dose text, times, days) with a fake reader fixture; route the document sink to Robin when the sender is a Robin admin (compose with the trips sink, do not replace it); child confirms medicines (yes/no) before saving; refill alert to the child with a "ordered" button (Robin never pays or orders); stock estimate correction from the weekly count.
- **Files:** friday/docunderstand/*.py, friday/chatbot_media/wiring.py (sink composition), friday/robin/medicine.py, friday/robin/wiring.py, tests/docunderstand/test_prescription.py, tests/robin/test_prescription_flow.py.
- **Depends on:** T04. **Acceptance:** photo fixture -> confirmation message -> saved only after yes; trips sink still works (regression); refill alert once per threshold; no medical advice in any line (existing test extended).
- **Flag:** fakes only (real vision provider chosen by founder earlier). **Risks:** OCR errors in medicine names: always confirm. **Founder inputs:** none.

### T13 Scam check by WhatsApp forward
- **Why:** the parent's most common safe action is forwarding a suspicious message and asking "is this real?".
- **Scope in:** from T07's inbound hook: text/link/screenshot from a Robin parent -> `scamcheck` (rules first, optional LLM that can only raise, image via existing OCR/vision with a fake), verdict as a short voice note + text in the parent's language ("do not click / do not pay / call your child"), HIGH verdicts also tell the child per `share_summary_with_child`; no content stored (verdict, category and time only); money-moment links to the first-hour playbook text for the child; repeated scam from the same sender hashed.
- **Files:** friday/robin/wiring.py, friday/robindevice/scamcheck.py (adapter only), friday/robin/lines.py (new lines PENDING), tests/robin/test_scam_forward.py.
- **Depends on:** T07, T09. **Acceptance:** corpus from tests/robindevice/test_scamcheck.py reused through the WhatsApp path; no content in storage or logs; without `scam_check` consent the parent is told Robin cannot help and the child is informed.
- **Flag:** fake now. **Risks:** false reassurance (never say "safe", only "no warning signs found"). **Founder inputs:** wording approval.

### T14 Android app part 1: thin widget, SOS, pairing
- **Why:** the parent's physical button and microphone; also the carrier for the protection pack.
- **Feasibility (checked in this sandbox):** Java 21 and Gradle 8.14 present. The Android command-line tools downloaded through the proxy (dl.google.com, 153 MB) and `sdkmanager` installed `platforms;android-34` successfully; maven.google.com, Gradle plugin portal and Maven Central answered 200 (Central returned one 429 earlier, then 200). So a Gradle build with JVM unit tests is expected to work here after `sdkmanager` installs build-tools; **a full APK build was not attempted**. There is no emulator or physical device: nothing about permissions, foreground services, widgets or the lock-screen SOS behaviour can be verified here.
- **Scope in:** Kotlin project `android/robin-app/` (applicationId from a build property, name from `brand_name` at build time, minSdk 26); pure-Kotlin modules with JUnit tests: `ApiClient` (all `/robin/device/*` calls, bearer token, strict schemas from docs/ROBIN_ANDROID_APP.md), `PairingFlow`, `ConsentView` (read-only, withdraw only), `SosGesture` (press-and-hold timing state machine), `PromptQueue`, `TransparencyScreenModel`; thin Android layer (activity, widget, foreground-less SOS, microphone permission); `scripts/build-android.sh` + GitHub Actions workflow for the founder's machine/CI (sdk install, `./gradlew test assembleDebug`); no analytics SDKs, no Firebase.
- **Scope out:** protection pack (T15), Play listing.
- **Files:** android/** (new), scripts, docs/ROBIN_ANDROID_APP.md status section, tests/robindevice/test_contract_fixtures.py (shared JSON fixtures used by both Python and Kotlin tests so the contract cannot drift).
- **Depends on:** T09. **Acceptance:** `./gradlew test` (JVM) passes in CI/sandbox if the SDK install succeeds; Python contract test passes; **explicitly unverified:** installation, widget on real launcher, mic capture, battery behaviour, OEM background kills.
- **Flag:** needs the founder's machine/CI to produce an APK and a real phone to test. **Risks:** Android toolchain cost in the sandbox; OEM restrictions; Play policy. **Founder inputs:** a test phone and Play account (later).

### T15 Android app part 2: optional protection pack
- **Scope in:** each item behind its own consent and role set up in person by the child: call-screening role (unknown-caller start/end/duration only, never audio), notification listener limited to a whitelist of bank/UPI package names emitting only `{package class, amount bucket, time}` (never text stored or sent beyond amount), camera-in-use callback, installed remote-access app query, heartbeat; all emit the strict signal types of robindevice/schemas.py; persistent notification and a "what is on" screen (Play requirement); pause/stop buttons.
- **Files:** android/** pure modules + tests; docs.
- **Depends on:** T14, T02. **Acceptance:** JVM tests for signal builders and the whitelist filter (payment text is parsed in memory and dropped; unit test asserts nothing but the bucket leaves the function); server contract tests unchanged. Everything platform-specific is **unverified until a real phone test** (T19).
- **Flag:** device-only verification. **Risks:** Play review of notification access and call screening; Android 13+ restricted settings for sideloads; unverified. **Founder inputs:** pilot phones, Play declarations.

### T16 Call-pattern screen-first and listen-in on Vobiz
- **Why:** voice-clone and digital-arrest scams are caught by the pattern of the call (urgency build-up, isolation, payment ask), not by a safe word.
- **Scope in (design + fake):** design doc section in docs/ROBIN_FAMILY_CORE.md section 9: calls routed through Robin's line; (a) screen-first: unknown caller hears "{brand} is screening, say who you are" before the parent's phone rings; (b) parent-triggered listen-in: one-tap/voice "Robin, suno" adds Robin to the call with an audible disclosure to both sides; a `CallBridge` port (Vobiz conference/stream) with `FakeCallBridge` that feeds transcripts; wire transcript turns to `DeviceService.feed_call_turn` and finish with `finish_call`; tier output drives S4P; transcript text never stored; consent item `call_listening` required, off by default; implement `screening.py` behind the two switches using the port; Vobiz real adapter written to the documented Vobiz stream/conference API but unexercised.
- **Files:** friday/robin/screening.py, new friday/robin/callbridge.py, friday/robin/wiring.py, tests/robin/test_screening_listen_in.py using tests/robindevice/call_dialogues.yaml.
- **Depends on:** T10, T09. **Acceptance:** dialogue corpus -> expected tiers through the full path; disclosure line always spoken first (test); no transcript persisted; consent off -> bridge refuses; legal flag in docs.
- **Flag:** fake bridge now; real needs Vobiz capability + legal OK. **Risks:** two-party consent law, latency, cost per minute, call quality. **Founder inputs:** disclosure wording, legal review.

### T17 Shadow-week report and false-alarm review page
- **Scope in:** read-only founder page (token-protected, counts only, no human desk, no live duty): per family: week number, signals seen vs alerts that would have fired (shadow), ceilings hit, "this was fine" taps, check-in answered rate, SOS count, authority dry-run log entries (script text without personal data); CSV export of counts; daily review checklist. Reuse `DeviceService.shadow_report` and the T05 counts.
- **Files:** friday/api/opsstatus.py, friday/robindevice/service.py (read helper), tests/robin/test_review_page.py. **Depends on:** T02, T05. **Acceptance:** page renders from seeded data; contains no phone, name, medicine or text (digit-run and wordlist test); wrong token 404.
- **Flag:** fakes only. **Risks:** accidental PII. **Founder inputs:** none.

### T18 Safety evaluation set and regression gate
- **Scope in:** `tests/bench/robin/` scenario files (YAML): scam-check (40+ texts incl. Hinglish, KYC/OTP/digital arrest/lottery/relative-in-trouble; 20+ benign), call patterns (reuse dialogues + add 10), care protocol (distress vs idiom false-positives, Hindi/Hinglish), emergency flow (SOS, threat, danger words, ladder timings). A runner prints precision/recall per category; a gate test fails the suite if recall on HIGH-risk scenarios drops below the recorded baseline or false-positive rate rises; baseline file committed and only the lead may update it. Tagged "unverified clinical/linguistic review needed".
- **Files:** tests/bench/robin/*, tests/robin/test_eval_gate.py, docs/ROBIN_EVAL.md. **Depends on:** T13, T16. **Acceptance:** `.venv/bin/pytest tests/bench/robin -q` green; deliberately weakening a rule makes the gate fail (negative-control test).
- **Flag:** fakes only. **Risks:** small corpus overfits; say so in the doc. **Founder inputs:** native-speaker review of the Hindi samples.

### T19 Pilot readiness
- **Scope in:** dry run with the founder's own family; checklist doc `docs/ROBIN_PILOT_CHECKLIST.md`: all section-2 blockers cleared, lines approved with audio, doctor all green, ops counts live, backups tested (deploy/backup.sh restore of Robin tables), T11 supervised call done, T14/T15 phone test report, forwarding tested per carrier, parent notice delivered and STOP tested by the parent for real, delete-everything demonstrated, SOS drill (authority stays dry-run), kill switch drill (`pause`), rollback steps, support/grievance contact, per-family daily cost. Output: go/no-go note for 4-5 families.
- **Depends on:** all. **Acceptance:** signed checklist in HANDOFF. **Flag:** real. **Founder inputs:** everything in section 2.

## 4. Definition of done (every ticket)
1. Tests added and passing; state the exact commands in the report, at least `.venv/bin/pytest tests/robin tests/robindevice tests/care -q` plus the ticket's own files and any directory it touched (`tests/api`, `tests/e2e/robin`, `tests/security`, `tests/ops`).
2. `.venv/bin/ruff check` and `ruff format --check` clean on touched files (the repo uses `# ruff: noqa: E501` in these packages; do not widen it).
3. Every new switch defaults OFF; no existing default changed; nothing added to FEATURES_ON in deploy scripts.
4. New or changed spoken/chat lines are PENDING (`LINE_STATUS` untouched), `docs/ROBIN_LINES.md` regenerated, brand only via `{brand}`.
5. No secrets, no real numbers, no personal data in code, tests, docs, logs (public repo); never read `.env`.
6. HANDOFF.md entry (start of task: what was asked; end: what was built, lessons, open items) and the relevant doc updated (ROBIN_FAMILY_CORE.md, ROBIN_ANDROID_APP.md).
7. The lead reviews the diff, merges, runs the affected-test gate (the ticket's dirs plus robin/robindevice/care and `tests/security`), and pushes only if green; red = no push, ticket goes back.
8. The lead sets the status in section 3 and notes any new gap here before dispatching the next ticket.

## 5. Developer brief template (the lead pastes this, filling the brackets)
```
You are a DEVELOPER agent for Robin (parents' security and care; code package `friday`). Repo /home/user/friday is PUBLIC.
Work in your own git worktree/branch `worktree-agent-<ticket>`. Do NOT push. Do NOT commit to the main branch; commit on your branch only if told.
TICKET: [T0X title] from docs/ROBIN_PHASE1_BACKLOG.md. Implement exactly its Scope-in; stop at Scope-out.
READ FIRST (in order): CLAUDE.md; docs/HANDOFF.md (latest 2026-11-04+ entries); docs/ROBIN_PHASE1_BACKLOG.md (your ticket + sections 1 and 4);
  docs/ROBIN_FAMILY_CORE.md; [ticket-specific files from its "Files" list]; the existing tests of those modules.
FIRST ACTION: add a HANDOFF.md entry (what the founder asked = this ticket, decisions, plan). Do not commit it separately unless told.
HARD RULES: never read or print .env; no secrets or real phone numbers anywhere; no real call, no real WhatsApp/SMS, no real 112/1930 (fakes only
  unless the ticket says "real adapter", and then only with the lead's explicit go-ahead); Robin never pays; no call recording; no SMS/WhatsApp content
  reading beyond what the ticket defines; no stealth; product name only through brand_name/{brand}; every new spoken or chat line is PENDING founder
  approval (do not change LINE_STATUS); all switches default OFF; do not touch spoken lines of existing flows (hear-before-change).
CONFLICT AVOIDANCE (one developer at a time, still): touch only the files in the ticket's Files list; if you must touch another file keep the diff
  minimal and list it in the report; never reformat or reorder code you do not change; do not edit migrations other than your own number (check
  friday/db/migrations/versions/ for the current head and tell the lead if it moved); do not touch friday/guardrails care logic, jobs, browser_agent,
  voice core unless the ticket names it; use unique scratch file names under the scratchpad directory; do not drop or apply git stashes.
TESTS: write the acceptance tests named in the ticket; run them and the regression set:
  .venv/bin/pytest tests/robin tests/robindevice tests/care -q   plus [ticket dirs].  ruff check + format on touched files.
REPORT (final message, concise): 1) what changed (files), 2) test commands and results (counts), 3) anything NOT verified and why, 4) new gaps or
  bugs found, 5) switches/migrations/lines added, 6) questions for the founder, 7) confirmation of: no secrets, switches default OFF, lines PENDING,
  HANDOFF entry written. Do not claim anything works that only a fake exercised: say "tested with fakes".
```

## 6. Risk register (top 10), cuts, first three
| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | Meta WhatsApp stays blocked: no parent channel, no child alerts | high / critical | provider-hosted WABA route; T08 SMS and webchat fallbacks; pilot can start with calls + SMS only (loses voice-note UX) |
| 2 | Alert-contract bug (found) or similar seams hide real failures | certain today / critical | T01 then T04 harness plus T18 gate |
| 3 | Device state lost on restart (in memory) | certain / high | T02 |
| 4 | Admin-on-behalf consent fails legal review | medium / critical | notify + stop + audit already built; keep guardian flag; T19 gate on counsel's answer |
| 5 | Automated 112/1930 calls illegal or harmful | medium / critical | stays dry-run; T06 proves it cannot go live by accident; no human desk in Phase 1 |
| 6 | False alarms burn the child's trust (alert fatigue) | high / high | shadow week, ceilings, "this was fine", T17 review page, T18 baseline |
| 7 | PII leak in logs, ops pages or public repo | medium / critical | T03 secrets scan, T04 no-PII gate, T05/T17 counts-only tests |
| 8 | Play policy rejects notification access / call screening; Android 13+ friction | high / medium | pilot via closed testing and in-person setup; the thin widget works without the pack |
| 9 | Elderly speech recognition and Hindi TTS quality too poor for check-ins | medium / high | T11 supervised test with a corpus; fall back to simple yes/no and child digest |
| 10 | Single-developer pipeline stalls on founder-only blockers (audio approval, Meta, legal) | high / medium | tickets T01-T06, T08-T09, T12, T17, T18 need no founder input; run them first |

**If time runs short, cut in this order (last first):** T17 review page (use ops counts), T18 bigger corpus (keep the gate with a small set), T12 prescription OCR (child types medicines by chat, already built), T15 protection pack (pilot with widget + SOS + check-in + scam forward + missed calls), T16 listen-in (keep screen-first design only). Never cut T01-T06, T07 (parent channel), T09, T10, T13, T14, T19.

**Dispatch now:** 1) **T01** alert-contract fix (small, critical, removes a silent safety bug), 2) **T02** persistence of device/alert-adjacent state, 3) **T03** consent and delete-everything integrity. Then T04 (harness), T05, T06 before any new feature.

## 7. Phase 2 (after Phase 1 passes T19; not ticketed yet)
Good-morning digest (text built in robin/greetings.py), festival graphics (needs PNG renderer, fonts, verified dates, original templates), bill payment (reminder + approved link only; Robin never pays), grocery ordering (official Zepto route), SMS reading (only as default SMS app; notification access is the substitute), sibling plan, document vault with due dates, first-hour recovery playbook automation, human rescue desk (docs/ROBIN_RESCUE_DESK_PILOT.md), bank/insurer partnerships. Each needs its own ticket and the same definition of done.
