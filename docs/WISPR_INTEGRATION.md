# Wispr (Wispr Flow) and Friday: integration design (EM, DESIGN ONLY, 2026-10-28)

Founder clarified: the product is **Wispr** (Wispr Flow), speech in, clean text out (dictation); not OpenAI Whisper, not text-to-voice.
No code, no keys, no real calls. Public repo. Companion PM doc: `docs/WISPR_RESEARCH.md` or `docs/WHISPER_AI_RESEARCH.md`; neither existed when this was written (checked locally and on origin). Every Wispr fact below is from general knowledge and is UNVERIFIED until the PM doc lands; re-check before any decision.

## 0. Decision and scope
Founder decision (2026-10-28): Wispr provides NO API key, so we build OUR OWN version inside `friday/speech`. No Wispr adapter, no vendor dependency. This doc is: gap list (s1), build plan (s2), paths and latency budget (s4), eval harness (s5), DPDP (s6), effort and go/no-go (s2, s9).
Optional only: an STT second opinion behind the existing `STTProvider` port (s3, a few lines). Wispr Flow itself stays a benchmark: the founder can dictate the same lines into his own app and we score its text (no data from Friday goes to it).

## 1. What Wispr-style dictation does vs what Friday has
Wispr Flow features (from public descriptions, unverified): fillers removed; self-correction handled ("backtrack"); punctuation and casing added; a personal dictionary of names/jargon; tone adapted to the app being typed in; snippets (short phrase expands to long text); command/edit mode ("make this shorter"); many languages including mixed-language speech; works anywhere via hotkey.

