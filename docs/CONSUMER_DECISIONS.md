# Decisions the builders need from the founder (19 Oct 2026)

Wording to approve (hear/read before anything is shown to a real person): friday/calls/copy.py, friday/liveagent/lines.py (297 lines; start with
disclose.*, stop.*, voicemail.message), friday/savings/copy.py (incl. the footer "Ranking sirf aapke reward se banti hai, kisi bank ya app se commission nahi."),
friday/lifestate/copy.py, friday/google/consent_copy.py.

## Calls (W1, W2)
1. Default limits OK? 10 calls and 30 minutes per user per day, 300 s per call, 3 calls per number per day and 6 per week across all users, 3 strikes = ban.
2. Calling windows: 09:00-19:00 IST for everyone except family and friends 08:00-21:30.
3. Tapping "Call again" reuses the approved plan without asking again?
4. Intro says "virtual assistant", the AI answer says "AI assistant" (matches the 10 Oct decision). Confirm.
5. Voicemail only when the brief allows it, never for customer care, official or business callees.
6. Any approval request (payment ask, unshareable question) makes the call status needs_user_approval.
7. Self-harm / distress line: a verified helpline number must be supplied (placeholder today; the live-agent line says 112).
8. Which legal rows in docs/LEGAL_MAP.md block launch with real recipients.
## Savings (W3)
9. Due-day bill reminder URGENT (bypasses the 3-a-day cap) or normal?
10. "Saved Rs X" counterfactual: the user's usual card, else the next-best card; single-card wallet counts 0; low-confidence rules logged but not counted. Right level?
11. Who verifies card rules and how often (proposal: a named person, monthly, from the issuer's own page).
12. Same purchase asked twice on one day counts once.
## Life state (W4)
13. User-set reminders inside quiet hours: ring through, or hold?
14. Follow-up delay table; do travel and appointments get an after-event nudge?
15. "Delete everything" needs the phrase "haan, sab mita do" (two steps). Right?
16. Retention period for past events and notes.
17. Which topics may use voice-note or call nudges.
## Google (connector)
18. Who calls /google routes (admin token now), Gmail switch for testers, redirect URI, consent wording; create the Google Cloud project (docs/GOOGLE_CONNECTOR.md).
## Still open
A3.1 free-form level for personal calls (recommended: bounded moves, as built); the remaining register items.
