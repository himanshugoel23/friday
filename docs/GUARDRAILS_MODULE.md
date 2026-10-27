# Guardrails module (`friday/guardrails/`), built 2026-10-27

Status: BUILT. Existing guard behaviours stay ON; everything new is OFF by default and all NEW wording is PENDING founder approval. No migration (nothing is stored in the database; the audit uses the existing audit table). No real sends.

Design: `docs/CHATBOT_GUARDRAILS.md`. This page says what exists, how to switch it, and what is still open.

## The idea
Code, not the language model, decides. Every inbound message goes through `check(message, context)` before any model; every model reply goes through `check_reply(reply, context)` on the way out. A closed list of categories maps to a closed list of actions (`policy.py`); the reply is fixed wording in the user's language.

| Category | Action | Phase | Switch |
|---|---|---|---|
| emergency (chest pain, cannot breathe) | escalate (112 line) | pre | existing (`FRIDAY_GUARDRAILS_ENABLED` + `FRIDAY_CHATBOT_GUARDS`) |
| medical advice (which medicine, dose) | refuse + offer a clinic call | pre | existing |
| fake bill / receipt | refuse + real route | pre | existing |
| out of scope (general knowledge, jokes, essays) | redirect + wishlist | post | existing (`FRIDAY_CHATBOT_OFFTOPIC`) |
| factual (sums, % , time, date) | allow, computed in code | post | existing (`FRIDAY_CHATBOT_QUICK_ANSWERS`) |
| self harm | escalate (caring line, Tele-MANAS 14416, 112) | pre | NEW |
| minors (says under 18; later asks for calls, payments, bookings) | redirect (stop sensitive skills) | pre | NEW |
| legal advice | redirect to a lawyer, offer to call | pre | NEW |
| financial advice (invest, loans, tax) | redirect to a registered advisor | pre | NEW |
| fake documents and fraud (beyond the fake-bill rule) | refuse | pre | NEW |
| harassment and abuse (scare/threaten a person, slurs at Friday) | refuse, strike | pre | NEW |
| adult | refuse, strike | pre | NEW |
| illegal (drugs, weapons, hacking, evading police) | refuse, strike | pre | NEW |
| privacy of other people (their location, chats, number owner) | refuse, strike | pre | NEW |
| prompt injection (ignore instructions, reveal prompt, commands in pasted text) | refuse, strike | pre | NEW |
| prohibited action (pay for me, send my OTP, save a card number) | redirect to QR / link | pre | NEW |
| sensitive codes in chat (see below) | refuse, or hand a login code to the browser worker | pre | NEW |
| politics / religion opinions, "are you a human?" (truthful answer) | redirect / allow with fixed line | post | NEW |
| small talk | allow (the flows reply) | post | NEW (report only) |
| rate limited (volume, repeats, strikes) | one notice, then silence | pre | NEW (`FRIDAY_GUARDRAILS_RATE_LIMIT`) |

`friday guardrails policy` prints the table with the switch of each row.

## Switches (all in `.env.example`)
- `FRIDAY_GUARDRAILS_ENABLED` default **ON**: master switch for the existing behaviours (each also keeps its old switch: `FRIDAY_CHATBOT_GUARDS`, `FRIDAY_CHATBOT_QUICK_ANSWERS`, `FRIDAY_CHATBOT_OFFTOPIC`). With the defaults the pipeline behaves exactly as before the move (the 350 chatbot tests are unchanged and pass).
- `FRIDAY_GUARDRAILS_NEW_CATEGORIES` default **OFF**: self harm, minors, legal, financial, extra fake-document and fraud phrases, harassment and abuse, adult, illegal, privacy, prompt injection, prohibited action, sensitive codes, politics and religion, identity answer, small talk, plus the extra emergency and medicine phrases. When off, old suicide wording is still caught by the existing emergency rule.
- `FRIDAY_GUARDRAILS_RATE_LIMIT` default **OFF**: per-user volume gate (more than 20 messages a minute, the same message 4 times in 2 minutes: mute 5 minutes; 3 strikes in 24 hours: mute 30 minutes; one notice, then silence). Safety messages (emergency, self harm) are never muted. In memory per process (a restart forgets mutes). Note the older `InboundThrottle` and cost `AbuseLimiter` in `friday/api` still run first; this gate is the policy-level one.
- `FRIDAY_GUARDRAILS_OUTPUT_FILTER` default **OFF**: `check_reply` on the brain's reply (replaces: system text or keys, "I am a human", dosing, invented numbers when the caller passes the known set, promises of money or time, injection echoes, card data; adds a disclaimer to medical, legal or investment-sounding text).
- `FRIDAY_GUARDRAILS_LOGIN_OTP_IN_CHAT` default **OFF**: needed (with the new categories) before a login code typed in chat is handed on.

