# Robin: fall detection, engineering manager plan (2026-11-06)

Author: engineering manager agent. Docs only; no code changed. Founder asked (2026-11-06) for a brainstorm on detecting when the parent falls at home.
Tags: **[S]** seen in repo docs or well-known public facts, **[U]** unverified (needs a real device, Play Console or vendor check), **[A]** my assessment.
Every spoken or shown line below is a draft: PENDING founder approval (hear before change). Nothing here is live and no real call is implied.

Fits what exists: thin widget with press-and-hold SOS (docs/ROBIN_ANDROID_APP.md), 11 fixed signal enums and scenarios S1-S8 (friday/robindevice/scenarios.yaml),
SOS always works (founder, 2026-11-06), check-in ladder (S7), AI emergency desk with dry-run authority calls (docs/ROBIN_EMERGENCY_FLOW.md).
Earlier docs said "not Phase 1" (PARENT_CARE_RESEARCH.md line 50; PARENT_CARE_PHASE1_SPEC.md section 4). The founder has since said all safety features are Phase 1, so this plan supersedes that.

## 0. Honest bottom line
1. No option detects all falls. Every option misses some falls (slow slides, falls onto a bed, falls while the phone is on a table) and raises false alarms (phone dropped, sat down hard, jolted in an auto).
2. Phone-only detection is the only option needing no new hardware and no purchase by the family, but it needs the phone on the body. Elderly parents often leave the phone on a table [A].
3. The most dependable signal we already have is not a sensor: it is "parent did not answer" plus "phone has not moved". Build that chain first; it also catches non-fall emergencies (fainting, stroke).
4. The manual path (press-and-hold SOS, "Robin help") stays the primary promise. Automatic detection is a bonus, labelled as such.

## 1. Detection options, cheapest first
| # | Option | Cost to family | What it catches | Honest accuracy and limits |
|---|---|---|---|---|
| 1 | **Parent says or presses**: SOS hold (exists), new "I fell" button on widget, voice note "Robin, main gir gaya" to WhatsApp | none | Falls where the parent is conscious and can reach the phone | Zero false alarms from sensors. Fails if unconscious or phone out of reach. Today's widget has no "I fell" button: small add. |
| 2 | **"No activity" escalation**: daily check-in unanswered (S7), heartbeat gap, and new "phone not moved for N hours while awake hours" | none | The long-lie case: fell, cannot get up, hours pass | Slow (hours, not minutes). Phone left on a table looks identical to a fallen parent, so false alarms are likely; the first step is a gentle call/prompt, not an alarm. N tuned in shadow week (guess: 4 h awake) [A]. |
| 3 | **Phone sensors, own algorithm** (accelerometer + gyro: free-fall dip, impact spike, then stillness for ~10 to 30 s) | none | Falls with the phone in a pocket or on a lanyard | Academic threshold detectors look good on staged falls by young volunteers but degrade on real daily activity and on elderly gait [S in general, exact numbers U]. Expect a real false-alarm rate that is high until tuned; **we have no measured number**. Misses falls with phone away from body. |
| 4 | **Android built-in recognition** | none | Not falls | Activity Recognition API offers still/walking/in-vehicle/tilting, **no fall type** [S, U on latest versions]. Pixel crash detection is for cars [S] and needs the Google Personal Safety app. Pixel and Samsung **phone** fall detection: none found [U]. Pixel Watch and Galaxy/Apple Watch have fall detection [S], but third-party apps cannot read those fall events; Health Connect has no fall record type [U]. So: build our own (row 3) or use a watch's own alert (row 5). |
| 5 | **Smartwatch** the family already owns or buys (Pixel Watch, Galaxy Watch, Apple Watch is iOS-only and out of scope) | Rs 10,000+ [U] | Falls with the watch worn; best sensor quality | Watch's own fall alert goes to the watch's own emergency contacts, not to Robin [U]. Options: set the child's number + Robin as contact (no integration, partial), or a Wear OS app of ours reading sensors (second app, review, battery). Elderly often do not wear or charge watches [A]. Phase 2 spike. |
| 6 | **Cheap pendant / BLE button** (Rs 1,500 to 5,000 [U]) | small | Press-for-help; some models auto fall detect | BLE button needs the phone nearby and our app listening (battery, background limits). GSM pendants with SIM and fall detection call fixed numbers on their own [U]: could be set to call Robin's number (the AI desk answers) with no app integration at all. Quality varies; vendor claims are unverified. Phase 2 spike. |
| 7 | **Home sensors** (door, smart plug/power use, motion, camera) | Rs 3,000+ [U] | "No kitchen movement by 10 am", long lie | Vendor clouds, Wi-Fi at home, consent of everyone in the house. Already Phase 3 in PARENT_CARE_PHASE1_SPEC.md; keep there. |
| 8 | **Voice after a fall**: "Robin help" | none | Conscious parent speaking | **Always-listening wake word is not allowed by our own rule** (no microphone in the background, ROBIN_ANDROID_APP.md section 0). Allowed forms: say it on a phone call or voice note; tap the widget mic; or the countdown screen listens once after it appears (see section 2). Google Assistant "OK Google, call Robin" routine is a free add-on if the parent already uses it [U]. |

