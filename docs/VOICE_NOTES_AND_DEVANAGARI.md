# Voice-note replies and Devanagari input (22 Oct 2026)

Two chatbot features, each behind its own switch, both OFF by default. With a switch off the product behaves exactly as before
(tests prove it). Code: `friday/chatbot_media/` (voice notes), `friday/lang_dev/` (Devanagari). Tests: `tests/chatbot_media/`,
`tests/lang_dev/`, `tests/channels/test_whatsapp_audio.py`. All offline: fakes only, no network, no real keys, invented numbers.

| Switch (env name) | Settings field | Default | Turns on |
|---|---|---|---|
| `FRIDAY_VOICE_NOTE_REPLIES` | `voice_note_replies` | off | confidence-aware voice-note transcription, the "maine suna ... sahi hai?" check, the per-user text/voice/both/mirror setting, voice-note replies |
| `FRIDAY_DEVANAGARI_INPUT` | `devanagari_input` | off | the Devanagari to Roman Hinglish normaliser in front of every parser, and script mirroring (Devanagari variants of fixed lines) |

Tuning (names only, with defaults): `FRIDAY_VOICE_NOTE_DAILY_CAP=10` voice replies per user per IST day, `FRIDAY_VOICE_NOTE_MAX_CHARS=600`
(about 30 seconds), `FRIDAY_VOICE_NOTE_CONFIRM_BELOW=0.6` (ask back below this transcript confidence), `FRIDAY_VOICE_NOTE_COST_PER_1K_CHARS_INR=3.0`
(an ESTIMATE used only for the cost log).

## 1. Voice-note replies

```
WhatsApp voice note
  -> InboundPipeline.handle: fetch_media (16 MB and type caps unchanged) -> STT (existing Sarvam client, behind Transcriber; fake for tests)
  -> _active: VoiceInbound.on_inbound
       turn state "this turn was spoken" (+ script)            confident transcript -> carries on as TYPED text
       low confidence -> 'Maine suna: "..." Sahi hai?' [Haan, sahi] [Nahi]   (held back; a tap on Haan sends it on)
       "text mein reply karo" style command -> sets the preference, answers, stops here
  -> (Devanagari normaliser, if on) -> consumer router / quotes / brain: the SAME path as typed text
  -> any reply -> Notifier.send -> 24-hour window gate -> OutboundHooks.before_send
       policy.decide -> speak? send text too?
       TTS of the SAME reply text (hold cache) -> ffmpeg -> Ogg/Opus -> POST /{phone_number_id}/media -> audio message by media id
       failure anywhere -> the plain text goes out, one log line, no text in the log
```

The voice note never has its own words: the TTS receives exactly the reply text the chatbot would have sent.

### Per-user setting
`text` (never voice), `voice` (voice when allowed), `both` (voice and text), `mirror` (the DEFAULT: a voice note gets a voice reply,
typed text gets text). A short message changes it, typed or spoken: "text mein reply karo", "sirf text", "voice note mat bhejo" (text);
"voice mein reply karo", "voice note bhejo", "sirf voice" (voice); "voice aur text dono" (both); "jaisa main bhejun waisa reply" (mirror).
Devanagari works too. A topic-bound request ("interview ke baad voice note bhejo") is NOT this setting: it belongs to the existing
follow-up settings (`parse_mute_command`). Stored in the shared cache under `vn:pref:<user>` with a 400-day TTL (see decisions).

### Rules (code: `chatbot_media/policy.py`, every one tested)
- Only inside the 24-hour window. The notifier gates the window first; templates and out-of-window messages never reach the hook.
- Short replies only: at most `voice_note_max_chars` (600) characters, about 30 seconds at 20 characters a second. A longer reply is text only
  (no "summary" voice note: a summary would be different words; see decisions).
- Numbers, amounts, links and buttons always ALSO go as text in the same turn (the voice note goes first, the text with its buttons after).
- Approvals (buttons `callap:` `callact:` `a:` `q:` `n:`, or an approve/confirm button prompt) are never spoken: text and buttons only.
  So an approval is never voice-only. The "maine suna" check (buttons `vn:`) is text too.
- Private details are not read aloud unless the user asked by voice in the same turn: bank and card names, bills, rent and EMI, the user's
  events (interview, appointment, doctor), medicine, "what do you remember". A typed question under `voice` gets text for these.
- A per-user daily cap (`voice_note_daily_cap`) and a per-day cost log (`voice reply cost day=... chars=... est_inr=...`; the reply text is never logged).
- Hold cache: an identical reply is synthesised once, converted once and uploaded once (in-process LRU of Ogg bytes plus the WhatsApp media id for
  20 days). It is in this process only, never the shared cache, because a reply can carry personal details.
