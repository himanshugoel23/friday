# Robin fall detection: developer design (2026-11-06)

Author: developer agent, for the founder and the engineering manager (the EM plan is a separate doc). Docs only: no code was changed.
Basis: read of `friday/robindevice/{scenarios.yaml,ports.py,service.py,schemas.py,rules.py,engine.py}`, `friday/robin/alerts.py`, `docs/ROBIN_ANDROID_APP.md`, `docs/ROBIN_EMERGENCY_FLOW.md`, `docs/ROBIN_PHASE1_BACKLOG.md`.
Evidence tags: **[S]** seen in this repo, **[K]** platform knowledge from memory, not re-checked online in this pass, **[U]** unverified: needs a Play Console, vendor-doc or real-phone check, **[A]** my assessment. Every number is a design guess until the shadow week and mat tests tune it. Every spoken or shown line is PENDING founder approval (hear-before-change). No sizes below are measurements.

## 0. Honest limits first (put these in front of the founder)
1. **A phone detects a fall only if the parent is carrying it** (pocket, waist pouch, lanyard). Older people often leave the phone on a table or charger at home. Coverage is therefore "falls while carried". We must measure a *carry ratio* in the pilot and tell families plainly. A watch or pendant covers more [A]; see 1.6.
2. Public datasets are mostly young actors falling on mats. Real elderly falls (slow collapse, slide down a wall, fall in the bathroom) look different. **We cannot measure real sensitivity in a 4-20 family pilot**; we can measure false alarms and carry coverage. Marketing must never say "detects falls"; say "tries to notice a hard fall and asks".
3. Android may kill or throttle the service (battery managers, Doze, user swipes the app away). We must detect that and tell the child (section 1.4).
4. Fall detection must never be the only safety path: SOS hold, the daily check-in and S7 (unreachable) stay.
## 1. On-device detector (thin Android app)
### 1.1 Where it sits
New "Safety pack" (Level 1b), separate from the Level 2 Protection pack so Play review of the thin widget stays easy [A]. Permissions: none for the accelerometer/gyroscope [K]; `POST_NOTIFICATIONS` (13+); `FOREGROUND_SERVICE` + a typed FGS permission; `ACTIVITY_RECOGNITION` (runtime, 10+, optional, used for the vehicle filter and step cues); `USE_FULL_SCREEN_INTENT` for the countdown screen over the lock screen. Persistent notification "Robin fall protection is on" (never hidden). New consent item `fall_detection` (child grants on the parent's behalf, `admin_on_behalf`, parent can withdraw or STOP; STOP turns the service off on the phone).
### 1.2 Sensor pipeline
- Source: `TYPE_ACCELEROMETER` (includes gravity) at **50 Hz** (`samplingPeriodUs=20000`, `maxReportLatencyUs` about 1-2 s so the hardware FIFO batches and the CPU can sleep) [K]. 50 Hz is enough for threshold impact detection; waist-worn research used 100-200 Hz but impact peaks of 2.5-4 g survive at 50 Hz with a small amplitude loss [A]. Above 200 Hz Android 12+ needs `HIGH_SAMPLING_RATE_SENSORS`; we do not need it [K].
- Gyroscope (`TYPE_GYROSCOPE`) is **not run continuously** (power). It is registered at 50 Hz only when a candidate starts and held for 10 s [A]. If the device has no gyro the detector degrades to accelerometer-only (fewer score points, same flow).
- Ring buffer in RAM: 15 s of accel (50 Hz x 3 floats, a few KB). Nothing is written to disk. **No raw sensor sample ever leaves the phone** (server receives enums only, 2.2).
- Signal: SVM = sqrt(ax^2+ay^2+az^2) in g; gravity vector from a 1.5 s low-pass for posture (angle to vertical).
- Phone placement is unknown; every feature must be orientation-independent (SVM, angle *change* of the gravity vector, variance), never "z axis > x".
### 1.3 Heuristic v1: free-fall -> impact -> stillness, as a score (not a hard chain)
Falls from standing often have **no clean free-fall phase**, so free-fall is a bonus, not a gate [A].
| Step | Test (starting values, `fall_profiles.yaml`, `balanced`) | Points |
|---|---|---|
| Candidate gate | any sample SVM >= 2.5 g (cheap check, runs always) | opens a 10 s window, starts gyro |
| Free-fall | SVM < 0.6 g for >= 80 ms in the 1 s before the peak | +1 |
| Impact | peak SVM >= 2.8 g (+1 more at >= 4.0 g) | +2 / +3 |
| Rotation | gyro magnitude peak >= 250 deg/s in the window, or no gyro: skip | +1 |
| Posture change | angle between gravity before (1.5 s) and after (2 s, from t+3 s) >= 60 deg | +1 |
| Stillness | after the impact, 5-8 s with SVM std < 0.08 g and no step cue | +2 |
| Prior activity (Activity Recognition) | was WALKING/ON_FOOT within 10 s before | +1 |
| Vehicle | IN_VEHICLE state, or vibration signature of a moving car (sustained 5-30 Hz low-g content) | veto |
| Phone dropped | free-fall then a spike with *no* rotation, no posture change, and a still tail on a flat surface (z about +-1 g) within 1 s | -2 |
| Sat down hard | peak < 3.2 g, no free-fall, no posture change to horizontal, movement resumes < 4 s | -2 |
Confidence bands: `low` 4-5, `medium` 6-7, `high` >= 8 (max about 11). Below 4: logged as a counter only. `low` runs the countdown only when sensitivity is `careful`. Per-family profile, section 3.2.
Timeline of one candidate: t0 peak -> t0+8 s observation (if sustained walking appears before t0+8 s the candidate is discarded as recovered and counted `auto_recovered`) -> countdown.
### 1.4 Foreground service, battery, Doze, OEM killers
- Android 9+ gives background apps no continuous sensor events; **a foreground service is mandatory** [K]. Android 14 requires a declared FGS type; candidates are `health` (needs one of the permissions the type demands, `ACTIVITY_RECOGNITION` is the natural one [U]) or `specialUse` (needs a Play justification and review [U]). Decide at the first Play closed-testing build; keep the type behind one manifest line.
- Android 15 adds limits on starting some FGS types from `BOOT_COMPLETED` and timeouts for `dataSync`/`mediaProcessing` [K]; confirm `health` is unaffected [U]. Restart after reboot via boot receiver; if the OS blocks it, the app shows a "tap to turn on fall protection" notification.
- Doze: a foreground service with batched sensors keeps getting events when the screen is off, usually without a wake lock (batching lets the AP sleep) [K/U]. Do not hold a permanent `PARTIAL_WAKE_LOCK`; take a 60 s one only during a candidate and countdown.
- Battery: continuous batched 50 Hz accel is low-power on modern phones (order of 1-3 % per day) [U, no measurement]. Set the target "fall service under 3 % per day" in the existing 24 h battery test (Android doc test 10).
- OEM killers (Xiaomi MIUI/HyperOS, Vivo, Oppo/Realme, Samsung "sleeping apps", Huawei) kill FGS and block auto-start [K]. Setup must open the maker's own "no restrictions"/"autostart" screen (the doc already requires this for the pack). Do not request `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` directly: Play restricts it [K/U]; use the settings screen intent.
- **Health reporting**: the heartbeat carries `fall_state` (`running`, `off_by_parent`, `permission_missing`, `service_not_running`, `sensor_missing`) so the server can say "fall protection is off on Papa's phone" to the child instead of silently not protecting. `service_not_running` for > 2 heartbeats while awake -> child WATCH. A watchdog `WorkManager` job (15 min) restarts the service and records `restarted_by_watchdog` (counter).
### 1.5 Play policy and permissions [U until submitted]
- Declare as a **safety/health-adjacent monitoring feature**, user-visible, persistent notification, in-app transparency screen listing "motion sensors: used on the phone only; only an alert is sent". Health apps declaration and no medical claims ("not a medical device, may miss falls") [K/U].
- FGS type justification (video of the feature in the console is required on Android 14+ targets) [K/U]. `USE_FULL_SCREEN_INTENT`: Android 14 auto-grants only calling/alarm apps, others are user-revocable [K/U]; fallback is a max-importance alarm-category notification plus the sound; test on 13, 14, 15.
- Activity Recognition permission is optional: if denied, vehicle veto falls back to the vibration signature and the `prior_activity` enum is `unknown`.
- No SMS, no call permission, no contacts. "Call family" is `ACTION_DIAL` (no permission).
### 1.6 Platform fall detection and what apps can read [U]
- Pixel Watch and Galaxy Watch have built-in fall detection that auto-calls emergency services [K]. Some Pixel/Galaxy phones have car-crash detection, not fall detection [K/U]. **Third-party apps cannot read these results** and cannot hook their emergency call [K/U]; do not plan on it.
- Activity Recognition API (Play services) exposes STILL/WALKING/RUNNING/ON_BICYCLE/IN_VEHICLE transitions; no fall type [K]. Useful as a filter only.
- Health Connect has steps, heart rate, sleep, exercise; **no fall record type** [K/U]. A watch could write heart rate/steps to Health Connect, giving context (not detection).
- Wear OS Health Services passive monitoring: no fall data type that third parties can subscribe to [U]. A Wear OS companion could run **our own** detector on the watch accelerometer (wrist-worn false alarms are higher: clapping, washing hands, hands thrown down) and message the phone. Spike ticket F14; out of the pilot.
### 1.7 Optional tiny ML verifier (v2, not before shadow data)
Run only on gated candidate windows (so no continuous inference cost): 4 s window (1 s before, 3 s after), features or a small 1D-CNN, TFLite under 100 KB, output P(fall). It can only **veto or confirm** the heuristic (never create a candidate alone). Train on public data plus our own volunteer recordings; expect domain shift (waist sensors, young actors) so threshold and veto weight come from our own labelled traces. Ship behind the same profile file; shadow-compare for a week before it can veto.
## 2. Server contract and escalation
### 2.1 The Android side before the server: the "Are you OK?" countdown
| Time | Phone | Server |
|---|---|---|
| t0 | impact; 8 s observation | nothing |
| t0+8 s | countdown starts: alarm-stream sound at max volume, vibration pattern, full-screen "Aap theek hain?" with two big buttons: **I'm fine** (green, cancel) and **I need help** (red). Pre-rendered audio line from the server (3 languages, cached on pair), not the phone's TTS, so no dependency on an installed Hindi voice [A]. Optional second sentence at +15 s louder | `fall_suspected` sent (enum, queued normally) |
| tap **I'm fine** | stops everything, shows a calm "Theek hai" | `fall_cancelled` -> INFO digest |
| tap **I need help** | goes straight to the SOS path | `POST /sos` with `reason: "fall"` -> EMERGENCY (exists today, works while paused, no consent item needed) |
| t0+8+30 s (countdown default 30, range 20-45, child sets none of this; profile) | no tap -> "Robin is telling your family", sound keeps going, "Call son" `ACTION_DIAL` button | `fall_unanswered` sent immediately (not behind the queue, retry every 10 s for 2 min like SOS) |
| +60 s after unanswered | (nothing) | family side rings the parent's phone through the check-in caller; parent picks up and says fine / "I have it" from the child closes it |
| +5 min unanswered and no child ack | (nothing) | auto-promote to EMERGENCY ladder (second contact, authority path per ROBIN_EMERGENCY_FLOW: dry-run, policy-gated, needs "two independent signals": fall_unanswered + parent not reachable by call counts) |
Offline phone: the alarm keeps sounding, retries run, the child sees nothing until the network returns; S7 (unreachable) later covers it. Honest gap, cannot send SMS (restricted permission) [A].
### 2.2 New device signals (fixed enums, extra=forbid, no free text)
Add to `schemas.py` (pattern as the existing events) and `SIGNAL_CONSENT` -> `fall_detection`; add `fall_detection` to `CONSENT_ITEMS` in `ports.py`:
| type | fields |
|---|---|
| `fall_suspected` | `fall_id` (app random), `confidence` low/medium/high, `impact_band` `lt3g`/`3_4g`/`4_6g`/`gt6g`, `freefall` bool, `posture_change` bool, `stillness_band` `lt5s`/`5_15s`/`gt15s`, `prior_activity` walking/still/vehicle/unknown, `profile_version` int |
| `fall_cancelled` | `fall_id`, `after_s_band` `lt5`/`5_15`/`15_30`, `how` `button`/`auto_recovered` |
| `fall_unanswered` | `fall_id`, `confidence` |
| `fall_help_requested` | `fall_id` (also sent via `/sos`; this one is the audit twin) |
Also: heartbeat gets `fall_state` (enum above) and `carry_band` (`lt1h`/`1_3h`/`3_6h`/`gt6h` of phone-on-body time yesterday, from significant-motion and step counts); heartbeat *reply* gets `fall: {enabled, profile: calm|balanced|careful, profile_version, countdown_s}` (ints inside fixed ranges; the app owns the numeric thresholds table). `/sos` body gets optional `reason: "button"|"fall"` (default button). Ingest change: `fall_unanswered` and `fall_help_requested` are **exempt from the pause drop** (like SOS) but not from STOP (service is off) and not from the consent check (if consent was withdrawn the phone has stopped detecting anyway).
Never sent: raw samples, sensor graphs, location (location only on SOS and only with the `location` consent, existing rule), floor/room.
### 2.3 Scenarios in `scenarios.yaml`
rules.py forbids an `EMERGENCY` tier in a scenario ("comes only from SOS") [S], so: HIGH from the engine, EMERGENCY from the SOS path or the family-side promotion.
```yaml
  - id: S9
    name: fall_unanswered
    priority: 3                  # above everything except S5
    window_min: 30
    cooldown_min: 20
    shiftable: false             # sensitivity acts in the phone profile, not here
    suppressible: false          # 'this was fine' must never teach the server to ignore falls
    shadow_exempt: true          # DECISION D1 below
    safety: true                 # NEW flag: ignores quiet hours and the nudge ceiling
    money: false
    needs_consent: [fall_detection]
    signals:
      - {id: unanswered, predicate: fall_phase, params: {phase: unanswered}, weight: 4, required: true, why: "fall alert on the phone was not answered"}
      - {id: high_conf, predicate: fall_phase, params: {phase: suspected, min_confidence: high}, weight: 1, why: "strong impact"}
      - {id: night, predicate: fall_at_night, params: {start: "22:00", end: "07:00"}, weight: 1, why: "at night"}
      - {id: cancelled_after, predicate: fall_phase, params: {phase: cancelled}, weight: -10, why: ""}   # a later tap closes it
    tiers:
      - {tier: HIGH, min_score: 4, prompt: s9_high, child_alert: true, full_screen: true}
  - id: S9N                       # the cheap, shadowable one: cancelled falls and the trend
    name: fall_cancelled_trend
    priority: 70
    window_min: 10080            # 7 days
    cooldown_min: 1440
    shiftable: true
    suppressible: false
    shadow_exempt: false
    needs_consent: [fall_detection]
    signals:
      - {id: cancelled, predicate: fall_count, params: {phase: cancelled, min_count: 1}, weight: 1, required: true, why: "{count} fall-like alerts this week, answered fine"}
      - {id: repeat, predicate: fall_count, params: {phase: cancelled, min_count: 3}, weight: 2, why: ""}
    tiers:
      - {tier: INFO, min_score: 1, child_alert: true, digest: true, defer_quiet: true}
      - {tier: WATCH, min_score: 3, prompt: s9n_watch, child_alert: true, defer_quiet: true, digest: true}   # "maybe unsteady, consider a check"
```
New predicates in `engine.PREDICATES`: `fall_phase`, `fall_count`, `fall_at_night`. `known_predicates()` already validates names [S]. `safety: true` needs a small engine change so quiet hours and `nudges_per_hour` do not apply (night bathroom falls are the commonest case [A]).
### 2.4 Mapping to alert tiers
| Situation | Tier | Child sees | Parent phone |
|---|---|---|---|
| below score 4, auto-recovered | counter only | nothing (shows in transparency counters) | nothing |
| countdown answered "I'm fine" | INFO | weekly/daily digest line | calm text |
| 3+ answered alerts in 7 days | WATCH (S9N) | "several fall-like alerts, consider a check-in" (not medical) | none |
| countdown unanswered | HIGH (S9) | WhatsApp at once + call (see 2.5), buttons Mark safe / I have it / Call papa | alarm continues, "Call son" |
| "I need help" tap, or SOS hold | EMERGENCY (`sos`, reason fall) | existing SOS ladder | existing SOS ack |
| HIGH unanswered 5 min, parent not reachable by call | EMERGENCY via promotion | second contact, authority dry-run per emergency flow | - |
### 2.5 Family-side changes (`friday/robin/alerts.py`)
Today a non-`sos`, non-`checkin*` scenario needs `DEVICE_SIGNALS` or payment consent and HIGH's plan puts the first child call at 1 x call spacing (default 5 min) [S]. For falls: (a) treat scenario `fall` as `internal` like `checkin*` (the child set fall protection up deliberately; same gate as SOS category physical); (b) add a `plan_for` branch `fall`: `wa_child 0, call_child 0, nudge_parent 0, call_parent 60 s, wa_second 120 s, promote_emergency 300 s`; (c) new step actions `call_parent` (uses the check-in caller) and `promote_emergency` (existing `confirm_emergency`, by="auto_fall"); (d) `category_of("fall")` = physical; the child message line comes from copy keys, built from enums only: "Papa's phone detected a hard fall and he did not answer at 7:42 pm" (PENDING). The wiring seam `_DeviceAlerts` maps device `S9` -> family scenario `fall` (T01's normaliser; add the table row and the contract test row).
The first-call-at-0 rule applies only to `fall`; other HIGH plans stay unchanged.
### 2.6 Shadow week
D1 (founder decision): a safety event cannot be log-only. My recommendation: **S9 (unanswered) and the help tap are live from day 1; S9N and everything else is shadow for the 7-day window**, and the child is told in the pairing message "fall alerts to you are live from day 1, trend notes start after the learning week". The phone itself runs detection and the countdown from day 1 (without it we cannot measure). Alternative (log-only for 3 days) means a real fall in those days alerts nobody: not recommended.
Engine changes: none for shadow itself (`shadow_exempt` exists [S]); counters `shadow:S9N:*` appear in `shadow_report` automatically. Add `fall` keys to the report in 3.3.
## 3. False alarms
### 3.1 Cases and mitigations
| Case | Mitigation |
|---|---|
| Phone dropped (hand/table/bed) | drop signature penalty (1.3); posture on a flat surface; countdown still gives the parent 30 s to cancel |
| Sitting down hard / flopping on sofa or bed | no free-fall, peak < 3.2 g, movement resumes: penalty; low confidence does not alert in `balanced` |
| Vehicle (car bump, auto-rickshaw, bus, braking, door slam) | Activity Recognition IN_VEHICLE veto; vibration signature; do not start the countdown if vehicle in the last 60 s |
| Bag/pocket knock, kids, pets | stillness requirement; auto-recovered counter |
| Phone charging on a table | when charging and static for > 10 min, ignore spikes unless a posture change of the *gravity vector* occurs (phone itself tipped) [A] |
| Exercise, yoga, stairs, bumpy road on foot | prior_activity running/stairs raises the gate to 3.5 g [A] |
| Sleeping / night | no change in detection; countdown volume stays high (hearing loss). A night false alarm wakes the parent: accept, measure |
### 3.2 Per-family tuning
- The child's existing Calm / Balanced / Careful maps to three phone profiles in `fall_profiles.yaml` (versioned, one file read by the app build, the Python harness and the server for validation): `careful` lowers the gate to 2.2 g and accepts `low` confidence; `calm` raises to 3.2 g, requires 8 s stillness. Countdown 30 s default, **45 s** for parents with slow reaction (a per-parent switch the child can set; never below 20).
- Learning: only *downward* (fewer alerts) with human approval. If > 3 cancelled alerts per week with the same `prior_activity` and `stillness_band`, the child is offered "make Robin less sensitive for Papa?" -> profile `calm`. The server never auto-lowers sensitivity and "this was fine" never suppresses S9 (see yaml).
- Rate limit on the phone: after a cancelled alert, a 2 min refractory period (but not for `high` confidence).
### 3.3 Shadow-week metrics (counts and enums only, from `shadow_report`)
Per family and overall: candidates per day; cancelled / unanswered / help / auto_recovered share; median time-to-cancel (`after_s_band`); alerts by hour of day (night share); confidence band mix; impact_band mix; prior_activity mix; carry_band distribution (coverage); `fall_state` uptime (% of awake heartbeats `running`); service restarts by watchdog; false-alarm rate target (starting guess, [A]): **unanswered with "this was fine"/Mark safe by child < 1 per family per month; cancelled alerts < 1 per family per week**; battery delta from the fall service. Goal is to learn the real baseline, not to hit those numbers.
## 4. Testing without hardware
### 4.1 Layers
1. **Pure detector library** (Kotlin, no Android classes): `FallDetector.feed(tNs, ax, ay, az, gx, gy, gz): Event?` plus a `SensorSource` interface so a replay source can drive it. Same logic is re-implemented as a **Python reference** in a test helper (`tests/robindevice/falls/`), both reading `fall_profiles.yaml`. Golden vectors (trace file + expected events with time tolerance +-100 ms) are shared; CI runs JUnit (JVM) and pytest and fails if they disagree. This is the contract; the Android service is a thin wrapper.
2. **Trace format**: CSV `t_ms,ax,ay,az,gx,gy,gz` (m/s^2, rad/s) + a JSON label (`kind`, `expected: [fall|none]`, `placement`, `subject_group`). Resample all sources to 50 Hz.
3. **Synthetic traces** (Python generator, seeded): ADL templates (walking at 1.8-2.2 Hz with 1.1-1.6 g peaks, standing up, sitting down soft and hard, lying on a bed, phone dropped on table/floor/bed, phone placed on a table, car bump/braking/door slam, stairs, sofa flop) and fall templates (forward, backward, sideways, collapse-slide, with/without free-fall), with random 3-D rotation (placement), per-sensor noise and bias, and a 15 s ring of pre-activity. Validates plumbing, thresholds' *direction* and regressions; **it does not prove accuracy**.
4. **Server-side**: pytest with `FakeAlertPort` and the fake clock drives `DeviceService.ingest` through full sequences (suspected -> unanswered -> HIGH -> promotion -> EMERGENCY; cancelled; pause-exempt; consent withdrawn; shadow report), as the existing tests do [S]. Adds rows to the alert contract table (T01).
5. **Emulator**: virtual sensor injection (`adb emu sensor set acceleration x:y:z`) is coarse, one value at a time, not 50 Hz [K/U]: only for UI/permission/service-lifecycle checks, not detection. There is no emulator in the current sandbox (HANDOFF 2026-11-06).
### 4.2 Public datasets (licences: all [U verify], many are research/non-commercial; Robin is a company, so write to the authors before training a shipped model)
SisFall (Univ. de Antioquia; 38 subjects incl. 15 aged 60-75 doing ADLs, 15 fall types, waist sensor, 200 Hz) [K]; MobiAct/MobiFall (HMU Crete; smartphone in trouser pocket, 4 fall types, about 66 subjects; registration form) [K]; UP-Fall, UMAFall, KFall, FARSEE, SmartFall [K, details U]. Caveats: young-actor falls onto mats, device placement differs from a phone in a pocket/hand, labelling differences. Use for (a) threshold sanity, (b) ML pre-training, never as the only evidence. If a licence forbids commercial use: use for internal threshold *research* only if the licence allows, otherwise rely on our own recordings. Raw data is never committed to the (public) repo: the script `fetch_and_convert` takes a local path, and only derived stats go in docs.
### 4.3 What still needs real phones and people
- Real phones: sensor sample rates and jitter per model, FIFO batching, FGS survival and restarts across Xiaomi/Vivo/Oppo/Samsung on Android 11-15, battery per day, full-screen-intent behaviour, alarm volume/DND, boot restart, 48 h offline behaviour. Add to the Android doc's real-phone checklist.
- Mat tests: trained **staff or paid adult volunteers** (not elderly) perform scripted falls onto crash mats with phones in trouser pocket, hand, bag, shirt pocket, on a lanyard; a written protocol with a first-aider, a medical sign-off and insurance [A].
- Elderly volunteers (with written consent, family aware): **no falls**. They carry the phone for 1-2 weeks doing ordinary life to measure false alarms, carry ratio, countdown audibility (hearing), reaction time to cancel, button size. Ethics/safety review before; data stays on the phone except enum counters; a research build with explicit separate consent may store local traces for the team (never in the production app).
- Hindi/Hinglish countdown audio audibility test with the founder's approval of the sound before it is built.
## 5. Proposed tickets (S = up to 1 day, M = 2-3 days, L = 4-6 days of agent work; guesses, not measurements)
| # | Ticket | Size | Needs | Depends on |
|---|---|---|---|---|
| F01 | Founder decisions D1-D5 + freeze `fall_profiles.yaml` and the enum list | S | founder | - |
| F02 | Server contract: 4 signal schemas, `fall_detection` consent item, heartbeat `fall_state`/`carry_band` + reply `fall`, `/sos reason`, pause-exempt list, tests, update ROBIN_ANDROID_APP.md | M | fakes only | T01, T02 |
| F03 | Engine: predicates `fall_phase`/`fall_count`/`fall_at_night`, S9/S9N in scenarios.yaml, `safety` flag, shadow report keys | M | fakes | F02 |
| F04 | Family side: `fall` plan, internal scenario, `call_parent`/`promote_emergency` steps, category physical, copy keys in 3 languages, **audio samples for founder approval** | M | founder audio approval | F03, T09 |
| F05 | Python reference detector + synthetic generator + golden vectors + parity-test spec | M | fakes | F01 |
| F06 | Dataset converter and evaluation script (SisFall/MobiAct), licence check written up | M | licence replies | F05 |
| F07 | Kotlin pure-JVM detector module + JUnit parity (part of T14) | M | CI | F05 |
| F08 | Android service wrapper: FGS, batching, boot/watchdog, `fall_state`, OEM battery screens | L | real phones | F07, T14 |
| F09 | Countdown UI: alarm/vibration/audio, I'm fine / Help / Call son, retries, offline behaviour | L | real phones, F04 audio | F08 |
| F10 | Activity Recognition permission flow + vehicle veto | S | real phone | F08 |
| F11 | Fall metrics in the shadow-week report (T17) | S | fakes | F03 |
| F12 | Field protocol: mat-test script, volunteer ADL week, consent forms, safety sign-off | M (doc) + L (execution) | people, insurance | F09 |
| F13 | ML verifier (TFLite) trained on our data | L | F12 data | F12 |
| F14 | Wear OS / pendant option spike | M | a watch | F12 |
Order: F01 -> F02/F05 in parallel -> F03 -> F04/F07 -> F08/F09/F10 -> F11 -> F12. Nothing is turned on by default (`FRIDAY_ROBIN_DEVICE_ENABLED` and the `fall_detection` consent gate it).
### Decisions needed from the founder
D1 shadow policy for falls (recommend live unanswered/help from day 1). D2 auto-promotion to EMERGENCY after 5 min and the authority path stays dry-run (recommend yes; legal gate unchanged). D3 countdown 30 s default, 45 s option. D4 whether the Safety pack ships in the first Play build or after the thin widget is approved (recommend after). D5 pilot families must carry the phone: approve a pouch/lanyard or a watch for the first 4 families.
## 6. Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Phone not carried | most falls missed | carry_band metric, honest wording, pouch/lanyard, watch spike |
| False alarms exhaust the child and the parent | trust loss, switch-off | countdown, profiles, S9N digest, tuning loop, kill switch by parent STOP |
| OEM/Doze kills service | silent no protection | `fall_state` heartbeat + child WATCH, watchdog, setup screens |
| Play rejects FGS type / full-screen intent / battery permission | no distribution | closed-testing early, alarm-category fallback, `specialUse` justification |
| Public-dataset licences forbid commercial use | no pretrained model | own data, heuristic v1 needs none |
| Over-claiming | legal and ethical | wording review, "may miss falls", no medical claim |
| Alert reaches nobody (Meta blocked, offline) | real fall unnoticed | existing SMS/webchat fallbacks (T08), call_child at step 0, S7 |
| Automatic EMERGENCY / authority call on a false alarm | wasted services | dry-run only, two independent signals, 60 s cancel window per emergency flow |
| Hearing loss: parent cannot hear the countdown | unanswered by accident | max alarm volume, vibration, 45 s option, child told "unanswered" with a call, not a diagnosis |
| Sensor data privacy creep | DPDP, trust | enums only, RAM buffer, research build separate and consented |
