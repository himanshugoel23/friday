# Life state and proactive (workstream W4)

One per-user picture of the user's day that every channel reads (WhatsApp, voice notes, calls), and
a scheduler that speaks first at the right moment without nagging. Code: `friday/lifestate/`.
Tests: `tests/lifestate/`. Migration: `0009_life_state`. All user-facing words: `friday/lifestate/copy.py`
(PENDING_FOUNDER_APPROVAL, hear-before-change).

## Architecture

```
user message ---> capture.py ----------+
Google Calendar -> sync.py (read-only) +--> LifeStore (events, commitments, mute, log) <-- memory.py
W3 bills / W1 call outcomes / bookings +        |                                       (view, forget, edit,
                                                |                                        export, delete)
                  now.py: now_status, context_summary ---> conversation.py (front door, live calls)
                  followups.py: plan -> guardrails -> sender  (after/before event, bills, reminders, brief)
```

| Module | Job |
|---|---|
| `models.py` | `LifeEvent`, `LifeCommitment`, `PersonRef`, `Repeat`, `NowStatus`, `UserContext`, `Followup`, `TopicPref`; text cleaning; `display_title` for untrusted titles |
| `dbmodel.py`, `friday/db/repositories/lifestate.py` | tables and `LifeRepo` (`container.repos.life`) |
| `store.py` | `LifeStore` protocol, `MemoryLifeStore` (tests, simulator), `export_life_state`, `delete_everything` |
| `capture.py` | Hinglish text to events and commitments, clarifying question, LLM hook |
| `sync.py` | calendar import, bookings, call outcomes, clash check |
| `now.py` | `now_status`, `context_summary` |
| `followups.py` | planner, `FollowupScheduler`, morning brief, reply handling, "mat poocho" parsing, `NotifierSender` |
| `memory.py` | "tumhe kya yaad hai", "bhool jao X", "X ko 4 baje kar do", export, delete everything |
| `conversation.py` | `LifeContextProvider` and the registration point the front door calls |
| `ports.py` | `CalendarPort`, `BillsPort`, `TravelBufferHook`, `CaptureLLM`, `Sender` (each has a fake in tests) |

## Data model (migration 0009)

All tables are keyed by `user_id` (FK to `users`, cascade) and RLS is on with no policy (same as the other tables).
Columns marked (enc) use the existing field encryption (AES-GCM, AAD `table.column`).

* `life_events`: title (enc), start_at, end_at (UTC), kind (interview, meeting, appointment, travel, bill_due, personal, other),
  source (user, calendar, booking, bill, call_outcome), source_ref, location (enc), protected, status (active, cancelled, done),
  note (enc, what the user said afterwards), repeat (JSON rule, e.g. a monthly bill). Unique on (user, source, source_ref): this is the dedupe.
* `life_commitments`: text (enc), due_at, source, status (open, done, cancelled), repeat, person (enc JSON: name, relationship).
* `mute_topics`: per user and topic: `muted`, and `channel` (text by default; voice_note or call only after the user asks for it for that topic).
* `life_followups`: the log of what was planned, sent, muted, dropped or held for the digest, keyed `(user, key)` so nothing is sent twice. Text (enc).
  Nudge history of the old proactive engine stays in `nudges`; this log is separate so the two can run side by side.

`NowStatus` is derived, never stored: `free`, `in_event(kind, ends_at, protected)`, `travelling`, `quiet_hours` (sleeping).
Travel and events win over quiet hours (an overnight train is "travelling"). Start is inclusive, end exclusive; back-to-back events chain.

Times are aware datetimes, stored UTC, read as Asia/Kolkata when naive.

## Capture: what is understood (and how it is shown back)

Examples that are tested (more than 80 cases in `tests/lifestate/test_capture.py`): "kal 2 baje interview hai", "parso shaam 6 baje dentist",
"bijli ka bill 20 ko", "mummy ki dawai 8 baje roz", "raat 12 baje meeting", "agle somvar 11 baje", "bill month end tak",
"saade 3 / dhai / dedh / sawa 4 / paune 5 baje", "2 ghante baad", "3 din baad", "20 oct", "25/10", "2 se 3 baje", "next friday", "har somvar", "har mahine 5 tarikh".

Conventions (every confirmation states the resolved day and time, so a wrong guess is visible and "galat" undoes the last capture):

