# QA manual: test every feature by hand, with real calls to your own phone

Status (2026-10-28): built and tested with fakes only. **Nobody has placed a QA call yet**, so every real-call path below is UNVERIFIED until you run it. WhatsApp is blocked by Meta, so you trigger everything from a web page on your iPad (or the `friday qa` command). Friday only ever dials the one number on your allow-list, which must be your own phone.

Code: `friday/qa/` (guard, runner, page, CLI), `deploy/qa-live.sh`, `deploy/qa-https.sh`. Tests: `tests/qa/` (86, all offline). Notes and results go to `var/qa/` on the server (gitignored).

## 1. What is guaranteed (all enforced in code, all tested)
- QA mode is a switch, `FRIDAY_QA_LIVE=true`. It is OFF by default everywhere; `deploy/qa-live.sh` turns it on for its own process only.
- The page and the CLI refuse to start unless `FRIDAY_MODE=live`, `FRIDAY_PROFILE=pilot` and `FRIDAY_PILOT_ALLOWED_NUMBERS` holds **exactly one number** (yours).
- A QA call can only go to that number. A scenario or flow that supplies any other number (a vendor, a redirect, a parameter) is refused before anything is dialled. The number is shown only as its last two digits.
- Business search is replaced by your phone: the Places shortlist is shown as **text only** (names and ratings, never a number) and your phone rings instead. The script keeps the real business name.
- Each call lasts at most **3 minutes**. At most **20 QA calls per day** and an estimated spend of **Rs 100 per day** (names: `FRIDAY_QA_MAX_CALLS_PER_DAY`, `FRIDAY_QA_MAX_SPEND_INR`; the spend is an upper-bound estimate at about Rs 5 a minute, so Rs 100 is roughly six full-length calls and more short ones).
- Kill switch: `friday pause` stops a run at the countdown and again right before the dial. It is always honoured.
- Every call needs your approval: type or tap exactly `YES, call my phone`. Then a visible **"Ring now in N seconds"** countdown (10 s) that you can cancel until the phone rings.
- QA-only override, scoped to your number and to the time a QA call runs: lines marked PENDING_FOUNDER_APPROVAL may be spoken, the per-number daily/weekly cap and the calling window are lifted. Outside QA no pending line is ever played. Each pending line id spoken is written to `var/qa/pending_heard.jsonl`.
- Friday still says she is a virtual assistant. No scenario asks for an OTP, PIN, password or payment. Recording is not switched on by QA (it stays whatever the pilot profile has: off).

## 2. Before you start (all must be true)
- [ ] **Vobiz is topped up** (balance was about Rs 14; each full QA call costs up to about Rs 5 a minute) and a caller ID number is assigned.
- [ ] **Vobiz `call_queue` is OFF** (ask Vobiz; `friday doctor --laptop` lists it as a Vobiz issue).
- [ ] The server `.env` has these names set (you type values on the server, never in chat): `FRIDAY_MODE=live`, `FRIDAY_PROFILE=pilot`, `FRIDAY_PILOT_ALLOWED_NUMBERS` = your phone only, `FRIDAY_CONSUMER_CALLS_ENABLED=true`, `FRIDAY_PUBLIC_BASE_URL` = the https address of the server.
- [ ] `FRIDAY_VENDOR_CALL_REDIRECT_TO` is **not needed** for QA (the scenarios dial your number directly). If you set it, it must be your phone.
- [ ] **https URL works** (`curl https://YOUR-HOST/health` answers ok) and Caddy has the QA route: `sudo bash /opt/friday/deploy/qa-https.sh` (once; run `explore-https.sh` and `lab-https.sh` first if you use them; they keep the `/qa` route).
- [ ] `friday doctor` shows PASS (docs/DOCTOR.md).
- [ ] `friday pause --status` says RUNNING.
- [ ] Nobody else is using the server: the QA page stops the front-door service while it runs and starts it again when you stop it. The Chat Lab (`/lab`) can stay up.

## 3. Start it (iPad)
```
tmux new -s qa
sudo bash /opt/friday/deploy/qa-live.sh
```
It prints `Calls go to +*********42` and a secret link `https://YOUR-HOST/qa/<token>/` (valid 8 hours; `--ttl-hours 2` for shorter). Open the link on the iPad. Detach with ctrl-b d. Stop with ctrl-c (the front door comes back by itself).

Other caps for one session: `sudo FRIDAY_QA_MAX_SPEND_INR=200 FRIDAY_QA_MAX_CALLS_PER_DAY=30 bash /opt/friday/deploy/qa-live.sh` (the names are passed through; they are not read from `.env`).

