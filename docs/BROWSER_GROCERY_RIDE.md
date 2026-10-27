# Private browser: grocery and ride adapters (Builder A notes, 2026-10-27)

Code: `friday/connectors/sites/grocery/` (Zepto, Blinkit, BigBasket, Instamart) and `friday/connectors/sites/ride/` (Uber, Ola, Rapido). Fakes: `sites/fakes/grocery_site.py`, `sites/fakes/ride_site.py`. Tests: `tests/connectors_sites/grocery/`, `tests/connectors_sites/ride/`. Adapter keys: `<site>.grocery`, `<site>.ride`. Each package exports `ADAPTERS` and `FAKE_SITES`. FAKE SITES ONLY: every real selector is a guess; real tuning touches only `profiles.py` of each package.

## Grocery
Shared `base.py` (connector + adapter), per-site `profiles.py` (selectors, alternates, paths, fee rules, quirks), `sites.py` (4 adapter classes).
- prepare (read-only): login and store-open check, search, brand/size pick (cheapest in-stock match when none given), minimum cart, ETA (instant sites) or slot (BigBasket), address, approval cap = items + expected fees + GST on fees + 5%.
- Sold out: never swaps. Problem `out_of_stock` with `options` (in-stock alternatives) so the flow can ASK. Sold out after approval: `out_of_stock` result, nothing clicked after.
- Substitution switch is read on the cart and forced OFF (Blinkit-style default ON is a tested quirk).
- Minimum: Zepto/Blinkit add a small-cart fee (inside the cap); BigBasket/Instamart refuse a small cart (`below_minimum`).
- After approval: cart built (a re-run after a re-ask adds only the difference; other items already in the cart stop the run), then price rise, fee rise, cap exceeded or a different delivery address mean `reapprove` with exact numbers; then `checkout_button` armed, one click, QR / UPI link handed over. Friday never pays.

## Ride
- prepare (read-only): login and service check, pickup and drop (text geocoded by the site, or a pin `28.61,77.20` / `pin: ...`), vehicle kind (auto, bike, cab, premium; site names mapped per site), fare RANGE, surge, cancellation fee in the card lines. Approval card expires in 3 minutes (`RIDE_APPROVAL_TTL`); an expired card is never acted on: live prices are read and a new card asked.
- After approval: live quote re-read; surge new or higher, fare above the approved range, cancellation fee higher, or different pickup/drop mean `reapprove`. Then `request_ride_button` (the one irreversible click) armed and pressed; waits for a driver; nobody accepts means the request is withdrawn and `out_of_stock`.
- Ride-start code: read by code, parked in `OneTimeReveal` (`ride/reveal.py`), the result carries only `otp_link` (token link to the one-time page). Driver name/vehicle are plain text, never parsed by a model. Live-trip share link is kept only if its host is on the site allow-list.
- No payment: result status `ride_requested`, no handoff.

## Both
Login expired: prepare returns Problem `needs_login`; execute raises `LoginRequired`. Bot check: `SiteBlocked` propagates and the connector never sends another request. Page labels pass through `strip_injection` (instruction-only labels are dropped). Copy: `grocery/copy.py`, `ride/copy.py` (PENDING founder approval, en + Roman Hinglish).

## Shared-file changes needed (engineering manager)
1. `flow.py` `_prepare`: map my Problem kinds (`needs_login`, `closed`, `below_minimum`, `no_slot`, `no_match`, `out_of_stock`) to wording; today anything not `out_of_stock` reads "could not find". `needs_login` should send the credential / takeover link; `problem.options` should become a "substitute?" question.
2. `flow.py` `_run`: handle `RideResult` (`status == "ride_requested"`): send driver text, `otp_link`, `share_link`; no payment phase. Grocery uses the existing `payment_ready`.
3. `flow.py` approval and summary text: use `grocery/copy.py` (`approve_grocery`) and `ride/copy.py` (`approve_ride`, 3-minute expiry, no UPI wording); `_missing` needs `pickup`/`drop`/`vehicle` questions (`q_ride_*`); the flow's QUESTION_KEY has no entries for them.
4. `registry.py` / `defaults.py` / `sim.py`: register `ADAPTERS` of both packages in the flow's adapter map and the sites in the registry; `base_urls` per key.
5. Ride one-time page route: mount `OneTimeReveal.take(token)` under a route like `/ride/code/<token>` (set `ride.base.LINK_BASE` or pass `link_base`; share one `OneTimeReveal` via `ride.DEFAULT_REVEAL`). Call `reveal.wipe(task_id)` when the task ends.
6. `reader.py` / `safety.py`: `SafetyEvent("injection")` details keep the attacker's sentence unscrubbed (fine for review, but scrub before any persistent log).

## Not verified
All selectors, fee numbers, vehicle names and the "request ride" flow are guesses tested against the fakes only. Login is never done by the adapters (the flow handles the credential link / OTP page / takeover). Real-site terms and anti-bot behaviour unchecked.
