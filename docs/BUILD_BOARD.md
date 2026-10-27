# Build board: one slice at a time (19 Oct 2026)

Rule (founder): finish a slice to 100% before starting the next. A slice is 100% only when every line of its checklist is ticked and the founder has seen it work.

## Definition of done for a slice
1. Spoken or written lines approved by the founder (audio heard for anything spoken).
2. Simulated tests cover it in every launch language; safety invariants pass; full test suite green.
3. Its legal row is cleared, or the risk is accepted in writing.
4. It ran for real on allow-listed test numbers/accounts and the founder watched or listened to the result.
5. It has monitoring, an off switch, and the user can see, undo and delete what it did.
6. Docs and the handoff are updated; the feature switch is turned on only for named testers.

## Order
- **Slice 0: foundation (blocks everything real).** Friday running somewhere, database migrations 0006-0009 applied, WhatsApp number and channel replying, health check and off switches, Google Cloud project for the later slices.
  Needs from the founder: where Friday runs (no server today), the Supabase password step, a WhatsApp Business number, business name and privacy page.
- **Slice 1: "Call someone for me", end to end.** Family/friend call first: request, approval, real consumer telephony factory, live engine, report; approve audio of greet, disclose, are-you-AI, stop, close lines; one real call to the founder's own phone; then a business call through the same path.
- **Slice 2: voicemail and receptionist** (conditional forwarding setup, shared-number user probe, take message, spam, urgent, missed-call note).
- **Slice 3: hold-fighting and reminder calls to others.**
- **Slice 4: voice channels** (call Friday's number, voice notes, voice nudges).
- **Slice 4b: understand media you send** (images, PDFs, voice notes, video, links; docs/MEDIA_UNDERSTANDING.md), founder-requested 21 Oct; order to be confirmed.
- **Slice 5: savings with real, verified card rules.**
- **Slice 6: your day with Google Calendar and Gmail (testers).**
Parked: ordering through platforms, payments by Friday, devices, social accounts.

## Status
| Slice | Code | Real-world | Blocked by |
|---|---|---|---|
| 0 | DONE: installer, migrations, friday doctor, runbook | no | founder: run installer on the existing droplet, Meta account/app, doctor PASS, 'hi' reply |
| 1 | built offline | no | slice 0; telephony factory; audio approval |
| 2-6 | built or designed offline | no | earlier slices |

Parked 21 Oct: always-on listening, wake word, desk mode.

## Slice 7 (added 2026-10-27): Instinct parity + beat list (docs/INSTINCT_CHAT_3.md)
Founder: do everything Instinct does well, and everything where Friday can beat it. Items: (1) digest within 2 min of Gmail connect + self-correction; (2) memory recap / forget; (3) invite count + share link (switch, default off, founder to confirm); (4) re-open-24h-window nudge template (no false urgency); (5) proactive calendar-clash/new-invite heads-up; (6) ride deep links (Uber verified format; no login) - read as "include", founder to confirm; (7) one in-flight turn per user, strict reply ordering; (8) status reply if a task runs > 60 s, with ETA; (9) INR-only prices, no US-only payment routes; (10) fake-document refusal wording; (11) reminder escalation WhatsApp -> call if unacknowledged; (12) secure-page-only for OTP/DOB/address (never in chat).
