# Friday private-beta: go / no-go checklist

Use with `docs/DEPLOY_AWS.md` (how) and `docs/LAUNCH_CHECKLIST.md` (provider details). Nothing in Friday has
yet been run against live providers (docs/QA_REPORT.md: "Nothing was verified against a live provider"), so
this gate is deliberately strict. **Every box in sections 1, 4 and 5 must be ticked before anyone but the
founder is invited. Any unticked box = NO-GO for that stage.**

Legend: [ ] open, [x] done in code (tests exist), "Owner" says who must act.

---

## 1. What the founder must provide (go/no-go inputs)

| # | Item | Why | Owner | Done |
|---|---|---|---|---|
| 1.1 | A **domain** you control, with an `A` record to the static IP | HTTPS webhooks (Vobiz, Meta need a real https URL) | Founder | [ ] |
| 1.2 | **AWS account**: root MFA, `friday-admin` user with MFA, budget alert, region ap-south-1 (DEPLOY_AWS s.1-2) | OPS-1 India hosting | Founder | [ ] |
| 1.3 | **Fresh keys, created after the old ones were rotated** (the old ones were pasted in chats, treat as leaked): Anthropic, Sarvam, Vobiz, Google Maps, Meta token and app secret. Monthly spend limits set on Anthropic and Google | secrets hygiene | Founder | [ ] |
| 1.4 | **Vobiz**: trial upgraded to a full account, balance topped up, a **dedicated number** bought for Friday (not the shared Sarvam demo number +91 80 7158 2175), **call queuing OFF**, answer/hangup URLs registered (DEPLOY_AWS s.10a), per-minute rate noted | docs/LAUNCH_CHECKLIST.md s.1 | Founder | [ ] |
| 1.5 | **Meta WhatsApp Business**: business verification done, display name approved, a real (not the free test) phone number, permanent System User token, all templates in section 4 **approved** | WhatsApp is the only text channel in the beta (SMS is off) | Founder | [ ] |
| 1.6 | **Privacy policy, terms of use and Grievance Officer** (name, email, address, response time) published at real URLs, and the placeholder links in the onboarding text replaced (section 3, item C-1) | DPDP Act notice and consent; OPS-4 | Founder + lawyer | [ ] |
| 1.7 | **Recording and retention decision** (section 6) written down. Default for the beta: no recordings, transcripts kept N days | DPDP / PRD Q4; OPS-8 | Founder + lawyer | [ ] |
| 1.8 | **Zero-data-retention (ZDR) and data-processing terms requested in writing** from Anthropic, Sarvam and Vobiz (also Meta and Google; they are standard terms). Keep the replies | OPS-2 | Founder | [ ] |
| 1.9 | **Official customer-care numbers verified**: open `friday/discovery/data/official_numbers.json`, and for every company check the number on its own website or a recent bill; mark the date. Friday refuses to call care lines not on this list, so a wrong entry = calling a stranger | docs/LAUNCH_CHECKLIST.md s.6 last row | Founder + one engineer | [ ] |
| 1.10 | **Truecaller for Business** (and CNAP where available) registered for the Friday caller number, so businesses see "Friday (AI assistant)" instead of an unknown number | caller-ID reputation | Founder | [ ] |
| 1.11 | A named **person on call** for the beta (phone reachable) who knows the kill switch; the Grievance Officer mailbox is monitored | incident response | Founder | [ ] |

---

## 2. Already done in code (tests exist, all offline)

