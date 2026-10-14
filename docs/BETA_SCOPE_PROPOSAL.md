# Wider beta: food, grocery, bills, connectors (proposal, 14 Oct 2026)

Why: vendor calls are rare (a few a month per user). Food, grocery and bills are weekly or daily, so
they give daily use, retention and a reason to onboard. It also makes Friday a real assistant.

## Rule that keeps us safe: the user pays, Friday never holds money
Friday finds, compares, prepares and hands over; the user taps pay in their own UPI/app. This keeps
the existing rules (never pays, never sees OTP/PIN/card) and avoids RBI licensing in the beta.

## 1. Food and grocery: compare and order
- Compare the same cart across Swiggy, Zomato, Instamart, Blinkit, Zepto, BigBasket (price, fees,
  delivery time, offers) and send ONE message: cheapest, fastest, and a "Order karo" button.
- Ordering, in order of effort: (a) deep link to the app with the cart prefilled, user pays there
  [fast, no partnership]; (b) official integration/MCP where the platform allows it (Swiggy and
  Zomato MCP, noted in COMPETITORS.md) [needs check of terms]; (c) call the local restaurant or
  kirana directly, which Friday already can do [differentiator].
- Remember per user: usual order, dietary choices, address, family size (that user only).
- Risk: apps may block scraping or prices; use official/partner routes and say "price may change".

## 2. Bill payments
- Beta: reminders and "pay now" deep links (UPI intent / BBPS-enabled apps): electricity, water,
  gas, broadband, mobile recharge, DTH, credit card due. Friday reads the due date and amount (from
  user message, photo of the bill, or Gmail with permission) and nudges before the due date.
- NOT in beta: Friday initiating the payment itself. That needs RBI authorisation (BBPS operating
  unit/agent or a UPI third-party app), a licensed partner, and a legal review. Decide later whether
  to partner with a licensed provider rather than build.
- Autonomy dial: remind only / remind with pay link / (later) pay within Rs X after approval.

## 3. Basic connectors (user's own data, that user only, with permission)
1. Contacts (who to call or message). 2. Google Calendar (appointments, reminders). 3. Gmail (read
bills, tickets; Phase 2 scope, start read-only and narrow). 4. WhatsApp (already). 5. UPI deep links.
6. Maps/Places (already, Google Places). 7. Later: Swiggy/Zomato MCP, vendor WhatsApp agents.
Each connector: ask once, say why, one-step disconnect, per-user encryption.

## Build order (suggested)
1. Bill reminders + pay links (lowest risk, daily value).
2. Food/grocery comparison with deep-link ordering.
3. Calendar + Gmail read-only connectors.
4. Restaurant/kirana order by call (reuse the table and quote playbooks).
5. Partnered payments, after legal review.

## Honest costs and risks
- This roughly doubles the surface to test; each flow needs its own scripts and tests, and the
  "hear before change" rule still applies to any new spoken line.
- Quick commerce price data is the hardest part (no public APIs). We may only get "approximate" or
  link-out comparison at first.
- Legal: DPDP consent for Gmail/bill data; RBI rules for payments; platform terms for ordering.
- Keep the vendor-calling hero; do not become a thin wrapper on other apps. The differentiator is
  still doing the calls and acting inside the user's limits.

## Decisions needed from the founder
1. Payment model for beta: user pays via link (recommended) or wait for a licensed partner?
2. Which two to build first: bills, food, or grocery?
3. Which apps first (e.g. Swiggy, Zomato, Blinkit, Zepto)?
4. Gmail/calendar in the beta or after the first 50 users?

## Wow factor: what makes a customer say "arre wah" (added 14 Oct 2026)
Wow = Friday acts before being asked, saves visible money or time, and shows proof. Candidates
(all keep the user-pays and per-user-data rules):
1. **Morning brief on WhatsApp**: today's bills due, appointments, weather, one suggestion, in the
   user's own language. Daily habit, costs nothing per call.
2. **"Sasta kar do"**: forward any bill or order; Friday finds a cheaper plan/seller and shows
   "you save Rs X a month" (broadband, recharge, grocery basket, insurance renewal).
3. **Photo in, action out**: photo of a bill, a broken tap, a prescription or a menu; Friday reads
   it and acts (reminder, plumber quote call, price comparison).
4. **Voice note in, done in minutes**: speak Hinglish, get one comparison message with a button.
5. **Group and family mode**: one Friday for the household; shared grocery list, bill split reminders.
6. **Savings tracker**: monthly "Friday saved you Rs X and 3 hours" message. This is also the
   retention metric and the fundraising proof.
7. **Calls that feel magic**: Friday phones three vendors at once and returns a comparison in
   minutes (already the hero; make the speed visible, "3 calls done in 6 minutes").
8. **Never-forget layer**: warranty dates, car service, vaccination, renewals, birthdays with a
   suggested gift order.
Suggested beta wow set: 1, 2, 6, 7 (cheap to build, easy to demo, measurable).
Decision needed: which 3 to lead with.
