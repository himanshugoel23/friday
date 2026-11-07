# Robin family core (package `friday/robin`)

Status (2026-11-04): built and tested offline with fakes. **No real call, no audio, no real WhatsApp message was produced.** Master switch
`FRIDAY_ROBIN_ENABLED` is **off by default**. Every spoken or chat line is **PENDING_FOUNDER_APPROVAL** (docs/ROBIN_LINES.md); the real dial adapter
refuses to ring while they are pending. Migration `0019_robin_family`. Tests: `tests/robin`. Product spec: docs/PARENT_CARE_PHASE1_SPEC.md,
research: docs/PARENT_CARE_RESEARCH.md.

Phase 1 is AI-only: no vendor or third-party calling, no human rescue desk or console, never pays, never records calls, never reads
messages, notifications or SMS (the device package `friday/robindevice` handles signals and hands them over through `alerts.raise_alert`).
**112 / 1930 (updated by a later founder instruction, 2026-11-04):** the original Phase 1 rule was "Robin never auto-dials 112". It is now relaxed ONLY to the
policy-gated, DRY-RUN-ONLY module `authority.py` (section 14): switch off by default, no live adapter exists, the CallGate still refuses emergency numbers. Nothing
in this repo places or simulates a real 112 call; the SOS flow itself still only rings the child and the second contact and shows the parent a one-tap "call 112".

## 1. Switches (all default OFF; names only, none in `deploy/enable-web-test.sh` FEATURES_ON; they are in its ALWAYS_OFF list = KEPT OFF)

| Setting (env) | Default | Meaning |
|---|---|---|
| `FRIDAY_BRAND_NAME` | `Friday` | the ONE place the product name lives; the Robin pilot sets `Robin`. Every line takes `{brand}` from it (a test fails if a line types a name) |
| `FRIDAY_ROBIN_ENABLED` | false | builds the `robin` component (container), the chat hook in `InboundPipeline._active`, the scheduler task `friday-robin` |
| `FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED` | false | T07: builds `ctx.parent_channel` (`channel.WhatsAppParentChannel`) in `build_robin`, only together with the cloud WhatsApp channel configured (token + phone number id); otherwise lines wait in the app outbox. The inbound parent route is always on with Robin |
| `FRIDAY_ROBIN_SAFE_WORD_ENABLED` | false | founder 2026-11-04: NO safe word by default (see 8); the code stays, optional per family |
| `FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED` / `_AUTHORITY_DRY_RUN` / `_AUTHORITY_COUNTDOWN_S` | false / true / 60 | the emergency desk's authority module (section 14); even when on it only LOGS the script (no live adapter) |
| `FRIDAY_ROBIN_MISSED_RING_MINUTES` / `_MISSED_RING_MAX` | 3 / 6 | urgent missed call: ring again every N minutes, at most this many tries |
| `FRIDAY_ROBIN_SCREEN_UNKNOWN_ENABLED` | false | stub only (section 9) |
| `FRIDAY_ROBIN_LISTEN_IN_ENABLED` | false | stub only (section 9) |
| `FRIDAY_ROBIN_CHECKIN_RETRIES` / `_RETRY_MINUTES` | 2 / 20 | retries after the first try (hard max 2), spacing |
| `FRIDAY_ROBIN_REFILL_DAYS` | 5 | refill alert to the child N days before stock ends (also at 2 days) |
| `FRIDAY_ROBIN_CALL_AUDIO_RETENTION_DAYS` | 0 | listening cues only; nothing kept by default |
| `FRIDAY_ROBIN_AUDIT_RETENTION_DAYS` / `_TICK_S` | 30 / 30 | audit rows are deleted after this; scheduler poll |
| `FRIDAY_ROBIN_INCIDENT_RETENTION_DAYS` | 90 | closed/exhausted incident records are deleted after this (proposed default; an open incident is never deleted) |

