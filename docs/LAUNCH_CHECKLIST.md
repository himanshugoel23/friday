# Live pilot launch checklist

Goal: a private pilot (founder + a handful of invited users) with real calls. Nothing here has been run
live yet. Work top to bottom; stop at the first failure and set `FRIDAY_MODE=simulator` to fall back.

## 0. Where live tests can run

The Claude cloud sandbox **cannot** reach the providers and the founder cannot edit its allowed domains.
Run live tests on a **machine or server with normal internet access** (a laptop with a tunnel, or a small
server in an India region). It needs: Python >= 3.11 + `uv`, a public HTTPS URL for webhooks and the
media WebSocket (`FRIDAY_PUBLIC_BASE_URL`; a tunnel is fine for the first call), and outbound access to
api.anthropic.com, api.sarvam.ai, api.vobiz.ai, graph.facebook.com, maps.googleapis.com.

## 1. Accounts and environment variable names

Put values in the server environment or an untracked `.env` (never commit, never paste into chat).

| Account | Variables |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| Sarvam (STT/TTS) | `SARVAM_API_KEY` |
| **Vobiz** (telephony; console.vobiz.ai) | `SARVAM_TELEPHONY_AUTH_ID` (Account/Auth ID), `SARVAM_TELEPHONY_AUTH_TOKEN` (Auth Secret), `FRIDAY_NUMBERS` or `SARVAM_CALLER_IDS` (comma list of E.164 numbers you own on Vobiz) |
| Google Maps Platform | `GOOGLE_PLACES_API_KEY` (Places API (New) + Geocoding API enabled) |
| Meta WhatsApp Cloud API | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` |
| MSG91 SMS (DLT) | `MSG91_AUTH_KEY`, `DLT_ENTITY_ID`, `FRIDAY_SMS_SENDER_ID`, `FRIDAY_SMS_DLT_TEMPLATES` |
| Platform | `FRIDAY_MODE=live`, `FRIDAY_PUBLIC_BASE_URL`, `FRIDAY_SECRET_KEY`, `FRIDAY_DATABASE_URL` (Postgres), `FRIDAY_REDIS_URL`, `FRIDAY_OBJECT_STORE_URL` (s3://bucket/prefix, India region), `FRIDAY_ADMIN_TOKEN`, `FRIDAY_ROLES` |
| Field keys (separate secrets, SECURITY-30) | `FRIDAY_PIN_PEPPER`, `FRIDAY_INDEX_KEY`, and `FRIDAY_FIELD_KEY_ID` (KMS) or, for a throw-away pilot only, `FRIDAY_FIELD_KEY` |

`uv run friday check` prints every missing or unsafe setting by name. It must say "live configuration: OK".

### Vobiz account state (as of the last update)
* KYC is verified. The account is **Prepaid with about Rs 25 balance** and shows a banner to **upgrade the trial
  to a full account**. A trial account typically restricts destinations / caller IDs and adds a prompt to calls:
  upgrade and top up before the pilot (budget: see `docs/QA_REPORT.md`, about Rs 0.4-1.2 of telephony+LLM per
  simulated task; real PSTN minutes cost more - get the per-minute rate from Vobiz).
* Buy/assign at least one outbound number; add more later for the pool (`FRIDAY_NUMBERS`).
* Turn **call queuing OFF** (queued calls can be held then failed).
* Ask Vobiz (open questions in `docs/SARVAM_QUESTIONS.md`): AI-voice-agent/spam policy for outbound from their
  DIDs, per-call caller-ID choice, CNAP name, concurrency limits, DTMF and Record request bodies, delete-recording
  API, hangup causes.
* The number rented inside Sarvam (+91 80 7158 2175) **cannot** be used: Sarvam owns that Vobiz account and only
  exposes its hosted agents. Telephony is Vobiz-only for now.

## 2. Verify the `TODO(<doc page>)` markers in `friday/voice/telephony/sarvam.py`

Open the Vobiz / Sarvam docs and resolve each marker (details and the question list: `docs/SARVAM_QUESTIONS.md`):

| Marker (line) | Verify |
|---|---|
| `DEFAULT_BASE_URL` (~120) | API base `https://api.vobiz.ai/api/v1` |
| Call -> DTMF / Record / Transfer (~42) | request bodies for send-DTMF, start-recording, live transfer |
| Hangup causes (~125) | cause names -> `DialStatus` mapping |
| `keepCallAlive`, mu-law inbound (~145) | stream attribute and codec |
| L16 byte order (~181) | little- vs big-endian |
| Delete recording (~354) | DPDP erasure API for recordings |
| Instant Outbound fields (~407) | `from`, `to`, `answer_url`, machine detection |
| Record API path (~478) | response field holding the URL |
| Stream events (~554) | `start` / `media` / `dtmf` / `playedStream` / `clearedAudio` / `stop` |

Record the outcome next to each marker and delete the `TODO`. Until DTMF and recording are confirmed, tasks that
need IVR navigation or recordings must stay disabled for pilot users.

## 3. Meta WhatsApp test number

1. developers.facebook.com -> create an app (type Business) -> add the WhatsApp product.
2. Use the free **test number**; add up to 5 recipient phones (the founder's and testers').
3. Copy the temporary token (24 h) -> `WHATSAPP_ACCESS_TOKEN`; Phone number ID -> `WHATSAPP_PHONE_NUMBER_ID`;
   App secret -> `WHATSAPP_APP_SECRET`; choose a random `WHATSAPP_VERIFY_TOKEN` (the default is rejected in live mode).
