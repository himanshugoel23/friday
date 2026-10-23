# Human-like voice (built 2026-10-23)

Everything here is **built, tested offline, and ON in the `internal-test` profile**. Production / pilot keep every
AUDIBLE element OFF until the founder hears the samples and approves them (CLAUDE.md rule 3). No real call and no
audio was made in building this. Nothing here pretends to be a person: AI disclosure on request is untouched
(`PROTECTED` lines are never reworded or shortened), backchannels are ordinary approved words in Ritu's voice
(no breaths, laughs or typing sounds), and no new line claims to be human (a test checks).

## How to turn it on
Server `.env`: `FRIDAY_VOICE_PROFILE=internal-test` (founder test calls to the allow-listed number only).
Any switch set explicitly in the env wins over the profile. See what is on: `friday voice switches`, `friday voice selftest`,
`friday doctor` (section 6, one line per switch). Install the neural voice detector: `uv sync --extra vad`
(the Dockerfile and `deploy/small-server.sh` already do; if the extra is missing Friday falls back to the energy rule, and doctor says so).

## Switches
| Switch | Kind | production / pilot | internal-test | What it does |
|---|---|---|---|---|
| `FRIDAY_INTENT_CLASSIFIER` | silent | ON | ON | small trained classifier answers common replies (needs a gate-passed model, else rules + model as before) |
| `FRIDAY_VOICE_SPECULATIVE_UNDERSTANDING` | silent | ON | ON | start understanding the early / stable transcript while the pause is timed out |
| `FRIDAY_LLM_STREAM_TO_TTS` | silent | ON | ON | speak a model-written reply sentence by sentence |
| `FRIDAY_VOICE_SEMANTIC_EOT` | silent | ON | ON | judge from the words whether the caller has finished |
| `FRIDAY_VOICE_VAD_BACKEND` | silent | silero (auto fallback to energy) | silero | trained voice detector; falls back to the energy rule if it cannot load or fails mid-call |
| `FRIDAY_VOICE_STREAM_STT` | silent | OFF | OFF | kept OFF on purpose: docs/LATENCY.md says compare REST vs streaming on real recorded audio first; not done |
| `FRIDAY_HUMAN_RESUME` | silent | ON | ON | after an interruption continue the unfinished point (only after a short "go on"; the connector wording needs `FRIDAY_HUMAN_VARIANTS`) |
| `FRIDAY_HUMAN_METRICS` | silent | ON | ON | per-call human-feel record (no transcript, no number) |
| `FRIDAY_HUMAN_BACKCHANNELS` | audible | OFF | ON | "haan ji / hmm / achha" during long answers |
| `FRIDAY_HUMAN_PROSODY` | audible | OFF | ON | pace multiplier and pause commas per line type |
| `FRIDAY_HUMAN_NUMBERS` | audible | OFF | ON | numbers, prices, times, phone digits in spoken Hinglish |
| `FRIDAY_HUMAN_VARIANTS` | audible | OFF | ON | phrasing variety from the pending table |
| `FRIDAY_HUMAN_MIRROR` | audible | OFF | ON | pure English / pure Hindi callee gets the matching variant |
| `FRIDAY_HUMAN_MOOD` | audible | OFF | ON | rushed / annoyed callee: shorter lines, one apology, one question |
| `FRIDAY_HUMAN_MATCH_LISTENER` | audible | OFF | ON | pace (0.8-1.0 around the approved 0.9) and line length follow the listener |
| `FRIDAY_HUMAN_PAUSES` | audible | OFF | ON | a 250-600 ms thoughtful pause before a hard question or after a price |
| `FRIDAY_HUMAN_NOISE_ADAPT` | audible | OFF | ON | noise-aware detector thresholds; asks "Sorry, ek baar phir?" (existing line) for unintelligible noise; gives up after 2 |

