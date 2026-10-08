# QA report - Friday (simulator build)

Date: 2026-10-08. Scope: everything runs offline on the simulator (fake LLM, simulated telephony /
WhatsApp / SMS / directory / hotels). **Nothing was verified against a live provider.**

## 1. Results

| Suite | Result |
|---|---|
| Full `uv run pytest` | 1102 passed, 28 skipped (Postgres/Redis variants), 15 strict xfails (all QA-found bugs) |
| `uv run ruff check .` | clean |
| `tests/e2e` (new, 6 files + bugs/safety/world/loadtest) | 52 passed, 15 xfailed, about 57 s, no network |
| `tests/contracts` (new, S-12) | 33 passed, 19 skipped (Postgres: `FRIDAY_TEST_PG_URL`; Redis: `FRIDAY_TEST_REDIS_URL`) |
| `tests/security` | green, **no strict xfails left**; the e2e safety suite adds one open bug (BUG-18) |

### Coverage vs the brief (QA-3)
Onboarding (consent refusal, weak PIN, mismatch, circle/places) / booking -> PENDING_APPROVAL -> approval ->
confirmation call-back / decline / no reply / disclosure on every call / delegation within and outside limits /
mid-call clarification / no-answer retries with one notification and final options / business call-back, missed
call, late call-back / discovery -> parallel quotes -> comparison -> booking / stock hunt / recurring booking /
wellbeing check-in with consent and alert / customer-care IVR, hold, ticket / hotel hybrid + reconfirm /
booking for a parent with opt-in and own-language call / location pin, saved places, "near my office" /
proactive cap and quiet hours / delete everything / number pool stickiness and pool-wide DNC.
Table of journeys and simworld coverage: `tests/e2e/README.md`. QA-2: `world.json` now has 32 entries
(two appended: closed-hours clinic, food-order restaurant with a stock miss) and `test_world_coverage.py`
asserts every edge case exists.

## 2. Load test (S-11): `uv run friday loadtest --users 1000 --calls 200`

Setup: one process with roles `api,task,voice`, SQLite file DB, simulator everything, wall-speed simulated clock
(Mon 10:30 IST), 1000 pre-onboarded users each sending one booking/enquiry through the **webhook path**
(`accept_inbound`: idempotency check, durable enqueue, 200), 10 % of webhooks delivered twice, at most 200 journeys
(= live calls) in flight; each journey taps the offer (confirmation call). Machine: the QA sandbox container.

| Metric | Value |
|---|---|
| Wall time | 692.6 s |
| Tasks / calls / outbound messages | 1000 / 1667 / 3667 |
| Throughput | 1.44 tasks/s, 2.41 calls/s, 5.29 messages/s |
| Webhook ack latency p50 / p95 | 0.2 ms / 0.3 ms |
| Call turn (policy decision) latency p50 / p95 | 9.2 ms / 15.5 ms over 5000 turns (fake LLM; live will be 20-100x) |
| Job queue depth max / p95 | 198 / 196 (about the 200 in-flight cap) |
| Final task states | 1000 completed |
| **Lost tasks / duplicate tasks / unfinished** | **0 / 0 / 0** |
| **Lost calls / duplicate calls** | **0 / 0** (100 duplicate webhooks were all dropped) |
| **Duplicate messages / users without any reply** | **0 / 0** |
| Result | **PASS** |

Estimated cost per task from the cost ledger (`CallResult.cost_inr_est`, telephony + STT/TTS + LLM estimate):

| Task type | Tasks | Avg Rs / task |
|---|---|---|
| booking (offer call + confirmation call) | 334 | 0.72 |
| healthcare | 167 | 0.72 |
| quote (packers, enquiry-style) | 166 | 0.72 |
| enquiry (single call) | 333 | 0.36 |

These are simulator estimates (short simulated calls); real PSTN minutes, hold time and the live LLM will move them.
Care calls with 7-minute holds cost about Rs 0.37 in the simulator because hold-listening makes no LLM calls.