Recommendation [A]: build rows 1, 2, 8 (the allowed forms) and 3 in **shadow mode** now; spike 5 and 6 as research tickets; keep 7 in Phase 3.

## 2. User flow
Detection sources all produce one new signal: `fall_suspected` (enum + `ts_ms` + `source` in `phone|watch|button`; no raw sensor data leaves the phone).
```
phone detects impact + stillness (or watch/button/"I fell" press)
 -> T+0   on phone: vibrate, loud tone, full-screen "Are you OK?" in parent's language, read aloud; buttons "I am OK" / "I need help" (big)
 -> T+0 to 30 s  countdown on screen; "I am OK" cancels everything, nothing goes to the child except a line in the weekly digest
 -> T+30 s no reply  louder repeat plus one-shot "say: main theek hoon / madad" (opens mic once, parent-initiated screen only) [U Android 14 rules]
 -> T+60 s no reply, or "I need help": POST /sos path (same as SOS): child gets WhatsApp + call: "Papa may have fallen at 7:42 pm; no reply for 60 s", location only if consented
 -> T+3 min child has not acknowledged: second contact (WhatsApp + call), same ring-every-3-min loop as EMERGENCY (x6)
 -> unresponsive + not acknowledged by anyone + phone not moved since: authority route, DRY-RUN ONLY: Robin logs the 112 script it would speak
 -> any stop: parent "I am OK", child "I have it", child "Call arranged": ladder stops; parent gets "Beta ko bata diya" line
```
- Requires the existing preconditions in ROBIN_EMERGENCY_FLOW.md section 3 (admin recorded `authority_calls`, two independent signals or parent says yes, 60 s cancel window unless unresponsive). A fall signal alone is **one** signal; fall + no response + no phone motion counts as two [A]. Real 112 stays OFF until legal review; no real call is made in tests.
- **If the phone is offline** at T+60 s: the app retries SOS every 10 s for 2 minutes (existing rule) and shows "Call family" and "Call 112" one-tap buttons.
- **Quiet hours do not apply** to a fall that went unanswered; they apply only to the pre-alert gentle "are you OK" for the inactivity path (row 2).
- **Cancel is easy, escalate is automatic.** A parent who is fine presses one big button; a parent who cannot press anything gets help.
- **False-alarm handling:** "I am OK" within the countdown counts as a false alarm and teaches the per-parent detector (raise threshold one step after 2 in a week; never below a floor). Child sees the count in the weekly digest, can set sensitivity (Calm/Balanced/Careful, same as scenarios.yaml).
- **Budget per family per week [A, founder to confirm]:** at most 3 fall prompts to the parent per day and at most 2 child alerts per week that came from automatic detection with the parent replying "I am OK" later. Reaching the cap does not stop SOS or manual "I fell"; it switches automatic detection to "log only" and tells the child once ("Fall detection paused after repeated false alarms; tap to review"). It never switches off silently.
- Shadow period: like the 7-day shadow week, first 14 days of detector use log only (no countdown, no alert) so we can count would-have-fired events.

