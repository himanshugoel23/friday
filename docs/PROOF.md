# Proof on every "done" message (design section B)

Status (2026-10-27): built and tested with fakes. **No real call, send or audio.** Switch `FRIDAY_PROOF_ENABLED`
is **off by default**; with it off every message is byte-for-byte the old one. All wording lives in
`friday/evidence/copy.py` and is `PENDING_FOUNDER_APPROVAL` (hear-before-change). No spoken lines.

## What it does
After a call ends in success, the engine (`TaskEngine._after_success` -> `_proof_message`) collects evidence from the
call result, asks `DoneGate` what the message may say, stores the evidence and one `done_claims` row, and sends the
gated text. The task stays `COMPLETED`: **no new `TaskStatus`**; the proof level lives on the claim.

## Evidence (`evidence_items`, migration `0013_evidence`)
Levels: `observed` (our system saw it), `vendor_stated` (the business said it), `user_supplied` (the user forwarded it).
There is no "verified by model" level. Kinds: call_summary, call_recording_ref (a pointer only), transcript_excerpt,
screenshot, order_id, booking_ref, receipt_file, confirmation_text, vendor_message, user_confirmed.
Rules in `collector.py` (code decides, model proposes):
- `observed` only for what our code saw (answered call that ended in success; a browser screenshot).
- A reference counts (`vendor_stated`) only if its characters occur in what the CALLEE said in the transcript (spacing and
  punctuation ignored). A reference only the model wrote is dropped.
- No raw document or image bytes in any column. A receipt = sha-256 + extracted fields. A screenshot is kept in the object
  store only when the caller says it was painted over (`masked=True`); otherwise it is dropped. `summary` and `payload`
  are encrypted text (AAD `evidence_items.summary` / `.payload`).

## Minimum evidence per claim (`policy.py`)
| claim | PROVEN needs | default |
|---|---|---|
| booked, ordered | a reference AND an observed item | strict |
| cancelled, rescheduled | an observed item AND the vendor's word (a vendor_stated item or a reference) | strict |
| refund_requested | a reference (ticket) AND an observed item | strict |
| info_found | any observed or vendor_stated item | soft |
Some evidence but a requirement missing = PARTIAL; none = UNPROVEN. Claim type comes from the task type (refund only when
the goal says so).

## Strictness (configurable)
`FRIDAY_PROOF_STRICT` (default true; false makes every claim soft) and `FRIDAY_PROOF_STRICT_CLAIMS` (CSV, default
booked,ordered,cancelled,rescheduled,refund_requested). Strict claim: only PROVEN uses the model's sentence; PARTIAL says
what is missing; UNPROVEN never says "done" and offers one follow-up (text only). Soft claim: the message is kept and one note
is added. Vendor text is data: only the reference (long numbers masked), who, when and duration are interpolated; a transcript
line is never shown.

## Retention and erasure
`FRIDAY_PROOF_RETENTION_DAYS=90` sets `expires_at`; the daily `run_retention` deletes expired items and their screenshot
objects (failures retried through `pending_deletions`). "Delete everything" (`DataPurger`) removes items and claims and
returns screenshot keys through `recording_urls` so the objects are erased too. RLS on, no policy (`rls.sql`).

## Not done / follow-ups
- A "See proof" button (needs a handler in the chat router); the full proof is stored and readable via `repos.evidence`.
- Parent/aggregate completions (discovery, recurring) and browser runs (`collector.from_recorder` is ready, no caller yet).
- Human-fallback line after two failed attempts (needs the support contact).
- Recording offered as a signed expiring link (the existing `media_url` behaviour is unchanged).
- Wording and the switch need founder approval before any real user sees it.
