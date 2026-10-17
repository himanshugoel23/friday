# Browser agent for cab, food, movie, hotel (founder ask, 17 Oct 2026)

Observation (founder's hands-on with Instinct): it drives a private web browser to book cabs, food, movies
and hotels. It asks the user for credentials (email, OTP), and at payment asks for a UPI ID (collect request),
a card saved in its vault, or shows a QR screenshot to pay. Question: can Friday build this?

## Short answer
Yes, technically (a cloud Chromium driven by an agent). But copy the capability, not the credential handling.
Friday's standing rule stays: Friday never sees, stores or speaks OTP, PIN or card details.

## Why not copy the OTP/credential part
- In India "never share your OTP" is the number-one fraud warning from banks and RBI. A bot that asks for
  OTPs trains users into the habit scammers exploit and puts our trust promise at risk.
- OTPs pass through chat/logs/the model: a leak or a prompt injection could expose them. Instinct was
  reported (TechCrunch, Aug 2026) to have pulled a sign-up code from an inbox and failed a phishing test.
- Site terms (Swiggy, Zomato, Uber, Ola, BookMyShow, MakeMyTrip...) generally forbid automation and account
  sharing; accounts can be banned; liability for misuse is unclear.
- Payment OTPs belong to the bank's flow; relaying them breaks the user's bank terms.

## The safer shape (build this)
1. **Private cloud browser per task** (isolated, ephemeral, no shared cookies between users). The agent
   proposes steps; one deterministic action gate decides allow / deny / ask (see Muse note in
   COMPETITORS.md). Page text, reviews and site content are untrusted input.
2. **Do the work, not the secrets:** search, compare, fill the cart, choose the seat/slot, stop at pay.
3. **Login:** user does it themselves in a **takeover view** (a secure streamed browser or a link to the
   site's own login) and types their own OTP; Friday never receives it. Keep a per-user session only if the
   user agrees, encrypted, revocable, expiring.
4. **Payment, in order of safety:**
   a. UPI intent / deep link or the site's QR: Friday sends the QR screenshot or "Pay now" link, the user
      pays in their own UPI app. No credentials involved. (First choice.)
   b. UPI collect request: only where the platform still allows it (NPCI limits collect requests; verify
      current rules) and only after the user approves the exact amount.
   c. Card vault: do NOT build. Storing cards is PCI-DSS scope and RBI tokenisation rules apply; the user
      pays with a card already saved inside the merchant app.
   d. Later: delegated payments (UPI Circle) or a licensed partner, after the legal read.
5. **Approvals:** exact amount, merchant and time, shown as WhatsApp buttons before any payment step.
6. **Audit trail:** screenshots of the cart and the receipt, a summary, and a log of every action.

## Order of preference per site
1. Official MCP/API (Swiggy Builders Club MCP, Zepto, Booking.com MCP; see COMPETITORS.md).
2. Deep link with a prefilled cart (user finishes in the app).
3. Browser agent on public pages without login (prices, availability, show times): read-only comparison.
4. Browser agent with user takeover for login and payment.
Never: relaying OTPs or passwords through chat, storing card numbers, or hiding that Friday is automated.

## Risks and costs
- **Fragile:** site layouts change, A/B tests, CAPTCHAs and bot detection; cloud IPs trigger extra checks.
- **Account bans:** Amazon reportedly blocked the Muse agent. Expect blocks; do not tie to the user's main account
  without consent.
- **Cost and speed:** a browser agent task takes tens of seconds to minutes and costs model calls; keep it for
  the cases where no API exists.
- **Security:** prompt injection from web pages; the action gate and a credential firewall are mandatory before
  any logged-in flow. Needs a security review.
- **Legal read:** platform terms, consumer protection, RBI/NPCI payment rules, DPDP.

## Build order
1. Action gate spec in SECURITY.md (pending).
2. Read-only browser comparison for movies/hotels/cabs (public pages, no login).
3. Takeover view and QR/UPI-intent payment handoff.
4. Logged-in flows for 2 or 3 platforms where an API does not exist, with the user taking over login.
5. Deep links and official MCPs wherever available (these replace browser steps as soon as they exist).
Each user-facing line follows hear-before-change.

## Clarification (founder, 17 Oct 2026): login OTP only; payment by QR
Scope is narrower than first read: Friday needs the user's account LOGIN (email/phone + login OTP) for
Uber, Zomato and similar, and never a payment OTP. Payment = Friday sends a QR (or UPI intent link), the user
pays in PhonePe or any PSP app. This is fine and much safer than relaying payment secrets.
How to handle the login OTP safely:
1. **Log in once per platform, not per order.** After the first login Friday keeps the browser session
   (cookies/token) encrypted per user, expiring and revocable ("Disconnect Zomato"). Next orders need no OTP.
2. **OTP goes through a secure one-time page, never chat.** Friday sends a link; the page has one field,
   explains why, and the code goes straight to that user's browser worker. It is never sent to the language
   model, never logged, deleted after use, and the link expires in minutes. No "send me the OTP in chat".
3. **Preferred when possible:** takeover view (user types the OTP into the site's own login screen), or
   "Sign in with Google/Apple" where the platform offers it.
4. **Android later:** no SMS-reading permission for the app (store policy and abuse risk).
5. The user always sees which account is connected, what Friday did (screenshots, log), and can disconnect.
Remaining risks, unchanged: site terms against automation, new-device checks and bans on cloud IPs, page-text
prompt injection (action gate), and users learning to share OTPs: keep the explanation clear that this is
Friday's own secure page and that Friday never asks for bank, card or payment OTPs.
Order of build unchanged; payment handoff by QR/UPI intent is step 3 and needs no credentials.

## Internal MCP connectors (founder decision, 17 Oct 2026)
Start with the browser. Wrap each site and use case as an INTERNAL MCP server (typed tools), so Friday never
drives a browser directly. When a platform later ships an official MCP or API, we swap the backend, and
nothing above it changes.
### Shape
- **One contract per use case, not per site.** Examples:
  - food: `search_restaurants`, `get_menu`, `build_cart`, `get_price_breakdown`, `get_payment_qr`, `track_order`
  - cab: `get_fare_estimates`, `book_ride`, `get_ride_status`, `cancel_ride`, `get_payment_qr`
  - movie: `search_shows`, `get_seats`, `hold_seats`, `get_payment_qr`
  - hotel: `search_hotels`, `get_rooms`, `hold_room`, `get_payment_qr`
  Every site implements the same tools for its use case (Zomato food, Swiggy food, Uber cab, Ola cab...).
- **Backends behind each connector:** (1) official MCP/API when it exists, (2) deep link, (3) scripted browser,
  (4) LLM-guided browser as a repair fallback only. Prefer scripted Playwright steps over a free-roaming
  agent: faster, cheaper, more reliable, easier to test.
- **Connector registry:** `site + use case + backend + status (live / degraded / off) + version`, with a kill
  switch per connector.
- **Action gate in front** (allow / deny / ask): every state-changing tool (`build_cart`, `book_ride`,
  `hold_seats`) needs an approval scoped to that task and exact details; read tools are allowed.
- **Credential firewall:** login happens inside the connector's session worker; the OTP page (see
  clarification above) feeds the worker directly; tools return only results, never secrets, and tool output
  is scrubbed of tokens and cookies before the model sees it. Page text is untrusted.
- **Per-user sessions:** isolated browser profile per user and platform, encrypted at rest, expiring, revocable.
- **Typed, validated output:** prices as numbers with currency, times as ISO, every field checked by code; the
  model never invents a price that did not come from a tool result.
### Reliability
- Fixture tests from saved pages for every connector; a daily canary run that checks login-free steps (search,
  price read) and flips the connector to `degraded` if the layout changed; alerts and automatic fallback to
  "here is the link, you finish in the app".
- Rate limits and polite behaviour per site; human-like pacing; no scraping of private data; respect
  robots/terms review per site (legal read).
### First connectors (recommended)
1. cab: Uber fare estimate + QR/deep-link handoff (needs login for exact fares).
2. food: Zomato menu/price read + cart build, handoff to pay. Swiggy via its official MCP (apply for access).
3. movie: BookMyShow show/seat read.
Then hotels via Booking.com MCP when onboarded, and trains/flights later.
### Build steps
1. Connector contract + registry + test harness (fake site for tests).
2. Session worker (isolated Chromium, per-user profile) + secure OTP page.
3. First connector end to end with the action gate and WhatsApp approval buttons.
4. Canary monitoring and the kill switch.
5. Add sites; swap backends as official MCPs arrive.

## Reading the user's SMS (asked 17 Oct 2026; platform rules from general knowledge, verify)
Recommendation: do not read SMS in general. Take only what the user hands over, one message at a time.
- **iPhone/iPad:** apps cannot read SMS. The secure code page uses `autocomplete="one-time-code"`, so Safari offers the
  code from the Messages SMS above the keyboard (one tap). An iPad receives the SMS if the iPhone has Text Message
  Forwarding on. An optional iOS Shortcuts automation ("when a message from X arrives, send it to Friday") works only if the
  user sets it up; opt-in, advanced, for bill SMS, never for bank OTPs.
- **Android (future Friday app):** the SMS User Consent API shows a system dialog with the one matching message and the user
  taps Allow; the app sees only that message. The broad READ_SMS permission is restricted by Google Play to default SMS apps
  and a few exceptions, so Friday would not get it. Notification-listener access is also sensitive and policy-limited.
- **Web:** the WebOTP API (Chrome on Android) can fill a code for a page when the SMS ends with `@host #code`; only works for
  SMS sent in that format by the site, so not for Zomato's own SMS.
- **Bills and receipts by SMS:** the user forwards them, or we read the same bills from Gmail (with the Google connector).
- **Why not read everything:** SMS holds other people's banking OTPs and private chats; DPDP and trust risk; Instinct drew
  criticism for pulling a sign-up code from an inbox, and Muse deliberately does not read OTPs from email.
- Rule unchanged: Friday never asks for or relays bank, card or payment OTPs; login codes go only through the secure page.
