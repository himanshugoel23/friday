# Sarvam / Vobiz telephony: status, questions, first live call

Friday's brain must decide every turn and `friday.core.safety` must gate every utterance and
key press, so we integrate in **raw media streaming** mode: the call audio goes to our
WebSocket, we use Sarvam STT/TTS on our side. The adapter is `friday/voice/telephony/sarvam.py`
(capability matrix in its docstring). The docs were not reachable while writing it, so each
point below is a `TODO(<doc page>)` in code. Please confirm, in this order of importance.

## Blockers (decide whether we can launch on Sarvam only)
1. **Raw audio to our server.** Can a Sarvam-rented number, or a BYO carrier via Vobiz, stream
   bidirectional call audio to a WebSocket we host (mu-law 8 kHz or PCM), with us playing audio
   back? Message formats (`start` / `media` / `playedStream` / `dtmf` / `stop`), checkpoint /
   mark events to know playback finished, and how a barge-in clears queued audio.
   _(docs.sarvam.ai/conversations/deploy/deploy-with-code, /deploy/telephony/vobiz)_
2. **If not (1): a per-turn hook.** Does Conversations offer a custom-LLM / per-turn webhook where
   Sarvam sends each transcribed user turn and speaks exactly the text we return (no agent-side
   rewriting, no agent-initiated turns)? Latency budget per turn, and can we veto / replace a
   turn before audio plays? This is mode (b) which we have NOT built.
3. **Outbound API.** Instant Outbound: request fields (from, to, ring timeout, max duration,
   answer / hangup callbacks, machine detection), response ids, authentication, status values
   and hangup causes (busy / no answer / rejected / blocked-as-spam / invalid number).
4. **Numbers.** How many outbound caller IDs per account? Can we choose the caller ID per call
   (we rotate a pool of Indian 10-digit numbers with sticky assignment per business)? Are
   rented numbers allowed to originate at business-hours volumes, and what is the call-back
   behaviour (does a call to a retired number still reach our inbound webhook)? DLT / TRAI
   constraints for voice from these numbers, and CNAP / branded caller-name support.

## Capabilities we need (each has a defined degrade path today)
5. **DTMF.** Send DTMF (REST or in-band over the stream)? Receive DTMF events? (We fall back to
   in-band tones; IVR tasks decline honestly if neither works.)
6. **Concurrency and rate limits.** Max simultaneous calls, calls per second, per-account and per
   number. What is the error when exceeded? (We cap with `provider_concurrency["sarvam"]`.)
7. **Transfer / conference.** Can we dial the user into a live call (warm transfer), with a whisper
   to the user first, and keep Friday on the line silently? Or only blind transfer? (Default OFF:
   BRIDGE_USER degrades to "ask the user to call back with the ticket context".)
8. **Recording.** Start / stop recording via API, both-leg or mixed, URL format, expiry, download
   authentication, **and a delete API** (DPDP erasure). Region (India) of storage.
9. **Inbound.** Webhook payload for a call to our number (caller ID, dialled number, call id);
   answer vs reject; how to detect a missed call (caller hung up while ringing) and its ring time.
10. **Answering-machine / voicemail detection** and early-media / hold-music behaviour (we classify
    hold music locally and skip STT).

## Commercial / compliance
11. Pricing per minute for stream-only (no hosted agent), STT and TTS minutes billed separately?
12. Data residency, retention and DPA; are call audio / transcripts stored by Sarvam when we use
    the stream only? Can storage be disabled?
13. AI-caller disclosure and spam-label policy for outbound calls from your numbers; known
    carrier-block thresholds and how blocks are reported (we map SIP 603 / 607 / 608 and
    "spam / block" reasons to the number-health score).

## Update 2026-10-08: the number is a Vobiz BYO number
The founder's calling number was created through **Vobiz** (a Bengaluru, +91 80 style DID). That is the
"BYO carrier" route this adapter was built for. So questions 1 (raw audio stream to our WebSocket), 3 (outbound
API), 4 (numbers, caller ID per call, DLT/TRAI), 5 (DTMF), 6 (concurrency), 7 (transfer), 8 (recording and delete),
9 (inbound and missed calls) and 10 (voicemail detection) are mainly for **Vobiz** (the carrier/Voice API).
Questions 2, 11 and 12 (per-turn hook, STT/TTS pricing, data retention for speech) stay with **Sarvam**.
Credentials go in `SARVAM_TELEPHONY_AUTH_ID` / `SARVAM_TELEPHONY_AUTH_TOKEN` (the Vobiz Auth ID and Auth Token).
Vobiz must be able to reach a public HTTPS URL (`FRIDAY_PUBLIC_BASE_URL`) for the answer/hangup webhooks and the
media WebSocket (`/voice/sarvam/media`), so a live call test needs a deployed or tunnelled server.