Same thing without the page, from a terminal: `friday qa list`, `friday qa show <id>`, `friday qa run <id>`.

On the page, for each scenario: tap **Show plan and run**, read what will happen and the REAL vs SIMULATED boxes, tap the big **YES, call my phone** button, watch the countdown, answer your phone, talk. Afterwards tap **OK**, **Wording change** or **Mark wrong: bug** and write a note (the notes box also works for a plain comment).

## 4. The scenarios
`R` = real call to your phone, `S` = simulator (nothing is called), `I` = instructions only. Under "you do", you are the business or person Friday phones.

| Id | Kind | You do | You should hear |
|---|---|---|---|
| `salon_quote` | R | Answer as a salon. Give a price for haircut + beard trim, tomorrow evening. | Approved script: hook, asks the price, books nothing, says she will come back after approval. |
| `salon_quote_pending` | R | Same, but the new PENDING script v7. | Compare the wording with `salon_quote`; approve/reject line ids afterwards. |
| `vendor_table` | R | Answer as a restaurant. Say a table for 4 at 8 is / is not free. | States the request first (4 people, tonight 8), no price question; never books another time on her own. |
| `vendor_home_service` | R | Answer as an AC repair shop. | Describes the problem, asks visit charge and estimate and a time tomorrow morning. |
| `vendor_stock_price` | R | Answer as a phone shop. Say in stock / out of stock. | Asks stock and price of the model, home delivery. |
| `vendor_hotel` | R | Answer as hotel reception. | Room for 2, Friday to Sunday, availability and rate. No booking. |
| `vendor_cab` | R | Answer as a cab operator. | Airport drop tomorrow 6 am, 2 people, fare. |
| `vendor_rental` | R | Answer as a PG owner. | Single-sharing room, rent, deposit, move-in. |
| `vendor_banquet` | R | Answer as a banquet manager. | Free on the date for about 60 guests, price. |
| `consumer_family` | R | Answer as your mother. | Opening line incl. "virtual assistant calling for <you>", then "main late aaunga". Report text printed on the page. |
| `consumer_provider` | R | Answer as a plumber's desk. | More formal; asks for tomorrow's slot. |
| `receptionist_greeting` | R | Answer, listen. | The receptionist lines one by one (greeting, name, reason, read-back, close, "are you AI" answer). One-way playback. |
| `receptionist_forwarding_ring` | R | **Decline** the call (do not answer). | Nothing is spoken. With forwarding set up, the call returns to Friday. If you answer, she just hangs up. |
| `urgent_escalation` | R | Read the alert text on the page, do **not** acknowledge, wait 2 minutes (countdown), answer. | "Hello <name>, main Friday bol rahi hoon. Aapke liye ek urgent message aaya hai. Kripya abhi WhatsApp dekh lijiye." No digits, no details. |
| `trip_hotel_call` | R | Answer as hotel front desk. | Reconfirms a booking and arrival (invented data), asks check-in questions. |
| `refund_followup` | R | Answer as store support; try "it will be done in 3 days". | Asks refund status, refuses a vague answer, asks for a date/reference. |
| `care_hold_rehearsal` | R | Play the IVR: "press 1 for billing, press 2 for new connection", then "please hold", wait 20 s, then an agent. | Picks billing, waits on hold, re-introduces herself, explains the double charge, asks for a complaint number. |
| `frontdoor_inbound` | I | Dial Friday's number yourself (the caller ID she shows). | Her greeting and a Hinglish conversation. |
| `receptionist_inbound` | I | Forward your phone to Friday's number, call yourself from another phone and do not answer. | The receptionist asks who and why, reads back, closes. |
| `morning_checkin` | I | Nothing. | Not built in this version. Write "not built" if you expected it. |
| `chat_text` | S | Read the replies. | Short, warm, honest replies in your language. |
| `chat_voice_note` | S | Read the replies. | Reply language matches the note (Hinglish, Devanagari). |
| `chat_documents` | S | Read the replies. | A clear summary of the sample bill, receipt and card; no invented facts. |
| `chat_trips_refunds` | S | Read the replies. | Trip, refund and Drive text commands answer sensibly. |