## 3. Phased plan and tickets
Sizes: S under 1 day, M 1 to 3 days, L 3 to 5 days of developer-agent time [A]. Numbering F01+ avoids collision with T01-T19 in ROBIN_PHASE1_BACKLOG.md. Fakes = pure Python/Kotlin tests with synthetic traces, no phone.
| ID | Ticket | Size | Depends on | Founder / real device | Testable with fakes |
|---|---|---|---|---|---|
| F01 | Add `fall_suspected` signal (12th enum), scenario S9 "fall" in scenarios.yaml (tiers WATCH/HIGH, source field, cooldown), copy keys in 3 languages | M | T01 (DONE) | Founder approves lines | Yes: engine tests with synthetic events |
| F02 | Server fall flow: prompt `full_screen`, countdown ack (`i_am_ok`), timeout to SOS path, second-contact timing, stop conditions, authority dry-run record | L | F01, T09, T08 | none | Yes: fake clock, fake child/second sender, authority dry-run log |
| F03 | "I fell" button + voice note "gir gaya" in widget/WhatsApp mapped to fall flow | S | F02, T14, T07 | Founder approves button label and audio | Server side yes; UI needs build |
| F04 | Inactivity signal: `phone_still_long` (enum + ts) from app, plus server rule using awake hours and battery; gentle first prompt then ladder S7 | M | F01, T14 | Real phone to measure drift | Server yes; app side needs phone |
| F05 | Detector design doc + pure Kotlin module (state machine: free-fall, impact, stillness) with replay harness on public fall/ADL datasets [U which licence] and synthetic traces; no raw data stored | L | T14 | Real phones and staged falls on a mattress (young volunteers, never elderly) | Replay yes; thresholds need real trials |
| F06 | Foreground service, battery whitelist guidance, Play declarations for sensor use, restart after reboot/OEM kill | M | F05 | Real phones per OEM (Xiaomi, Vivo, Samsung), Play Console | Partly (unit); behaviour needs devices |
| F07 | Shadow mode (14 days log only) plus false-alarm counter, weekly cap logic, child digest line | M | F02, F05, T17 | Founder reviews counts | Yes |
| F08 | Child sensitivity setting and parent "I am OK" teaching of the detector | S | F07 | none | Yes |
| F09 | Research spike: Wear OS/Galaxy Watch fall events via Health Connect, vendor SDK, or watch-to-contacts setup | S | none | A watch in hand | No (docs and one device) |
| F10 | Research spike: GSM/BLE pendant that dials Robin's number; AI desk answers a pendant call | M | T10, T11 | Buy 2 or 3 pendants; Vobiz number | Fake call only |
| F11 | Legal and Play policy review note (health-adjacent claims, sensor use, DPDP for health inference) | S | F05 | Counsel, Play | n/a |
| F12 | Supervised field test with founder's own family | M | F02, F05, F06, F07 | Founder, family, approval of every line, real phones | No |

**Phase recommendation [A]** (founder said all safety is Phase 1, so I split by risk, not by feature):
- **Phase 1, live:** manual paths (F03), fall flow and escalation from any source (F01, F02), inactivity chain (F04), child settings (F08), authority DRY-RUN only.
- **Phase 1, shadow then live:** phone detector (F05, F06, F07). It logs only until the shadow data shows an acceptable false-alarm rate in real pilot homes. **We should not turn on automatic fall alerts to children before this data exists.** If it does not, it ships as "log only" and the marketing does not mention automatic detection.
- **Phase 2:** watch and pendant integrations (F09, F10 spikes now, build later), real 112 call after legal review. **Phase 3:** home sensors and cameras.

