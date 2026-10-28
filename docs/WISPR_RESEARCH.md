# Wispr Flow research (PM, 2026-10-28; replaces docs/WHISPER_AI_RESEARCH.md)

Founder clarified the spelling: "Wispr" (W-I-S-P-R). Earlier question: "Whisper AI, job is text to voice".
Plain finding: Wispr Flow is NOT text-to-voice. It is the opposite: you speak, it types clean text (voice dictation). The founder's "text to voice" is a mix-up of direction.
Rules: every claim has source + date; V = read on vendor page today, C = vendor claim, U = unverified. Prices exclude GST. INR at about 88 per USD (my assumption).

## 1. Wispr Flow in one paragraph
Voice dictation app (Mac, Windows, iPhone, Android): speak anywhere, it removes ums, fixes self-corrections, punctuates, adapts tone to the app. Hinglish model
(beta, then Android in India) and India-specific pricing launched 2026; India is its second-largest market. Source: https://techcrunch.com/2026/05/09/voice-ai-in-india-is-hard-wispr-flow-is-betting-on-it-anyway/ (2026-05-09).
Funding: one analysis page says USD 30M raised (U, third party): https://www.extruct.ai/hub/wisprflow-ai/ . India traction: Hinglish pushed growth up; India about 14% of installs but 2% of in-app revenue (one secondary report, U): https://ecosistemastartup.com/?p=80323

## 2. Facts asked for

| Question | Finding | Status |
|---|---|---|
| Public API / SDK? | YES, a "Voice interface API": WebSocket `/ws` (recommended, streaming) and REST `/api`; API key (backend) or client-side access tokens; a "Warm Up API" to cut latency. https://api-docs.wisprflow.ai (2026-10-28) | V |
| How do we get access / partner terms? | Not stated on the docs pages I could read; a "Usage & Billing" page exists but its contents were not retrievable. Contact Wispr | U |
| API price | Not found | U |
| App price | Free: 2,000 words/week (Mac/Windows), 1,000 (iPhone), Android unlimited for a limited time. Pro USD 15/month (about USD 12 annual), 14-day trial. https://wisprflow.ai/pricing (via search, 2026-10-28). India: INR 320 (about USD 3.4) per month on annual plan per TechCrunch; other outlets say it is annual, so billing period U | V (US) / U (India) |
| Hindi / Hinglish | "100+ languages" (V on API page); Hinglish model exists in the app (TechCrunch). Hindi/Hinglish accuracy numbers: none found | U |
| Latency | WebSocket + warm-up advertised as lower latency; NO millisecond figure published | U |
| 8 kHz phone audio | Not documented in what I could read; consumer product is built for microphones, not narrowband phone lines | U |
| Data handling | Transcription is always in the cloud. "Privacy Mode" = zero retention of audio/transcripts/edits, default for Enterprise, not clearly default for individuals. Some requests go to third-party model providers (ZDR with some, standard terms with others). Claims SOC 2 Type II, ISO 27001, HIPAA (Enterprise). https://wisprflow.ai/data-controls and https://docs.wisprflow.ai/articles/3467817258-security-and-compliance-faq (2026-10-28) | C |
| Compliance doubt | One Medium post says their earlier audit vendor was in a fake-audit investigation (Mar 2026) and a re-audit was unfinished; not confirmed from a primary source | U |
| Where audio goes | Wispr cloud + sub-processors, almost certainly outside India (region not stated). For DPDP: cross-border transfer, needs consent and a processor agreement | U |
| Licence | Closed SaaS. No open weights, cannot self-host | V |
| Third-party API catalog | An unofficial catalogue lists many "Wispr AI" API specs at api.wisprflow.ai (Transform, Voice Actions, etc.). Unofficial, may be stale: https://apis.apievangelist.com/store/wispr-ai-platform-api/ | U |

## 3. What Friday already copied from Wispr (friday/speech, built 2026-10-26)
- The "Wispr-style clean-up" idea is built as the Speech Understander (docs/SPEECH_UNDERSTANDING.md; docs/SCOPE_SETTLED_2026-10-26.md): one small LLM call turns a noisy transcript
  into the user's meaning (fillers, stutters, self-corrections, misheard names fixed from memory), hard deadline (voice notes 3 s, calls 0.9 s), fallback model -> rule floor -> raw words,
  original always kept. Never applied to a vendor's speech (a silent fix could change a quoted price).
