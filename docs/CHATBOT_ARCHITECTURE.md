# Friday's WhatsApp chatbot: architecture and access requests (22 Oct 2026)

Founder: most conversations happen on WhatsApp, so the chatbot is a first-class part of Friday, and he wants to brainstorm it. Most of the pieces exist (channel, front door, router, quotes flow, calls, savings, life state, proactive). This document names the layers, shows what is built, what is missing, and what Friday needs to ask the user for.

## Layers (one message flows top to bottom)
1. **Channel (built, `friday/channels/whatsapp.py`).** Webhook with signature check, text, voice notes, images, PDFs, location pins, contact cards, buttons (up to 3) and lists, templates, media download (16 MB cap), delivery statuses. Rules baked in: the 24-hour window (free text only inside it; templates outside), button titles up to 20 characters, opt-out keywords.
2. **Identity and onboarding (partly built).** The WhatsApp number is the identity. First message: who Friday is (an assistant), what she does and never does, consent to process messages, name, language, city, then one useful first task. Pending: the approved onboarding copy and consent record (workstream in the 5-day plan).
3. **Understanding (built: rules, then the small classifier, then a model with a schema).** Cheap and safe first: keywords and patterns in Hinglish/Hindi/English, then the trained classifier, then the language model only for what is left. Output is always a typed intent with slots, never free text that acts.
4. **Router and skills (built, `friday/integration/router.py`).** One skill per job: call someone, vendor quotes (existing flow), savings (cards, bills), your day (capture, follow-ups, memory controls), Google connect, later: receptionist, media, hold-fighting, reminders to others. Old flows stay untouched when a new switch is off.
5. **Conversation state.** Short-lived state for multi-step asks (which contact, what to say, approve brief) held per user with a timeout; durable facts go to the life state, wallet, bills, contacts. Today call-intake state is in memory for 30 minutes and is lost on restart (to move into the database).
6. **Approvals and safety (built).** Every action that touches the outside world (a call, a booking, a calendar write, a message to a third person) is a proposal shown to the user with buttons, checked by code gates (limits, do-not-call, calling windows, no payments by Friday). The language model proposes; code decides.
7. **Reply composer.** Picks language and register from the user's profile, keeps messages short (one idea, one question), adds buttons for the likely next steps, adds the one-clause "why" on proactive messages, never repeats a line, never states a number that did not come from a tool or the user. All wording lives in "pending approval" copy modules.
8. **Proactive engine (built).** Morning brief, follow-ups, bill reminders, reminders to the user; caps, quiet hours, per-topic mute, template fallback outside 24 hours.
9. **Memory and privacy (built).** Per-user life state, wallet (card names only), bills, contacts; view, edit, forget, export, delete everything.
10. **Observability.** Per-message trace (intent, route, latency, outcome), a review queue for "unhandled" messages that feeds the labelled set, daily cost, alarms, an off switch per skill.

## Brainstorm: choices we should make together (open)
1. **One persona or two modes.** Same Friday on chat and voice (recommended), shorter on voice.
2. **How much free-form chat.** Recommended: Friday answers about the user's own world (day, bills, cards, calls) and politely redirects general questions ("main aapke kaam ke liye hoon") with a wishlist capture, as decided earlier; no generic chatbot.
3. **Chat style.** Hinglish by default, mirrors the user; emojis none or rare; max about 3 lines; buttons for choices; a "menu" word that shows what she can do.
4. **First-run experience.** One wow in the first minute (for example "kal ka din kya hai?" after connecting Calendar, or "kaun sa card?" after adding two cards).
5. **Group chats.** Out for now.
6. **Voice notes.** Answer a voice note with a voice note (needs approved audio) or text with a "listen" option? 
7. **Escalation to a human.** A "help" keyword that reaches the founder's support inbox during the pilot.
8. **Language mirroring and Devanagari.** Parse Devanagari input (basic today), reply in the user's script.
9. **When Friday stays silent.** Silence is a feature: no stage updates, only outcomes and questions only the user can answer.

## What Friday needs to ask the user for (access catalogue)
Principle: ask just in time (at the moment it helps), one thing at a time, say why in one line, make "no" easy and still useful, and show how to remove it. Never ask for passwords, OTPs, card numbers or bank logins.
| What | Why | How we ask | Needs a permission screen? | Notes |
|---|---|---|---|---|
| WhatsApp number, name, language, city | identity, tone, local vendors | first chat | no | name and city typed in chat |
| Consent to process messages | law and trust | onboarding button "Haan, theek hai" | no | consent record stored |
| Google Calendar (events read/write) | knows your day, clash checks, bookings | link at the moment a time matters ("calendar jodun?") | yes, Google consent (testers only until verified) | `calendar.events` only |
| Gmail (read-only, narrow) | bills, tickets, appointments | later, optional, after trust | yes, Google consent (restricted scope; testers only) | switch off by default; or user forwards instead (no permission) |
| Google Drive | not needed for the launch set | skip | would be a restricted scope | if ever: only files the user picks (the per-file `drive.file` scope), never all of Drive |
| Contacts | "mummy ko call karo" needs a number | ask the user to SHARE a contact card in WhatsApp (zero permission) or type the number; save as a nickname once | no | optional later: Google contacts read-only (sensitive scope) |
| Location | nearby vendors, travel time | WhatsApp location pin on request, or a saved home/work place via the onboarding form | no | saved places stay per user |
| Cards (names only) | "which card" answers | chat: "mere paas HDFC Regalia hai" | no | never numbers |
| Bills | reminders | forward text, photo or PDF | no | media understanding later |
| Voice notes and photos | talk and show Friday things | user sends them | no | stored briefly, deletable |
| Phone-number forwarding (voicemail) | receptionist | guided setup page | the user's own carrier code | later slice |
| Notifications and call permission | Friday calls or messages first | opt-in per topic ("subah ka brief?") | no | caps and quiet hours apply |
| Social accounts, SMS inbox, call log, camera roll | not used | never asked | n/a | decided: no social accounts |
Wording for each ask is drafted in pending copy and shown to the founder before anyone sees it.
## Build gaps for the pilot (2 builders now)
Status 22 Oct: (a) is built behind `FRIDAY_CHATBOT_ONBOARDING`, see `docs/CHATBOT_PILOT.md` (wording pending approval, template drafts in `docs/WHATSAPP_TEMPLATES.md`).
(a) the pilot onboarding and consent flow in the router with approved-wording placeholders and a consent record; WhatsApp template drafts for messages sent outside 24 hours; contact-card capture into the contact book; (b) the consumer telephony factory and a `friday consumer call-test` command.