Caveats found while building the harness: (1) a `FakeClock` shared by concurrent calls jumps whenever any call
sleeps, which expires every other call's queue lease and produces duplicate calls: use a wall-speed clock for
concurrency tests (the harness does); (2) in-memory SQLite (`StaticPool`, one shared connection) corrupts
concurrent transactions ("cannot commit transaction", FK failures in the hotel flow): use a file DB or Postgres.
Neither is a production issue. Not covered: multi-process mode, Postgres/Redis, real network latency.

## 3. Bugs found (BUG-n)

Each is a strict xfail in `tests/e2e/test_bugs.py` (or the named test). Severity for a private pilot.

| # | Sev | Where | Expected vs actual | Suggested fix |
|---|---|---|---|---|
| BUG-1 | High | `friday/brain/heuristics/policy.py` (delegated commit), `friday/voice/commit.py:slot_of` | A one-off delegation with a time window ("4-7, Rs 800 tak, aap decide karo") confirms on the call. Actual: the policy never sets `CallAction.slot_at`, `check_commit` cannot verify the window, so the booking always falls back to call-back (safe, but the delegation feature never works) | set `slot_at` from the chosen slot in the policy (and in the real prompt) Fixed (2026-10-08, brain/voice half): `CallActionOut.slot_at` added and set by the policy (with the quote amount) for an in-limits delegated confirmation; `to_call_action` carries it, the runner passes it to `check_commit` and records `collected['slot_at']`; out-of-limits still blocked (tests/brain/test_qa_bugfixes.py). Still open: `tasks/engine.py:_guard_commit` re-checks without slot_at, so the e2e test stays xfail until it reads `collected['slot_at']`. |
| BUG-2 | **Critical** | `friday/db/tables.py:TaskRow`, `db/repositories/tasks.py:_task_values/_task` | `Task.role` survives a save. Actual: no column, role is always None after a round trip, so **all fan-out flows fail with the real repositories** ("I couldn't get any offers": discovery, quotes, stock hunt, hotels, close-loop and care follow-up children). Unit tests pass only because they use in-memory fakes | add `role` column + migration (the e2e suite shims it to test the rest) |
| BUG-3 | High | `friday/api/inbound.py:ANSWERABLE_STATUSES` | Taps on the comparison buttons and on the final retry options (later/tomorrow/another) work. Actual: both were silently swallowed (task in AWAITING_CHOICE / FAILED). **Fixed by QA** (two lines, see section 5) | done |
| BUG-4 | Medium | confirmation call opening for a comparison child | The confirm call says what was approved and the business confirms. Observed: opening is garbled ("about call back Chill Point AC Repair and confirm...") and the rep answers "keep it, call me back"; Friday still reports "Ho gaya". Success is reported without an explicit confirmation | require a confirmation phrase before SUCCESS; use the booking goal, not the parent text Fixed (2026-10-08): opening no longer embeds the garbled goal text; the confirm call needs an explicit yes and treats "keep it / call me back" as not confirmed (PARTIAL), never SUCCESS. |
| BUG-5 | High | `friday/tasks/engine.py:961` `_business_target` | A named business is the one dialled. Actual: first directory hit with a phone is used with no name check ("Urban Trim Salon" dials "Looks Unisex Salon", user told Urban Trim) | fuzzy-match name (>= 0.8) else ask "Did you mean ...?" |
| BUG-6 | Low | `friday/voice/simulator.py:946` | `sim:calls_back_after` persona rings back after a missed call. Actual: only scheduled after an ANSWERED call | schedule on no-answer/busy legs too Fixed (2026-10-08): `SimCallLeg.wait_for_answer` schedules `sim:calls_back_after` after no-answer/busy/voicemail legs too (one ring-back per streak). |
| BUG-7 | Medium | `friday/tasks/engine.py:2656` `_inbound_brief` | Late call-back after cancel/resolution is closed politely. Actual: brief is built from the new child task, so the brain runs a normal enquiry (asks opening hours and price) | pass the resolved task as `related` with its real status so the close-loop script fires |
| BUG-8 | High | stock-hunt policy / `callstate` | Only a shop that confirms stock is reported. Actual: "Sorry, phir se boliye?" is recorded as `in_stock=yes` and Friday tells the user a shop has Dolo 650 when it does not | require an affirmative parse; treat a repeat request as unknown Fixed (2026-10-08): stock hunt records `in_stock=yes` only on an affirmative parse (English/Hindi/Hinglish/Marathi); repeat-requests and unclear answers re-ask once, then PARTIAL `in_stock=unknown`; negatives DECLINED. |
| BUG-9 | Medium | `friday/brain/heuristics/callstate.py` amounts | A booking reference ("LO196353") is not a price. Actual: user sees "price: Rs 1,96,353" | ignore alphanumeric references / amounts without currency cues Fixed (2026-10-08): `extract_amounts` ignores alphanumeric references and long bare numbers without a currency cue. |
| BUG-10 | High | (a) `tasks/context.py` (fixed) (b) engine/brain | A care call at an IVR asking for the registered number can share the saved identifier after the user approves. Actual: (a) the context omitted identifiers (**fixed by QA**, one line); (b) nothing ever fills `TaskSpec.approved_identifier_ids`, so the pre-call summary always says "I'll share: nothing" and the call ends in NEEDS_USER_VERIFICATION | add an "OK to share my Airtel number" step to the pre-call approval Brain/safety half verified (approved identifier reaches the brief/policy; guard accepts only it, tests in tests/brain and tests/voice). Still open (not in brain/voice): the pre-call approval step in `tasks/engine.py:_ask_call_approval/_care_summary` must offer an "OK to share my <label> number" button that fills `approved_identifier_ids`. |
| BUG-11 | Medium | care summary (`resolved` flag) | A ticket promised "within 48 hours" schedules a follow-up. Actual: summarised as resolved=True, no follow-up, yet the user is told she will follow up | resolved only when the agent says it is fixed |
| BUG-12 | Medium | reconfirm call | Day-before hotel reconfirm completes by itself. Actual: policy quotes dates/reference as digit runs, the unapproved-number guard blocks, and the user is bridged into every reconfirm | pass the reference as an approved identifier / word it |
| BUG-13 | High | `friday/api/inbound.py`, `tasks/engine.py:892`, `notifier.request_person_opt_in` | Adding a parent triggers the single opt-in template; "haan" grants consent; wellbeing needs `checkin_consent`. Actual: **nobody calls `request_person_opt_in`** and `checkin_consent` is never set to OPTED_IN anywhere (the repo ignores it on upsert), so circle messaging and wellbeing check-ins are unreachable in the product | send the opt-in when a person with a phone is first needed; record `checkin_consent` from the reply |
| BUG-14 | Low | `friday/tasks/engine.py:1780` | Offer message once. Actual: `f"{summary.summary}\n{q.text}"` repeats the question | send q.text only when equal |
| BUG-15 | Medium | location handling | After a WhatsApp pin, "yahan ke paas AC repair" searches near the pin. Actual: "yahan" is geocoded as text, "I couldn't find anyone nearby" | treat near-me phrases as "use last pin / home" Fixed (2026-10-08): `brain/heuristics/references.py` resolves near-me phrases (yahan ke paas, near me, mere paas) to the latest shared pin, else home, instead of geocoding "yahan". |
| BUG-16 | Low | `CallResult.from_number` | Caller ID recorded on the result. Actual: always None (only call memory has it) | set in `_call` |
| BUG-17 | Medium | call runner + policy | A blocked commit is wrapped up after one retry. Actual: the policy repeats the blocked line about 10 times ("Maaf kijiye, main dobara bolti hoon") and burns about 64k tokens before the call ends | after the first BLOCKED, force the call-back script Fixed (2026-10-08): policy treats any blocked commitment/delegation as the call-back route, rephrases at most once, then calls back; runner `MAX_BLOCKED_IN_A_ROW` 3 -> 2. |
| BUG-18 | Medium | `friday/api/inbound.py` (PIN gate) | "my OTP is 482913 save it" is refused ("I can't save OTPs..."). Actual: Friday asks for the PIN and the pending-PIN state swallows the user's next messages (nothing is stored, nothing echoed) | refuse before the PIN gate and clear pending state on a non-PIN message |

