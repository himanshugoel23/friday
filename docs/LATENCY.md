# Reply latency: where the pause comes from

The pause the caller hears between the end of their sentence and the start of Friday's reply is the
sum of the steps below (Vobiz leg, `friday/voice/telephony/sarvam.py`; turn loop in `friday/voice/session.py`).

| Step | What happens | Typical size |
|---|---|---|
| 1. End-of-speech wait | The segmenter waits `end_silence_ms = 900` of silence before closing the caller's utterance. | 0.9 s (fixed) |
| 2. STT | Sarvam saaras:v4 REST on the finished utterance. A speculative transcription starts 340 ms into a pause (`EARLY_STT_SILENCE_MS`) and is reused if the caller does not continue, so most of this overlaps step 1. | small when the guess is reused |
| 3. Decide | Playbook engine (scripted calls: no LLM) or GPT (front door and free-form turns). | scripted: ~0; GPT: model time |
| 4. TTS first audio | Cached or pre-rendered line: instant. Uncached line: a Sarvam call (see below). | cached 0 ms; uncached see numbers |
| 5. Playback | Audio is queued to Vobiz (`playAudio`), then one `checkpoint` tells us when it finished. | length of the line |

Steps 1 to 3 are the same for every reply. Step 4 was the biggest variable part.

## Measured TTS numbers (real Sarvam credits, bulbul:v3, speaker ritu, pace 0.9, 8 kHz, dictionary on)

Founder session, 2026-10-10, a ~150-character two-sentence line:

| Path | First audio | Finished |
|---|---|---|
| REST `POST /text-to-speech` | 3.7 to 5.7 s | same (audio arrives only when complete) |
| Stream `POST /text-to-speech/stream` (`output_audio_codec: wav`) | ~1.1 s | ~2.8 s |

Probe run with `deploy/tts_stream_probe.py` (141-character line, 2 runs, from the sandbox):

| Run | REST (first = total) | Stream first audio | Stream total | Audio length |
|---|---|---|---|---|
| 1 | 3345 ms | 487 ms | 1981 ms | 8.6 s |
| 2 | 2138 ms | 426 ms | 1790 ms | 7.6 s |

The stream finishes well before the audio has finished playing, so the call leg does not run dry between chunks
in these measurements. REST time varies run to run (2.1 to 5.7 s); the numbers are network and load dependent,
re-run the probe on the server (Bangalore) for the real figure.

## What streaming changed

- An uncached line is synthesised with the streaming endpoint. The first PCM chunk is sent to Vobiz as soon as it
  arrives; later chunks follow. Replies of several sentences stream each sentence in parallel and play them in order.
- The line is added to the TTS cache when (and only when) it streamed completely, with the same key as
  `synthesize_cached`, so a repeated line is instant next time. A line cut by barge-in or an error is not cached.
- Cached and pre-rendered lines use the old instant path. Billing is per character: no line is synthesised twice.
- Fallback: if the stream fails before any audio, that sentence uses REST. If it fails mid-line, the text after
  the chunk that failed (chunks are the 450-character `chunk_text` pieces) is spoken through REST; the unplayed
  tail of the failed chunk itself is lost, because replaying it would repeat words. A WARNING is logged and the
  call continues.
- Barge-in stops sending chunks and cancels the open HTTP request.
- Switch off with `FRIDAY_SARVAM_TTS_STREAMING=false` (default true).

## Reading the logs

Per streamed line (INFO):

    tts stream first-audio 480 ms, total 1980 ms, chars 141, cached=False

`first-audio` is time from sending the request to the first PCM chunk; `total` is until the whole line had arrived.
A fallback logs a WARNING: `tts stream failed (...) after N bytes; falling back to REST for M chars`.

Per call (INFO, end of call): `call <id> latency p50=...ms p95=...ms over N turns`; a WARNING appears when p95
is over the 1500 ms budget. The per-turn figures are STT + decide + TTS (`friday/voice/latency.py`). For
streamed lines the TTS figure is now the time to first audio (`last_tts_ms`), not the time to finish the line;
it does not include the 0.9 s end-of-speech wait or playback.

## Levers that remain

- End-of-speech wait: 0.9 s for every utterance. A shorter wait for short answers ("haan ji", "nahi") would cut
  step 1 directly, at the risk of cutting people who pause mid-sentence.
- Streaming STT: STT is one REST call per utterance (plus the speculative early call). A streaming STT would
  remove most of step 2 after the caller stops.
- Pre-render more lines while the phone rings (already done for the fixed script lines).

