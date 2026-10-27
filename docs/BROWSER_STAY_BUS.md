# Private browser: stay (hotel, flight) and bus adapters (2026-10-27)

Builder B notes. Everything runs against FAKE sites only; every real selector, URL and flow detail is an unverified guess.

## What exists
- `friday/connectors/sites/stay/`: `base.py` (shared flow), per-site modules (selectors and quirks only), `contract.py`, `copy.py` (en + Hinglish, PENDING founder approval). Keys: `makemytrip.hotel|flight`, `goibibo.hotel|flight`, `booking.hotel`, `agoda.hotel`, `oyo.hotel`, `cleartrip.flight|hotel`.
- `friday/connectors/sites/bus/`: `base.py`, `redbus.py`, `abhibus.py`, `contract.py`, `copy.py`. Keys: `redbus.bus`, `abhibus.bus`.
- Fakes: `sites/fakes/stay_site.py`, `sites/fakes/bus_site.py`. Each site has its own selector dialect, URL shapes, query-parameter names and money format, spelled out in the fake independently of the adapters.
- Both packages export `ADAPTERS` (`"<site>.<use case>"`) and `FAKE_SITES` (`FAKE_SITES[key](**knobs)` returns a browser session on that fake).

## Rules as built
Search -> shortlist of at most 5 (INR) -> pick -> reserve/hold only after approval -> total check -> approval card -> one irreversible click (`proceed_to_pay`, armed by `SiteSafety.approved`) -> QR/UPI link. Friday never pays.
- Stay cap = the all-in total (taxes and fees included, no margin). Any rise, or worse cancellation terms, after approval returns `reapprove` with the exact new total; the second approval is a new card.
- Free-cancellation deadline and the non-refundable items are read from the site and printed on the card (`copy.approval_text`).
- Foreign currency (or no positive INR evidence) -> `HandoverProblem("foreign_currency", link=<catalog home>)` before anything is clicked.
- Block page / CAPTCHA -> `SiteBlocked` propagates (the flow already shows the hand-over link). Login -> one-time OTP channel, `LoginRequired` / `LoginFailed` propagate.
- Passenger and guest names only from the user's slots (`clean_names`); missing or malformed -> `need_info` problem, nothing opened. Baggage and meal add-ons are switched off even if the site pre-ticks them.
- Bus: seats are selected (site holds them) only after approval. The approval card lasts 5 minutes; the site hold is 8+ minutes and starts after approval. The hold timer is read after holding and again just before the last click; a lapsed or too-short hold returns `reapprove` (no click). Boarding/dropping points are asked (with the site's options), never guessed. The operator cancellation policy is on the card.
- Page text is untrusted: names and labels go through `strip_injection` + `scrub_text`; hits are noted in `kit.safety` (flag `injection`).

## Shared-file changes the engineering manager must make
1. `sites/adapters.py` `ADAPTERS`: merge `stay.ADAPTERS` and `bus.ADAPTERS`. Import them lazily or at the very bottom of adapters.py (my modules import `Proposal`, `Prepared`, `Problem`, `ExecResult`, `APPROVAL_TTL` from adapters.py: a top-of-file import would be circular).
2. `flow.py` `QUESTION_KEY`: add `origin`->`q_flight_origin`, `checkin`, `checkout`, `guest_name`, `depart_date`, `return_date`, `passengers`, `date` (bus), `destination` (`q_stay_destination`); the texts are in `stay/copy.py` and `bus/copy.py` (the same slot name `origin`/`destination` differs by use case: pick by `st.connector`). `_take_answer` must parse `passengers` into a list of names (split on commas / "and") and dates into ISO.
3. `flow.py` `_missing`: no extra profile slot is needed for these use cases.
4. `flow.py` `_approval_text`: for stay/bus connectors call `stay.copy.approval_text(p, lang)` / `bus.copy.approval_text(p, lang)` (the default food/movie cards do not show cancellation terms).
5. `flow.py` `_prepare`: when `prep.problem.kind` is `foreign_currency` or `need_info`, show `stay.copy.problem_text` / `bus.copy.problem_text`; `foreign_currency` must also end the task with the link (`HandoverProblem.link`). Today any unknown kind prints the `no_match` line. For `need_info` the flow should ask `problem.slot` (bus boarding/dropping carry `problem.options`) and re-run prepare.
6. `flow.py` `_paid`/`summarise` and `_quick`/planner: no stay/bus phrases yet (planner is a shared file).
7. `registry`/`defaults.py`: register `scripted_browser` backends for the 11 keys (catalog `adapter` field and `mode="scripted"` for them) once the founder clears them.
8. `ExecResult.status` has no value for a mid-run foreign currency: it surfaces as `ForeignCurrency` (a `ConnectorError`, so the flow says "I hit a problem and stopped safely").

## Found while building
- `friday.connectors.contract.rupees_to_paise("Rs. 4,200")` returns 42 paise-ish (0.42 rupees): the dot after "Rs" is kept. `stay.base.parse_inr` strips the marker first and rejects any foreign or unknown currency. The shared function should be fixed.
- `ActionGate()` uses the real clock; the adapters pass `ActionGate(now=ctx.now)`.
- `SiteSafety.events` keep the short injected sentence (by design, for review); it never reaches users.

## Not verified / gaps
- No real site was touched. All selectors, URLs and money formats are guesses against the fakes; real flows (seat maps, room lists, multi-step checkouts, pop-ups, GST forms) will differ.
- Logins are OTP-only; password / Google login (Booking, Agoda, OYO) via `CredentialService.autofill` is not wired.
- Return flights are modelled as one round-trip fare; multi-city, children/infants, passenger ages and ID details are not covered. Hotel guests are one name; flight add-ons are never turned on (even if asked).
