# Making Friday feel like Jarvis (founder ask, 16 Oct 2026)

Problem: today Friday is request-response (user calls or texts, gets a result). Jarvis feels alive
because it (1) knows what is happening in your life right now, (2) speaks first at the right moment,
(3) is reachable instantly in any way you like, and (4) every channel is the same mind.

## 1. One shared "life state" per user (the missing piece)
A per-user timeline that every channel reads and writes: events (interview 14:00-15:00), commitments
(call mummy tonight, bill due 20th), open tasks (3 vendor calls running), mood/context hints, last things
said. Sources: what the user tells Friday ("kal 2 baje interview hai"), Calendar (after the Google
connector), bookings Friday made, forwarded bills. Stored per user only, encrypted, viewable and
deletable. A live "now" status is derived: in_interview, driving, sleeping (quiet hours), free.

## 2. Proactive follow-ups at the right time (check-ins)
- After an event ends + a delay: "Interview kaisa gaya? Kuch yaad rakhna ho toh bata do." (WhatsApp
  first; a short call only if the user opted in.)
- Before an event: "2 baje interview hai, 1:15 baje nikalna hoga, traffic ke hisaab se."
- After a booking/call outcome, a bill due date, a parent's medicine time.
- Rules: respect quiet hours and caps; never interrupt a busy event (hold until it ends, unless urgent);
  every nudge says why in one clause; user can say "mat poocho" per topic. Built today: proactive
  engine with caps and triggers. To add: event-aware timing and the follow-up templates.

## 3. Same mind on every channel (the interview example)
User calls at 2:30 (during the interview window) and says "yaar aaj interview nahi tha kya? beech mein
kyun call kar raha hai?" Friday reads life state and answers in context: "Haan, aapka interview 2 se 3
hai. Aap theek ho? Agar free ho toh baad mein baat karte hain, ya jo bhi chahiye abhi bata do." (She
does NOT call or ping during a protected event unless the user asked.) Inbound call, WhatsApp text and
voice note all load the same state first, so there is no "who are you again" moment. Build: inject a
short life-state summary into the front-door context for every inbound message and call.

## 4. Always reachable, without hardware (first)
- Friday in the phone's contacts and WhatsApp pinned; voice notes answered in voice.
- Later: a small Friday phone app: home-screen button/widget, lock-screen voice, wake word on the phone,
  earbuds. This is the Siri-like "active at any point" layer and it is software.
- Dedicated device (speaker/pendant) later, only after demand. It adds always-on microphones, which is
  a privacy risk: needs consent, a visible mute, no secret recording, and legal read.

## 5. Personality
Short, warm Hinglish, remembers small things ("kal aap thake lag rahe the"), light humour, never
nagging. Consistent voice (Ritu). The felt "Jarvis" comes from timing and memory more than from raw
intelligence.

## Build order
1. Life-state store + "now" status, fed by user messages and bookings (no new APIs needed).
2. Inbound context injection (calls + WhatsApp read the state).
3. Event follow-up nudges ("kaisa gaya") with quiet-hours and protected-event rules.
4. Google Calendar connector as an automatic source.
5. Phone app with a one-tap and wake-word voice mode.
6. Optional device, after real demand and a privacy review.

## Risks and rules
- Too many nudges kills trust: strict caps, opt-out per topic, learn from "stop".
- Never speak private info on a call to someone else or in a public place: confirm identity by the
  registered number; avoid reading sensitive details aloud unprompted.
- Always-on listening: off by default, explicit consent, local wake word only, no raw audio stored.
- Hear-before-change: every new spoken or written follow-up line needs founder approval first.

## 6. Voice-first on the phone (founder, 16 Oct 2026): "Friday, aaj haircut book kar do"
Goal: the phone is the device; the user talks, Friday talks back, no typing. (Platform rules below are
from general knowledge and must be verified before building.)
**What the app does:** push the mic audio to our server over a live connection, stream the reply voice back
(same Sarvam STT, LLM, TTS pipeline as the call lane, but app audio is wideband and free of telecom cost
and delay). Same shared life state and the same playbooks; "book kar do" starts the normal vendor flow and
the result comes back as a spoken answer plus a card.
**How the user wakes it:**
- Android (best): Friday can be set as the phone's default assistant app, so long-press power/home or a
  home-screen button opens it, like Google Assistant. A hands-free "Hey Friday" works only while a visible
  Friday foreground service holds the mic (battery cost, a persistent notification, stricter rules on
  newer Android). Also: widget, quick-settings tile, earbud/headset button, lock-screen shortcut.
- iPhone: Apple does not let third parties replace Siri or listen for a wake word in the background. We use
  Siri Shortcuts/App Intents ("Hey Siri, ask Friday ..."), the Action button, a lock-screen widget and the
  headset button. Wake word on iPhone stays "Hey Siri" plus the Friday phrase.
