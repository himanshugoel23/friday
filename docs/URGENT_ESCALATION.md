# Urgent-call escalation: if you do not acknowledge, Friday rings you

Status (2026-10-27): built and tested offline with fakes. **No real call, no audio, no real WhatsApp message was
produced.** The switch `FRIDAY_URGENT_ESCALATION_ENABLED` is **off by default**. The spoken line is
**PENDING_FOUNDER_APPROVAL** (hear-before-change): the real dial adapter refuses to dial while it is pending, so
nothing can ring a phone until the founder has heard the audio and a reviewed commit flips
`friday/urgent/lines.py::LINE_STATUS` to `APPROVED`. Package `friday/urgent/`, tests `tests/urgent/`, migration
`0015_urgent_escalation`. Builds on the receptionist (docs/RECEPTIONIST.md), the CallGate (`friday/calls/gate.py`) and
the escalation idea of chatbot parity item 11 (`friday/chatbot/parity/escalation.py`, which only decides and dials
nothing; this package is the multi-attempt, persisted version with the real CallGate in front).

Founder idea (2026-10-27) and decision (default 5 minutes, configurable, per-user override).

## 1. How it works

```
receptionist classifies a forwarded call URGENT
   -> escalation opened (one per message, idempotent) -- only if switch ON and the user opted in
   -> WhatsApp alert at once: the usual summary + hint line + [Acknowledge] [Call back] [Ignore]
      (Acknowledge replaces Block on this alert: WhatsApp allows three buttons)
   -> timer starts when the alert was SENT (a failed send starts it from the opening: ringing is the better fallback)
user taps Acknowledge / Call back / Ignore / Block, or rings Friday         -> stop, never a call
N minutes (default 5) pass without that                                    -> call 1 to the user's OWN number
5 minutes later, still nothing                                             -> call 2 (max 2 by default)
the user picks up                                                          -> stop (they heard the line)
both calls unanswered                                                      -> one WhatsApp line: "I called you twice, please see the message above"
```

The runtime loop (`friday/api/runtime.py`, task `friday-urgent-escalation`, next to the receptionist loop) calls
`UrgentEscalation.tick()` every `FRIDAY_URGENT_ESCALATION_TICK_S` (20 s). The tick is safe to run on several replicas.

## 2. Settings and the per-user override

| Setting (env) | Default | Meaning |
|---|---|---|
| `FRIDAY_URGENT_ESCALATION_ENABLED` | false | master switch (the doctor lists it with the other switches) |
| `FRIDAY_URGENT_ESCALATION_MINUTES` | 5 | wait for Acknowledge before the first call |
| `FRIDAY_URGENT_ESCALATION_MAX_CALLS` | 2 | calls per escalation (hard maximum 3) |
| `FRIDAY_URGENT_ESCALATION_SPACING_MINUTES` | 5 | between those calls |
| `FRIDAY_URGENT_ESCALATION_DAILY_CAP` | 3 | escalations per user per IST day that may place a call (later ones only alert) |
| `FRIDAY_URGENT_ESCALATION_STALE_MINUTES` | 30 | an alert older than this (plus its wait) is never rung about (outage, restart) |
| `FRIDAY_URGENT_ESCALATION_RETENTION_DAYS` | 30 | finished rows are deleted |

Per user (table `urgent_escalation_configs`, encrypted JSON): `opted_in`, `number` (the number the opt-in came from),
`minutes` (clamped 2 to 60: never an instant call), `max_calls` (1 to 3), `spacing_minutes` (2 to 30),
`emergency_in_quiet_hours` (default true). WhatsApp commands (handled in `Receptionist.handle`): `urgent call on`
(also `chalu`), `urgent call off` (`band`; stops any running escalation), `urgent call 3 min`, `urgent call status`.
The timer of a running escalation is a snapshot: changing a setting never moves it.

## 3. Rules (each has a test)

* **Own number only.** The target is the number stored at opt-in, and it must equal the user's CURRENT phone at dial
  time; otherwise the escalation is `refused` and nothing is dialled. Three independent walls: `policy.decide`
  (`not_own_number`), `OwnNumberGate` (the user's phone must equal the number, then the real CallGate), and the
  real dialler (`pilot_dial_blocked`). In the pilot the allow-list (`FRIDAY_PILOT_ALLOWED_NUMBERS`) applies as for every call.
* **CallGate in front of every dial** (`friday/urgent/gate.py`): kill switch, user standing, abuse classifier, emergency
  numbers, pilot allow-list, do-not-call, daily caps, calling window. The per-call approval step is replaced by the
  user's standing opt-in (the brief is marked approved with its own hash only because the opt-in exists; `policy.decide`
  checks the opt-in first). Only one gate "ask" can be overridden: `outside_window`, and only for a true emergency.
