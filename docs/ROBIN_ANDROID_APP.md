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

**Voice** `POST /voice`: raw audio body, `Content-Type: audio/ogg|audio/mp4|audio/aac|audio/amr|audio/wav|audio/webm|audio/mpeg`, header `X-Duration-S` 1-60, body at most 1 MB. Needs consent item `voice_messages` (403 otherwise). Works while stopped (it is an explicit press). Reply `{"accepted": true, "reply_text": "..."|null, "reply_audio_url": "https://<server>/robin/device/audio/<token>"|null}` (T09). `reply_text` is in the PARENT's language; `reply_audio_url` is Robin's own text-to-speech, an unguessable token URL on the server's host that works for ONE fetch within about 90 seconds (then 404), no bearer needed; null/absent = speak `reply_text` yourself. The server passes the bytes to speech-to-text (language hint = the parent's language) and never stores them; the app deletes its local copy after a 200. A spoken "madad karo" / "help" / "bachao" raises an SOS (EMERGENCY, rings the child) even while paused or before setup is finished; the reply then says the child was told, or (if nobody could be told) says to press 112, never a false "told". Other words: "stop" pauses, "main theek hoon" is acknowledged, distress goes to the care protocol, anything else gets a short hello. Audio that could not be understood gets "say it once more" (200, `accepted: true`). Without the `voice_messages` consent (family `scam_check` item) the answer is 403 `no_consent` and the audio is not listened to; the SOS button still works.

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

**Commands that were run in the sandbox:** SDK install via `sdkmanager` (platform 34, build-tools 34.0.0), `./gradlew test assembleDebug` (BUILD SUCCESSFUL, 50 tests; the build now has two flavors, section 10), build with overridden id and brand (aapt2 shows the new package and label), `pytest tests/robindevice/test_contract_fixtures.py`.

**Design choices to know about**
- The widget cannot detect a 2-second hold, so each widget button opens `QuickActivity`, where the hold happens. This also stops a pocket tap from sending an SOS.
- Permissions: `INTERNET` and `RECORD_AUDIO` only. No foreground service, no WorkManager, no notifications, no location, no analytics, no Firebase, `allowBackup=false`, cleartext off. The heartbeat is sent when the app opens (no background job), so prompts reach the parent when the app or widget is opened; there is no push.
- SOS is sent without a location (no location permission in the thin build). The reply line says "call 112"; the app always shows a Call 112 button (dialer only). A "Call family" button is NOT built because the API does not supply the child's number (open product decision).
- The voice file is deleted after every upload attempt (success or failure) and at every app start; a failed send means record again.
- Reply parsing is a strict reader of the keys the app uses and ignores extra keys (so a server that adds a field does not break old phones); the writer sends only schema fields and refuses locally anything the server schema would refuse.
- The phone cannot grant consent: `ConsentView` and `ApiClient` have only `withdrawConsent`; a `true` is not expressible.

**NOT verified (no device, no emulator, no Play):** installation; the widget on a real launcher; `QuickActivity` over the lock screen (`showWhenLocked`); the microphone permission flow and recording quality (AAC/MP4 16 kHz) and that the server's speech-to-text accepts that audio; hold timing and haptics on real touch input; Keystore behaviour across OEMs, reboots and restores; Hindi rendering; text-to-speech read-aloud; battery and OEM background kills; behaviour on Android 8 to 15; TalkBack accessibility; the GitHub Actions workflow itself.

**Gaps against the plan:** no 15-minute WorkManager heartbeat; no offline signal queue (nothing queues in the thin build); no location with SOS; no "Call family" button; no erase UI (the API exists; the child owns delete-everything); no release signing; placeholder icon; UI strings and Hindi are placeholders; `signals` and `share` exist in `ApiClient` (contract complete) but have no screen.