4. Webhook: callback URL `https://<host>/webhooks/whatsapp`, verify token as above, subscribe to `messages`.
5. Send "hi" from an allowed phone: Friday must reply within a second. A bad signature must be rejected.
6. For a permanent token create a System User token; later move to a verified Business number.
7. Meta's policy on general-purpose AI assistants (OPS-10): keep SMS/voice fallback working.

## 4. Message templates to register (WhatsApp, category UTILITY unless noted)

Logical key -> default name in `Settings.whatsapp_templates`: `nudge` -> `friday_nudge_v1`,
`task_update` -> `friday_task_update_v1`, `question` -> `friday_question_v1`, `reengage` -> `friday_reengage_v1`.
Also needed: the business touch `friday_biz_request` (messages to businesses), `business_booking_declined`,
and the circle opt-in `beneficiary_optin` (name, requester, relation, what). Each takes one body parameter
(the message text, <= 1024 chars) except the opt-in. Register Hindi and English (`FRIDAY_WHATSAPP_TEMPLATES` can
override names). Free-form messages are only allowed inside the 24 h window after the user's last message.

## 5. SMS: DLT, Truecaller

* **DLT** (TRAI): register the entity (-> `DLT_ENTITY_ID`), a 6-char header (`FRIDAY_SMS_SENDER_ID`) and templates for
  `business_booking_confirmed`, `business_enquiry_thanks`, `user_task_update`, `user_reminder`; put the template IDs in
  `FRIDAY_SMS_DLT_TEMPLATES` (JSON). Voice from Indian numbers also needs the telemarketer/DLT constraints confirmed by Vobiz.
* **Truecaller for Business** (and CNAP when available): register the business name for the caller IDs so called
  shops see "Friday (AI assistant)" instead of an unknown number. Do this before volume, it protects number reputation.

## 6. Ops and legal blockers (from `docs/SECURITY_FIXES.md`)

| ID | Item | Needed before |
|---|---|---|
| OPS-1 | India-region hosting, **KMS** CMKs (`FRIDAY_FIELD_KEY_ID`), secrets manager, encrypted backups + restore drill, WAF | any real user data |
| OPS-2 | **Zero-data-retention + DPA** with Anthropic, Sarvam, Vobiz, Meta, MSG91, Google; vendor region inventory | live LLM / telephony |
| OPS-3 | **External penetration test** + live-call AI red-team | public beta (not the founder-only pilot) |
| OPS-4 | **Grievance Officer** named in the notice; WhatsApp "grievance" keyword + email | beta |
| OPS-5 | DPIA (third-party health data, call recording) and legal sign-off | beta |
| OPS-6 | breach runbook, CERT-In contact, 180-day logs in India | beta |
| OPS-8 | recording announcement + India storage + delete at provider | live calls |
| - | **Verify the official customer-care numbers** in `friday/discovery/data` against each company's website/bill (Friday refuses to call a care line that is not on the list) | care tasks |

For the first founder-only call the minimum is: a throw-away database, `FRIDAY_FIELD_KEY`, no real third-party data.

## 7. First live call to the founder's own phone

1. On the internet-connected machine: `uv sync`, export the variables, `FRIDAY_ROLES=api,task,voice`.
2. `uv run friday check` -> must print "live configuration: OK". Run `uv run pytest -q` (offline) once more.
3. `uv run friday serve` behind the HTTPS tunnel; confirm `curl https://<host>/health` -> `{"status":"ok"}`.
4. In the Vobiz console set the application's answer URL to
   `https://<host>/voice/sarvam/inbound?token=<token>` and hangup URL `/voice/sarvam/hangup` (print the token as in
   `docs/SARVAM_QUESTIONS.md`).
5. WhatsApp the test number from the founder's phone; onboard (name, city, language, consent, PIN).
6. Add the founder as the target: "mujhe call karke batao abhi kitne baje hain" with the founder's own mobile as the number.
7. Expect: the phone rings from the Vobiz number; **first words are the AI disclosure**; she mirrors the language; "are you
   a bot?" is answered honestly; she never speaks a digit run you did not approve; a WhatsApp report arrives.
8. Hold/DTMF test against a toll-free IVR you control (the log shows `DTMF:` turns).
9. Inbound test: call the Vobiz number from your phone (greeting), let one ring out (missed-call event).
10. Say "delete everything" -> PIN -> DELETE; the recording must disappear from the object store.
11. Watch cost: `GET /admin/...` (bearer `FRIDAY_ADMIN_TOKEN`) and the Vobiz balance after the call.

Go/no-go for inviting friends: steps 5-10 pass twice, no secret in logs (`grep` for your PIN/number), and
the bugs marked High in `docs/QA_REPORT.md` are fixed.

## 8. Rollback

* Switch off: `FRIDAY_MODE=simulator` (or stop the `voice` role: no call is ever placed without it).
* Stop calls only: remove `voice` from `FRIDAY_ROLES`; queued `call.place` jobs wait harmlessly.
* Pause nudges: remove `proactive`; pause one user via "pause everything".
* Kill a bad number: DNC it (`pool.block`) or retire it in the number pool; unsubscribe the WhatsApp webhook in Meta.
* Data: `delete everything` per user; ops erasure through the retention job; restore from the encrypted backup.
* Revoke keys: rotate the Anthropic / Sarvam / Vobiz / Meta secrets and set `FRIDAY_SECRET_KEY` anew (all PIN hashes
  survive; sessions do not).
