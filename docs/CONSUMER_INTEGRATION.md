# Consumer beta integration (W5, 19 Oct 2026)

One WhatsApp conversation over the four built packages: calls (W1 `friday/calls`, W2 `friday/liveagent`), savings (W3
`friday/savings`), life state (W4 `friday/lifestate`) and the Google connector (`friday/google`). Code: `friday/integration/`,
tests: `tests/integration/` (offline, no network, invented numbers). Every new feature is OFF until the founder turns a switch on;
with all four switches off the product behaves exactly as before (a routing test proves it).

## The picture

```
WhatsApp -> InboundPipeline._active
              1. pending PIN / delete (unchanged)
              2. ConsumerRouter.handle(user, msg)      <- NEW, only when a switch is on; False = carry on
              3. quotes flow, PM gateway, button payloads q:/a:/n:, brain (unchanged)

ConsumerRouter (text)
  pending call question / "Edit" reply ........ W1 CallIntake / CallOrchestrator.apply_edit
  Google connect | disconnect | status ........ friday/google (GoogleOAuth.start / status / disconnect)
  call request ("... ko phone karke ...") ..... W1 CallIntake -> approval message (Approve / Edit / Cancel)
  memory ("tumhe kya yaad hai", "bhool jao X") . W4 MemoryControls
  savings ("mere paas ... card", bill text) .... W3 SavingsCommands.handle
  "mat poocho" / reply to a follow-up .......... W4 FollowupScheduler.handle_reply
  "mera din" ................................... W4 build_morning_brief
  "Zomato pe 640" (user has cards) ............. W3 which_card
  "galat" / "kal 2 baje interview hai" ......... W4 undo_last / capture_message (never a question or a request:
                                                 "mausam kaisa hai", "cab chahiye", "pizza order karo" go on to the brain)
ConsumerRouter (buttons)  ButtonRegistry: callap: callact: led: bill: life:   unknown id -> not ours, ignored

call path (single dial path)
  Approve -> CallGate -> QueueTaskPort.create -> JobQueue "consumer.call" (dedupe key callreq:<id>:<attempt>)
          -> TaskEngine handle_job -> CallOrchestrator.execute (gate again, attempt saved BEFORE the dial)
          -> LiveEngineAdapter.run -> W2 LiveCallEngine on a TelephonyFactory line -> CallOutcome
          -> W1 report on WhatsApp with next-action buttons, or retry (+1 h, +3 h, max 3), or stop

proactive path (one tick)
  ProactiveEngine.candidates += BillReminderSource (W3) + LifeFollowupSource (W4); briefing text from LifeBriefingProvider
  -> process(): dedupe by key -> guardrails (quiet hours 22-08, 3 a day, ignore-learning, digest) -> send fixed text
```

## Files

| File | What |
|---|---|
| `friday/integration/bridge.py` | W1 brief -> W2 brief, W2 result -> W1 outcome (`STATUS_MAP`), `LiveEngineAdapter` (the production `LiveCallEngine`), `LiveOpeningLineProvider`, `TelephonyFactory` (default REFUSES), redirect/allow-list on the dial target |
| `friday/integration/telephony.py` | `ConsumerTelephonyFactory`: the production line (real Sarvam/Vobiz leg), built by `build_consumer` only for live + pilot profile + calls switch; see docs/CONSUMER_CALL_TEST.md |
| `friday/integration/call_test.py` | `friday consumer call-test [--dry-run]`: one test call to your own allow-listed phone |
| `friday/integration/taskport.py` | `QueueTaskPort` (W1 `TaskPort`), `job_handler`, `ConsumerJobs` (`run_due`, `recover_stale`, `purge_expired`) |
| `friday/integration/router.py` | `ConsumerRouter`: the front door, `clash_note`, `on_task_done`, `periodic`, calendar sync |
| `friday/integration/buttons.py` | `ButtonRegistry` and the prefixes |
| `friday/integration/proactive.py` | `BillReminderSource`, `LifeFollowupSource`, `LifeBriefingProvider`, `SavingsBillsPort` |
| `friday/integration/wiring.py` | `build_stack` (all dependencies injected), `build_consumer(c)` (the `consumer` component), `attach` |
| `friday/integration/sim.py` | `PersonaTelephony` (W2 personas as a line), `demo_card_rules` (INVENTED example rows) |
| `friday/integration/demo.py` | `friday consumer demo` |
| `friday/integration/copy.py` | the few new lines (PENDING_FOUNDER_APPROVAL) |

