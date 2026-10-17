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
