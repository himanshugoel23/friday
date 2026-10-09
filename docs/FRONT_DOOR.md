# The front door: people call Friday's number and talk to Friday

BRIEF section "Founder requirement: public front-door number". Until now Friday only placed outbound
calls and handled business call-backs; a person ringing Friday's number was not handled. This is the MVP
of that door: cost-aware, safe, and honest about what it cannot do yet.

Run it: `uv run friday listen` (live, pilot profile) or `uv run friday listen --simulate` (offline).
Codespaces: `bash deploy/codespace_call.sh --listen`. Code: `friday/voice/frontdoor.py` (call loop, guard,
result call-backs), `friday/brain/frontdoor.py` (fixed copy, deterministic understanding),
`friday/voice/telephony/vobiz_app.py` (Vobiz application plumbing), `friday/pilot.py` (`friday listen`),
`friday/api/callbacks.py` (classification hook), `friday/tasks/engine.py` (pilot refusal).

## 1. What happens on a call

```
Vobiz number --answer_url--> /voice/sarvam/inbound --<Stream>--> /voice/sarvam/media (WebSocket)
   -> InboundCallReceived (published in the background, so the media loop keeps reading)
   -> CallbackService.on_inbound_call: match call memory, record the contact, then CLASSIFY
```

| Caller | How we know | What happens |
|---|---|---|
| **Known user** | phone blind-index lookup (`users.get_by_phone`) | front door, greeted by name |
| **Business** | call-memory match (a business Friday called) | **unchanged** business call-back path (approval rule, unverified callers learn nothing) |
| **Unknown** | neither | pilot: front door voice onboarding if allow-listed; other profiles: front door only when `FRIDAY_FRONTDOOR_OPEN_SIGNUP=true`, else the existing "take a message" path |
| **Not allowed** (pilot, number not in `FRIDAY_PILOT_ALLOWED_NUMBERS`; suspended / deleted / waitlisted user; over a limit) | allow-list first, before any database or AI cost | one short fixed AI-voice message, hang up |
| Hidden / unparsable caller ID | `ValueError` on normalising | same cheap message, hang up |