- [x] **Safety rules held in every simulated test** (docs/QA_REPORT.md s.4, s.6): AI disclosure is the first thing said on every call; never asks for or stores OTP/PIN/CVV/card numbers; no commitment without the user's approval; private notes and phone numbers never reach businesses; consent gates; quiet hours; "delete everything".
- [x] `tests/security` has no open xfails; every code item in `docs/SECURITY_FIXES.md` is closed.
- [x] Bugs BUG-1..BUG-18 from the QA report are fixed (BUG-2 fan-out on the real DB, BUG-5 wrong business dialled, BUG-8 false stock report, BUG-13 family consent flow were the "must fix before pilot" ones).
- [x] Load test: 1000 users, 200 concurrent calls, zero lost/duplicate tasks, calls or messages (single process, simulator; Postgres/Redis/real network not covered).
- [x] Webhooks: WhatsApp `X-Hub-Signature-256` verified (bad or missing signature = 401, in live without an app secret = 401); verify-token handshake; Vobiz URLs and media WebSocket require a per-call HMAC token (403 otherwise); duplicate deliveries dropped by the idempotency store.
- [x] `FRIDAY_PROFILE=beta` (friday/core/config.py): live mode refuses to start unless Anthropic, Sarvam, Vobiz + caller IDs, Google Places, WhatsApp Cloud (token, phone number id, app secret, a non-default verify token), an https public URL, Postgres, all four separate keys, the admin token, and `FRIDAY_INVITE_ONLY=true` are set; `friday check` names each missing item. Hotels (Expedia), SMS (MSG91/DLT) and the object store are optional; recordings are forced OFF without an object store. Tests: `tests/cli/test_beta_and_pause.py`.
- [x] Live mode refuses the default secret key, default WhatsApp verify token and DEBUG logging; separate PIN pepper / field key / blind-index key (SECURITY-30).
- [x] `/admin/*` is disabled (404) without a token and 401 with a wrong one; `/sim/*` does not exist in live mode; `/docs` is not reachable through the proxy.
- [x] **Kill switch**: `friday pause` / `--resume` / `--status` (friday/pause.py): no new outbound calls, no scheduled retries, no nudges; new requests get a polite notice; inbound messages and calls in progress continue. Tests included.
- [x] Deployment pack: `Dockerfile`, `deploy/` (compose with only 80/443 published, Postgres/Redis on an internal network, HSTS, WebSocket pass-through, token-redacting access logs, log rotation, healthchecks, restarts), nightly `pg_dump` to S3 with a minimal IAM policy and 30-day lifecycle, `update.sh` with rollback, `smoke_test.sh`.

---

## 3. Still open (be honest with yourself about these)

Severity for a **small beta with consenting friends**. "Blocker" = do not invite anyone until closed.

