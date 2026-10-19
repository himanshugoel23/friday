# Friday: the full feature list (v2, 19 Oct 2026)

Friday is a voice-first personal assistant for Indian users. It talks, calls, remembers your day, saves you money and answers calls for you, working only for the user and never selling anything.
Tags: [LAUNCH] in the agreed launch set; [LATER] planned after launch; [PARKED] founder parked; status in brackets: built+tested offline / designed / open.
Rules that apply to everything: nothing is spoken or sent to a real person before the founder approves the words; the user approves actions; Friday never pays, never takes payment OTP/PIN/card; per-user data only; one-step delete.

## 1. Talking to Friday
- [LAUNCH] WhatsApp text, in Hindi, Hinglish and English; "my requests" and status of any request. (built)
- [LAUNCH] WhatsApp voice notes in and out. (open)
- [LAUNCH] Call Friday's number and talk by voice: ask about your day, bills, cards, or tell her to call someone; she recognises you by your number. (open)
- [LAUNCH] Corrections mid-conversation ("nahi, kal nahi, parso"), one question at a time, confirmation of what she understood. (partly built)
- [LATER] Elder-friendly mode, regional languages, Siri / "Hey Friday" phone app, Apple Watch. [PARKED: hands-free app]
## 2. Friday calls others for you
- [LAUNCH] Businesses: quotes, bookings, enquiries across 22 categories, one comparison message, retries at +1 h and +3 h, "could not reach" message. (built; scripts pending audio approval)
- [LAUNCH] Anyone else: service providers, customer care, family and friends, officials, unknown people, groups with RSVPs, call-backs. (built offline)
- [LAUNCH] You approve the exact brief and opening line first; safety check, shared do-not-call list, limits, calling hours; plain-language report with transcript summary and next-action buttons. (built)
- [LAUNCH] Live call behaviour: always says she is an assistant, truthful if asked "AI?", never invents numbers or reveals private facts, never promises outside your limits, stops on "stop" or "wrong number", handles voicemail, phone menus and hold. (built offline)
- [LATER] Hold-fighting for customer care, reminder and wake-up calls to others (with their consent), personal negotiation, warm transfer "connect me when they pick up".
## 3. Friday answers calls for you (the receptionist and voicemail)
- [LAUNCH] Voicemail replacement via conditional forwarding (no answer, busy, unreachable): takes name, reason, call-back number, summary on WhatsApp. (designed)
- [LAUNCH] Spam handling after the ring: polite end, mark number, show how to block. (designed)
- [LAUNCH] Urgent flagging with an immediate alert; missed-call notes. (designed)
- [LAUNCH] Near one-tap forwarding setup with carrier codes, test call and "turn off" button; identifying which user the call was for on one shared number. (designed; needs a real probe)
- [LATER] Temporary all-calls mode for protected events, patch-through, emergency-call handling.
## 4. Your day, remembered
- [LAUNCH] Life state: appointments, bills, commitments from your messages (Hinglish dates) and from Google Calendar; "what am I doing now". (built)
- [LAUNCH] Follow-ups and reminders: "Interview kaisa gaya?", before-event reminders, bill-due nudges, each with a one-clause reason; quiet hours, daily caps, protected events, per-topic mute. (built)
- [LAUNCH] Morning brief (text built; voice note or call open) and after-event check-in by voice note or call. (open for voice)
- [LAUNCH] Memory controls: what do you remember, forget X, export, delete everything. (built)
## 5. Savings, with no sales pitch
- [LAUNCH] Wallet of your cards by name only (never numbers), "which card for this spend" with a reason, verified rules table, calculator in code. (built; real card rules still to be entered)
- [LAUNCH] Bills: forwarded text or Gmail summaries become bills, reminders with a pay link; you pay in your own app. (built)
- [LAUNCH] Monthly "Friday saved you Rs X" from confirmed items only; ranking takes no revenue input. (built)
- [LATER] Subscription finder and cancellation, bank link through Account Aggregator, offer stacking, travel and big-purchase advice.
## 6. Connections (each user connects their own account)
- [LAUNCH] Google: Calendar read/write and clash check; Gmail read-only narrow search for bills and tickets (switch off by default; testers only until Google verifies). (built vs fake Google)
- [PARKED] Social accounts, Gmail broad access, Drive.
## 7. Trust and control
- [LAUNCH] Approval before calls and actions, code-level safety gates, truthful disclosure, no voice cloning, no emergency-number calls, abuse limits and strikes, shared do-not-call, recordings stored 30 days by default and deletable, encryption per user, "delete everything". (built)
- [LAUNCH] A public "what Friday never does", legal map with open questions, consent screens that say what and why. (drafted; legal read pending)
## 8. How it improves
- [LAUNCH] Learning loop: every business or caller utterance logged (numbers masked), labelled, evaluated; style tool; simulation personas for every use case; spoken lines change only after your approval. (built)
## 9. Parked or later, by your decision
Ordering through platforms and browsers (code stays off in the repo), payments by Friday, devices and hardware, on-device models, social accounts, translation or note-taking during your own calls, insurance and investment advice, call-screening before the phone rings.
## 10. What must happen before real users
Approve wording and audio; create the Google Cloud project; enter real card rules; apply database migrations (0006-0009); decide where Friday runs (no server today); business name, privacy policy and legal read; WhatsApp number and templates; run each launch feature on real test calls to allow-listed numbers; monitoring and an off switch for each feature.