### Real vs simulated, per scenario
- Vendor calls (`salon_*`, `vendor_*`): **real** = Vobiz call, Sarvam voice, the production playbook engine; **simulated** = the vendor, their answers, the WhatsApp request and quote message (WhatsApp is blocked). The Places shortlist is real Places data when a Places key is set, otherwise labelled sample names; it is text only and nothing from it is dialled.
- `consumer_*`: **real** = the whole consumer path (gate, approval, live engine, report); **simulated** = the callee (you), the WhatsApp request and report message (printed only).
- `receptionist_greeting`: **real** = the call and the real receptionist lines; **simulated** = the live listening and classification (use `receptionist_inbound` for that).
- `receptionist_forwarding_ring`: **real** = the ring; **simulated** = the "forwarding works" WhatsApp text (check the server log).
- `urgent_escalation`: **real** = the escalation dial and the spoken line; **simulated** = the alert and Acknowledge button, and the 5-minute timer shortened to 2 minutes.
- `trip_hotel_call`, `refund_followup`: **real** = the call with the module's own goal sentence and questions; **simulated** = trip/refund data, the proposal message and the Yes tap.
- `care_hold_rehearsal`: **real** = the call and the hold; **simulated** = the IVR and the company (you read the IVR aloud; there is no automatic IVR player).
- `chat_*`: all **simulated** on the Chat Lab engine (in-memory channel, fake numbers, fake clock, the lab's fake model). Real = the message pipeline and chatbot code.
- Not covered by a scenario (nothing to run by phone): proof/documents against a real Drive or Google account. The Drive is a stub in the simulator.

## 5. Record your verdict
Use the page buttons, or the CLI: `friday qa note <id> --verdict ok|wording|bug --note "..."`. Keep this table up to date as you go:

| Scenario | Verdict (OK / wording change / bug) | Note |
|---|---|---|
| salon_quote | | |
| salon_quote_pending | | |
| vendor_table | | |
| vendor_home_service | | |
| vendor_stock_price | | |
| vendor_hotel | | |
| vendor_cab | | |
| vendor_rental | | |
| vendor_banquet | | |
| consumer_family | | |
| consumer_provider | | |
| receptionist_greeting | | |
| receptionist_forwarding_ring | | |
| urgent_escalation | | |
| trip_hotel_call | | |
| refund_followup | | |
| care_hold_rehearsal | | |
| frontdoor_inbound | | |
| receptionist_inbound | | |
| chat_text / chat_voice_note | | |
| chat_documents / chat_trips_refunds | | |

Do not put a full phone number, a key or any password in a note (digits of 6 or more are masked automatically, but do not rely on it).

## 6. Pending lines: the hear-before-change loop
1. During a QA call every pending line Friday speaks is logged by id (`playbook:...`, `urg.*`, `rcp.*`, liveagent ids). The call itself is the audio sample.
2. After the call, open **Results** on the page. Each id has **approve** and **reject** buttons (or `friday qa line <line_id> approve|reject --note "..."`).
3. Ids you approved are listed by `friday qa report`; send that list to Claude. A reviewed commit then flips the status of those lines (`LINE_STATUS` or promoting a playbook with its marker file). Nothing changes by itself.
4. A line you reject, or a scenario marked "wording change", needs a **new audio sample** before it can be approved (CLAUDE.md rule 3). Tell Claude what to change; run the scenario again.
5. The log is approximate for the consumer live engine: a line is logged when it is chosen to be spoken.

## 7. Results summary
```
friday qa report
```
prints, for every scenario, your verdict, runs, notes, and all pending line ids heard with your approve/reject decision. Send back the report text only (it contains no number and no key). Also available on the page under **Results**.

## 8. If something goes wrong
- `REFUSED: QA mode will not start ...` lists exactly which rule failed (names only).
- "Another run is in progress": wait, or tap **Hang up / stop**.
- Phone does not ring: check the Vobiz top-up and `call_queue`, then `friday doctor`; the run log on the page and `var/livecalls/` / `var/consumer_calls/` on the server hold the masked transcripts.
- "public address is not reachable": `FRIDAY_PUBLIC_BASE_URL` must be the https address and `https://YOUR-HOST/health` must answer.
- Stop everything now: `friday pause` (kill switch), or ctrl-c in the tmux window.
- Remove the page route afterwards: `sudo bash /opt/friday/deploy/qa-https.sh --off`.

## 9. NOT verified (nobody has placed these calls yet)
- Every real call path: the dial, the answer, the audio, hang-up, the reply gap and Hinglish recognition on your voice.
- That the QA page, which runs each call as a child process, can bind the Friday port while the front door service is stopped on your server.
- That the receptionist forwarding ring comes back to Friday (depends on the carrier; see docs/RECEPTIONIST.md).
- The Places shortlist with a real key (the code is tested with a fake directory).
- That `FRIDAY_CONSUMER_CALLS_ENABLED=true` and the consumer path accept the allow-listed number from the child process.
