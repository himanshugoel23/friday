# Voice agent: next steps (21 Oct 2026)

Built already: Ritu voice on Sarvam with streaming speech output, barge-in, early/streaming speech-to-text (off), reply-gap logging, call-turn model on Sarvam, speculative understanding + streamed replies + small intent classifier (all off), 297 pending consumer lines, simulated callees. Still running: semantic end-of-turn and a trained voice-activity model (builder).
Rule: nothing spoken or sound-changing goes live without the founder hearing it.

## Ranked next steps
1. **Real-call evidence first (slice 1 calls).** The first real calls decide everything else. Record every test call (the founder's own phone), log reply gaps per turn, mark where it felt wrong. Turn the three speed switches on one at a time (classifier, then early understanding with streaming speech-to-text, then streamed replies) and compare gaps.
2. **Finish semantic end-of-turn and the trained voice-activity model** (builder running), then try each on real calls, noisy rooms included, and keep it only if the cut-off rate stays under 2%.
3. **A listening kit for approval.** The same ten important lines (opening, "are you an AI?", stop, wrong number, voicemail, confirm a time, a price readback) in today's treatment and in the new ones, generated on the server with the real voice. Founder approves or edits each; approved versions become the pre-rendered set.
4. **Backchannels and "ek second" holds.** Pre-rendered "haan ji / achha / hmm / theek hai", inserted at natural pauses (cap one per 4 s, never over speech, off for elders), plus a short hold line when the model is slow. Needs approved audio.
5. **Natural reading of numbers, times, prices and phone digits, and per-line prosody.** A deterministic normaliser ("500" -> "paanch sau", "sawa paanch baje", phone numbers in groups of 3-4-3 with pauses) and a per-line-type pace and pause profile (numbers slower, questions with a lift, bad news softer). Preview audio before it replaces the current reading.
6. **Speech-to-text comparison on real audio.** Run Sarvam REST, Sarvam streaming and ElevenLabs on the same recorded calls (with consent), compare word error on numbers, times and names, and choose per language. Streaming partials are only worth it if they are accurate on real phone speech.
7. **A replay and regression harness from real calls.** Masked transcripts and audio clips become tests for end-of-turn, intent and number reading, so every change is checked on real examples and never gets worse.
8. **Voices per relationship** (a warmer, slower voice for elders), after step 3 proves the process.

## What I can build now (no keys or real calls needed)
The backchannel engine, the number/time reader, per-line prosody profiles, the listening-kit generator (to run on the server), the replay harness skeleton. All default off and previewable. To avoid merge conflicts with the running builder, I start this bundle when it lands.
