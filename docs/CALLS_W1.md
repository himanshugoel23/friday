# Consumer calls, W1: before and after the call

Package `friday/calls/`, tests `tests/calls/`, migration `0007_consumer_calls` (down_revision `0006_google_connector`; the lead re-links 0008 at merge). The live conversation is W2's.

## Flow
message -> `RequestUnderstander` (rules first, optional LLM hook checked against the user's words; one question at a time) -> `ContactBook.resolve` (nickname, ambiguity question, number confirmed back) -> `CallBrief` (user's own words + fixed guards) -> `ApprovalService.prepare` (summary + exact opening line from `OpeningLineProvider`, buttons Approve / Edit / Cancel) -> user taps Approve (hash of what was shown) -> `CallGate.decide` -> task via `TaskPort` -> `CallOrchestrator.execute` (gate again, attempt saved before the dial, `LiveCallEngine.run`) -> `ReportBuilder` -> retry (existing `TaskPolicy`/`retry_at`: +1 h, +3 h, max 3, moved into the callee's calling window) or stop.

## Safety, all in code
- Approval hash covers goal, say/ask/not-say lists, limits, facts, opening line and the callee number hash; any edit drops approval. Tested for every field.
- Gate order: kill switch (`FRIDAY_CALLS_ENABLED`, core pause flag), per-kind switch, user standing and strikes, classifier (threat, harassment, scam, prank, impersonation, minors, medical, legal, self-harm, emergency), number validity, emergency numbers (all +91 and local forms), test allow-list (core `pilot_dial_blocked`), global do-not-call, daily call and minute caps, per-recipient day/week caps across all users, approval, number confirmed, calling window. Deny beats ask.
- Do-not-call: keyed hash only (`call_dnc`), no user id; opt-out, wrong person and the user's "stop" add to it; checked again right before every dial; not removed by user erasure.
- Privacy: `privacy.scrub` removes private facts and any long number from approvals and reports; logs carry ids and masked numbers only (tested).
- No new text outside `copy.py` (marked `PENDING_FOUNDER_APPROVAL`; a test enforces it).

## Settings (env prefix `FRIDAY_CALLS_`, names only)
`ENABLED`, `DISABLED_KINDS`, `DAILY_CALL_CAP` (10), `DAILY_MINUTE_CAP` (30), `MAX_CALL_SECONDS` (300), `NUMBER_DAY_CAP` (3), `NUMBER_WEEK_CAP` (6), `WINDOW_<KIND>` ("09:00-19:00"; family_friend "08:00-21:30"), `STRIKE_BAN_THRESHOLD` (3), `APPROVAL_TTL_HOURS` (24), `RECORDING_RETENTION_DAYS` (30), `GROUP_MAX_MEMBERS` (10), `RETRY_MAX_ATTEMPTS` (3). The test allow-list and pause flag stay the core settings.

## How W2 plugs in
Implement `LiveCallEngine.run(brief, callee) -> CallOutcome` and `OpeningLineProvider.opening_line(brief, name)` (`friday/calls/interfaces.py`). Rules: speak `brief.opening_line` exactly; answer only from `shareable_facts`; any promise outside the brief goes to `needs_user_approval`; end at `callee.max_duration_s`; set `OPTED_OUT` / `WRONG_PERSON` / `do_not_call_again`; use `copy` key `spoken_apology_wrong_person`; `dnc.detect_opt_out` and `detect_wrong_number` are available. `friday.calls.fakes` has offline fakes. Group children reuse the parent's approved opening line.

## Wiring left for the lead
- `TaskPort`: no adapter to the real `TaskEngine` yet. Tests use `FakeTaskPort`. The current engine runs its own brain and runner, so an adapter must make the engine's scheduled job call `CallOrchestrator.execute(request_id)` (single dial path), not dial itself.
- `UserNotifier` over the core `Notifier.notify_user`, `IntakeState` persistence per user, button dispatch to `handle_button`, a periodic `run_due` / `recover_stale` / `RecordingService.purge_expired`.
- Apply migration 0007 and `rls.sql` to the live database.

## Unverified
All legal rows (docs/LEGAL_MAP.md); emergency number list; keyword rules are not a full abuse detector; Hindi (Devanagari) understanding is basic; every user-facing line is pending approval; Hinglish phrasing was not heard or read by the founder; the DB repositories were tested on SQLite only (Postgres not run).
