# Instinct chat 3: what we learn (founder's own test chat, Oct 9-25 2026)

Source: founder's WhatsApp export with Instinct (not in repo; contains personal data). This note is a redacted summary.

## What Instinct does well (copy)
1. **Onboarding in one tap**: waitlist -> "access ready" nudge -> invite-only with N invites to share (viral loop) -> a short "get to know you" question, then it uses the answer (job hunt) for every later suggestion.
2. **Connect-link pattern**: one link per connection (Google, vault). "Nothing connected yet" is stated honestly; connected state is confirmed ("Connected, thank you").
3. **Proactive**: morning heads-up on calendar overlaps, new invite on calendar, "time-sensitive: reply and I'll explain" (this one is a re-open-the-24h-window template trick), 15-min interview reminder, invite-link reminder.
4. **Inbox + subscriptions digest** from Gmail within minutes of connecting: leads needing replies, PAN-phishing warning, storage 99%, failed deploys, renewals with dates. This is the "wow" moment. Self-corrects when wrong ("Correction on your inbox").
5. **Memory recap on request** ("what do you remember about me") with an offer to forget.
6. **Approval discipline**: shows total, stops before payment, offers UPI request / QR / COD; cancels cleanly and says "nothing was charged".
7. **Language mirroring**: switches to Hindi when asked and stays; short, bro-ish tone.
8. **Sensible refusals**: fake fuel bill refused twice (no sample either) with the honest alternative (duplicate bill from the pump); medical: suggests paracetamol with caveats, escalates chest pain to 112.
9. **Insurance research** ranked by claim settlement, not price, using the user's past experience.

## Where it fails (beat)
1. **Slow and flaky browser work**: 5-10 min for fares, QR codes expiring twice, "Status??" asked repeatedly. Founder had to chase.
2. **Contradictions / hallucinated capabilities**: said "I can't phone anyone" (no voice) while Friday can; mixed cake-order state ("never ordered"); wrong sector/address matches; typo hotels; USD prices for an Indian user; US-card-only payment (Link).
3. **Asked for OTPs, DOB and address in chat** and a Zomato/IRCTC/Uber/Ola OTP flow; the user pasted login OTPs into the chat. Friday rule: never in chat, secure page only.
4. **No voice, no calls, no messaging other people** ("can't text my mom", "can't call my brother"). Friday's opening: calls to vendors, hold-fighting, reminders to others, receptionist.
5. **Refuses what Friday could do on a call**: appointments with local parlours ("call karna padega, number dena").
6. **Duplicated / out-of-order replies** (answers arriving after the next question). Friday: one in-flight turn per user, strict ordering.
7. **No savings engine**: lists subscriptions but never compares cards, cheaper plans or coupons.
8. **Phone reminders only on WhatsApp** (admits "miss ho jayega"). Friday: escalate a missed reminder to a call.
9. **Dependence on logins/OTPs for every site**; deep-link fallback (Uber link with coordinates) was the best moment and worked without any login.

## Concrete asks for Friday (feed the build board)
- Deep-link fallback for rides (Uber `m.uber.com/looking` format) instead of browser login; verify formats before sending (Instinct did).
- 24h-window re-open message pattern ("time-sensitive ... reply and I'll explain") = a template; check it against Meta policy (avoid false urgency).
- Invite-count + invite-link loop in the pilot (decision for founder: yes/no).
- Digest-after-connect: send within 2 minutes, correct itself when wrong.
- Reminder escalation: WhatsApp -> call if unacknowledged (we can; Instinct cannot).
- Fake-document refusal wording (see their text) goes into docs/CHATBOT_GUARDRAILS.md as the reference case.
- Memory recap command ("what do you remember") + "forget" are in scope for the chatbot.