## What each element does
- **Backchannels** (`friday/human/backchannel.py`): only when Friday is silent, the other side has spoken at least 4 s, and they are in a 250-450 ms pause; once per pause, at least 6 s apart, at most 2 per answer and 6 per call, never the same twice in a row, off for elders (relation words) and by switch. The leg plays a cached clip; if the turn ended meanwhile it stays silent. Wired into the Sarvam leg.
- **Prosody** (`prosody.py`): number lines x0.92 with a comma before the first number phrase, bad news x0.94, thanks x0.97, greeting x0.98, questions and plain lines unchanged. The multiplier reaches the TTS as the voice's `speaking_rate` (clamped 0.85-1.10 relative).
- **Numbers** (`numbers.py`): `450` -> "chaar sau pachaas", `Rs 1,500` -> "dedh hazaar rupaye", `5:30 pm` -> "shaam saade paanch baje", `5:15` -> "sawa paanch baje", `5:45` -> "paune chhe baje", phone `9876543210` -> groups 3-4-3 digit by digit. Roman Hinglish only; English, Devanagari and anything near OTP/PIN/CVV are left alone. The transcript keeps the original text.
- **Variants** (`variants.py`, `lines.py`): choice depends only on call id, key and use count, so a call never contradicts itself and never repeats a variant back to back; no free generation. Used for the hold line, the cancel line, the short hold, the resume connector and the mood apology; scripted playbook lines are not touched.
- **Language mirroring**: the callee's last utterance is classed as `hi` (Devanagari), `en` (clear English, no Hindi words) or `hinglish` (default when unsure); the matching variant of the pending table is chosen.
- **Mood** (`mood.py`): keyword rules for rushed / annoyed; then pleasantries dropped, at most one question, at most 12 words, ONE apology line per call (never on the disclosure turn). Stop / do-not-call stays with the call engine.
- **Match the listener** (`listener.py`): from the transcript and audio duration: words per second, answer length, hesitation ("um", "matlab", "..."), and repeat requests ("kya?", "sorry?", "phir se"). Slow / hesitant / repeating -> pace 0.8-0.875 and lines of at most 16 words; busy and curt -> pace up to 1.0 and 12 words. Sentences with a question or a number are never dropped; disclosure lines are never shortened.
- **Right-sized silences** (`pauses.py`): 250-600 ms, deterministic per call seed, only before a hard question (budget, discount, final...) or right after the other side gave a price; none when they asked us something; pause + reply gap is capped at 1 s.
- **Noise** (`noise.py`, hooks in the Sarvam leg): noise floor (quietest 10 percent of the last 5 s, which still works if a loud line makes the detector call every frame speech) and speech-to-noise ratio -> class clean / moderate / noisy / very_noisy -> longer end-of-speech wait (900 -> up to 1300 ms), stricter speech-start probability (+0.05 to +0.2), less touchy barge-in (level 1.6 -> 2.8, frames 7 -> 9). Pure noise (empty or symbol-only transcript) is not answered; garbled speech gets the existing "Sorry, ek baar phir?"; after 2 failures the existing safe-exit line ends the call politely. Her own voice is never counted as noise. Tests use synthetic noisy audio (`friday/human/synth.py`).
- **Barge-in resume** (`resume.py`): the leg counts sentences fully queued; if the callee interrupts and then only says a short "go on" (haan ji / boliye / achha...), Friday continues from the second clause of the cut sentence (or the sentence itself if short) plus the rest, with an optional connector. A real question or answer is handled by the normal policy and the unfinished point is dropped.
- **Pronunciation lab**: `friday voice pron-add "<word>" "<spoken form>"` edits `friday/voice/tts/pronunciations.json`; `friday voice pron-test "<line>"` shows the respelling and renders it (real TTS if keys exist); then `friday tts-dict sync` and restart. No training, no voice cloning.
- **Metrics** (`metrics.py`): per call: hang-up within 10 s, "are you a robot / AI?" asked count, call length, noise class and SNR, backchannels, resumes, listener style. Live calls append to `var/human/metrics.jsonl`; `friday voice metrics` prints the aggregate. Every call also logs one `human-feel:` line.
- **Blind listening kit**: `friday voice listening-kit --pairs 6` writes A/B pairs (old vs new treatment, order shuffled), two mini calls (`call_1.wav`, `call_2.wav`), `rating_sheet.csv` (natural 1-5, bot or person) and a KEY file not to open before rating.

