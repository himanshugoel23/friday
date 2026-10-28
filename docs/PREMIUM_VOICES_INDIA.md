# Premium, very real Indian voices: Sarvam vs ElevenLabs vs others (research 2026-10-28)

Founder question (2026-10-28): is there a PREMIUM voice that sounds very real, with an Indian accent (ElevenLabs or Sarvam)?
Labels: **V** = read on the vendor's own page today; **C** = vendor/third-party claim; **U** = unverified.
**I cannot listen to audio.** Nothing below says how any voice sounds. "Sounds real" is decided only by the blind test in section 5.
Prices exclude GST. USD to INR at about 88 (my assumption). Page text was read through a fetch tool that summarises pages, so
re-check any price on the vendor page before you buy. Not a product decision: hear-before-change still applies (CLAUDE.md rule 3).

## 0. Short answer
- Yes, there are newer and more expressive options than today's Ritu (Bulbul v3): **Sarvam Bulbul v4 Flash** (Hinglish `enhi`
  personas, "customer" and "expressive" styles, INR 1/1,000 chars on the pricing page) and **ElevenLabs Eleven v4 / v4 Turbo**
  (launched Sep 2026, "most emotive", Hindi in the language list). Whether either beats Ritu on a phone line is **U** until we listen.
- Sarvam is Indian-hosted-looking and cheaper; ElevenLabs is about 3-7x the price and stores data in the US unless an enterprise
  India residency add-on is bought. Our own measurement already says Sarvam streams faster from the Bangalore server (docs/LATENCY.md).
- No vendor offers a single "premium Indian tier" badge. The closest are Sarvam `*_expressive` / `*_warm` personas and ElevenLabs v4.