Per family (admin chat): check-in time, quiet hours (default 22:00 to 07:00), sensitivity Calm/Balanced/Careful, refill days, `good_morning`, `festival_graphics`
(both default off), safe-word on/off, guardian basis.

## 2. Roles and the family model
Founder roles: **ADMIN** = the paying child (`Role.CHILD`), optional **CO_ADMIN** siblings, **USER** = the parent (`Role.PARENT`), **CONTACT** = second contact
(`Role.SECOND_CONTACT`, receives alerts only, and only if named in advance). The admin configures everything Robin DOES (times, quiet hours, medicine lists,
thresholds, sensitivity, who is alerted, plan/billing, safe-word on/off). Tables: `robin_families`, `robin_members` (phone hashed with the same keyed `NumberHasher`
as the CallGate AND encrypted inside the JSON), `robin_consents`, `robin_records` (medicines, doses, check-ins, incidents, audit, outbox; one generic table by
`kind`, encrypted JSON). `user_id` (the child) is the erasure key; `DataPurger.purge_user` deletes all four; `FamilyService.erase` ("delete everything for my
parent", DELETE confirmed) deletes one family. Pause/resume: the PARENT can pause Robin at any time (voice note "Robin, band karo", text, widget stop, or on a call);
the family becomes PAUSED, nothing rings or nudges, and the child is told "your parent asked to stop, please talk to them".

## 3. Consent model (FOUNDER FINAL, 2026-11-04) and the LEGAL-REVIEW FLAG
ALL consent is given by the CHILD (admin) on the parent's behalf, because elderly parents cannot manage technical consent. Each item
(`daily_checkin_calls`, `medicine_reminders`, `scam_check`, `device_signals`, `payment_alerts`, `location`, `call_listening`, `authority_calls`, `share_summary_with_child`) is stored per parent
with `given_at`, `source` (`admin_chat`, `voice_yes`, `app_tap`, `guardian`), `given_by` = **`admin_on_behalf`** (default) or `user` (the parent said yes themselves; this replaces the
admin basis), and `withdrawn_at`. The audit log records who/how/when ("the admin, on their behalf ... Legal-review flag" for sensitive items).
* The parent is **NOTIFIED, not asked**: on setup Robin sends a WhatsApp voice note + text in the parent's language (says it is an AI assistant called `{brand}`, who set it up, what
  it does, that it does not read their chats or record their phone, how to stop: `notify.*`, `intro.*`), and an optional introduction call (`IntroService`, same script; with `ask=True`
  it also asks for the parent's own yes). **No call to the parent before that notification** (`Ctx.call` refuses `parent_not_notified`) and none without the matching consent item.
* A parent "stop" immediately pauses everything (including sensitive items). **Only the PARENT can resume**; the admin can only request (`admin_consent` returns `parent_paused`).
* Monthly reminder of what is on (voice note via the channel, else the outbox).
* **GUARDIAN flag** (adult parent with a lawful guardian): the admin records a documented basis (`guardian mode <reason>`); nothing is verified in Phase 1.
* **LEGAL REVIEW NEEDED (not a legal opinion):** DPDP has no verified route for a child consenting on behalf of a non-disabled adult parent; Google Play's notification-access and call
  related declarations expect the device owner's own consent. The design therefore (a) records the basis honestly, (b) notifies the parent, (c) lets the parent stop at any time, (d) keeps
  sensitive items individually switchable and visible ("what is on" view). Counsel must confirm before any real family is onboarded.

## 4. Onboarding by chat (child)
"set up Robin for my father" (also "papa ke liye robin set up karo") asks in order: parent mobile number, language (Hindi/Hinglish/English), check-in time, quiet hours, second contact
(optional; only someone named now is ever contacted), sensitivity, may Robin ring you. It then records the admin consents for the four non-sensitive items, notifies the parent, and attempts
the introduction call. The call respects the CallGate/pilot allow-list (`RobinGate`): in the pilot the parent's number must be explicitly in `FRIDAY_PILOT_ALLOWED_NUMBERS`, otherwise the child is told and nothing rings.
Sensitive items: `enable device signals | payment alerts | location | call listening` (a separate explicit command).

## 5. Daily check-in (`checkin.py`)
Scheduler (`RobinHub.tick`, loop `friday-robin`): at the parent's time (parent timezone, default Asia/Kolkata) one call per day with: greeting (AI), ate, slept, pain, mood word, strange call or money
request, medicines taken (if medicines exist), on Sundays "how many pills are left?" per medicine (max 2). Answers are read by plain rules (`answers.py`: yes/no, number, mood word, stop; unclear is never treated as consent or as all-well).
Result: a structured record + one line to the child ("Papa checked in: ate: yes, ..."); without the parent's `share_summary_with_child` consent the child gets only "picked up the call". Daily digest at 20:00 and
weekly on Sundays (also on demand: "digest"). Unanswered: retry after 20 minutes, max 2 retries; then the ladder (section 7): WhatsApp the child, ring the child 5 minutes later, then the named second contact. A later answer from the
parent closes the ladder and tells the child "Papa is fine". Quiet hours and the care protocol defer the call (not a try); after 3 hours it is skipped.
Reuse of `friday/urgent`: its `RingResult`-style outcomes, `GateResult`, the CAS pattern (a step is persisted as `started` BEFORE the dial so a crash never dials twice). It is not used directly: its lines hard-code "Friday"
and it is keyed to receptionist messages and the user's own number.

## 6. Medicine (`medicine.py`)
Schedule by chat (`add medicine Amlodipine 5mg at 8am, 8pm strips 2 of 10 bought 2026-11-01`) or by prescription photo (`RobinHub.on_document_confirmed`: lines such as "Metformin 500 mg 1-0-1" become a PROPOSAL; the child must answer yes before anything is saved).
**docunderstand has no `prescription` DocType yet** (its types are flight/train/hotel/passport/bill/generic): that gap is unverified and must be closed in `friday/docunderstand` by its owner. Reminders by call (grouped per time slot) with a retry after 20 minutes
(then `unreached`, which is reported as "could not reach", never as "missed"); `app_tap` capture via `record_dose`; the child can pause reminders ("pause reminders 3 days"). Stock estimate = strips x pills per strip minus doses/day x days since purchase, corrected
by the weekly count; refill alert to the child at N days (default 5) and at 2 days, once each per purchase cycle. **No medical advice**: the only advice anywhere is "ask the doctor"; a test scans every line.

## 7. Alerts, ceilings, ladder, SOS (`alerts.py`, `sos.py`)
**Contract for the device package (stable):** `from friday.robin.alerts import RobinAlert, raise_alert` then `await raise_alert(RobinAlert(parent_member_id, tier, scenario, why, money=False, dedupe_key=None, occurred_at=None, location=None, amount_text=None))` returns
`AlertResult(accepted, reason, incident_id, duplicate)` and never raises (`robin_off` when the switch is off). The `AlertPort` Protocol is the same for injection. Tiers INFO (digest only) / WATCH (app notification to the parent, max 2 an hour, note to the child) / HIGH / EMERGENCY.
Ceilings (family may lower, never raise): parent nudges 2 per hour; calls to the parent at most 3 per incident, 5 minutes apart (same for the child and the second contact); quiet hours 22:00-07:00 except EMERGENCY and HIGH-with-money; at most 3 escalation calls per person per day;
second contact only if named in advance; every alert states why in one line; stop on "Mark safe", "I have it", or the parent saying they are fine (money is never an all-clear: the child is told to check anyway); Robin never blocks a number, messages a bank or third party, or dials 112.
Sensitivity (Calm/Balanced/Careful) changes thresholds (Calm turns WATCH into a digest note, Careful lifts INFO to WATCH), not what is read. Care gate: `care.is_active(user_id)` is imported defensively from `friday.guardrails.care` or `friday.care`
(absent = inactive; sync or async); while active, check-ins, medicine reminders, digests and WATCH nudges are skipped; HIGH and EMERGENCY still go (decision, flag if the care builder disagrees).
Child buttons (WhatsApp allows 3): [Call parent] [Robin joins call] [Mark safe]; "Show details" is the text command `details` (the alert says so). Call parent = shows the number (Robin does not dial it for the child); Robin joins = rings the child and adds the parent to the same call (`bridge`, **unverified on a real provider**).
Ladder per scenario is `plan_for`. Persistence/restart safety: incidents are records with a status CAS (`open` -> `running`); a replica that died mid-step is recovered after 120 s and never re-dials the same step.
**SOS** (`SosService.trigger`, called by the device API widget hold or by the parent phoning in): EMERGENCY, rings the child (repeat on the ladder), WhatsApps the child and the second contact (location only with the `location` consent), works even when the parent paused Robin, never dials the parent, returns `show_112=True` so the app shows one-tap "call 112".
The second contact is messaged through `Ctx.extra_senders["second"]` which has **no real adapter** (a business-initiated WhatsApp to a non-user needs an approved template; unverified).
"What Robin did today": `FamilyService.view`, `render_view` (the same page for child and parent), erasable, audit retention 30 days.

## 8. Safe word (optional, OFF)
Founder decision: no family safe word as the defence against voice-clone scams; Robin judges the call's PATTERN (urgency ramp, secrecy, money ask), see 9. The code remains (`set_safe_word`, keyed hash `robin_safeword:<family>`, never stored in plain, `check_safe_word`),
works only when `FRIDAY_ROBIN_SAFE_WORD_ENABLED` and the family's `safe_word_enabled` are on, is not in the default help or onboarding, and the S4 nudge uses it only when a word exists.

## 9. Screen-unknown-callers and listen-in (DESIGN + STUB, `screening.py`; switches off; nothing dials or listens)
* **Screen-first:** the parent forwards unknown/unsaved callers to Robin's line (carrier conditional forwarding, like friday/receptionist). Robin answers ("I am an AI assistant answering for Papa; who is calling and why?"), streams the transcript (text only) to a
  `CallPatternAnalyzer` (Protocol, implemented in `friday/robindevice` by another builder; `FakeAnalyzer` here) and **bridges to the parent only if the verdict is FINE**; otherwise it declines politely and tells the child why. Forwarded caller ID ("redirecting number") is unverified with Vobiz.
* **Listen-in:** the parent adds Robin to a live 3-way call (needs the `call_listening` consent). Robin's first words are an audible disclosure (`listen.disclose`), it listens, and whispers `listen.warn` to the parent only. Not recording; `FRIDAY_ROBIN_CALL_AUDIO_RETENTION_DAYS=0` means only verdict cues are kept.
* Call audio rule: listening happens only on calls routed through Robin's own line, with an audible disclosure at the start; recording is not built.

## 10. WhatsApp-first parent channel, widget, templates (T07: adapter + fakes built; real Meta send BLOCKED, never exercised)
The parent's primary channel is WhatsApp, voice-note first; the parent never types and never sees the generic Friday menu. Code: `friday/robin/channel.py`.

**Outbound.** `WhatsAppParentChannel` implements `ports.ParentChannel` over `channels/whatsapp.py` (`send`, `upload_media`, `send_audio`) and the existing voice stack
(`TTSProvider.synthesize` in the parent's language -> `chatbot_media.convert` Ogg/Opus). Inside the 24 h window: voice note first, then the same words as text. Outside it
(or when Meta answers 131047): the pre-approved TEMPLATE `robin_parent_message_v1` carries the line (a voice note cannot open a conversation); a voice note + text of one line send ONE
template. Every method returns False on failure and never raises; the callers (intro, missed call, greetings) leave the line in the app outbox (`pending` record), which the T08 drain retries.
The window marker (`WindowTracker`, shared cache keyed by the blind index of the phone) is set by the inbound route; with an in-process cache a restart reads as "closed" and the template is used (always valid).
`ports.FakeParentChannel` has the same behaviour (`window_open`, `fail`) and `channel.FakeWhatsApp` stands in for the Cloud channel in tests.

**Inbound.** `InboundPipeline._handle` has ONE early hook (after the provider-retry check, before transcription and user resolution): `RobinHub.parent_inbound(msg)` -> `channel.ParentInbound.handle`.
If the sender's phone belongs to a Robin PARENT member the message is consumed there; any other number (including the child's) continues down the old path unchanged.
Voice note -> fetch media -> STT (language hint from the parent) -> the audio is dropped (never written to disk or the database, never logged; the provider copy is deleted best-effort with `delete_media`) -> `RobinHub.parent_said(phone, text, via="voice")`
(stop / start / help = SOS / threat / "I am fine"; any word ends an "unanswered" ladder). A control word typed as text (stop, help, I am fine) is treated the same, because stopping must always work.
Other text, links, forwarded messages, screenshots, documents -> `ScamIntake` = **T13 STUB** (`UnbuiltScamIntake`: analyses and stores nothing; the parent gets the short `inbound.hello` line). Nothing from a parent reaches the general assistant.
Unreadable audio gets the same hello (never silence). With no channel configured the reply waits in the outbox.
**Care protocol:** `RobinHub.parent_said` screens the parent's words with `friday.care.detect.assess` (after "stop", before the other branches): HIGH -> the care protocol's own line in the parent's language (voice + text);
the family is told only if the parent's `share_summary_with_child` consent is on (the `authority.distress` chat line, no words in it, any hour); the words are never stored or logged.

**WhatsApp templates to submit to Meta (all wording PENDING founder approval; none submitted; `{brand}` is filled from `FRIDAY_BRAND_NAME` at submission; category UTILITY; languages en and hi):**

| Name | Parameters (in order) | Body (PENDING) | When |
|---|---|---|---|
| `robin_parent_message_v1` | `{{1}}` the line to say, in the parent's language | `{brand}: {{1}}` | any parent line while the 24 h window is closed (voice note cannot open it) |
| `robin_parent_reopen_v1` | `{{1}}` how the family calls the parent, `{{2}}` the child's name | `{brand} is the assistant {{2}} set up for {{1}}. Send any voice note or say hello so {brand} can reply.` | T08 outbox drain, to reopen the window before queued lines follow |

Meta may refuse a body that is only a variable; if it does, the wording of `robin_parent_message_v1` gets a fixed sentence around `{{1}}` (founder to approve). Still design-only for the child side (outside the window): `robin_alert_child`, `robin_checkin_missed_child` (Notifier templates).
Meta's token is blocked; the web chat is the working channel for the child meanwhile. Opt-in: the child saves Robin's number on the parent's phone and the parent (or the child) sends "Hi" once, which opens the window.
**Widget hooks** (thin Android widget: press-to-talk mic and SOS press-and-hold): `RobinHub.widget_voice(parent_member_id, transcript)` and `RobinHub.widget_sos(parent_member_id, location)` (the `WidgetHooks` Protocol). The voice upload endpoint can reuse the device API of `friday/robindevice` later; STT happens before `widget_voice`.
`FamilyService.take_app_notifications` is the outbox the app polls (nudges, monthly reminder, good morning when no channel).

## 11. Good morning and festival graphics (`greetings.py`, `data/festivals.json`)
Per family `good_morning` / `festival_graphics` (off). Daily after `good_morning_time` (07:30, outside quiet hours, not paused, not during the care protocol): greeting + date + today's medicine times (+ festival greeting). Festival calendar is a data file with regional tags; **a festival is sent only when its date is marked `verified`**
(the lunar dates in the file are from the builder's memory and unverified: a human must check them against an authoritative calendar). Graphics are original SVG (gradient + geometric petals + text, no scraped or religious imagery); PNG needs an optional converter (`cairosvg`, not a dependency) and a Devanagari font: unverified.
Sent via `ParentChannel.send_template(..., media)`; the parent can forward it to family groups. All wording PENDING.

## 12. Data policy
Phones: keyed hash for lookup + AES-GCM encrypted in JSON (never logged; `mask_phone`). Check-in answers, medicine names, audit text: encrypted JSON. No call audio, no transcripts, no message text is stored; listening mode keeps verdict cues only. Location only in an SOS and only with consent.
`user_id` is the erasure key; both sides can see the audit; the parent sees the same "what is on" page.

## 13. Unverified / not built
Real calls, TTS audio, WhatsApp delivery (child, parent, second contact), the bridge ("Robin joins call") on Vobiz, forwarded-caller ID, the `prescription` DocType, PNG rendering and Devanagari fonts, festival dates, the second-contact message adapter, the Android widget, the device API transport, the `CallPatternAnalyzer`,
the care protocol module (absent today), Postgres (SQLite only in tests), the inbound voice front door hook for a parent phoning the Robin number (`parent_said(..., via="call")` and `SosService.call_steps` are the functions to call), co-admin chat commands (a co-admin only receives alerts), legal basis of admin-on-behalf consent.

## 14. Missed calls and the AI emergency desk (AI only; no human console)
**Missed calls, either direction (`missedcall.py`, entry `RobinHub.on_missed_call(missed_phone, caller_phone, answers)`).** Robin answers the forwarded call (the leg plays `MissedCallService.steps_for`: who is calling and why, is it urgent) and the MISSED person gets a WhatsApp
message with who called, when and what they said (the child as chat text; the parent as text + a voice note in their language, else the app outbox). If the caller says it is urgent / an emergency, or a strong danger word is in what they said, the message carries the call context and Robin
keeps RINGING the missed person ("tell them it is an emergency", `missed.emergency_ring`): every 3 minutes, at most 6 tries, stop on pickup, on "Mark safe"/"I have it", or on "I am fine"; quiet hours do not apply. Wiring of the receptionist's forwarded-call leg into `on_missed_call` is NOT done (unverified:
forwarded caller ID with Vobiz).
**Emergency desk triggers:** SOS press-and-hold, the parent saying they are being threatened (`answers.THREAT`, scenario `threat`), danger words in an urgent missed call, or the ladder failing for a medical/fraud HIGH (the HIGH plan ends with an `authority` step). The desk first does what SOS already did: rings the child and the second contact
and WhatsApps them (section 7). Then, and only then, it considers the authority module:

**`authority.py` (switch `FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED`, default OFF, and DRY-RUN by default: it only logs the script it would speak).** There is no live adapter. 112 and 1930 are in `calls/numbers.EMERGENCY_NUMBERS`, so the CallGate refuses them; a live path needs a reviewed gate change, a real adapter, legal clearance and the
founder's explicit approval. Preconditions, each audited when it refuses: (1) switch on and the parent has not paused Robin; (2) consent item `authority_calls` recorded by the admin (`enable authority calls`); (3) a confirmed EMERGENCY: two independent signals (`RobinAlert.signals`, `sos_button`, `parent_said_threat`, `ladder_failed` = the child was rung and did not pick up,
`child_confirmed` via "confirm emergency") or the parent said yes (`confirm_emergency(..., "parent")`); (4) category: PHYSICAL (sos, threat, medical, fall) -> 112 script; FRAUD -> never 112: only a conference/bridge of the child to 1930 (Robin does not speak alone) when money is involved, plus a cybercrime.gov.in complaint DRAFT to the child
(sent even with the switch off, it is text, and says Robin filed nothing); DISTRESS -> never a call, handed to the care protocol (not built) and the child is told; (5) the parent's name and address from the profile (`parent name ...`, `address ...` by the admin), a fixed calm script (what, where, who, callback = the child's number), see `authority.script_112`;
(6) a 60-second "I am fine" cancel window with a spoken countdown (`authority.countdown`), skipped only when the parent does not answer; "I am fine", "cancel", "Mark safe" or "I have it" cancel it; (7) a hard cap of one authority call per incident and an audit record. Tests (`tests/robin/test_desk_missed.py`) check every refusal, the cap, that fraud never reaches 112 and that no authority number is ever passed to the dialler.
Unverified: whether an automated call to 112/1930 is lawful or accepted (legal review needed before any live adapter), forwarding/conference to 1930, and the wording of every `authority.*`, `missed.*` line (PENDING).


