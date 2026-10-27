# Private browser: coverage beyond Zomato and BookMyShow (2026-10-26)

Founder (10-26): do not limit the browser to two sites; cover Zepto, Blinkit, Swiggy, Uber, Ola, Rapido, MakeMyTrip, hotel, train and bus sites, "everything".

## What changed in the repo
`friday/connectors/catalog.py` is a data catalog of 25 sites in 9 categories (food, grocery, ride, stay, train, bus, flight, movies, shopping). A site is one entry: hosts (used by the browser's network allow-list and the password vault), a public home page, mode, legal status, login kind, the one irreversible click. `friday/connectors/defaults.py` registers a **link hand-over for every unblocked site today**, so Friday can already answer "book a cab" with the right app link on any of them. Tests: `tests/connectors/test_catalog.py`.

## The rule that decides what Friday may do on a site (`effective_mode`)
Automate only if ALL are true: a scripted or official backend exists, legal status is `cleared` for that site, the site is named in `FRIDAY_BROWSER_SITES_ENABLED`, and the session is founder-supervised. Otherwise it is a link hand-over; `blocked` is a status the founder can set for a site; today no site is blocked. **Nothing is cleared today**, so every real site is link-only until you and a lawyer clear it one by one.

## Notes on specific sites (founder decision 10-26: IRCTC is treated like any other site)
- **IRCTC (trains):** cataloged as a normal site: link hand-over today; automation goes through the same gate as every site (scripted adapter + legal status cleared + enabled + supervised). Its saved password is allowed in the vault. Open item for the founder and a lawyer: whether IRCTC's terms permit automated booking is unverified; it has anti-bot protection, and an account can be restricted. eRail is read-only timetable and seat information.
- **Amazon (founder 10-27: not blocked):** cataloged like any other site. Its conditions of use mention robots (EM design) and another agent product was reported blocked quickly (unverified), so real runs wait for the legal call and stay supervised.
- **Every site:** terms not read; "does a user-directed agent in the user's own account breach the terms, and who bears a ban?" is an open legal question (docs/PRIVATE_BROWSER_EM.md section 8).
- **Anti-bot:** Zomato resets our datacenter connections and Swiggy showed a challenge page; travel sites are usually stricter. Never rotate IPs to dodge a block; on a block Friday hands over the link.
- **Official access first:** Swiggy is reported to run an invite-led developer programme, Uber has a public ride API; check these before any scripted browser (unverified).

## One skeleton for every category (the food and movie adapters are the pattern)
search -> options -> pick -> cart or hold -> total check (a price rise after approval means ask again) -> approval card (exact items, total, cap, expiry) -> one irreversible click -> payment handed to the user as QR or UPI link. Per category only the selectors and the irreversible click differ:
| Category | Sites in the catalog | Irreversible step | Extra care |
|---|---|---|---|
| food | Zomato, Swiggy | place order | address and delivery slot confirmed |
| grocery | Zepto, Blinkit, BigBasket, Instamart | place order | substitutions off by default, minimum cart |
| ride | Uber, Ola, Rapido | request ride | live price changes; pickup pin; cancellation fee |
| stay / flight | MakeMyTrip, Goibibo, Booking, Agoda, OYO, Cleartrip | confirm booking | currency and foreign-card route; cancellation terms read back |
| train | IRCTC, eRail (info), ixigo (partner?) | book ticket | seat, class, passenger details read back |
| bus | redBus, AbhiBus | confirm booking | seat and boarding point |
| movies / shopping | BookMyShow, Flipkart | confirm / place order | seat hold timeout |

## Build waves (my estimate; each wave needs the legal call first)
1. **Now, no risk:** link hand-over for every site (done), "what can you help with" listing from the catalog, the doctor shows the coverage table.
2. **Wave 1, fake sites only (about 3 days per category, estimate):** fake grocery, fake ride, fake stay and fake bus sites plus the shared skeleton, so flow logic, approvals and price-rise handling are tested before any real page.
3. **Wave 2, founder-supervised real runs on the founder's own accounts:** one site per category, chosen after the legal read, with the credential vault for password sites and the takeover link for OTP sites. Expect selectors to break; the repair loop and daily canary from the EM design apply.
4. **Wave 3, tester access** only for sites with a clean record and a cleared legal status.

## Decisions needed
1. (Amazon decided 10-27: not blocked.) 2. Which one site per category goes first for the supervised runs (suggest Swiggy or Zomato, Blinkit, Uber, MakeMyTrip, redBus)? 3. Who does the legal read of site terms (the 25 entries are unverified)? 4. Host names and home URLs in the catalog are from general knowledge: confirm on the first supervised run.
