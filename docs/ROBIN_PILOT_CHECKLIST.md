# Robin pilot checklist (for the founder)

Written 2026-11-10 for a non-technical reader. Everything here was **tested with fakes only**: no real call, no real WhatsApp message, no real phone
has been used by the engineering work. So every sentence that says "this works on a real phone / SIM / carrier / store" is **[U] = not verified** until you
do the step below and write the result in the go/no-go table (section 18).

How to read it: the steps are in the order to do them. A step has **Who** (you, a lawyer, engineering, a pilot family), **Do**, and **Done when**.
Commands are for the server (log in as root; the app lives in `/opt/friday`). Where it says "run on the server" copy the line exactly.
Nothing below ever turns on the 112/1930 automatic calling or listening-in to calls: those stay OFF, and the scripts refuse if they are not.

Plain-English map of the three things Robin does in the first release (Founder: "first Play ship = thin widget + WhatsApp, protection pack later"):
the phone widget with the big mic and SOS button, WhatsApp messages and voice notes to the parent and the child, and phone calls (daily check-in,
alerts). The human concierge and the human emergency desk come with their own steps (8.6 and the gaps in section 19) and are optional for the first families.

---

## 0. The order at a glance

1. Decide the people and numbers (step 1): who staffs, which numbers, grievance officer. Nothing else can finish without these.
2. Unblock the outside accounts (steps 2-5): Meta WhatsApp, Vobiz, Google Play, the real domain.
3. Hear and approve the words (step 6).
4. Legal review (step 7), in parallel with 2-6.
5. Switch things on, one at a time, on the server (step 8) and check each (step 9).
6. Test with your own phone and your own family only: live call (section 10), forwarding (11), parent notice and STOP (12), SOS drill (13), kill-switch drill (14), delete-everything demo (15). Cost (16) and rollback (17) are read before you start.
7. Go / no-go (section 18) for 4-5 families, then widen to 20.

---

## 1. Decide: people, numbers, officer  (Who: you)

| # | Decision | Why it is needed | Where it ends up |
|---|---|---|---|
| 1.1 | **Grievance officer**: name and email | the law and the Play listing need one | server settings `FRIDAY_GRIEVANCE_NAME`, `FRIDAY_GRIEVANCE_EMAIL` (step 8) |
| 1.2 | **Support line**: ONE WhatsApp number AND ONE phone line (your decision 2026-11-10: both) | families need a place to ask, complain and ask for deletion | `FRIDAY_SUPPORT_INBOX` (where support mail/notes land) and `FRIDAY_ROBIN_WAITLIST_CONTACT` (the text shown on the privacy page, e.g. "WhatsApp DELETE to <number>") |
| 1.3 | **Who answers the support WhatsApp and phone**, in which hours | an unanswered support line is worse than none | your list; say the hours on the page. Engineering has NOT built a ticket system or a phone-line product: it is a person with a phone [U] |
| 1.4 | **Who staffs the human concierge** (errands) and **the human emergency desk**, and in which hours | your decision: staff grows with sign-ups; the desk also has humans | `docs/ROBIN_CONCIERGE_DESK.md` section 2 and the staffing ratios there (all numbers invented). For the first 4-5 families you can run both with yourself plus one or two trusted people [U: your call] |
| 1.5 | **Staff non-disclosure agreement (NDA)** and a short written rule sheet: never pay, never ask for an OTP/PIN/password, never share a family's details | staff will see family situations | lawyer drafts (step 7); every staff member signs before getting a login |
| 1.6 | **Pilot families**: 4-5 first (yours first), up to 20 later | each needs an in-person phone set-up | a list kept by you, not in the repository (names and numbers never go into git) |
| 1.7 | **Money limit for the pilot**: how much per day you accept (see section 16) | speech, voice and AI services cost money | `docs` budget notes; set the same limits in each provider's own dashboard |

---

## 2. Meta WhatsApp: token and templates  (Who: you; engineering helps)

Without this there is no WhatsApp to the parent or the child, no voice notes, no buttons on alerts. The server can fall back to SMS and web chat for the child [U: SMS path never run for real].