- Degrade to text, silently, with a log line: no ffmpeg (named once: "ffmpeg not found"), no TTS, TTS or conversion error, upload or send rejected,
  channel without media upload, daily cap reached.

### ffmpeg
`chatbot_media/convert.py`: `ffmpeg -i pipe:0 -vn -ac 1 -ar 16000 -c:a libopus -b:a 24k -application voip -f ogg pipe:1`, arguments as a list (no
shell), audio through pipes, 20 s timeout, output cap 4 MB. `FakeConverter` is the offline path (`b"OggS" + the TTS bytes`, with `present=False` and
`fail=True` variants). `deploy/small-server.sh` now installs the `ffmpeg` apt package. `friday doctor` (section 6, switches) prints both switches
and an ffmpeg line: `[ OK ] ffmpeg is installed`, or `[WARN] ffmpeg is MISSING: install it with 'apt-get install -y ffmpeg'` when the voice switch is on.

### WhatsApp channel (backward compatible)
`WhatsAppCloudChannel.upload_media(data, mime, filename)` posts multipart `messaging_product=whatsapp`, `type=audio/ogg` and the file to
`/{phone_number_id}/media`, same size and type caps as downloads, returns the media id (validated). `send_audio(to_phone, media_id)` sends
`{"type":"audio","audio":{"id":...}}`. `build_payload` already accepted a media id; nothing existing changed. The simulator has the same two methods.

### Hooks in existing files (small, marked `HOOK`)
`channels/notifier.py` (an `outbound_hook` attribute, called after the 24-hour gate; built only when a switch is on), `api/inbound.py` (`_transcribe`,
`_active`, `_media_hook`, `_media_inbound`), `core/config.py` (the switches and four tuning fields), `cli.py` (`friday chatbot devanagari-eval`),
`ops/doctor.py`, `channels/whatsapp.py`, `channels/simulator.py`, `deploy/small-server.sh`. With both switches off none of the new code runs.

## 2. Devanagari input

`friday/lang_dev/normalise.py`: `normalise_text("कल 2 बजे interview है") -> "kal 2 baje interview hai"`. The pipeline hook runs it at the top of
`_active` (after the message was logged, so logs and the display keep the original; the Roman text rides in the message copy, the original in
`raw['original_text']`), so every parser sees Roman Hinglish: life capture, savings categories and wallet, bills, call-request understanding, memory
controls, "mat poocho" (mute), menu/help, the quotes flow and the brain. The parsers themselves were not touched.

| Piece | What it does |
|---|---|
| digits | `०-९` to ASCII, danda `।` to `.` |
| number words | `numbers.py`: 1 to 99 (all spellings of the common ones), `सौ हज़ार लाख करोड़`, `डेढ़ ढाई सवा साढ़े पौने`. `parse_number_phrase("पाँच सौ") == 500`, `("डेढ़ सौ") == 150`, `("सवा पाँच") == 5.25`, `("साढ़े तीन हज़ार") == 3500` (exact `Decimal`). Written as digits when they are an amount, a time, a date or above twelve; kept as a word otherwise (`बता दो` stays "bata do", `दो बजे` becomes "2 baje") |
| clock fractions | `सवा पाँच बजे -> sawa 5 baje`, `साढ़े नौ बजे -> saade 9 baje`, `डेढ़ बजे -> dedh baje`, `ढाई बजे -> dhai baje`, `पौने छह बजे -> paune 6 baje` (the forms `lifestate/capture.py` reads) |
| lexicon | `lexicon.py` (about 660 word forms and 37 phrases): days, months (English month names, which the bill and the capture parsers both read), time words, grammar words, verbs, family and providers, English words typed in Devanagari (कार्ड, बिल, फोन, डॉक्टर, रेस्टोरेंट, इंटरव्यू), banks, card names, merchants, rupaye. Phrases (मत पूछो, बता दो, हटा दो) are matched before words. Nukta and chandrabindu spellings are folded. |
| fallback | `translit.py`: consonant, vowel and matra table with schwa deletion (`कितना -> kitna`, `समझ -> samajh`), for names and unknown words |
| homographs | `बस` is "bas" (enough) except next to `बजे`/`स्टैंड`/`टिकट` ("bus") |
| mixed script | Latin words, digits and punctuation pass through; only Devanagari words change |
| script | `detect_script` (roman, devanagari, mixed); `mirror_script` (Devanagari when Devanagari words are at least as many as Roman ones) |
| replies | `reply.py`: a reply mirrors the user's script only when a Devanagari variant of that EXACT Roman line is registered (`register_variant`); everything else stays Roman. Friday does not transliterate free text into Devanagari |

Speech-to-text returns Devanagari for Hindi speech, so voice notes use the same path.