* no am/pm word: 1 to 6 means afternoon or evening, 7 to 11 means morning (evening for dinner, party, movie, shaadi); a bare "12 baje" is asked ("dopahar ya raat?");
* "raat 12 baje" is midnight at the END of the named day; "raat 1 to 5 baje" is after the midnight that ends the named day;
* a weekday name is its next occurrence; "agle <weekday>" is strictly after today; today's weekday with the time already over means next week;
* "20 ko" is the next 20th, clamped in short months (31 in November is the 30th); "29 feb" waits for a leap year; "month end" is the last day of the month;
* a time with no date is today if still ahead, else tomorrow.

What it refuses to guess: no date or time for an event, "kal" with a past marker ("kal interview tha"), week-only ("agle hafte"), a past explicit date.
Each gives exactly one question; the next message is parsed together with the first (no hidden state).
Questions ("kal kya hai?") and requests to Friday ("dentist book kar do") are NOT captured: they return `status="none"` for the other handlers.
The front door should try `MemoryControls.handle` and `FollowupScheduler.handle_reply` first (they only claim their exact commands), then `capture_message`.

Optional model hook (`CaptureLLM`): only asked when the rules found nothing and the text is neither a question nor a request. Its proposal is re-validated by code
(non-empty title, start within a year, end after start and within two days, kind in the enum) and confirmed back like any capture. It never sees calendar text.

## Rules for proactive messages

1. **Why, in one clause, on every message** ("Isliye pooch rahi hoon ki aapka interview 12 baje khatam hua tha"), plus how to stop it ("mat poocho"). Tested for every copy function and every message the scheduler sends.
2. **Protected events**: interviews, meetings, appointments and travel are protected by default. A nudge that falls due while one is running (or a chain of back-to-back ones) is held and released after it ends, unless it has gone stale.
3. **Stale means dropped, not late**: "how did it go" expires 6 hours after it was due; a before-event reminder expires 5 minutes before the start; a bill nudge at the end of the due day; a reminder 3 hours after its time.
4. **Quiet hours, daily cap, ignore-learning**: these are the existing `proactive/guardrails.evaluate` (22:00 to 08:00 IST, 3 messages a day shared with the other triggers through `extra_sent_today`, back-off after unanswered messages). Over the cap, a message that will not be stale tomorrow goes into the next morning brief; one that will be stale (an after-event nudge) is dropped.
5. **Mute and "stop"**: "mat poocho", "stop", "interview ke baare mein mat poocho", "bill ke reminder band karo", "sab band karo", "phir se poocho". A bare "stop" right after a nudge mutes that nudge's topic; with nothing recent it mutes everything. Topics: `after_event[:kind]`, `before_event[:kind]`, `bill_due`, `commitment`, `reminders` (group), `morning_brief`, `all`. Only short messages (12 words or fewer) can be commands.
6. **Channel**: text. A voice note or call is used for a topic only after the user asks for it for that topic ("interview ke baad voice note bhejo"). The `NotifierSender` has no voice or call path yet and falls back to text; nothing is ever escalated to a call by itself.
7. **Replies**: a reply to an after-event nudge within 24 hours is stored as a note on the event (encrypted) and, if it contains a new date ("next round parso 4 baje"), captured as the next event. A reply that is a request to Friday is left to the normal handlers.
8. **Timing table** (after: interview 40 min, meeting 20, appointment 30, travel 15; before: interview 90 min, meeting 30, appointment 60, travel 120; with a travel-buffer hook the reminder comes 30 min before the time to leave; bills 2 days before at 10:00) are constants in `followups.py`, to be tuned from real reactions.
9. **Morning brief**: today's events, reminders and bills due within two days, at most 6 lines ("aur N cheezein" for the rest), one suggestion at most (leave time, clash, pay the bill today), one why-clause, sent once a day from 08:00 IST, skipped entirely when there is nothing to say. Digest lines held back by the cap ride along.

## Privacy rules

