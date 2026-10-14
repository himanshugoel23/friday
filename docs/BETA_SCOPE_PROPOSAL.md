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

## The savings engine: "best card, best app, best price" (founder, 14 Oct 2026)
Idea: Friday knows the user's cards, spending and habits, so before any purchase it answers
"kaun sa card, kaun si app, kitna bachega". This is the personal, neutral, no-pitch assistant.

### What the user gives (once, by chat)
- Which cards they hold: bank + card NAME only (e.g. "HDFC Regalia"). **Never card numbers, CVV,
  expiry, OTP.** Optional: monthly spend by category, billing date, reward points balance.
- Apps they use and their address and family size (for groceries).

### What Friday answers
1. **Which card for this purchase:** "Zomato pe Rs 640: SBI Cashback se 5% (Rs 32); HDFC se 3%.
   SBI use karo. Is mahine ka cashback cap: Rs 180 bacha hai."
2. **Which app for this cart:** price + fees + delivery + offers per item or per basket, with an
   honest split: "dal Blinkit se, sabzi Zepto se, total Rs X kam".
3. **Stacking:** card offer + app coupon + bank offer + wallet cashback, only combinations that
   actually work together, with the final price.
4. **Timing:** "Kal sale hai" or "billing date ke baad kharido taaki 45 din ka free credit mile".
5. **Monthly view:** "Is mahine Friday ne Rs X bachaye; aapka kaun sa card use nahi ho raha".
6. **Big purchases:** phone, flights, hotels, appliances: best card + portal + offer, and when to wait.

### How to build it
1. **Card rules table** (versioned, one row per card per category: rate, cap, exclusions, source URL,
   date checked). Start with the 10 to 15 most common Indian cards. Data from public bank pages;
   a person verifies each rule before it goes live; show "last checked" to the user.
2. **User wallet** (card names, optional caps used so far, per user only, encrypted).
3. **Calculator** (pure code, unit-tested, never the language model deciding the number). The model
   only understands the request and writes the reply; every rupee figure comes from the calculator
   (same rule as today: no invented numbers).
4. **Price sources:** user-forwarded screenshots and bills first; app deep links; official APIs or
   MCP where allowed; clearly mark "approximate, price may change".
5. **Proof:** log each recommendation and the actual outcome, so the savings tracker is honest.

### Risks to decide
- Card rewards change often and have hidden exclusions (wallet loads, fuel, rent, insurance, caps).
  A wrong "use this card" loses trust. Mitigation: verified rules, "last checked" dates, ask the user
  to confirm on the card app when the rule is older than 30 days.
- Quick-commerce prices are not public. Early version = card advice (data we control) + link-out
  comparison; full basket comparison comes after partnerships or user-contributed prices.
- Financial rules: card advice from the user's own cards is fine. Recommending NEW cards to apply for
  is a sales-adjacent area (no affiliate links, say so openly; later check legal).
- Privacy: card names and spend patterns are sensitive; per user only, delete in one step, never
  used for ads or sold.

### Suggested first slice (cheap, high wow)
"Kaun sa card?" for the 10 most common cards across food, grocery, fuel, travel, shopping, bills.
Works with no partner APIs, is accurate when verified, and shows saving in rupees right away.

## Bill and credit card payment APIs (web search 14 Oct 2026; secondary sources, verify)
- **Electricity, gas, water, broadband, DTH, credit card** all run on **BBPS (now "Bharat Connect")**,
  run by NPCI Bharat BillPay Ltd. A third-party app connects as a **Customer Operating Unit (COU)** or
  through a licensed partner that is one. Billers connect through a BBPOU/BOU.
- **Licensed providers with APIs:** Razorpay (COU; fetch billers, fetch bill amount, pay), Cashfree,
  EnKash, Setu, BillAvenue. Flow: list categories, list billers, send the customer identifier
  (consumer number, mobile, account), fetch the outstanding bill, pay, check status, receipt.
  Each biller says whether bill fetch is supported. Amounts are in paise.
- **Credit cards:** one vendor guide says RBI requires credit card bill payments through third-party
  apps to go via BBPS from 1 July 2024. Not confirmed in an RBI text. No card-specific API spec found.
- **What we need to use them:** a company, GST/PAN, bank account, partner agreement, UAT
  certification; vendors quote about 1-2 weeks for integration once approved. Holding or moving user
  money is the licensed partner's job, which keeps Friday outside RBI licensing if we only initiate.