1. Resolve the blocked Meta onboarding: follow `docs/META_UNBLOCK_PLAN.md` (ask Meta, or use a provider that hosts the WhatsApp number). **Done when**: you have a phone number id and a token that can send a test message to your own number.
2. Put the three WhatsApp values on the server using the existing helper (never paste them into chat or git): run on the server `bash /opt/friday/deploy/set-whatsapp.sh` and follow its questions. The names are `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`.
3. **Submit the two Robin message templates** for Meta approval (they are the only way to message a parent whose 24-hour window is closed):
   - `robin_parent_message` (one variable: the line, already in the parent's language) and `robin_parent_reopen` (two variables: how the family calls the parent, the child's name).
   - Wording is in `friday/robin/channel.py` and `friday/core/templates.py`; the wording is PENDING your approval (step 6) and Meta's approval takes time [U: days].
4. **Done when**: `friday doctor --section robin` no longer lists `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` in the "pilot readiness" line, and a test message reaches your own phone.

---

## 3. Vobiz: the number and the call line  (Who: you)

1. Robin's line (the number the carrier forwards missed calls to, and that parents see when Robin calls): get it in Vobiz, top up the balance, and **ask Vobiz in writing** whether they support (a) forwarded-call information (which number was dialled originally), (b) joining a call to two phones (bridge), (c) listening/streaming (only needed later). Engineering wrote the code from the Vobiz documents and **never ran it on a real call [U]**.
2. Only numbers on your allow-list can be dialled during the pilot: `FRIDAY_PILOT_ALLOWED_NUMBERS` must contain your own number first, then each pilot family's numbers after they agreed. Add them on the server with `bash /opt/friday/deploy/setenv.sh FRIDAY_PILOT_ALLOWED_NUMBERS <numbers separated by commas>` (the list format is the one the setting uses [U]) and never put them in git.
3. **Done when**: the "pilot readiness" line no longer names `FRIDAY_MODE=live` or `FRIDAY_PILOT_ALLOWED_NUMBERS`.

---

## 4. Google Play and the test phone  (Who: you)

