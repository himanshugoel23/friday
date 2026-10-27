# Settled product scope (founder, 2026-10-26; recorded as given)

Source: the founder's message in chat B, "Here's what we settled on" (apparently the outcome of a brainstorm in another chat). The list below is the founder's wording, lightly formatted. Section 2 is MY notes (not decisions): conflicts with standing rules and the open items. Nothing here is built yet.

## 1. As settled by the founder
**Core basics (the foundation)**
- Bill payments through BBPS: electricity, gas, phone. Onboarding by photo of an old bill.
- LPG booking, medicine refills, local vendor bookings, and reminders.
- Approval before any payment, receipts, and simple memory (family, bills, preferences, vendors).

**The four viral launch features, in build order**
1. **Paisa collector:** group money collection through UPI links to the organiser's own UPI ID, with a live tracker and reminders. Fastest to build and spreads through groups.
2. **Gift Rio to your parents:** a prepaid plan, voice-first use by parents in Hindi, and a weekly summary for the child, with the parent's consent.
3. **Savings finder:** find unused or overpriced subscriptions and bills from email or statements, then cancel or switch with approval.
4. **Customer care warrior:** start with written complaints and escalations, then add AI calls that wait on hold and chase refunds.

**Agreed to add next**
- **Voice layer:** WhatsApp voice notes in Hinglish, cleaned up Wispr-style into the right action. (Built 10-26: `friday/speech`.)
- **Custom assistant name:** users can rename their assistant, while the brand stays the same.
- **Morning check-in call,** borrowed from Asmi: "Aaj kya karna hai?"
- **"Speak messy, send clean":** a rambling voice note turned into a polished message to send.
- **Voice-only mode for elders,** where parents just call.
- **"Wrapped" monthly card:** hours saved and money recovered, made for sharing.
- **Live tracking links** to share task progress with family.

**Later (Phase 2 and beyond)**
- An Android app with a floating mic bubble.
- Browser automation for portals with no API, then phone control for selected apps.
- A vendor-side booking system, which starts the marketplace, and A2A connections for businesses.

## 2. My notes: what this changes or conflicts with (to be decided, not decided)
1. **Payments reverse a standing rule.** FEATURES.md and the legal map say Friday never pays and never takes payment. BBPS bill payment and any "approval before payment" means Friday would INITIATE payments. docs/BETA_SCOPE_PROPOSAL.md (founder research, 10-22) says initiating payment needs RBI authorisation or a licensed BBPS partner (names in that doc: Setu, Razorpay etc.); not verified here. Needs an explicit founder decision: reverse the rule only for bill payments through a licensed partner, with the user paying from their own UPI app/PIN where possible.
2. **Paisa collector** collects from many people through UPI links straight to the organiser's own UPI ID, so Friday never holds money (good); it still sits near payment regulation (collect-request rules, reminders to non-users, consent for group members). Legal read needed. The founder's earlier rule "UPI link, user pays in their own app" fits.
3. **"Rio" and "Asmi" are not defined anywhere in the repo.** I do not know what Rio is (a partner's prepaid plan? a wallet? a SIM plan?) or what Asmi's morning call looks like. A prepaid plan that holds value may fall under RBI prepaid-instrument rules. Founder to say what each is.
4. **Parent and child data:** a weekly summary to the child needs the parent's consent as the data owner (DPDP); an elder-only mode needs protection against scams and confusion (no payments by voice, no OTP by voice).
5. **Savings finder** reads email or statements: Gmail is a restricted scope (testers only until Google verifies); statements are uploads. "Cancel or switch" is browser/vault work (docs/CREDENTIAL_VAULT.md, BROWSER_SITE_COVERAGE.md). "Money recovered" in the Wrapped card must count confirmed items only (existing rule in FEATURES.md section 5).
6. **Customer care warrior** brings back hold-fighting, which GO_LIVE_5_DAYS had cut; the written-complaint part first is cheaper and safer.
7. **Phase 1 timeline:** the pilot plan (5 working days after Slice 0) already has more than it can carry. This list needs a cut: which items are IN the first pilot and which wait. Suggested: core reminders + memory + speech layer (built) + Paisa collector (smallest, no money held) + approval/receipts skeleton; everything touching real money or real sites after the legal read.
8. **Custom assistant name:** keep the rule that she says she is an AI assistant; the brand "Friday" must stay discoverable (consent line, disclosure).
