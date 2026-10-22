# Receptionist: Friday answers the calls you did not pick up

Status (2026-10-22): built and simulated offline. **No real call, no audio, no real WhatsApp message was
produced.** Every line below is `PENDING_FOUNDER_APPROVAL` (hear-before-change): nothing may go live until the
founder has heard the audio. The switch `FRIDAY_RECEPTIONIST_ENABLED` is **off by default**. Package
`friday/receptionist/`, tests `tests/receptionist/`, simulator `uv run friday receptionist-sim`.

This is the "after-hours receptionist plus what-did-I-miss" idea from the ElevenLabs ad (docs/COMPETITORS.md update
(i)), built the way the founder decided on 2026-10-22: Friday does **not** take all calls. She answers only when the
user did not pick up after N rings, or cut / declined the call, or the phone is off. The user's phone still rings
first, exactly as today.

## 1. How it works

```
caller rings the user's phone
   user answers                     -> nothing happens, Friday never sees the call
   user does not answer in N rings  -> the CARRIER forwards the call (conditional forwarding)
   user declines / is busy / phone off / no network (same carrier feature)
                                         |
                                         v
        Friday's shared inbound number (Vobiz) -- carries the REDIRECTING number (unverified, see 4)
                                         |
        InboundCallReceived(redirecting=...) -> CallbackService -> Receptionist.claims()
             forwarded + known user  -> receptionist call (user lane)
             forwarded + unknown redirecting number -> generic polite message-taker (nobody is notified)
             not forwarded (someone rings Friday directly) -> the normal front door, unchanged
                                         |
        receptionist call (max 90 s): greet -> who / what for -> read back -> close
                                         |
        classify (code rules) -> store (encrypted) -> WhatsApp summary + buttons
             URGENT  -> sent at once (even in quiet hours): [Call back] [Ignore] [Block]
             NORMAL / SPAM -> kept for the morning digest (sent once quiet hours end)
        "what did I miss?" -> text on WhatsApp, short spoken version when the user calls Friday
```

## 2. Setup (per user)

Config (`ReceptionistConfig`, stored encrypted, table `receptionist_configs`):

| Field | Meaning | Default |
|---|---|---|
| `rings` | rings before the carrier forwards (3 to 6) | 5 |
| `forward_no_answer` / `forward_busy` / `forward_unreachable` | which carrier conditions send the call to Friday | all on |
| `quiet_hours` | local hours in which a NORMAL message is never pushed (urgent still is) | 22:00 to 08:00 |
| `urgent_keywords` | extra words that make a call urgent | none |
| `urgent_contacts` | numbers whose calls are always urgent (even a silent hang-up) | none |
| `known_contacts` | number to name, never treated as spam | none |
| `user_name`, `language` | how callers hear the user's name (never a pronoun), call language | none, hinglish |
| `private_facts` | words that must never be spoken (city, address ...) | none |

### Carrier codes (GENERAL KNOWLEDGE, NOT VERIFIED ON ANY REAL SIM)

Standard GSM supplementary-service codes (3GPP TS 22.030). `<n>` is Friday's inbound number as `+91XXXXXXXXXX`
(fallback: the 10-digit form, `friday receptionist codes --national`), `<s>` is the no-reply timer in seconds.

| What | Activate | Cancel | Check status |
|---|---|---|---|
| Forward when **not answered** | `**61*<n>**<s>#` | `##61#` | `*#61#` |
| Forward when **busy** (a declined call usually counts as busy) | `**67*<n>#` | `##67#` | `*#67#` |
| Forward when **unreachable** (phone off / no network) | `**62*<n>#` | `##62#` | `*#62#` |
| Cancel ALL forwarding | | `##002#` | |

`<s>` = 5 seconds per ring, rounded to a multiple of 5, never above the carrier's allowed maximum (30 s is the GSM maximum):

| Rings chosen | `<s>` |
|---|---|
| 3 | 15 s |
| 4 | 20 s |
| 5 | 25 s |
| 6 | 30 s |

Per carrier (all rows are unverified):

| Carrier | Codes used | Notes | Status |
|---|---|---|---|
| Jio | `**61*<n>**<s>#`, `**67*<n>#`, `**62*<n>#` | Jio is 4G/5G (VoLTE) only. The standard codes are believed to work; if the dialler rejects them, use the phone's own Call Forwarding setting (Android: Phone app > Settings > Calling accounts > Call forwarding). Jio may use a fixed no-reply timer. | not verified |
| Airtel | `**61*<n>**<s>#`, `**67*<n>#`, `**62*<n>#` | Standard codes believed to work. Airtel offers its own voicemail on some plans: switch it off or it may answer before Friday. | not verified |
| Vi (Vodafone Idea) | `**61*<n>**<s>#`, `**67*<n>#`, `**62*<n>#` | Standard codes believed to work. Vi may have a voicemail service active by default: switch it off or it may answer before Friday. | not verified |
| BSNL | `**61*<n>**<s>#`, `**67*<n>#`, `**62*<n>#` | Standard codes believed to work, but some BSNL plans may need forwarding enabled by customer care first. | not verified |

