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

## 2026-10-12 Streaming speech-to-text: what we measured and what was built (opt-in)
Measured from the sandbox, same clips (a "haan ji bataiye", a price, a time, a long question), seconds after the caller stopped:
| Path | Text available at |
|---|---|
| Sarvam REST (today; spec starts 340 ms into the pause, ~450-550 ms call) | ~850-900 ms |
| Sarvam realtime stream, final | ~780-900 ms (its partials keep drifting until ~730 ms; `language_code=auto` even turns Hindi partials into English) |
| ElevenLabs Scribe v2 realtime, commit (vad 0.3 s) | 670-890 ms |
| ElevenLabs realtime, stable partial acted on by the leg | ~200-600 ms when partials exist (2 of 4 clips), else the commit |
So streaming is NOT a 1 s fix by itself: the typical gain is ~0-300 ms, up to ~650 ms on some turns. It is built because it is the base for the next steps.
Built: `friday/voice/stt/{sarvam_stream,elevenlabs_stream,stream}.py` (provider-agnostic client; never raises; falls back to REST when unhealthy) and
`SarvamCallLeg` integration (audio forwarded as mu-law 8 kHz; a partial unchanged for `FRIDAY_VOICE_STREAM_STT_STABLE_MS` (220) on a short answer
(<= `FRIDAY_VOICE_EARLY_COMMIT_WORDS` words) is acted on at once, otherwise the commit; own-voice echo ignored; hold music and forced cuts stay on REST).
Switches (default OFF): `FRIDAY_VOICE_STREAM_STT=true`, `FRIDAY_VOICE_STREAM_STT_PROVIDER=auto|elevenlabs|sarvam` (auto = ElevenLabs if its key is set),
`FRIDAY_VOICE_STREAM_STT_LANGUAGE=hi-IN` (fixed on purpose; an English-only call should keep the REST path), `FRIDAY_VOICE_STREAM_STT_SILENCE_MS=300`.
Compare with the `reply gap` log lines, stream on vs off, on the same script.
What is left for <1 s on every turn: (a) start the model on the stable partial BEFORE the commit (speculative understanding: hides ~0.65 s of the
model call), (b) a faster inference host or small intent classifier, (c) stream the model's words into the voice, (d) a short acknowledgement
("ji") while a slow turn works (needs founder audio).

