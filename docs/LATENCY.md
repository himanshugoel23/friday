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
