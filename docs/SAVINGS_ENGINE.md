# Savings engine v1 (workstream W3, 19 Oct 2026)

"Kaun sa card?" and "meri bills", with no sales pitch. Code: `friday/savings/`, tests: `tests/savings/`.
Problems covered: B1, B2, B3, B4, B7, B8, B11, B13 (docs/CONSUMER_PROBLEMS.md), plus the savings
engine section of docs/BETA_SCOPE_PROPOSAL.md.

## What it does
- **Wallet.** The user tells Friday which cards they hold: "mere paas HDFC Regalia aur SBI Cashback hai".
  Friday stores the bank and the card NAME only (plus, if the user gives them, billing day, monthly spend,
  cap used, points balance), encrypted per user, and confirms back what it noted. A message that looks
  like a card number, CVV, expiry, OTP or PIN is refused and nothing is stored.
- **Which card.** "kaun sa card Zomato pe 640" -> the user's own cards ranked by the reward each gives,
  with a one-clause reason ("Food delivery pe 5% milega, cap me Rs 300 bacha hai"). If the amount or the
  category is not clear, Friday asks one question instead of guessing.
- **Bills.** The user forwards a bill or SMS (electricity, gas, water, broadband, mobile recharge, DTH,
  credit card). Deterministic regexes read the amount and the due date; the user confirms ("Sahi hai /
  Galat hai"). Reminders: 3 days before, 1 day before, on the day (IST, 09:00), through the proactive
  engine. Buttons: Paid / Snooze / Not mine. A pay link is shown only if the user supplied it, it was in
  the forwarded message, or it is a known biller link from the verified table. Friday never pays.
- **Monthly figure.** "Friday ne is mahine Rs X bachaye", computed ONLY from recommendations the user
  confirmed using (see "Ledger").

## Architecture
```
message -> commands.py (thin router) -> categories.py (amount, category, merchant)
                                     -> wallet.py     (cards, encrypted)    -> store.py -> DB (0008)
                                     -> rules.py      (verified table)      -> store.py
                                     -> calculator.py (pure: best_card)
                                     -> savings_ledger.py (log + user-confirmed outcome)
                                     -> copy.py       (ALL user-facing text)
bills.py: parse forwarded text -> unconfirmed Bill -> user confirms -> reminders = NudgeCandidates
```
- Money is integer paise everywhere; rates are basis points; rounding is half-up to the paise
  (`money.pct_of`). No floats, no model arithmetic.
- `calculator.best_card(spend_paise, category, wallet, rules, today, merchant=None)` is a pure function.
  Per card it takes the applicable rule (merchant rule > category rule > "all" base rate; the one paying
  most wins), applies the minimum spend, the per-payment cap and the monthly cap remaining
  (`rule cap - wallet caps_used`, caps reset each calendar month), and the exclusions (category or
  merchant keys). A card with no usable row is listed under "unknown", never as Rs 0.
- **Confidence.** HIGH = verified and checked within 30 days. MEDIUM = older than 30 days (the answer says
  "confirm on your card app") or a points rule (the rupee value of a point is an estimate). LOW = older than
  90 days, unverified, or an EXAMPLE row. Ranking key = reward x confidence, then reward, then confidence,
  then the card key (stable). Only those inputs reach the ordering.
- The language model is not in this loop: it may later phrase text, never compute a figure or pick a card.
- **Settings** (`friday/savings/config.py`, env `FRIDAY_SAVINGS_*`): `STALE_AFTER_DAYS` (30),
  `VERY_STALE_AFTER_DAYS` (90), `ALLOW_EXAMPLE_RULES` (false; true only in dev/tests), `BILL_HOUR_IST` (9).
  Reminder days (3, 1, 0), options shown (3) and the rate sanity bounds are fields of `SavingsConfig`.
  They live in this package so it merges without touching `core/config.py`.

## Neutrality (B11), enforced by tests
- No input, field, column or CSV column for revenue, commission, affiliate, referral or sponsorship
  exists (`CardRule` forbids extra fields; `tests/savings/test_neutrality.py` also walks the syntax
  tree of `calculator.py` and `rules.py` for such names and shows the ordering depends only on reward and
  confidence).
- Every option carries a non-empty reason clause (`Option` refuses an empty one).
- No affiliate links, no application links, no "get this new card" anywhere.

## The rules table and its process
Table `card_rules` (one row per card x category, optional merchant list). Columns: card key
(`<bank-slug>/<card-slug>`, filler words such as "card" ignored), category, reward type
(cashback / points / discount), `rate_bp`, `monthly_cap_paise` (cap on the REWARD), `per_txn_cap_paise`,
`min_spend_paise`, exclusions, merchants, `source_url`, `checked_on`, `verified_by`, `valid_from/to`.

**The repo ships no real card offers.** The only rows are in `friday/savings/data/example_rules.csv`:
fake bank "Example Bank", `source_url` on `example.invalid`, `verified_by = EXAMPLE_NOT_REAL`. The loader
refuses them unless `ALLOW_EXAMPLE_RULES` is on, answers built from them are labelled "[EXAMPLE data, asli
offer nahi]", and they have LOW confidence so they can never feed the savings figure.

