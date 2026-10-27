# Instinct parity (slice 7)

Built offline, fakes only, all switches OFF. Code: `friday/chatbot/parity/`. All wording is in
`friday/chatbot/parity/copy.py` (PENDING_FOUNDER_APPROVAL; Hinglish, Hindi, English). No spoken line changed.
Source list: `docs/INSTINCT_CHAT_3.md`; board: `docs/BUILD_BOARD.md` "Slice 7".

| # | Item | Status | Where | Switch (default off) |
|---|---|---|---|---|
| 1 | Digest after Gmail connect (leads, PAN/KYC phishing warning, storage, dated renewals, self-correction), due within 2 min | built, pure function; not yet called by the Gmail connect flow | `digest.py` | `FRIDAY_PARITY_DIGEST` |
| 2 | Memory recap / forget | SKIPPED: already built (`friday/memory/chat.py`) | | |
| 3 | Invite counter + tokenized link (SHA-256 at rest, one-use) | built; ledger is in memory, needs a table | `invites.py`, `hooks.py` | `FRIDAY_PARITY_INVITES` |
| 4 | Window-reopen nudge, no false urgency | template `chatbot_window_reopen` in `templates.yaml`, `docs/WHATSAPP_TEMPLATES.md`; helper `nudge.py` | | `FRIDAY_PARITY_NUDGES` |
| 5 | Calendar clash / new-invite heads-up | pure detector | `calendar.py` | `FRIDAY_PARITY_NUDGES` |
| 6 | Ride deep links | Uber format built + unit tested; Ola/Rapido say there is no official link | `rides.py` | `FRIDAY_PARITY_RIDE_LINKS` |
| 7 | One turn per user, ordered replies | SKIPPED: exists in `InboundPipeline.handle` | | |
| 8 | Status reply if a task runs > 60 s, with ETA | built (`run_with_status`), not yet used by a long task | `turns.py` | `FRIDAY_PARITY_STATUS` |
| 9 | INR-only formatter, refuse USD / US-card-only routes | built; refusal wired in chat | `pricing.py` | `FRIDAY_PARITY_INR_ONLY` |
| 10 | Fake-document refusal | SKIPPED: exists (`guards.py`, `refuse_forgery`) | | |
| 11 | Reminder escalation WhatsApp -> call, own number only, after non-acknowledgement, via CallGate | built as a decision function + CallGate adapter; does not dial | `escalation.py` | `FRIDAY_PARITY_ESCALATION` |
| 12 | Secure-page-only for OTP/DOB/address | SKIPPED: credential vault / secure page exists | | |

## Uber link format (item 6)
`https://m.uber.com/looking?pickup=<JSON>&drop%5B0%5D=<JSON>`, each JSON URL-encoded
`{"addressLine1","latitude","longitude"}`. The key `drop[0]` is sent with encoded brackets (decodes the same).
Verified by unit tests only (structure, encoding, round trip). NOT verified against a live Uber app or phone.
Never send a link in any other format; Ola and Rapido get the "no official link" line.

## Not verified / open
- Real Gmail/Calendar data (digest and heads-up work on fixtures); the digest is not yet triggered by connect.
- Invite ledger is in memory (lost on restart); asking "invites" issues one new link and uses one invite. Founder decision: invite loop yes/no.
- Uber link on a real phone; founder decision: include ride links yes/no.
- Template wording and Meta approval (category MARKETING proposed); status, escalation and heads-up not wired to schedulers.
- Escalation call must go through the normal call path with CallGate; no call was placed.
- Deliberately skipped (exist on the base branch): items 2, 7, 10, 12.
