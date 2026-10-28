# TTS health gate (2026-10-28 incident: Sarvam HTTP 402 / 429, calls cut at pick-up)

Code: `friday/voice/tts/health.py` (breaker, last-error memory), `cache.py` (prerender), `voice/session.py` (call gate, mid-call), `tasks/engine.py` (chat line), `ops/doctor.py` (line).

- 402 / quota opens the breaker at once (cool-down 300 s, doubling, cap 30 min). 429 / 5xx open it after 3 in a row (5 s, doubling). One probe after the cool-down; any success resets. Logged once per state change.
- While open: prerender makes no vendor call; no outbound call is placed (`CallResult.error = tts_unavailable`, task fails with the line below, no retry); cached lines still play.
- Mid-call TTS failure: cancel line only if already cached, hang up, result `error = tts_failed` (outcome FAILED).
- State file `var/tts_health.json` (`FRIDAY_TTS_HEALTH_FILE`), read by `friday doctor` (no network).

## New chat lines for founder approval (no spoken lines changed)
1. Refusal: "Voice is temporarily unavailable on my side, so I have not called. I will tell you when it is back."
2. Recovery (sent once the first TTS success follows a refusal; added so line 1 is a true promise): "Voice is back. You can ask me to make that call again."