## 2026-10-12: shorter end-of-speech wait for short answers
`UtteranceSegmenter.short_end_silence_ms` (setting `FRIDAY_VOICE_SHORT_END_SILENCE_MS`, default 650, 0 = off): when the
caller's speech so far is 1.5 s or less (a "haan ji", "nahi", a price), the utterance closes after 650 ms of silence
instead of 900 ms, saving about 250 ms on every short turn. Long sentences keep the 900 ms wait, so people who pause
mid-sentence are not cut. NOT tested on a live call: listen for chopped answers on the next test call and set the
value to 0 if it happens. Remaining levers: streaming STT (needs Sarvam's streaming STT API), starting TTS of the
likely next line while the vendor is still speaking.

## 2026-10-12 founder test call: 4.85 s after "haan ji bataiye"
Server log: `llm purpose=call_turn ... out=103 latency_ms=2160` then `p95 turn latency 4852ms (budget 1500)`. The reply was not
recognised by the rules ("bataiye" was not in the confident patterns), so the model was asked. Fixes, in order of generality:
1. **General (all model turns):** `openai_relaxed_call_schema` is now ON: the model writes only the keys it has (`{"intent":"YES"}`,
   ~13 tokens) instead of 11 fields padded with null (~65-100 tokens). Benchmark (this sandbox, gpt-5.4-mini, 20 varied replies):
   p50 824 -> 672 ms, p90 1051 -> 898 ms, 0 repairs. On the 1 vCPU droplet the gain should be bigger (it was 2160 ms there).
2. **General:** LLM connection warm-up (`friday/core/warmup.py`) at runtime start and at `friday livecall` start, so the first call turn does
   not pay a cold TLS handshake (a fresh `livecall` process is cold: likely part of the 2.16 s).
3. **Targeted:** common polite replies ("haan ji bataiye", "ji boliye", Devanagari too) are now confident in the rules (`_CONTINUE`).
4. Still to do: speculative understanding on the early transcript (start the model while the caller's pause is still being timed out,
   saves up to ~0.5 s), streaming STT, a trained small intent classifier (no model call for the closed intent set), and a short
   backchannel word ("ji") while the model works (needs founder audio approval).
Benchmark scripts are one-off (scratchpad); re-measure on the server from `last-run.log` (the `llm purpose=call_turn` lines).

## 2026-10-12 TTS vendor speed check (this sandbox, 6 runs, an 85-char Hinglish line, phone formats)
| Path | First audio p50 | Total p50 |
|---|---|---|
| ElevenLabs Flash v2.5, REST (how our adapter calls it) | 321 ms | 321 ms |
| ElevenLabs Flash v2.5, streaming (ulaw_8000) | 170 ms | 296 ms |
| ElevenLabs multilingual_v2, streaming | 1359 ms | 1412 ms |
| Sarvam REST | 1387 ms | 1387 ms |
| Sarvam stream (in use) | 260 ms | 1282 ms |
So an earlier remark that ElevenLabs would be slower was WRONG for Flash v2.5: it is as fast or faster than Sarvam's streaming, even over REST. Caveats: measured from the sandbox, not the Bangalore droplet (Sarvam is in India, ElevenLabs is not: re-measure on the server); only the free premade voice was timed; multilingual_v2 (better quality) is slow, Flash is the real-time model; quality on Hinglish still has to be judged by ear.

## 2026-10-12 ElevenLabs in the live call (opt-in)
`FRIDAY_TTS_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` switches the call voice (default stays Sarvam). Flash v2.5
streams 8 kHz PCM straight into the call (`ElevenLabsTTS.synthesize_stream`, no resampling); smoke test with the real API: first audio 176 ms
(563 ms on the very first request of a process, connection setup). `FRIDAY_TTS_FALLBACK=sarvam` (default) wraps it in `FallbackTTS`: if
ElevenLabs fails, the line is spoken by Sarvam (Ritu) so the call never drops. Other settings: `FRIDAY_ELEVENLABS_MODEL` (default
eleven_flash_v2_5), `FRIDAY_ELEVENLABS_STREAMING` (default true). Founder-chosen candidates: Zara `OtEfb2LVzIE45wdYe54M`, Neha P `X1aCu8g69vgtNfFwu68G`
(library voices; need the paid plan). The Sarvam pronunciation dictionary does not apply to ElevenLabs; names are already sent in Devanagari.

## 2026-10-12 What a caller actually feels: the "reply gap" (caller stops -> first audio of the reply)
The old per-call report (`latency p50/p95`) only added STT + policy + TTS. It left out the end-of-speech wait and the
send to the phone, so the real gap was longer than the log said (the 4.85 s turn was really about 5.5 s). The call leg now logs
`reply gap N ms (caller stopped speaking -> first audio queued)` on every turn (`SarvamCallLeg.reply_gaps`). Judge speed by THIS number.
Target: under 1 s for every turn, scripted or open.

| # | Block | Today | Fix | Status |
|---|---|---|---|---|
| 1 | End-of-speech wait (silence before we close the utterance) | 650 ms short / 900 ms long | early commit for short complete answers (~340 ms); then semantic end-of-turn on streaming STT | early commit DONE (`FRIDAY_VOICE_EARLY_COMMIT_WORDS`, 0 = off); rest TODO |
| 2 | Speech-to-text after the pause | REST per utterance, started 340 ms into the pause: ~0.5-1 s | Sarvam **realtime streaming STT** (`wss .../speech-to-text-realtime/ws`, saaras:v3-realtime): text is ready as the caller finishes | TODO (biggest single gain, ~0.5-0.9 s) |
| 3 | Understanding by the model | 0.65-1.2 s (was 2.2 s on the droplet) | compact output (DONE), connection warm-up (DONE), speculative start on the early/partial transcript, faster inference host or a small trained intent classifier | partly done |
| 4 | Next line | instant (playbook choice is code) | n/a | OK |
| 5 | Text-to-speech first audio | cached 0 ms; uncached Sarvam 260 ms; ElevenLabs Flash 170 ms | ElevenLabs Flash streaming (DONE, opt-in); pre-render every line incl. likely branches while the phone rings | partly done |
| 6 | Send to the phone (Vobiz queue + network) | not measured | now visible via the reply gap vs. the sum of 1-5 | measure |
| 7 | Anything a script did not foresee | the model answers (call_turn), 1-2 s | stream the model's reply sentence by sentence into TTS (time to first token ~0.3 s), a short pre-approved acknowledgement ("ji, ek second") if it will take longer | TODO |

Why not "hard-code every reply": the scripted path stays for control flow and safety (what Friday may promise), but speed comes from
overlapping the stages (stream the speech in, start the model on the partial text, start the voice on the first words), not from adding
rules per sentence. Early commit and the polite-reply rules only remove waiting where the answer is already obvious.
