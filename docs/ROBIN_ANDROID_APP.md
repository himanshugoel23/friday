# Robin Android app: contract for the app builder (2026-11-04)

Server side: `friday/robindevice` (device API under `/robin/device/*`, scenario engine S1-S8 plus S4P, scam-check engine, call-pattern analyzer). Default OFF: `FRIDAY_ROBIN_DEVICE_ENABLED`. **Android code now lives in `android/robin-app` (thin app only, see the status section at the end).** Every line the app shows or reads aloud comes from the server in three languages (English, Roman Hinglish, Devanagari) and is **PENDING founder approval** (hear-before-change). The product name comes from the server (`brand` in the pair reply; setting `brand_name` / env `FRIDAY_BRAND_NAME`, pilot value "Robin").

Evidence tags: **[S]** seen in docs/research, **[U]** unverified, needs a real-phone or Play Console check, **[A]** my assessment.

## 0. Founder decisions this contract follows (2026-11-04)
1. **Consent is given by the CHILD (the family admin) on the parent's behalf**, `consent_basis = admin_on_behalf`. The parent is told on WhatsApp (family package) and can stop everything by voice or a widget tap. The phone **cannot grant** consent (`PUT /consent` with a `true` value is refused with 403); it can only **withdraw** items, and withdrawal erases what that item allowed the server to keep.
2. **A parent STOP pauses every sensitive signal type server-side until the PARENT resumes** (`POST /stop`, then `POST /resume` from the parent's device). There is no family-side resume. SOS and the voice button keep working while stopped. The child is told (WATCH) that the parent stopped Robin.
3. **The parent's main channel is WhatsApp, voice-note first.** Scam-check works by forwarding a message, link or screenshot to Robin on WhatsApp, with no app. The app is optional and has **two levels**.
4. No stealth, no call recording or audio capture beyond the parent's own press-to-talk message, no SMS, no call log, no accessibility service, no auto-blocking, no auto-calling of banks or police.

## 1. The two levels
### Level 1: the thin widget (easy Play review)
- A home-screen widget and an in-app screen with: **press-to-talk microphone button** (like "OK Google": hold to record, release to send, up to 60 s) and **press-and-hold SOS**.
- Permission: **microphone (`RECORD_AUDIO`) only** (plus notifications on Android 13+). No phone, no notification access, no camera.
- The voice message is uploaded to `POST /voice` and deleted by the server after speech-to-text. The app never records in the background.
- Also on the screen: **Stop / Resume**, "what Robin does" (the transparency screen, section 4) and the Robin name and icon. A persistent notification is only needed while recording or playing a reply.
- Screens: (a) first open: pairing code entry in the parent's language, with a voice prompt; (b) home: big mic, big SOS, small "Stop Robin"; (c) "what Robin sees" (read-only list); (d) paused/stopped banner with a big "Start again".

### Level 2: the optional PROTECTION PACK (installed by the child, in person)
- The child installs it **at an in-person setup with the parent's phone in hand**. Android requires the **phone's holder** to grant the call-screening role, notification access and (on sideloads) the restricted-settings override, so **the child cannot switch these on remotely** [S, per research]. The setup screen walks through each grant with a plain reason, one at a time, and shows a green tick per grant.
- Adds (each only if the family admin granted the matching consent item, otherwise the server drops the signal and counts it):

| Role / permission | Why (shown to the parent) | Consent item | Signals |
|---|---|---|---|
| Call-screening role (`ROLE_CALL_SCREENING`, Android 10+) | "tells Robin when an unknown number calls and for how long" | `calls` | `unknown_call_started`, `unknown_call_ended` |
| Phone state (`READ_PHONE_STATE`) | "knows whether you are on a call" | `calls` | `call_state_offhook` |
| Notification access, **limited to a fixed list of bank/UPI packages** | "reads only the amount and whether money left, from bank and UPI apps; never the message" | `payment_notifications` | `payment_notification` |
| Package-visibility `<queries>` for a fixed remote-access list | "notices if a screen-control app such as AnyDesk is installed or opened" | `remote_access` | `remote_access_app_installed/opened` |
| Camera-in-use callback (`CameraManager.AvailabilityCallback`) | "notices that the camera is on, not what it sees" | `camera` | `camera_in_use_start/stop` |
| Foreground check of a fixed bank/UPI list (usage access or accessibility **not** used; see 6) | "notices a bank app opened during a call" | `payment_app` | `payment_app_foreground` |
| Installer check on new apps (optional) | "notices an app installed from outside the store" | `unknown_sources` | `app_installed_unknown_source` |
| Location (optional, only with an SOS) | "sends where you are when you press SOS" | `location` | `location` on `/sos` |

- **Never requested:** SMS, call log, contacts, accessibility service, screen capture, call recording, microphone in the background.
- Level 2 shows a **persistent notification** ("Robin is protecting this phone", tap = the transparency screen) and uses a distinct Robin icon. Never hidden.

## 2. Play Console declarations [U until submitted]
- **Level 1:** a "voice message to your family assistant" feature; `RECORD_AUDIO` is used only on a user press. Data safety: voice recordings, collected, shared with the service, deleted after transcription, required for the feature.
- **Level 2:** (a) **Monitoring / device-safety purpose declaration**: parental/family safety, user-visible, with persistent notification and an in-app transparency screen; (b) **notification access** (core-function explanation): "the app reads payment notifications only from a fixed list of banking/UPI packages to extract amount and direction; the text is parsed on the phone and discarded"; (c) call-screening role use; (d) data safety form: no SMS, no call log, no contacts; (e) foreground-service type justification [U which type applies on Android 14+].
- Distribute through **Play closed testing** for the pilot, **not** sideloaded APKs (Play Protect pilot in India blocks risky sideloads [S]). If a sideload is unavoidable, Android 13+ shows **restricted settings** for notification access and accessibility: the setup must send the child through App info, three-dot menu, "Allow restricted settings" [S/U per OEM].

## 3. Device API (bearer device token; bad token = 404; JSON; `extra=forbid`)
Base `/robin/device`. All errors name fields and rules, never values. Limits per device: heartbeat 12/min, signals 30/min, share 10/min, voice 10/min, SOS 10/min, others 10-60/min; body max 64 KB (voice 1 MB); 429 on excess.

**Pair** `POST /pair` (no token). The child shows an 8-character code (15 minutes, single use); one device per parent (a new pairing revokes the old phone).
```json
{"code": "K7M2QX9A", "app_version": "1.0.0", "os_sdk": 34}
```
reply: `{"device_token": "rbn_...", "parent_id": "...", "language": "hinglish", "brand": "Robin", "consent_items": [...], "server_time_ms": 1788000000000, "limits": {"max_batch": 100, "max_body_bytes": 65536}}`. Store the token in the Android Keystore-backed encrypted storage. The server keeps only its SHA-256.

**Heartbeat** `POST /heartbeat` every 15 minutes (WorkManager) and on app open:
```json
{"app_version": "1.0.0", "os_sdk": 34, "ts_ms": 1788000000000, "battery_low": false,
 "roles": {"call_screening": true, "phone_state": true, "notification_access": true, "location": false,
           "package_visibility": true, "usage_access": false, "post_notifications": true}}
```
reply: `{"server_time_ms": ..., "paused": false, "consent": {"calls": true, ...}, "prompts": [ ...prompt payloads... ]}`. If `paused` is true show the "Robin is stopped/paused" banner.

**Signals** `POST /signals`: `{"events": [ ... up to 100 ... ]}`. Each event: `id` (8-64 chars `[A-Za-z0-9_-]`, unique, used for dedupe), `type`, `ts_ms` (epoch ms, not older than 48 h, not more than 5 min in the future) plus the fields below. **Any other field is rejected.**

| type | extra fields |
|---|---|
| `unknown_call_started` | `call_id` (app-local random), `number_class` (`international` `voip_like` `mobile` `landline` `toll_free` `shortcode`), optional `number_hash` (64 hex), optional `direction` (`incoming`/`outgoing`) |
| `unknown_call_ended` | `call_id`, `duration_s`, `answered` |
| `call_state_offhook` | optional `call_id`, `duration_s`, `ongoing`. Send one **every 5 minutes while off-hook** (`ongoing: true`) and one at hang-up (`ongoing: false`). The server treats a call with no update for 8 minutes as ended. |
| `camera_in_use_start` / `_stop` | none |
| `remote_access_app_opened` / `_installed` | `app`: `anydesk` `teamviewer` `quicksupport` `rustdesk` `airdroid` `other_remote` |
| `payment_app_foreground` | `app`: a payment label (below) |
| `payment_notification` | `app`, `direction` (`debit`/`credit`), `amount_paise` (int), `payee_kind` (`known` `new` `unknown` `merchant`) |
| `app_installed_unknown_source` | `source_class`: `browser` `messaging_app` `file_manager` `unknown` |
| `phone_heartbeat_missing` | `gap_s` (the app may report its own offline gap after reconnecting; the server also computes it) |

Payment labels: `gpay phonepe paytm bhim cred amazon_pay whatsapp_pay sbi_yono hdfc icici axis kotak pnb bob canara union indusind idfc other_bank other_upi`.

reply: `{"accepted": 3, "duplicates": 0, "dropped_no_consent": 1, "dropped_paused": 0, "stale": 0, "invalid": 1, "invalid_detail": [{"index": 2, "reason": "extra_field"}], "prompts": [...]}`. A bad event never blocks the batch: **drop the events listed in `invalid_detail`** from the queue (they would never be accepted). `dropped_no_consent` events are also dropped for good.

**Number hash:** the phone computes `sha256(per-install random salt + digits)`; the **salt never leaves the phone**, so the server cannot enumerate numbers. A reinstall loses the trusted list (acceptable). Never send the digits.

**Share** `POST /share` (the parent shares something from the Android share sheet): `{"kind": "text|url|phone|app_name|file_name|screenshot_ref", "value": "..."}` (max 2000 chars; for `screenshot_ref` an opaque id such as `shot_9f3a1c20`; Phase 1 cannot read pictures and answers UNSURE). The server answers with `verdict` (`SCAM_LIKELY` `RISKY` `UNSURE` `NO_SIGNS_FOUND`), `headline`, `reason`, `next_step`, `next_steps`, `alert_child`, `child_told`. The text is checked and **not stored**. 403 if the family has not granted `share_check`.

**Prompts** `GET /prompts` (also inside heartbeat and signals replies): each is
```json
{"prompt_id": "...", "scenario": "S1", "tier": "HIGH", "full_screen": true, "read_aloud": true,
 "not_before_ms": 0, "expires_ms": 0, "language": "hinglish",
 "text": {"en": "...", "hinglish": "...", "hi": "..."},
 "actions": [{"ack": "this_was_fine", "label": {"en": "...", "hinglish": "...", "hi": "..."}}],
 "status": "PENDING founder approval"}
```
Show `text[language]`; read it aloud with the phone's TTS if `read_aloud`; do not show before `not_before_ms` (night prompts are deferred to the morning); the buttons post the action's `ack`.

**Ack** `POST /ack`: `{"kind": "this_was_fine|i_am_ok|dismissed|call_son_tapped|sos", "prompt_id": "..."}` (`prompt_id` required for the first, third and fourth). "This was fine" resolves the incident, tells the child, and (for non-money, non-remote-access scenarios) teaches the parent's trusted numbers.

**SOS** `POST /sos`: `{}` or `{"lat": 28.6, "lon": 77.2}` (location kept only with the `location` consent). Works while stopped, paused or in the learning week and with no consent item. Press-and-hold 2 seconds. The reply carries a line that includes "tap Call 112": the app must also show a one-tap dial button for 112 (the server never dials). If the request fails, retry and also show a "Call family" button that opens the dialer with the child's number as supplied by the family package at pairing [U, product decision]; the app never reads contacts.

**Voice** `POST /voice`: raw audio body, `Content-Type: audio/ogg|audio/mp4|audio/aac|audio/amr|audio/wav|audio/webm|audio/mpeg`, header `X-Duration-S` 1-60, body at most 1 MB. Needs consent item `voice_messages` (403 otherwise). Works while stopped (it is an explicit press). Reply `{"accepted": true, "reply_text": null|"..."}`. The server passes the bytes to speech-to-text and never stores them; the app deletes its local copy after a 200.

**Consent** `GET /consent` -> `{"consent_basis": "admin_on_behalf", "items": {...}}`; `PUT /consent` `{"items": {"camera": false}}` withdraws only. **Pause** `POST /pause` `{"minutes": 5..1440}`. **Stop** `POST /stop`, **Resume** `POST /resume` (parent device only). **Erase** `DELETE /erase` deletes everything stored about the phone, revokes the token and tells the child. **Transparency** `GET /transparency` feeds the "what Robin sees" screen: `collected`, `never_collected`, live `counters`, the last 20 things the child was told (exact `why`, tier, details), `learning_mode`.

### Android-side parsing contract for `payment_notification`
The server rejects any text field, so the phone must do all parsing locally:
1. Only notifications whose package is in the fixed list are even looked at; everything else is ignored immediately and never logged.
2. Map package to the `app` label (candidate package names, **all UNVERIFIED, confirm with `adb shell pm list packages` and the Play listing**): `com.google.android.apps.nbu.paisa.user` gpay, `com.phonepe.app` phonepe, `net.one97.paytm` paytm, `in.org.npci.upiapp` bhim, `com.dreamplug.androidapp` cred, `com.sbi.lotusintouch` sbi_yono, `com.snapwork.hdfc` hdfc, `com.csam.icici.bank.imobile` icici, `com.axis.mobile` axis; others fall to `other_bank`/`other_upi`. Remote-access: `com.anydesk.anydeskandroid`, `com.teamviewer.teamviewer.market.mobile`, `com.teamviewer.quicksupport.market`, `com.carriez.flutter_hbb`, `com.sand.airdroid`.
3. Parse the title/body **in memory**: direction from debit/credit words ("debited", "paid", "sent", "credited", "received"; Hindi equivalents), amount from the rupee pattern converted to paise. If direction or amount is not found, **send nothing** (do not send a guess).
4. `payee_kind`: `known` if the payee string was seen in an earlier notification (the phone keeps a local set of salted hashes of payee strings; never uploaded), `new` if not, `merchant` if the payee looks like a merchant handle [U heuristics per app], `unknown` if it cannot be told. Do not read the phone's contacts for this.
5. Drop the text from memory straight after; no logging, no crash-report breadcrumbs with the text.

### Offline queue, retry and battery rules
- Queue events in an encrypted local DB: at most 500 events and 48 hours; when full drop the **oldest**. Send in batches of at most 100, oldest first; retry with backoff 30 s, 2 min, 10 min, then every hour. Use event `id` as the dedupe key; resending is safe.
- Remove from the queue on a 200 (accepted, duplicate, dropped or invalid alike).
- SOS and voice are **never queued behind** the signal queue: send at once; SOS retries every 10 seconds for 2 minutes with a visible "sending" state.
- Battery: no wake locks, no polling loops; heartbeat by WorkManager (15 minutes is the minimum period); off-hook updates only while a call is active; camera and notification listeners are event-driven. Set `battery_low` when below 15 percent (the server then lowers the "phone unreachable" alarm). Expect OEM battery optimisers (Xiaomi, Vivo, Oppo, Samsung) to kill the service: the setup must show the device's own "unrestricted battery" screen [U].

## 4. What the server does with the signals (so the app can explain it)
Scenarios S1 digital-arrest pattern, S2 remote-access app, S3 KYC/OTP call, S4 voice-clone panic (signal-based) and **S4P (driven by the conversation-pattern analyzer when the family package supplies a call transcript; there is no safe-word prompt)**, S5 payment alerts, S6 night camera, S7 phone unreachable, S8 pension season. Rules live in `friday/robindevice/scenarios.yaml` (flagged unverified). Per-parent **shadow mode** for the first 7 days (log only, no alerts and no nudges, with a counter report). The parent sees at most 2 nudges an hour (SOS exempt) and none between 10 pm and 7 am except a HIGH payment/money event. The child sees, for payments, only the **amount, direction, time and payee kind**. Sensitivity (Calm/Balanced/Careful) is set by the child.

## 5. Real-phone test checklist (Jio, Airtel, Vi; Android 11 to 15) [all U]
Run each on at least one phone per carrier and per Android version (11, 12, 13, 14, 15), including one Xiaomi/Samsung/Vivo:
1. Pairing code entry; token survives reboot; second pairing revokes the first.
2. Level 1: widget mic records and uploads; SOS hold; Stop then Resume; behaviour with the screen locked; Android 13+ notification permission.
3. Call-screening role prompt (Android 10+): unknown vs saved contact; international and +91 mobile classes; does the carrier verdict data (Android 11+) add anything.
4. Off-hook updates every 5 minutes during a 25-minute call; does the service survive Doze and the OEM battery manager.
5. Camera-in-use fires for a WhatsApp video call, the camera app and a front-camera selfie; false positives (flashlight? screen recorders?).
6. Notification access: each bank/UPI app's debit/credit notification text in English and Hindi; the parse rate; a UPI collect request; a credit; a failed payment (must not count as a debit).
7. Restricted settings flow for a sideloaded build on Android 13, 14 and 15; the same via Play closed testing.
8. Remote-access apps: opened and installed detection via `<queries>`; apps not on the list.
9. 48-hour offline test: airplane mode, 500 queued events, resume, no duplicates on the server.
10. Battery drain over 24 hours (target under 3 percent; **no figure is measured yet**).
11. Carrier forwarding for the receptionist (separate flow): USSD forwarding status per carrier; whether Robin sees the caller's number on a forwarded call (open with Vobiz).
12. WhatsApp video call while a bank app is open: confirm what Level 2 can and cannot see (expected: camera on, no content).

## 6. UNVERIFIED (do not promise in marketing)
- Camera-in-use callback: whether any permission is needed, and whether it fires for every app.
- Foreground bank-app detection without usage access or accessibility: **no Play-compliant method is confirmed**. Until the policy check is done, `payment_app_foreground` may come only from a notification arriving or the app being opened via the app's own launch intent; S3 and S4 degrade gracefully (the server accepts the signal if it ever arrives).
- Notification access approval by Play review; the foreground-service type for Android 14+; restricted settings in Android 15/16.
- Package names above; payee-kind heuristics; whether `voip_like` can be derived on-device (the server's 140-series rule is for pasted numbers only).
- DPDP read of `admin_on_behalf` consent with parent notification; the exact notification wording on WhatsApp (family package).
- All thresholds and weights (shadow week exists to tune them); the pension-season window (15 Oct to 30 Nov) is a design guess.
- Server persistence: device state is in memory in this build; the lead must back it with tables before a multi-instance deploy.

## 7. Status of the Android code (T14, 2026-11-06, branch work, not pushed)
**Scope built = Level 1 thin app only** (founder decision D4: the first Play ship is the thin widget; no protection pack, no sensor fall detector, no notification access, no call screening). All user-facing strings are **PENDING founder approval** (`app/src/main/res/values/strings.xml`, Hindi placeholders in `values-hi`).

| Part | Where | State |
|---|---|---|
| Pure Kotlin modules (`:core`, JVM only) | `android/robin-app/core` | built, 50 JUnit tests pass |
| `ApiClient` (all `/robin/device/*` calls, bearer token, strict writer and reader) | `ApiClient.kt`, `Models.kt` | tests pass; matches the shared fixtures |
| `PairingFlow`, `ConsentView` (withdraw only, no grant function), `SosGesture` (2 s hold) + `SosSender` (retry every 10 s for 2 min), `VoiceNoteGesture`, `PromptQueue`, `TransparencyScreenModel` | `core/src/main/kotlin/app/robin/core` | tests pass |
| Android layer: `MainActivity` (pairing, home, "what is on", consent list), `QuickActivity` (SOS + voice + Call 112, shown over the lock screen), `RobinWidget` (two big buttons), Keystore token store, `HttpsURLConnection` transport | `android/robin-app/app` | **compiles; debug APK builds; never run** |
| Shared contract fixtures | `tests/robindevice/contract/*.json` | read by `tests/robindevice/test_contract_fixtures.py` (replays each against the real server) and by `ContractFixturesTest.kt` |
| Build | `scripts/build-android.sh`, `.github/workflows/android.yml` | script run here; workflow not run (needs GitHub) |

**Build properties** (`android/robin-app/gradle.properties`, override with `-P` or the script's `ROBIN_*` env vars): `robin.applicationId` (placeholder `app.robin.parent`), `robin.brandName` (app label, default Robin), `robin.baseUrl` (placeholder `https://robin-server.invalid`, so an unconfigured build cannot reach anything), `robin.versionName`, `robin.versionCode`. minSdk 26, target/compile 34.

**Commands that were run in the sandbox:** SDK install via `sdkmanager` (platform 34, build-tools 34.0.0), `./gradlew test assembleDebug` (BUILD SUCCESSFUL, 50 tests), build with overridden id and brand (aapt2 shows the new package and label), `pytest tests/robindevice/test_contract_fixtures.py`.

**Design choices to know about**
- The widget cannot detect a 2-second hold, so each widget button opens `QuickActivity`, where the hold happens. This also stops a pocket tap from sending an SOS.
- Permissions: `INTERNET` and `RECORD_AUDIO` only. No foreground service, no WorkManager, no notifications, no location, no analytics, no Firebase, `allowBackup=false`, cleartext off. The heartbeat is sent when the app opens (no background job), so prompts reach the parent when the app or widget is opened; there is no push.
- SOS is sent without a location (no location permission in the thin build). The reply line says "call 112"; the app always shows a Call 112 button (dialer only). A "Call family" button is NOT built because the API does not supply the child's number (open product decision).
- The voice file is deleted after every upload attempt (success or failure) and at every app start; a failed send means record again.
- Reply parsing is a strict reader of the keys the app uses and ignores extra keys (so a server that adds a field does not break old phones); the writer sends only schema fields and refuses locally anything the server schema would refuse.
- The phone cannot grant consent: `ConsentView` and `ApiClient` have only `withdrawConsent`; a `true` is not expressible.

**NOT verified (no device, no emulator, no Play):** installation; the widget on a real launcher; `QuickActivity` over the lock screen (`showWhenLocked`); the microphone permission flow and recording quality (AAC/MP4 16 kHz) and that the server's speech-to-text accepts that audio; hold timing and haptics on real touch input; Keystore behaviour across OEMs, reboots and restores; Hindi rendering; text-to-speech read-aloud; battery and OEM background kills; behaviour on Android 8 to 15; TalkBack accessibility; the GitHub Actions workflow itself.

**Gaps against the plan:** no 15-minute WorkManager heartbeat; no offline signal queue (nothing queues in the thin build); no location with SOS; no "Call family" button; no erase UI (the API exists; the child owns delete-everything); no release signing; placeholder icon; UI strings and Hindi are placeholders; `signals` and `share` exist in `ApiClient` (contract complete) but have no screen.