## Commands
`friday voice selftest` | `switches` | `human-preview` (writes `var/preview/human/<group>/*.wav` and `index.tsv`; without TTS keys it writes only the text list and says so; keys are never printed) | `listening-kit` | `pron-add` | `pron-test` | `metrics`.

## NEW spoken lines awaiting founder approval (status PENDING_FOUNDER_APPROVAL)
Placeholders: `{name}` = the user's name. The hold and cancel rows 1 are the existing approved lines (index 1 = today's wording); rows 2 and 3 are new.

| Key | Language | # | Text |
|---|---|---|---|
| `bc.short` | hinglish | 1 | Haan ji. |
| `bc.short` | hinglish | 2 | Hmm. |
| `bc.short` | hinglish | 3 | Achha. |
| `bc.short` | hi | 1 | हाँ जी। |
| `bc.short` | hi | 2 | हम्म। |
| `bc.short` | hi | 3 | अच्छा। |
| `bc.short` | en | 1 | Okay. |
| `bc.short` | en | 2 | I see. |
| `bc.short` | en | 3 | Right. |
| `hold.moment` | hinglish | 1 | Ek second ji. |
| `hold.moment` | hinglish | 2 | Bas ek second. |
| `hold.moment` | hinglish | 3 | Ek minute, dekh rahi hoon. |
| `hold.moment` | hi | 1 | एक सेकंड जी। |
| `hold.moment` | hi | 2 | बस एक सेकंड। |
| `hold.moment` | hi | 3 | एक मिनट, देख रही हूँ। |
| `hold.moment` | en | 1 | One second. |
| `hold.moment` | en | 2 | Just a moment. |
| `hold.moment` | en | 3 | One moment, let me check. |
| `hold.waiting` | hinglish | 1 | Hold karne ke liye dhanyavaad. Main abhi {name} ke jawab ka intezaar kar rahi hoon. |
| `hold.waiting` | hinglish | 2 | Aapke intezaar ka shukriya. Main abhi {name} ke jawab ka wait kar rahi hoon. |
| `hold.waiting` | hinglish | 3 | Thoda aur ruk jaiye, {name} ka jawab abhi aana baaki hai. |
| `hold.waiting` | hi | 1 | होल्ड करने के लिए धन्यवाद। मैं अभी {name} के जवाब का इंतज़ार कर रही हूँ। |
| `hold.waiting` | hi | 2 | आपके इंतज़ार का शुक्रिया। मैं अभी {name} के जवाब का इंतज़ार कर रही हूँ। |
| `hold.waiting` | hi | 3 | थोड़ा और रुकिए, {name} का जवाब अभी आना बाकी है। |
| `hold.waiting` | en | 1 | Thank you for holding. I'm still waiting for {name}'s reply. |
| `hold.waiting` | en | 2 | Thanks for waiting, I'm still waiting to hear back from {name}. |
| `hold.waiting` | en | 3 | Please bear with me, {name}'s reply has not come in yet. |
| `cancel.sorry` | hinglish | 1 | Sorry, mujhe abhi yeh call khatam karni hogi. Aapke time ke liye dhanyavaad. |
| `cancel.sorry` | hinglish | 2 | Maaf kijiye, mujhe yeh call abhi band karni padegi. Aapka bahut shukriya. |
| `cancel.sorry` | hinglish | 3 | Sorry ji, mujhe abhi call rakhni hogi. Aapke time ka dhanyavaad. |
| `cancel.sorry` | hi | 1 | माफ़ कीजिए, मुझे अभी यह कॉल खत्म करनी होगी। आपके समय के लिए धन्यवाद। |
| `cancel.sorry` | hi | 2 | माफ़ कीजिए, मुझे यह कॉल अभी बंद करनी पड़ेगी। आपका बहुत शुक्रिया। |
| `cancel.sorry` | hi | 3 | सॉरी जी, मुझे अभी कॉल रखनी होगी। आपके समय का धन्यवाद। |
| `cancel.sorry` | en | 1 | Sorry, I need to end this call now. Thank you for your time. |
| `cancel.sorry` | en | 2 | I am sorry, I have to end the call now. Thank you very much. |
| `cancel.sorry` | en | 3 | Sorry, I have to go now. Thanks for your time. |
| `resume.connector` | hinglish | 1 | Toh main yeh keh rahi thi, |
| `resume.connector` | hinglish | 2 | Haan toh, main bata rahi thi, |
| `resume.connector` | hinglish | 3 | Toh jo main keh rahi thi, |
| `resume.connector` | hi | 1 | तो मैं यह कह रही थी, |
| `resume.connector` | hi | 2 | हाँ तो, मैं बता रही थी, |
| `resume.connector` | hi | 3 | तो जो मैं कह रही थी, |
| `resume.connector` | en | 1 | So, as I was saying, |
| `resume.connector` | en | 2 | Right, I was saying, |
| `resume.connector` | en | 3 | So, what I was about to say, |
| `mood.apology` | hinglish | 1 | Maaf kijiye, bas ek chhoti si baat. |
| `mood.apology` | hinglish | 2 | Sorry ji, main jaldi se poochti hoon. |
| `mood.apology` | hinglish | 3 | Aapka time nahi lungi, bas ek baat. |
| `mood.apology` | hi | 1 | माफ़ कीजिए, बस एक छोटी सी बात। |
| `mood.apology` | hi | 2 | सॉरी जी, मैं जल्दी से पूछती हूँ। |
| `mood.apology` | hi | 3 | आपका समय नहीं लूँगी, बस एक बात। |
| `mood.apology` | en | 1 | Sorry, just one quick thing. |
| `mood.apology` | en | 2 | Sorry about that, I will be quick. |
| `mood.apology` | en | 3 | I will not take your time, just one thing. |

