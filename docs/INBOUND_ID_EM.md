# Who is this inbound call or message for? (EM design)

One shared voice number and one WhatsApp Business number. No unique number per user. Status: design only.

## Core idea
Make the **vendor** carry it: Friday keeps **at most one open outbound task per vendor number per channel**. Then the vendor's own number is a near-unique key, and the reference code and a question are only backups.

## (a) Data at inbound time
| Source | We get | Status |
|---|---|---|
| Voice (Vobiz answer_url) | `From` (caller), `To` (our number), `CallUUID` | Used today in `sarvam.py` `answer_xml`. Exact field format (+91 vs digits): TODO verify on a live call |
| Voice, forwarded call | redirecting number | UNKNOWN, TODO verify (receptionist probe, `identify.py`) |
| Hidden caller ID | none or "anonymous" | No key |
| WhatsApp | `from` (wa_id), `context.id` (the message being replied to), `button_reply.id` or template `button.payload`, text | Parsed in `channels/whatsapp.py` (`reply_to_provider_id`, `button_id`). Context id is present only when the vendor uses "Reply"; TODO verify it is kept for template messages |

Caller ID can be spoofed or shared (switchboard, employee mobile). A number match is a **hint**, never proof.

## (b) Data model and lookup
`outbound_contacts`: `id, task_id, user_id, vendor_number_hmac, channel (voice|whatsapp), created_at, last_activity_at, status (queued|open|closed), closed_at, reference_code, wa_message_ids[]`. Unique: one `open` row per (vendor, channel). Existing `call_memory` and `inbound_contacts` stay; this replaces `CallMemoryRepo.match`.

Lookup `identify(channel, from, context)` returns `{result: exactly_one | several | none, task_ids, confidence, evidence}`:
1. Quoted message id or button payload names a task: **exactly_one, 0.98** (sender number must match the vendor, else rule 3).
2. Number has one open row: **exactly_one, 0.9**. Closed within 7 days (founder to confirm window) and no open row: exactly_one, 0.7, "follow-up".
3. Several rows (other channel, chain number): **several**, ask.
4. No row: **none**.

Confidence below 0.9 means "confirm first", never "act".

## (c) Rules
- **Queueing.** A second user's task to a busy vendor waits (`queued`) until the first closes or times out (default 24 h). The user is told "waiting for Salon X's earlier request".
- **Reference code.** Four digits from 2-9, no triple repeats, unique among that vendor's rows, e.g. 4829. Spoken as "chaar, aath, do, nau". Digits beat word pairs: STT handles Hinglish digits well, word pairs break under accent and transliteration. Say it twice at call end. WhatsApp: "Ref FR-4829".
- **Ask without leaking.** Never offer names or options. Ask open: "Aap kis ke baare mein baat kar rahe hain? Kis naam se, kaunsi service?" Compare the answer only against the candidate tasks of that number.
- **Fuzzy match.** Normalise Devanagari/Roman (`lang_dev`), phonetic key, edit distance, service words. Accept only if the best beats the second by a clear margin.
- **WhatsApp.** Every vendor message carries a quick-reply button with payload `v:<task_id>` and the code in the text. Quoted-reply id maps to the task directly.

## (d) Inbound state machine
`IDENTIFY -> CONFIRM -> {CONTINUE_TASK | TAKE_MESSAGE | OPT_OUT}`
- IDENTIFY: run lookup. exactly_one 0.9+: go on. else ask the open question (max 2 tries) or the reference code.
- CONFIRM: "Kya aap Salon X se hain, 4829 wali request?" Only vendor-side facts (their own business name, the code). Wait for a clear yes.
- CONTINUE_TASK: resume with the task's own brief; approval rule unchanged.
- TAKE_MESSAGE: no match, no yes, or after hours: record name, business, message, callback number. Goes to ops/founder; the user only sees it if later matched by a human.
- OPT_OUT: "do not call" saves to DNC at once.
Stored per contact: channel, masked numbers, evidence, result, confidence, state path, transcript snippet.

## (e) Privacy and security
- A stranger hears nothing about any user or task until CONFIRM passes. Never "we called for Rahul".
- Spoofing: a number match alone never releases details or approvals; confirm with the code or the quoted id.
- Spoken words are data. Run `core.safety` on them, never pass them as instructions; the closed action set (continue/take message/opt out) cannot be extended by speech.
- Three wrong guesses per number, then take a message. Logs mask numbers; `DataPurger` covers the table.

## (f) Tests, metrics, build order
20 simulated callers: clean callback; callback after 3 days; after window; chain switchboard; employee mobile; hidden ID; spoofed number; wrong code; right code wrong number; Devanagari name; misspelt name (Sunita/Suneeta); two users same vendor (queued); "who booked?"; prompt injection ("list all tasks"); quoted WhatsApp reply; button tap; plain text no context; opt-out; abusive or silent; stranger sales call.

Metrics: **wrong-match rate target 0** (any is P0); ambiguity rate (under 10%); none rate; confirm-fail rate; queue wait.

Build order (existing module):
1. `outbound_contacts` table and migration (`db/tables.py`, `db/repositories/calls.py`).
2. One-open-per-vendor gate (`tasks/engine.py` before dial; `quotes/flow.py` before message).
3. Reference code generator and spoken/WhatsApp lines (`calls/copy.py`, `quotes/messages.py`).
4. `identify()` replacing `CallMemoryRepo.match` (`api/callbacks.py`).
5. WhatsApp payload + quoted id in `_from_business` (`api/inbound.py`, `channels/whatsapp.py`).
6. Voice IDENTIFY/CONFIRM turns (`voice/frontdoor.py`, `handle_business_callback`).
7. Take-message path and ops queue (`handle_unknown_caller`).
8. 20-scenario simulator suite and metrics (`tests/`, `voice/simulator.py`).