## T03: consent, erase, SOS, retention (2026-11-06)
- **Owner of consent and erase is the child (admin).** `FamilyService.erase` and `DataPurger.purge_user` also erase the device package's rows (`robin_device_states`, `robin_device_codes`, keyed by the parent's member id) and, through the hook registry in `robin/ports.py` (`register_erase_hook`, no import cycle), `DeviceService.erase_parent` drops the token cache and live analyzers. The device token is rejected afterwards (the device API answers a plain 404 to any bad token). A family erase is audited in the core audit log (counts only).
- **SOS always works.** Before the family is ACTIVE (setup unfinished, no consent, no `call_ok`) an SOS still messages and rings the child (up to 3 rings); no second contact and no authority step in that minimal plan. With no child contact it logs an error and answers `no_child_contact`. Every other scenario is still `family_not_active`.
- **Consent audit:** every grant, withdrawal, pause, resume (and refused resume) carries `actor` (`admin_on_behalf` / `user` / `guardian`), `source` and `at`. Only the parent resumes after a parent pause (`FamilyService.resume(..., actor=)` refuses any other actor); the admin's consent never un-pauses a parent who stopped during setup.
- **Retention (scheduler, `RobinHub.tick`):** audit 30 d, closed incidents 90 d, device events 7 d (the engine also trims to 48 h), call-pattern cues `call_text_retain_days` (1 day when 0).
- Guards: `tests/security/test_robin_at_rest.py` (every Robin column encrypted or allow-listed), `tests/security/test_no_secrets_in_repo.py` (+ `secrets_allowlist.txt`).