## Update 2026-10-08 (later): there is NO direct Vobiz account
The founder confirmed there is no separate Vobiz login: the number (+91 80 7158 2175) exists only inside Sarvam's
console (Voice Agents > Deploy > Phone numbers, via a Sarvam "Vobiz connection"). So the direct-Vobiz route
("Route A": Vobiz Auth ID/Token, Plivo-style API, media WebSocket to our server) is NOT available unless Sarvam gives
us those credentials or an equivalent stream endpoint. The only confirmed way to place calls is Sarvam's platform:
`POST https://apps.sarvam.ai/api/scheduling/v1/orgs/{org_id}/workspaces/{workspace_id}/campaigns` (header
`X-API-Key`; body app_config{app_id, app_version, app_type:"agent"}, connection_configs[{connection_id, phone_numbers}],
attempts_per_second ...) which runs a Sarvam-HOSTED agent.
DECISION PENDING (do not build blind): we need to learn whether a Sarvam agent supports (1) a custom LLM / per-turn
webhook so OUR brain and safety guard decide every turn, or (2) raw audio streaming to our server on this number, or
(3) credentials to the underlying Vobiz connection. Until one of these is confirmed, live calls must not be placed
for booking/commitment tasks, because a hosted agent's speech cannot be gated by friday.core.safety.

## Status after checking the docs (2026-10-08, via search summaries; direct fetch is blocked)
Confirmed: the direct-Vobiz raw-stream route (Sarvam guide "Build a Voice Agent using Vobiz");
base URL `https://api.vobiz.ai/api/v1`, `X-Auth-ID` / `X-Auth-Token`, `POST /Account/{id}/Call/`
(from, to, answer_url, answer_method -> `call_uuid`), `<Stream bidirectional="true">`, stream events
`start` / `media` / `playedStream` / `clearedAudio` / `stop` and commands `playAudio` / `checkpoint` /
`clearAudio`; transfer to PSTN or SIP is supported. Answers to questions 1, 3 (mostly), 7 (transfer,
not 3-way) are therefore "yes". **Still open:** the DTMF and Record request bodies (5, 8), the live
transfer request shape (7), hangup causes and where the hangup URL is set (3, 13), L16 byte order,
concurrency limits (6), delete-recording API (8). Each is a `TODO` in `sarvam.py`.

## First live call: your own phone (+91 80 7158 2175 is the Vobiz number)
Set before starting (secrets only in the environment): `FRIDAY_MODE=live`,
`FRIDAY_PUBLIC_BASE_URL=https://<public https host>` (a tunnel is fine),
`SARVAM_TELEPHONY_AUTH_ID` / `SARVAM_TELEPHONY_AUTH_TOKEN` (Vobiz console, Voice -> Voice
Applications -> Overview), `FRIDAY_SARVAM_CALLER_IDS=+918071582175` (comma list), `SARVAM_API_KEY`,
`FRIDAY_SECRET_KEY`, `FRIDAY_OBJECT_STORE_URL` (or run with the simulator store for a dry run).
1. **Vobiz account:** turn call queuing OFF (queued outbound calls are held and can be marked
   failed). In the Vobiz Application for the number, set the answer URL to
   `https://<host>/voice/sarvam/inbound?token=<sarvam_token(secret, "inbound")>` (and the hangup URL
   to `/voice/sarvam/hangup` with the same token); print the token with
   `python -c "from friday.voice.telephony.sarvam import sarvam_token as t; print(t('<FRIDAY_SECRET_KEY>','inbound'))"`.
2. `uv run friday check` must pass; start `FRIDAY_ROLES=api,task,voice` and watch the logs
   (phone numbers are masked).
3. **Outbound to you:** ask Friday on the chat channel to "call me and ask what time it is" with your
   own mobile as the target. Expect: it rings, the FIRST words are the AI disclosure, she mirrors your
   language, answers honestly if you ask "are you a bot?", never speaks a digit run you did not approve.
4. **Hold / DTMF:** ask for a call to a toll-free IVR you own or a friend's test line; press-test one
   menu key (the call log shows `DTMF:` turns). If the IVR ignores it, note whether the in-band
   fallback logged "sending in-band tones".
5. **Inbound / call-back:** hang up, then call +91 80 7158 2175 from your mobile: you should hear the
   Friday inbound greeting; let a second call ring out to verify the missed-call event.
6. **Transfer:** run a care-style task and say "connect me": the call should hand over to your
   phone; if Vobiz refuses, the log shows `BRIDGE FAILED` and the user gets a call-back pack.
7. **Recording and erasure:** the report has a recording link; "delete everything" must delete it.
Stop on any failure: `FRIDAY_MODE=simulator` restores the safe default.
