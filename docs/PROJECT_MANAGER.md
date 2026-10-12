# Project manager and classifier (agents 1 and 2)

Code: `friday/pm/`. Spec source: `docs/AGENT_ROSTER.md` ("Project manager and distance rule"), `docs/SCOPE_BUCKETS.md`.
Offline by default: tests use fakes only; no network, no vendor contact.

## Agent 1: classifier (`friday/pm/classifier.py`)
One job: `text (+ channel) -> {bucket, category, confidence}` from the closed lists (10 buckets in `data/buckets.yaml`,
20 Wave 1 categories in `data/categories.yaml`, same keys as `friday/scouting/categories.py`; a test enforces it).
* `Classifier` Protocol. `LLMClassifier` (real; uses the repo's `LLMClient`, i.e. `OpenAILLM`, model gpt-5.4-mini, strict
  JSON schema with enums). Reply is validated twice (schema keys + closed lists); one repair retry; then `unsure()` (never an
  invented label). The user message is quoted as data. Call/voice channels add a note that the text is a noisy transcript.
* `KeywordClassifier` (= the fake/baseline): deterministic keyword scoring, EN/Hinglish/Devanagari.
* Fixture `tests/pm/fixtures/classifier_examples.json`: 104 labelled messages (Hinglish, Hindi, English; 24 are
  short STT-noisy call-style utterances with `channel: call`). `pytest tests/pm/test_classifier.py -s` prints baseline accuracy
  (currently 104/104). Caveat: the baseline keywords were written alongside the fixture, so that number is optimistic;
  use it as a regression guard, and measure the LLM with `friday classify` on new messages.
* CLI: `friday classify "text" [--channel whatsapp_text|whatsapp_voice|call|sms]` uses the live LLM only if an OpenAI key
  is configured, otherwise says so and uses the baseline. Output is one JSON line.

## Agent 2: project manager (`friday/pm/manager.py`)
A deterministic state machine over a persisted `TaskRecord` (`state.py`: JSON, `MemoryTaskStore`, `JsonFileTaskStore`,
`TaskStore` Protocol for a DB adapter). The LLM, if used at all, only rewords a user-facing question (`GuardedRewriter`:
rejected if it adds numbers or links, is long, or is not a question). The PM never calls vendors and never writes
vendor-facing words: `StepContext` carries structured fields only (a test pins its field list).

### Turn interface (any channel)
`await pm.handle_turn(task_id | None, text, channel, user_id=, profile=, updates_on=) -> TurnReply`
(`reply_text`, `state`, `pending_kind`, `pending_slot`, `background`, `whatsapp[]`, `done`).
`handle_message` is the same with a richer `PMReply`. Channels: `whatsapp_text | whatsapp_voice | call | sms`; the output
(bucket, category, slots, questions) is the same, only the wording differs.

### Quiet rule (founder)
ONE acknowledgement when the request is understood (the plan exists), then silence until an outcome or a question only the
user can answer (clarification, widen the radius, approve the shortlist, over budget). Failures (no pickup, next vendor,
retries) are handled internally and only logged. A per-request `updates_on` flag (default off) enables a short
"Update: <step> done" message per step. Replies to the user's own interruptions (cancel, change) are acknowledgements.

### Channel rules
* Call: ONE very short, speakable question per turn (`spoken:` block in `data/plans.yaml`, 40 characters max, no lists).
  The ack says the result will come on WhatsApp. After the ack the call turn returns (`background=True`); the caller then
  invokes `pm.run_background(task_id)`: from there the shortlist question and the final outcome go to WhatsApp, so nothing
  depends on the caller staying on the line or the phone being online (docs/HANDOFF.md 2b).
* Long inputs (`long_slots` = details; full address, pin and many numbers belong here too) are never taken by voice: the call
  says the question will come on WhatsApp, the real question is queued in `TurnReply.whatsapp`, the pending slot waits for the
  WhatsApp answer. A polite stop on a call is also sent on WhatsApp.
* The voice layer (`friday/voice/*`, not touched) can drive this later: speak `reply_text`, send `whatsapp` texts.