* Per user only: every store call takes the `user_id`; there is no query across users (tested for both the SQL and the in-memory store, including an attempt to overwrite another user's row).
* Encrypted at rest: titles, locations, notes, commitment text, the person a commitment is about, and the text of sent messages. A test reads the raw rows and checks for `v1:` ciphertext.
* The context summary other channels see contains kinds, times and counts only: no title, note, location or person ("in event (interview) until 15:00 IST (protected); bills due this week: 2").
* Untrusted text: a calendar title is data. It is cleaned and shortened for display (URLs, e-mail addresses, long digit runs, markup removed), classified into a kind by fixed word lists, never parsed as an instruction, never put in a message (messages use the kind), never in the context summary. Calendar text never goes to the capture LLM hook.
* View, change, delete, export: "tumhe kya yaad hai", "bhool jao X" (one step), "X ko 4 baje kar do", "mera data export karo" (JSON, the caller sends it as a file), "sab delete karo" which asks for the exact phrase "haan, sab mita do" (stateless; nothing else erases everything). `DataPurger` (account erasure) also deletes all four tables.
* Never used for ads, never across users, calendar is read-only (the port has one method; a test fails if sync touches anything else).

## How other workstreams feed it

* **Google (done on this base)**: `friday/google/calendar.py` `CalendarClient.list_events` already returns objects that fit `CalendarPort`; `sync.GoogleCalendarAdapter(client)` exposes only that method. A periodic job per connected user calls `sync_calendar(store, user_id, adapter, now)`. A failed fetch changes nothing. An event the user already told Friday about (same kind within 15 minutes) is merged, not doubled. Clash check before accepting a booking: `check_booking_slot(store, user_id, start, end, calendar=adapter)` uses stored events and a live read of the slot.
* **W3 bills**: implement `BillsPort.pending_bills(user_id, now) -> [BillRef(id, due_on, biller, pay_link)]`. The scheduler nudges 2 days before and puts the pay link in the message (a link only; Friday never pays); the brief and the context count them. Until then, a bill the user typed ("bijli ka bill 20 ko") is a `bill_due` event and works the same without a link. Bills not mirrored as events are de-duplicated by due date.
* **W1 call outcomes and bookings**: `record_booking_from_task(store, task)` (finished task with an appointment time) and `record_call_outcome(store, user_id, call_id=..., title=..., start=...)`; both are idempotent per task or call id and update the same event if the time changes. `cancel_booking` marks it cancelled.
* **Front door and live call engine**: `LifeContextProvider.context_for(user_id, now)` returns the safe summary to inject into the prompt; `register_context_provider` / `get_context_provider` is the registration point. The front door is not changed in this workstream. A user who calls or writes during a protected event is never refused: the summary only lets Friday answer in context ("aapka interview 2 se 3 hai"). Friday does not start contact during it.
* **Proactive engine**: the scheduler uses `guardrails.evaluate` and shares the daily cap, but sends through its own `Sender` and logs in `life_followups`. To run it, build `FollowupScheduler(repos.life, NotifierSender(notifier), settings, clock, bills=..., travel=..., extra_sent_today=...)` and call `run_user(user_id)` for each active user on the engine tick, and `send_morning_brief(user_id)`. Not wired into `ProactiveEngine.tick` yet (kept out to avoid conflicts with W1 and W3).

## Unverified (needs real people or real systems)

* Real Google calendars: recurring events, time zones other than IST, declined and tentative events, all-day semantics, rate limits, token expiry mid-sync. Only the fake and the `CalendarEvent` shape are tested.
* Real users' reactions: whether 40 minutes after an interview feels right, whether the caps and the wording feel like care or nagging, whether people say "mat poocho" in the forms parsed, how they phrase times we do not read (Devanagari script is not parsed at all).
* WhatsApp: a message we start outside the 24-hour window needs an approved template; the notifier handles the fallback but these messages have no approved template yet. Voice notes and calls from Friday are not built.
* The 12-hour guesses (7 to 11 morning) will be wrong for some people; the confirmation shows the guess and "galat" undoes it.
* Travel time: only a hook; no maps or traffic.
* Retention: events are kept until the user deletes them; a retention period (for example 90 days after the end) is not decided.
* Legal read (DPDP) on storing calendar-derived data and notes: not done.

## Decisions for the founder

1. Approve or change the wording in `copy.py` (text first; audio only if any line is to be spoken).
2. User-set reminders (a medicine at 22:30) during quiet hours: today they follow the proactive rule (held, and dropped if stale). Should an explicit user-set time ring through quiet hours?
3. Delay table (40 / 20 / 30 minutes after) and the lead times; and whether travel and appointment get an after-event nudge at all.
4. "Delete everything" needs the exact phrase "haan, sab mita do" (two steps). Fine, or one step?
5. Retention period for past events and notes.
6. Voice note and call nudges: which topics may offer them, and the spoken lines (hear-before-change).