**Validator** (`rules.validate_rule`): rejects a missing or non-web `source_url`, a missing or FUTURE
`checked_on`, a missing `verified_by` (or a non-person such as "claude", "ai", "bot", "auto", "tbd"), a rate
outside 1..2500 bp (discounts 1..5000), an inverted validity window, an unknown category, duplicates. The
loader keeps only rows with no issue. Unverified rows are refused, not downgraded.

**Who verifies.** A person (name in `verified_by`), reading the bank's own public page, never a model and
never a third-party blog. They record the page in `source_url` and the day they read it in `checked_on`.
**Last-checked policy:** a rule older than 30 days is still used but flagged "confirm on your card app" and
ranks lower; older than 90 days it is LOW confidence. Re-check each row at least monthly; rows with a
`valid_to` expire by themselves.

**Adding a real card row (steps).**
1. Open the card's public page on the issuer's site (rewards table and the terms/exclusions PDF).
2. Write one CSV line per category with the exact rate, caps and exclusions (columns in
   `rules.CSV_COLUMNS`; money in paise, rate in basis points: 5% = 500, Rs 300 = 30000). Put the page in
   `source_url`, today's date in `checked_on`, leave `verified_by` empty (draft).
3. `uv run friday savings rules import rules.csv --dry-run`, then without `--dry-run`. Rows are stored as
   DRAFTS; drafts are never served.
4. A second look at the page, then
   `uv run friday savings rules verify hdfc-bank/regalia --by "Your Name" --checked-on 2026-10-19`.
   The command refuses a non-person name, a missing source, a future date.
5. `uv run friday savings rules list` shows `served / stale / draft / example` per row;
   `export out.csv` writes the table back out.

## Bills, reminders and the proactive engine
- `bills.parse_bill_text` -> `BillParse` (kind, biller, amount, minimum due for cards, due date,
  `missing` fields). Raw forwarded text is not stored; only the confirmed fields are. A long account number
  is never read as an amount; a card number pasted into a credit-card forward is not kept; CVV/OTP/PIN words
  with digits stop the intake.
- `bills.bill_reminders(user_id, bills, now)` returns `NudgeCandidate`s (kind `DATE_BASED`, category
  `REMINDERS`, urgency NORMAL, dedupe key `bill:<id>:d3|d1|d0|snooze...`, `expires_at`, the message text
  and the Paid / Snooze / Not mine buttons in `data`). Only the stage that is current is produced, so a bill
  added late does not get a pile of old reminders. Only confirmed, unpaid, non-snoozed bills of that user
  produce any. The candidate `reason` is the one-clause "why": "aapne BSES ka bill add kiya tha aur uski
  due date 25 Oct (kal) hai".
- The existing guardrails do the rest (tested against `proactive.guardrails.evaluate` and the real
  `ProactiveEngine.process`): quiet hours 22-08 IST, the daily cap of 3 (over the cap a reminder becomes a
  line of the morning digest), ignore-learning, dedupe.
- Button ids: `bill:<bill_id>:ok|paid|snooze|notmine`. Snooze = silent until 09:00 IST next day, then one
  reminder (never past the due day). Every lookup is by `(user_id, bill_id)`.

