# WhatsApp calling: "tap the call button on Friday's WhatsApp" (design only)

Status (2026-10-27): DESIGN ONLY. No code, no real call, no Meta setting changed. Founder ask: HANDOFF 2026-10-27
("support call Friday from WhatsApp"). Public repo: no keys, numbers or personal data (env names only).
Every spoken line here is `PENDING_FOUNDER_APPROVAL` (hear-before-change). Switch: `FRIDAY_WA_CALLING_ENABLED`, default OFF.

Labels: **[V]** verified in Meta docs read on 2026-10-27 (fetched page, link given); **[U]** unverified / third-party / my inference.
Meta pages: [calling overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/),
[user-initiated](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls),
[call settings](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings),
[pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing/).

## 1. What the user sees
The user opens the WhatsApp chat with Friday, taps the phone icon, and a normal WhatsApp voice call rings. Friday answers
as the same voice agent (Ritu on Sarvam), knows who is calling from the WhatsApp number, uses memory and life state, and can
run receptionist-style tasks ("what did I miss?", "call the plumber", "kal ka din kaisa hai"). The user pays nothing extra.

## 2. What Meta gives us (facts)
| Claim | Label |
|---|---|
| Needs a number on **Cloud API** (not the WhatsApp Business app), `calls` webhook field subscribed, `whatsapp_business_messaging` permission, calling switched ON in call settings. This is also slice 0 of our launch. | [V] overview |
| Production needs a daily messaging limit of at least 2,000 unique recipients (test numbers and sandbox are exempt). A new beta number may not qualify at first. | [V] overview |
| **User-initiated calls are free** ("All user-initiated calls are free"). Business-initiated calls are billed per country, in 6-second pulses. | [V] pricing |
| India: user-initiated calling is "available wherever Cloud API is available". The page does not name India; the business-initiated exclusion list is US, Canada, Egypt, Vietnam, Nigeria (India not on it). Confirm on the Cloud API country page and in the spike. | [V] rule, [U] India itself |
| Media: **WebRTC** (default, HTTPS signalling + webhooks, no extra enablement) or **SIP** (needs explicit enablement; with SIP the calling endpoints and webhooks are off). No PSTN bridging by Meta. | [V] overview, call settings |
| Webhook `calls` / event `connect`: call id (`wacid`), `direction: USER_INITIATED`, `session` = SDP **offer** (RFC 8866), optional `deeplink_payload`/`cta_payload`. | [V] user-initiated |
| Actions on `POST <PHONE_NUMBER_ID>/calls`: `pre_accept` (SDP answer, recommended: faster, no clipped first words), `accept` (answer SDP must equal the pre-accept one; start media only after 200 OK), `reject`, `terminate`. | [V] user-initiated |
| We have about 30 to 60 s after `connect` to answer, else the user sees "Not answered" and we get a `terminate` webhook. | [V] user-initiated |
| `terminate` webhook: status COMPLETED/FAILED, start/end/duration only if picked up, `biz_opaque_callback_data` echoed (max 512 chars). | [V] user-initiated |
| Audio is **Opus**; PCMA/PCMU (G.711) can be enabled as extras but add transcoding and bandwidth. | [V] call settings |
| DTMF from the user follows RFC 4733, 8 kHz clock only; no webhook reports digits (digits arrive in the media stream). | [V] user-initiated |
| Calling hours + holiday schedule can be set on Meta's side; the call icon can be hidden (`DISABLE_ALL`) or limited by user country; voicemail (OGG/Opus announcement under 60 s) exists. Clients may take up to 7 days to reflect changes. | [V] call settings |
| Supported from the user's primary phone and iPhone/Android companion devices; **not** WhatsApp Web/desktop. | [V] user-initiated |
| **Caller identity**: the `connect` payload can omit the user's phone number (`from`, `wa_id`) and carry business-scoped user ids (BSUID) instead. Do not assume a number is present. | [V] user-initiated |
| Trickle ICE / candidate exchange is not documented on the page; we must send a complete answer SDP (candidates gathered before we answer). | [V] absence, [U] behaviour |
| Callback permission rules (1 permission request/day, 2/week per pair; revoked after 4 unanswered calls; changelog mentions 100/day from Dec 2025, conflicting). Only matters for business-initiated calls, which are OUT OF SCOPE here. | [V] overview, conflict noted |