1. Create the Google Play Console account and pay the fee (one time).
2. Get **one test Android phone** (a real, cheap, recent one; the parents' phones are often older [U]).
3. Choose the **app id** (the permanent name of the app on Play; it can never be changed once published) and the **server address** the app talks to (must be `https`). The code has a placeholder app id and a placeholder server address.
4. Ask engineering to build the app with your values: on a computer with the project: `ROBIN_APPLICATION_ID=<your app id> ROBIN_BASE_URL=https://<your domain> scripts/build-android.sh`. This gives a test file (`app-debug.apk`). **Nothing visual was ever checked on a real phone [U]**: installing, the widget, the big mic, the SOS hold, the mic permission, speaking the answer aloud in Hindi.
5. Upload the app to a **closed test** on Play (not public), declarations: microphone, and for the later floating mic: "draw over other apps", foreground service with the special-use reason. **The floating mic bubble is built (T22) but its release timing is your decision**; Play review of the "draw over other apps" and foreground-service declarations is hard and can reject [U]. Lead's proposal: ship the thin widget + SOS first, the bubble as version 1.1.
6. **Done when**: the app installs on the test phone from Play (or the file) and a child can pair it (section 10, the live test).

---

## 5. Real domain  (Who: you)

Buy the domain, point it at the server, switch the web address setting to it (`FRIDAY_PUBLIC_BASE_URL=https://<domain>`), keep https on. It is needed for the Meta callbacks, the privacy policy page, the app's server address, and the public waitlist page (`bash /opt/friday/deploy/enable-robin-waitlist.sh`). **Done when**: the page `/robin` opens on the domain over https and the "pilot readiness" line no longer names `FRIDAY_PUBLIC_BASE_URL`.

---

## 6. Approve every PENDING line and hear the audio  (Who: you; the lead sends samples)

Rule 3 of the project: **hear before change**. No audio has been generated yet [U]. The real phone dial refuses to ring a parent while the lines are PENDING (except your own allow-listed number in the QA call, step 10). All lines are in `docs/ROBIN_LINES.md` (560 rows = **237 line ids**; spoken lines in English, Roman Hindi (Hinglish) and Devanagari Hindi; chat lines in English and Hinglish). Review them in the batches below, **in this order** (what the parent hears first matters most).

How: the lead sends audio samples per batch -> you listen -> you tell the lead "approve" or "change" per id -> a reviewed commit flips the status. (For lines you hear on your own QA call: `friday qa report` lists the ids you heard, and `friday qa line <id> approve|reject` records your decision.) Nothing flips by itself.

| Batch | Feature | Count (ids) | Ids (after `robin.`) |
|---|---|---|---|
| B1 | First call to the parent: who I am, AI disclosure, consent, notice | 22 | `intro.` greet, will, wont, no, ask.daily_checkin_calls, ask.medicine_reminders, ask.scam_check, ask.share_summary_with_child, thanks, declined, not_now, result.consented, result.declined, result.no_answer, result.refused; `notify.` stop, set_up_by; `consent.` withdrawn, given, request_sent, parent_paused, admin_given |
| B2 | Pause, resume, delete | 5 | `pause.` ack, parent; `resume.` ack, parent; `delete.ack` |
| B3 | Daily check-in call and what the child hears | 33 | `checkin.` greet, q.ate, q.slept, q.pain, q.mood, q.strange, q.meds, pain_ack, strange_ack, bye, result.ok, result.concern, result.missed, result.fine_later; `sum.` yes, no, unclear, ate, slept, pain, mood, strange, meds, answered_only; `digest.` daily, weekly, empty; `dg.` checkins, concerns, meds, alerts; `call.repeat`; `monthly.reminder` |
| B4 | Alerts, SOS, scam nudges, widget | 41 | `sos.` parent, ask, noted, child, loc, second; `alert.` head.watch, head.high, head.emergency, money_note, hint, details, safe, taken, parent_fine, call_parent, join_started, join_refused, unknown, followup, flood_summary, second; `nudge.` generic, remote_access, money, safe_word, fine_ack, not_fine_ack; `child.` ring, ring_sos, ring_unreached; `second.ring`; `bridge.` child, parent; `callnow.` started, refused; `widget.` sos, sos_failed, unclear; `inbound.` hello, unclear |
| B5 | Medicine reminders and refills | 23 | `med.` remind, thanks, later, count_ask, count_thanks, added, confirm, confirm_saved, confirm_dropped, rx_unreadable, rx_partial, rx_nothing_open, ordered_ack, format, list_item, list_empty, removed, not_found, missed, refill, paused, resumed, consent_missing |
| B6 | Scam check by WhatsApp forward (and the safe word, which is OFF) | 17 | `scam.` high, risky, unsure, nosigns, unreadable, repeat, no_consent, child_high, child_repeat, child_no_consent, child_playbook; `safeword.` prompt, set, format, none, check_ok, check_no |
| B7 | Missed-call messages and "X has been told" | 13 | `missed.` ask_who, ask_urgent, urgent_ack, normal_ack, msg, msg_urgent, emergency_ring, caller_told, caller_told_urgent, child_note, child_note_urgent, unknown_caller, no_summary |
| B8 | The child's set-up chat (the child reads these; lower risk) | 54 | `setup.` start, bad_number, same_number, ask_language, ask_time, bad_time, time_in_quiet, ask_quiet, bad_quiet, ask_second, ask_sensitivity, bad_sensitivity, ask_child_call, done, not_allowed, intro_started, intro_pending_line, no_family, cancelled; `enable.` done, unknown; `pair.` steps, off, not_ready; `guardian.` set, bad_basis, off; `coadmin.added`; `forward.` ask, codes, unknown_carrier, unavailable, test; `status.` line, waiting_consent, active, paused; `view.` child.head, item.on, item.off, item.withdrawn, never, shared, audit_head, audit_empty; `cmd.` checkin_set, sensitivity_set, delete_ask, delete_done, delete_cancelled, help, care_active, escalation_unnamed; `inbox.head` |
| B9 | Emergency desk wording (stays dry-run; approve the wording, not the live calls) | 13 | `authority.` countdown, what.medical, what.threat, what.unknown, script_112, bridge_1930, complaint, dry_run, refused, distress, countdown_child, set_address, set_name |
| B10 | Only for later (switches stay OFF in the pilot; no need to approve now) | 16 | `screen.` ask, connect, decline, child_note; `listen.` disclose, warn, left, child_note; `gm.` greet, meds, share, on, off; `fest.` greeting, on, off |
| | **Total** | **237** | (B1 22 + B2 5 + B3 33 + B4 41 + B5 23 + B6 17 + B7 13 + B8 54 + B9 13 + B10 16 = 237) |

Also PENDING and **outside** `ROBIN_LINES.md` (approve at the same time):

- **31 care-protocol lines** (distress, helpline offers) in `friday/care/copy.py`, English / Hinglish / Hindi. A clinical or counsellor review is also needed [U]; the helpline numbers in them are unverified.
- **2 WhatsApp templates** (step 2).
- **The app's own texts** (English plus Hindi placeholders) in the Android project; see `docs/ROBIN_ANDROID_APP.md`.
- **The voice**: confirm the female voice and the pace for elderly listeners; Hindi pronunciation of names must be heard (rule 3).

**Done when**: the lead has flipped the status for the batches B1-B9 (B10 may stay pending) in a reviewed commit, and `friday doctor --section robin` no longer says "spoken lines still PENDING".

---

## 7. Legal review  (Who: a lawyer; nothing here is legal advice)

Bring `docs/LEGAL_MAP.md`, `docs/CARE_PROTOCOL.md`, `docs/ROBIN_FAMILY_CORE.md` (consent sections), `docs/ROBIN_RESCUE_DESK_PILOT.md`, `docs/ROBIN_CONCIERGE_DESK.md`.

| # | Question for counsel | Why | If the answer is "no" |
|---|---|---|---|
| 7.1 | **Admin-on-behalf consent under the DPDP Act**: the *child* gives the consent for the parent's data (daily check-ins, medicine reminders, scam check, sharing a summary with the child); the parent is told and can stop at any time (soft approval). Is this valid? Is a guardian/other basis needed for a parent who cannot decide? | this is how every family is onboarded | the onboarding must change before any real family |
| 7.2 | **Automated 112 / 1930 calls**: the module exists but is **dry-run only** and cannot be switched live by the scripts. Is any automated call to emergency numbers or a cyber helpline allowed, under what consent? | until counsel agrees it stays dry-run; the human desk (section 13 and the gaps in section 19) tells the family to call 112 themselves | keep dry-run forever |
| 7.3 | **Call listening / two-party consent** (listen-in and screen-first, switches OFF): needs the disclosure wording to both sides; is it lawful in India and for the Play policy | these features cannot be turned on without this | keep OFF; the first release does not need them |
| 7.4 | **Concierge and desk staff**: NDA, background checks, data-protection duties, what they may see and do; no payments by staff | humans will see family information | no staff before this |
| 7.5 | Privacy policy, notice text, data retention (audit 30 days, closed incidents 90 days: proposed), delete-everything, children-of-the-user and elderly-person data | public pages and Play listing need it | blocks the public page and Play |
| 7.6 | Google Play policy for the permissions Robin asks for (microphone; later overlay and foreground service; notification access in the protection pack) | review risk | thin build only |
| 7.7 | Calling an elderly person with an AI voice: the disclosure line ("I am an AI assistant, not a person") and the do-not-disturb rules | the opening line of every call | change the lines (step 6) |

**Done when**: written answers are in the go/no-go table (section 18).

---

## 8. Switch things on, one at a time  (Who: you, on the server; engineering on the phone if stuck)

Every command below only writes harmless on/off settings (never keys), then restarts the service (a few seconds of pause). Each prints what it did. **They refuse to run, and change nothing, if the emergency authority calling is live or listen-in is on** (exit code 3). They never turn authority calling or listen-in on. **Do them in this order and run the check (step 9) after each.**

| Order | What it switches | Run on the server | Needs first |
|---|---|---|---|
| 8.1 | Settings (not switches): grievance and support | set each with `bash /opt/friday/deploy/setenv.sh NAME VALUE` (one at a time; it refuses anything that looks like a secret): `FRIDAY_GRIEVANCE_NAME`, `FRIDAY_GRIEVANCE_EMAIL`, `FRIDAY_SUPPORT_INBOX`, `FRIDAY_ROBIN_WAITLIST_CONTACT`, `FRIDAY_PUBLIC_BASE_URL`, `FRIDAY_MODE` (value `live`); keys (speech, AI) with `deploy/set-key.sh` / `deploy/enable-fast-voice.sh` | steps 1, 5 |
| 8.2 | The public waitlist page | `bash /opt/friday/deploy/enable-robin-waitlist.sh` (undo: add `off`) | 8.1 |
| 8.3 | **Robin core + the phone-app server** (`FRIDAY_ROBIN_ENABLED`, `FRIDAY_ROBIN_DEVICE_ENABLED`) | `bash /opt/friday/deploy/enable-robin.sh` (undo: `... enable-robin.sh off`) | the lines can stay PENDING: no parent phone rings until approved |
| 8.4 | Parent WhatsApp | `bash /opt/friday/deploy/enable-robin-channels.sh parent-whatsapp` (undo: add `off`) | step 2 done |
| 8.5 | Missed-call forwarding | `bash /opt/friday/deploy/enable-robin-channels.sh forwarded-calls` (undo: add `off`) | step 3, and the per-carrier test (step 11) |
| 8.6 | Human desk (optional for the first families) | `bash /opt/friday/deploy/enable-robin-channels.sh concierge` (undo: add `off`) | staff list, second-factor check, family lookup wired by engineering (**not built, see section 19**) |
| NEVER | Emergency authority calls, listen-in, screen-first unknown callers | not in any script; leave these settings off: `FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED`, `FRIDAY_ROBIN_LISTEN_IN_ENABLED`, `FRIDAY_ROBIN_SCREEN_UNKNOWN_ENABLED`; `FRIDAY_ROBIN_AUTHORITY_DRY_RUN` stays `true` | a lawyer's written yes (step 7) and your explicit decision |

The script `deploy/enable-web-test.sh` (the older web-test switch) never touches the Robin switches.

---

## 9. Check after every switch  (Who: you)

Run on the server: `friday doctor --section robin`

- Red **FAIL** lines mean stop and undo the last step. A FAIL on "authority is LIVE" means someone set `FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false`: set it back to `true` at once.
- The line **"pilot readiness"** lists, by name only (never a value), what is still missing: the switches that are off, the missing settings and keys, and "spoken lines still PENDING". When the line says "nothing missing for go-live", the server side is ready. It does **not** check the phone app, the carriers, the lawyers or the staff.
- Counts without personal data: `https://<domain>/ops-status/<token>/robin` and the weekly review page `.../review` (token = `FRIDAY_OPS_STATUS_TOKEN`).
- Scheduler: the doctor says "scheduler task running; last tick N s ago". If it says stopped, check `journalctl -u friday`.

---

## 10. Supervised live call (your own phone only)  (Who: you, with engineering watching)

This is the first real phone call Robin ever makes [U]. Only to **your** allow-listed number, with the approval phrase, a countdown and a cost cap.

1. Plan only (no call): `friday robin call-test --plan-only` -> it prints the check-in plan and dials nothing.
2. Real: follow `docs/QA_MANUAL.md` setup (`FRIDAY_QA_LIVE`, exactly ONE number in the allow-list, `sudo bash deploy/qa-https.sh` once, `sudo bash deploy/qa-live.sh` in a terminal that stays open), then run `friday robin call-test --language hinglish` and type the approval phrase when asked.
3. Pick up. Answer "haan", "theek hoon", say nothing once, say "madad" once (the help word must raise the child alert; use your own number as the "child" in a test family so no real person is alarmed).
4. Read the printed result: outcome, step timings, how sure the speech recognizer was, estimated cost. No words and no number are printed.
5. Hear: is it clear, slow enough, is Hindi pronounced right, can the elderly (ask a parent of yours to try it with you) understand it? Record **Hindi speech recognition quality on real elderly voices** — nobody has measured it [U].
6. `friday qa report` -> the ids you heard -> approve or reject per id.

**Done when**: one clean call, every step answered correctly, voicemail/no-answer behaviour seen (let it ring out once; a voicemail must never count as "reached"), and the cost line is within the budget (section 16).

---

## 11. Forwarding test per carrier  (Who: you; pilot parent's SIM later)

Missed-call messages work only if the parent's phone forwards unanswered calls to Robin's line. The set-up text per carrier is in the child's chat ("forwarding jio", "forwarding airtel", "forwarding vi"); **every code in it is general knowledge and unverified on a real SIM [U]**. Test each carrier you have a SIM for (Jio, Airtel, Vi), **with your own SIM and your own allow-listed number only**:

1. In the child's chat type `forwarding <carrier>`; set the codes on the test SIM; check the status code the text gives.
2. From a second phone ring the test SIM and **do not answer**. After the no-reply time (carrier setting [U]) Robin should answer, ask who is calling and whether it is urgent.
3. Say a name and "no": your WhatsApp gets the message within a minute. Repeat and say "yes": the urgent ring loop starts (the real dial only works on your number; lines pending use the QA override).
4. Note which Vobiz field carried the original number: run `friday receptionist probe` and write the answer in the table (engineering needs it) [U].
5. Undo the forwarding afterwards (the cancel code is in the same text: `##002#` is the general code [U]).

**Done when**: each carrier is marked pass/fail/not tested in section 18. A carrier that fails is **not offered** to families.

---

## 12. Parent notice delivered, STOP tested for real  (Who: you and one family member)

1. Set up Robin for your own family member as the child (chat: "set up Robin for my father" and follow it). The parent must receive the **notice** that the child enabled Robin, on WhatsApp (voice note first, then text), and the first call introduces Robin as an AI.
2. The parent says (voice note or text) "Robin, band karo" (or presses stop in the app, or says it on a call). **Done when**: Robin stops within a minute, the child is told once, and nothing more rings or messages until the **parent** resumes.
3. Try "I am being threatened" (text on the test family): must raise an emergency to the child. Try it while Robin is paused: it must still work.

---

## 13. SOS drill  (Who: you; authority stays dry-run)

1. On the test phone, hold the SOS button for 2 seconds (it needs the 2-second hold).
2. The child (you) must get a WhatsApp at once and then a call within about a minute; the second contact named at set-up is messaged. Press "Mark safe" in the child's chat: everything stops.
3. Repeat **with the child not answering**: the ladder goes on (child rings x3, second contact). The authority step must only **write a dry-run record** (no call to 112 or anyone). Check the weekly review page for "authority dry-run: 1" and no number was dialled.
4. Repeat at night: security alerts ignore quiet hours and calling hours by design.
5. If the human desk is on: the handoff card reaches the desk page (engineering wired this on 2026-11-10; tested with fakes only [U]); with nobody on the roster the log says "desk not staffed" and Robin goes on alone.
6. SOS before set-up was finished, and while Robin is paused, must still tell the child. Check both.

---

## 14. Kill-switch drill (pause)  (Who: you)

Two levels:

- **Everything, now** (founder switch): run on the server `sudo /opt/friday/deploy/dc.sh exec api friday robin pause-all`.
  It takes about a second, needs no restart, works in every container. While it is on: **no Robin call is placed** (not check-in, medicine, alert, SOS ring), no check-in/digest/reminder/greeting/monthly message starts, no phone-app sweep runs. Alerts that are already open can still **message** the child on WhatsApp. SOS from a phone still messages the child; the rings are refused [U: please confirm you accept this, section 20 question 1].
  Look: `... friday robin pause-all --status` (prints PAUSED/running). Undo: `... friday robin pause-all --resume`. Calls already in progress finish normally.
  It uses the same flag as the older `friday pause` (which also stops every other Friday call), so either command pauses Robin.
- **One family**: the parent says "band karo", or the child pauses that family in chat.

Drill: pause-all -> wait for a check-in time to pass -> confirm no call and no message -> `--resume` -> the next check-in happens. **Done when** you did it once yourself.

---

## 15. Delete-everything demo  (Who: you, with the test family)

1. In the child's chat: `delete everything for my parent`; Robin asks to confirm; answer DELETE.
2. Expected: the family, members, consents, records, the phone-app state (token and codes) and, if the desk is on, that parent's errands and handoffs are erased. The phone's old token must stop working. The audit keeps counts and ids only.
3. Show it to the next family on the first day: they own the delete button, not Robin.
4. Backups: a deleted family can still sit in last night's backup (nightly, 30 days kept in the bucket) [U: say this in the privacy policy; lawyer].

---

## 16. Per family, per day cost  (all numbers are estimates [U])

The code logs an estimated call cost at **Rs 5 per connected minute** ("generous: phone line + speech + AI turns") per family per day. Unanswered rings cost nothing in that estimate. WhatsApp messages cost per Meta's price list [U: check the current India rates], so ask your provider.

| Item | Assumption (invented) | Estimate per family per normal day |
|---|---|---|
| Daily check-in call | 2 connected minutes | Rs 10 |
| Medicine reminders by call | 1 call, 1 minute (or WhatsApp only) | Rs 0-5 |
| WhatsApp (digest to child, nudges, replies; mostly free inside the 24 h window; paid templates outside it) | 3-6 messages | Rs 1-5 [U] |
| Voice notes (speech to text and text to speech) | 2-4 short notes | Rs 1-4 [U] |
| Scam checks | 0-2 | Rs 0-2 |
| **Normal day** | | **about Rs 15-25** |
| Alert day (HIGH, a few rings) | +6-10 connected minutes | **up to about Rs 50-80** |

So 5 families is roughly Rs 75-125 per day, 20 families Rs 300-500 per day, plus staff time for the desk. After the first week read the real numbers: the doctor/ops counts and your Vobiz balance. Set a spend limit in every provider dashboard (Vobiz, speech, AI) **before** step 8.3.

---

## 17. Rollback  (Who: you)

In this order, stop at the first one that fixes it:

1. **Pause everything**: `sudo /opt/friday/deploy/dc.sh exec api friday robin pause-all` (section 14).
2. **Switch a feature off**: `bash /opt/friday/deploy/enable-robin-channels.sh <parent-whatsapp|forwarded-calls|concierge> off`.
3. **Switch Robin off**: `bash /opt/friday/deploy/enable-robin.sh off`. This also switches the phone-app server off (an SOS from a phone then reaches nobody; tell the families to call their child and 112 directly).
4. **Undo carrier forwarding** on each pilot phone (the cancel code in the child's forwarding text).
5. **Go back to the previous release**: `sudo ./deploy/update.sh --rollback` (previous image, database untouched; see `docs/DEPLOY_AWS.md`) [U: not exercised for Robin]. The Robin tables stay in the database (migrations 0019, 0020, 0021 are additive); rolling the code back with Robin switched off is safe.
6. **Restore the database** only if data is damaged: `deploy/restore.md` section B. Run drill A and C of that file once **before** the first family. `python -m friday.ops.backupcheck <sqlite file>` proves the same on a SQLite copy.
7. Tell the families in a plain message what happened and when Robin will be back.

---

## 18. Go / no-go table for 4-5 families

Fill the **status** column yourself: GO, NO-GO, or NOT TESTED. A single NO-GO on a line marked **(must)** means no go.

| # | Item | Who | Status |
|---|---|---|---|
| 1 | Grievance officer named and shown (must) | you | |
| 2 | Support WhatsApp number and phone line staffed with hours (must) | you | |
| 3 | Real domain with https, privacy page, `/robin` page (must) | you | |
| 4 | Meta WhatsApp token works; both templates approved (must for WhatsApp) | you / Meta | |
| 5 | Vobiz line, balance, written answers on forwarded-call info and bridge (must for calls) | you / Vobiz | |
| 6 | Play Console account, app id, server address, closed test installed on a real phone (must for the widget) | you | |
| 7 | Batches B1-B9 approved with audio heard; care lines (31) approved | you / lead | |
| 8 | Legal 7.1 admin-on-behalf consent: written yes (must) | lawyer | |
| 9 | Legal 7.2 automated 112/1930: stays dry-run (must stay) | lawyer | |
| 10 | Legal 7.3 listen-in / two-party consent: feature stays OFF unless a yes | lawyer | |
| 11 | Staff NDA and rule sheet signed by everyone with a login (must if the desk is on) | lawyer / you | |
| 12 | Who staffs concierge and emergency desk, hours written down (must if the desk is on) | you | |
| 13 | `friday doctor --section robin`: no FAIL; "pilot readiness" empty | you | |
| 14 | Backup drill A + C done once; backup job runs nightly | you | |
| 15 | Supervised live call done; Hindi speech quality heard on an elderly voice | you | |
| 16 | Forwarding tested: Jio / Airtel / Vi (each its own row) | you | |
| 17 | Parent notice delivered and STOP tested by a real parent | you / family | |
| 18 | SOS drill passed, authority record was dry-run only | you | |
| 19 | Kill-switch drill (`pause-all` then `--resume`) done (must) | you | |
| 20 | Delete-everything demo done (must) | you | |
| 21 | Daily cost estimate reviewed; spend limits set in provider dashboards (must) | you | |
| 22 | Pilot families chosen, each told in person and agreed; in-person phone set-up booked | you | |
| 23 | Rollback steps read once (section 17) | you | |
| 24 | Daily review routine: review page checked every day of the shadow week | you | |

Signed off by you with the date goes into `docs/HANDOFF.md`.

---

## 19. What engineering could NOT close (gaps)  [U]

These are known and open; each needs engineering work, a decision, or a vendor.

1. **Real second-factor (TOTP) check for desk staff**: only a fake exists. Without it the human desk cannot be mounted (it deliberately refuses to start with fakes).
2. **Staff directory**: no real list of staff accounts; planned as an environment list named `ROBIN_CONCIERGE_STAFF`; not built.
3. **Pager**: the desk can only "page" through a fake; the real one (a call or WhatsApp to the on-call person) is not built. Until then a handoff is recorded but nobody is woken up; the AI ladder (child, second contact) still runs.
4. **Masked-contact bridge** (staff phone the family without seeing the number): fake only.
5. **Family lookup for the desk** (to let the desk see a family's details by id): adapter not built.
6. **Intake channel for the concierge**: there is no path yet for a parent's WhatsApp or voice request ("book me a cab") to become a concierge request. Today only the code interface exists.
7. **Payment link message** for concierge errands (the user pays by a link, staff never pay): not built.
8. **The AI emergency flow now hands a card to the desk and the Robin scheduler runs the desk's page escalation** (built 2026-11-10 with fakes only). Real paging (3) is what makes it matter.
9. Real calls were never placed; real WhatsApp was never sent; real Vobiz forwarded-call field, bridge and listen-in are written from documentation only.
10. Carrier codes, no-reply timers and call forwarding behaviour: unverified.
11. Hindi and Hinglish speech recognition on elderly voices; text-to-speech pronunciation: unmeasured.
12. The Android app and floating mic: built and unit-tested, never run on a device; no pre-launch report from Play.
13. Postgres: Robin tables are tested on SQLite; the restore drill on Postgres (restore.md section C) has not been run [U].
14. Device S7/S8 (phone silent, phone off) sweeps run in the same tick; thresholds are invented and flagged unverified. The protection pack (notification and call signals) is a later release.
15. The safety evaluation corpus is small and written by engineers; real misses are listed in `docs/ROBIN_EVAL.md`; clinical and Hindi review needed.
16. No ticket system for the support line; no staff scheduling tool; roster is entered by a lead one shift at a time.
17. Audit hash chain anchor (so staff cannot rewrite history unnoticed): not built.

---

## 20. Questions for you

1. **Kill switch**: when you press `pause-all`, an SOS from a parent's phone still WhatsApps the child but no phone rings. Is that what you want, or should pause-all silence everything including the SOS message?
2. Which carriers do your first families use? We only offer forwarding for carriers that passed section 11.
3. First families: only yours, or also friends? (Each needs an in-person visit.)
4. Will you or a named person be the lead on the emergency desk roster for the first weeks?
5. Floating mic: ship with version 1.0 or as 1.1 after Play accepts the thin build?