* **Quiet hours** (the receptionist's own setting, default 22:00 to 08:00 IST): an ordinary URGENT call never rings
  (the escalation is cancelled with reason `quiet_hours`; the WhatsApp alert already went out). Only a **true
  emergency** may, and only if the user has not turned that off. A true emergency is decided by code only
  (`policy.is_emergency`): a built-in strong word of the receptionist's rules (accident, ambulance, heart attack, ICU,
  unconscious, died, fire, kidnap, bachao, behosh, ...). It is never: a model verdict, an "urgent contact", a custom user
  keyword, or a weak word ("urgent", "jaldi"). Words such as hospital, tabiyat, serious, surgery are urgent but not emergencies.
* **Kill switch** (`FRIDAY_PAUSED` / the pause flag file): running escalations are cancelled (`kill_switch`), none opens,
  and the real dialler refuses on its own. Turning the feature switch off cancels running ones too (`switch_off`).
* **Stops:** Acknowledge; Call back, Ignore or Block on the receptionist alert (the user has seen it); the user ringing a
  Friday number from their own phone (`note_inbound_call`, hooked in `api/callbacks.py`; only the user's own number matches);
  the user picking up the escalation call; opting out; all calls used.
* **No false urgency:** a stale alert, a missing opt-in, an inactive user or the daily cap cancel; no doubt ever rings.
  A model verdict can make a call URGENT (alert) but cannot make it ring at night.
* **One call attempt = one persisted attempt.** See section 4.

If the user declines Friday's escalation call and the carrier forwards it back to Friday's inbound number, the
receptionist recognises Friday's own pool number as the "test ring" case: nothing is spoken or stored.

## 4. Idempotent and restart-safe

Table `urgent_escalations` (one row per urgent receptionist message, UNIQUE user + message, no personal text) holds the
state machine; every transition is a compare-and-set in the store (same suite on memory and SQL):

* `create`: opening twice returns the existing row; a replayed webhook or restart never sends a second alert or timer.
* `claim`: pending + not in flight + `calls_made == expected` becomes in flight with `calls_made + 1`, **before** the dial.
  Two replicas ticking together place one call; a crash while ringing can never lead to a second dial of that attempt
  (the fake dialler also de-duplicates on `dedupe_key = <escalation id>:<attempt>`).
* After a crash the attempt stays in flight; after a 120 s grace period it is recorded as made (`unknown`) and the next
  call is scheduled by the spacing (an escalation whose last call crashed is closed as exhausted, no extra call).
* `close`: only a pending row can be closed, so a late Acknowledge never reopens anything and a stop during ringing is kept.
* A pending row survives restarts with its timer; a row older than the stale limit is cancelled instead of rung.

Data: `urgent_escalation_configs.config` is AES-GCM encrypted (it holds the user's number); `urgent_escalations` has no
number or text. `user_id` is the erasure key: `DataPurger.purge_user` deletes both (counts `urgent_escalations`,
`urgent_escalation_configs`); finished rows go after the retention period (each tick). `deploy/supabase/schema.sql` was
regenerated and both tables are in `rls.sql`; the doctor's `EXPECTED_HEAD_CHAIN` is `0015_urgent_escalation`.

## 5. Wiring (what changed outside `friday/urgent/`)

* `receptionist/service.py`: `ReceptionistService.escalation` (None = old behaviour exactly). `_push` opens the escalation
  for an URGENT message, appends the hint and puts Acknowledge first; button use calls `escalation.user_acted`.
  Any failure in the escalation is logged and never blocks the alert.
* `receptionist/wiring.py`: builds the component, routes `urg:<id>:ack` and the text commands; `note_inbound_call`.
* `core/container.py`: component `urgent_escalation` (None while the switch is off). `api/runtime.py`: the loop.
  `api/callbacks.py`: the "user rang Friday" hook. `core/config.py`, `ops/doctor.py`, `.env.example`: switches and names.

## 6. What the founder must do

1. Listen to the escalation call audio and approve (or change) the lines in section 7. Until then the real dial refuses
   (`line_pending`); WhatsApp texts are also PENDING approval.
2. Decide whether Acknowledge replacing Block on the alert is acceptable (WhatsApp reply buttons are limited to three).
3. For a first real test (CLAUDE.md rule 5: only the allow-listed founder number, only with approval): set the pilot
   allow-list, enable the receptionist and this switch, send `urgent call on` from the founder phone, flip `LINE_STATUS`
   in a reviewed commit, then place a forwarded urgent test call.

## 7. Every PENDING line

### 7a. Spoken on the escalation call (`urg.<key>.<language>`; the only slot is the name the user chose; no number, no caller, no detail)

| Id | Text |
|---|---|
| `urg.ring.urgent.hinglish` | Hello {user}, main Friday bol rahi hoon. Aapke liye ek urgent message aaya hai. Kripya abhi WhatsApp dekh lijiye. Thank you. |
| `urg.ring.urgent.hi` | हैलो {user}, मैं फ्राइडे बोल रही हूँ। आपके लिए एक urgent मैसेज आया है। कृपया अभी WhatsApp देख लीजिए। थैंक यू। |
| `urg.ring.urgent.en` | Hello {user}, this is Friday. There is an urgent message for you. Please check WhatsApp now. Thank you. |
| `urg.ring.emergency.hinglish` | Hello {user}, main Friday bol rahi hoon. Aapke liye ek emergency message aaya hai. Kripya abhi WhatsApp dekh lijiye. Thank you. |
| `urg.ring.emergency.hi` | हैलो {user}, मैं फ्राइडे बोल रही हूँ। आपके लिए एक emergency मैसेज आया है। कृपया अभी WhatsApp देख लीजिए। थैंक यू। |
| `urg.ring.emergency.en` | Hello {user}, this is Friday. There is an emergency message for you. Please check WhatsApp now. Thank you. |

### 7b. Written on WhatsApp (`urgw.<key>.<language>`)

| Id | Text |
|---|---|
| `urgw.alert.hint.hinglish` | Agar aap {minutes} minute mein Acknowledge nahi karenge, toh Friday aapko call karegi. |
| `urgw.alert.hint.en` | If you do not tap Acknowledge within {minutes} minutes, Friday will call you. |
| `urgw.alert.hint.emergency.hinglish` | Yeh emergency lag rahi hai. Agar aap {minutes} minute mein Acknowledge nahi karenge, toh Friday aapko call karegi (raat mein bhi). |
| `urgw.alert.hint.emergency.en` | This looks like an emergency. If you do not tap Acknowledge within {minutes} minutes, Friday will call you (even at night). |
| `urgw.reply.ack.hinglish` | Theek hai, acknowledge ho gaya. Ab main call nahi karungi. |
| `urgw.reply.ack.en` | Okay, acknowledged. I will not call you. |
| `urgw.reply.stale.hinglish` | Yeh alert ab active nahi hai. |
| `urgw.reply.stale.en` | That alert is no longer active. |
| `urgw.exhausted.hinglish` | Maine aapko {n} baar call kiya, par baat nahi ho payi. Upar wala urgent message dekh lijiye. |
| `urgw.exhausted.en` | I called you {n} time(s) but could not reach you. Please look at the urgent message above. |
| `urgw.optin.on.hinglish` | Theek hai. Jab koi urgent call aayegi aur aap {minutes} minute mein Acknowledge nahi karenge, Friday sirf aapke apne number par call karegi. Band karne ke liye likhiye: urgent call band. |
| `urgw.optin.on.en` | Okay. When an urgent call comes in and you do not tap Acknowledge within {minutes} minutes, Friday will call only your own number. To stop, write: urgent call off. |
| `urgw.optin.off.hinglish` | Theek hai, ab Friday urgent call ke liye aapko call nahi karegi. WhatsApp alert aata rahega. |
| `urgw.optin.off.en` | Okay, Friday will no longer call you for urgent calls. You will still get the WhatsApp alert. |
| `urgw.optin.minutes.hinglish` | Theek hai, ab {minutes} minute baad call karungi. |
| `urgw.optin.minutes.en` | Okay, I will call after {minutes} minutes. |
| `urgw.optin.unavailable.hinglish` | Urgent call ki suvidha abhi chalu nahi hai. |
| `urgw.optin.unavailable.en` | Urgent-call escalation is not available right now. |
| `urgw.optin.status.on.hinglish` | Urgent call chalu hai: {minutes} minute mein Acknowledge nahi kiya toh Friday aapko call karegi (max {calls} baar). |
| `urgw.optin.status.on.en` | Urgent call is on: if you do not acknowledge within {minutes} minutes Friday will call you (at most {calls} times). |
| `urgw.optin.status.off.hinglish` | Urgent call band hai. |
| `urgw.optin.status.off.en` | Urgent call is off. |
| `urgw.button.ack.hinglish` | Acknowledge |
| `urgw.button.ack.en` | Acknowledge |

## 8. UNVERIFIED / not done

* No real call, audio, or WhatsApp message; the real dial adapter (`telephony.py`) is tested only against a fake provider leg
  and refuses while the line is PENDING. How a real Vobiz/Sarvam call to a phone that has receptionist forwarding on behaves
  (the carrier may forward Friday's call back to Friday if declined or unanswered) is unverified.
* WhatsApp template for the alert outside the 24 h window is not registered (same gap as the receptionist's urgent alert).
* The calling-window rule of the CallGate (family window 08:00 to 21:30) and the receptionist quiet hours (22:00 to 08:00) leave
  a 21:30 to 22:00 gap in which an ordinary urgent call does not ring (gate ask); a true emergency does.
* The CallGate's own per-user call counters are not fed by these dials (they do not go through the call orchestrator); the
  daily cap here (`FRIDAY_URGENT_ESCALATION_DAILY_CAP`) is the cap that applies.
* Not run on Postgres (SQLite in tests); the compare-and-set updates are plain `UPDATE ... WHERE` and should hold there.
* Found while testing, not caused by this feature: `Runtime.stop()` hangs when the receptionist loop is cancelled mid-query on
  in-memory SQLite (the new test cancels the tasks itself).