## 2026-10-12 Measured FROM the Bangalore server (deploy/latency_probe.sh) and what it changed
| What | From the server |
|---|---|
| OpenAI tiny completion (gpt-5.4-mini, no reasoning) | 1.3-1.5 s first byte (0.65 s from a US machine); TCP only 18 ms: it is the route/host, not the connection |
| ElevenLabs Flash TTS stream first byte | ~0.27-0.5 s |
| Sarvam TTS stream first byte | ~0.10 s (faster than ElevenLabs from India; the earlier US-side comparison was backwards for this server) |
The live call showed the same: call_turn model call 2161 ms (out=28 tokens) -> reply gap 3637 ms.
**Fix (opt-in): `FRIDAY_LLM_CALL_TURN_PROVIDER=sarvam`** routes ONLY the call-turn job (understanding the vendor's reply) to Sarvam's India-hosted
`sarvam-105b-conversations` (`/v1/chat/completions`; `/v2` needs beta access, `sarvam-105b` is a reasoning model and returns empty answers at small token
budgets). Benchmark on the playbook intent task: 10/10 correct with json_schema, p50 ~455 ms from the US (expect far less from Bangalore). Falls back to OpenAI on any
Sarvam error/timeout (`FRIDAY_SARVAM_LLM_TIMEOUT_S`, default 3 s). `friday/brain/sarvam_llm.py`, `RoutedLLM`.
**Streaming STT with ElevenLabs is NOT accurate enough on real phone speech** (it heard "जी यह उधर है" for "haan ji bataiye"; Sarvam REST heard it correctly):
keep `FRIDAY_VOICE_STREAM_STT=false` until both are compared on recorded real audio.

## 2026-10-12 21:39 live test call (Zara voice, Sarvam for call turns, streaming STT OFF): first sub-second replies
`llm sarvam model=sarvam-105b-conversations ... latency_ms=305` (the same job took 2161 ms on OpenAI from this server). Reply gaps (caller stopped -> first audio queued): 624 ms, 779 ms,
then 31 ms for a turn that needed no new caller speech; call summary `latency p50=269 ms p95=577 ms over 2 turns`; 7 turns, 24 s, no warnings. 3 measured turns only: repeat on a full
script (price, slot) before calling it fixed. Open: the model returned 103 output tokens (full schema); a leaner prompt/schema may save another ~50-100 ms.

## 2026-10-21: speculative understanding, streamed model replies, trained intent classifier (built; ALL THREE OFF; measured offline only)
Founder ask (21 Oct): cut the reply gap without touching a single spoken word. Each feature has its own switch, default OFF,
and with the switches off the code path is the old one (tests: `tests/latency/test_switches_off.py`). Nothing here has been
heard on a real call. Code in `friday/latency/` (speculative, streaming, adapters, simulator) and
`friday/playbooks/classifier.py` + `friday/learning/classifier_*.py`; tests in `tests/latency/`.

| Switch (env) | Default | What it does |
|---|---|---|
| `FRIDAY_VOICE_SPECULATIVE_UNDERSTANDING` | false | Scripted calls: start the understanding (rules, classifier, model) on the early REST transcript or a stable streaming partial while the pause is still timed out. |
| `FRIDAY_LLM_STREAM_TO_TTS` | false | Free-form (model-written) turns: speak sentence 1 while the rest of the reply is still being written. |
| `FRIDAY_INTENT_CLASSIFIER` | false | A small trained classifier answers the common replies the rules are unsure of, so no model call. |
| `FRIDAY_INTENT_CLASSIFIER_THRESHOLD` | 0.9 | Minimum confidence for the classifier to answer (0.5 to 1.0). Below it: rules + model as before. |

### 1. Speculative understanding (`PlaybookPolicy.speculate`, `friday/latency/speculative.py`)
- The call leg hands the early transcript (or a streaming partial unchanged for 150 ms, `SarvamCallLeg.SPECULATE_STABLE_MS`) to the
  policy through `early_text_hook`. The policy builds the same model question it would ask at the commit and starts it.
- At the commit the guess is REUSED only if the final text equals it (case, punctuation and spacing ignored; a different digit is a different
  text), in the same step and after the same Friday line. Otherwise it is dropped and a fresh call runs.
- Never acts early: the guess is a pure function that returns an `Understanding`. The script does not move, nothing is learned, recorded or said
  until the normal path runs after the commit (test: state snapshot before/after is identical).
- At most ONE speculative call per turn (a cancelled or wrong one still counts, so no second guess). Skipped when the rules are already
  confident, when the classifier will answer, for a stop request, with `llm_mode=never`. Cancelled when the caller keeps talking (loud again),
  on barge-in / Friday starting to speak, on a changed partial, on a forced cut or hold, and at the end of every turn.
- Only scripted (playbook) calls: the free-form brain policy has no `speculate`, so the hooks are never attached.
- Honest limit: with REST speech-to-text the early text is ready at about 340 + 500 ms, AFTER the 650 ms short-answer wait, so there is nothing
  to gain on short answers and about 60 ms on long ones. The gain comes with streaming speech-to-text (partials exist while the caller is still
  finishing): about 70 ms on short answers and about 350 ms on long (more than 6 words) ones in the simulator. The brief's "about 0.6 s" is the upper end; it needs a model call
  of about 0.65 s and a long answer. On the Sarvam call-turn model (about 300 ms) the saving is smaller.

### 2. Streamed model replies (`FridayBrain.next_call_action_streamed`, `friday/latency/streaming.py`, `stream_adapters.py`)
- OpenAI and Sarvam chat-completions streaming adapters (`OpenAIChatStream`, `SarvamChatStream`) behind the `StreamingLLM` interface, and a
  `FakeStreamingLLM` for tests. `streaming_for(llm)` picks the client that would serve `call_turn` (Sarvam when `RoutedLLM` routes call turns
  there). The Anthropic client and the offline fake have no adapter: those runs use the old path.
- The model still writes the same JSON action. `JsonFieldStream` pulls the `text` field out as it arrives, `SentenceSplitter` cuts it at
  `. ! ?` and the Hindi danda (numbers like 10.30 stay whole, fragments under 14 characters are merged, a piece over 90 characters is cut at a comma), and each sentence goes
  to the voice only after the guards.
- Guards per sentence = the existing whole-reply guards applied to ONE sentence (`guards.to_call_action`): money promises, commitment wording,
  ungrounded prices and times, secrets / long numbers, claims to be human; plus "no repeated line" per sentence (`RepeatGuard`: the sentence was
  already in each of her last two turns, or earlier in this reply). The first failing sentence stops the stream (the model request is cancelled),
  nothing after it is spoken, and the safe fixed line the guard produced is used.
- Speech starts only once `type` is known to be `say`. Any other action (hang up, ask the user, press keys) is collected and handled by the
  ordinary guards with no second request.
- Calls that must not commit (a commit-type task without approval or delegation) are never streamed.
- Fallbacks: no adapter or a stream error before the first sentence = the old non-streaming call (same words, same guards). An error after the
  first sentence ends the reply there and the call listens; words are never replayed. Barge-in stops the remaining sentences.
- The call session speaks the sentences one by one through the leg and records ONE Friday turn at the end, so the repeat rule still sees one line.
- NOT wired: the front door (scripted lines, no model-written text on the live path) and the W2 live-agent line model (`LineModel.generate` returns
  a whole line that `check_line` must see before it is spoken; it needs its own change). `stream_to_voice` is generic and ready for them.

### 3. Trained intent classifier (`friday/playbooks/classifier.py`)
- Pure Python, no libraries: multinomial naive Bayes over hashed word 1-2-grams and character 2-5-grams (65,536 buckets), one JSON file
  (`friday/playbooks/learning/intent_classifier.json`, about 245 KB) and a version file next to it (`intent_classifier.version.json`: data hash,
  model sha256, counts per source, cross-validation table, held-out metrics, gate verdict). No randomness in training: same data, same bytes.
- Used in `PlaybookPolicy._understand_raw` ONLY when: the switch is on and a gate-passed model loads, the hard rules (stop, secret, rude, AI question)
  did not fire, the rules are not confident, confidence >= threshold, the intent carries no value to extract (no price / time / name / number /
  advance: `SAFE_INTENTS`), and the playbook step allows that intent. Everything else takes the rules + model path unchanged.
- Training data (repo only, never `var/`, never real calls): the TRAIN share of `labels.yaml` (a fixed 60% by content hash), the `(step, text, INTENT)`
  rows in `tests/playbooks/`, persona replies from the playbooks labelled by the rules only where the rules are confident, and a deterministic
  synthetic augmentation (`friday/learning/synth.py`: hand-written Hinglish / Hindi / English templates x politeness words, numbers, times, names). 3,318 sentences in
  total (75 labels, 42 test rows, 296 persona, 2,905 synthetic). The other 40% of `labels.yaml` (50 sentences) is the HELD-OUT evaluation set, never trained on; any training
  sentence that equals a held-out one is dropped.
- `uv run friday learn train-classifier [--dry-run] [--threshold X]`: picks smoothing, confidence sharpness and the threshold by 5-fold cross-validation on the
  gold training sentences (never on the held-out set), trains, scores on the held-out set, and applies the REGRESSION GATE. It writes the model and the version file only if
  the gate passes: held-out precision at the threshold >= 98%, at least 10 answers (so that figure means something), live-path accuracy not below the rules baseline,
  and not worse than the model already in the repo on the same set. A refused model is never written (tested).
- `uv run friday learn eval-classifier [--model PATH] [--all-labels]`: accuracy per intent, confusion pairs, comparison with the rules baseline, the gate verdict.
- REAL NUMBERS (held-out 50 sentences, threshold 0.9, data hash `dc098278eb5d2891`):
  classifier alone 86.0%; rules baseline 74.0% (the offline "model" path is the same rules, so rules + model could not be measured separately);
  live path (rules, then classifier, then model) 80.0%. The classifier answered 22 of the 50 (44%), all 22 right: precision 100%, but the 95% interval lower bound
  is only 85%, because 22 answers cannot prove 98%. Cross-validation on the training gold sentences gave 98.1% precision at 0.9 (53 answers).
  Where it matters for latency (rules NOT confident, so a model call would have been made): 3 of the 50 sentences (6%), classifier right 3, rules right 0.
  Weakest held-out intents: YES (33%: "ji haan ho jayega" reads as a free slot to both the rules and the classifier), GIVES_STYLIST, OFFERS_SLOTS, GIVES_TIME, PRICE_RANGE
  (value intents, which the classifier never answers on its own). So it removes the model call for roughly 1 turn in 16 of these test sentences; the real share on phone speech is unknown.
- Honest caveats: the held-out set is 50 hand-written sentences from this repo, not phone speech; the synthetic templates were written in the same
  style as those labels, so accuracy on real, noisy, mixed-language speech will be lower. The first training run printed the held-out mistakes once (7 of them);
  no template was added or changed for them.

### Simulator (`uv run python -m friday.latency.simulator`, `tests/latency/test_simulator.py`)
Virtual-time loop (time jumps to the next timer), fake STT / model / TTS delays, the REAL policy, speculator, classifier and `stream_to_voice`.
Reply gap in ms, defaults: model 650 ms, REST STT 340 + 500 ms, scripted line pre-rendered (TTS 0), free-form model 450 ms to first token at 100 tokens/s, uncached TTS 260 ms.
The mix of turn kinds (45% rules sure, 20% unsure and the early text is final, ...) is an ASSUMPTION; the per-case numbers are what the code does for the delays configured.

| Scripted turns | baseline | speculative | classifier | both |
|---|---|---|---|---|
| REST speech-to-text, mean over the assumed mix | 1204 | 1198 (-6) | 1138 | 1132 |
| Streaming speech-to-text, mean over the assumed mix | 956 | 900 (-56) | 890 | 842 |
| Streaming, long unsure answer | 1500 | 1150 (-350) | 1500 | 1150 |
| Streaming, unsure answer the classifier knows | 1220 | 1150 | 570 (-650) | 570 |

Speculative hit rate: 75% of the turns where a guess was started (streaming), 40% of all turns; cost 15 wasted model calls per 100 turns.
Free-form replies: 1 sentence 1888 -> 1888 (nothing to overlap); 2 sentences 1988 -> 1750 (-238); 3 sentences 2100 -> 1750 (-350); first sentence is spoken at about 650 ms.

### Reading the logs (INFO, same style as `reply gap`)
    speculative understanding started (text 'haan toh phir', step S1)
    speculative understanding hit (saved ~430 ms, text 'haan toh phir')
    speculative understanding miss (text changed 'haan toh phir' -> 'haan toh phir kal dekhte hain'; model call wasted)
    speculative understanding cancelled (caller kept talking)
    classifier hit YES conf=0.972 (no model call)
    classifier miss YES conf=0.610 (below_threshold); rules + model path        (reasons: below_threshold, not_safe_intent, not_allowed_here)
    stream-to-tts first sentence 590 ms after the request (48 chars)
    stream-to-tts done: 3 sentences spoken, first at 590 ms, stream ended at 1480 ms
    stream-to-tts sentence blocked by guard (safety: ungrounded number(s) ['450']); stopping       (WARNING)
    stream-to-tts failed (ProviderError) after 0 sentences; falling back                           (WARNING)
    llm openai stream first token 410 ms (purpose=call_turn)   /   llm sarvam stream first token ...
Judge them against the existing `reply gap N ms` lines, switch on vs off, on the same script. For a streamed turn the per-call `latency p50/p95` policy figure is the time to the first sentence.

### NOT verified (nothing here touched a live call, the network, or real vendors)
- Live Vobiz audio: the sentence-by-sentence `leg.speak` calls (each waits for its playback checkpoint) may leave a small gap between sentences; barge-in between sentences.
- Real Sarvam / OpenAI streaming behaviour: the adapters follow the documented SSE format and are tested against fakes and mock transports only. Whether Sarvam honours
  `response_format` json_schema together with `stream: true`, the real time to first token, and how structured output arrives (key order: `type` must come before `text`) are unknown.
- Real speech-to-text partial quality: how often the early / stable text equals the final text on phone speech (the simulator's hit rate is a scenario, not a measurement). ElevenLabs partials were
  already seen to be wrong on real Hindi (see above); a wrong partial costs one wasted model call, never a wrong action.
- Classifier accuracy on real phone speech (50 hand-written held-out sentences only), and how many real turns it would take off the model (6% of the held-out sentences).
- Language of the streamed sentences: they are spoken in the language the call is already in (`_lang()`), not the model's own `language` field, which arrives after the text.
- Cost: speculation adds wasted model calls (15 per 100 turns in the simulation); the classifier removes calls; nothing here was priced on real traffic.

### Turning them on for a test call (founder decision)
Start with `FRIDAY_INTENT_CLASSIFIER=true`: it needs no new audio path. Then `FRIDAY_VOICE_SPECULATIVE_UNDERSTANDING=true` together with `FRIDAY_VOICE_STREAM_STT=true`
(speculation helps little with REST speech-to-text). `FRIDAY_LLM_STREAM_TO_TTS=true` last, and listen for a pause or a restart between sentences. Compare the `reply gap` lines.