Changes outside the new package (all additive, behaviour unchanged while the switches are off):
`core/config.py` (4 switches), `core/container.py` (`consumer` component, `consumer.call` job route), `core/models.py`
(`ConversationContext.day_summary`), `api/inbound.py` (router hook, context summary), `api/runtime.py` (attach + periodic loop),
`tasks/engine.py` (`register_job_handler`, clash note in the booking offer, booking recorded on completion),
`proactive/engine.py` (`register_source`, `register_briefing_provider`, `register_sent_hook`, `fixed_text`/`fixed_buttons` on a
candidate), `liveagent/contracts.py` + `report.py` (`CallOutcome.answers`, `callback_time`), `calls/orchestrator.py` (one group
report when two children finish together), `cli.py` (`friday consumer demo`).

## The switches (names only; all default false)

| Env name | Turns on |
|---|---|
| `FRIDAY_CONSUMER_CALLS_ENABLED` | call requests, approval, the call job, the periodic call jobs (plus the existing W1 kill switch `FRIDAY_CALLS_ENABLED`, default true, and `friday pause`) |
| `FRIDAY_SAVINGS_ENABLED` | wallet, "which card", bills, bill reminders, the `led:`/`bill:` buttons |
| `FRIDAY_LIFESTATE_ENABLED` | capture, memory controls, "mera din", mute/reply, follow-ups, morning brief text, the day summary in the brain context, clash note, booking record |
| `FRIDAY_GOOGLE_ENABLED` | connect/disconnect/status intents and the calendar sync (the `/google` routes themselves exist as before and need the Google Cloud settings) |

## Where W1 and W2 disagreed, and where it is fixed (all in `bridge.py`)

