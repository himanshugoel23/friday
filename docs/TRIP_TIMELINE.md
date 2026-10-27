# Trip timeline engine (item F)

Status: built, behind `FRIDAY_TRIPS_ENABLED` (default OFF). Fakes only: nothing here dials, sends or calls a provider.
All wording is PENDING founder approval (`friday/trips/copy.py`, same pattern as the other `copy.py` files). Design: `docs/TRIP_CONCIERGE_DESIGN.md` section F. Migration `0017_trips`.

## What it does
A trip is built from CONFIRMED documents (flight, train, hotel from item D; the Drive pointer kind from item E is carried on the leg) or from the user's own typed fields. From the legs it derives, as pure table-tested functions (`friday/trips/derive.py`):
- **Leave-by**: departure minus airport/station buffer minus travel time. Buffers: domestic 2 h, international 3 h, train 45 min (config). Travel time is the user's number ("airport tak 40 min"); if unknown, a stated default of 60 min is used and the message says so. An airport that is not in the table counts as international (longer buffer) and is flagged.
- **Hotel**: check-in time only if the document has it (else "unknown", never guessed); a "call the hotel first" PROPOSAL due the day before at 10:00 local; checkout reminder.
- **Cab**: a proposal 12 h before leave-by. No booking: the user gets a ride hand-off link (`handoff.py`, provider-neutral, format UNVERIFIED) built from a pickup address the user typed.
- **Flight/train status watch** behind `FlightStatusPort` (`ports.py`). The provider is NOT chosen; only `FakeFlightStatus` exists. Starts 24 h before, every 3 h, hourly in the last 6 h, stops 1 h after departure; backs off 30 min after a provider failure and stays silent. Only a real change is told (delay of 15 min or more, cancellation, gate or terminal); a delay re-derives leave-by and the cab time; data older than 3 h is labelled with its age.
- **Lounge hint** by card (`lounge.py`) from the new shared `card_perks` table. Same person-verified validator as savings rules (source link, past check date, named human verifier, marked served, not an EXAMPLE row). No rule means silence. Never mentions upgrades or new cards. The repo ships only EXAMPLE rows (`friday/trips/data/example_perks.csv`, fake bank, `example.invalid`).
- **Day-wise plan** (`render.py`): "meri trip" returns the plan grouped by local day; it is also the pinned card of the per-trip thread. Every trip message starts with `[trip name]` and its buttons carry `trip:<trip_id>:<action>:<task_id>` (the per-trip thread inside the 1:1 chat). Times are shown in the zone they happen in.

## Proposals and the call/task engine
Hotel call: the user taps Yes, then `TripTaskPort.create_task` is called with a `TaskSpec` (type `reconfirm`, `approved=False`), so the existing task engine asks again before it dials and the existing `CallGate` rules apply. `EngineTaskPort` wraps `TaskEngine.create_task`; tests use `FakeTripTaskPort`. **The hotel number comes only from the document or from the user** (`hotel number +91...`); with none, the bot asks and never searches. The questions the call agent would ask are `HOTEL_CALL_QUESTIONS` in `copy.py` (PENDING; they need an audio sample before any real call). `mark_engine_task_finished` links the evidence ids back to the trip task.

## Nudges
`TripService.run_user/tick`: daily cap 5 per IST day (`FRIDAY_TRIP_DAILY_CAP`, founder decision 8; shared count with other proactive senders via `extra_sent_today`), quiet hours 22:00-08:00 evaluated in the zone of the leg, dedupe per nudge key, expiry (a stale nudge is dropped, not sent late), per-trip mute ("trip mute"). Leave-by, delay and cancellation nudges are "critical": they bypass the cap and (switch `FRIDAY_TRIP_CRITICAL_BYPASSES_QUIET_HOURS`, default ON, a founder decision) quiet hours, because a silent leave-by for a 6 am flight is worse than a night message. A user message always wins: skip a task, move its time (locked against re-derive), or mute.

## Switches (all default OFF or conservative)
`FRIDAY_TRIPS_ENABLED=false`, `FRIDAY_TRIPS_ENABLED_USERS` (empty = all), `FRIDAY_TRIP_FLIGHT_WATCH_ENABLED=false` (no provider exists), `FRIDAY_TRIP_LOUNGE_ENABLED=false`, `FRIDAY_TRIP_DOMESTIC_BUFFER_MINUTES=120`, `..._INTERNATIONAL_...=180`, `FRIDAY_TRIP_TRAIN_BUFFER_MINUTES=45`, `FRIDAY_TRIP_DEFAULT_TRAVEL_MINUTES=60`, `FRIDAY_TRIP_HOTEL_CALL_HOUR=10`, `FRIDAY_TRIP_CAB_PROPOSE_HOURS_BEFORE=12`, `FRIDAY_TRIP_DAILY_CAP=5`, `FRIDAY_TRIPS_RETENTION_DAYS=30`. `ops/doctor` lists the switch and warns when on.

## Data (0017_trips)
`trips`, `trip_legs`, `trip_tasks`, `flight_watch`, `trip_nudges` (per user, `user_id` is the erasure key) and shared `card_perks`. Titles, airports, booking references, hotel phone/address, pickup address and message text are encrypted (field cipher); the booking reference also has a blind index for duplicate detection. No file or document text is stored. `DataPurger.purge_user` deletes them; retention deletes a trip 30 days after its last day (`expire_trips`); RLS on with no policy (`deploy/supabase/rls.sql`). Untrusted document text (hotel name) is cleaned and capped before it reaches a title or a message.

## Not done / needs the founder
- **Not wired into the live chat router or the scheduler loop**: `TripCommands` and `TripService.tick()` are complete and tested; the production `TripSender` (WhatsApp text + buttons, template for out-of-window sends) is not written. Out-of-window nudges need an approved WhatsApp template (same open item as LIFE_STATE).
- Flight-status provider (decision 8), real card perk rows (a person enters them from public bank pages), approval of every line and the hotel-call questions, and the numbers above are all pending.
- A flight/train cancellation seen by the status watch now asks the refund tracker to PROPOSE a refund case (`TripService(refunds=...)`, docs/REFUNDS.md); the user confirms, nothing is requested from anyone.
- Passport-validity and name-mismatch doc checks from the design are not built. Forward-to-family (G2) is not built.
- Quiet hours and the cap day are IST-based for the cap and leg-zone-based for quiet hours; a user who lives abroad is not modelled.
