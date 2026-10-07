# Friday — Architecture (Phase 1)

> Source of truth for product decisions: `docs/BRIEF.md`. This document is the source
> of truth for **how** we build it. Code-level contracts live in `friday/core/`
> (`models.py`, `interfaces.py`, `container.py`) — when this doc and the code disagree,
> the code wins and this doc gets fixed.

## 1. Principles

1. **Channel-agnostic core.** WhatsApp can be lost (Meta's AI-assistant policy).
   Nothing outside `friday/channels/` knows about WhatsApp. All messages arrive as
   `InboundMessage` and leave as `OutboundMessage`.
2. **Everything external is a Protocol with a real and a simulated implementation.**
   LLM, telephony, STT, TTS, audio classifier, WhatsApp, SMS/DLT, places directory,
   geocoder, hotel API, official care numbers, number verifier, document extraction.
   `FRIDAY_MODE=simulator` (the default) runs the whole product end-to-end with
   **no API keys**.
3. **Goal-driven calls, not scripts.** The task engine turns a task into a `CallBrief`
   (goal + constraints + budget + approvals + what may be disclosed). The brain's
   `CallPolicy` decides each turn. Task types are *data* (`BriefTemplate`), not code
   branches.
4. **Trust > autonomy, enforced in code, not only in prompts.** Fixed AI disclosure
   line (spoken by the runner itself), `CallBrief.can_commit()` gate on bookings,
   `friday.core.safety` blocks OTP/PIN/CVV/unapproved numbers on every utterance and
   DTMF key, consent checks before messaging circle members, full audit log.
5. **Async-first, DI over globals.** Every component is built by the `Container`
   from a factory; business logic takes a `Clock` (never `datetime.now()`).
6. **Time:** stored and passed as aware **UTC**; converted to **IST** only for display
   and IST rules (quiet hours, business hours, briefing time).
7. **Brain is pure.** No DB, no sending, no sleeping. Backend builds a
   `ConversationContext` snapshot, calls the brain, then acts on the result.

## 2. Components & ownership

```
                         ┌──────────────────────────── friday/core (EM) ───────────────────────────┐
                         │ config · models · interfaces · events · clock · safety · container · log │
                         └───────────────▲───────────────────▲───────────────────▲──────────────────┘
                                         │ imports only      │                   │
 ┌──────────── Backend Eng ─────────────┐│  ┌──── AI Eng ────┐│  ┌── Voice Eng ───┐│
 │ api/        FastAPI, webhooks, /sim  ││  │ brain/          ││  │ voice/          │
 │ channels/   WhatsApp, SMS-DLT, sim,  │└──│  llm, fake_llm  │└──│  telephony/*    │
 │             notifier (24h, consent)  │   │  service (Brain)│   │  simulator      │
 │ tasks/      task engine, fan-out,    │   │  templates/     │   │  stt/* tts/*    │
 │             approvals, retries,      │   │  prompts/       │   │  classifier     │
 │             recurrence, queue        │   │  extraction     │   │  session (runner)
 │ proactive/  triggers + guardrails    │   └─────────────────┘   │  http (router)  │
 │ discovery/  places, geocoder, hotels,│                         └─────────────────┘
 │             official numbers, verify │   friday/simworld/ (EM loader, QA data): shared
 │ db/         tables (after hand-off), │   fake businesses for every simulator
 │             repositories             │
 └──────────────────────────────────────┘
```

Dependency rule: `api → tasks/proactive/channels/discovery → core`; `tasks → (via
container) brain, voice, channels, discovery`; `brain → core`; `voice → core`
(voice receives the brain as a `CallPolicy`/`Translator` and callbacks; it never
imports `friday.brain` or `friday.tasks`). **No package imports another engineer's
package directly** — cross-package access goes through `container.get(...)` and the
Protocols in `friday/core/interfaces.py`.

## 3. Key flows

### 3.1 WhatsApp message → task → call → user approval → confirmation call-back → result

```
User (WhatsApp)               Backend (api/channels/tasks)     Brain (AI)             Voice (runner)          Business
 │ "book haircut at Looks      │                               │                      │                        │
 │  tmrw evening for papa"     │                               │                      │                        │
 ├─────────────────────────────► POST /webhooks/whatsapp       │                      │                        │
 │                             │ verify sig → InboundMessage   │                      │                        │
 │                             │ (voice note: fetch_media →    │                      │                        │
 │                             │  stt.transcribe → .text)      │                      │                        │
 │                             │ user lookup, last_inbound_at, │                      │                        │
 │                             │ onboarding? → onboarding_turn │                      │                        │
 │                             │ ConversationContext ──────────► interpret()          │                        │
 │                             │◄──────── Interpretation ──────┤ (resolve_references: │                        │
 │                             │ NEW_TASK → Task(requester,    │  papa → Person)      │                        │
 │                             │  beneficiary=papa, spec,      │                      │                        │
 │                             │  delegation=none)             │                      │                        │
 │◄─ "On it, calling Looks" ───┤ PLANNING: autonomy, abuse     │                      │                        │
 │                             │ limit (ops, off), NumberVerif.│                      │                        │
 │                             │ business hours → SCHEDULED?   │                      │                        │
 │                             │ build_call_brief ─────────────►                      │                        │
 │                             │◄────────── CallBrief ─────────┤                      │                        │
 │                             │ CALLING: runner.run(brief, ask_user, notify_user) ───►                        │
 │                             │                               │  place_call ───────────────── ring ──────────►│
 │                             │                               │  speak(disclosure) ──────────────────────────►│
 │                             │                               │◄ next_call_action ───┤◄ "4 ya 6 baje?"        │
 │                             │                               │ SAY "Main Rahul se   │                        │
 │                             │                               │  confirm karke call  ├──── speak ────────────►│
 │                             │                               │  back karti hoon"    │                        │
 │                             │                               │ HANGUP(PENDING_      │                        │
 │                             │◄──────────── CallResult (offer: 4pm/6pm, ₹400) ──────┤ hangup, recording      │
 │◄─ "Looks has 4pm or 6pm,  ──┤ AWAITING_APPROVAL             │                      │                        │
 │    ₹400. Book which?"       │ buttons a:<task>:… / q:<id>:i │                      │                        │
 │    [4pm] [6pm] [Neither]    │                               │                      │                        │
 ├── taps [6pm] ───────────────► CONFIRMATION_CALLBACK         │                      │                        │
 │                             │ brief.approved_terms="6pm ₹400"                      │                        │
 │                             │ runner.run(brief…) ──────────────────────────────────► call back ────────────►│
 │                             │                               │ SAY "6pm confirm     │ can_commit ✓ safety ✓  │
 │                             │                               │  kar dijiye" (commits)├──── speak ───────────►│
 │                             │◄──────────── CallResult(SUCCESS, quote) ─────────────┤                        │
 │                             │ save call/transcript/quote;   │                      │                        │
 │                             │ summarize_call ───────────────► TaskResult           │                        │
 │◄─ summary, details,     ────┤ COMPLETED; vendor memory;     │                      │                        │
 │    recording, next steps    │ reminder + follow-up nudges;  │                      │                        │
 │                             │ business-touch SMS (DLT) ────────────────────────────────────────────────────►│
```

Notes
* **Approval rule (founder decision, final).** Default `ApprovalMode.CALLBACK`: Friday
  never confirms on the first call. She says she will call back after checking with
  the user, ends with outcome `PENDING_APPROVAL` → task `AWAITING_APPROVAL` → user
  approves (or picks another option) → `CONFIRMATION_CALLBACK` call with
  `CallBrief.approved_terms` → confirm. **Exception:** an explicit `Delegation`
  given with the task ("any slot 5–7pm under ₹800, you decide") lets her confirm on
  the call strictly within its limits; anything outside → call-back flow. Recurring
  rules carry their own `Delegation` used for every instance.
* **Mid-call questions** (`ASK_USER`, reply buttons, call continues on answer) are for
  clarifications/choices that don't commit (e.g. "do you also want a beard trim?"),
  and for the opt-in `HOLD_THEN_CALLBACK` mode. Runner holds with polished hold lines.
* **Language mirroring.** Calls open in Hinglish. Every CALLEE utterance carries the
  STT-detected `language`; the policy returns `CallAction.language`; the runner speaks
  in it with `tts.voice_for(language)`.
* **Friday is female.** Feminine Hindi forms ("karti hoon", "kar rahi hoon") in all
  prompts and the fixed disclosure line; female TTS voices (`VoiceProfile.gender`).
* **Disclosure** is spoken by the runner (`brief.disclosure()`), never by the LLM.
  On IVR calls it is spoken when a human agent joins.
* **Mid-call question plumbing:** `call_questions` table; the in-flight wait is an
  `asyncio.Future` keyed by question id held by the task engine; replies arrive as
  button payload `q:<question_id>:<option_index>` or as free text that `interpret()`
  classifies as `ANSWER_QUESTION` (with `ctx.pending_question` set).
* **No user-facing usage cap in beta.** Per-call/task cost estimates (`cost_inr_est`)
  are tracked internally with ops alerts; an abuse rate-limit exists but is off by
  default (`FRIDAY_ABUSE_RATE_LIMIT_ENABLED`). Users never see cap messaging.

### 3.2 Call session loop (voice runner)

```
run(brief, ask_user, notify_user):
  leg = telephony.place_call(req) ; status = leg.wait_for_answer()
  if status != ANSWERED → CallResult(outcome = BUSY|NO_ANSWER|VOICEMAIL|FAILED)
  heard = leg.listen()                      # IVR prompt? human? hold music?
  if human: speak(disclosure)
  loop until HANGUP / max_duration / CallEnded:
      action = policy.next_call_action(brief, transcript, answers)       # fast model
      guard:  safety.check_speech/check_keys ; commits_booking ⇒ brief.can_commit
              (blocked → SYSTEM turn "BLOCKED: …", ask policy again)
      SAY / HANGUP   → leg.speak(text, action.language)
      PRESS_KEYS     → leg.send_dtmf(digits)
      ASK_USER       → speak(text) ; answer = await ask_user(q) with polished hold lines
                       every N s (no fillers); SYSTEM turn with answer / timeout
      WAIT_ON_HOLD   → hold-listening: NO LLM calls; loop leg.listen() until
                       audio_class ∈ {HUMAN, IVR_PROMPT} or max_hold_s → HOLD_TIMEOUT;
                       notify_user("still on hold, ~8 min") every hold_user_update_interval_s
      BRIDGE_USER    → user_leg = leg.add_participant(brief.user_phone) ; leg.leave()?
      WAIT           → listen again
      (TRANSLATOR mode: listen on both legs, translator.translate(), speak to call)
      transcript += turns ; bus.publish(CallTurnRecorded)
  → CallResult(dial_status, outcome, transcript, quotes, care, languages_heard,
               recording_url, hold_seconds, …)
```

### 3.3 Discovery → shortlist → parallel calls → comparison → booking (A4, A9, B14)

```
"find a good AC repair guy near mom's place, under ₹800"
  interpret → TaskSpec(type=QUOTE|DISCOVERY, discovery_query, location, budget, fan_out)
  engine (parent task): DISCOVERING
     geocoder.geocode(place) → directory.search(query, location, near) → details(top N)
     number_verifier.verify(each phone)   (drop SCAM, flag SUSPICIOUS)
     brain.shortlist(ctx, spec, candidates, n) → [ShortlistItem(reason)]
     notify user: shortlist with reasons (+ approval if autonomy < 3)
  WAITING_CHILDREN: child tasks (one per target), FanOutPolicy:
     SEQUENTIAL  – each child brief gets competing_quotes from earlier children
     PARALLEL    – asyncio.Semaphore(concurrency) ∩ global max_concurrent_calls
     FIRST_MATCH – cancel remaining children when one succeeds (stock hunt)
  aggregate: brain.compare_quotes(ctx, parent, quotes) → QuoteComparison + buttons
  AWAITING_CHOICE → user taps → child BOOKING task (target = chosen business,
     approved_terms = chosen offer) → CONFIRMATION_CALLBACK → COMPLETED
```

### 3.4 Customer-care / IVR call (C21–C26)

```
"Airtel broadband down 3 days, raise complaint"
  interpret → TaskSpec(type=CUSTOMER_CARE, company="Airtel", care_request=COMPLAINT)
  engine: official_numbers.lookup("Airtel","broadband") → number_verifier.verify()
          ask user to approve identifiers to share (AccountIdentifier ids → spec)
  runner: IVR prompt → policy PRESS_KEYS("2") … "enter registered mobile number"
          → PRESS_KEYS(approved id) (safety allows only approved values)
          → hold music → WAIT_ON_HOLD (no LLM) → human → disclosure → complaint
          → OTP demanded → BRIDGE_USER (patch-in) or HANGUP NEEDS_USER_VERIFICATION
          → capture CareOutcome(ticket, agent, promised_date, escalation_level)
  engine: TaskResult.care → follow_up_at = promised_date + grace → proactive /
          scheduled STATUS_CHASE call; escalation guidance as text only.
```

### 3.5 Hotel / stay (D27–D29)

```
interpret → TaskSpec(type=HOTEL_BOOKING, stay=StayRequest)
engine: hotels.search(stay) + directory reviews → brain.shortlist
        child calls to properties (brief.stay, brief.api_offer = online rate to beat):
        availability, room, inclusions, negotiate direct rate, ask to HOLD the room
        → comparison → user approves → confirmation call-back (or on-call if delegated):
            DIRECT_HOLD (property holds against user's own payment; confirmation by
            WA/SMS to user) | PAY_AT_HOTEL via hotels.book() | BOOKING_LINK sent to user
        → HotelBooking persisted → child RECONFIRM task scheduled day before check-in
        (hotel_reconfirm_hour_ist). Modify/cancel by call or hotels.modify/cancel.
No payments; no scraping.
```

### 3.6 Proactive loop

```
ProactiveEngine (asyncio task, every proactive_tick_s, uses Clock)
  triggers → NudgeCandidate(dedupe_key, urgency, category, person_id?)
     task reminders (appointment in 2h) · follow-ups (plumber came?) · date facts
     (rent due, insurance, Dad's BP check) · patterns (haircut every ~4w) ·
     recurring due (A12) · care promised-date passed (C25) · hotel reconfirm ·
     wellbeing alert (A13, URGENT) · morning briefing (opt-in, briefing_hour_ist)
  dedupe (nudges.user_id+dedupe_key unique)
  guardrails (backend, deterministic):
     autonomy[category] disabled? → suppress
     daily cap: count SENT in IST day ≥ proactive_daily_cap and urgency==NORMAL → suppress
     quiet hours 22–08 IST and urgency != SAFETY → SCHEDULED for next_quiet_hours_end
     ignore-learning: ≥ N consecutive IGNORED of this kind → back off / suppress
     recipient is a circle member → Person.contact_consent must be OPTED_IN
  brain.judge_nudge(ctx, candidate) → NudgeDecision(send, text, buttons, proposed_task)
     every sent nudge offers an action (buttons n:<nudge_id>:<action>)
  autonomy level: 1 inform · 2 suggest · 3 act on "Yes" · 4 create task directly
  notifier.send: inside 24h window → free-form; outside → WhatsApp template
  feedback: button / reply → ACTED/DISMISSED/STOP; no reply in window → IGNORED
```

### 3.7 Onboarding (chat)

`OnboardingStep`: INVITE_CODE → NAME → CITY → LANGUAGE → TONE → CONSENT (DPDP "I agree",
stored as `Consent` with evidence text) → PIN (4 digits, hashed by backend, never
stored raw) → CIRCLE (optional) → PLACES (optional) → FIRST_TASK → DONE.
Brain proposes `next_step` and extracted values; backend validates and persists.
`FRIDAY_ADMIN_PHONES` skip the invite step.

## 4. Data model

Domain models: `friday/core/models.py` (pydantic). ORM: `friday/db/tables.py`.
IDs are 32-char uuid4 hex. Enums stored as strings. Nested value objects as JSON.

| Table | Purpose / key columns |
|---|---|
| `users` | phone (E.164, unique), status, onboarding_step, pin_hash, invites_remaining, rate_limited (ops-only), last_inbound_at (24h window) |
| `profiles` | name, city, language, tone, morning_briefing, briefing_hour_ist |
| `consents` | DPDP & per-feature consents; `person_id` for circle-member opt-ins; evidence text |
| `invites` | code, created_by, redeemed_by |
| `autonomy_settings` | (user, category) → level 1–4, enabled |
| `people` | circle: owner, name, relation, aliases, phone, language, **private** notes, contact_consent, checkin_consent, linked_user_id |
| `places` | owner, label, aliases, address, lat/lng, source (typed/voice/maps_link/wa_location), person_id |
| `businesses` | shared across users: phone, category, hours (JSON), best_call_times, whatsapp_phone, ivr_notes, is_customer_care, verification, directory ids, rating |
| `vendor_interactions` | per-user vendor memory: quoted/paid/no-show/rating/notes |
| `account_identifiers` | care-call identifiers, **encrypted**; never OTP/PIN/CVV/password |
| `facts` | memory: kind, key, value, due_on, recurrence, person_id |
| `messages` | every inbound/outbound message (any channel, users/people/businesses) |
| `tasks` | requester_user_id, beneficiary_person_id, place_id, parent_task_id, type, status, spec/target/result/recurrence/delegation (JSON), attempts, next_attempt_at, next_run_at, approved_terms, cost_inr_est |
| `calls` | one row per attempt: provider ids, dial_status, outcome, mode, care (JSON), hold_seconds, languages_heard, recording_url |
| `call_turns` | transcript (seq, speaker, text, language, confidence) |
| `call_questions` | mid-call questions + answers (purpose, approves) |
| `quotes` | structured quotes per call (amount, original, inclusions, validity, slots) |
| `hotel_bookings` | held/linked/confirmed stays |
| `nudges`, `nudge_feedback` | proactive messages and reactions (unique user+dedupe_key) |
| `audit_log` | append-only action log; survives "delete everything" with PII scrubbed |

Task state machine (`TaskStatus`):

```
CREATED → PLANNING ─┬─→ NEEDS_INFO ──(user replies)──→ PLANNING
                    ├─→ AWAITING_APPROVAL ──(yes)──→ SCHEDULED/CALLING
                    ├─→ DISCOVERING → WAITING_CHILDREN → AWAITING_CHOICE → (child BOOKING) → COMPLETED
                    └─→ SCHEDULED (business closed / retry / recurring) ──(due)──→ CALLING
CALLING ⇄ AWAITING_USER (mid-call question)
CALLING → COMPLETED | FAILED | SCHEDULED (retryable outcome & attempts < max)
        → AWAITING_APPROVAL (PENDING_APPROVAL outcome; the default for bookings/orders)
             ──(user approves / picks)──→ CONFIRMATION_CALLBACK ─(call)─→ COMPLETED
             ──(user declines)──→ CANCELLED (Friday may notify the business politely)
any non-terminal → CANCELLED (user "cancel")
```

## 5. Provider abstraction & simulator strategy

| Interface (core) | Real impl | Simulator / fake | Resolution |
|---|---|---|---|
| `LLMClient` | Anthropic (`claude-opus-5-5`; calls use `claude-haiku-5-5`) | deterministic fake keyed on `purpose` | real if key present |
| `TelephonyProvider`/`CallLeg` | Twilio (Exotel/Plivo stubs) | `voice/simulator` reading `simworld` personas, IVR trees, hold queues, conference | **live mode only** |
| `STTProvider` | Sarvam / Deepgram | fake (text passthrough) | real if key present |
| `TTSProvider` | Sarvam / ElevenLabs | fake (text as bytes) | real if key present |
| `AudioClassifier` | heuristic/ML on audio | simulator emits classes | n/a |
| `MessagingChannel` | WhatsApp Cloud API | in-memory simulator channel + CLI/HTTP | **live mode only** |
| `SMSProvider` | MSG91 (DLT) | fake (records sends) | **live mode only** |
| `BusinessDirectory` | Google Places (New) | `simworld` | real if key present |
| `Geocoder` | Google Geocoding | `simworld.places` | real if key present |
| `HotelProvider` | Expedia Rapid (stub ok) | `simworld` hotels | **live mode only** (book has side effects) |
| `OfficialNumberDirectory` | curated JSON data | `simworld` (official=true) | n/a |
| `NumberVerifier` | official dir + listings + call history + scam list | `simworld` (scam=true) | n/a |
| `DocumentExtractor` | LLM vision | fake from filename/meta | follows LLM |

Rules: side-effecting providers (calls, messages, SMS, hotel bookings) are **always
simulated in simulator mode** — Friday can never phone a real business by accident.
Pure-compute/read-only providers use the real vendor whenever its key is set.
`Settings.live_problems()` lists missing credentials; the container refuses to start
in live mode if any.

**The shared simulated world** (`friday/simworld/world.json`) is the single fixture
all simulators read: the number the directory returns is the number the telephony
simulator answers, with that business's persona (language + mid-call switch, prices,
negotiation room, slots, stock, IVR tree, hold queue, busy/no-answer/callback
behaviour, "are you an AI?" question, hang-ups), so every flow in §3 runs offline and
deterministically in tests. The simulated business may additionally use the LLM
(when a key is set) for free-form replies, but the scripted path must be deterministic.