| Question | Decision |
|---|---|
| Callee kinds | W1 `family_friend` -> W2 `family_elder` for mother/father/grandparents, else `friend`; `group` never dials (children carry their kind) |
| Facts | W1 lists -> W2 dicts (`fact1..`, `private1..`); private facts only ever reach W2 guards |
| User name | W1 `user_display_name` -> W2 `user_name`; no name -> the neutral word `copy.SPOKEN["unnamed_user"]` ("mere user"), pending |
| Purpose said twice | `must_say` equal to the goal is dropped (said once as the purpose); a question purpose is replaced by the fixed lead-in `goal_spoken_ask` and asked once from the ask list |
| Limits | only the money ceiling and the call length carry over. `allowed_times`/`allowed_commitments` stay EMPTY: a promise asked for on the call becomes a "needs your OK" item, never agreed alone |
| Voicemail | `voicemail_allowed` is always false (W1's brief has no voicemail consent): no message is ever left |
| Statuses | `STATUS_MAP`: NEEDS_USER_APPROVAL -> PARTIAL with the approvals listed; VOICEMAIL_LEFT -> PARTIAL (not retried: a retry would leave it again); VOICEMAIL_NO_MESSAGE -> VOICEMAIL (retried); UNREACHABLE -> NO_ANSWER; WRONG_NUMBER -> WRONG_PERSON; DO_NOT_CALL -> OPTED_OUT + `do_not_call_again`; DISTRESS/HOSTILE -> SAFETY_STOP; UNRESOLVED/DROPPED -> FAILED; CUT_OFF -> PARTIAL |
| Summary language | W2's summary is English; the bridge writes a short Hinglish summary from the status and the structured fields (W2 `CallOutcome` gained `answers` and `callback_time` for this: the only W2 model change) |
| Opening line | the approved first utterance is what the W2 engine says first: `LiveOpeningLineProvider` runs the real engine against a silent probe line. A group child inherits the parent's line (made without a name), so the child runs in that neutral register (test: spoken first utterance == approved line) |

## Safety (all tested)

- Nothing can dial: `LiveEngineAdapter` needs a `TelephonyFactory`; the production default refuses (the call ends FAILED, undialled), and
  the router answers "the calling line is not switched on" before any approval is asked. The test line is a simulated persona.
- The W1 gate is unchanged (kill switch, allow-list `pilot_dial_blocked`, do-not-call, caps, windows, approval hash). The adapter also
  applies `vendor_call_redirect_to` and the allow-list to the number actually dialled, as vendor calls do.
- One dial path: the engine's `consumer.call` job and the periodic safety net both call `CallOrchestrator.execute`, which saves the attempt
  before dialling; a re-delivered job or a lost-then-found job dials once.
- Job payloads carry request ids only. Logs carry masked numbers only (a sweep test covers calls, savings, life and Google flows).
- Business calls with a confident BUSINESS kind are NOT taken by the consumer router: they keep their approved playbooks.

## Tests

`uv run pytest tests/integration -q` (about 20 s). `test_e2e_calls.py` (a) mummy-late whole flow, (b) refusal, do-not-call, "stop calling",
wrong number, voicemail with +1 h/+3 h retries and the final message, (c) group of two; `test_e2e_savings_life.py` (d) cards, Zomato, forwarded bill and
reminders, (e) interview, context summary, after-event nudge under the caps, quiet hours, mute; `test_routing.py` (f) switches off and old flows
unchanged, buttons; `test_privacy.py` (g); `test_bridge.py`, `test_taskport.py`, `test_proactive_google.py`, `test_demo_and_copy.py`.

`uv run friday consumer demo [--scenario calls|savings|all]` prints the WhatsApp transcript of (a) and (d) on a fake WhatsApp, a simulated
callee and an in-memory database (no network, no `.env`; the card rows are invented and labelled EXAMPLE).

## What is NOT verified

- Real WhatsApp: templates outside the 24-hour window (the simulator renders a template; the real template names/approval are unchecked), button
  payload limits, delivery receipts for the new messages.
- Real voice: the production `TelephonyFactory` now exists (`friday/integration/telephony.py`, tested with fakes) but no real call has been placed through it
  (run `friday consumer call-test`, docs/CONSUMER_CALL_TEST.md). Real latency, Hindi/Hinglish STT on real callees, IVR and voicemail on a live line, the opening line heard aloud.
- Live database: migrations 0006-0009 were not applied to Supabase/Postgres; the integration tests ran on SQLite only. No Postgres run.
- The call-intake state (a half-finished request, an Edit in progress, a pending capture question) is in process memory with a 30-minute life; it
  is lost on restart and not shared between replicas (it holds a pending number, so it must not go in the shared cache).
- Two children of a group finishing at the same instant on DIFFERENT workers could still send two group reports (the fix is a per-process lock).
- Typed answers to a button question ("Sahi hai" typed instead of tapped) are not understood; the buttons are.
- Gmail: the Gmail reader exists behind its own switch but nothing turns an email into a bill yet (only forwarded text does); no Gmail sync job.
- "Export my data" and "delete everything" are left to the existing PIN-protected flows; W4's own "haan, sab mita do" phrase still erases only the life state.
- The live-engine `UserChannel` (ask the user mid-call) is not wired to WhatsApp, so an unplanned question on a call always ends as "needs your OK".
- Every user-facing and spoken line is PENDING founder approval (this module's `copy.py` and the five package copy modules).

## Decisions the founder needs to make (new ones from this work)

1. **Unnamed user**: when the profile has no name the callee hears "mere user ki virtual assistant". Ask for the name at onboarding, or accept?
2. **Voicemail**: W1's brief has no voicemail consent, so no message is ever left (the call is retried). Add a consent in the approval message?
3. **Commitments**: nothing is pre-approved (every time/visit/booking the callee proposes comes back as "needs your OK"). Add "you may accept times between X and Y" to the approval?
4. **Voicemail left** is a finished call (not retried). **Unresolved/dropped** calls are retried like a failure (+1 h, +3 h). Right?
5. **Bill statements in words** ("25 ko bijli ka bill") go to the savings engine when it is on (it asks for the date format), and to the life state only when savings is off.
6. **Morning brief**: W4's text replaces the generic briefing text for users who opted in to the morning briefing; nobody gets a W4 brief without that opt-in.
7. **Delete everything**: W4's two-step phrase and the existing PIN flow both exist. Keep both, or make the PIN flow the only one?
8. **Group call opening**: a group child says the neutral opening (no name, "Hello, namaste.") because the parent plan, which the user approved, has no single name. Acceptable?

## What the founder must turn on to try it

Text features today (no calls): apply migrations 0006 -> 0009 to the database, import verified card rules (`friday savings rules import`; the repo ships
only EXAMPLE rows that are never served), set `FRIDAY_SAVINGS_ENABLED=true` and/or `FRIDAY_LIFESTATE_ENABLED=true` on the server and restart, approve the
wording of `savings/copy.py`, `lifestate/copy.py` and this module's `copy.py`. Google: create the Google Cloud project per `docs/GOOGLE_CONNECTOR.md`, set its
client id/secret/redirect, `FRIDAY_GOOGLE_ENABLED=true`, named testers only.

Calls: `FRIDAY_CONSUMER_CALLS_ENABLED=true` with `FRIDAY_MODE=live` and `FRIDAY_PROFILE=pilot` (then the production `ConsumerTelephonyFactory` is wired; in any other
profile the line still refuses), approval of `calls/copy.py` and the `liveagent/lines.py` audio, `FRIDAY_PILOT_ALLOWED_NUMBERS` limited to the founder's own number and
`FRIDAY_VENDOR_CALL_REDIRECT_TO` set to it for the first test, and his approval of one specific test call. Outside live + pilot the switch only makes Friday
say that the calling line is not on.