`friday receptionist codes --carrier jio --number +91XXXXXXXXXX --rings 5` prints the codes, the tap-to-dial links
(`tel:` with `#` encoded as `%23`) and the setup text below for any carrier.

### The setup message (Hinglish and English; PENDING approval)

Generated by `friday/receptionist/setup.py`; it contains the user's exact codes, how to check, how to turn off, the
charges warning and, most important, the **carrier voicemail warning**: the carrier's own voicemail may answer before
Friday (it usually sits on one of the three conditions). If it does, the user must switch the carrier voicemail OFF
(carrier app or customer care) and dial the codes again. The page ends with a "Test it" button (section 3).

Example for Jio, 5 rings (invented number):

```
**61*+918000000099**25#   **67*+918000000099#   **62*+918000000099#
status: *#61# *#67# *#62#     turn off: ##002#
```

## 3. The forwarding PROBE (what the founder must do)

We do not know which webhook field Vobiz uses for the number the call was forwarded from, or whether it sends one at
all. The probe finds out, on your own phone, without any user:

1. On the server set FRIDAY_RECEPTIONIST_PROBE=true (the switch FRIDAY_RECEPTIONIST_ENABLED can stay false) and restart `friday listen`.
2. On YOUR phone (the founder's) set ONLY forwarding when unanswered to Friday's inbound number: the no-answer code from `friday receptionist codes --carrier <yours> --number <Friday number>`.
3. From a SECOND phone, call your own number and do not answer (let it ring until it forwards), then repeat once with the second phone calling and you pressing Decline.
4. Run `friday receptionist probe --show`. It prints, masked, every webhook key that arrived and any key whose value looks like your number.
5. If a key is listed as a candidate, put its name first in FRIDAY_RECEPTIONIST_REDIRECT_FIELDS; if none, nothing carries it and the fallback (ask the caller whom they wanted) is needed. Send the output to the team; it contains no full numbers.
6. Cancel with ##002#, check with *#61#, and repeat for each carrier you have a SIM for (Jio, Airtel, Vi, BSNL).

Details: with `FRIDAY_RECEPTIONIST_PROBE=true` every inbound webhook is recorded to `var/receptionist/probe.jsonl`
with the **key names** and, for values that look like phone numbers, a **masked** form. A key whose value is a third
number (neither the caller nor Friday's number) is printed as a CANDIDATE redirecting-number key. Nothing else from
the webhook is written. `friday receptionist probe --demo` shows the output format on an invented example;
`friday receptionist probe` prints the steps; `friday receptionist probe --show` prints what was recorded.

The test-call helper (`TestCallHelper`, the "Test it" button) rings the user's own phone from Friday; if the user does
not answer, the call forwards back and the probe sees it. It is **not wired to a dialer**: it refuses non-allow-listed
numbers and the kill switch, and with no dialer it only tells you to call yourself from a second phone. A real test
call needs the founder's approval first (CLAUDE.md rule 5).

What to send back to the team after the probe: the output of `friday receptionist probe --show` for each carrier SIM
and each of the two cases (not answered, declined). It contains no full numbers.

## 4. Which user was the call for?

Founder decision (2026-10-19/22): ONE shared inbound number, the user is identified by the redirecting (diverting)
number. `friday/receptionist/identify.py` is an **adapter**: it reads the keys listed in
`FRIDAY_RECEPTIONIST_REDIRECT_FIELDS` (default guesses: `ForwardedFrom, Forwarded-From, DivertedFrom, Diversion,
DiversionNumber, RedirectingNumber, RedirectingParty, OriginalCalledNumber, OriginalTo, History-Info, HistoryInfo,
X-Forwarded-For-Number, SIP-Diversion`) and parses a plain number, `tel:`, a `sip:` URI, or SIP `Diversion` /
`History-Info` header text (with several numbers, History-Info lists the original first and Diversion lists it last).
**TODO(vobiz-probe): pin the real key and format here once the probe shows them.** The Vobiz adapter
(`voice/telephony/sarvam.py`) only calls `observe_inbound(params)`, which is inert until the receptionist or the probe
is configured, and puts the raw value on `InboundCallReceived.redirecting`.

| Redirecting number | What happens |
|---|---|
| none (a direct call to Friday), or Friday's own number, or the caller's own number | not forwarded: the normal front door |
| a Friday user with the receptionist on | the receptionist, that user's lane |
| a Friday user with the receptionist off | one short polite line (`rcp.blocked.end`), nothing stored, nothing sent |
| a number that is not a Friday user | **generic message-taker**: does not name anyone, is honest that the message may not reach anybody (`rcp.unrouted.close`), is stored with no user for 7 days for ops, **never** attributed to a guessed user, nobody notified |

If the probe shows the field does not exist, the fallbacks from docs/JARVIS_FEEL.md 8b apply (ask the caller whom they
wanted on a small pool, or a paid dedicated number); nothing else in this package changes.

## 5. The call (moves, rules, limits)

A small state machine in `flow.py`, built on the live engine's pieces (the `TelephonyPort`, `HeardUtterance`, the
callee understanding for silence / "are you AI" / secrets / wrong number, and its idea of fixed approved lines) but its
own flow, because the live engine is written for calls Friday makes. All Friday sentences are fixed lines from
`lines.py` (the only dynamic parts are the caller's own name and the first 12 words of their own reason, sanitised).

Moves: greet (+ role disclosure) -> ask name / reason -> **read back briefly** -> close. Side moves: truthful AI answer,
"who is this", deflect a question about the user, deflect "put me through", refuse a promise, refuse an OTP/PIN. Stops:
abuse, wrong number, silence (one "hello?" then a polite end), "do not note this down", hang-up, 90 seconds.

Hard rules (code, not prompt; the simulator checks each one on every caller):

* Greets as the user's assistant ("... {user} ki virtual assistant ... {user} abhi call nahi utha paye. Main aapka
  message note kar leti hoon"): the same AI-disclosure rule as the live engine (founder 10 Oct: do not volunteer "AI",
  but answer truthfully the moment anyone asks, in any form, and never deny it). The line also tells the caller that the
  message is being noted.
* **Never promises or commits anything for the user** (no "he will call you back", no times, no "yes"): she only says she
  will pass the message on. A caller asking for a promise gets `rcp.promise.refuse`.
* **Never reveals anything about the user**: location, number, schedule, whether they are home. A question about the user
  gets `rcp.deflect.user_info`; a caller who asks three times is politely closed. `private_facts` are also kept out of
  the read-back.
* Asks for a call-back number **never**; a number the caller volunteers is noted (`rcp.callback.noted`).
* No digits, OTP, PIN or card detail is ever spoken or stored; a request for one gets `rcp.secret.refuse`.
* Stops at once on hang-up (`CallDropped`), no line is spoken after it.
* At most **90 s**: wrap-up starts at 60 s (one utterance is at most 20 s, then the closing line); the service also
  ends the call. At most 12 caller turns.
* Language follows the caller (STT language tag), default is the user's setting.

### Data and consent rules (DPDP read still needed, see open questions)

* The greeting tells the caller that the message is noted. **No audio is recorded.** What is stored: caller number
  (encrypted), name and reason in the caller's words (encrypted, secrets redacted), urgency + the reasons it was
  flagged, and a **transcript snippet** (the caller's own words, at most 240 characters, encrypted, deleted after
  `FRIDAY_RECEPTIONIST_SNIPPET_DAYS`, default 30).
* If the caller says "do not note anything / mat likho / don't record", Friday stops collecting, stores **no reason and
  no snippet** (only that someone called), and tells the user "they asked me not to note anything".
* A caller who hangs up is still reported ("X called at 3:12 and left no message").
* Everything is keyed by `user_id` and erased by "delete everything" (`DataPurger`).

## 6. Classification (`classify.py`)

Code rules first; a model only behind the `UrgencyModel` interface (there is a `FakeUrgencyModel`; **no real model is
wired**). Order:

1. an urgent contact -> URGENT (even a silent hang-up);
2. strong urgent words (accident, hospital, emergency, ambulance, police, ICU, tabiyat, bimar, Hindi-script equivalents,
   plus the user's own keywords) -> URGENT, even from an unknown number: **when unsure, flag it**;
3. a known contact: any urgent word -> URGENT, otherwise NORMAL and **never spam**;
4. spam patterns from an unknown caller (loan, KYC, lottery, insurance, offers, trading ...; a telemarketer number
   prefix 140/160; an OTP request with bank/card wording) -> SPAM;
5. weak urgent words (urgent, jaldi, turant ...) from an unknown, non-spam caller -> URGENT; a spam pitch that says
   "urgent" stays SPAM;
6. otherwise NORMAL, and only then the optional model is asked. It may raise a call to URGENT; it may lower to SPAM only
   for an unknown caller; it can never lower an urgent call; invalid output is ignored; it never sees the number or any
   private fact.

Word lists are English, Hinglish and Hindi script, written by us and tested on invented callers only.

## 7. After the call

* Stored in `receptionist_messages` (migration `0011_receptionist`, tables `receptionist_configs`,
  `receptionist_messages`, `receptionist_blocks`). Personal text is encrypted with the field cipher; numbers are looked
  up by blind index. `DataPurger.purge_user` deletes all three tables for the user.
* WhatsApp summary (`service.py`, texts in `copy.py`): who (name and number, or the contact name), when, what about, their
  own words, any number they gave, and why it was flagged. Buttons (ids `rcp:<message id>:<callback|ignore|block>`,
  routed by `InboundPipeline`): **Call back** (replies with the number to tap), **Ignore**, **Block** (adds the number
  to the user's Friday block list and explains how to block on the phone itself, which Friday cannot do).
* URGENT is sent immediately, even at 2 am. NORMAL and SPAM wait for the **morning digest**: `ReceptionistService.tick`
  (run every 5 minutes by the `Runtime`) sends one WhatsApp message per user once their quiet hours are over and marks
  the messages notified. Spam is a count with the caller names. Merging the digest into the generic morning briefing text
  is not done (the briefing provider has a single slot); `digest_text` is ready for it.
* **Block list / do-not-answer**: a blocked number gets one fixed polite line (`rcp.blocked.end`) and the call ends; a
  content-free row is kept so caps still count. Per user; the outbound global do-not-call registry is a different thing.
* **Caps** (before any conversation): `FRIDAY_RECEPTIONIST_PER_USER_PER_DAY` (40) forwarded calls per user per day and
  `FRIDAY_RECEPTIONIST_PER_CALLER_PER_HOUR` (3) per caller number; over a cap the caller hears `rcp.cap.end`.
* **Kill switch**: `friday pause` / `FRIDAY_PAUSED` makes every forwarded call end with `rcp.blocked.end`; nothing is stored
  or sent while paused. The test-call helper also refuses.
* **"What did I miss?"** (WhatsApp text, also "kya miss hua", "kisne call kiya" ...): counts by urgency, then each
  non-spam item newest-urgent-first, then today's calendar events if the life-state store has any (a failing calendar
  never blocks the answer). The **short spoken version** (`missed_spoken`, for the user calling Friday) gives the counts,
  reads at most two urgent items by name and reason, and says the full list is on WhatsApp. It is **not yet wired into
  the front door's voice conversation** (the front door is not touched by this package); the function and lines exist.

## 8. Switches and wiring

| Env name | Meaning | Default |
|---|---|---|
| `FRIDAY_RECEPTIONIST_ENABLED` | the receptionist (claims forwarded calls, buttons, "what did I miss?", digest loop) | **false** |
| `FRIDAY_RECEPTIONIST_INBOUND_NUMBER` | the shared number users forward to (else the first of `FRIDAY_NUMBERS`) | unset |
| `FRIDAY_RECEPTIONIST_REDIRECT_FIELDS` | webhook keys that may carry the redirecting number (CSV) | guesses, see 4 |
| `FRIDAY_RECEPTIONIST_PROBE` | record masked webhook keys to `var/receptionist/probe.jsonl` | false |
| `FRIDAY_RECEPTIONIST_MAX_CALL_S` | call length cap | 90 |
| `FRIDAY_RECEPTIONIST_PER_USER_PER_DAY` / `_PER_CALLER_PER_HOUR` | caps | 40 / 3 |
| `FRIDAY_RECEPTIONIST_SNIPPET_DAYS` | how long a transcript snippet is kept | 30 |

Changes outside the package (all inert while the switch is off): `core/config.py` (settings), `core/events.py`
(`InboundCallReceived.redirecting`), `voice/telephony/sarvam.py` (`_observe_redirect`, passes the raw value on),
`core/container.py` (`receptionist` component), `api/callbacks.py` (claim a forwarded call before the front door),
`api/inbound.py` (buttons and "what did I miss?"), `api/runtime.py` (build early, digest loop), `db/tables.py` and
`db/repositories/purge.py` (tables and erasure), `db/migrations/versions/0011_receptionist.py`, `cli.py`.

## 9. Commands

```
uv run friday receptionist-sim [--show <caller id>] [--morning]    # 47 scripted callers, offline
uv run friday receptionist codes --carrier jio --number +91XXXXXXXXXX --rings 5
uv run friday receptionist lines                                    # every spoken line and WhatsApp text
uv run friday receptionist probe [--show] [--demo]
uv run pytest tests/receptionist -q
```

## 10. The simulator

`friday/receptionist/sim.py`: 47 scripted callers (Hinglish, Hindi script, English): sales and loan spam, insurance,
KYC scam that says "urgent", lottery, a 140-series number, a bank OTP scam, mummy (urgent contact), a brother, a school
call about a sick child, an accident, ambulance, a doctor's clinic (normal and serious), a courier (also asking for an
OTP), a plumber who gives his number, a landlord, a recruiter, a society secretary, wrong number, abusive, silence,
hang-ups, "are you a robot?", "where is she?", "put me through", "will she call me back?", "do not note anything", an
STT language mismatch, a very long monologue, plus the routing cases (blocked number, unknown redirecting number, hourly
cap, kill switch, receptionist off). Time is virtual. Every run is checked for: truthful AI answer, no promise, no
private fact or user number spoken, no digit the caller did not say, no repeated line, nothing after hang-up, at most
90 s, no secret stored, urgent -> exactly one immediate push with three buttons, others -> no push before the digest.

## 11. UNVERIFIED (everything that matters)

1. Each code works on each carrier (Jio, Airtel, Vi, BSNL) and on prepaid AND postpaid plans.
2. The **seconds** value is honoured; some carriers ignore it and use their own timer (often 20-30 s) or cap it below 30.
3. A declined call (iPhone Decline, Android reject) is treated as BUSY and therefore forwarded.
4. Whether silenced unknown callers (iPhone Silence Unknown Callers, Android spam filters) take the forwarding path.
5. That the carrier's own voicemail does not win (it may sit on one of the three conditions).
6. That the number is accepted with +91 (otherwise try the 10-digit form).
7. Whether the network passes the redirecting number to Vobiz, and in which webhook field.
8. Forwarded-call charges to the user (differs by plan) and dual-SIM / eSIM behaviour.
9. That the phone's own dialler accepts these codes (iPhone may refuse some tel: links).
10. **Everything spoken**: no line was heard; pronunciation, pace and tone of every `rcp.*` line, the Devanagari variants,
    and the read-back of a caller's raw words (it may sound odd when the caller's words contain "aapka ...").
