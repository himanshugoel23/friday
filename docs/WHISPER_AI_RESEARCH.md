# "Whisper AI" research (PM, 2026-10-28)

Founder question: "a company called Whisper AI, whose job is text to voice: how can we use it in Friday and how will it benefit us?"
Rules: every claim has a source and date; "unverified" = could not confirm; vendor pages are claims, not proof. Prices exclude GST.
Exchange rate used for INR conversions: about INR 88 per USD (my assumption, not sourced). Chars per spoken minute assumed 800-1,000 (my estimate, unverified).

## 1. What does he most likely mean? (honest ambiguity)

I could NOT find any company literally called "Whisper AI" whose job is text-to-speech. Search on 2026-10-28 returned only speech-to-TEXT products
(source: web search, 2026-10-28; G2 seller page https://www.g2.com/sellers/whisperui). Closest matches, most likely first:

| # | Candidate | Does text to voice? | Likelihood |
|---|---|---|---|
| a | OpenAI Whisper (open-source model + API) | NO, speech to text. Name collision is the likeliest cause: OpenAI's TTS is a different model (gpt-4o-mini-tts), same company | High |
| b | Wispr Flow (voice dictation, speech to clean text; Hinglish model + Android in India) | NO, text OUT of voice. https://techcrunch.com/2026/05/09/voice-ai-in-india-is-hard-wispr-flow-is-betting-on-it-anyway/ (2026-05-09) | Medium (name sounds like "whisper") |
| c1 | WhisperUI (STT + TTS web platform built on OpenAI Whisper) | Yes, small product, no G2 reviews; track record unverified. https://www.g2.com/sellers/whisperui | Low |
| c2 | Whisper.ai, Inc. (hearing aids / transcription; acquired Sep 2025 by Evertrace ApS per Preqin summary) | No. https://www.preqin.com/data/profile/asset/whisper-ai--inc-/395466 | Low |
| c3 | WhisperAI.com (dictation Chrome extension) | No. https://chromewebstore.google.com/detail/hkoppnnlmjhndhmjpoegdpjfadkjoonn | Low |
| d | Real text-to-voice vendors for India (Sarvam Bulbul = what we use; ElevenLabs; Smallest.ai; Cartesia; Azure/Google; OpenAI TTS) | Yes | What he probably NEEDS |

Conclusion: the founder probably heard "Whisper" (OpenAI) or "Wispr" and a vendor demo of voices. Ask him where he saw it (video, post, person);
until then treat the real question as "is there a better or cheaper text-to-voice than Sarvam Bulbul for Ritu, and does Whisper help elsewhere?"

## 2. Candidate fact sheet (verified V = from vendor docs/page fetched; C = vendor claim; U = unverified)

### Sarvam Bulbul (TTS) and Saaras (STT): BASELINE we already use
- Price V: Bulbul v3 INR 3.00 per 1,000 chars; Bulbul v4 Flash INR 1.00 per 1,000 chars (pay as you go); STT INR 0.49 per min incl. streaming.
  https://docs.sarvam.ai/api/getting-started/pricing.md (fetched 2026-10-28). Rough TTS cost per spoken minute: v3 about INR 2.4-3.0, v4 Flash about INR 0.8-1.0 (my arithmetic).
  An older third-party page called INR 30 per 10K chars a "beta rate"; the official docs now show the figures above.
- Hinglish/Hindi C: built for Indian languages and code-switching. Latency C: "under 250 ms first byte" on WebSocket. 8 kHz C: optimized, works with Exotel/Twilio.
  https://www.sarvam.ai/apis/text-to-speech.md (2026-10-28, vendor claims).
- Our own measurement V: Sarvam streaming and REST first audio about 260 ms uncached, 8 kHz, from our measurement (docs/LATENCY.md, 2026-10).
- Data: India-based vendor, so audio stays in India (best fit for DPDP); retention terms still to be confirmed in writing (docs/SARVAM_QUESTIONS.md).
- Note: docs/LATENCY.md says the live call uses bulbul:v3. v4 Flash is cheaper; we have not heard it. Not tested = unverified quality.

### (a) OpenAI Whisper (STT only) and OpenAI TTS
- Whisper: open weights (permissive licence, from OpenAI repo; licence text not re-checked today = U) and API. API price C: whisper-1 and gpt-4o-transcribe
  USD 0.006 per min (about INR 0.53), gpt-4o-mini-transcribe about USD 0.003. Third-party summaries only; check
  https://openai.com/api/pricing before budgeting. Source: https://diyai.io/ai-tools/speech-to-text/openai-whisper-api-pricing-2026/ (2026).
- Hinglish quality: vendor-run benchmarks put Whisper large-v3 well behind Saaras-v3: CoSHE-500 Hinglish WER 29.74 vs 11.47 (lower is better), and
  Whisper tends to write English words in Devanagari, which hurts scoring. Source: https://huggingface.co/Trelis/tara and https://friendli.ai/models/Trelis/whisper-hinglish-preview
  (2026). Run by a competitor-model author, NOT independent. On pure Hindi the gap is small (13.79 vs 12.32 mean over 7 sets, same source).
- Latency: batch model, not streaming by design (realtime tier of the API: U). Our own ElevenLabs/Sarvam STT timings are in docs/LATENCY.md; none for Whisper.
- Telephony 8 kHz: not tested by us (U). Public reports of Whisper hallucinating on silence/noise are widely known (general knowledge, not re-verified today).
- OpenAI TTS (gpt-4o-mini-tts): C price about USD 0.015 per spoken min (about INR 1.3), token-billed, estimate only.
  https://community.openai.com/t/understanding-gpt-4o-mini-tts-pricing-input-characters-cost/1151816 (2025). Hindi/Hinglish quality: U, nothing found. 8 kHz: U (output formats not checked).
- Data: US servers for inference. India data residency covers data AT REST only, inference still runs abroad; no official statement that the API meets DPDP.
  https://ai.icai.org/articles_details.php?id=235 and https://ecorpit.com/openai-zero-data-retention-limits-endpoints-india-residency-2026/ (2026; second source is a blog, treat as U).
  Default abuse-monitoring retention reported as 30 days (U). Self-hosting open Whisper on our own server avoids this (audio stays on our DigitalOcean box).
- Free alternative we already use: faster-whisper "small" was used by the PM team to transcribe the ElevenLabs ad (docs/COMPETITORS.md update i).

### (b) Wispr Flow (dictation)
- Product: speech to clean typed text on Mac/Windows/Android/iOS. Hinglish model beta then Android launch in India; India second-largest market. Price in India:
  TechCrunch says INR 320 (about USD 3.4) per month on annual plan vs USD 12 global; other outlets disagree on the billing period, so U.
  https://techcrunch.com/2026/05/09/voice-ai-in-india-is-hard-wispr-flow-is-betting-on-it-anyway/ (2026-05-09).
- Developer API: none found (U). No TTS. Relevance to Friday: a user-side tool, and proof that Hinglish voice-to-text has demand. NOT a vendor for us.
  Idea worth stealing: its "clean the transcript" step (remove ums, fix numbers) is what friday/speech already aims at.

### (d) Other text-to-voice vendors (India relevance)
- ElevenLabs: Flash v2.5 lists Hindi, about 75 ms model latency (C), USD 0.05 per 1,000 chars on API (about INR 4.4 per 1,000 chars, 1.5x-4x Sarvam),
  billed in USD. Source: https://replicate.com/elevenlabs/flash-v2.5 and https://invideo.io/blog/ai-voice-model-pricing/ (2026, third-party).
  Our OWN measurement V: Flash streaming first audio 170-296 ms, native 8 kHz (ulaw_8000), already wired as opt-in (docs/LATENCY.md, 2026-10-12).
  Data: US/EU, audio leaves India; our SECURITY.md lists it as "fallback only". Hinglish quality: to judge by ear (docs/LATENCY.md says so).
- Smallest.ai (Lightning, Indian company): C TTFB as low as 100 ms, Hinglish code-switching native, native 44.1 kHz in its test (8 kHz not shown). Vendor blog only.
  https://smallest.ai/blog/top-fastest-text-to-speech-apis-in-2026 (2026). Price: not found (U). Worth a trial because Indian and fast, but unproven.
- Cartesia Sonic: Hindi support and price NOT confirmed (U). Only data is Sarvam's own chart saying Bulbul v3 beats Sonic-3; discount it (competitor).
- Azure / Amazon Polly: Gnani roundup (vendor blog, 2026-01) lists 400-700 ms latency and Hindi MOS about 3.6-4.0 out of 5. Slower; skip.
  https://www.gnani.ai/resources/blogs/best-text-to-speech-hindi-tools-in-2026-gnani-ai-google-translate-alternatives
- No independent, neutral Hinglish TTS benchmark found. Every comparison above is from a vendor or an affiliate.

## 3. Benefit and risk for Friday, per use case

| Use case | Whisper (OpenAI, STT) | OpenAI TTS / any "Whisper AI" TTS | Net |
|---|---|---|---|
| Live call voice (Ritu) | No benefit: it does not speak. Do not use for live STT (batch, weaker Hinglish, latency) | Unproven Hindi, US latency from Bangalore (U); would break the "India-hosted audio" story | Keep Sarvam; test v4 Flash for cost and Smallest.ai / ElevenLabs for quality |
| WhatsApp voice-note replies | Nothing | Latency does not matter here, only naturalness and price: best place to try a second TTS (ElevenLabs quality, or v4 Flash for cost) | Good low-risk test bed |
| Listening kit / pronunciation | Whisper can act as an independent judge: transcribe our TTS output and flag mispronounced names/numbers (round-trip check) | Each new TTS needs its own pronunciation fixes; our Sarvam dictionary does not carry over (docs/LATENCY.md) | Useful as a checker, not as a voice |
| Speech understanding second opinion | Reasonable third opinion for hard clips and for offline QA of recorded calls (self-host, no cost per call). Weak on Hinglish script (Devanagari for English words) so normalise before comparing | n/a | Offline only; never in the live path |
| Cost per minute | STT: Sarvam INR 0.49 vs Whisper API about INR 0.53, no saving; self-host is free per minute but needs a GPU/CPU box (cost U) | OpenAI TTS about INR 1.3 per min (C); v3 about INR 2.4-3.0; v4 Flash about INR 0.8-1.0; ElevenLabs Flash about INR 3.5-4.5 | The only real saving is Bulbul v4 Flash, still Sarvam, if quality holds |

Risks: (1) wrong vendor chosen because of a name; (2) audio leaving India (DPDP, user trust, our own SECURITY.md); (3) 8 kHz phone quality differs from demos;
(4) pronunciation dictionary, pace and the approved voice (Ritu) are tuned to Sarvam; any switch is a hear-before-change event (CLAUDE.md rule 3);
(5) vendor benchmarks are marketing; only our own blind test counts.

## 4. Ranked recommendation (what to try first)

1. Ask the founder where he heard "Whisper AI" (10 minutes; may end the question).
2. Bulbul v4 Flash vs v3 (same vendor, same API, about 3x cheaper per character): the safest saving. Test first.
3. Smallest.ai Lightning and ElevenLabs Flash v2.5 as quality challengers (both Hindi/Hinglish capable per vendors); ElevenLabs is already wired, so it is cheap to test.
4. OpenAI Whisper self-hosted as an OFFLINE checker for the listening kit and QA (round-trip transcribe our TTS lines). Not for live calls.
5. OpenAI gpt-4o-mini-tts only if a quick sample sounds good in Hindi (U today); lowest priority because of US latency and data location.
Do NOT adopt Wispr Flow (no API, wrong direction) or WhisperUI (unknown vendor).

## 5. Bake-off design (small, blind, cheap)

- Lines: the same 20 Hinglish lines in Roman script and Devanagari as Friday really says them: 4 greetings, 4 with names (Indian names, vendor names), 4 with numbers/prices/dates/times
  (e.g. "teen sau pachaas rupaye", "Tuesday 11:30 baje"), 4 with English loanwords mid-sentence, 4 empathy/hold/apology lines. Taken from the real script bank, frozen before the test.
- Voices: Sarvam v3 Ritu (control), Sarvam v4 Flash (best female match to Ritu), ElevenLabs Flash (a Hindi female voice, founder's candidates in docs/LATENCY.md), Smallest.ai (one female voice), optional OpenAI mini-tts.
  Same pace target; render at 8 kHz and play through a real phone call to the listeners' phones (allow-listed numbers only, per CLAUDE.md rule 5), plus 24 kHz for voice notes.
- Listeners: the same 5-8 people for every clip (founder + native Hindi speakers + 2 who dislike bots), same phone, same room. Files renamed to random codes, order shuffled per listener.
- Scores per clip (1-5): naturalness, clarity on phone, correct pronunciation (names/numbers), warmth, "would you stay on this call". Plus a pass/fail on any mispronounced number or name.
- Objective columns: first-audio latency (p50/p95 over 20 runs, measured FROM the Bangalore server, not the sandbox), cost per line from the price tables, failure count.
- Decision rule (set before listening): a challenger replaces or joins Sarvam only if mean naturalness is at least 0.3 above the control AND zero number errors AND p95 first audio under 500 ms
  AND the data-location answer is acceptable. Otherwise keep Sarvam; use the cheaper v4 Flash if it is within 0.2 of v3.
- Second mini-test (STT): 30 real phone clips (with consent), compare Saaras, ElevenLabs Scribe and self-hosted Whisper large-v3 on word error for numbers, times, names (docs/VOICE_NEXT_STEPS.md item 6).
- Output: a one-page result in this file as a dated update; no voice change goes live without founder approval after hearing samples.

## 6. Could not verify (plainly)

- Any company named "Whisper AI" that does text-to-speech (none found).
- Hindi/Hinglish quality of OpenAI TTS, Smallest.ai and Cartesia; Cartesia Hindi support and price; Smallest.ai price; 8 kHz suitability of all but Sarvam and ElevenLabs.
- Official OpenAI pricing page (only third-party mirrors reached) and any DPDP statement from OpenAI, ElevenLabs, Smallest.ai.
- Independent (non-vendor) Hinglish benchmarks; the Whisper vs Saaras numbers come from a rival-model author.
- Real INR per spoken minute: depends on chars per minute (my assumption) and the exchange rate.

## Update log
- 2026-10-28: first version (PM agent).
