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