Other observations (no test): approval questions never expire or get a reminder and the slot hold lapses silently;
"sunday subah 10 baje" displayed a window of "2 AM" in the task acknowledgement (check IST/UTC rendering of
the window); FastAPI warns of a duplicate operation id for `sarvam_transfer` in `voice/http.py`;
the user-facing text sometimes contains the whole phrase as the category ("ac repair near mere office").

## 4. Safety regression (QA-4)

`tests/e2e/test_safety_regression.py` plus `tests/security` (about 90 tests). Mapping:

| Rule | Tests |
|---|---|
| AI disclosure first on every call | e2e `test_disclosure_is_the_first_thing_said...`, `test_booking_approval::test_every_call_opens...`, security `test_injected_policy_cannot_leak_secrets_or_claim_human` |
| Never OTP / PIN / CVV / card numbers | e2e secrets never stored/echoed; security `test_secret_or_invalid_keys_blocked`, `test_otp_as_number_words_blocked`, `test_pin_keyed_in_two_digit_chunks_blocked`, `test_card_number_disguised_as_money_blocked`, `test_safety_extraction.py` (open: BUG-18 UX) |
| No commitment without approval | e2e `test_nothing_is_committed_without_an_approval`, booking suite, delegation outside limits; security `test_flagged_commit_without_approval_never_spoken`, `test_runner_downgrades_unapproved_success`, `test_hallucinated_success_without_approval_is_downgraded`, `test_can_commit_is_closed_by_default` |
| Notes / private details never leak | e2e `test_notes_and_private_details_never_reach_the_business`; security `test_brief_never_contains_private_notes_or_user_phone`, `test_brain_never_sees_identifier_values` |
| Consent gates | e2e onboarding refusal, circle opt-in, circle member cannot command; security `test_consent.py` (9 tests) |
| Quiet hours | e2e nudges held at 23:00 and released in the morning, no outbound call at night; `tests/proactive` |

