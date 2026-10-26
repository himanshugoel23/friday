# Speech understanding layer: a small model between speech-to-text and the big LLMs (DESIGN, 2026-10-26)

Founder ask (2026-10-26): when the user SPEAKS, a small "Whisper-like" model should (1) correct what the transcript says the user meant, (2) use
memory (names, places, past requests), (3) work out the meaning, and (4) hand a clean, structured result to the other LLMs for the next step.
This file is a DESIGN. No code and no spoken line has been changed. Status: proposal, waiting for the founder to pick scope (section 9).

## 1. What already exists (reuse it; do NOT rebuild)

| Need | Already in the repo | Gap |
|---|---|---|
| Speech to text | Sarvam `saaras:v4` REST per utterance (`friday/voice/stt`), returns ONE text + detected language + a `confidence` that is only a language probability (`core.models.Transcription`). No alternatives (no n-best). | no second hypothesis, no real per-word confidence |
| Script clean-up | `friday/lang_dev` (`normalise_text`, hook `FRIDAY_DEVANAGARI_INPUT`): Devanagari or mixed script -> Roman Hinglish for the rule banks; original kept. | fixes script only, not mishearings |
| Voice note handling | `friday/chatbot_media/inbound.py` (`VoiceInbound`): download -> STT -> same path as typed text; asks "maine suna: ... sahi hai?" with 2 buttons only when the transcript is not confident. | the doubt test is crude (a language probability), no repair |
| Meaning (cheap first) | `brain/heuristics/interpret.py` (rules, EN/HI/Hinglish) -> trained intent classifier (`friday/learning`, naive Bayes, regression-gated) -> `brain.interpret` LLM with a schema (`CHATBOT_ARCHITECTURE.md` layer 3). | works on whatever text it is given, so a mis-heard name or number flows straight through |
| Memory and references | `tasks/context.build_context` (profile, facts, people, places, vendor history, open tasks, recent turns) and `brain.resolve_references` (rules first, LLM only if unresolved; proposes `new_aliases`). | not used to REPAIR the transcript, only to resolve "mummy ke ghar" style references |
| Intent bucket | `friday/pm/classifier.py` (bucket + category, closed lists, LLM + keyword baseline), PM state machine, `pm/factslots.py` (rules). | consumes text only |
| Live calls | `friday/latency` speculative understanding (starts understanding before the caller finishes), semantic end-of-turn, `FridayBrain.door_turn` for the front door. | fast path must stay under the reply-gap budget |
| Learning | consent-gated redacted transcripts, labels, `friday eval` baseline regression gate (`QUALITY_LOOP.md`). | no labelled set of MISHEARINGS |

So the missing piece is small and specific: **a repair-and-package step** between STT and the existing understanding chain, plus one standard output object.

## 2. The idea in one picture

```
voice note / call audio
   -> STT (Sarvam; optional second opinion on low confidence)          [exists]
   -> script normaliser (lang_dev)                                      [exists]
   -> SPEECH UNDERSTANDER (NEW, small, closed schema)
        a. repair: fix likely mis-hearings using memory (names, places, aliases, recent turns, open tasks)
        b. understand: intent family, slots (who / what / when / where / how much), references resolved
        c. decide: proceed | confirm (one tap) | ask ONE question | fall back to the raw text
   -> UnderstoodUtterance (structured, with a "what I changed and why" list)
   -> existing chain: rules -> classifier -> PM / brain.interpret (bigger LLMs) -> engine
```
The big LLMs never see a raw transcript alone: they get the cleaned text, what was repaired, how sure each slot is, and the original words.

## 3. Naming, and Whisper

* Call it the **Speech Understander** (or "Listener"). Avoid "Whisper" in code: `whisper` already means "announce to the user on a transferred call" in the telephony code.
* OpenAI Whisper is a speech-to-text model, not an understanding model. The repo uses Sarvam STT because it is tuned for Indian languages and phone audio. Whisper is
  worth testing ONLY as a second opinion for utterances Sarvam is unsure about (two transcripts that disagree = a signal to confirm). It must be measured on our own
  Hinglish phone/voice-note audio before it is adopted; no accuracy, price or latency numbers for it are claimed here.

## 4. How the small model is built (layered, cheapest first; the same pattern the repo already uses)

1. **Deterministic repair (no model, no cost):** compare each suspicious word with memory using spelling and sound similarity (Roman and Devanagari): saved people and aliases
   ("Mummy", "Rahul bhaiya"), saved places ("office", "PG"), vendor names from past requests, numbers and times ("pachaas" vs "pachas", "paanch" vs "panch", "kal" vs "call").
   A repair is allowed only if the candidate comes FROM MEMORY or a closed lexicon and the similarity is high.
2. **Small trained model (offline, regression-gated, like the intent classifier):** for intent family and slot hints when rules are unsure.
3. **Small LLM with a strict JSON schema, only when 1-2 are unsure** (same `auto` pattern as `FRIDAY_PLAYBOOKS_LLM_MODE`). Candidates to measure: the cheap OpenAI model already in use, or
   Sarvam's conversational model used for live turns. The model gets a minimal context (not the whole profile), the transcript as quoted untrusted data, and returns the schema only.
4. Anything still unsure -> a single confirm tap or ONE short question (never a menu of questions).

## 5. The output object (closed schema, additive to `core/models.py`, logged in `CORE_CHANGES.md`)