## Where it is wired
- `friday/chatbot/service.py`: `pre` runs `_guardrail(..., "pre")` first (so an emergency is never swallowed by a pending question), `post` runs `_guardrail(..., "post")` after a typed phone number is handled (quick facts, off-topic redirect and wishlist, new post categories). "Reply in Hindi" stays in `_guards`.
- `friday/api/inbound.py`: `InboundPipeline.guardrails` (one shared engine); `_looks_sensitive` redacts the STORED copy of a message that carries a secret; the brain reply goes through `check_reply` when the output filter is on.
- Moved, not copied: `friday/chatbot/guards.py` -> `friday/guardrails/legacy.py`; `friday/chatbot/scope.py` -> `friday/guardrails/scope.py`. The old modules re-export the same names, so the existing tests and imports are untouched. The existing wording stays in `friday/chatbot/copy.py` and is looked up from there.

## Sensitive codes in chat (founder decision 2026-10-27)
- A **login OTP** (4 to 8 digits, also `4 8 2 1`, Devanagari `४८२१`, `otp hai 4821`, `ओटीपी है ४८२१`) is accepted only when Friday itself started a login for that user (`engine.begin_login(user_id, site, task_id)`), once, within 5 minutes. The code goes to the sink (e.g. `OneTimeOtpChannel.submit`) inside the engine and never appears in the decision, the audit, the ring log or an error; the stored chat text is replaced by a placeholder before anything else sees it. A failing worker leaves the login pending and tells the user to try again.
- Always refused with a pointer to the user's own bank or UPI app, or to the secure link: bank, payment or transaction OTPs, UPI or ATM PIN, card number (any 13 to 19 digits that pass the Luhn check, or are called a card), CVV (`c v v 123` too), Aadhaar OTP, and a password typed in chat ("use the secure link").
- A bare number is never an OTP: with no pending login `4821`, `5000`, an order number are left alone. A message that says "otp" plus digits with no pending login is refused ("no login in progress; do not share this code") and never relayed.
- NOT wired yet: nothing in the browser build calls `begin_login` or sets `otp_sink` (the browser worker is another builder's). Until it does, the switch has no effect on real traffic. The sink is a plain callable `(task_id, code)`.
- Open: the copy in WhatsApp/Meta cannot be deleted by us, so the consent wording must say so; legal read (DPDP + WhatsApp retention) still needed.

## Evasions handled
Case, Unicode look-alikes (full-width), zero-width characters, Devanagari digits, letters spaced or dotted (`s u i c i d e`, `f.u.c.k`), repeats (`diiiie`), light leet-speak (`h4ck`, `ign0re`), curly apostrophes, and a few high-risk terms typed with stray gaps (`kh u d ko khatam`). Not handled: spelled-out digits ("four eight two one"), other scripts, images, voice (a voice note is transcribed first and then checked like text), long paraphrases. Rules are phrase based; the model-based classifier in the design doc is NOT built.

## Red-team corpus and gate
- `friday/guardrails/redteam.txt`: 234 invented messages (English, Hinglish, Devanagari; 20+ evasions; 49 harmless look-alikes that must NOT be stopped). Format `category | language | tag | message`; about a quarter (by hash of the text) is the held-out split.
- `friday/guardrails/gate.json` holds the floors (overall and held-out at least 95%, no harmless message stopped, every category at least 90% recall, at least 230 cases). `uv run pytest tests/guardrails/test_redteam.py` enforces them; `uv run friday guardrails eval` prints the report (misses listed).
- Honest limit: the rules and the first corpus were written together, so the 100% today is optimistic. The right next step is to add every real miss from the pilot (the review queue below) as a corpus line.
- Known gap: product-opinion questions like "jeans kaisa hai?" are not caught by a rule (they reach the brain); the old scope rules only cover general knowledge.

## Audit and review
- Every non-allow decision (and every sensitive-code or rate-limit event) is written to the existing audit table as `guardrail.decision` with: category, decision, rule id, phase, language, message length and a snippet of at most 60 characters with phone numbers, long digit runs, emails and links masked. For self harm, emergency, minors and sensitive codes the snippet is empty. No raw text, no user id inside the record (the audit row carries the user id as always).
- `Guardrails.log` is an in-memory ring (500) for the Chat Lab and a daily review. A Chat Lab panel and a persistent review queue are NOT built (the audit table is the queue for now).

## Not built / open for the founder
1. Wording: all ids in `docs/CHATBOT_PILOT.md` ("guardrails wording") need approval; helpline numbers 112 and Tele-MANAS 14416 must be verified (they are from memory, not checked against an official page).
2. Minors: only a declared age in the current process is remembered (`Context.is_minor` lets the caller pass a stored flag); decision pending whether to stop sensitive skills (built) or require parent consent. Needs a profile field if the flag must survive a restart (no migration made).
3. Strike policy numbers (3 strikes, 30 minute mute) are defaults to confirm; who reviews the queue.
4. The trained classifier from the design doc is not built; the rules are the policy.
5. Small talk: only reported (the flows still answer). "One warm line then back to work" is the existing behaviour.
6. `check_reply` runs on the brain path only; fixed chatbot lines are not filtered (they are the approved wording).