## 1. Sarvam (today's vendor)
| Item | Finding | Label / source |
|---|---|---|
| Models | `bulbul:v4-flash` ("latest, recommended for new integrations"), `bulbul:v3` (stable API default), `bulbul:v2` (legacy; our code notes it returns HTTP 400). A non-Flash "Bulbul V4" (39 voices, emotion control, cloning from 30-60 s) is described by one third party; I found no API model id or price for it | V: https://docs.sarvam.ai/api-reference-docs/text-to-speech/convert ; C: https://alphasignal.ai/news/sarvam-ai-ships-bulbul-v4-to-bring-emotional-voice-to-11-indian-languages |
| v3 speakers | shubh (default), aditya, ritu, priya, neha, rahul, pooja, rohan, simran, kavya, amit, dev, ishita, shreya, ratan, varun, manan, sumit, roopa, kabir, aayan, ashutosh, advait, anand, tanya, tarun, sunny, mani, gokul, vijay, shruti, suhani, mohit, kavitha, rehan, soham, rupali (37). The API page gives NO gender; our code treats priya, ritu, neha, simran, kavya, ishita, shreya, roopa, pooja, tanya, shruti, suhani, kavitha, rupali as female (repo list, source unclear) | V (names) / U (gender) |
| v4-flash voices | 83 named personas, 224 speaker ids (one page says 222), ids look like `<name>_<lang>_<style>`. Hindi 116, English 62, Hindi-English mixed `enhi` 13 | V: https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/best-practice-guide-for-bulbul-v-4-flash and https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices |
| Hinglish personas (`enhi`) | ishita (companion, customer, customer expressive), sanchita (companion), shalini (companion, customer), shubh (companion, ads, banking), simran (companion, customer, banking expressive), sunny (customer). Sarvam says write English in Latin script and Hindi words in Devanagari | V (same voices page) |
| Hindi/English customer-care personas | Sarvam's own call-use table marks as female: aparna_hi_customer (customer care, appointments, sales), aarti_hi_customer, simran_en_sales, simran_hi_recovery, aparna_en_companion. Also on the voices page: ritu_hi_customer, ritu_hi_customer_warm, ritu_hi_customer_utility, ishita_en_customer, neha_en_customer, shalini_en_customer | V (best-practice guide, voices page). Gender of names not in that table is U |
| Premium / expressive tier | No separate premium tier found. "Expressive" appears only inside persona ids (e.g. `ratan_hi_customer_expressive`, `ishita_enhi_customer_expressive`). Sarvam markets v3 and v4 as emotionally nuanced | V (ids) / C (marketing: https://www.sarvam.ai/apis/text-to-speech.md) |
| Languages | 11 codes incl. en-IN, hi-IN; v4-flash has no Malayalam/Odia personas yet (use v3) | V |
| Streaming latency | Vendor: "sub-250 ms first byte" on WebSocket (C). Ours, measured with v3 from the Bangalore server: about 0.10 s first byte (docs/LATENCY.md, 2026-10). v4-flash not yet measured by us | C / V (ours, v3 only) |
| 8 kHz telephony | 8000 Hz listed; Sarvam says v4-flash output at 8 kHz is for "IVR and contact-centre legs"; streaming max 24 kHz. mulaw/alaw codecs listed | V |
| Controls | v3 and v4-flash: pace 0.5-2.0, temperature 0.01-1.0 (v3 docs); v4-flash guide also lists pitch -0.5..0.5 and loudness 0.1..2.5. No SSML | V (the v4 guide and convert page disagree on pitch/loudness for v4; U which is right) |
| Price (INR per 1,000 chars) | Pay-as-you-go: **v4 Flash 1.00, v3 3.00**, Instant Voice Cloning 2.00; Pro 0.925 / 2.85; Growth 0.85 / 2.70. WARNING: a third party says Flash list price is INR 2 per 1,000 with INR 1 a launch promo "through November 12", so budget at INR 2 until Sarvam confirms | V: https://docs.sarvam.ai/api/getting-started/pricing.md ; C: https://runtimewire.com/article/sarvam-bulbul-v4-flash-pricing-launch |
| Voice cloning | Yes, **Instant Voice Cloning, beta**: 10-15 s reference clip, cross-lingual, consent tick-box required, "only clone a voice you have the right to use"; commercial rules same as preset voices plus proof of rights. Sarvam's TTS page also says cloning is "with consent and safeguards for high-volume enterprise cases" | V: https://docs.sarvam.ai/api/api-guides-tutorials/voice-cloning/overview , https://docs.sarvam.ai/api/getting-started/commercial-licensing |
| Vendor benchmark | Sarvam says listeners preferred Bulbul v3 over ElevenLabs Flash v2.5 77.95%, over ElevenLabs v3 Alpha 43.64%, over Cartesia Sonic-3 40.08% (8 kHz). Own test, method unseen | C |
| Data location | Sarvam's TTS page does not state data hosting | U |

## 2. ElevenLabs
| Item | Finding | Label / source |
|---|---|---|
| Models | **Eleven v4** (launched about 2026-09-28; "fastest and most emotive"; 90+ languages incl. Hindi; 5,000 chars) and **v4 Turbo** (about 100 ms model inference, about 150 ms to first speech, "best for voice agents"). **Eleven v3** (70+ languages, 5,000 chars, labelled previous generation), **v3 Conversational** (about 280 ms), **Multilingual v2** (29 languages, 10,000 chars, more stable, slower), **Flash v2.5** (32 languages incl. Hindi, about 75 ms model time, 40,000 chars, for real-time agents), Turbo v2.5 (deprecated) | V: https://elevenlabs.io/docs/overview/models , https://elevenlabs.io/blog/create-realistic-transatlantic-accent-text-to-speech . Exact API ids for v4 (`eleven_v4`, `eleven_v4_turbo`) are C (third-party listing) |
| Best for phone | Flash v2.5 or v4 Turbo. Multilingual v2 and v3 are too slow for live turns (ours: multilingual_v2 about 1.4 s first audio). API offers mu-law/A-law 8 kHz | V (models page) ; ours: docs/LATENCY.md |
| Our measured latency | Flash v2.5 streaming 8 kHz: first audio 170 ms (US sandbox) to 270-500 ms from the Bangalore server; Sarvam about 100 ms from Bangalore. v4 not measured | V (ours, docs/LATENCY.md) |
| Indian voices | Voice Library has language and accent filters; third-party catalogues list Hindi/Indian-English and Hinglish voices (e.g. "Sia", "Priyanka"). Library quality varies, so only a listening test tells. Founder-chosen candidates in repo: Zara `OtEfb2LVzIE45wdYe54M`, Neha P `X1aCu8g69vgtNfFwu68G` | V (filters: https://elevenlabs.io/docs/product-guides/voices/voice-library) ; C (https://json2video.com/ai-voices/languages/hindi/india/?page=4) |
| Library-voice risks | Library voices need a paid plan for the API; the owner can withdraw a voice (immediately, or after a notice period of up to 2 years). Terms are in the Voice Library Addendum, which I did not read, so commercial voice-agent licence for a shared voice is **U** | V (same page) |
| Cloning and consent | Instant clone: 1-2 min audio, no verification step described in docs. Professional clone: Creator plan or higher, 30-180 min audio, mandatory voice verification, "you can only create a Professional Voice Clone of your own voice" (consent from someone else does not change this). Output is traceable to the account | V: https://elevenlabs.io/docs/product-guides/voices/voice-cloning |
| Price (USD per 1,000 chars, API) | Pricing page text: Flash/Turbo **0.04**, Multilingual v2 **0.08**, v3 **0.08** (about INR 3.5 / 7.0). Third parties quote 0.05 / 0.10, so the figure is unstable. No v4 price found. Plans: Starter 6, Creator 22, Pro 99, Scale 299, Business 990 USD per month. 1 minute is about 1,000 chars by their rule | V (read via fetch tool): https://elevenlabs.io/pricing/api ; C: https://developer.puter.com/tutorials/elevenlabs-api-pricing/ |
| Data residency | Default storage US. Storage regions EU, India, Singapore exist but are an **enterprise** feature; processing may still occur elsewhere unless Zero Retention Mode is on. India marketing page mentions "India Data Residency" for DPDP | V: https://elevenlabs.io/docs/overview/administration/data-residency ; https://start.elevenlabs.io/india/enterprise-v1 |
| Commercial licence | The pricing page I read only states commercial licensing for Music, nothing for TTS. Check the Terms of Service and plan before launch | U |

## 3. Other credible options (one honest line each)
- **Cartesia Sonic 3.6**: Hindi supported, including Latin-script Hindi; vendor says "fastest"; Vapi measured about 166 ms median for Sonic 3; about USD 50 per 1M chars derived (so about USD 0.05 per 1,000). 8 kHz output not confirmed. No adapter in our repo. C. https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
- **Smallest.ai Lightning v3.1 / v3.1 Pro**: Indic focus, Pro has English+Hindi code-switching, about 200 ms first byte, 8 kHz to 44 kHz and mu-law; no price found. No adapter. C. https://docs.smallest.ai/models/documentation/text-to-speech-lightning/overview
- **Google Chirp 3 HD**: Hindi (hi-IN) supported, USD 30 per 1M chars (about USD 0.03 per 1,000), 1M chars/month free; Hinglish handling and phone latency not checked; no adapter. V (price). https://cloud.google.com/text-to-speech/pricing
- **Azure Neural / HD voices**: Hindi voices exist; HD price was USD 30 per 1M chars at preview, current number not read; we have not checked Hinglish. U. https://azure.microsoft.com/en-in/pricing/details/speech
- **Deepgram Aura-2**: no Hindi TTS found (7 languages, Hindi only as speech-to-text). Drop. V. https://developers.deepgram.com/docs/tts-models-languages-overview
- **OpenAI gpt-4o-mini-tts**: steerable by instructions; reports of American-accented non-English speech; official price is per token (USD 0.60 per 1M text tokens in, 12 per 1M audio tokens out), roughly USD 0.015/min unofficially. Audio inference runs outside India. Cheap to try, probably not the winner. C/U.
- **Murf Falcon**: claims 130 ms first audio, 35 languages, USD 0.01/min, pitched at Indian voice agents; Hindi voice count not seen; vendor marketing only. C. https://murf.ai/api
- **Resemble Chatterbox (open, MIT)**: 23 languages incl. Hindi, self-hostable, cloning; Hindi quality U. We would run it ourselves. C. https://www.resemble.ai/products/text-to-speech
- **Gnani.ai**: claims MOS 4.3+ and "90% cannot tell from human" for Hindi (self-reported, no method). C. https://www.gnani.ai/resources/blogs/best-text-to-speech-hindi-tools-in-2026-gnani-ai-google-translate-alternatives
- **AI4Bharat Indic Parler-TTS (open)**: 21 Indic languages, voices steered by text description (no fixed phone-agent voices); licence shown as MIT on one page and Apache 2.0 on another; needs a GPU and latency work. C/U. https://huggingface.co/ai4bharat/indic-parler-tts
- **Pi, Rabbit, Alexa/Google Assistant voices**: not buyable as TTS for our calls; not researched here.

## 4. What I could not verify
- How any voice sounds (I cannot listen), including whether v4-flash or Eleven v4 is more "real" than Ritu v3.
- Gender of v3 speakers from an official page, and the full gendered v4-flash list (docs give names and styles, not gender).
- Whether Sarvam v4-flash is INR 1 or INR 2 per 1,000 after 2026-11-12; v4-flash first-audio from our server; whether the v4 pronunciation dictionary works (guide says yes; our adapter sends `dict_id` only for v3, so names on v4 are not yet protected).
- ElevenLabs: exact v4 API ids and price, the Voice Library Addendum, TTS commercial terms, current price (two figures seen), India residency price.
- Cartesia/Smallest/Murf/Gnani prices, 8 kHz phone quality and Hinglish behaviour.
- Voice ids quoted by third-party catalogues (e.g. "Sia") are unchecked and may not be free to use commercially.

## 5. Shortlist to audition (6 + 1) and the blind test
| Code | Voice | Why | Can Friday tooling render it? |
|---|---|---|---|
| A (control) | Sarvam v3 `ritu`, pace 0.9, temperature 0.9 | today's founder pick | yes |
| B | Sarvam v4-flash `simran_enhi_customer` | Hinglish customer persona; already our v4 default | yes |
| C | Sarvam v4-flash `ishita_enhi_customer` | second Hinglish customer voice | yes |
| D | Sarvam v4-flash `ritu_hi_customer_warm` | same speaker as today, warm customer style | yes |
| E | ElevenLabs Flash v2.5 with Zara or Neha P (library) | real-time model, measured by us | yes (`--provider elevenlabs`) |
| F | ElevenLabs v4 Turbo (or v4) with the best Indian voice found by filtering Voice Library: language Hindi, accent Indian | "most emotive" claim | maybe: our adapter was built for Flash; v3/v4 may reject some `voice_settings` (U) |
| G (optional) | Cartesia Sonic 3.6 or Smallest Lightning v3.1 Hindi voice | fastest-claim challengers | no: use the vendor playground, then convert to 8 kHz; mark clearly |

**Test set**: 20 Hinglish call lines, written once and frozen before listening: 4 openings/introductions with a business name,
4 price or time readbacks ("chaar sau pachaas rupaye", "sawa paanch baje"), 3 phone-number readbacks, 3 questions, 2 apologies or
bad news, 2 thanks/closings, 2 "are you an AI?" answers. Use Devanagari names and spoken-form numbers exactly as the live call
would send them (`friday/voice/names.py`, `friday/human/numbers.py`). Render everything at 8 kHz phone quality.
**Raters**: founder plus at least 4 others (include 2 who often take business calls). Files renamed to random codes; key kept by one
person; each rater sees the voices in shuffled order, never the name. Score 1-5: naturalness, phone clarity, pronunciation of
names and numbers, warmth, and "is it an AI?" (1 = surely a human, 5 = surely a machine). Raters also tick any line that has a
wrong word, number or name. Friday still keeps its AI-on-request line (docs/VOICE_NEXT_STEPS.md item 3); realism does not replace it.

**Decision rule** (all must hold):
1. Gate: zero wrong numbers/prices/times and at most 2 of 20 lines with a mispronounced name; otherwise out.
2. Gate: first audio on a real call path from the Bangalore server at most 400 ms median (measure; vendor numbers do not count).
3. Gate: cost at most INR 4 per 1,000 chars (about INR 3-4 per spoken minute, assumption of 800-1,000 chars per minute) and a working
   fallback to Sarvam v3 Ritu; data stays in India or the founder accepts abroad processing in writing (legal read pending).
4. Winner = highest mean of (naturalness 30%, pronunciation 25%, phone clarity 20%, warmth 15%, AI-score inverted 10%), and it
   must beat control A by at least 0.3 points and in at least 60% of paired lines. Otherwise keep Ritu.
5. Tie within 0.2: pick the cheaper, then the Indian-hosted one. Founder has final say after hearing the top two live on a test
   call to his own allow-listed number (rule 5 of CLAUDE.md).

## 6. Founder copy-paste: make the samples on the server
Tooling found in the repo (no invented commands): `friday say` (one line to a wav; flags `--provider sarvam|elevenlabs`, `--pace`,
`--out`, `--phone`), `friday tts-check` (Sarvam only, checks name pronunciation by listening back, does not judge naturalness),
`friday playbook preview` (the full real script as one wav). There is NO `--speaker` or `--model` flag, so pass them as
environment settings in front of the command (`FRIDAY_SARVAM_TTS_SPEAKER`, `FRIDAY_SARVAM_TTS_MODEL`, `FRIDAY_ELEVENLABS_MODEL`,
`ELEVENLABS_VOICE_ID`, from `friday/core/config.py` and `friday/voice/tts/sarvam.py`). Keys are read from the server's `.env`; do
not print it. Run as the DigitalOcean console user (same pattern as the doctor command in docs/HANDOFF.md section 0). These commands
are drawn from the code, I could not run them here; if one fails, send the error text, not keys.

```
cd /opt/friday
mkdir -p var/preview/voicetest
# one test line first (A = control, today's voice)
sudo -u friday env FRIDAY_SARVAM_TTS_MODEL=bulbul:v3 FRIDAY_SARVAM_TTS_SPEAKER=ritu \
  /home/friday/.local/bin/uv run friday say --phone --pace 0.9 --out var/preview/voicetest/A_test.wav \
  "Namaste, main Rahul ji ki taraf se bol rahi hoon. Haircut ka rate kya hai?"
# B = Sarvam v4-flash Hinglish persona (pace 1.0 is Sarvam's advice for agents)
sudo -u friday env FRIDAY_SARVAM_TTS_MODEL=bulbul:v4-flash FRIDAY_SARVAM_TTS_SPEAKER=simran_enhi_customer \
  /home/friday/.local/bin/uv run friday say --phone --pace 1.0 --out var/preview/voicetest/B_test.wav \
  "Namaste, main Rahul ji ki taraf se bol rahi hoon. Haircut ka rate kya hai?"
# E = ElevenLabs Flash v2.5; fallback off so a failure is not silently spoken by Sarvam
sudo -u friday env FRIDAY_TTS_FALLBACK=none FRIDAY_ELEVENLABS_MODEL=eleven_flash_v2_5 ELEVENLABS_VOICE_ID=OtEfb2LVzIE45wdYe54M \
  /home/friday/.local/bin/uv run friday say --provider elevenlabs --phone --out var/preview/voicetest/E_test.wav \
  "Namaste, main Rahul ji ki taraf se bol rahi hoon. Haircut ka rate kya hai?"
```
For all 20 lines: put them one per line in `/opt/friday/var/preview/voicetest/lines.txt` (frozen test set, section 5), then repeat
this loop once per voice, changing only the `env` part and the letter (A to F):
```
cd /opt/friday; n=0
while IFS= read -r line; do n=$((n+1)); f=$(printf '%02d' $n)
  sudo -u friday env FRIDAY_SARVAM_TTS_MODEL=bulbul:v4-flash FRIDAY_SARVAM_TTS_SPEAKER=ishita_enhi_customer \
    /home/friday/.local/bin/uv run friday say --phone --pace 1.0 --out var/preview/voicetest/C_$f.wav "$line"
done < var/preview/voicetest/lines.txt
```
Notes: `--phone` gives the 8 kHz mu-law round trip the business hears. Sarvam temperature stays 0.9 from settings for all Sarvam voices
(change it only as a separate test). v3 speakers use the pronunciation dictionary, v4 does not (see section 4). For F set
`FRIDAY_ELEVENLABS_MODEL` to the v4 Turbo id once you confirm it in the ElevenLabs dashboard (U); if the call errors, the adapter's
`voice_settings` may be the cause. Voice ids and model names change: confirm in the vendor dashboard. To blind the files, copy
them to new random names and keep the key off the server. These samples are for listening only: no config or code change until
the founder approves, and no real vendor calls.