### The accuracy report
`uv run friday chatbot devanagari-eval [--split dev|heldout|all] [--baseline] [--no-failures]` (offline, never reads `.env`). It runs each labelled message
through the SAME parsers the router uses (`RequestUnderstander`, `parse_wallet_message`, `parse_purchase`, `parse_bill_text`, `capture.parse_message`,
`MemoryControls` regexes, `parse_mute_command`, `brain.heuristics.interpret`), in the router's order, with and without the normaliser (`--baseline`),
and prints accuracy per intent (intent only, and strict = intent and slots: hour, day, amount, bank, callee) plus every failure with what the parser read.
Data: `friday/lang_dev/data/dev.tsv` (198 messages) and `heldout.tsv` (94), 292 in all, 22 of them "must NOT be taken" controls.

Numbers on 22 Oct 2026:

| Set | n | Intent accuracy | Strict accuracy | Without the normaliser |
|---|---|---|---|---|
| dev (built against) | 198 | 100.0% | 100.0% | 8.0% |
| **held-out** (never tuned on) | **94** | **98.9%** | **97.9%** | 9.6% |

Held-out failures, left as they are: "डाउनलोड" (download) is not in the lexicon, so "mera data download karo" was not read as an export;
"एयू बैंक" (AU Bank) was read as "eyu bank". Held-out protocol: the labels were checked against the Roman spelling of the same sentences (the parsers'
own limits, three rows were dropped for that), then the Devanagari was run ONCE; the lexicon has not changed since. Read the number with care: the
held-out messages were written by the same author as the lexicon, so it measures generalisation inside that author's Hindi, not real users. Expect
real accuracy to be lower until real Devanagari messages are collected (`friday chatbot devanagari-eval` takes more rows in the same TSV format).

## 3. New user-facing text (all PENDING_FOUNDER_APPROVAL)
`friday/chatbot_media/copy.py` only (Roman and Devanagari variants): the "maine suna" check and its two buttons, "send again", "link expired", "too long",
"could not understand the voice", and the four setting acknowledgements. No existing script, spoken line or playbook was changed. A voice note speaks
whatever reply text the chatbot already had, so the founder approves the TEXT, not a second script. Before any change to a voice, pace or
pronunciation the founder hears a sample first (standing rule 3); this work does not change any voice.

## 4. What is NOT verified
- Real WhatsApp rendering and playback of the uploaded Ogg/Opus as a voice note (the waveform bubble), on Android and iPhone; the real media-upload response; whether Meta accepts the `audio/ogg` type with our opus settings.
- Real Sarvam speech-to-text accuracy on real voice notes (Hindi, Hinglish, noise, accents). The "confidence" the Sarvam client returns is its LANGUAGE probability, not a word-error estimate, so the 0.6 threshold is a placeholder.
- ffmpeg on the real server (the installer line and the doctor line exist; the real conversion is covered by a test that runs only where ffmpeg is installed).
- Real Sarvam/ElevenLabs TTS reading Devanagari or Hinglish replies naturally; the cost estimate (3 INR per 1,000 characters is a guess).
- Real Devanagari users: the normaliser and its 292 messages are written by one author; typing habits (spelling, "ऑ" vs "ओ", chat abbreviations) will differ.
- Regional scripts other than Devanagari (Tamil, Telugu, Bengali ...), Marathi in Devanagari (treated as Hindi), and Urdu script.
- Preferences and counters live in the shared cache (Redis in production); on a Redis flush the preference returns to `mirror` and the daily count to 0.
- A pending "maine suna" confirmation lives in one process for 10 minutes; a tap that lands on another worker answers "link expired".

## 5. Decisions for the founder
1. Wording of `chatbot_media/copy.py` (Roman and Devanagari).
2. Default `mirror`, or start everyone on `text` and let people opt in?
3. A reply longer than 600 characters is text only. Want a short spoken summary instead? That would be different words from the text.
4. Persist the voice preference in the database (a column on the profile and a migration) instead of the cache?
5. Daily cap of 10 voice replies per user, and the cost estimate: confirm after the first week of real use.
6. Which voice and pace speak the replies (the existing TTS settings are used unchanged); the founder hears a sample before it goes to testers.
7. Turn on `FRIDAY_DEVANAGARI_INPUT` first for the founder only, then testers; the onboarding flow (another builder's work) is not normalised, so a Devanagari name stays in Devanagari.
8. Are Devanagari variants of the other fixed chatbot lines wanted? `reply.register_variant(roman, devanagari)` is the hook; each new line needs approval.

## 6. Turning it on
1. Install ffmpeg (`deploy/small-server.sh` does) and run `friday doctor`: the ffmpeg line must say installed.
2. Approve the wording, then set `FRIDAY_VOICE_NOTE_REPLIES=true` and/or `FRIDAY_DEVANAGARI_INPUT=true` in the server environment and restart.
3. Try with the founder's own number first: a voice note, then "text mein reply karo", then a Devanagari message.