| ID | Item | Source | Severity | Owner |
|---|---|---|---|---|
| O-1 | **Nothing has run against live providers.** Do the founder-only live call test (section 7, stage A) and fix what breaks | QA_REPORT header | Blocker | Founder + engineer |
| O-2 | **Vobiz `TODO` markers** in `friday/voice/telephony/sarvam.py`: DTMF / record / transfer request bodies, hangup causes, mu-law and L16 details, delete-recording API. Until confirmed, keep tasks that need IVR navigation (customer-care calls), call transfer ("connect me") and recordings **off for testers** | docs/LAUNCH_CHECKLIST.md s.2, docs/SARVAM_QUESTIONS.md | Blocker for care tasks | Engineer + Vobiz |
| O-3 | **OPS-2** ZDR and DPAs with the vendors (item 1.8) | SECURITY_FIXES.md | Blocker (real user data) | Founder |
| O-4 | **OPS-1 residual**: the beta stores `FRIDAY_FIELD_KEY` in a root-only file on the server instead of AWS KMS (`FRIDAY_FIELD_KEY_ID`), uses a local secrets file instead of Secrets Manager, and has no WAF/CloudTrail. Acceptable for friends-only, not for public launch | SECURITY_FIXES.md OPS-1 | Accept for beta, close before public | Engineer |
| O-5 | **OPS-4** Grievance Officer named in the notice and a "grievance" keyword/email route; **OPS-5** DPIA (health data of third parties, call recording) and legal sign-off | SECURITY_FIXES.md | Blocker for anyone outside the founder's circle | Founder + lawyer |
| O-6 | **OPS-3** external penetration test and live-call AI red-team | SECURITY_FIXES.md | Before public beta, not before friends | Founder |
| O-7 | **OPS-6** breach runbook, CERT-In 6-hour contact, 180-day security logs in India (the VM keeps Docker logs for ~50 MB; ship them somewhere durable before public beta) | SECURITY_FIXES.md | Before public beta | Founder + engineer |
| O-8 | **OPS-7** staff access: SSO/MFA, break-glass. Beta rule: only the founder and one engineer have the SSH key; MFA on AWS, GitHub, Meta, Vobiz, Anthropic | SECURITY_FIXES.md | Accept for beta with the rule | Founder |
| O-9 | **OPS-8** recording announcement + India storage + delete at the provider. Beta stance: recordings OFF, so nothing to delete; the Vobiz delete-recording API is still an open `TODO` | SECURITY_FIXES.md, QA_REPORT s.4 | Closed by "recordings off" | Founder |
| O-10 | **OPS-10** Meta's policy on general-purpose AI assistants can remove WhatsApp access at any time. SMS is OFF in the beta, so a ban stops all text delivery. Mitigation: keep a second channel plan (register DLT + MSG91 before public launch) | SECURITY_FIXES.md | Known risk | Founder |
| O-11 | **Hotel tasks are simulated** when Expedia keys are absent (the beta default): `friday check` prints it, but a user who asks Friday to "book a hotel" would get a **pretend** booking. Do not offer or test hotels; ask engineering to make the brain refuse hotel tasks when the provider is the simulator | config.py `beta` profile | Blocker unless testers are told | Engineer |
| O-12 | **Placeholder legal links**: the onboarding consent text contains `https://friday.example/terms` (hardcoded in `friday/brain/heuristics/onboarding.py`, lines ~162 and ~167) and has no privacy-policy or grievance link. Needs a code change by the AI/brain owner to read the real URLs (suggest `FRIDAY_TERMS_URL`, `FRIDAY_PRIVACY_URL`) | onboarding.py | Blocker for friends | Engineer |
| O-13 | **WhatsApp nudge template shape**: the proactive engine sends template `nudge` with 2 variables (first name, text) while the notifier's generic fallback sends 1 variable (text). Meta rejects a variable-count mismatch, so one of the two paths would fail outside the 24-hour window. Register the 2-variable body (section 4) and have engineering unify the fallback | channels/notifier.py vs proactive/engine.py | Fix before relying on nudges | Engineer |
| O-14 | Re-run `uv run pytest` and `uv run ruff check .` on the exact commit you deploy (the QA report lists tests that were once expected failures and have since been fixed) | QA_REPORT s.3 | Routine | Engineer |
| O-15 | **Single process for web + task + voice** (mid-call questions and the Vobiz audio stream need the same process). One server = one point of failure; a restart cuts live calls. Fine for a beta, not for scale | DEPLOY_AWS.md s.0 and s.15 | Known design limit | Engineer |
| O-16 | **Kill switch limits**: calls already in progress finish; a task step already running may still send its next message; the flag is a file on a shared Docker volume (or `FRIDAY_PAUSED=true`), not a database row. `update.sh` pauses new calls automatically during a release | friday/pause.py | Documented | Engineer |
| O-17 | The Docker image and compose stack were validated by static checks only (`docker compose config`, `bash -n`, wheel contents); **no image has been built** in the environment that prepared this pack. The first `update.sh` run is the real test | this pack | Expect small fixes on day one | Engineer |
| O-18 | Truecaller / CNAP registration and caller-ID warm-up caps (10, 20, 35 calls per day) mean early call volume is intentionally small | ARCHITECTURE.md s.10.1 | Informational | Founder |
| O-19 | Approval questions never expire or send a reminder; "2 AM" window display bug for "sunday subah 10 baje"; user-facing category text sometimes contains the whole phrase | QA_REPORT "Other observations" | Medium | Engineer |

---

## 4. WhatsApp message templates to submit to Meta

Submit each in **English (`en`)** and **Hindi (`hi`)**; for Hinglish users register Romanised-Hindi variants
under `en` with the suffix `_hinglish` (PRD Q9) only if you want them. Footer on every template: "Reply STOP to stop these."
Category UTILITY unless noted. Meta rejects a body that is only a variable or that starts or ends with one:
add fixed words around it. The code fills the variables with the text in the right-hand column.

Names below are the **exact names Friday sends**. They come from `Settings.whatsapp_templates`
(`FRIDAY_WHATSAPP_TEMPLATES` in `deploy/env.production.example`). If you rename one in Meta, change the JSON, too.

### 4.1 Needed for the beta (the code sends these)