A user wins over a business match (the user's own number can sit in call memory after a translator call).

### The conversation (front-door mode `CallMode.FRONT_DOOR`)

1. Friday answers at once with a **fixed, pre-rendered** line that starts "Hello / Namaste, this is Friday, an
   AI assistant" (female voice, Hinglish by default, Hindi and English variants). Unknown caller: the same clip
   already asks for the name ("greeting_new"). Known user: the disclosure clip, then "Rahul ji, bataiye..."
   (the personal line is warmed into the cache while the disclosure plays).
2. **Language is mirrored turn by turn** from the STT language of each utterance (a one-word "haan" never
   flips it; a regional language is answered in English copy until it has reviewed copy).
3. **Unknown allowed caller: voice onboarding, a deterministic state machine** (no LLM):
   name -> language ("Hindi, English, or a mix?") -> **spoken consent** ("May I store your name and requests
   safely in India? Say yes ... you can say delete everything at any time"). Nothing is written before a
   spoken yes (a bare "ji" is not a yes). On yes: user (`status=onboarding`, `onboarding_step=PIN`), profile
   (name, language) and a consent record (evidence = the words said) are created. **No PIN is asked or spoken**:
   the PIN is set later on WhatsApp, where the existing flow continues at the PIN step. Declining stores nothing.
4. **Personal assistant**: the utterance goes to `brain.interpret` (the same model routing as WhatsApp; the
   brain itself skips the LLM for deterministic cases). For a new request Friday **reads it back** ("I will
   do this: ... Shall I go ahead?") and creates the real task only after a spoken yes, through
   `InboundPipeline.create_task` -> `TaskEngine.submit` with the caller as requester, so memory, vendor lookup,
   the approval-before-booking rule, the DNC list, abuse limits and the pilot allow-list all apply unchanged.
5. **Honest follow-up**: Friday only promises what is built. If a call-back is possible she says she will call
   back "with an update"; if WhatsApp is real she says she will message; otherwise she says she cannot send the
   result on this setup. Never "done" for something that did not happen; a task that fails at once is reported
   with the engine's own reason.
6. Deterministic answers (no LLM): "are you a bot / human / robot" ("Yes, I am an AI assistant, not a human"),
   "who are you / what can you do", "bye / that's all", "delete everything", a PIN/OTP/CVV said aloud
   (refused, never forwarded to the brain, redacted in the transcript).

### Pilot mode: honest about real businesses
In a **live pilot** (`FRIDAY_PROFILE=pilot` and `FRIDAY_MODE=live`) Friday refuses to phone any number that is
not in `FRIDAY_PILOT_ALLOWED_NUMBERS`: the front door says "In this test mode I cannot phone real businesses
yet, so I have not started that" **before** creating anything, and the engine refuses again at plan and at dial
time (`call.blocked_pilot` in the audit log, task fails with that same sentence) in case a path reaches it. A
request to call an allow-listed number (your other phone playing a business) goes through. In the simulator
profile (`--simulate`, tests) simulated businesses are fine.

## 2. Limits and abuse protection (all before any LLM or TTS spend where possible)

| Control | Default | Setting |
|---|---|---|
| Who is served in the pilot | only `FRIDAY_PILOT_ALLOWED_NUMBERS` | |
| Live front-door calls at once | 1 in the pilot, `FRIDAY_FRONTDOOR_MAX_CONCURRENT` otherwise | |
| Max call length | 180 s pilot, 300 s otherwise (checked every turn, plus a hard timeout) | `FRIDAY_FRONTDOOR_PILOT_MAX_CALL_S`, `_MAX_CALL_S` |
| Per caller | 3 per hour, 10 per day | `FRIDAY_FRONTDOOR_PER_CALLER_PER_HOUR`, `_PER_DAY` |
| Global | 40 calls per hour | `FRIDAY_FRONTDOOR_GLOBAL_PER_HOUR` |
| Spend cap (estimated, per process) | `FRIDAY_PILOT_MAX_SPEND_INR` (25) in the pilot, none otherwise | `FRIDAY_FRONTDOOR_SPEND_CAP_INR` |
| Silence / prank | one "I'm still here", then a polite hang-up after 3 silent turns (24 s) | `FRIDAY_FRONTDOOR_MAX_SILENCES` |
| Repeat refused caller | after 3 refusals in an hour the call is dropped without a word | |
| Kill switch | `friday pause` still blocks outbound calls; the door still answers, new tasks are cancelled | |

Rejection lines are fixed and cached (cost: telephony seconds only). Limits are in-memory per process (the
door lives in the process that receives the Vobiz webhook); a second replica would need the shared `Cache`.

## 3. Safety

* **AI disclosure first**, always: every greeting and every rejection starts with it, and a unit test checks it
  for all three languages.
* **No PIN / OTP / CVV by voice, ever.** Vobiz has **no inbound DTMF/stop events in a bidirectional media
  stream** (`<Gather>` is the only DTMF receiver and it cannot run alongside a stream), so a keypad PIN cannot
  be collected inside the stream, and we will not take a spoken one. Sensitive actions (saved identifiers,
  memory reads, settings, circle, delete for a real account, approvals) answer "that needs your PIN, which I
  never take on a call" and stay on WhatsApp behind the PIN. `core.safety.check_speech` runs on every dynamic
  sentence Friday speaks.
* **Caller ID is not authentication.** The voice door can create tasks (like a WhatsApp message from that
  number) and answer public facts about itself, nothing more. "Delete everything" is honoured by voice only
  for a caller who has not consented yet (nothing stored) or an account created minutes ago without a PIN;
  for an account with a PIN it says to ask on WhatsApp.
* **Data minimisation / DPDP**: no row before a spoken yes; the consent record keeps the words said; the
  transcript is a local file (`var/livecalls/frontdoor-*.txt`, pilot only) with secrets redacted and the
  caller number masked; calls are not recorded (`call_record` is forced off in the pilot); the call itself
  is not persisted as a task call, only an audit line without content.
* **Approval rule intact**: a voice request becomes a normal task; an offer still waits in
  `AWAITING_APPROVAL`; **approvals cannot be given on a call** (Friday says so). The result call-back for an
  offer says "nothing is confirmed" and, where WhatsApp is not real, "I have not booked anything".
* DNC, caller-ID pool and rate limits of the engine apply to what the task does afterwards.

## 4. Cost and latency

* Fixed lines (disclosure, greeting, rejection, goodbye, hold, silence, consent, the answers above) are
  pre-rendered into the shared TTS cache when `friday listen` starts: 56 lines, about 4,900 characters, a
  **one-off cost of roughly Rs 10** (then replayed for free, also across restarts through the disk cache or the
  shared Cache). Dynamic text (read-back, the brain's short replies, the name line) is synthesized and cached.
* LLM only for free-form understanding: **0 LLM calls** for rejection, greeting, onboarding, "are you a bot",
  goodbye, delete and secrets. One `brain.interpret` per free-form request (`gpt-5.4-mini` / Claude light
  model routing unchanged). Compact context from `build_context`.
* Estimated cost (internal, upper bound, same constants as the call runner): about Rs 1.3 per minute for
  telephony + STT, Rs 2 per 1,000 billed TTS characters, Rs 0.12 per LLM turn. A full 180 s pilot call is
  about Rs 4-5; a rejected call costs nothing but a few seconds of telephony.
* Latency: deterministic turns need only STT + (cached) TTS. For an LLM turn slower than 1.2 s Friday plays a
  cached "One moment." instead of dead air. Per-turn STT / policy / TTS times are recorded and `friday
  listen` prints p50 / p95 per call. **The live p95 has not been measured** (no real call from here); the
  offline numbers (tens of ms) only show our own code adds nothing. The product guardrail stays p95 < 1.5 s
  (`P95_BUDGET_MS`); the founder's first live call is the measurement. Not built: barge-in (Friday's speech
  is not interrupted), end-of-speech tuning.

## 5. Result call-backs
After a request Friday can ring the caller back (`FRIDAY_FRONTDOOR_RESULT_CALLBACKS=true`): once when an
offer is waiting for approval and once when the task finishes. Rules: only 08:00-21:00 IST, only to a number
the pilot allow-list permits, within the spend cap, never in the engine's critical path (a background task),
never claims a booking. Limits: pending call-backs live in process memory (a restart forgets them, the normal
WhatsApp/outbox message still goes out); a call-back that is not answered is not retried; approvals cannot be
taken on the call-back either.

## 6. Setting up Vobiz (what `friday listen` does for you, and what you must do once)

Once, in the Vobiz console: the number you want people to call must be on the account and voice-enabled
(`SARVAM_CALLER_IDS` must start with it), balance topped up, **call queuing OFF** (as for outbound). Nothing
else is needed: `friday listen` creates the application itself.

`friday listen` (module `vobiz_app.py`, docs: vobiz.ai/docs/applications, /applications/create-application,
/applications/attach-number, /applications/detach-number, /account-phone-number):

1. `GET /Account/{id}/numbers` - the current `application_id` of the number (stored in
   `var/listen/vobiz_link.json` **before** anything changes, so a crash can be undone).
2. `GET /Account/{id}/Application/` - find the application named `friday-front-door` (paginated), else
   `POST /Application/` with `answer_url = FRIDAY_PUBLIC_BASE_URL/voice/sarvam/inbound?token=...`,
   `hangup_url = .../voice/sarvam/hangup?token=...`, both `POST`. An existing one is updated
   (`POST /Application/{app_id}/`) only if the URLs differ (the tunnel address changes on every start).
3. `POST /numbers/%2B91.../application {application_id}` - link the number (nothing is written if it already
   points at the application).
4. On Ctrl+C / error / normal exit: restore. The previous application is re-attached, or the number is
   detached if it had none. If the number was changed by someone else meanwhile it is left alone. If restoring
   fails, `friday listen` prints how to fix it: `uv run friday listen --restore` (also finds a link left by a
   crashed run). Nothing is ever deleted (an unused application is harmless).

All of it is idempotent and tested only against an in-memory fake Vobiz (`FakeVobizAccount`, used by the
tests and by `friday listen --simulate`); the real endpoints were checked against the published docs, **not
against the live account** (the founder runs the first real sync). The answer URL carries the same `inbound`
token the adapter signs; the media WebSocket gets its own per-call token from the XML.
`friday doctor` now also shows (read-only) which application the number rings today.

## 7. Built / not built

| Built (MVP) | Not built (documented gaps) |
|---|---|
| Classification user / business / unknown; pilot allow-list; rejections | **PIN by voice** (impossible without DTMF in a stream; deliberately not spoken) |
| Fixed pre-rendered AI-disclosure greeting, language mirroring | **Keypad PIN capture / "press 1 to agree"** via a `<Gather>` leg before the stream |
| Voice onboarding: name, language, spoken consent, right to delete | **WhatsApp hand-off / wa.me SMS link** (DLT template) at the end of onboarding |
| Request -> read-back -> yes -> real task through the engine | **Approvals, saved identifiers, memory reads, address notes by voice** (PIN-gated) |
| Honest pilot refusal to phone real businesses | **Toll-free (1800) number, missed-call-to-callback** for callers (the `MissedCallReceived` path only serves business call-backs) |
| Per-caller / global limits, one call at a time, max duration, spend cap, silence hang-up | Shared (multi-replica) limits, admission waitlist / daily cap on NEW signups, 18+ confirmation |
| Result call-backs (offer / final), quiet hours | Pending call-back durability, retries, SMS/WhatsApp question instead of a mid-call question |
| `friday listen`, `--simulate`, `--restore`, Codespaces `--listen`, Vobiz sync / restore | Truecaller-verified name, QR / short link, barge-in, recording consent |

## 8. How it is tested (all offline)
`tests/frontdoor/`: known user greeted by name and a real task created with the approval rule intact, new
allow-listed caller onboarded without a PIN, consent declined stores nothing, delete before / after consent,
non-allow-listed caller rejected without any LLM call and dropped silently when repeated, business call-back
unchanged, "are you a bot", pilot refusal (front door and engine), per-caller / global / concurrency /
duration / spend limits, silence hang-up, secrets never reaching the brain, language mirroring, result
call-back rules, Vobiz sync / restore / idempotency / crash recovery / failure on mocked HTTP only, and the
whole `friday listen --simulate` run.

## 9. Risks not tested here
Real audio (Sarvam STT accuracy for names and Hinglish consent, VAD end-of-speech delay, TTS voice); the real
Vobiz Application / attach responses (field names are from the docs); the inbound `From` / `To` form fields on
a real call; that Vobiz keeps the stream open while our handler runs the call (the receive loop is no longer
blocked, but this was not seen live); STIR/spam labelling of the number; Codespace sleep during a call.