## 8. T21 voice-first home screen and widget (2026-11-07, branch work, not pushed)
Founder: "default voice widget; nobody will type anything". All strings PENDING founder approval (English + Hindi placeholders).
- **Parent flow has no text input.** The only `EditText` is on the *Family setup* screen, reached by a long press on the Robin name, or by the link/QR payload `robin://pair?code=XXXXXXXX` (opens the setup screen with the code filled in; a person still taps Connect, so a stray link cannot silently re-pair the phone). Not paired: the parent sees one sentence and Call 112. Consent stays withdraw-only; the setup screen also offers "Add to home screen" (launcher pin request; not all launchers support it, and Android never lets an app add a widget without the launcher confirming [U]).
- **`VoiceTurn`** (`:core`, pure): idle -> recording -> uploading -> answering -> idle, plus error (no mic, too short, no speech, not understood, no consent, unpaired, busy, rejected, server) and offline. Tap starts, tap again / 2.5 s of silence after speech / 30 s stops; 10 s of silence at the start gives up. The recording file is deleted right after its bytes are read (before the upload); network failures retry up to 3 times from memory with 1.5 s waits; after that the parent taps again to record afresh. All numbers invented, unverified. 22 new JUnit tests (`VoiceTurnTest`, `SpeechPlanAndLinkTest`, voice-fixture test, `ApiClientTest`); 73 tests pass in total.
- **Answer spoken aloud** (`SpeechPlan`): `reply_audio_url` if present (optional key, **the server does not send it yet**; accepted only if https and the same host as the server), else Android TextToSpeech (hi -> hi-IN, hinglish/en -> en-IN), always with the text in large type. If the text is missing the app says a fixed fallback line (PENDING).
- **Widget**: a big Talk button (opens the quick screen and starts listening at once) and SOS (hold happens on the quick screen). The old hold-to-record voice button is replaced by tap-to-talk; the `/voice` route, `ApiClient.voice` and `VoiceNoteGesture` stay.
- **Still true**: permissions INTERNET and RECORD_AUDIO only; no foreground service, no background microphone, no hotword, no analytics. The microphone is released when the screen leaves the foreground.
- **NOT verified (no device, no emulator):** everything in section 7, plus: the widget tap starting recording, the permission prompt then auto-start, silence detection thresholds on real microphones, TTS voices and Hindi availability, MediaPlayer playback of a server URL, haptics, TalkBack reading of states, large-font layouts, the pin-widget request, the deep link from a QR scanner. (T09, 2026-11-07: the server now sends `reply_text` and, with a TTS voice, `reply_audio_url`; the app's fallback line is used only when neither arrives.)

## 9. T22 floating mic bubble (2026-11-10, branch work, not pushed)
Founder: "a PROPER floating mic like Wispr Flow's bubble". Founder decision 2026-11-10: **the bubble ships in 1.0**, protected against Play rejection by two build flavors (section 10). The permissions in section 7 ("INTERNET and RECORD_AUDIO only") describe the thin widget; **the `full` flavor adds the permissions below; `lite` does not (section 10)**. All strings are English + Hindi placeholders, **PENDING founder approval**. Not an accessibility service, no text injection, no hotword, no analytics.

**What it does.** A small draggable bubble (88 dp touch target) floats above every screen once (1) the child set it up on the family setup screen and (2) "Display over other apps" is allowed. One tap = the same `VoiceTurn` and `ApiClient.voice` as the T21 widget (tap to talk, 2.5 s silence or 30 s stops, answer by server https audio URL on the same host or Android TextToSpeech, large-type card next to the bubble). Six states, each with its own outline shape, glyph, word and colour (not colour alone): idle circle/mic/"Talk", listening rounded square/stop/"Listening" (a ring grows with loudness), sending diamond/arrow/"Sending", answering hexagon/speaker/"Speaking", offline triangle/"No internet", problem octagon/warning/"Problem". Haptics on state change (confirm, or reject for offline/problem), TalkBack labels per state plus custom actions (open menu, move to left/right edge, hide). Drag, snap to the nearest side edge, position remembered as edge + fraction (survives rotation). Long press (0.6 s) opens the menu: **SOS (2 s hold, same `SosGesture`/`SosSender`)**, Call 112 (dialer only), Hide for now, Turn off for now, Close. After an SOS the card keeps a Call 112 button.

**Control surfaces.** Child setup screen (reached by the existing long press on the name / setup link): permission steps in words (Done / Needed / Optional), the system screen for each missing step, an "after restart" choice, Turn on / Turn off. Parent main screen: one large On/Off switch (can always switch off; can switch on only after the child set it up and while all permissions hold). The bubble's own menu "Turn off for now" and "Hide for now" are the third and fourth ways to stop it (asked in the ticket). The notification tap opens the first screen (where the switch is); when the bubble is hidden, the notification tap shows it again. **Question for the founder:** the ticket says "tap to stop" on the notification and also "ONLY child screen and parent switch": I made the tap open the switch, with no stop button in the notification.

**Reboot.** `BootReceiver` starts it only if the child allowed it, chose "start after restart", it was left on (parent had not switched it off) and every permission is still in place (`BubblePolicy.startAtBoot`; the service checks again).

**Sensitive screens.** Without an accessibility service the app cannot know when a password or banking field is on screen: the person hides the bubble (menu, TalkBack action or notification) and it comes back by the notification. Hidden is not remembered across a restart of the service. Screen off stops the microphone and the voice. The bubble is not drawn over the lock screen by design of overlay windows [U on OEMs].

**Foreground service type (Android 14).** Declared `specialUse|microphone`. The long-lived overlay runs as `specialUse` (subtype property `floating_voice_assistant_bubble`); the `microphone` type is added with `startForeground` only for the seconds a tapped question is recorded, and removed again when it ends. **[U]** whether Play accepts `specialUse` for this (the special-use declaration form is reviewed by hand); whether an overlay touch counts as a "user interaction" exemption for starting the microphone type from the background on 14/15 [U: if refused, the code falls back to the plain service and the recording may capture silence, which the app reports as "I did not hear anything"]. `microphone` cannot be started from a boot receiver on Android 15, which is why boot starts only `specialUse`.

### Exact manifest permissions and Play-review impact
| Permission | Why | Play impact |
|---|---|---|
| `INTERNET` | talk to the Robin server | none |
| `RECORD_AUDIO` | the question, only after a tap | runtime permission; Data safety "voice recordings" (already declared for the widget); the microphone-in-background story must be explained in the listing |
| `SYSTEM_ALERT_WINDOW` | draw the bubble over other apps | **high scrutiny**: Play restricts "draw over other apps" to apps whose core function needs it; expect a permission/core-functionality justification (floating voice assistant for elders, user-initiated, always visible, hideable). The person must switch it on in system settings. [U] |
| `FOREGROUND_SERVICE` | long-running bubble service | needs a foreground-service declaration for Android 14+ apps |
| `FOREGROUND_SERVICE_SPECIAL_USE` | the overlay itself | **hand-reviewed** declaration with a subtype text and a demo video [U] |
| `FOREGROUND_SERVICE_MICROPHONE` | microphone type while a tapped question records | declaration with a video showing the user-initiated recording; the persistent notification must be visible [U] |
| `POST_NOTIFICATIONS` | "Robin mic is on" on Android 13+ | runtime permission; low impact |
| `RECEIVE_BOOT_COMPLETED` | restart after reboot, only if the child chose it | low impact; **not in the ticket's list**, added for "auto-start after reboot": remove it to drop that feature |
Not used: `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` (restricted by Play; the setup only opens the system battery screen, which needs no permission), `USE_FULL_SCREEN_INTENT`, accessibility, location, camera, contacts.

### What the code is (files)
`:core` (pure, JUnit): `BubbleState.kt` (state to look, cards, polygons), `BubbleGeometry.kt` (snap, placement, keyboard, card position, `TouchClassifier` tap/drag/long press), `BubbleMenu.kt` (menu model, `BubbleSession` modes, effects), `OverlayGate.kt` (permission gate, `BubbleSettings`/`BubblePolicy`, parent switch model). `:app`: `BubbleService.kt` (overlay windows, notification, foreground types, voice driver), `BubbleView.kt`, `BubblePrefs.kt` (settings, position, permission reads), `BubbleSetupUi.kt` (child section and parent switch), `BootReceiver.kt`; `MainActivity` hooks. 46 new JUnit tests, 119 in total, all pass.

### Overlay-permission missing: what the child setup screen shows
The "Display over other apps" row stays red-worded "Needed" with the reason, a button that opens the system screen for this app, and an extra paragraph naming the OEM variants ("Appear on top", "Show over other apps"); Turn on stays disabled until every Needed row is Done. On return the screen re-reads the permission.

### NOT verified (no device, no emulator, no Play)
Everything visual and system-level: overlay drawing and the shapes' look, touch, drag and snap feel, the 0.6 s long press, panel placement, service survival (battery managers on Xiaomi/Vivo/Oppo/Samsung, Doze), the specialUse and microphone foreground-type rules on Android 14/15 and the microphone from a background overlay, the boot start, keyboard avoidance (an unfocusable overlay may not receive the keyboard insets; the user can hide it), TalkBack on overlays and the custom actions, lock-screen and "show over keyboard" behaviour, haptics, notification channel on 13+ without permission, Hindi rendering, behaviour on Android 8 to 15, the Play declarations. `Settings.canDrawOverlays` can be wrong on some OEMs [U].

### Gaps / known rough edges
No analytics or crash reporter. No per-app hiding (impossible without accessibility). The auto-start checkbox on the setup screen resets if the child leaves for system settings before turning on. The card auto-hides after 45 s (answers), 20 s (problems) and the menu after 30 s: invented values. The bubble size, colours and words are unreviewed by a designer or a parent. Wording of the notification and permissions explanation is PENDING and needs a Play-policy read before submission.

## 10. Two build flavors: `full` and `lite` (2026-11-10, branch work, not pushed)
Founder decision: the floating mic bubble ships in 1.0. Google Play review of "draw over other apps" and the foreground-service declarations is the main risk, so the same code builds two editions. A rejection of `full` then never blocks the release of `lite`.

**What differs** (everything else, including `:core`, the widget, SOS, in-app voice, pairing, consent, the offline queue, is shared and identical):

| | `full` | `lite` |
|---|---|---|
| Home-screen widget, SOS, in-app voice | yes | yes |
| Floating mic bubble (overlay + foreground service) | yes | no |
| Bubble section on the child setup screen, parent On/Off switch | shown | hidden (not built into the screens) |
| Permissions (checked by `aapt2`) | `INTERNET`, `RECORD_AUDIO`, `SYSTEM_ALERT_WINDOW`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE`, `FOREGROUND_SERVICE_MICROPHONE`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED` | `INTERNET`, `RECORD_AUDIO` only |
| Components `BubbleService`, `BootReceiver` in the manifest | yes | **no** |
| `BuildConfig.BUBBLE_ENABLED` | `true` | `false` |
| Gradle tasks | `assembleFullDebug` | `assembleLiteDebug` |
| APK | `app/build/outputs/apk/full/debug/app-full-debug.apk` | `app/build/outputs/apk/lite/debug/app-lite-debug.apk` |

**How it is built.** One flavor dimension `edition` in `app/build.gradle.kts`. The shared manifest (`src/main/AndroidManifest.xml`) holds only `INTERNET`, `RECORD_AUDIO`, the activities and the widget. The bubble permissions, `BubbleService` and `BootReceiver` live only in `src/full/AndroidManifest.xml`, which Gradle merges into `full`. `MainActivity` builds the bubble UI only if `BuildConfig.BUBBLE_ENABLED`. The bubble Kotlin classes stay in the common source set (no duplicated logic) and are simply never started in `lite`; they hold no manifest entries, so `lite` declares and can use none of the bubble permissions. `applicationId`, brand and base URL build properties apply to both flavors (`ROBIN_APPLICATION_ID`, `ROBIN_BRAND_NAME`, `ROBIN_BASE_URL`; checked: id `com.example.x`, label `Zed` in the lite APK). Both flavors keep the SAME application id, so on one phone only one of them can be installed (a user moves from `lite` to `full` as an update of the same app).

**Guard.** `scripts/build-android.sh` runs `./gradlew test assembleFullDebug assembleLiteDebug`, prints each APK's permission list with `aapt2` and calls `scripts/check-android-flavor.sh`, which **fails the build** if `lite` has any permission other than `INTERNET` and `RECORD_AUDIO`, or any `service` element, `BubbleService`, `BootReceiver`, `BOOT_COMPLETED` or `foregroundServiceType`; and if `full` is missing one of its eight permissions or two components. The check itself is tested in `tests/ops/test_android_flavor_check.py` (fake `aapt2`, with negative controls). `.github/workflows/android.yml` runs the same script and uploads both APKs.

**Which to submit first [U: founder decision].** Recommendation: submit `lite` first, as the safe fallback, to the production (or first closed/open) track. It carries only microphone and internet, so it should pass review like any voice app, and it gives parents the widget, SOS and in-app voice. Submit `full` as a separate Play track (for example a closed or open testing track for the pilot families) or as a later update of the same listing once the overlay and foreground-service declarations are accepted. The two share an application id, so they cannot be two separate store listings under this id; they need a different `versionCode` per upload (keep `full` above `lite` if `full` is to replace `lite` as an update). If the founder prefers to go straight to `full` for the pilot families, `lite` stays the ready fallback if Play rejects. Whether Play lets two editions with one id sit on two tracks at the same time is [U]; if it does not, the alternative is two application ids (`-Probin.applicationId` for the second build) at the cost of two listings.

**Play declarations for `full` [U: nothing here has been submitted or accepted; wording is a draft for the founder].**
- *Foreground service type.* `specialUse` (subtype text `floating_voice_assistant_bubble`): the app keeps a small, user-visible voice button on screen so an elderly person can ask Robin a question from any app without finding the app; it is a persistent, visible overlay and has no matching standard type. `microphone`: used only for the few seconds after the person taps the bubble, until they tap again, stay silent for 2.5 s or reach 30 s; the type is added then and removed afterwards. A persistent notification ("Robin mic is on") is shown the whole time; the person can switch it off from the app, the notification and the bubble menu.
- *Overlay (`SYSTEM_ALERT_WINDOW`) core functionality.* The product is a voice assistant and safety button for elderly parents who struggle to open apps. The always-reachable mic and SOS is the core function, not an extra. It is set up in person by the adult child, started by a visible switch, never draws over the lock screen, reads nothing from other apps (no accessibility service, no screen reading, no text injection into other apps), has no hotword, and the person can hide it any time.
- *Demo video points.* (1) child setup screen: permission steps in words; (2) turning on "Display over other apps" in system settings; (3) the bubble appearing over another app, drag and snap; (4) tap, speak, listening state, answer shown and spoken; (5) the notification "Robin mic is on" at all times; (6) long-press menu: SOS 2 s hold, Call 112, Hide for now, Turn off for now; (7) parent On/Off switch turning it off and the bubble disappearing; (8) the microphone indicator only while recording; (9) after a reboot, the bubble returns only because the child chose it.
- *Data safety.* Same as the widget (voice recordings, sent to the Robin server for the answer); no analytics, no ads.

**NOT verified.** No device, emulator or Play upload exists: that both APKs install and run on a phone; that `lite` shows no bubble UI on the real screens; that Play accepts either; upgrading from `lite` to `full` on a phone (the setup flow after the update); Play's treatment of two editions with one id on separate tracks. What was verified: both APKs build, the manifests are as the table says (aapt2), 119 JVM tests pass, the guard fails on a bad `lite` (tests).
