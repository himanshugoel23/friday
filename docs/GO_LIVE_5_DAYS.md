# Live in 5 days: what "live" means and the plan (22 Oct 2026)

## What can honestly be live in 5 days
A PRIVATE PILOT: the founder plus a handful of named testers (5 to 10), on one WhatsApp number, with real calls only to people who agreed (the allow-list) or to the testers' own phones. Not a public launch: no ads, no open sign-up, no calls to businesses that did not agree.
In the pilot (turned on per tester):
1. WhatsApp chat in Hinglish/Hindi/English, voice notes in and out (voice-note answers are open work, see cuts).
2. "Call someone for me" (family, friends, providers) to allow-listed numbers, with approval of the brief and a report.
3. Savings: "which card" (only with real verified rules the founder enters), bills from forwarded text, reminders.
4. Your day: capture, follow-ups, morning brief (text), Google Calendar for named testers (Google testing mode).
5. Trust: consent screen, "what do you remember / delete everything", off switch, doctor PASS.
## Cut for now (after go-live)
Receptionist/voicemail forwarding, hold-fighting, reminder calls to others, voice-note replies and voice nudges (unless done early), media understanding, desk mode and any wake word, Gmail (unless the founder wants it for himself in testing mode), real card rules beyond a handful, regional languages, polish bundle (backchannels, pronunciation lab).
## Hard dependencies only the founder can clear (the clock depends on these)
1. Server: installer run on the droplet, doctor PASS (day 1).
2. Meta: Facebook account done; Business portfolio, developer app, WhatsApp number added, display name submitted (day 1 to 2; display-name review can take days, so start with the free test number and add the real SIM when approved).
3. Vobiz account upgraded and topped up; consumer caller ID/number assigned (day 1 to 2).
4. Approve the audio kit and wording (day 2 to 3), at least: opening, assistant disclosure, "are you an AI?", stop/wrong number, close, voicemail rule, approval message, report message, consent/onboarding message.
5. The 26 decisions in docs/CONSUMER_DECISIONS.md: answer the top 8 (limits, windows, voicemail, delete phrase, wording).
6. Privacy policy page, a Grievance Officer name, business name (working name allowed), Truecaller verified profile (do not wait for it).
7. Legal: accept in writing a pilot-only risk position (calls only to consenting people), or a lawyer's quick read of docs/LEGAL_MAP.md rows marked blocking.
## Day by day
- **Day 1:** founder: installer + Meta app + doctor. Claude: consumer telephony factory + `friday consumer call-test`, pilot onboarding and consent flow, WhatsApp template drafts, chatbot architecture and access doc, listening-kit generator. Exit: "hi" on WhatsApp gets a reply, doctor PASS.
- **Day 2:** founder: approve audio kit and wording, Vobiz topped up and number linked. Claude: fix what doctor/real server shows, load approved lines, enable the classifier and Silero on the server, templates submitted to Meta. Exit: first real call to the founder's phone works end to end.
- **Day 3:** founder: second call, add 2 testers (allow-list), test the off switch. Claude: Google Calendar connect for the founder, savings rules entry help, bug fixes from real calls, reply-gap tuning. Exit: founder can use chat, a call and the day brief for a full day.
- **Day 4:** invite the first testers (3 to 5), watch logs, daily transcript review with the founder, fix top issues, backups and monitoring check, weekly cost check.
- **Day 5:** go/no-go: no secrets in logs, off switch tested, deletion tested, calls only to consenting people, doctor PASS, two clean days. Then widen to the 10 testers.
## Go/no-go checklist (all must be yes)
- [ ] doctor PASS on the server, database at 0009, backups on
- [ ] WhatsApp reply works, wrong signature rejected, templates approved for anything sent after 24 hours
- [ ] first-line assistant disclosure approved and heard; stop and opt-out work; do-not-call list works
- [ ] calls only to the allow-list; per-user and per-number limits on; kill switch tried
- [ ] consent screen, privacy policy page, grievance contact live; delete-everything tested
- [ ] no secret, number or token in logs (grep check)
- [ ] cost per call known; telephony balance alarm
- [ ] the founder has used it for a day and signs off
## Risks to the 5 days
Meta display-name review and any ID check, Vobiz account state, founder response time on approvals, real-call surprises (STT, noise), WhatsApp templates approval, legal comfort for calling non-users. The plan keeps a fallback at every step: free Meta test number, calls only to the founder's phone, kill switch.
