# Reply speed on calls: how the pause happens, how to measure it, what to change

Founder target (2026-10-10): after the business speaks, Friday's reply starts **within 1 second**. First test call: 5+ seconds after
"yes", the salon said "hello, hello, hello". This file keeps the analysis so nobody redoes it. Status of fixes: `HANDOFF.md` section 7.

## Where the time goes (Vobiz leg, `friday/voice/telephony/sarvam.py`)
What the caller perceives = **end-of-speech wait + reply gap**.
1. **End-of-speech wait**: `SarvamCallLeg._segmenter.end_silence_ms = 900`. We wait out a pause before deciding the person finished
   (phone speech has pauses; 900 ms avoids cutting people mid-sentence). Floor of the whole reply time.
2. **STT**: early (speculative) speech-to-text starts after 340 ms of silence (`EARLY_STT_SILENCE_MS`), so most of it overlaps step 1.
3. **Decide**: the playbook engine (`friday/playbooks/engine.py`). Rules first (`understand.heuristic`); the LLM is called only when the
   rules are not confident (`playbooks_llm_mode = auto`). LLM call = 2-5 s. "yes"/"haan ji" never need it; before 2026-10-10 a bare price
   ("300", "teen sau", "200 se 300") did.
4. **TTS**: lines are synthesised with Sarvam. Pre-rendered lines come from the cache instantly; an uncached line costs ~1-2 s per
   sentence (first sentence plays while the rest is made). The cache is warmed while the phone rings (`static_utterances` +
   `TTSCache.prerender`, started in `CallRunner._start_prerender` right after dialling).
5. **Playback start** over the Vobiz stream (`_play_audio`).

## Causes found in code (2026-10-10, before any server log was read) and the fix
| Cause | Fix (commit `a435f2a`) |
|---|---|
| Warm-up ran one line at a time, in file order; the lines needed after "haan ji" were at positions 21+ of 39, not ready when the salon picked up | `static_utterances` returns call order (disclosure, then steps breadth-first, then shared answers, then the rest); `prerender` runs 3 at a time |
| Bare price answers went to the LLM | `slots.price_details(bare_ok=True)` at steps S3/S3r/S3b |
| No trustworthy per-turn timing (the old `tts_ms` could include playback; reports were only p50/p95) | one INFO line per turn: `reply gap X ms after the 900 ms end-of-speech wait (stt, decide, tts-first-audio; whole line cached=...)` |

## How to measure (after any test call, on the droplet)
```bash
journalctl -u friday --since "10 min ago" --no-pager | grep "reply gap"
```
Read each line: `stt` should be small (early STT overlapped), `decide` small unless the LLM ran, `tts-first-audio` small when
`cached=True`. Perceived pause ~= 900 + the gap. If `decide` is large -> the LLM ran: find the reply text and add a heuristic rule.
If `tts-first-audio` is large and `cached=False` -> that line was not warmed: add it to the warm list (or the input changed).
If everything is small but the pause is still > 1 s -> the 900 ms wait is the problem.

## Levers not yet pulled (do only after reading real `reply gap` numbers)
- **Shorter end-of-speech wait for short answers**: when the early-STT guess is a short confirmation ("haan ji", "yes", "ji", "hello"),
  close the utterance at ~500 ms instead of 900 ms. Risk: cutting someone who pauses mid-sentence; keep 900 ms for everything else.
- **Speculative reply**: when the early guess is confident, pre-synthesise the likely next line during the wait.
- Warm only lines reachable for this call's inputs (skip negotiation/stylist lines when those inputs are empty) to shorten the warm-up.
- Keep the Sarvam TTS concurrency at 3 unless the vendor rate-limits (`TTSCache.PRERENDER_PARALLEL`).
- A 1 GB droplet can be CPU/RAM-starved during a call; check `uptime`/`free -m` if numbers look random.