## Ledger (B12)
Each recommendation is logged (`savings_ledger`); the user answers with a button (`led:<entry>:used|other|
skip`). Rules that keep the figure honest:
- Only "used the recommended card" entries count, and only the FIRST answer is kept (a second tap, or a
  flipped answer, changes nothing).
- Saving = recommended reward minus the counterfactual, floored at 0. Counterfactual = the card the user
  marked as usual ("mera usual card X hai"), else the next-best card in their wallet. A single-card wallet
  has no counterfactual, so it records Rs 0. The summary text states which counterfactual was used.
- The same purchase (user, day, amount, category, merchant) asked twice is one entry.
- Entries whose rule is LOW confidence are logged but not counted (the text says how many).
- When the user confirms, the reward is added to that card's `caps_used` for the month, so the next
  answer reflects the remaining cap.

## Connecting it (for the lead; nothing here edits the front door)
```python
from friday.savings.commands import SavingsCommands
from friday.savings.savings_ledger import SavingsLedger
from friday.savings.store import SavingsRepos

repos = SavingsRepos(c.db, c.clock)                      # or attach to Repositories
cmds = SavingsCommands(wallet=repos.wallet, rules=repos.rules, bills=repos.bills,
                       ledger=SavingsLedger(repos.ledger, c.clock), clock=c.clock)
reply = await cmds.handle(user.id, text)                 # Reply(text, buttons) or None
reply = await cmds.handle_button(user.id, button_id)     # ids starting "led:" or "bill:"
```
- In the inbound pipeline call `handle` before the general classifier and `handle_button` for ids that
  start with `led:` or `bill:` (nudge buttons keep `n:`). Send `reply.text` with `reply.buttons`.
- Proactive: add `*bill_reminders(user_id, bills, now)` to `ProactiveEngine.candidates()` (bills from
  `repos.bills.active_for_user`), and when a candidate has `data["text"]` / `data["buttons"]` use them as the
  nudge text and buttons instead of asking the brain to rephrase (the wording is fixed and pending approval).
- Migration: `0008_savings_engine.py` has `down_revision = "0006_google_connector"`; after W1's 0007 lands,
  point it at 0007. Re-run `uv run python -m friday.db.regen_supabase_sql`.
- "Delete everything" (`DataPurger.purge_user`) already removes wallet cards, bills and ledger rows.

## Gmail later
The Google connector's `GmailClient.find_bills_and_tickets` returns typed `UntrustedEmailSummary` objects
(sender domain, extracted amount, due date, subject; email text is data, never instructions).
`bills.bill_from_email_summary(user_id, summary)` turns one into an UNCONFIRMED `Bill` with
`source = gmail`; the same "Sahi hai / Galat hai" confirmation applies before any reminder. It needs a
due date; it never creates a pay link. Nothing calls it yet (the Gmail switch is off by default).

## What stays out
- No insurance or investment advice or comparison-as-advice (IRDAI / SEBI); no loans.
- No "apply for this new card" recommendations; only the user's own cards are ranked.
- No affiliate or referral link, no sponsored ranking, no revenue input to any ranking function.
- No payments: no UPI collect, no bill pay, no autopay setup. Pay links open the user's own app.
- No card numbers, CVV, expiry, OTP, PIN or bank logins, ever; no BBPS bill fetch yet; no price
  comparison across apps (B5); no subscription detection (B9).

## Unverified and open
- **Every real card rule is unverified because none has been entered.** The beta answers "verified rules
  nahi hain" for cards without rows. A person must enter and verify the first 10 to 15 cards.
- Keyword tables in `categories.py` (merchants, fuel, grocery words) are mine, not reviewed against real
  user messages. Merchant to category is a default; an issuer's own category (MCC) mapping may differ,
  which is why exclusions exist in the rules table.
- Caps are tracked per calendar month; some issuers use the statement cycle (the wallet stores
  `billing_day` but the calculator does not use it yet).
- Bill regexes are tested on invented examples shaped like common SMS/emails, not on real bills.
  `KNOWN_BILLER_LINKS` is empty on purpose.
- All user-facing wording is `PENDING_FOUNDER_APPROVAL` in `friday/savings/copy.py`.
- Question for the founder: should a bill's due-day reminder be URGENT (bypass the daily cap)?
  Today every bill reminder is NORMAL and over-cap ones fall into the morning digest.