Also NEW but not a line: the `numbers` spellings (the Hinglish number words themselves), the pace multipliers, the pause lengths, and the backchannel timing. The mood apology and resume connector are used only in internal-test.
Existing approved line re-used unchanged: "Sorry, ek baar phir?" (noise repeat) and the session's safe-exit line (noise give-up).

## What the founder must listen to (run `friday voice human-preview` on the server)
1. `numbers/*_before` vs `*_after`: do the Hinglish number words sound right ("chhe", "paune", "derh")?
2. `prosody/*`: flat vs hinted; is the slower number line better or odd?
3. `variants/*`: every new line, three languages.
4. `listener/pace_0.8|0.9|1.0` and `pauses/pause_0|250|600ms`.
5. `mood/rushed_after`, `resume/resume_with_connector`.
Then `friday voice listening-kit` for the blind old-vs-new rating.

## Unverified (nothing here has met a real call)
- All audible quality: number-word spellings, prosody multipliers and commas, pause lengths, backchannel choice and timing.
- Backchannel echo: her own "haan ji" may be picked up by the line and appear in the caller's transcript; only the first internal-test call shows this. Kill: `FRIDAY_HUMAN_BACKCHANNELS=false`.
- The noise thresholds (RMS floors 150 / 350 / 800, SNR 25 / 16 / 9 dB) and the detector adaptation are guesses tested on synthetic audio only; real noisy phone audio is untested.
- Silero VAD, semantic end-of-turn, speculative understanding, streamed replies and the intent classifier: offline tests only; defaults flipped ON on that basis; first real call decides (watch `reply gap`, chopped first syllables, odd 0.7 s waits).
- `FRIDAY_VOICE_STREAM_STT` stays OFF: not compared on real audio. docs/VOICE_PROBE_RESULTS.md findings (realtime STT in use, HTTP TTS stream stays) are respected: no endpoint was changed.
- Listener / mood / language detection are keyword and count rules; Hindi-script and regional languages are only lightly covered.
- Resume uses queued-sentence counts, which can be ahead of what was actually heard (it errs on repeating a sentence).
- `friday voice human-preview` was only run against a stub TTS in tests.
