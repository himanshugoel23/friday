# Voice probe results: Sarvam realtime STT and Bulbul TTS (live, 2026-10-22)

Probes: `deploy/probe_saaras_realtime.py`, `deploy/probe_bulbul_ws.py` (+ `deploy/probe_voice_common.py`). Real Sarvam
credits, run from the build sandbox (not the Bangalore droplet). No defaults were changed.

**Caveat first.** All audio is *synthetic*: Sarvam TTS (male voice `aditya`, 8 kHz) turned into mu-law, streamed
in real time in 20 ms frames, with digital silence before and after. No line noise, no background, no real accents,
no hesitations, not a Vobiz phone leg. Absolute numbers (and especially the truncation/WER findings) must be
confirmed on a real call. Network time is sandbox-to-Sarvam, which differs from the droplet.

**Blocked / failed.** Sarvam answered `quota_exceeded` ("Credits exhausted") on the realtime socket during the very last
run, so the `silence 250 ms` variant has only 4 of 10 utterances and no further tests were run. No HTTP 401/402 earlier.
The docs site was reachable by `curl` only (the WebFetch tool could not resolve it); protocol taken from
`docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws.md`, `.../text-to-speech/stream.md` and the changelog.

## Protocols found
- STT realtime: `wss://api.sarvam.ai/speech-to-text-realtime/ws?language_code&model=saaras:v3-realtime|saaras:v4&stream_type=fast|balanced|simulated&encoding=mulaw&sample_rate=8000&silence_duration_ms=500(default)&endpointing=vad|manual`.
  `saaras:v3-realtime` is the default; the changelog (2026-09-03) added `saaras:v4` on the same socket. This is the
  endpoint `friday/voice/stt/sarvam_stream.py` already uses, so "new endpoint vs existing client" is the same wire path:
  the existing client is measured as-is and a raw client is used for the settings variants.
- TTS WebSocket: `wss://api.sarvam.ai/text-to-speech/ws?model=bulbul:v3&send_completion_event=true`; client messages
  `config` (`language_code, speaker, pace, temperature, speech_sample_rate, output_audio_codec, dict_id, min_buffer_size, max_chunk_length`),
  `text`, `flush`, `ping` (docs list no cancel/clear message).

## TEST 1: speech-to-text (10 Hinglish utterances, 0.9 to 2.4 s each)
"End of speech" = the instant the last speech frame is sent. All times in ms. WER is word error against the known
text, best of the Roman / Devanagari / digit spellings (the STT answers in Devanagari; "हेयर कट" vs "हेयरकट" spacing
and "बियर्ड" variants count as errors, so WER is a rough upper bound; 0.15 and 0.22 are spelling/spacing, not misheard words).

| Path | Final after end of speech p50 / p90 | First partial after speech START p50 / p90 | WER (mean) |
|---|---|---|---|
| REST saaras:v4 (`SarvamSTT`), call time on speech + 340 ms silence | 1487 / 1635 (+340 ms before it is fired = about 1830 from end) | none | 0.02 |
| Existing streaming client `SarvamStreamSTT` (v3-realtime, fast, silence 300) | **732 / 746** | 603 / 627 | 0.04 |
| Raw WS v3-realtime, fast, silence 300 (current settings, re-run) | 735 / 754 | 583 / 641 | 0.04 |
| Raw WS v3-realtime, fast, silence 500 (doc default) | 913 / 952 | 588 / 621 | 0.04 |
| Raw WS v3-realtime, fast, silence 200 | 639 / 679 | 591 / 617 | 0.10 (1 of 10 cut mid-sentence) |
| Raw WS v3-realtime, fast, silence 150 | 563 / 584 | 590 / 613 | 0.17 (2 of 10 cut mid-sentence) |
| Raw WS v3-realtime, fast, silence 250 | 654 / 664 (n=4 only, credits ran out) | 622 / 669 | 0.06 (n=4) |
| Raw WS v3-realtime, balanced, silence 300 | 726 / 762 | **1010 / 1034** | 0.04 |
| Raw WS saaras:v4, fast, silence 300 | 742 / 765 | 592 / 624 | 0.02 |

Other measured facts (silence 300): the server's `vad.speech_end` arrives about 657 ms after the end of speech and the
final about 75 ms after that. A partial that already equals the final text exists at p50 629 / p90 699 ms (8 of 10
utterances; 2 differ only in punctuation or spelling), i.e. about 100 ms before the final. The websocket opens in
about 910 ms from the sandbox (once per call, not per turn). With silence 150 and 200 the server closed an
utterance at the natural comma pause ("नहीं सर," ... "अभी फ्री नहीं है") and delivered a truncated first final; the
probe stops at the first final, so those rows show what an early cut does, not what the second final would add.

Per utterance (ms; client = existing `SarvamStreamSTT`, raw = raw socket with the same settings):

| utt | text | REST call | client first partial / stable / final | raw first partial / stable / final | v4 final |
|---|---|---|---|---|---|
| u01 | haircut ke kitne paise lagenge | 1439 | 645 / 501 / 706 | 655 / 498 / 703 | 721 |
| u02 | kal shaam paanch baje ka slot hai | 1533 | 574 / 691 / 742 | 553 / 712 / 734 | 728 |
| u03 | haan ji bataiye | 1389 | 607 / 593 / 706 | 617 / 581 / 691 | 736 |
| u04 | chaar sau rupaye | 1487 | 599 / - / 683 | 645 / - / 697 | 705 |
| u05 | nahi sir abhi free nahi hain | 1607 | 621 / 637 / 724 | 571 / 635 / 728 | 748 |
| u06 | theek hai main parso aa jaunga | 1488 | 609 / 733 / 747 | 589 / 347 / 751 | 728 |
| u07 | beard trim aur haircut dono karna hai | 1886 | 625 / 619 / 726 | 577 / 623 / 724 | 787 |
| u08 | kya aap sunday ko khule hain | 1282 | 560 / 655 / 746 | 587 / 677 / 759 | 752 |
| u09 | rukiye main calendar dekh ke batata hoon | 1577 | 593 / - / 746 | 609 / - / 762 | 754 |
| u10 | ji bilkul main shaam ko call karta hoon | 1399 | 578 / 578 / 737 | 575 / 693 / 733 | 762 |

