# Private browser: flows, agents, sites (Developer B)

Default OFF: `FRIDAY_BROWSER_ENABLED=false`. Code: `friday/connectors/flow.py`, `friday/connectors/sites/**`; tests
`tests/connectors_sites/` (all against FAKE sites; nothing has touched a real site). Design: `PRIVATE_BROWSER_EM.md`.

## Agents (each one job, plain code, model behind `llm.py` interface, fakes in tests)
| Agent | File | Rule |
|---|---|---|
| Planner | `planner.py` | request -> connector from a closed set (`zomato.food`, `bookmyshow.movie`) + slots; LLM answer is validated, anything else falls back to rules |
| Page reader | `reader.py`, `injection.py` | page text scrubbed, instruction-like sentences removed and logged, never passed on |
| Element locator | `locator.py` | selector dict, then reviewed alternates, then at most 3 LLM repairs per task; repairs are logged unconfirmed, used for this task only, never for irreversible clicks |
| Action executor | `executor.py` | `GuardedSession` wraps the `BrowserSession` port, so connectors are unchanged |
| Verifier | `verifier.py` | after every action: block/CAPTCHA/error page stops the run; per-click expectations |
| Safety gate | `safety.py` + `gate.py` | domain allow-list, never type secrets, no payment clicks, approval needed for the irreversible click (armed only after `ActionGate` allows), page text ignored |
| Summariser | `summariser.py` | deterministic, user language, scrubbed |

## Connectors
- **Zomato food** (`zomato_agent.py`, subclass of `food/zomato.py`, whose tests are untouched): search, menu, sold-out check,
  cart, delivery-address check, stop at checkout with a QR / UPI link. There is no pay call.
- **BookMyShow movies** (`movies/`): search shows, seat map, hold seats, QR / UPI link, track booking.
  Why this second site: its read steps are public (search, show times, seats) so it is the least block-prone and gives a
  useful read-only fallback; a seat hold is time-limited and reversible; payment ends in the same QR handoff as food
  (cab apps pay the driver or inside the app, with live-location and surge pricing, and bot checks are stronger);
  Instamart duplicates food and Swiggy has an official MCP route. IRCTC and Amazon skipped as asked.

## Flow (`flow.py`)
request -> one ack -> clarifying question (one at a time) -> approval card (items, merchant, address, price ceiling,
"I never pay") -> run -> login code via the secure one-time page when needed -> QR / UPI link -> user taps "I have paid"
-> one final summary. A price rise after approval, a changed delivery address, or any mismatch with the approval means
the card is shown again (max 2 re-asks). Sold out, no match, cancelled, expired, blocked page, layout change each end with
one outcome message; layout failure marks the connector degraded and gives the "finish yourself" link.
Task state (`TaskState`, JSON, no secrets, no QR bytes) is saved at each phase; `resume(user_id)` continues after a restart.
Buttons: `bf:yes|no|retry|paid:<task_id>`; events: `login_code_ready`, `paid`.

## Wiring for the chatbot owner (not done by me)
```python
from friday.connectors.flow import BrowserFlow, register_browser_handler, get_browser_handler
# at start-up (needs Developer A's SessionManager adapted to flow.SessionProvider, the OTP channel, a send function):
register_browser_handler(BrowserFlow(send=..., registry=..., sessions=..., otp=..., profile=..., login_link=..., base_urls={...}))
# in the router, before the other skills:   h = get_browser_handler()
#   if h and h.enabled() and (h.matches(text) or await h.handle_text(...)):  consumed
# button ids starting "bf:" -> await h.handle_button(user_id, id); secure OTP page stored a code -> await h.handle_event(user_id, "login_code_ready")
```
`handle_text` returns False for unrelated text, so the router continues as before. `friday browser-sim` needs the 3-line
registration shown at the top of `sites/sim_cli.py` in `friday/cli.py`; until then: `python -m friday.connectors.sites.sim_cli`.

## Simulator scenarios (20, `friday browser-sim --list`)
happy path, clarifying questions, cancel, login required (code never typed), wrong code, out of stock / seat taken, price
changed after approval (re-ask, and decline), prompt injection on the page, layout change (alternate, logged model repair,
unrepairable -> finish in app), CAPTCHA page. Food and movie.

## NOT verified / open
- Everything about real Zomato and BookMyShow (markup, login, checkout, anti-bot, terms). Selectors target the fakes.
- Delivery address selection on the real site is not built; only a visible "deliver to" line is compared.
- `LlmRepairer` / `LlmPlanner` have only been run with `FakeLLM`. The port has no DOM outline call: repair uses page text, or an
  optional `outline(max_chars)` method on the session (request to Developer A).
- Restaurant ambiguity: the first match in the user's area is taken and shown on the card (no "which one?" question).
- "7" or "7 baje" is read as 7 pm. Hindi lines are Roman Hinglish; gender of Friday's verbs ("ruk gayi") to be settled.
- SessionProvider is a protocol only; wiring to `SessionManager`, the secure OTP page link and WhatsApp buttons is the owner's.

## All new user-facing lines: PENDING founder approval (hear before change)
Generated from `sites/copy.py` (`friday browser-sim --print-copy`). Nothing here has been approved or heard.

### `ack`
- en: On it. I'll message you only if I need something or when it's done.
- hi: Theek hai, ho jayega. Kuch poochna hua ya kaam ho gaya, tabhi message aayega.

### `q_food_items`
- en: What would you like to order?
- hi: Kya order karna hai?

### `q_food_restaurant`
- en: From which restaurant?
- hi: Kaunse restaurant se?

### `q_address`
- en: Which address should it go to?
- hi: Kis address par bhejna hai?

### `q_movie_title`
- en: Which movie?
- hi: Kaun si film?