```
UnderstoodUtterance:
  original_text         # exactly what STT returned (always kept)
  corrected_text        # the repaired text the rest of the system reads
  language, script
  repairs: [ {span, from, to, source: memory|lexicon|model, evidence_ref, confidence} ]
  intent_family         # existing Intent / bucket vocabulary, no new free-text labels
  slots                 # who, service/category, when, where, budget ... each {value, confidence, source}
  references            # resolved person_id / place_id (from resolve_references)
  ambiguities           # list of things it could not settle
  decision              # proceed | confirm | ask_one_question | use_raw
  question              # the single question if decision = ask_one_question (PENDING_FOUNDER_APPROVAL wording)
```
Downstream code reads `corrected_text` plus the decision; the LLM-backed steps may also read `repairs` and per-slot confidence in their prompts.

## 6. Safety rules (non-negotiable, enforced in code, not by the model)

* **Grounding:** a repair may only use words present in the transcript, the user's own memory, or a closed lexicon. It never invents a name, price, time, address or phone number
  (same idea as `understand.ground` in the playbook engine). Anything not grounded is dropped.
* **High-stakes fields are never silently changed:** if a repair touches money, a date/time, a phone number, a person to be called, or an address, the decision is at least `confirm`.
  Irreversible actions (booking, calling a real person) always go through the existing approval gates anyway.
* **Secrets:** OTP/PIN/card digits are never repaired, stored or forwarded (the existing safety normaliser runs first and last).
* **Untrusted input:** the transcript is data, never instructions (as in the classifier and PM).
* **Memory is read-only** for this layer. New aliases are only PROPOSED ("kya yeh Rahul bhaiya hain?") and saved after the user confirms, through the existing alias mechanism.
* **Privacy/DPDP:** minimal context in prompts; transcripts used for shadow evaluation only with the existing consent rules, redacted and encrypted, 30-day retention (`QUALITY_LOOP.md`);
  per-user data never leaks across users; "delete everything" removes any learned aliases.
* **No spoken or written wording changes without founder approval** (hear-before-change): the confirm/question lines are new copy and stay PENDING until approved.

## 7. Where it plugs in (file-level; all behind one switch, default OFF)

* Switch `FRIDAY_SPEECH_UNDERSTANDING` (`off | shadow | on`); per-channel sub-switches `..._VOICE_NOTES`, `..._CALLS`.
* **WhatsApp voice notes first:** replace the confidence test in `chatbot_media/inbound.py` (`VoiceInbound.on_inbound`) with the Understander's `decision`; pass `corrected_text` on exactly as typed text.
  Latency here is forgiving (1-3 s is fine).
* **Live calls second:** use ONLY steps 1 and 2 on the hot path (no extra model call unless unsure), feed it through the existing speculative understanding so it adds ~0 ms when the early transcript
  is stable; the reply-gap budget (< 1 s, p95 < 1.5 s) and the 900 ms end-of-speech wait stay untouched. The front door (`door_turn`) and playbooks keep their own closed-intent classification.
* **Downstream:** `ConversationContext` gets an optional `speech: UnderstoodUtterance` (additive field); `brain.interpret`, `pm/classifier`, `pm/factslots` read `corrected_text` and may use the repair list.
* **Learning loop:** every `repairs` entry and every user correction ("nahi, Shreya nahi, Shriya") is a labelled example for `friday review` / `friday eval`; add a held-out "mishearing" set.

## 8. Evaluation and rollout (no real users involved until the numbers pass)

1. Build a labelled set of Hinglish voice-note transcripts with realistic mis-hearings (names, numbers, times, places) from the founder's own test notes and consented transcripts.
2. Metrics: repair PRECISION (a wrong repair is worse than none; gate it like the classifier at >= 98% before any auto-apply), intent accuracy lift over raw text, confirm rate (too many = annoying),
   added latency, added cost per utterance (estimates until measured).
3. **Shadow mode first:** run the Understander on every voice note, log what it WOULD have changed, change nothing. Review with `friday review`.
4. Internal-test on the founder's own notes -> named pilot testers (voice notes only) -> calls last.
5. Kill switch: the single switch above plus `friday pause`; failure of any step falls back to the raw text (never silence, never a stuck conversation).

## 9. Decisions needed from the founder

1. **Scope first:** WhatsApp voice notes only (recommended: forgiving latency, easy to measure) or also live calls in the same build?
2. **Second opinion STT:** test Whisper (or another STT) only for low-confidence utterances, or keep Sarvam alone for now?
3. **When to auto-correct vs ask:** names and amounts always confirm (recommended), small clear fixes (a misheard filler) applied silently?
4. **Small model route:** rules + trained classifier first and a small LLM only when unsure (recommended), or LLM-first for speed of building?
5. **Shadow logging:** may we keep redacted transcripts of the founder's and named testers' voice notes (30 days) for the mishearing set?
6. **Priority vs the pilot:** build in parallel but OFF by default, so it does not delay `GO_LIVE_5_DAYS`?

## 10. Build plan once scope is chosen (small, disjoint files; run the FULL suite before push)

* `friday/speech/` (new package): `understander.py` (orchestrates), `repair.py` (memory/phonetic repair), `schema.py` (UnderstoodUtterance), `shadow.py` (log only), `cli.py` (`friday speech eval|shadow|replay`).
* Tests: unit tests for repair grounding and high-stakes confirm; a mishearing eval set with a regression gate; fake STT/LLM only; no network.
* Docs: this file, `CORE_CHANGES.md` entry for the additive model, `HANDOFF.md` state, wording of every new confirm line listed as PENDING_FOUNDER_APPROVAL.
