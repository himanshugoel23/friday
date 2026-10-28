# Instinct chat 4: what to learn and where Friday can beat it (2026-10-29)

Source: the founder's own WhatsApp export with Instinct (9-29 Oct 2026). Raw export stays OUTSIDE the repo (it contains personal data: card figures, ID details, one-time codes). This file keeps only generalised lessons, no personal data.

## What Instinct does well (copy the idea, not the code)
1. **Proactive morning/heads-up messages from the user's own calendar and mail** (today's calls, clashes between two calls, "this needs your attention before 3 PM", "interview in 15 minutes"). Friday: connect Google, build the same daily brief (PARITY_DIGEST is built but off).
2. **"What do you remember about me?"** answered as a short, honest list with an offer to delete anything. Friday already has memory recap and forget; keep it this plain.
3. **Always states what it cannot do** (no calls, no texts to others, cannot set a phone alarm) and gives the nearest alternative (a paste-ready message). Friday can do more (calls), but should keep the same plain honesty for what it cannot do.
4. **Stops before money**: shows restaurant, items, address, fees and total, then offers UPI QR / collect request / cash on delivery. Matches Friday's rule (user pays; Friday never pays).
5. **Safety manners**: refused to fabricate a bill for reimbursement (twice, with a useful alternative: ask the pump for a duplicate); gave cautious fever advice and sent chest pain to emergency (112). Friday has these guards; keep the same tone.
6. **Verified deep links** (Uber format) instead of guessing; says when a link needs a partner token.
7. **Mirrors the user's language**: when asked "reply in Hindi" it switched to Devanagari for the rest of the chat.

## Where Instinct is weak (where Friday can beat it)
1. **Browser-only for shopping and rides: slow and fragile.** Minutes of waiting ("Status?" asked three times), Rapido has no web booking, Ola/Uber hide fares until login, Zomato desktop shows only an app-download page, and on 29 Oct it failed the same Zepto atta price question ("Location not found" for 131001, for Sonipat, for every pincode). **Friday with Zepto's official MCP got real prices in seconds** (see HANDOFF 2026-10-29). Lesson: connectors/MCP first, browser last, deep links as the fallback.
2. **Many OTPs in chat for many sites** (Zomato, Ola, Uber, Urban Company, IRCTC); codes expire, the user pastes several times. Friday: official OAuth where it exists (Zepto), so the OTP is typed on the provider's own page, never in chat.
3. **Surprising actions**: it sent a UPI collect request using a UPI id saved in the user's Urban Company account; the user asked "how did you get my UPI id?". Friday rule: never trigger a payment request to a saved id unless the user asked for that exact method; prefer QR/link the user opens.
4. **IRCTC account created by the bot** after asking for date of birth in chat. Friday: do not create government/identity accounts for users in beta.
5. **Out-of-order and contradictory messages** (answers to older questions arriving after newer ones, "correction on your inbox", two replies to one message). Friday: ordered handling per sender (already built), one answer per message, edit instead of correcting later.
6. **Wrong guesses stated as plans** (assumed Gurugram address, misread "Alma society", treated "De" as a festival greeting). Friday: ask one short question when a place/name is low-confidence (query-understanding agent + personal dictionary).
7. **Cannot call** ("I can't phone anyone or take calls"). This is Friday's biggest advantage: calling businesses and holding for the user.
8. **Hotel/payment route limited to US cards** (USD prices, "Link" needs a US card); the user had to ask for rupee prices. Friday: INR only (PARITY_INR_ONLY).
9. **Generic third-party content pages** (a comparison sheet on its own domain). Friday: comparison inside the chat/app with real cards and cited sources.
10. **Cannot message other people or read texts** (hence "copy and send yourself"). Friday: WhatsApp-native on the user's own account is a phase-2 question; for now draft-and-send-yourself is the same.

## Things in this chat that match Friday's decisions (no change)
Invite-only beta with invite links (10 each); waitlist; payment never by the bot; browser logins through a vault, OTP allowed in chat; user can see/forget memory.

## New ideas to consider (not decided; founder to pick)
- **Daily morning brief** from Google (calendar, bills due, renewals) as a proactive feature; credit-card due dates from Gmail were useful but are sensitive (store nothing; show and forget).
- **Subscriptions finder** (receipts in mail + UPI autopay reminder) since many subscriptions are not in email.
- **Verified deep links library** for rides (Uber/Ola/Rapido) as the fallback when no connector exists.
- **Birthday/people reminders** ("mom's birthday today; order a cake?") from memory and calendar.
- **Speech/text language rule**: reply in the script the user writes (Roman Hinglish stays Roman).