### `q_movie_seats`
- en: How many seats?
- hi: Kitni seats chahiye?

### `q_movie_time`
- en: Which show time? (for example 7 pm)
- hi: Kaun sa show? (jaise 7 baje)

### `q_movie_area`
- en: Which area or cinema?
- hi: Kis area ya cinema mein?

### `approve_food`
- en: Please check:
{lines}
From: {merchant}
Deliver to: {address}
Items: {subtotal}. Delivery fee and taxes get added at checkout. I will go ahead only if the final bill is {max_total} or less.
I never pay: you pay in your own UPI app. Go ahead?
- hi: Ek baar dekh lijiye:
{lines}
Kahan se: {merchant}
Kahan bhejna hai: {address}
Items: {subtotal}. Delivery fee aur tax checkout par judte hain. Final bill {max_total} ya usse kam ho tabhi aage badhungi.
Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?

### `approve_movie`
- en: Please check:
Movie: {movie}
Cinema: {merchant}
Show: {when}
Seats: {lines}
Tickets: {subtotal}. Booking fee and taxes get added. I will go ahead only if the final amount is {max_total} or less.
I never pay: you pay in your own UPI app. Go ahead?
- hi: Ek baar dekh lijiye:
Film: {movie}
Cinema: {merchant}
Show: {when}
Seats: {lines}
Tickets: {subtotal}. Booking fee aur tax judte hain. Final amount {max_total} ya usse kam ho tabhi aage badhungi.
Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?

### `reapprove`
- en: Something changed: {reason}
New total: {total} (you approved up to {old_max}).
{lines}
Do you still want it?
- hi: Kuch badal gaya: {reason}
Naya total: {total} (aapne {old_max} tak ka kaha tha).
{lines}
Kya ab bhi chahiye?

### `btn_yes`
- en: Yes, go ahead
- hi: Haan, aage badho

### `btn_no`
- en: No, cancel
- hi: Nahi, rehne do

### `btn_retry`
- en: Try again
- hi: Phir se try karo

### `btn_paid`
- en: I have paid
- hi: Pay kar diya

### `login_needed`
- en: {site} needs you to log in. A code was sent to your phone by {site}. Type it on this private page, never in chat: {link}
Friday never asks for bank or payment codes.
- hi: {site} par login chahiye. {site} ne aapke phone par code bheja hai. Use sirf is private page par daaliye, chat mein kabhi nahi: {link}
Bank ya payment ka code Friday kabhi nahi maangti.

### `login_timeout`
- en: The login code did not arrive in time. Tap below to try again.
- hi: Login code time par nahi mila. Phir se try karne ke liye neeche dabaiye.

### `login_failed`
- en: {site} did not accept that code. Tap below to try again.
- hi: {site} ne woh code nahi manaa. Phir se try karne ke liye neeche dabaiye.

### `payment_ready`
- en: All set. Pay {amount} to {merchant} in your own UPI app: scan this QR{link_part}. I have not paid anything.
- hi: Sab taiyaar hai. {amount} {merchant} ko apne UPI app se dijiye: yeh QR scan kijiye{link_part}. Maine kuch pay nahi kiya hai.

### `link_part`
- en:  or open {link}
- hi:  ya {link} kholiye

### `paid_thanks`
- en: Thanks. {status}
- hi: Shukriya. {status}

### `summary_food`
- en: Done: {lines} from {merchant}, to {address}. Total {amount}, paid by you through UPI.{notes}
- hi: Ho gaya: {merchant} se {lines}, {address} par. Total {amount}, UPI se aapne pay kiya.{notes}

### `summary_movie`
- en: Done: {movie}, {when} at {merchant}, seats {lines}. Total {amount}, paid by you through UPI.{notes}
- hi: Ho gaya: {movie}, {when}, {merchant}, seats {lines}. Total {amount}, UPI se aapne pay kiya.{notes}

### `note_injection`
- en:  The site showed some odd instructions in its text; I ignored them.
- hi:  Site ke text mein kuch ajeeb instructions the; maine unhe ignore kiya.

### `note_repaired`
- en:  The site layout changed a little; I adapted and logged it for review.
- hi:  Site ka layout thoda badla tha; maine adjust kiya aur review ke liye note kiya.

### `out_of_stock`
- en: Sorry, {names} is not available right now, so I stopped before adding anything.
- hi: Maaf kijiye, {names} abhi available nahi hai, isliye kuch add kiye bina ruk gayi.

### `no_match`
- en: I could not find {what} on {site}. Nothing was ordered.
- hi: {site} par {what} nahi mila. Kuch order nahi hua.

### `degraded`
- en: I can't use {site} reliably right now. You can finish it yourself here: {link}
- hi: Abhi {site} ko bharose se use nahi kar pa rahi. Aap khud yahan poora kar sakte hain: {link}

### `blocked`
- en: {site} is asking for a human check, so I stopped. Nothing was ordered. Finish here: {link}
- hi: {site} human check maang raha hai, isliye ruk gayi. Kuch order nahi hua. Yahan poora kijiye: {link}

### `cancelled`
- en: Okay, cancelled. Nothing was ordered or paid.
- hi: Theek hai, cancel kar diya. Kuch order ya pay nahi hua.

### `expired`
- en: That request timed out, so I stopped. Nothing was ordered or paid. Ask me again any time.
- hi: Request ka time khatam ho gaya, isliye ruk gayi. Kuch order ya pay nahi hua. Kabhi bhi phir bolein.

### `error`
- en: I hit a problem and stopped safely. Nothing was ordered or paid.
- hi: Kuch gadbad hui, isliye surakshit roop se ruk gayi. Kuch order ya pay nahi hua.

### `not_available`
- en: Browser ordering is not switched on yet.
- hi: Browser se order abhi chalu nahi hai.