| Logical key | Meta template name | Variables the code sends | Suggested body (`{{n}}` = variable) | Quick-reply buttons |
|---|---|---|---|---|
| `task_update` | `friday_task_update_v1` | `{{1}}` = the update text (max 900 chars) | "Update from Friday: {{1}}" | `See details` |
| `question` | `friday_question_v1` | `{{1}}` = the question text | "Friday has a question for you: {{1}} Tap to answer." | `Answer now` |
| `nudge` | `friday_nudge_v1` | `{{1}}` = first name, `{{2}}` = nudge text (max 900) | "Hi {{1}}, a quick heads-up from Friday: {{2}}" (see open item O-13) | `Yes, do it` , `Not now`, `Stop these` |
| `reengage` | `friday_reengage_v1` | `{{1}}` = text | "Friday here. {{1}} Reply any time to continue." | none (registered because it is configured; no sender exists in the code yet) |
| `friday_biz_request` (messages **to businesses**, PRD US-24.2) | `friday_biz_request` | `{{1}}` = on whose behalf (the user), `{{2}}` = the ask | "Hello, this is Friday, an AI assistant contacting you on behalf of a customer, {{1}}. {{2}}" | `Reply`, `Stop messages` |
| `beneficiary_optin` (asks a family member for permission; circle feature) | `friday_beneficiary_optin` | `{{1}}` = their name, `{{2}}` = who added them, `{{3}}` = relation, `{{4}}` = what | "Namaste {{1}}, I'm Friday, an AI assistant. {{2}} ({{3}}) has booked {{4}} for you. May I send you confirmations and reminders for it?" | `Yes`, `No` |
| `business_booking_declined` (note to a business when the user declines) | `friday_business_declined_v1` | `{{1}}` = business name | "Hello {{1}}, the customer who contacted you through Friday (an AI assistant) will not be going ahead with the booking. Thank you for your time." | `OK`, `Stop messages` |
| `business_booking_confirmed` (end-of-call touch to a business) | `friday_business_touch` | `{{1}}` = customer name, `{{2}}` = confirmed terms, `{{3}}` = "Friday" | "Booking confirmed via {{3}} for {{1}}: {{2}}. Friday is an AI assistant that books on behalf of customers." (PRD `friday_business_touch`) | `OK`, `Stop messages` |
| `business_enquiry_thanks` | `friday_business_thanks_v1` | `{{1}}` = customer name, `{{2}}` = "Friday" | "Thank you for speaking with {{2}}, an AI assistant, on behalf of {{1}} today." | `Stop messages` |

(The key `friday_biz_request` has no entry in the JSON, so Friday uses it as the name directly.)

### 4.2 In the product requirements (PRD section 8.1) but not wired to the beta defaults
The PRD lists these additional templates; the code today routes nudges, updates and questions through the generic
ones above. Do **not** wait for them: `friday_appointment_reminder`, `friday_call_question`, `friday_approval_needed`,
`friday_followup_check`, `friday_date_nudge`, `friday_pattern_nudge` (MARKETING, PRD Q10), `friday_morning_briefing`,
`friday_business_change`, `friday_beneficiary_reminder`, `friday_comparison_ready`, `friday_checkin_optin`,
`friday_checkin_summary`, `friday_checkin_alert`, `friday_care_update`, `friday_recurring_booked`, `friday_stay_reminder`,
`friday_cancel_deadline`. If you want one, also add its logical key to `FRIDAY_WHATSAPP_TEMPLATES` once engineering uses it.
Anything sent **outside the 24-hour reply window** needs an approved template; if none fits, Friday does not send.

