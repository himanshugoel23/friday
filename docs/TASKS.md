# Friday — Phase 1 Task Breakdown

Read first: `docs/BRIEF.md` (what), `docs/ARCHITECTURE.md` (how), then the contracts in
`friday/core/` — **`models.py`, `interfaces.py`, `container.py` (factory paths)**.

Priorities: **P1** = needed for the Phase-1 launch slice; **P2** = Phase-1 scope, after P1
works end to end. Per founder decisions: scam check (B16) and warm transfer/three-way
(B17) are **P1**; translator mode (B18) and the B-section items 16-18 otherwise P2.

**Founder decisions baked into the contracts (final):**
1. *Approval rule:* default = no confirmation on the call → `PENDING_APPROVAL` →
   `AWAITING_APPROVAL` → user approves → `CONFIRMATION_CALLBACK` call with
   `approved_terms`. Only an explicit `Delegation` (on `TaskSpec`/`Task`/`CallBrief`,
   or a recurring rule's `RecurrenceRule.delegation`) allows confirming on the call,
   within its limits. `CallBrief.can_commit()` encodes this.
2. *No user-facing usage cap in beta:* internal `cost_inr_est` tracking + ops alerts;
   abuse rate-limit is ops-configurable and **off by default**.
3. *Friday is female:* feminine Hindi forms everywhere; female TTS voices.

## 0. File ownership (disjoint — do not edit files you don't own)

| Path | Owner | Notes |
|---|---|---|
| `friday/core/**` | EM | **Frozen.** Import only. See "Changing core" below. |
| `friday/simworld/__init__.py` | EM | Loader/schema, frozen (additive only). |
| `friday/simworld/world.json` | QA | Everyone may **append** businesses/places; don't edit others' entries. |
| `friday/brain/**` | AI Eng | llm, fake_llm, service, templates/, prompts/, extraction, translator. |
| `friday/voice/**` | Voice Eng | telephony/*, simulator, stt/*, tts/*, classifier, session, http, sim_data/. |
| `friday/channels/**` | Backend Eng | whatsapp, simulator channel, sms, notifier, cli (simulator chat). |
| `friday/discovery/**` | Backend Eng | directory, geocoder, hotels/, official_numbers (+ data), verify. |
| `friday/tasks/**` | Backend Eng | task engine. |
| `friday/proactive/**` | Backend Eng | triggers, scheduler, guardrails. |
| `friday/api/**` | Backend Eng | FastAPI app, webhooks, /sim endpoints. |
| `friday/db/**` | Backend Eng (after hand-off) | tables.py may be extended; repositories/ new. |
| `friday/cli.py` | QA | finalise run commands. |
| `tests/core/**`, `tests/conftest.py` | EM | Add fixtures in your own `tests/<pkg>/conftest.py`. |
| `tests/brain/**` | AI Eng | |
| `tests/voice/**` | Voice Eng | |
| `tests/{channels,discovery,tasks,proactive,api,db}/**` | Backend Eng | |
| `tests/e2e/**` | QA | |
| `pyproject.toml` | shared | Add deps **only** with `uv add <pkg>` (never hand-edit others' lines). |
| `README.md` | QA | |
| `docs/ARCHITECTURE.md`, `docs/TASKS.md` | EM | Propose edits in `docs/CORE_CHANGES.md`. |
| `docs/VISION.md`, `docs/PRD.md` | PM | |

**Factory contract.** Each engineer provides exactly the callables listed in
`friday/core/container.py::FACTORIES`, signature `def build_x(c: Container) -> Impl`.
Pull dependencies from the container (`c.settings`, `c.clock`, `c.bus`, `c.db`,
`c.llm`, `c.brain`, …) — never import another engineer's package.

**Changing core.** Core is frozen so three people can work in parallel. If you
genuinely need a change, write it in `docs/CORE_CHANGES.md` (append-only: what, why,
exact diff). Only *additive* changes are acceptable (new optional fields with
defaults, new enum members, new Protocols). Until merged, define what you need
locally in your package (e.g. subclass a model).

**Definition of done (every task):** code + tests in your `tests/<pkg>/`, `uv run pytest`
and `uv run ruff check .` green, no network in tests, works in simulator mode with
no keys, logs without PII.

---

## 1. AI Engineer — `friday/brain/`

| # | Pri | Task | Acceptance criteria | Depends on |
|---|---|---|---|---|
| AI-1 | P1 | **LLM clients**: `llm.py::build_anthropic_llm` (official `anthropic` SDK, async, `claude-opus-5-5` default / `llm_fast_model` for call turns, structured outputs for `json_schema`, image/PDF `attachments`, retries, token/cost logging per `purpose`; no `temperature`/`budget_tokens` — models reject them) and `fake_llm.py::build_fake_llm` (deterministic, rule/fixture-based per `purpose`, records calls). | Both satisfy `LLMClient` (`isinstance` with runtime Protocol). Fake returns identical output for identical input. Live test marked `@pytest.mark.live`. | core |
| AI-2 | P1 | **Persona & prompts** (`prompts/`): Friday is **female** — feminine Hindi forms ("karti hoon", "bata rahi hoon"); character (witty, warm, concise, calm), formal/playful tone, Hindi/English/Hinglish, honesty about being AI, never commit money, safety rules, minimum disclosure, notes privacy. | Prompt snapshot tests; tone switch changes output in fake. | AI-1 |
| AI-3 | P1 | **`interpret()`**: intents incl. NEW_TASK for all `TaskType`s, ANSWER_QUESTION (uses `ctx.pending_question`), APPROVE/REJECT, CHOOSE, CANCEL, REMEMBER (facts + `due_on` + recurrence), ADD_PERSON/ADD_PLACE, SETTINGS (tone, language, autonomy, briefing), STATUS, DELETE_DATA (`requires_pin`), INVITE, SAVE_IDENTIFIER (refuse OTP/PIN/CVV), RATE_VENDOR, HELP. Hinglish + voice-note transcripts. Fills `TaskSpec.missing` instead of guessing. Extracts an explicit `Delegation` ("you decide", time window, price ceiling, user's literal words) — never infers one. | ≥40 table-driven cases (EN/HI/Hinglish) pass on the fake path; schema-validated JSON on the real path. | AI-1, AI-2 |
| AI-4 | P1 | **`resolve_references()`** + alias learning: "papa", "mummy ke ghar ke paas", "near my office", "his place" (from `ctx.recent`); ask once when ambiguous with ≤3 buttons; propose `new_aliases`. | Cases for people, places, pronouns, ambiguity, unknown → None. | AI-3 |
| AI-5 | P1 | **`BriefTemplate` data** for every `TaskType` (`templates/*.json|yaml`) + `template_for()`; **`build_call_brief()`**: goal, constraints, budget/negotiation, approval policy, beneficiary + `shareable_details` (minimum), location context, vendor history, competing quotes, approved identifiers, stay/api_offer, mode. | Every TaskType has a template (test iterates the enum). Briefs never contain `Person.notes` unless allowed. | AI-3 |
| AI-6 | P1 | **`next_call_action()` (CallPolicy)**: goal-driven; mirrors callee language; asks for quotes, clarifies inclusions, negotiates within budget/`NegotiationPolicy`; ASK_USER(APPROVE_BOOKING) before any commitment; `commits_booking` flag; handles busy-ish replies, call-back-later (`CALLBACK_LATER` + time), "are you an AI?" honestly; IVR menus → PRESS_KEYS/SAY, WAIT_ON_HOLD on hold/queue, agent path preference; verification demand → BRIDGE_USER or NEEDS_USER_VERIFICATION; CareOutcome capture; ends with HANGUP + outcome + quote/care. Default: **never confirm on the first call** — say she'll call back after checking with the user, HANGUP `PENDING_APPROVAL` with the offer in `quote`/`collected`; confirm only on a confirmation call-back (`approved_terms`) or within an explicit `Delegation`'s limits (price/time/scope); outside limits → call-back. Uses fast model, p95 < 1.5 s. | Scripted transcript tests (fake) for: offer → PENDING_APPROVAL (default), confirmation call-back, delegated on-call booking within limits and refusal outside them, slot choice, callback-later, negotiation (no deal above max), language switch mid-call, IVR navigation, hold, OTP demand, AI question. | AI-5 |
| AI-7 | P1 | **`summarize_call()`** → `TaskResult` (summary in user language/tone, details, `appointment_at`, `follow_up_at`, quotes, care, alert for wellbeing, vendor interactions, business-touch `TemplateRef`, retry suggestion) and **`compare_quotes()`**. | Outcome-specific tests (success, busy, declined, pending approval, care ticket). | AI-6 |
| AI-8 | P1 | **`shortlist()`**: rank candidates by rating, review count, review text, distance, vendor history; drop no-phone; short user-facing reasons. | Deterministic on simworld AC-repair set. | AI-1 |
| AI-9 | P1 | **`onboarding_turn()`** for every `OnboardingStep` (incl. optional CIRCLE/PLACES, first task "one call you've been avoiding"); consent only on explicit agreement; PIN extracted, never echoed. | Step-by-step tests incl. refusal of consent and invalid PIN. | AI-3 |
| AI-10 | P1 | **`judge_nudge()`**: send/no-send + copy with an action, template params for outside-24h, `proposed_task`. | Tests per `NudgeKind`. | AI-3 |
| AI-11 | P1 | **`DocumentExtractor`** (`extraction.py`): menus/price lists/quote photos/PDFs → `ExtractedDocument` via vision; fake from filename/metadata. | Fake + live-marked test. | AI-1 |
| AI-12 | P2 | **`translate()`** for translator mode; meaning-preserving, keeps numbers/names. | Hindi↔English, Marathi→Hinglish cases. | AI-1 |
| AI-13 | P2 | Simulated-business LLM persona helper (optional, for Voice simulator free-form replies) exposed as a plain function taking an `LLMClient`. | Deterministic when the fake LLM is used. | AI-1 |

## 2. Voice Engineer — `friday/voice/`

| # | Pri | Task | Acceptance criteria | Depends on |
|---|---|---|---|---|
| V-1 | P1 | **Telephony simulator** (`simulator.py::build_simulated_telephony`): `CallLeg`s driven by `simworld` personas — answers/busy/no-answer/voicemail/callback-later, language + mid-call switch, prices/slots/stock/negotiation room, room holds, asks-if-AI, hang-ups, **IVR trees with DTMF, hold queues (hold music/queue announcements → human)**, OTP demands, conference (`add_participant`, `leave`), recording URL to a local file. Deterministic (seeded). | Tests drive each persona via `CallLeg` directly. Unknown numbers → NO_ANSWER. | core, simworld |
| V-2 | P1 | **`CallSessionRunner`** (`session.py::build_call_runner`): §3.2 loop — disclosure first (to a human), language mirroring, ASK_USER with polished hold lines (no fillers) and `hold_timeout_s`, WAIT_ON_HOLD hold-listening with **zero** policy calls and `notify_user` updates, PRESS_KEYS, BRIDGE_USER, max duration, `friday.core.safety` + `can_commit` guards (block → SYSTEM turn → re-ask), outcomes mapping, transcript/quotes/care/languages/hold_seconds in `CallResult`, bus events. Never raises on call failure. | With a stub `CallPolicy` + simulator: every outcome in `CallOutcome` reachable; blocked OTP never reaches `speak`; no policy calls during hold. | V-1 |
| V-3 | P1 | **STT/TTS fakes** (`stt/fake.py`, `tts/fake.py`) + **Sarvam** STT/TTS (detected language required; per-language calm **female** voices from `tts_voices`, `VoiceProfile.gender="female"`, no fillers) + Deepgram STT / ElevenLabs TTS. | Protocol conformance tests; live tests marked. | core |
| V-4 | P1 | **Twilio provider** (`telephony/twilio.py`): place call via REST, Media Streams WebSocket (μ-law 8 kHz) ↔ streaming STT/VAD/TTS inside `CallLeg`, DTMF, recording, status callbacks, conference for `add_participant`/`leave`. `http.py::build_router` exposes webhooks/WS (mounted by API at `/voice`). Exotel/Plivo: stubs raising `ProviderError`. | Unit tests with recorded webhook payloads; signature validation; live test marked. | V-2, V-3 |
| V-5 | P1 | **AudioClassifier** (`classifier.py`): heuristic (music/tone energy, speech rate, keyword spotting "your call is important", beep) → `AudioClass`; used by real legs. | Fixture audio tests (synthetic tones/silence). | V-3 |
| V-6 | P1 | **Voice-note path helper**: convert WhatsApp OGG/Opus → STT input format (used by Backend via `c.stt`). | OGG fixture transcribes on fake path. | V-3 |
| V-7 | P1 | **Warm transfer / three-way** end to end in simulator + Twilio conference. | Simulator test: BRIDGE_USER → user leg joins → Friday leaves → outcome TRANSFERRED. | V-2 |
| V-8 | P2 | **Translator mode** loop (`CallMode.TRANSLATOR`) using `Translator`. | Simulator test with Marathi persona. | V-2, AI-12 |
| V-9 | P2 | Latency budget instrumentation (STT→policy→TTS per turn) + metrics events. | p95 turn latency logged per call. | V-4 |

## 3. Backend Engineer — channels, tasks, proactive, api, discovery, db

| # | Pri | Task | Acceptance criteria | Depends on |
|---|---|---|---|---|
| B-1 | P1 | **Repositories** (`db/repositories/`, `build_repositories(c)` returning a bundle with `tasks, users, people, places, businesses, identifiers, facts, nudges, messages, consents, invites, audit, …`) implementing core repository Protocols; identifier values encrypted with `secret_key`. | Round-trip tests for every model ↔ row. | core |
| B-2 | P1 | **Simulator channel + CLI** (`channels/simulator.py`, `channels/cli.py:main`): in-memory `MessagingChannel`, renders buttons as numbered choices, location pins (`/pin lat,lng`), voice notes (`/voice text`), multiple users and businesses; `/sim/*` HTTP endpoints. | `uv run friday chat` works with no keys. | B-1 |
| B-3 | P1 | **WhatsApp Cloud adapter** (`channels/whatsapp.py`): webhook GET verify + POST signature (`X-Hub-Signature-256`), parse text/voice/button/location/contact/image/document, send text/buttons (≤3, ≤20 chars)/templates/media, `fetch_media`, status callbacks. | Fixture payload tests; live marked. | core |
| B-4 | P1 | **Notifier** (`channels/notifier.py`): choose channel; 24h window (`last_inbound_at`) → template fallback; circle-member consent gate; business messaging (B15); logs `messages`; DLT **SMS** adapter (`channels/sms.py`: fake + MSG91) for business touch & user fallbacks. | Window/consent/template tests with FakeClock. | B-1, B-3 |
| B-5 | P1 | **Inbound pipeline + users**: user lookup/creation, invites (5/user), waitlist, onboarding state machine (with `brain.onboarding_turn`), DPDP consent records, PIN hash/verify/lockout, **no user-facing cap**: per-user cost tracking (`cost_inr_est` roll-ups, ops alert at `cost_alert_inr_per_user_month`) + abuse rate-limit (`abuse_rate_limit_enabled`, default off, never messaged as a "cap"), "delete everything" (PIN) purge, context builder (`ConversationContext`), dispatch on `Interpretation`, people/places upsert (geocode), identifiers, vendor ratings. | Scenario tests with fake brain. | B-1, B-2 |
| B-6 | P1 | **Task engine** (`tasks/engine.py`): state machine (ARCHITECTURE §4) incl. **`PENDING_APPROVAL` → `AWAITING_APPROVAL` → `CONFIRMATION_CALLBACK`** (approved_terms, "relay a different choice", decline → polite cancel), delegation pass-through (task/recurring rule → brief), approvals (autonomy), AskUser futures (`q:` buttons, timeout), NotifyUser, retries/backoff, business-hours-aware queue (`BusinessHours.next_open`, default call window, lunch avoidance), global + per-parent concurrency, parent/child **fan-out SEQUENTIAL/PARALLEL/FIRST_MATCH**, aggregation via `compare_quotes`, AWAITING_CHOICE → booking child, PENDING_APPROVAL → confirm call, recurring schedules (`RecurrenceRule`), care follow-ups at promised date, hotel reconfirm day-before, wellbeing check-ins (checkin consent), vendor memory writes, business touch. | Engine tests with stub `CallSessionRunner` + FakeClock covering every transition; stock hunt cancels siblings on first match. | B-1, B-4 |
| B-7 | P1 | **Discovery** (`discovery/`): simworld directory + geocoder simulators; Google Places (New) text search/details (phone, rating, reviews, hours) and Geocoding + maps-link resolution; **official numbers** data + loader; **NumberVerifier** (official dir, listings consistency, call history, scam list; simulator via simworld). | Simulator tests; recorded-payload tests for Google; live marked. | core, simworld |
| B-8 | P1 | **Hotels** (`discovery/hotels/`): simulator (simworld hotels: rates, pay-at-hotel, links) + Expedia Rapid stub (auth signature, search/details wired; book/cancel may raise `ProviderError("not enabled")`). | Protocol conformance + simulator tests. | core |
| B-9 | P1 | **Proactive engine** (`proactive/engine.py`): asyncio tick loop on Clock, all triggers in ARCHITECTURE §3.6, guardrails (cap 3/IST day, quiet hours with SAFETY exception, autonomy levels, ignore-learning, consent, dedupe), `judge_nudge`, feedback capture. | FakeClock tests per trigger & guardrail. | B-1, B-4 |
| B-10 | P1 | **API** (`api/app.py::create_app`): lifespan builds Container (+ startup checks), `/health`, `/webhooks/whatsapp`, `/sim/*`, mounts `voice_router` at `/voice` if available, starts proactive loop + engine queue workers. | `TestClient` tests; app boots with no keys. | B-3, B-6, B-9 |
| B-11 | P1 | Number verifier advanced signals (multiple-listing cross-check, past-call history weighting), user warnings UX. | Tests with simworld scam/suspicious numbers. | B-7 |

## 4. QA Engineer

| # | Pri | Task | Acceptance criteria | Depends on |
|---|---|---|---|---|
| QA-1 | P1 | Finalise `friday/cli.py` + README run commands (`friday chat`, `friday serve`, `friday check`). | Fresh clone → `uv sync && uv run friday chat` works offline. | B-2, B-10 |
| QA-2 | P1 | Grow `simworld/world.json` to cover every TaskType and edge case (busy, voicemail, callback, hang-up, language switch, IVR wrong branch, OTP demand, scam number, closed hours, stock hit/miss, hotel hold). | Loader test + coverage table in `tests/e2e/README`. | — |
| QA-3 | P1 | **E2E suites** (`tests/e2e/`) through the simulator channel with fake LLM: onboarding; booking → PENDING_APPROVAL → user approval → confirmation call-back; delegated booking confirmed on the call; mid-call clarification question; warm transfer; callback-later retry; discovery → parallel quotes → comparison → booking; stock hunt first-match; recurring booking; wellbeing check-in with consent; customer-care IVR + hold + ticket + follow-up; hotel hybrid + reconfirm; proactive cap/quiet hours; delete everything. | All green in CI time < 60 s; no network. | all P1 |
| QA-4 | P1 | Safety regression suite: disclosure always first, never OTP/PIN/CVV, never commit without approval, notes never leak, consent gates, quiet hours. | Fails loudly on any regression. | V-2, B-4, B-6 |
| QA-5 | P2 | Metrics harness from simulator runs: task success rate, hang-up rate, est. cost/call. | Report printed by a CLI command. | QA-3 |

## 5. Suggested sequencing (parallel)

```
Week 1   AI: AI-1, AI-2, AI-3        Voice: V-1, V-3 fakes       Backend: B-1, B-2, B-7 sims
Week 2   AI: AI-5, AI-6, AI-8        Voice: V-2                   Backend: B-4, B-5, B-6
Week 3   AI: AI-7, AI-9, AI-10, AI-11 Voice: V-3 real, V-4, V-5, V-6 Backend: B-3, B-8, B-9, B-10
Week 4   P2 items + QA-3/QA-4 hardening, live smoke tests with real keys
```

Integration seams to agree on early (all already typed in core): `CallBrief` ↔
`CallPolicy` (AI ↔ Voice), `CallSessionRunner.run(brief, ask_user, notify_user)`
(Voice ↔ Backend), `ConversationContext` → `Interpretation` (Backend ↔ AI),
`simworld` (Voice ↔ Backend ↔ QA).
