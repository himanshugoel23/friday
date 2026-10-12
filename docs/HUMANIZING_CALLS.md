# Humanizing vendor calls (ideas to explore, 2026-10-12)

Goal: businesses stay on the line and answer. **Humanize = sound natural, be brief, be useful, be trustworthy. It does NOT mean pretending to
be a person.** Friday never denies being an AI (founder rule 2026-10-10; also the safe line legally and for brand trust). Every change to what
she says or how she sounds gets audio to the founder first (hear-before-change).

## Why a business hangs up (hypotheses to test)
1. Unknown number / looks like a sales or spam call. 2. A long first sentence before they know why you called. 3. Delay after they speak
(robot feel). 4. Talking over them, or not stopping when interrupted. 5. Same stiff phrasing every time. 6. Bad moment (lunch rush, busy hours).
7. Learning it is an AI and having no reason to continue. 8. Audio artefacts (dead-silent gaps, clipped words, wrong number reading).

## Ideas, grouped
**A. Trust before the call**
- Caller ID: one steady number; apply for Truecaller "verified business" profile ("Friday, assistant for <user>") so it shows a name, not "spam".
- Optional WhatsApp/SMS to the business right before: "Himanshu sir ke liye rate poochna hai, abhi call karungi" (reduces surprise).
- After the call: an SMS/WhatsApp with who called, for whom, a call-back number, and a one-word opt-out (also required by DLT/DPDP spirit).
- A small vendor page ("Friday kaun hai?") linked in the SMS: builds the "real service" feeling.

**B. The first 5 seconds**
- One breath: who + for whom + why ("Himanshu sir ki taraf se, haircut ke rate poochne the"), then the question. No pleasantries.
- Ask permission when it is plausible they are busy: "Do minute hain?" and honour a no ("Kab call karun?").
- Mirror their register (formal/casual), use their language (Hindi / Hinglish / English; regional later).

**C. Turn-taking that feels human** (biggest naturalness gain after latency)
- Backchannels while they speak or just after: "ji", "achha", "hmm", "theek hai" (pre-rendered, instant). Needs audio approval.
- Never talk over them; stop within 300 ms if they cut in (barge-in already does).
- Reply within ~1 s every time (done most turns); a short acknowledgement ("ji, ek second") if the model needs longer.
- Short sentences, one question per turn, repeat a number back the Indian way ("paanch sau, theek hai").
- Varied wording: 3-4 approved variants per line, picked at random, so repeat vendors do not hear the identical script.

**D. Voice and audio**
- Phone-tuned audio (8 kHz EQ), light room/line comfort noise instead of perfect digital silence, no clipped starts.
- Numbers, prices, times read naturally ("dedh sau", "sawa paanch baje"), names transliterated (done), no English words with odd accents.
- Ritu stays (decided). Explore small pace variation per sentence; temperature 0.9 already adds variety.

**E. The "are you an AI?" moment (the real decision)**
Today: she answers truthfully when asked (`ai_disclosure: on_request`). Make that moment work for us, not against us:
"Haan ji, main Himanshu sir ki AI assistant hoon. Unhone sirf rate poochne ko kaha hai, ek minute lagega. Theek hai?" then give them an
easy way out and a benefit: "Aap chahein toh WhatsApp pe bhej dijiye" / "sir se baat karwa dun?". Test whether warm + short + a choice keeps more
people than a flat statement. Never deny, never argue.

**F. Give them a way to say yes in THEIR way**
- Offer WhatsApp for the answer when they are busy; allow call-back at a time they name; accept "mere number pe message kar do".
- Skip the call and use WhatsApp Business/Google booking links where a vendor has them.

**G. Pick better moments and targets**
- Call in the vendor's quiet hours (Google "popular times", category rules: salon mid-afternoon, restaurants before lunch/dinner rush).
- Never call twice in a day; do not redial a "no"; skip numbers that look like IVR/helplines/toll-free (done for toll-free).
- Prefer vendors with high recent pickup (learned from our own logs).

**H. Measure it (nothing improves without this)**
- Log per call: picked up, first reply within X s, minutes in, hung up where (which step), why (heard "AI"? rude? busy?), outcome.
- Weekly review of 20 transcripts + audio by the founder; tag hang-up reasons; change ONE thing at a time; A/B approved variants.
- Metrics: pickup rate, completion rate, hang-up-after-AI-question rate, median talk time, quotes collected per 10 calls.
- Build into the quality loop (friday/quality/) as a dashboard in `friday review`.

## My suggested first five to explore (cheapest, biggest effect)
1. Tighten the first 5 seconds (B) and add the permission question where relevant.
2. Backchannels + short "ek second" holds (C): needs audio samples for approval.
3. Truecaller verified business + after-call SMS with callback number and opt-out (A): paperwork, start now.
4. Instrument hang-up reasons (H): needed to know what actually works.
5. Rework the AI-question answer (E) and A/B test it on 20 calls.

## Open founder questions
- Disclosure timing: keep "virtual assistant" in the opening and "AI assistant" on request, or test saying "AI assistant" up front? (Measure hang-up rates; do not hide it.)
- OK to message the business on WhatsApp before the call?
- Which vendor categories are most important to tune first (salon, clinic, AC repair)?