- **Cost and fit:** these are payment APIs. Using them means Friday initiates payment (the user
  approves each payment), which changes our current "Friday never pays" rule. Needs a founder
  decision and a legal read.
- **Beta without APIs:** bill reminders and "pay now" links (UPI or the biller app). Bill amount from
  the user's photo/SMS/Gmail. Upgrade to bill fetch via a BBPS partner after the first users.
- Not covered by search: Bharat Connect's own rules for third-party apps, fees to us, and which
  providers allow a start-up without its own license. Next step: ask Razorpay, Cashfree and Setu.

## Google Suite connector: plan (14 Oct 2026)
State: nothing exists in the code yet (only Google Places/Geocoding keys). The connector is new work.
Google rules (vendor blogs, verify in the Google Cloud console): Gmail read scopes are RESTRICTED and
need a yearly third-party security assessment (CASA; cost quoted from about Rs 50k to Rs 60 lakh
depending on the source, weeks to months). Calendar scopes are SENSITIVE: a lighter review (about
3 to 5 business days per Google, per one source). Apps in testing mode can serve a small list of named
test users without verification (about 100; confirm).
Plan:
1. **Now (beta, no review needed):** build with the founder's Google Cloud project in testing mode and
   named testers: OAuth (per user, tokens encrypted per user, one-step disconnect) and Calendar
   read/write: show today's schedule in the morning brief, add reminders and booked appointments,
   avoid clashes ("us waqt aap busy hain").
2. **Then:** submit Calendar for verification (privacy policy URL, a demo video, a domain we own;
   needs the business name).
3. **Gmail, narrow first:** instead of full read, start by the user FORWARDING bills and tickets to a
   Friday address (no Google review), and add Gmail read later with a limited search, after budget and
   the CASA decision. Drive/Docs/Sheets: not needed for the beta.
Rules: ask once and say why; read-only by default; never send email without approval; per-user
data only; never used for training or ads; delete on disconnect.
Founder to do (cannot be done by Claude): create the Google Cloud project, enable the Calendar API,
set up the OAuth consent screen, add the test users, and put the client id and secret in the server
.env (names only in chat or git). Needed first: a privacy policy page and the business name.

## Doing "what Muse does" in India (14 Oct 2026; web search, vendor sources, verify)
| Muse feature | India route for Friday | Beta? |
|---|---|---|
| Read email and calendar | Google connector (plan above): Calendar first, Gmail by forwarding then read later | Calendar yes |
| Bank connection, expense tracking | **Account Aggregator (AA)**: RBI-regulated, consent-based; Friday is a Financial Information User (FIU). Needs Sahamati certification, or use a technical service provider (Setu, Finvu, OneMoney etc.) that handles it. User links the bank by OTP on the AA's screen, Friday never sees the bank login. Gives transactions, balances. | After the first users (needs company, partner, certification) |
| Find and cancel unused subscriptions | Detect recurring debits (UPI AutoPay, NACH, card subscriptions) from AA data or forwarded SMS/emails. Cancel: the mandate is revoked by the user in the UPI or bank app (Friday sends the exact steps or a deep link), or Friday CALLS the merchant to cancel (our hero feature). Friday does not revoke mandates itself. | Detect + guide + call: yes, after data source exists |
| One-time cards (Stripe) | India has no Stripe-style link. Options: (a) **UPI Circle** delegated payments (primary user delegates to a secondary: reported caps Rs 5,000 per payment, Rs 15,000 per month, up to 5 secondary users, via BHIM; reported from news, check NPCI); (b) virtual cards from a licensed issuer partner (RBI rules, KYC, partner needed); (c) the user pays by UPI link each time. | (c) in beta; (a)/(b) later after legal read |
| Phone calls | Already built (22 categories). | Yes |

Principles that stay: Friday never sees bank logins, OTP, PIN or card numbers; every payment or
cancellation is approved by the user; limits are enforced in code; data per user only; consent
screens say what and why; one-step disconnect and delete.
Sequence: (1) calendar + forwarded bills, (2) subscription detection from forwarded SMS/emails/
statements the user uploads (no licence needed), (3) AA bank link through a technical partner,
(4) delegated payments (UPI Circle) after legal read.
Needs from founder: company registration and business name, a partner choice (Setu, Finvu or
other), a lawyer's read on AA/FIU, UPI Circle and payments, and a privacy policy.