## 4. Risks
- **Play Store [U]:** continuous sensor use needs a foreground service with a visible notification; Android 14 requires a declared foreground-service type and Play review of the reason (health/special-use, to be confirmed). Health-related claims and "emergency" features attract extra scrutiny; wording must say "alert" not "medical". Keep the Level 1 widget free of this (microphone only) so basic review stays easy: ship fall detection inside Level 2 (protection pack, installed by the child in person) or a third opt-in toggle.
- **Battery and background limits:** since Android 9 background apps get no continuous sensor data; the detector must run in a foreground service or use batched low-power sensors; target under 3 percent per day is an unmeasured goal [S: ROBIN_ANDROID_APP.md section 5]. OEM killers (Xiaomi, Vivo, Oppo, Samsung) will stop it; the setup must show the "unrestricted battery" screen. Doze can delay work; the detector must not rely on WorkManager (15 min minimum).
- **Permissions:** accelerometer needs no runtime permission on most versions, but high sampling rate may need `HIGH_SAMPLING_RATE_SENSORS` on Android 12+ [U]; notifications on Android 13+; full-screen intent permission on Android 14+ for the "Are you OK?" screen over the lock screen [U]; microphone for the one-shot reply only after the screen is shown; location only with the existing `location` consent.
- **Phone not on body:** the biggest practical limit. Say it plainly in setup and in the child's screen ("works when Papa carries the phone").
- **Alarm fatigue:** children who get three false alarms will mute Robin. The weekly cap and shadow period exist for this.
- **Safety and liability:** a missed fall is a harm; a false authority call is a harm. Authority stays DRY-RUN, human-reviewed logs by the founder, and a lawyer decides on 112.
- **Privacy:** only the enum, `ts_ms` and source leave the phone; raw accelerometer/gyro samples are processed in memory and discarded; no sensor traces in logs, crash reports or the server; the transparency screen lists "fall detection: on/off, last 20 events (time only)". Consent item `fall_detection` recorded by the child (admin on behalf), the parent can stop it from the widget; withdrawal erases stored fall events. A fall signal is health-adjacent personal data under DPDP [U]; keep retention at 30 days like the audit log [A].

## 5. What we must NOT claim
- Never "detects all falls", "detects every fall", "100 percent", "medical-grade", "life-saving", "replaces a caregiver or an alert pendant", or "calls an ambulance automatically".
- Never state an accuracy number until we have measured it in pilot shadow data; then state it with the sample size.
- Do say: "Robin can notice some hard falls when Papa carries his phone, and asks 'Are you OK?'. If he does not answer, it tells you. He can also press or say help at any time."
- Do not say fall detection works without the phone on the body, indoors/outdoors, or with a watch, until each is tested.
- Do not imply 112 is called; today it is a logged dry-run, and in Phase 1 the phone shows a one-tap "Call 112".

## 6. Questions for the founder
1. Is a shadow period (no automatic alerts for the first 14 days) acceptable, or do you want live alerts from day one with a clear "may give false alarms" warning to the child?
2. Fall detection in the optional Level 2 pack only (easier Play review), or also in the Level 1 widget?
3. Is the weekly cap (2 automatic child alerts that the parent cancels) right, and who is told when the cap is reached?
4. Countdown lengths: 30 s on screen, 60 s to child alert, 3 min to second contact. Too slow or too fast for your parents?
5. May we buy two or three BLE/GSM pendants and one Wear OS watch for the F09/F10 spikes (budget)?
6. May we run staged falls (mattress, young volunteers from the team) for tuning, and may the first live test be your own family?
7. Is the child told "Papa may have fallen" in these words, and may Robin say so to the second contact, who is not a Robin user?
8. Do you accept that an unconscious parent whose phone is on a table is not covered, and that we say so in setup?