## 3. Architecture
```
user taps call
  -> Meta -> POST /webhooks/whatsapp (existing route; field "calls", event connect + SDP offer)
       verify signature (same check as messages) -> WaCallingGate (switch, hours, kill, allow-list, identify)
       reject?  -> POST /calls action=reject (or let voicemail/hours on Meta's side handle it)
       accept?  -> WaMediaEndpoint (aiortc peer connection): set remote offer, create answer
                -> POST /calls pre_accept (answer SDP) -> media connects -> POST /calls accept (same SDP)
  -> WaLeg (new adapter, looks like a SarvamCallLeg to the engine)
       RTP Opus 48k -> decode -> resample to 16k (and 8k for the segmenter) -> existing VAD -> STT -> classifier
       existing TTS PCM -> resample 48k -> Opus encode -> RTP out
  -> call engine (below) -> terminate (POST /calls action=terminate) + terminate webhook closes the record
```

### 3.1 What exists today (read in code)
| Piece | Where | Reuse |
|---|---|---|
| Telephony adapters: Sarvam leg over Vobiz media WebSocket (mu-law 8 kHz both ways); Exotel/Twilio/Plivo disabled | `friday/voice/telephony/{sarvam,media,routing}.py` | the leg pipeline (VAD segmenter -> STT -> audio classifier -> TTS) is provider-agnostic; only framing and REST are Vobiz-specific |
| Audio helpers: mu-law, resample, wav | `friday/voice/audio.py` | add Opus-side helpers only |
| Voice session / policy / safety | `friday/voice/session.py`, `friday/core/safety.py` | unchanged |
| Live engine with `TelephonyPort` (speak / listen / send_dtmf / hangup) and `SarvamLegPort` | `friday/liveagent/{ports,sarvam_adapter}.py` | `WaLegPort` is a second adapter; engine untouched |
| Front door (inbound calls to Friday's number, caller guard, spend/concurrency caps, `InboundCallReceived`) | `friday/voice/frontdoor.py`, `friday/voice/events.py` | the WhatsApp call is a front-door call with channel = whatsapp |
| Receptionist (`claims()`, summary, "what did I miss") | `friday/receptionist/` | reused for the receptionist tasks; a WA call is never a forwarded call |
| Consumer router (calls, savings, memory, life state) | `friday/integration/router.py` | the same brain, same memory, same life state as WhatsApp text |
| WhatsApp channel + webhook | `friday/channels/whatsapp.py`, `friday/api/inbound.py` | add the `calls` field to the webhook parser |

### 3.2 What to add (new package `friday/wacalling/`)
1. `webhook.py`: parse `calls` events (connect, terminate), dedupe by call id, hand to the gate. Fake payloads in tests.
2. `signaling.py`: Graph client for `pre_accept/accept/reject/terminate` with timeouts; one retry; never log SDP bodies (they hold IPs).
3. `media.py`: **aiortc** peer connection (Python, pure asyncio, Opus via libopus/PyAV). One peer per call. Pre-accept first, accept after ICE connected. [U] aiortc compatibility with Meta's SDP (DTLS-SRTP, ICE-lite or full) is the first thing the spike must prove.
4. `leg.py`: `WaCallLeg` (subclass the same base the Sarvam leg uses) + `WaLegPort` for the live engine. Handles barge-in (`clear` = flush the outgoing queue).
5. `gate.py`: switch, hours, kill, allow-list, identification, caps (section 7 to 9).
6. `copy.py`: the few new lines (section 6), all pending.
Alternative media server (LiveKit, Janus, Pion, a SIP-to-WebRTC provider): [U] stronger at scale, but it adds a second process, a TURN/ports story and cost. Do not choose it before the aiortc spike fails.

### 3.3 Capacity on a 1 GB droplet [U]
No measurement exists. Estimate: aiortc Opus decode+encode per call is a few percent of one core; the heavy parts are already ours
(STT/TTS are Sarvam API calls, not local). The Python process plus Silero VAD if on (FRIDAY_VOICE_VAD_BACKEND) is the memory risk.
Plan: 2 concurrent WhatsApp calls on 1 GB as the starting cap (`FRIDAY_WA_CALLING_MAX_CONCURRENT`, default 2), measure in the spike
(RSS, CPU, jitter), then raise. UDP: WebRTC needs outbound UDP and a reachable media path. A public-IP droplet works without TURN [U];
a NATed host (some AWS setups) needs a fixed UDP port range open (set aiortc/ICE port range) and a firewall rule. Meta's media relay
addresses must be allowed; Meta publishes none that I verified.

## 4. Codecs and the 8/16 kHz pipeline
Opus is mandatory on Meta's side [V]; we never enable G.711 (no transcoding win, and it would force us to a worse quality).
Inbound: Opus 48 kHz mono -> PCM16 -> `resample_pcm16` to 16 kHz for STT (Sarvam STT accepts 16 kHz [U]) and 8 kHz where the existing
segmenter/classifier assumes telephony rates. Outbound: Sarvam TTS PCM (22/24 kHz [U]) -> 48 kHz -> Opus, 20 ms frames.
Note: the PSTN leg is 8 kHz narrowband; a WhatsApp leg is wideband, so STT on WhatsApp calls should be BETTER than PSTN, and TTS sounds
fuller. Do not downsample to 8 kHz for the sake of the old pipeline when the STT takes 16 kHz.

## 5. Latency budget (turn = user stops talking -> Friday starts talking)
Rough, not measured. See docs/LATENCY.md for today's PSTN numbers; the spike replaces these with real ones.
| Stage | PSTN (Vobiz) | WhatsApp (WebRTC) |
|---|---|---|
| Network one-way | carrier hop plus Vobiz relay | Meta relay plus our UDP; likely similar or lower [U] |
| Jitter buffer + codec | 20 to 60 ms | 40 to 80 ms (Opus + aiortc buffer) [U] |
| End-of-speech wait (VAD) | 900 ms telephony setting | same code, same 900 ms (tunable) |
| STT final + brain + TTS first audio | unchanged | unchanged |
Expected delta: within about +-100 ms of PSTN. Setup is slower: SDP answer and ICE add about 1 to 2 s before audio, hidden by `pre_accept`
and a first greeting that starts only after `accept` returns 200 (else the first words are clipped [V]).

## 6. Consent and AI disclosure
* The user called Friday on purpose, so this is a user-initiated call [V]; no callback permission is needed. We make NO business-initiated calls.
* First utterance must carry the AI disclosure, same as every Friday call (`disclose` move, never denies being an AI): one short line in
  the user's language, e.g. (**PENDING founder approval, hear-before-change; wording not final**) "Namaste, main Friday hoon, aapki AI assistant."
* Recording: OFF by default. If the founder wants recordings or transcripts for quality, a separate spoken consent line is needed first
  (Meta recording/transcription is currently free but not required) [V pricing]. Transcripts are stored masked like other calls.
* Third parties: a WhatsApp call is between Friday and the account holder only, so no third-party consent issue. A speaker-phone bystander is
  handled by the existing "is this a good time / who is this" lines.
* No sample audio is produced by this design; before any line ships the founder hears it.

## 7. Identifying the caller
1. Preferred: `from`/`wa_id` in the `connect` payload -> `normalize_phone` -> the user table (same lookup as WhatsApp text).
2. If only BSUID is present [V it may be]: map BSUID -> user from the last WhatsApp message webhook that carried both (store the pair at
   chat time; new table column or a small mapping row, see section 11). No mapping -> treat as unknown.
3. **Unknown caller** (no user, or ambiguous): Friday still answers only when `FRIDAY_WA_CALLING_UNKNOWN` = `front_door` (default `reject`).
   With `front_door` she plays the existing front-door persona (explains what Friday is, offers WhatsApp sign-up), saves no memory, runs no
   tasks, and has the short cap. Default is reject because an unidentified call cannot be tied to a user's data.
4. The caller is never trusted by what they SAY on the call: a WhatsApp number identifies the account, not the person holding the phone.
   Sensitive actions (a call to someone, spending, memory deletion) keep the existing PIN/approval rules; the voice call can only PROPOSE and the
   approval lands as a WhatsApp button, exactly as for calls today.

## 8. Hours, off switch, kill switch
* `FRIDAY_WA_CALLING_ENABLED` (default false): master. Off = the webhook ignores `calls` events and we send nothing; do not even set
  calling to ENABLED at Meta, so no call icon appears.
* Kill switch: `friday pause` (existing `var/PAUSED`) and `FRIDAY_CALLS_ENABLED=false` both make the gate `reject` at once; a new
  `friday wa-calling off` flips the setting and also calls Meta's settings API to set `call_icon_visibility = DISABLE_ALL` [V field].
* Hours: our own gate decides first (`FRIDAY_WA_CALLING_HOURS`, default 24 h while the founder tests); optionally mirror them to Meta
  call hours so the icon shows unavailable [V]. Note Meta says to turn call hours off when voicemail is on [V].
* Outside hours or at capacity: `reject` + the existing WhatsApp text "call me back later" (a text, not a voicemail, in v1).
* Allow-list: during beta only the founder's allow-listed number is accepted (`FRIDAY_WA_CALLING_ALLOW`, names of env only); everyone else is
  rejected. Same rule as CLAUDE.md "no real calls except allow-listed founder number".
* Caps: max concurrent (front-door guard reused), max call length (`front_door.max_call_s`), per-user daily minutes, spend cap.

## 9. Doctor checks (`friday doctor`, see docs/DOCTOR.md)
Add to `friday/ops/doctor.py` (next to the existing switch lines): switch state printed ON/OFF; webhook field `calls` subscribed; calling
ENABLED at Meta for the number (`GET` call settings); number is on Cloud API; messaging limit >= 2,000 (WARN if not); SDP/ICE self-test
(loopback aiortc offer/answer, no network); outbound UDP reachable (WARN only); `aiortc` importable; allow-list non-empty while beta;
call icon hidden when the switch is OFF (WARN if visible). All offline-safe: live checks only with `--live`.

## 10. Config summary (names only)
`FRIDAY_WA_CALLING_ENABLED` (false), `FRIDAY_WA_CALLING_ALLOW`, `FRIDAY_WA_CALLING_HOURS`, `FRIDAY_WA_CALLING_MAX_CONCURRENT` (2),
`FRIDAY_WA_CALLING_UNKNOWN` (`reject`), `FRIDAY_WA_CALLING_RECORD` (false). Reuses the existing Cloud API token and app-secret env names.

## 11. Migration
Probably one small one, only if the BSUID mapping needs persistence. Next free revision after `0012_receptionist_spam` is **0013**, but other
designs may also claim 0013+; take the next free number at build time and rebase the `down_revision`. Content: `wa_user_ids(user_id,
bsuid, parent_bsuid, first_seen)` and `wa_calls(call_id pk, user_id null, started_at, ended_at, duration_s, status, outcome)` (no SDP, no
audio, no transcript text; masked transcript goes through the existing call store). If the founder allows phone-number-only identification
in v1, no migration is needed for the spike.

## 12. Receptionist-style tasks on this channel
The call enters the same consumer router as text, with `channel="whatsapp_call"`: memory ("tumhe kya yaad hai"), life state ("mera din"),
"what did I miss?" (spoken short version, already designed in RECEPTIONIST.md), and "call X" (proposal then WhatsApp approval). Task work
that takes time ("ek minute", hold) uses the existing wait lines; long results are sent as a WhatsApp message and the call says so.
The receptionist forward path (carrier conditional forwarding to Vobiz) is separate and not touched.

## 13. Testing
* Offline fakes: fake `calls` webhook payloads (connect/terminate/BSUID-only/missing number), `FakeGraphCalls` recording pre_accept/accept/
  reject/terminate order, `FakeMediaEndpoint` feeding scripted PCM and capturing output, reusing the existing STT/TTS fakes and
  `friday.liveagent.simulation` personas through `WaLegPort`.
* Invariants: gate order (kill > switch > allow-list > hours > capacity); pre_accept before accept; accept SDP equals pre_accept SDP;
  media never starts before accept 200; terminate sent exactly once; disclosure first; unknown caller never reaches memory; 30 to 60 s answer
  timeout handled; duplicate `connect` ignored; OFF switch = zero Graph calls.
* **Real-call spike (founder approval required, founder's allow-listed number only)**: (1) Meta test/sandbox or the production number with calling
  enabled; (2) call in from WhatsApp on the founder phone; (3) answer with a fixed tone, then a fixed greeting; (4) measure ICE time,
  first-audio delay, clipping, RSS/CPU, one-way delay by a clap test; (5) then full conversation with the real engine; (6) confirm India
  availability, whether `from` is present, and the exact ICE behaviour. Spike output is added to this doc as [V] facts. No other number is called.

## 14. Risks
| Risk | Mitigation |
|---|---|
| India not enabled / not stated on Meta's page [U] | spike first; fall back to "WhatsApp voice note" (A2 in VOICE_AGENT_COVERAGE.md) |
| 2,000-recipient messaging limit blocks a small beta number [V] | test number / sandbox for the spike; plan the tier upgrade |
| aiortc vs Meta SDP mismatch, or ICE needs open UDP ports [U] | spike; keep a media-server option (LiveKit/Janus) as plan B |
| 1 GB droplet CPU/RAM under audio [U] | cap at 2, measure, move up a size |
| Missing phone number (BSUID only) [V] | mapping from earlier chat, else unknown-caller path |
| Clipped first words / long silence [V] | pre_accept, greet only after accept 200 |
| Meta changes calling API fields [U] | one signalling module, contract tests on fake payloads |
| Hallucinated promises on voice | same bounded engine, guards, approval-by-WhatsApp |
| Public-repo leakage (SDP holds IPs) | never log SDP; redact in tests |

## 15. Build order (rough human-day guesses, not commitments)
| # | Step | Size |
|---|---|---|
| 0 | Prereqs: number on Cloud API, calling enabled on a test number (founder/Meta) | 0.5 to 1 day (partly waiting) |
| 1 | Spike A: aiortc answers a real WhatsApp call, plays a tone (no engine) | 2 days |
| 2 | `wacalling` webhook + signaling + gate + fakes + tests | 3 days |
| 3 | `WaCallLeg`/`WaLegPort` + audio resampling + engine hookup, simulation personas | 3 days |
| 4 | Router channel, identification, BSUID mapping + migration, hours/kill/caps, doctor | 2 days |
| 5 | Spike B: full conversation on the founder number; latency and capacity numbers; fix | 2 to 3 days |
| 6 | Copy approval (hear-before-change), docs, beta allow-list widening | 1 day + founder time |
Total about 11 to 14 days of one engineer; the aiortc/Meta SDP unknown is the main swing.

## 16. Founder decisions (max 6)
1. **Go for the 2-day spike now, or wait until after the B to G queue?** Recommend: spike now (it is cheap and answers India/aiortc/BSUID).
2. **Media: aiortc inside the Friday process, or a media server?** Recommend: aiortc first, media server only if the spike fails.
3. **Unknown callers: reject, or answer with the front-door persona?** Recommend: reject in beta, front-door later.
4. **Which number: the future production number, or a Meta test number for the spike?** Recommend: a test number (avoids the 2,000-limit block).
5. **Recording/transcripts of these calls?** Recommend: no recording; masked transcript only, as today.
6. **Opening line (AI disclosure) wording and voice?** Recommend: approve after you hear a sample from Ritu; nothing ships before.
