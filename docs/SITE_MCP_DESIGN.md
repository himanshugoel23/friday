# Site MCP: our own browser-driven MCP server per app (2026-10-29)

Status: built and tested against FAKE stores only. Nothing here has touched a real site. Selectors are guesses. Switches `FRIDAY_SITE_MCP_ENABLED` and `FRIDAY_SITE_MCP_PROBE_ENABLED` default OFF. No chat or spoken wording was added.

## Why
Official MCP/OAuth approvals (Zepto, others) take weeks. Founder decision 2026-10-29: use a normal browser for now, and wrap each app in its own small MCP server with the SAME tools, so the shopping PM and the team agents stay generic and an official MCP can later replace one site behind the same `GroceryProvider` port (`friday/shopping/sites.py`, see `docs/ZEPTO_MCP_PLAN.md`).

## Shape (`friday/sitemcp`)
```
shopping PM -> FallbackGroceryProvider -> BrowserMcpGroceryProvider -> SiteMcpHub (in-process MCP JSON-RPC)
                       \-> WebGroceryProvider (web search)                 |-> SiteServer zepto | blinkit | instamart  (one per app)
                                                                           |      driven by knowledge/<site>.v1.json (data)
                                                                           '-> SessionPool -> SafeSession -> ONE shared Chromium
```
- **MCP surface** (`protocol.py`): the official Python MCP SDK is NOT a dependency (checked `pyproject.toml`, `uv.lock`), so this is a small hand-written JSON-RPC 2.0 server: `initialize`, `ping`, `tools/list`, `tools/call`. Transports: in-process (default, no subprocess) and newline-delimited stdio (`friday sitemcp serve <site>`). HTTP is NOT implemented (`McpServer.handle` is transport free; an adapter is a few lines). The user id travels in `params._meta.user_id`, never in tool arguments.
- **Tools, identical on every site** (`tools.py`): `set_location(place|pincode)`, `search_products(query)`, `get_product(id)`, `add_to_cart(id, qty)` (stage only), `view_cart()`, `checkout_preview()`, `login_start(phone)`, `login_status()`, `logout()`. Every result has a `status`: ok, needs_location, location_not_found, needs_login, otp_required, logged_in, logged_out, blocked, busy, rate_limited, not_found, unavailable (reason page_changed = selectors drifted), error.
- **No pay / place-order tool exists.** `assert_no_payment_tools` runs at construction and in a test; names containing pay, order, buy, purchase, confirm, submit, card, upi, wallet, refund are refused.
- **Knowledge** (`knowledge/*.v1.json`): urls, selectors, blocked markers, rate limits, quirks, `status: unverified`. `knowledge.validate` rejects a click/fill selector or url that looks like paying or placing an order, and any selector outside the CSS subset the fake engine understands. Product ids are on-site paths from `search_products`; `get_product` refuses any other host.

## Honest boundaries (enforced in code, tested)
1. A normal browser, as the USER, on their own account, with their consent. No captcha solving, no fingerprint spoofing, no proxy rotation, no stealth plugins, no user-agent tricks (`chromium.py` sets none; robots.txt identifies us as `FridayBot`).
2. `robots.txt` is read for ANONYMOUS pages (`RobotsPolicy`); disallowed or unreadable = `blocked` (reason `robots`), the page is never fetched.
3. Polite pacing: per site and per user minimum interval between page loads (knowledge `rate`, default 4 s / 3 s); a wait longer than `max_wait_s` returns `rate_limited` instead of sleeping.
4. A challenge marker, a captcha frame, HTTP 401/403/429 -> `blocked` and a 30 minute cooldown for that (user, site): further calls return `blocked` without touching the site, so nothing retries in a loop. The advice string tells the agent to use web sources or a deep link and tell the user plainly. `location_not_found` is likewise final for that call.
5. Network default deny: only the site's domains, their subdomains and the knowledge `extra_hosts` (a guess) can load.
6. Logins: only the user's own account. The phone goes into the site's field and nowhere else. The one-time code is typed by the user on Friday's existing secure OTP page (`/connectors/otp/<token>`, `OtpTokenRegistry` + `OneTimeOtpChannel`: memory only, single use) and never passes through a tool argument, log or model; the guarded login-OTP-in-chat flow is armed through `PendingLoginRegistry.expect`. Passwords are never stored. After login the Playwright storage state is saved with `StorageVault` (encrypted per user, TTL 30 d, `logout` and `forget_user` erase it).
7. `checkout_preview` reads the cart bill. It clicks the knowledge `checkout.proceed` button ONLY when that file says `proceed_verified: true` (all real files say false: nobody has confirmed what that button does on the live site); after it, it only reads. It reports `payment_step_reached` (`cart_summary`, `address_or_slot`, `payment_options`) and `stopped_before_payment: true`. `SafeSession` additionally refuses any payment-looking click, fill or goto. The user always pays in the app.
8. Screenshots exist only for the ANONYMOUS probe session (public pages), never for a logged-in page.