## T05: observability without PII (2026-11-07)
- `friday doctor --section robin` (section 13): Robin and device switches, authority lock (`FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false` is a FAILURE; calls on with dry-run is a warning), listen-in, spoken-lines status (PENDING/APPROVED), migrations 0019/0020 present, care component present, scheduler last tick (the scheduler writes one number to `var/robin/last_tick`, override `FRIDAY_ROBIN_TICK_FILE`), parent channel (WhatsApp configured or messages wait in the outbox).
- `GET /ops-status/<token>/robin.json` (and `/robin` as `key=value` lines): wrong token is 404. Only integers and the status word `ok`/`off`: families by status, active incidents, alerts by tier (24 h), `sos_24h`, `falls_24h`, check-ins done/unanswered (24 h), devices paired, heartbeats missed (S7 open), outbox pending, `errors` (since process start), `last_tick_age_s` (-1 = none). Never ids, names, numbers, times or text; `tests/robin/test_opsstatus_counts.py` walks the response and rejects any string longer than a status word or a 10+ digit run.
- Counters: `friday/robin/opscounts.py::bump` (fixed names only) counts in process and logs one line `metric robin.<name> +n` through the logging layer.
- `deploy/enable-robin.sh [off]`: sets only `FRIDAY_ROBIN_ENABLED` and `FRIDAY_ROBIN_DEVICE_ENABLED`; refuses (exit 3, no change) if authority dry-run is false, or authority calls / listen-in are already on. `enable-web-test.sh` no longer resets those two switches (KEPT list); safe-word, screen-unknown and listen-in stay in its ALWAYS_OFF.