| Wispr-style feature | Friday today | Status |
|---|---|---|
| Remove fillers/stutters | `speech/rules.py` `clean_basic` (um/uh/hmm, repeated words) + LLM | done |
| Self-correction ("kal nahi, parso") | rules for same-kind swaps (day, part of day, digit number) + LLM `self_correction` repairs | partly: rules cover only day/period/digit; longer or spoken-number ("paanch nahi chhe") corrections rely on the LLM |
| Fix mis-hearings from context | `understander.py` + `memory.py` (names, places, shops) + `ground.py` (no invented number/day/name; script never changed) | done, real-model quality NOT measured |
| Personal dictionary | `memory.py` builds a view from the user's names/places/shops/aliases | partial: derived, not user-editable; no "teach Friday this word" flow; no per-user pronunciation/spelling list |
| Punctuation/casing/format | not needed for intent; not produced | missing, only needed if a surface shows text back (summaries, notes, drafts) |
| Tone per destination | n/a | missing, low priority |
| Snippets | none | missing, optional (e.g. "mera address" -> saved address, only from the user's own profile) |
| Edit by voice ("isse chhota karo") | none in speech layer | out of scope here (belongs to drafting flows) |
| Script handling Hinglish/Devanagari | `friday/lang_dev` normaliser before understanding | done |
| Confirm when unsure | `VoiceInbound` asks "maine suna: ... sahi hai?" with 2 buttons on low confidence | crude (language-probability based, see `SPEECH_UNDERSTANDING.md` s1) |
| Live latency | call deadline 0.9 s, voice note 3 s, never raises, never blocks | done |
| Measured accuracy | `friday speech eval` offline floor cases; `eval --live` exists | missing: no Hinglish WER set, no harmful-edit rate |

Missing list, in priority order: (a) a measured Hinglish eval and the numbers; (b) user-teachable personal dictionary with a "sahi word ye hai" correction loop; (c) a better doubt signal than language probability (disagreement between two STT passes, or grounded-repair count); (d) wider rule-based self-correction (spoken numbers, "matlab", "ya phir"); (e) optional punctuation/format for text-back surfaces; (f) optional snippets.

## 2. Gaps to build in friday/speech (no vendor)
Files to change/add:
- `friday/speech/dictionary.py` (new): per-user dictionary `{heard_form -> written_form, kind, source, added_at}`; sources: user correction, memory, pilot-curated list. Stored with the user's existing profile store (no new infra); consent already covers it as the user's own data. Applied as (i) hint list in the prompt, (ii) deterministic replace in `rules.py` for exact heard-forms.
- `friday/speech/rules.py`: add spoken-number correction ("paanch nahi chhe baje"), "ya phir", "matlab" patterns; every new rule needs a case in `speech/data/eval_cases.json`.
- `friday/speech/schema.py`: optional `alt_transcript`, `alt_source`, `needs_confirm: bool`, `confirm_reason`.
- `friday/speech/ground.py`: allow dictionary-listed words as grounded; keep all existing refusals.
- `friday/chatbot_media/inbound.py`: use `needs_confirm` instead of the crude probability test; when the user corrects, add to the dictionary ("sahi hai / nahi, ye tha").
- `friday/speech/cli.py`: `friday speech dict add|list|rm`, `friday speech bench` (section 5).
Switches (default OFF unless stated): `FRIDAY_SPEECH_DICTIONARY=off|shadow|on`, `FRIDAY_SPEECH_CONFIRM_ON_DOUBT=off|on`, `FRIDAY_SPEECH_FORMAT_TEXT=off`. Existing `FRIDAY_SPEECH_UNDERSTANDING` stays as is (note: default is "on"; confirm that was approved after the live eval).
Effort: dictionary + loop 2 d; rules + cases 1.5 d; confirm-on-doubt 1.5 d; bench harness 2 d; punctuation/snippets 2 d (optional). About 7 working days core.

## 2b. Tone/format matching and mixed script (build)
- `friday/speech/format.py` (new, `FRIDAY_SPEECH_FORMAT_TEXT=off`): only for surfaces that show text back (summaries, notes, drafts to a vendor). Deterministic punctuation/casing; tone preset per destination (`casual` own notes, `polite` vendor drafts) chosen by the caller; model only if the deadline allows. Never changes numbers/names (reuses `ground.py`).
- Mixed script: keep `lang_dev` Roman-Hinglish normalisation before rules; output keeps the user's script (existing rule). Add Devanagari filler/"matlab" rules and Devanagari digit words; cases in `eval_cases.json`.
- Self-correction: widen rules (spoken numbers, "ya phir", "nahi nahi", sentence restarts); LLM handles the rest, grounded.
- Personal dictionary from memory: seed `dictionary.py` from `memory.py` / `build_context` (names, places, shops, aliases) so users need no effort; the "sahi word ye hai" loop adds the rest.
- Latency budget: calls 0.9 s hard deadline (rules + dictionary replace are under 5 ms and always run; LLM only if budget remains; format off on calls); voice notes 3 s (reply is not interactive); second opinion never on the live call path. Track p50/p95 and timeout-to-floor rate per channel.

## 3. Optional: STT second opinion (a few lines)
Port exists: `STTProvider.transcribe` (`friday/core/interfaces.py`), chosen by `Settings.stt_provider`. If the eval shows entity errors that rules cannot fix, add a batch-only Whisper-class adapter `friday/voice/stt/whisper.py` plus `second_opinion.py` (voice notes with digits/names or low confidence; calls only post-turn). Disagreement goes to the understander as `alt_transcript`, `ground.py` gates it, doubt asks the user. Switch `FRIDAY_STT_SECOND_OPINION=off|shadow|on` (default off, shadow 2 weeks first), key by name only. About 4 days. Audio leaves our servers: see s6.

## 4. Voice-note path and call-turn path
Voice note: WhatsApp Ogg/Opus -> `voicenote.prepare_voice_note` (3 min cap, 16 kHz WAV) -> primary STT -> [second opinion, if on] -> `lang_dev` -> `speech.understander` (3 s deadline) -> `VoiceInbound` -> intent chain. Dictionary and confirm-on-doubt live here first (latency is forgiving; a confirm button costs one tap).
Call turn: streaming/REST STT -> `FrontDoorSession.hear` -> understander (0.9 s deadline, rules floor on timeout). Only the user's own turns; never a vendor's speech on outbound calls (a silent fix could change a quoted price). Second opinion not on the live path; use it post-turn to correct the stored record. Dictionary replace is deterministic and free, so it is allowed on the live path.
Where it must NOT apply: secret talk (OTP/card/passwords; `redact_secrets` already), vendor-side quotes, anything money-moving without a read-back.

## 5. Eval plan (Hinglish)
Harness: `friday speech bench` and `friday/speech/bench/` (new), data and outputs under `var/` (git-ignored); only masked text snippets and synthetic lines may be committed.
Sets (all with consent or synthetic; none from strangers):
1. **Transcription WER**: 50 clips, 3 to 30 s, Hinglish voice notes plus phone-quality call segments; human reference transcripts. Compare Sarvam, Sarvam + understander, second-opinion STT, merged. Score WER on a normalised form (Roman vs Devanagari handled per `VOICE_NOTES_AND_DEVANAGARI.md`), plus **entity error rate** on numbers, times, names, amounts (the metric that matters).
2. **Self-correction set**: 40 utterances with a planted correction ("kal nahi, parso", "paanch nahi chhe baje", "Rohan, matlab Rohit"); metric: final intended value correct (%), over-correction rate (a repair applied where none was intended; target 0 for numbers/names).
3. **Filler/stutter set**: 30 lines; metric: meaning preserved (human) and words removed correctly.
4. **Personal-dictionary set**: 25 user-specific names/shops/brands, said 2 ways; metric: hit rate before/after dictionary, and false-substitution rate.
5. **Harmful-edit set**: ambiguous lines where the safe answer is to leave text alone or ask; metric: harmful edit rate (target 0), ask-rate sensible.
6. **Latency**: understander p50/p95 on voice-note and call deadlines (0.9 s call), timeout/fallback rate to the rules floor; second opinion adds p50/p95 and cost per 100 notes.
Blind scoring: raw, Sarvam-only, understander, and (if any) Wispr-style/second-opinion outputs shuffled and anonymised; the founder plus 2 native Hinglish speakers rate "did it keep my meaning?" 1 to 5. Add the existing offline cases and `eval --live` as the regression gate.
Optional benchmark: the founder dictates the same 20 lines into Wispr Flow himself and we score its text with the same sheet (his own voice, his own app; no API, no data sent by Friday). This answers "is ours as good?" with no integration.
Effort: sets recorded and referenced 2 d (founder time), scoring scripts 2 d, run and write-up 1 d.

## 6. Data handling and DPDP
- Voice notes and call audio are personal data. Today audio goes to Sarvam (already a processor). Any new STT vendor or Wispr API means audio leaves our servers to another processor: name it in the privacy notice, record purpose, and add it to a processor list.
- Consent: second-opinion STT runs only for users who said yes to a one-line consent ("aapki voice note samajhne ke liye ek aur partner service use ho sakti hai, theek hai?"); founder hears/approves wording before it ships (hear-before-change). Calls: opening disclosure gets one extra line only if call audio goes out; default is calls stay on the primary.
- No storage: require zero-retention and no-training in writing as a go condition; Friday keeps the original text only (existing `raw['original_text']` audit), no raw audio in git or logs, counts-only audit (`UnderstoodUtterance.audit`) already avoids words in logs. Secrets never sent (deny filter before any outbound STT call is impossible for audio, so secret-talk users stay on primary only).
- Personal dictionary is the user's own data: viewable, editable, deletable (`friday speech dict rm`), included in delete-my-data.
- Wispr's own app: if the founder uses it personally, that is his data under Wispr's terms; do not feed Friday customer audio through it.
- Bake-off audio: only the founder's voice or explicit consent of the speaker. Real calls only to the allow-listed founder number and with approval (rule 5).

## 7. Failure modes
Understander over-corrects a name or number (grounding + zero-tolerance metric + shadow first); model slow (rules floor, raw fallback); second STT hallucinates on silence/noise (drop on no-speech, check script, force language); transcripts disagree on a number (ask, never guess); dictionary poisoning by a wrong correction (versioned, undo, per-user only); Roman/Devanagari mismatch inflating WER (normalise before scoring); cost creep (daily cap); vendor outage (second opinion simply skipped); false sense of accuracy from synthetic sets (keep real-voice sets).

## 8. Short section: if a text-to-voice vendor is wanted anyway
Out of scope for "Wispr", but for completeness: a second TTS fits behind `TTSProvider` (`friday/voice/tts/`). ElevenLabs is already an adapter (`tts/elevenlabs.py`), `FallbackTTS` already falls back to Sarvam on error (`Settings.tts_fallback`), `CachedTTS` caches, `pronunciations.json` is the dictionary. Missing: a per-use-case selector (call / voice-note reply / listening kit), a first-audio deadline for the fallback, per-vendor cost log fields. Add a `RoutedTTS` (`tts/router.py`) with `FRIDAY_TTS_ROUTE_CALL|VOICE_NOTE|KIT` (empty = Sarvam), 8 kHz via native output or one shared resample helper, blind 20-line Hinglish bake-off with first-audio p50/p95 vs Sarvam stream (about 480 ms in `LATENCY.md`) plus 150 ms bar. Effort about 8 working days. Order: listening kit first, calls last. Founder hears every sample first.

## 9. Go / no-go checklist
Dictation clean-up (friday/speech improvements):
1. Bench numbers exist for sets 1 to 5 and beat raw STT on entity accuracy and self-correction with harmful-edit rate 0 on numbers/names.
2. Live eval run on the server with the real model; founder reviewed 20 before/after examples.
3. Dictionary shadow for a week with no false substitutions; undo works.
4. Latency within deadlines; fallback tested by fault injection.
5. Kill switches verified (`FRIDAY_SPEECH_*` back to off/shadow).
Wispr as a service (adapter) or any second STT:
6. A documented API/partner route exists (PM doc) with Hinglish support shown on OUR clips.
7. Zero retention / no training in writing; region and sub-processors listed; consent line approved.
8. Entity error rate better than primary by a margin that justifies cost; cost per 100 notes under cap.
9. 2 weeks shadow with no incident; then voice notes only, calls last.
No-go: no public API or terms forbid our use; needs audio retention; worse numbers/names; adds visible latency to calls; requires voice cloning or impersonation.

## 10. Questions for the founder
Did you mean Wispr Flow the dictation app (assumed)? Is the goal "Friday should understand my voice notes as well as Wispr types them" (yes -> section 2, 5) or "use Wispr's engine" (needs vendor answer)? Will you dictate 20 lines into Wispr for the side-by-side? Who are the 2 Hinglish listeners/scorers?