## RAM (1 GB droplet, Chromium is heavy)
ONE shared Chromium process (`chromium.SharedChromium`, launched lazily, flags `--disable-dev-shm-usage --disable-gpu`, images/media/fonts blocked), one context per (user, site). Hard caps: `FRIDAY_SITE_MCP_MAX_SESSIONS` (default 2; the least recently used idle context is evicted), ONE page working at a time, idle contexts closed after `FRIDAY_SITE_MCP_IDLE_S` (240 s), and a memory guard (`FRIDAY_SITE_MCP_MIN_FREE_MB`, default 250 of `MemAvailable`) that refuses NEW sessions with `busy / low_memory` while existing ones keep working. The scheduled probe closes the browser after every site. A Chromium is about 300-500 MB (an estimate, not measured): expect `busy` on the 1 GB machine when it competes with the app; swap helps (the installer adds it). A 2 GB droplet is the comfortable size.

## Live probe (no login) and how to see it remotely
- `friday sitemcp live <site> [--query atta] [--pincode 131001]`: on the SERVER; opens the real public site, sets the location, searches, parses the first results; records per-step status (ok / blocked / location_not_found / changed / unavailable / browser_unavailable) with timings, counts, up to 3 product names with printed prices, and saves one screenshot of the public page where it ended. No personal data.
- `friday sitemcp probe <site>`: opens the public pages and prints a selector drift report, COUNTS only (`matched/checked`).
- `friday sitemcp report`: prints the saved results.
- `FRIDAY_SITE_MCP_PROBE_ENABLED=true`: `friday serve` runs the live probe for `FRIDAY_SITE_MCP_SITES` (zepto, blinkit, instamart) about 90 s after start and then every `FRIDAY_SITE_MCP_PROBE_INTERVAL_H` (12 h), one site at a time, 30 s apart. Results under `var/sitemcp/` (git-ignored): `live_last.json`, `live_history.jsonl`, `drift_last.json`, `shots/<site>.png`.
- Read-only over the existing ops-status router, same token auth, 404 while the switch is off: `GET /ops-status/<token>/probe` (text) and `GET /ops-status/<token>/shot/<site>` (last public-page PNG). Site names are restricted to `[a-z0-9_-]`.
- `friday doctor` (section "private browser") prints the switches, Playwright / Chromium / Xvfb presence, available RAM, the last probe result per site and the install commands when something is missing (a WARN when either switch is on).

## Server prerequisites (NOT installed on the droplet yet)
Run once as root; the founder does this (not the self-updater):
```
apt-get install -y xvfb
cd /opt/friday && sudo -u friday /home/friday/.local/bin/uv sync --extra browser
cd /opt/friday && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers /home/friday/.local/bin/uv run playwright install chromium --with-deps && chmod -R a+rX /opt/pw-browsers
systemctl restart friday
```
`find_chromium` already looks in `/opt/pw-browsers` or `PLAYWRIGHT_CHROMIUM_PATH`. The default is headless; Xvfb matters only for headed runs, which are not wired into the service (running headed would mean starting the service under `xvfb-run`; not done).

### Proposal (NOT enabled): a fixed "ensure browser deps" step in `deploy/autoupdate.sh`
The self-updater runs a fixed sequence as root and must stay that way: no arbitrary script execution. If the founder wants updates to keep the browser current, add one fixed, idempotent step after `uv sync`, guarded by the switch being on:
`[ "$(grep -c '^FRIDAY_SITE_MCP' .env)" -gt 0 ] && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers uv run playwright install chromium` (no `--with-deps`, no `apt`; the apt packages stay a one-time manual step). Risks: a download during an update (needs network, about 150 MB, can fail: it must not fail the update), and a Playwright version bump changes the browser build. Not written into the script; decide first.

## What is NOT done / unverified
- Every selector and url in `knowledge/*.v1.json` is a guess from general knowledge. The sandbox cannot load these sites. The first `friday sitemcp live` run decides; expect `blocked` or `changed` for some sites and fix the data files, then set `status: verified` per site.
- Login/OTP, the logged-in cart and `checkout_preview` have never run on a real site (fakes only). `proceed_verified` stays false everywhere until a supervised run confirms the button only opens the address/payment step.
- Zomato and Swiggy Food servers are not built; the framework takes a new knowledge file plus a `GroceryProvider`/food adapter.
- The chat/web flow that hands the user the secure OTP link after `login_start` is not wired; only the tool and the existing secure page exist.
- Real-browser behaviour (Chromium launch, route guards, `ContextSession`) is covered by one test that skips cleanly when Playwright is absent; it has not run in this sandbox.
- `ShoppingInput.user_id` / `GrocerySearch.user_id` were added (optional) so a per-user session can be used; without it a shared guest context per pincode is used.