- Friday goes BEYOND Wispr in three ways Wispr cannot do: memory of the user's names/places/shops, grounding rules (no invented number/day/name), and acting on the result (booking, call).
- NOT yet measured: real-model quality (the live eval `friday speech eval --live` must run on the server first).

## 4. Could Friday use Wispr's API? Verdict (FOUNDER DECISION 2026-10-28: no API key/partner access from Wispr, so we use OUR OWN friday/speech)
Note: Wispr's public docs DO describe a Voice interface API (section 2), but I could not verify any way to obtain access or terms, so it is moot. Reasons below stay valid.
- Replacing Sarvam Saaras STT with Wispr: NO for now. Unknown Hinglish accuracy, unknown 8 kHz behaviour, no latency figure, audio leaves India, no published API price, and it is built to clean
  text for a typist, not to feed an agent (it may rewrite words, which our grounding rules forbid). Sarvam STT is INR 0.49/min with streaming, Indian-hosted (https://docs.sarvam.ai/api/getting-started/pricing.md, 2026-10-28).
- As a WhatsApp voice-note cleaner (not live): possible but pointless; our Speech Understander already does this, with memory, for the cost of one small LLM call.
- Worth ONE email: ask Wispr for API pricing, Hinglish WER, 8 kHz support, region, and DPA/partner terms. Cost: 15 minutes; only a possible third STT opinion.
- Borrow, do not buy: their product lessons (Hinglish launch drove growth; "Command Mode" = voice edits like "make it shorter"; context-awareness toggle). Their pricing warns that Indians
  install a lot but pay little, so Friday's pricing must not rely on a Wispr-style subscription alone.
- Threat level: LOW. Not a caller, no booking. It would only matter if Wispr added "act on what I said" agents; watch quarterly.

## 5. OpenAI Whisper and text-to-voice (short)
- OpenAI Whisper = speech to text only (open weights + API, about USD 0.006/min, about INR 0.53; third-party summary https://diyai.io/ai-tools/speech-to-text/openai-whisper-api-pricing-2026/).
  Vendor-run benchmarks (not independent) put it behind Saaras on Hinglish: 29.74 vs 11.47 WER on CoSHE-500 (https://huggingface.co/Trelis/tara). Use only as an OFFLINE checker
  (self-hosted, audio stays with us), e.g. transcribe our TTS output to catch mispronounced names/numbers. Not for live calls.
- No company literally named "Whisper AI" doing text-to-speech was found (search 2026-10-28; closest: WhisperUI https://www.g2.com/sellers/whisperui, unverified small product).
- If the real need is a better or cheaper voice for Ritu (text to voice), the candidates and prices are:
  Sarvam Bulbul v3 INR 3.00 per 1,000 chars (about INR 2.4-3.0 per spoken minute, my estimate), Bulbul v4 Flash INR 1.00 per 1,000 chars (same pricing page; quality not yet heard by us),
  ElevenLabs Flash about USD 0.05 per 1,000 chars (third party, https://invideo.io/blog/ai-voice-model-pricing/; our own measured first audio 170-296 ms, 8 kHz, docs/LATENCY.md),
  OpenAI gpt-4o-mini-tts about USD 0.015 per min (estimate; Hindi quality U), Smallest.ai Lightning (vendor claims about 100 ms; price U; https://smallest.ai/blog/top-fastest-text-to-speech-apis-in-2026).
  Cartesia Hindi support not confirmed. No independent Hinglish TTS benchmark exists; all comparisons are vendor-made.
- Data: OpenAI India residency covers data at rest only, inference stays abroad (https://ai.icai.org/articles_details.php?id=235); ElevenLabs is US/EU (docs/SECURITY.md: fallback only).

## 6. Per use case (summary)
| Use case | Wispr Flow | OpenAI Whisper | Better TTS vendor |
|---|---|---|---|
| Live call voice | none (does not speak) | none | keep Sarvam; test v4 Flash for cost |
| WhatsApp voice-note replies | none | none | best place to trial a second voice |
| Listening kit / pronunciation | none | offline round-trip checker | each vendor needs own pronunciation fixes |
| Speech understanding second opinion | possible 3rd opinion via API, if terms OK (U) | offline QA opinion | n/a |
| Cost per minute | unknown (no API price) | about INR 0.5 STT, no saving vs Sarvam | v4 Flash about INR 0.8-1.0 vs v3 about INR 2.4-3.0 |

## 7. MAIN RECOMMENDATION: improve our own friday/speech by copying Wispr Flow's features, and measure each
Wispr feature (from its public product descriptions, TechCrunch 2026-05-09 and wisprflow.ai) -> status in friday/speech -> how we evaluate:
| Feature to copy | Today in friday/speech | Next step | Eval (build a 60-100 clip Hinglish set from consented real voice notes, plus recorded team clips) |
|---|---|---|---|
| Hinglish transcription accuracy | Sarvam Saaras STT upstream; Understander fixes after | Keep Saaras; compare with ElevenLabs Scribe and self-hosted Whisper as offline second opinion | WER and number/time/name error rate with a script-safe normaliser (Roman vs Devanagari must not count as errors); report per clip type |
| Filler removal ("um", "matlab", "basically") | rules.py floor + model | Add Hinglish filler list tests | Precision: no meaningful word removed; recall: share of fillers removed |
| Self-correction ("kal nahi, parso") | plain cases in rules; model for the rest | Add 30+ real patterns (day, time, amount, name) | Exact-match on final intent field; any invented/changed number = hard fail (grounding rule) |
| Personal dictionary (names, shops) | memory.py aliases, active after 2 uses or 1 tap | Let the user add/remove words; seed from contacts the user shares | Name accuracy before vs after dictionary; false-fix rate |
| Tone matching / mirroring | Persona decision: Friday mirrors the user | Keep cleaning for meaning, mirror tone only in replies | Blind rating of 20 replies by 5 listeners: "sounds like me" 1-5 |
| Command-style edits ("make it shorter") | not built | Park until a use case (drafting messages) exists | n/a |
Always keep: original kept, fallback chain, deadlines (3 s notes, 0.9 s calls), never on vendor speech. Gate: ship a change only if error rate drops with zero new number errors.
Eval run: `friday speech eval --live` on the server first, then extend the case file; PM to define cases, EM to wire it.

## 7b. Other next steps
1. Run `friday speech eval --live` on the server (measures our Wispr-style layer for real).
2. Optional: email Wispr for terms only if the founder changes his mind (not needed).
3. Voice bake-off, only if the founder wants a better or cheaper Ritu: 20 Hinglish lines (4 greetings, 4 with names, 4 with numbers/dates/times, 4 with English words mid-sentence, 4 empathy/hold lines),
   frozen before the test; voices: Sarvam v3 Ritu (control), v4 Flash, ElevenLabs Flash, Smallest.ai, optional OpenAI mini-tts; render at 8 kHz and play over a real call to allow-listed numbers only,
   plus 24 kHz for voice notes. Same 5-8 listeners, same phone, random file codes, shuffled order. Score 1-5: naturalness, phone clarity, pronunciation, warmth, "would stay on this call";
   plus pass/fail on any wrong number or name. Measure first-audio p50/p95 from the Bangalore server. Rule set before listening: a challenger wins only if +0.3 naturalness, zero number errors,
   p95 under 500 ms and acceptable data location; use v4 Flash if within 0.2 of v3. Any voice change needs founder approval after hearing samples (CLAUDE.md rule 3).
5. STT mini-test: 30 consented phone clips, Saaras vs ElevenLabs Scribe vs self-hosted Whisper (and Wispr only if they give terms) on errors in numbers/times/names (docs/VOICE_NEXT_STEPS.md item 6).

## 8. Could not verify
- Wispr API access route and price; Hinglish/Hindi accuracy; latency in ms; 8 kHz support; data region; the audit-vendor story.
- Any "Whisper AI" TTS company; Hindi quality of OpenAI TTS, Smallest.ai, Cartesia; official OpenAI price page (third-party mirrors only).
- Real INR per spoken minute (depends on my assumed 800-1,000 chars/min and exchange rate).

## Update log
- 2026-10-28: first version as Whisper AI research; rewritten same day around Wispr Flow after the founder's spelling correction (PM agent).