("stable" = first moment a partial equalled the final text; "-" = never, because the partial differed from the final in
spelling/punctuation. First partial is measured from the start of speech, so for a 1 s word it lands near the end.)

## TEST 2: text-to-speech (10 lines of 49 to 153 characters)
bulbul:v3, speaker `ritu`, **pace 0.9** (set via `FRIDAY_TTS_SPEAKING_RATE=0.9`; the sandbox default is 1.0 and a first
run at 1.0 gave the same picture: HTTP stream first audio p50 425, WS warm 389, WS cold 1213, REST 1244), temperature 0.9,
8 kHz, pronunciation dictionary ON (the id in `var/tts/dict_id.json` was sent on every path). Paths interleaved per line.

| Path | First audio p50 / p90 | Total p50 / p90 |
|---|---|---|
| REST `POST /text-to-speech` (`synthesize`) | 1222 / 2271 | same (audio only arrives complete) |
| HTTP stream `POST /text-to-speech/stream` (in use; connection already open) | **481 / 506** | 1077 / 1291 |
| WebSocket, persistent connection reused (warm) | **463 / 471** | 1063 / 1223 |
| WebSocket, new connection + config per line (cold; includes about 790 ms connect) | 1259 / 1403 | 1940 / 2117 |

WebSocket settings: the config message accepted `speaker=ritu`, `pace=0.9` (output was longer than at 1.0: 5.1 s vs 4.7 s
average), `temperature=0.9`, `speech_sample_rate=8000`, `output_audio_codec=linear16` (raw PCM, no WAV header, so no
parser needed) and `dict_id`, all without error, i.e. the same voice/pace/temperature/dictionary settings are supported.
Not verified: that the dictionary changes the *sound* on the WebSocket (needs an ear test; not run). No server-side
cancel exists in the documented client messages, so barge-in means closing the socket and paying the connect again.

## TEST 3: proposed changes (nothing was changed)
Measured = from the tables above. Guess = reasoning, not tested.

| Setting | CURRENT | PROPOSED | Expected saving | Basis |
|---|---|---|---|---|
| STT endpoint | Realtime WS `saaras:v3-realtime` (if the leg is on REST fallback: saaras:v4 REST) | Keep realtime WS. Do not fall back to REST except on failure | WS vs REST: about 1100 ms (REST 1487 + 340 early start vs 735 final) | Measured |
| STT model | v3-realtime | Keep. saaras:v4 realtime is equal in speed (742 vs 735) and slightly cleaner text (WER 0.02 vs 0.04, spelling only); it also supports `keyterms` (names) | 0 ms | Measured; keyterm benefit is a guess |
| stream_type | fast | Keep fast. `balanced` delays the first partial to 1010 ms with no gain in final | 0 (balanced would cost +420 ms to first partial) | Measured |
| Server `silence_duration_ms` | 300 | 200 only after real-call tests; 250 as a cautious step | 200: about 95 ms (639 vs 735); 250: about 80 ms (4 samples only); 150: about 170 ms but 2 of 10 sentences cut | Measured (small n); the cut risk on real, hesitant callers is a guess and is likely worse than here |
| Early commit on stable partial (`stable_ms` 220, 6 words) | commit when a partial is unchanged for 220 ms | Not helpful as set: the matching partial appears at about 629 ms, +220 ms = about 850 ms, later than the server final (about 735). Lower `stable_ms` to about 80 ms for short answers would commit near 710 ms | about 25 to 100 ms at best | Measured partial timing; the effect of 80 ms is a guess and risks committing half a phrase |
| TTS endpoint | HTTP stream | Keep HTTP stream. WS warm is 18 ms faster at p50 (463 vs 481), within noise. WS cold is 780 ms slower; no cancel for barge-in | about 0 to 20 ms | Measured |
| TTS REST for uncached lines | stream already used | no change (REST would cost +740 ms at p50) | 0 | Measured |

Where the time goes for a short answer today (measured parts only): end of speech to final transcript about 735 ms,
of which about 657 ms is the server waiting for silence (300 ms setting plus roughly 350 ms of VAD/endpoint latency)
and about 75 ms is finalisation. TTS first audio for an uncached line adds about 480 ms. Cached lines add 0.
The big remaining lever is therefore the server-side end-of-speech detection (about 650 ms), not the endpoint choice.
Untested ideas (guesses): `endpointing=manual` with Friday's own VAD sending `speech_end` and `flush` (the docs describe a
flush event for manual mode) could remove most of those 657 ms, since Friday's segmenter already knows when the caller
stopped; and starting TTS for a likely reply while STT is finishing. Neither was run.

**Confirm on a real call.** Everything here is synthetic speech without noise, accents or phone codecs, from the
sandbox network. Real callers pause mid-sentence, so silence settings below 300 ms may cut sentences more often than the
1 to 2 in 10 seen here. Re-run both probes on the droplet and judge by the call log's `reply gap` before changing any default.