11. Real Hinglish / Hindi STT on a forwarded 8 kHz call, names (Indian names are not transliterated for the caller's name
    in the read-back), barge-in and the end-of-speech delay.
12. The Vobiz behaviour for a forwarded call itself: that the call is delivered to the inbound application at all, the ring
    time seen by the caller, caller-ID presentation, and the SIP/webhook field with the redirecting number.
13. WhatsApp: the urgent summary is a free-form message; **outside the 24-hour window it needs an approved template**
    (none is registered yet: `docs/WHATSAPP_TEMPLATES.md`), and button titles/payload limits on a real device.
14. The word lists and the telemarketer prefix rule (140/160) on real calls; false "spam" on a genuine unknown caller
    (a job offer) is possible and is why spam is still listed in the morning digest.
15. DPDP/TRAI: noting a third party's message, storing their number, the greeting wording as notice, retention periods;
    the legal read in docs/LEGAL_MAP.md has not been done for this feature.
16. Postgres: migration `0011` ran on SQLite only. Multi-replica: the per-process pieces are the digest loop (idempotent
    through message status) and nothing else keeps state in memory.

## 12. Open questions for the founder

1. **Probe first.** Run section 3 on your own SIM (and a friend's on another carrier). Until the redirecting number is
   confirmed, every forwarded call takes the generic message-taker path.
2. Unknown redirecting number: today the generic taker is honest that the message may not reach anyone and stores it
   without a user for 7 days. Is that acceptable, or should it only say "please call again" and store nothing?
3. The read-back repeats the caller's own words (first 12 words). Keep it, or only say "I am noting your message"?
4. Should the greeting say "AI" up front for this feature? (Today: the same rule as the live engine: asked -> truthful.)
5. Urgent push at night: always (today), or only for urgent contacts / strong words?
6. "Call back" replies with the number to tap. Should it instead make Friday ring the user and the caller (a bridged call)?
   That needs a live-call approval design.
7. Spam: the call is ended politely like any other, and the user is offered Block. Should Friday end a clear sales pitch
   faster, with its own line, once the Hinglish audio of the base lines is approved?
8. WhatsApp template wording for urgent alerts outside the 24-hour window.
9. Calendar-aware urgency ("in an interview now" vs "free") and a protected-event all-calls mode are not built.

## 13. Every new line (for audio approval)

Nothing below has audio. `{user}` is the user's name (never a pronoun), `{name}` and `{reason}` are the caller's own words.
Approve by listening to the audio the team generates after you pick the lines you want changed. The ids are stable.

### 13a. Spoken to the caller (`rcp.<key>.<language>`; languages: hinglish, hi = Devanagari, en)

| id | text |
|---|---|
| `rcp.greet.intro.hinglish` | Hello, main Friday bol rahi hoon, {user} ki virtual assistant. {user} abhi call nahi utha paye. Main aapka message note kar leti hoon. Aap kaun bol rahe hain, aur kis kaam se call kiya tha? |
| `rcp.greet.intro.hi` | हैलो, मैं फ्राइडे बोल रही हूँ, {user} की वर्चुअल असिस्टेंट। {user} अभी कॉल नहीं उठा पाए। मैं आपका मैसेज नोट कर लेती हूँ। आप कौन बोल रहे हैं, और किस काम से कॉल किया था? |
| `rcp.greet.intro.en` | Hello, this is Friday, {user}'s virtual assistant. {user} could not take the call just now. I can note down your message. Who is speaking, and what is it about? |
| `rcp.greet.generic.hinglish` | Hello, main Friday bol rahi hoon, ek virtual assistant. Aap kisse baat karna chahte the, aur kya kaam tha? |
| `rcp.greet.generic.hi` | हैलो, मैं फ्राइडे बोल रही हूँ, एक वर्चुअल असिस्टेंट। आप किससे बात करना चाहते थे, और क्या काम था? |
| `rcp.greet.generic.en` | Hello, this is Friday, a virtual assistant. Who were you trying to reach, and what is it about? |
| `rcp.ask.name.hinglish` | Aapka naam kya hai? |
| `rcp.ask.name.hi` | आपका नाम क्या है? |
| `rcp.ask.name.en` | May I have your name? |
| `rcp.ask.reason.hinglish` | Aap kis baare mein baat karna chahte the? |
| `rcp.ask.reason.hi` | आप किस बारे में बात करना चाहते थे? |
| `rcp.ask.reason.en` | What would you like me to tell them it is about? |
| `rcp.ask.reason_named.hinglish` | Ji {name}, aap kis baare mein baat karna chahte the? |
| `rcp.ask.reason_named.hi` | जी {name}, आप किस बारे में बात करना चाहते थे? |
| `rcp.ask.reason_named.en` | Thank you, {name}. What is it about? |
| `rcp.unclear.hinglish` | Maaf kijiye, mujhe samajh nahi aaya. Kya aap dobara bata sakte hain? |
| `rcp.unclear.hi` | माफ़ कीजिए, मुझे समझ नहीं आया। क्या आप दोबारा बता सकते हैं? |
| `rcp.unclear.en` | Sorry, I did not catch that. Could you say it again? |
| `rcp.readback.hinglish` | Theek hai, main note kar rahi hoon: {name}, {reason}. Sahi hai? |
| `rcp.readback.hi` | ठीक है, मैं नोट कर रही हूँ: {name}, {reason}। सही है? |
| `rcp.readback.en` | Okay, I am noting this down: {name}, {reason}. Is that right? |
| `rcp.readback.generic.hinglish` | Theek hai, main aapka message note kar rahi hoon. Sahi hai? |
| `rcp.readback.generic.hi` | ठीक है, मैं आपका मैसेज नोट कर रही हूँ। सही है? |
| `rcp.readback.generic.en` | Okay, I am noting your message down. Is that right? |
| `rcp.retake.hinglish` | Theek hai, phir se bataiye. |
| `rcp.retake.hi` | ठीक है, फिर से बताइए। |
| `rcp.retake.en` | Okay, please tell me again. |
| `rcp.callback.noted.hinglish` | Theek hai, aapka number note kar liya. |
| `rcp.callback.noted.hi` | ठीक है, आपका नंबर नोट कर लिया। |
| `rcp.callback.noted.en` | Okay, I have noted your number. |
| `rcp.close.message.hinglish` | Theek hai, main aapka message {user} tak pahuncha deti hoon. Thank you. |
| `rcp.close.message.hi` | ठीक है, मैं आपका मैसेज {user} तक पहुँचा देती हूँ। थैंक यू। |
| `rcp.close.message.en` | Alright, I will pass your message on to {user}. Thank you. |
| `rcp.close.no_details.hinglish` | Theek hai, main {user} ko bata dungi ki aapne call kiya tha. Thank you. |
| `rcp.close.no_details.hi` | ठीक है, मैं {user} को बता दूँगी कि आपने कॉल किया था। थैंक यू। |
| `rcp.close.no_details.en` | Alright, I will let {user} know that you called. Thank you. |
| `rcp.close.noted.hinglish` | Theek hai, maine aapki baat note kar li hai. Thank you, goodbye. |
| `rcp.close.noted.hi` | ठीक है, मैंने आपकी बात नोट कर ली है। थैंक यू, गुडबाय। |
| `rcp.close.noted.en` | Alright, I have noted what you said. Thank you, goodbye. |
| `rcp.close.declined_notes.hinglish` | Theek hai, main kuch note nahi karungi, bas itna bataungi ki aapne call kiya tha. Thank you. |
| `rcp.close.declined_notes.hi` | ठीक है, मैं कुछ नोट नहीं करूँगी, बस इतना बताऊँगी कि आपने कॉल किया था। थैंक यू। |
| `rcp.close.declined_notes.en` | Alright, I will not note anything down, only that you called. Thank you. |
| `rcp.ai.answer.hinglish` | Haan, main {user} ki AI assistant hoon. |
| `rcp.ai.answer.hi` | हाँ, मैं {user} की एआई असिस्टेंट हूँ। |
| `rcp.ai.answer.en` | Yes, I am {user}'s AI assistant. |
| `rcp.ai.answer.generic.hinglish` | Haan, main ek AI assistant hoon. |
| `rcp.ai.answer.generic.hi` | हाँ, मैं एक एआई असिस्टेंट हूँ। |
| `rcp.ai.answer.generic.en` | Yes, I am an AI assistant. |
| `rcp.who.hinglish` | Main Friday hoon, {user} ki virtual assistant. |
| `rcp.who.hi` | मैं फ्राइडे हूँ, {user} की वर्चुअल असिस्टेंट। |
| `rcp.who.en` | I am Friday, {user}'s virtual assistant. |
| `rcp.deflect.user_info.hinglish` | Maaf kijiye, main {user} ke baare mein yeh jaankari nahi de sakti. Aap apna message bata dijiye. |
| `rcp.deflect.user_info.hi` | माफ़ कीजिए, मैं {user} के बारे में यह जानकारी नहीं दे सकती। आप अपना मैसेज बता दीजिए। |
| `rcp.deflect.user_info.en` | Sorry, I cannot share that about {user}. Please tell me your message. |
| `rcp.deflect.connect.hinglish` | {user} abhi baat nahi kar paa rahe. Aap message bata dijiye, main pahuncha dungi. |
| `rcp.deflect.connect.hi` | {user} अभी बात नहीं कर पा रहे। आप मैसेज बता दीजिए, मैं पहुँचा दूँगी। |
| `rcp.deflect.connect.en` | {user} is not able to talk right now. Please tell me your message and I will pass it on. |
| `rcp.promise.refuse.hinglish` | Main koi vaada nahi kar sakti, par aapka message zaroor pahuncha dungi. |
| `rcp.promise.refuse.hi` | मैं कोई वादा नहीं कर सकती, पर आपका मैसेज ज़रूर पहुँचा दूँगी। |
| `rcp.promise.refuse.en` | I cannot promise anything, but I will pass your message on. |
| `rcp.secret.refuse.hinglish` | Maaf kijiye, main OTP, PIN ya card jaisi koi jaankari na leti hoon na deti hoon. |
| `rcp.secret.refuse.hi` | माफ़ कीजिए, मैं ओटीपी, पिन या कार्ड जैसी कोई जानकारी न लेती हूँ न देती हूँ। |
| `rcp.secret.refuse.en` | Sorry, I never take or give an OTP, PIN or card details. |
| `rcp.abuse.end.hinglish` | Main yeh baat-cheet yahin khatam kar rahi hoon. Goodbye. |
| `rcp.abuse.end.hi` | मैं यह बातचीत यहीं खत्म कर रही हूँ। गुडबाय। |
| `rcp.abuse.end.en` | I am ending this conversation now. Goodbye. |
| `rcp.silence.prompt.hinglish` | Hello? Kya aap sun pa rahe hain? |
| `rcp.silence.prompt.hi` | हैलो? क्या आप सुन पा रहे हैं? |
| `rcp.silence.prompt.en` | Hello? Can you hear me? |
| `rcp.silence.end.hinglish` | Lagta hai line mein dikkat hai. Aap dobara call kar sakte hain. Goodbye. |
| `rcp.silence.end.hi` | लगता है लाइन में दिक्कत है। आप दोबारा कॉल कर सकते हैं। गुडबाय। |
| `rcp.silence.end.en` | The line seems to have a problem. You are welcome to call again. Goodbye. |
| `rcp.wrong_number.hinglish` | Koi baat nahi, shayad galat number lag gaya. Goodbye. |
| `rcp.wrong_number.hi` | कोई बात नहीं, शायद गलत नंबर लग गया। गुडबाय। |
| `rcp.wrong_number.en` | No problem, you may have dialled the wrong number. Goodbye. |
| `rcp.blocked.end.hinglish` | Abhi message lena possible nahi hai. Thank you, goodbye. |
| `rcp.blocked.end.hi` | अभी मैसेज लेना संभव नहीं है। थैंक यू, गुडबाय। |
| `rcp.blocked.end.en` | I am not able to take a message right now. Thank you, goodbye. |
| `rcp.cap.end.hinglish` | Abhi main aur message nahi le paa rahi. Aap thodi der baad call kar sakte hain. Goodbye. |
| `rcp.cap.end.hi` | अभी मैं और मैसेज नहीं ले पा रही। आप थोड़ी देर बाद कॉल कर सकते हैं। गुडबाय। |
| `rcp.cap.end.en` | I cannot take more messages right now. Please try again a little later. Goodbye. |
| `rcp.timeout.wrapup.hinglish` | Samay kam hai, main aapka message yahin tak note kar leti hoon. Thank you, goodbye. |
| `rcp.timeout.wrapup.hi` | समय कम है, मैं आपका मैसेज यहीं तक नोट कर लेती हूँ। थैंक यू, गुडबाय। |
| `rcp.timeout.wrapup.en` | We are running out of time, so I will note your message as it is. Thank you, goodbye. |
| `rcp.unrouted.close.hinglish` | Main aapka message note kar rahi hoon, par pakka nahi keh sakti ki yeh kisi tak pahunchega, kyunki mujhe nahi pata chala ki aap kisse baat karna chahte the. Behtar hoga ki aap unhe seedha message bhej dein. Thank you. |
| `rcp.unrouted.close.hi` | मैं आपका मैसेज नोट कर रही हूँ, पर पक्का नहीं कह सकती कि यह किसी तक पहुँचेगा, क्योंकि मुझे नहीं पता चला कि आप किससे बात करना चाहते थे। बेहतर होगा कि आप उन्हें सीधे मैसेज भेज दें। थैंक यू। |
| `rcp.unrouted.close.en` | I am noting your message, but I cannot be sure it will reach anyone, because I could not tell whom you were trying to reach. It is better to message them directly. Thank you. |

### 13b. Written to the user on WhatsApp, and the spoken "what did I miss?" (`rcpw.<key>.<language>`)

The `spoken.*` rows are the short version Friday would SAY to the user when they call her; they need audio approval too.

| id | text |
|---|---|
| `rcpw.urgent.head.hinglish` | URGENT: {who} ne abhi call kiya ({when}). |
| `rcpw.urgent.head.en` | URGENT: {who} just called ({when}). |
| `rcpw.normal.head.hinglish` | {who} ne call kiya ({when}). |
| `rcpw.normal.head.en` | {who} called ({when}). |
| `rcpw.spam.head.hinglish` | Spam jaisa call: {who} ({when}). |
| `rcpw.spam.head.en` | Likely spam call: {who} ({when}). |
| `rcpw.line.reason.hinglish` | Kaam: {reason} |
| `rcpw.line.reason.en` | About: {reason} |
| `rcpw.line.snippet.hinglish` | Unke shabd: "{snippet}" |
| `rcpw.line.snippet.en` | Their words: "{snippet}" |
| `rcpw.line.number.hinglish` | Number: {number} |
| `rcpw.line.number.en` | Number: {number} |
| `rcpw.line.callback_number.hinglish` | Unhone yeh number diya: {number} |
| `rcpw.line.callback_number.en` | They gave this number: {number} |
| `rcpw.line.why.hinglish` | Kyun urgent/spam laga: {why} |
| `rcpw.line.why.en` | Why flagged: {why} |
| `rcpw.line.no_message.hinglish` | Unhone koi message nahi chhoda. |
| `rcpw.line.no_message.en` | They left no message. |
| `rcpw.line.declined.hinglish` | Unhone kaha ki kuch note na karein, isliye details nahi hain. |
| `rcpw.line.declined.en` | They asked me not to note anything, so there are no details. |
| `rcpw.who.unknown.hinglish` | ek anjaan number |
| `rcpw.who.unknown.en` | an unknown number |
| `rcpw.who.named.hinglish` | {name} ({number}) |
| `rcpw.who.named.en` | {name} ({number}) |
| `rcpw.who.contact.hinglish` | {contact} |
| `rcpw.who.contact.en` | {contact} |
| `rcpw.reply.callback.hinglish` | Theek hai. Call back ke liye number: {number}. Is par tap karke call kar lijiye. |
| `rcpw.reply.callback.en` | Okay. Number to call back: {number}. Tap it to call. |
| `rcpw.reply.ignore.hinglish` | Theek hai, ignore kar diya. |
| `rcpw.reply.ignore.en` | Okay, ignored. |
| `rcpw.reply.block.hinglish` | {number} ko Friday par block kar diya: ab se unka call message liye bina khatam hoga. Apne phone par bhi block karna ho toh Phone app > Recents > us number par tap karke Block chuniye (main aapke phone par block nahi kar sakti). |
| `rcpw.reply.block.en` | Blocked {number} on Friday: their calls will end politely without taking a message. To block on your phone too, open the Phone app > Recents > tap the number > Block (I cannot block on your phone). |
| `rcpw.reply.stale.hinglish` | Yeh message ab available nahi hai. |
| `rcpw.reply.stale.en` | That message is no longer available. |
| `rcpw.digest.head.hinglish` | Kal raat se {n} call(s) miss hui, jo Friday ne uthayi: |
| `rcpw.digest.head.en` | {n} missed call(s) Friday answered since last night: |
| `rcpw.digest.item.hinglish` | - {when} {who}: {reason} |
| `rcpw.digest.item.en` | - {when} {who}: {reason} |
| `rcpw.digest.spam.hinglish` | {n} spam jaise call(s) bhi aaye ({names}). |
| `rcpw.digest.spam.en` | {n} likely spam call(s) too ({names}). |
| `rcpw.missed.none.hinglish` | Koi nayi miss call nahi hai. |
| `rcpw.missed.none.en` | You have no new missed calls. |
| `rcpw.missed.head.hinglish` | Aapki {n} call(s) miss hui: {urgent} urgent, {normal} normal, {spam} spam jaisi. |
| `rcpw.missed.head.en` | You missed {n} call(s): {urgent} urgent, {normal} normal, {spam} likely spam. |
| `rcpw.missed.item.hinglish` | - {when} {who}: {reason} |
| `rcpw.missed.item.en` | - {when} {who}: {reason} |
| `rcpw.missed.calendar.hinglish` | Aaj ka calendar: {events}. |
| `rcpw.missed.calendar.en` | On your calendar today: {events}. |
| `rcpw.spoken.none.hinglish` | Koi nayi miss call nahi hai. |
| `rcpw.spoken.none.en` | You have no new missed calls. |
| `rcpw.spoken.head.hinglish` | {n} call miss hui. {urgent_part}{normal_part}{spam_part} |
| `rcpw.spoken.head.en` | You missed {n} calls. {urgent_part}{normal_part}{spam_part} |
| `rcpw.spoken.urgent.hinglish` | {n} urgent: {who} ne {reason}.  |
| `rcpw.spoken.urgent.en` | {n} urgent: {who} about {reason}.  |
| `rcpw.spoken.normal.hinglish` | {n} normal.  |
| `rcpw.spoken.normal.en` | {n} normal.  |
| `rcpw.spoken.spam.hinglish` | {n} spam jaisi.  |
| `rcpw.spoken.spam.en` | {n} likely spam.  |
| `rcpw.spoken.more.hinglish` | Poori list WhatsApp par bhej di hai. |
| `rcpw.spoken.more.en` | I have sent the full list on WhatsApp. |
| `rcpw.status.on.hinglish` | Receptionist chalu hai: jo call aap {rings} ring tak nahi uthate, Friday uthayegi. |
| `rcpw.status.on.en` | Receptionist is on: calls you do not answer within about {rings} rings go to Friday. |
| `rcpw.status.off.hinglish` | Receptionist band hai. Forwarding band karne ke liye {cancel} dial karein. |
| `rcpw.status.off.en` | Receptionist is off. To stop forwarding on your phone dial {cancel}. |
| `rcpw.test.confirmed.hinglish` | Forwarding sahi chal rahi hai: Friday ko forwarded call mili. |
| `rcpw.test.confirmed.en` | Forwarding works: Friday received the forwarded call. |
| `rcpw.test.failed.hinglish` | Test call forward nahi hui. Codes aur carrier voicemail dobara check karein. |
| `rcpw.test.failed.en` | The test call was not forwarded. Please re-check the codes and the carrier voicemail. |
| `rcpw.button.callback.hinglish` | Call back |
| `rcpw.button.callback.en` | Call back |
| `rcpw.button.ignore.hinglish` | Ignore |
| `rcpw.button.ignore.en` | Ignore |
| `rcpw.button.block.hinglish` | Block |
| `rcpw.button.block.en` | Block |