### Flow
1. Classify. Handoff buckets (confirm, reschedule/cancel, follow-up, complaint) stop with a handoff note (beta scope).
   No category -> one category question; bucket "other"/low confidence -> one bucket question.
2. Plan template = archetype base (quote, availability, book, service_visit, information) merged with per-category
   overrides (`data/plans.yaml`; radii from `categories.yaml`): required slots, optional, defaults, `n_vendors`, `call_mode`.
   All 20 categories x 5 archetypes build (tested).
3. Slots: rule extractor (`RuleSlotExtractor`, behind the `SlotExtractor` Protocol; an LLM extractor can replace it, output
   goes through `clean_slots`) reads the first message plus saved places from `profile` (`home_place`, `parents_place`: "for
   mummy" uses the parents' place). Missing required slots: ONE question at a time, max 2 rounds in total, in a fixed order.
   After that defaults are applied (listed in the ack) or, with a required slot that has no default, a polite stop.
   `book` needs an explicit delegation; if the user declines or never gives it, the plan is downgraded to `availability`
   (never books without it).
4. Plan = ordered steps: locate, search, filter, reviews, rank, shortlist, consent, calls, collect, compare, report
   (information/book skip some). Each step goes to `StepAgents.run(step, ctx) -> StepResult` (`steps.py` Protocol;
   `FakeStepAgents` is a pretend world with vendor distances). The PM reads only the typed result.
5. Distance rule, enforced in code: the shortlist is re-checked and any vendor beyond the current radius, beyond the
   category hard max, or without a distance is dropped and logged (`distance_violation`). Nothing in range -> ask to widen
   (default -> x1.5 -> hard max); asking happens every time, beyond hard max the PM stops politely.
6. Consent: the user approves the shortlist; then the `consent` agent (allow-list, quota, hours, redirect) is the safety gate;
   a block stops the task.
7. Calls: `quote`/`availability`/`service_visit` call until `n_vendors` answered, `book`/`information` until the first
   success; no pickup (or other failure) silently moves to the next vendor of the ranked shortlist; ambiguous results are
   flagged for the report; all failing stops with a retry-later message.
8. Over budget: if every priced quote is above the budget the PM asks before reporting. Final text comes from the report agent.
9. Interruptions: "cancel/rehne do" cancels (steps skipped, logged). A message that carries new slot values re-plans from the
   earliest affected step (place -> locate, service -> search, time/delegation -> calls, budget -> collect; consent is kept for
   the same vendors) and works even while a yes/no is pending ("nahi, Sector 45 mein" is a change, not a refusal).
10. Resume: `pm.resume(task_id)` after a restart re-sends a pending question or re-runs the step caught mid-run.
11. Decision log on the record: classified, slots_extracted, default_applied, question_asked, answer_received, plan_created,
    step_*, no_vendors, widen_*, vendor_skipped, distance_violation, flagged_ambiguous, interrupt_*, replan, stopped, done.

### Wording
All user text lives in `data/plans.yaml` (`en` and `hinglish`; Devanagari input gets the Hinglish wording). These are WhatsApp
texts and short spoken questions, not vendor scripts. The spoken question wording is new voice text: per the hear-before-change
rule, play the `spoken:` lines to the founder before the voice layer uses them.

### CLI
* `friday pm-sim [scenario] [--log] [--list]`: runs a transcript (built-in names in `friday/pm/data/scenarios/` or a JSON file)
  against fakes and prints each turn, the plan and optionally the decision log.
* Scenario JSON: `{"channel", "turns": ["text" | {"user", "channel"}], "fake": {"vendors", "pickup", "prices"}, "profile",
  "updates_on"}`.

### Known limits / next
Rule-based slot reading is conservative (an LLM extractor behind the same Protocol is the upgrade); no category/bucket switch
mid-task (start a new task); "fewer than N vendors inside the radius" does not yet offer to widen (only "none"); real
adapters from `StepAgents` to scouting, quotes and voice, and a DB-backed `TaskStore`, belong to the integration step.