Test every template with your own phone before testers join (Meta's template manager has a *Send test* option).

---

## 5. Technical gate (all must be true on the server)

- [ ] `sudo ./deploy/smoke_test.sh` prints `SMOKE TEST PASSED` (includes `friday check --live`: live configuration OK; Vobiz balance and numbers read-only).
- [ ] `sudo ./deploy/dc.sh exec api friday check` prints `live configuration: OK` and lists the optional features that are OFF (hotels, SMS, recordings) exactly as you expect.
- [ ] A **restore drill** succeeded this week (`deploy/restore.md`, section A) and last night's backup is in S3.
- [ ] `FRIDAY_PROFILE=beta`, `FRIDAY_MODE=live`, `FRIDAY_INVITE_ONLY=true`, `FRIDAY_CALL_RECORD` irrelevant (recordings are off without a store).
- [ ] Kill-switch drill: `friday pause`, send yourself a WhatsApp message (you get the polite notice, no call is placed), then `friday pause --resume`.
- [ ] `/etc/friday/.env` offline copy stored; no secret has ever been in chat/git; AWS Budget alert email received a test.
- [ ] `uv run pytest` and `uv run ruff check .` green on the deployed commit (CI or engineer's machine).
- [ ] Anthropic, Google and Vobiz spend limits / low-balance alerts are set.

---

## 6. Recording and retention decisions (write the answers down)

| Question | Beta default | Decision (founder) |
|---|---|---|
| Do we record calls? | **No.** Recordings stay off (no object store). Needs an announcement, India storage, a delete path at Vobiz and legal sign-off (OPS-8) before turning on | |
| How long do we keep call transcripts, messages and task history? | Until the user says "delete everything"; the retention job erases on request. Pick a maximum (for example 90 days) and tell users | |
| Who may read transcripts? | Founder and one named engineer, for quality review only; never exported to chat/email | |
| Are vendors allowed to retain or train on our data? | **No**: ZDR / no-training terms requested from Anthropic, Sarvam, Vobiz (item 1.8) | |
| What do we tell a business on the call? | AI disclosure is the first sentence on every call (already enforced). If recording is ever enabled, the announcement is added | |
| Health or third-party data | Treat as sensitive. Do not test with real parents' health data until OPS-5 (DPIA) is done | |

---

## 7. Pilot rollout plan

Do not skip stages. Each stage ends with a short written note: what broke, what it cost, what changes.

**Stage A: founder only (days 1-3).**
1. Deploy, smoke test, register webhooks (DEPLOY_AWS s.9-11). Keep `FRIDAY_ADMIN_PHONES` = your number only; invite-only stays on.
2. Run the first-live-call script in docs/LAUNCH_CHECKLIST.md s.7 (onboarding, a call to your own mobile, inbound call, "delete everything"). Twice, both pass.
3. Run the kill-switch drill and a rollback drill (`update.sh --rollback`).
4. Check cost per call against the estimates (DEPLOY_AWS s.14).

**Stage B: 5-10 consenting friends (weeks 1-2), only after sections 1, 4 and 5 are fully ticked.**
- **Allowlist**: Friday stays `FRIDAY_INVITE_ONLY=true`. Create the invite codes yourself (message "invite" to Friday from your admin number: you receive a `FRI-XXXXXX` code, each works once) and hand them to named friends only. Keep a list of who has a code. Nobody else can onboard.
- **Consent**: each friend reads the privacy notice and agrees in the onboarding chat; tell them it is a test, calls are made by an AI that says so, and **not to give health, financial or other people's private data**.
- Scope: simple tasks only: enquiries, one-business bookings with call-back approval, reminders. Switch off or avoid: hotels, customer-care/IVR calls, call transfer, wellbeing check-ins, family-member features, until open items O-2, O-11 and the circle consent flow are verified live.
- Caps (already in `deploy/env.production.example`): 2 concurrent calls, 20 calls per number per day, 2 proactive messages per user per day, 5-minute calls. Raise them only after a clean week.
- **Daily review (15 min, every day, same person)**:
  1. `sudo ./deploy/smoke_test.sh` green; no dead letters.
  2. Read **every call transcript and outcome** from the last 24 hours: did Friday say it is an AI first, stay on topic, avoid digits and commitments the user did not approve, and treat the business politely? Anything off: pause, note it, fix before resuming.
  3. **Cost**: Vobiz balance, Anthropic usage, Google billing, AWS Budget. Compute cost per task; compare with section 14 of DEPLOY_AWS.md. Anything above 2x the estimate: pause and investigate.
  4. Complaints, "stop" and "delete everything" requests, businesses that asked not to be called (the do-not-call list must be honoured on every number).
  5. Number health: `GET /admin/numbers` (admin token) shows answer rate, spam flags, status per number.
  6. Ask each friend one question: "Was there anything you did not like?"
- **Weekly**: restore drill result, key and access review, Meta quality rating, decide whether to add the next 5 friends.

**Kill switch procedure (anyone on the team can do it; no approval needed).**
1. `ssh` to the server, `cd /opt/friday`, `sudo ./deploy/dc.sh exec api friday pause`. (Or, from the Lightsail console, use *Connect using SSH*.)
2. Confirm: `sudo ./deploy/dc.sh exec api friday pause --status` says PAUSED. Send yourself a WhatsApp message to see the polite notice.
3. If a call is still running and misbehaving: `sudo ./deploy/dc.sh restart api` (cuts live calls), or remove the number's application in the Vobiz console.
4. Wider stop: `sudo ./deploy/dc.sh stop api worker-proactive`, or unsubscribe the Meta webhook.
5. Tell affected testers in plain words. Write down what happened.
6. Resume only when the cause is fixed and one test call by the founder is clean: `friday pause --resume`.

**Exit criteria for widening beyond friends** (a different checklist): all open items in section 3 marked Blocker or "before public beta" closed, an external penetration test (OPS-3), legal sign-off (OPS-5), DLT/SMS fallback live, and two weeks of daily reviews with no unresolved safety issue.
