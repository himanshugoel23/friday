# Questions for Sarvam (Conversations / Voice Agents + telephony)

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