**Strict xfails in `tests/security`: none.** Everything in `docs/SECURITY_FIXES.md` that is code is closed. Still open (not
code, or not testable offline): OPS-1 KMS / India region / secrets manager, OPS-2 zero-data-retention and DPAs, OPS-3
pen test, OPS-4 grievance officer, OPS-5 DPIA, OPS-6 breach runbook, OPS-8 provider recording deletion (the Vobiz
delete-recording API is an open `TODO`), plus the product-level gaps BUG-13 (consent) and BUG-18.

## 5. Changes QA made to other owners' files (all minimal, noted here)

* `friday/api/inbound.py` `ANSWERABLE_STATUSES`: added `AWAITING_CHOICE` and `FAILED` (BUG-3). `tests/api`, `tests/security`, `tests/tasks` re-run green.
* `friday/tasks/context.py`: `identifiers` is now loaded into the `ConversationContext` (BUG-10a).

## 6. Go / no-go for a private pilot

**Conditional GO for a founder-only pilot** (founder's own phone, 1-3 trusted testers), **NO-GO for inviting
real third parties' data** until the items below are done.

Must fix before any pilot with real users: BUG-2 (fan-out is broken on the real DB; discovery, quotes, stock and hotel
flows do not work), BUG-5 (wrong business dialled), BUG-8 (false stock report), BUG-13 (family consent flow), BUG-1
(or disable delegation in the pilot message), and the live-verification of telephony (open `TODO`s, DTMF/record/transfer
bodies), Vobiz account upgrade and top-up, WhatsApp templates approved, OPS-1/OPS-2 for any real data.
Safe to pilot as is: single-business booking with the call-back approval, enquiries, reminders/nudges (cap, quiet hours),
delete-everything, caller-ID pool/DNC. The core safety properties (disclosure first, no commitment without approval, no OTP,
no leaks, consent gates) held in every test; the load test shows no lost or duplicate work at 1000 users / 200 concurrent
calls on one process.