- Anyone, any phone: the existing Friday phone number still works as the fallback.
**Build order:**
1. Web voice page (no app store): tap, talk, listen; proves latency and the flow in days.
2. Android app: push-to-talk, assistant role, widget, then optional hands-free mode.
3. iOS app with Shortcuts.
4. On-device only for the wake word (small, no audio leaves the phone until the wake word fires).
**Rules:** mic off unless the user starts it or opts in to hands-free; a visible indicator; no raw audio
kept unless the user agrees; spoken replies avoid reading sensitive details aloud unprompted; every
spoken line still follows hear-before-change.
**Why this beats WhatsApp/call:** no switching apps, instant, lets Friday speak first with a
notification tap-to-talk, and gives the Jarvis/Siri feel on hardware the user already owns.

## 7. iPhone-first voice, and Friday speaking first (founder, 16 Oct 2026)
Hard limits on iPhone (from general knowledge; verify with Apple's current docs): a third-party app cannot
replace Siri, cannot listen for its own wake word in the background, and cannot keep the mic open when the
user has not started a session. So "always active" is built from layers, not one switch.
(India note: most Indian phones are Android; design for both, iPhone first only if that is our target users.)

### A. Friday speaks first (the "Jarvis" moment)
1. **Friday calls the user's phone.** Works on every phone today with the existing call stack. She speaks
   first: "Interview kaisa gaya?" Use for high-value moments only (telecom cost, can feel intrusive). The user
   opts in per topic, with quiet hours.
2. **WhatsApp voice note first,** user replies with a voice note. No new app, works now. Outbound-first
   messages need an approved template (WhatsApp rule).
3. **WhatsApp call from Friday** (Meta's Business Calling API: calls only to users who gave permission;
   availability in India to check). Free over data, better audio.
4. **Friday app incoming call screen (iOS VoIP push + CallKit):** the iPhone rings with the normal full-screen
   call UI over the internet, she speaks when answered. Apple allows it for real calls only; abuse risks
   rejection.
5. **Time-Sensitive notification + Live Activity / Dynamic Island** ("Friday: interview ke baare mein poochna
   hai"), tap and talk. Optional AirPods: notifications can be read aloud for messaging-style apps (check).

### B. The user speaks (no typing)
1. "**Hey Siri, Friday**" via an App Shortcut: opens Friday in voice mode. Two steps, fully hands-free.
2. **Action Button / Back Tap / lock-screen and Control Center control** (one press).
3. **AirPods or headphone button** to start a session.
4. **Voice-session mode:** once started, Friday keeps the mic open with the screen off (like ChatGPT voice),
   conversational and interruptible, until the user ends it. This is the closest iPhone gets to "always
   talking", and it works while walking with AirPods.
5. **Apple Watch (later):** raise-to-talk and a tap on the wrist when Friday wants to speak.
6. Fallback for everything: the Friday phone number and WhatsApp.

### C. What it feels like together
Morning: Friday rings or sends a voice note brief. Midday: user presses the Action Button, "aaj haircut
book karna hai"; Friday asks one question, books via the normal vendor flow, replies by voice. 3 pm: a
Time-Sensitive tap or a short call, "Interview kaisa gaya?". No typing, and she can begin the talk.

### Build order for iPhone
1. **Now, no app:** proactive WhatsApp voice notes and opt-in Friday calls, plus the shared life state.
2. **Web voice page** (works in Safari, tap to talk): proves delay and flow.
3. **iOS app:** voice-session mode, App Shortcut "Friday", Action Button, widget, push (Time-Sensitive,
   Live Activity), then CallKit incoming calls.
4. Android app (assistant role, wake word), then Apple Watch.
Needs from the founder: Apple Developer account (paid, yearly), the business name and a privacy policy,
decision on which proactive moments may use a call vs a voice note, and a legal read on call consent.

## 8. Divert the user's incoming calls to Friday (founder, 16 Oct 2026)
Idea: someone calls the user; the user (or Friday, by rule) sends that call to Friday, who answers as
the user's assistant, finds out what it is about, and reports back. (Carrier and iPhone details are from
general knowledge; verify with each carrier before promising.)
### How it works
1. **Carrier call forwarding to a Friday number.** The user sets it once. Conditional types: when busy, when
   not answered, when unreachable; or unconditional (all calls) for a window like an interview. Set by
   dialling the carrier codes (e.g. *67*number# busy, *61*number# no answer, *62*number# unreachable,
   *21*number# all calls, ##002# cancel; Indian carriers differ) or iPhone Settings > Phone > Call Forwarding
   (all calls only). A guided WhatsApp message gives the exact code per carrier and a one-tap tel: link.
2. **iPhone trick:** declining a call is treated as "busy" by most carriers, so with busy-forwarding set to
   Friday, "Decline" becomes "send to Friday". Test per carrier. (An app cannot auto-answer or intercept
   normal cellular calls on iPhone; Apple's own call screening is not open to third parties.)
3. **Friday answers** on the forwarded leg: "Namaste, main Himanshu ji ki assistant Friday bol rahi hoon.
   Wo abhi busy hain. Kya kaam hai, main unhe bata dungi." She takes name and reason, can answer simple
   things the user allowed (call back time, "meeting mein hain"), ends politely on spam/sales.
4. **Report back:** WhatsApp summary + transcript, buttons: "Call back", "Busy hoon, baad mein", "Spam
   block". Urgent words or a VIP caller -> Friday rings or pings the user immediately.
5. **Rules the user sets:** which contacts always ring through, which are always screened, quiet hours,
   calendar-linked: during a protected event (interview) unknown callers go to Friday automatically.
### Hard parts to decide
- **Which user was the call for?** A forwarded call arrives at Friday's number; carriers do not always pass
  the original dialled number. Fixes: a **unique forwarding number per user** (small monthly cost per
  number from the telephony provider), or rely on original-number information where the carrier gives it.
  Per-user numbers are the reliable choice.
- **Carrier charges:** forwarded calls may be charged to the user by the carrier (differs by plan). Tell
  the user before they turn it on.
- **Call consent and disclosure:** Friday answers third parties: she says she is an assistant, tells
  callers if anything is recorded (our stored-recording rule needs a legal read), no OTP/banking details
  taken. TRAI and DPDP read needed.
- **Selective divert** (only this caller) is not possible at the carrier level for iPhone; it is done by
  routing rules above (VIP list rings through, via the app/contacts), not by per-call buttons.
### Build
1. Receptionist playbook (pending, new lines need founder-approved audio) using the existing inbound call
   lane; outcome: message taken, urgency, caller name.
2. Per-user forwarding numbers + mapping table; onboarding message with codes per carrier.
3. WhatsApp summary and the action buttons.
4. Calendar-linked protected events and VIP lists after the Google connector and the life-state store.

### 8b. Decision (founder, 19 Oct 2026): no per-user forwarding number
Cost per user is too high, so the receptionist uses ONE shared inbound number (or a very small pool). How to know which user a forwarded call is for:
1. **Redirecting / original-called number from the carrier (preferred, to verify).** When a call is forwarded, the network may pass the number originally dialled
   (SIP Diversion or History-Info header, or a provider field such as "forwarded from"). If our telephony provider delivers it reliably for Jio, Airtel, Vi and BSNL, one
   shared number serves every user and costs nothing extra. Test: forward the founder's own phone to Friday's number, call it, and log the webhook fields (masked).
   Build a small inbound-probe command that prints which fields arrived.
2. **Fallback A, ask the caller:** "Aap kisse baat karna chahte hain?" on a small pool where each number holds a handful of users; match the spoken name against those
   few users only. Cost: a slightly awkward first question, and it can reveal that the person is a Friday user (decide wording with the founder).
3. **Fallback B, paid tier:** a dedicated number only for users who pay or who are heavy users; everyone else uses the shared number if option 1 works.
4. **Not recommended:** matching the caller's number against each user's contacts (ambiguous and a privacy risk).
Whatever we pick, calls whose user cannot be determined are never recorded or summarised for a guessed user: Friday says it cannot take the message and ends politely.

### 8c. Making call forwarding almost one tap (asked 19 Oct 2026; carrier codes and phone behaviour from general knowledge, verify per carrier)
Nobody can switch on carrier forwarding silently: the user's own phone must send the code. The shortest honest flow:
1. In WhatsApp Friday asks the carrier with buttons (Jio, Airtel, Vi, BSNL, other) and what to forward (when busy or unanswered, or all calls during an event).
2. Friday sends one https link to a small setup page that shows ONE big button. The button is a `tel:` link carrying the right code with the Friday number and `#` encoded as %23.
   Tapping it opens the phone dialler with the code filled in; the user presses call once; the network shows a confirmation.
   Typical GSM codes (Airtel, Vi, BSNL; Jio uses its own codes, verify): busy `**67*<number>#`, no answer `**61*<number>#`, unreachable `**62*<number>#`, all calls `**21*<number>#`, cancel all `##002#`.
3. The same page has "Turn off" (cancel code) and "Check status" (`*#21#` style) buttons.
4. Verification: a "Test it" button makes Friday ring the user's phone; the user declines or ignores it, the call forwards back, Friday confirms "forwarding works" on WhatsApp (this also doubles as the redirecting-number probe).
5. iPhone: iOS may refuse USSD-style `tel:` links; fallback is Settings > Phone > Call Forwarding (all calls only) with a two-line instruction and a screenshot; conditional forwarding by dial code still works if the dialler accepts it. Test on a real iPhone.
6. Android later: a Friday app can send the code itself in one tap (USSD permission), which gives a true one-tap setup. The web page route needs no app.
Risks: wrong code for a carrier or plan (some plans do not allow conditional forwarding), dual SIM and eSIM, carrier charges (tell the user first), users forgetting it is on (a monthly reminder and a "Turn off" button in every summary).