## 6. Configuration

All settings: `friday/core/config.py`; documented in `.env.example`. Friday knobs use
`FRIDAY_*`; vendor credentials use vendor names (`ANTHROPIC_API_KEY`,
`TWILIO_AUTH_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `GOOGLE_PLACES_API_KEY`,
`EXPEDIA_RAPID_API_KEY`, …). Highlights:

* `FRIDAY_MODE` simulator|live; `FRIDAY_*_PROVIDER` auto|<vendor> per component.
* `FRIDAY_DATABASE_URL` (SQLite dev; `postgresql+asyncpg://` later — add `asyncpg`).
* Calls: ring/duration/attempt/backoff, hold timeout & hold-line cadence, global
  concurrency, fan-out concurrency, business-call window, IVR max hold.
* Proactive: daily cap 3, quiet hours 22–08 IST, tick, briefing hour, ignore threshold.
* Access: invite-only, 5 invites, PIN attempts, admin phones. No user-facing cap;
  `FRIDAY_ABUSE_RATE_LIMIT_ENABLED` (off) / `FRIDAY_ABUSE_MAX_CALLS_PER_DAY`,
  `FRIDAY_COST_ALERT_INR_PER_USER_MONTH` for ops.
* Voice: `FRIDAY_TTS_VOICES` per language (female voices), `FRIDAY_TTS_VOICE_GENDER=female`.
* Secrets are `SecretStr`; never log them. `FRIDAY_SECRET_KEY` mandatory in live.

## 7. Cross-cutting rules

* **Safety layer** (`friday/core/safety.py`): runner calls `check_speech` /
  `check_keys` for every utterance/key. Brain prompts must also follow the rules.
* **Minimum disclosure:** only `CallBrief.shareable_details` and
  `approved_identifiers` may be shared; `Person.notes` are private to the owner and
  never go to businesses or other circle members.
* **Consent:** DPDP consent before any task; circle members get one opt-in template
  before any message (`contact_consent`) or wellbeing call (`checkin_consent`).
* **Audit:** every state change, call, message, consent and deletion → `audit_log`.
* **Delete everything:** PIN-protected; purges user-keyed rows (cascade), keeps
  PII-free audit tombstone.
* **Logging:** `mask_phone()`; no message bodies/PII at INFO.
* **Events** (`friday/core/events.py`): `MessageReceived/Sent`, `TaskStatusChanged`,
  `CallStarted`, `CallTurnRecorded`, `MidCallQuestionAsked`, `UserAnswerReceived`,
  `CallFinished` — for audit, metrics, simulator UI. Not for request/response.

## 8. Phase 2: inbound voice (users calling Friday)

The voice pipeline is already direction-agnostic:
* `CallLeg` is the same for inbound; a provider adds `accept_inbound(webhook) -> CallLeg`
  (new Protocol method, additive) and the voice router maps the provider's inbound
  webhook to it.
* `CallSessionRunner.run(brief, ask_user, notify_user)` is reused with a brief whose
  `target` is the **user** (`TargetKind.PERSON`-like "self"), `CallDirection.INBOUND`,
  and a goal of "understand and act on the user's request". The disclosure line is
  replaced by a greeting; identity via caller-ID + PIN (DTMF, never spoken back).
* The policy's `HANGUP` result feeds `brain.interpret` the transcript as an
  `InboundMessage(channel=VOICE)`, so the rest (tasks, memory, proactive) is unchanged.
* `MessagingChannel` for `Channel.VOICE` (Friday calls the user to deliver a
  result/nudge — useful for feature phones) is a new channel impl, no core change.

## 9. Testing strategy

* Unit tests per package under `tests/<package>/`; shared fixtures in `tests/conftest.py`
  (simulator settings, in-memory SQLite, `FakeClock`, `EventBus`, `Container`).
* No test may hit the network. Real-provider tests are marked `@pytest.mark.live`
  and are skipped by default.
* QA owns `tests/e2e/`: scripted conversations through the simulator channel covering
  every flow in §3 using `simworld` personas and the fake LLM.
