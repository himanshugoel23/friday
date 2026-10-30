# Remote browser (managed browser service) for Friday's web tasks

Status: built and tested with fakes only. Nothing has run against a real provider. Switch `FRIDAY_REMOTE_BROWSER_ENABLED` is OFF. Privacy decision: PENDING founder.

## Read this first: privacy, in plain words
With a remote browser, the web pages Friday opens are loaded and rendered on a THIRD PARTY's machines (Browserbase, Steel or whoever you pick). That company can technically see the page content, and anything typed into the page, including a phone number or a logged-in page. Today the browser runs on our own server and nothing leaves it except to the site itself. Friday's own rules still apply (no payment, no government or identity pages, page text is untrusted, no passwords stored), but the provider's own privacy terms are what govern what they keep. We turn the provider's session recording and logging OFF in the create call, but we cannot see what else they store. Do not switch this on for logged-in or personal pages until you have read the provider's privacy policy and decided. Until then, use it only for public pages (the probe).

## What it is
`friday/sitemcp/remote.py`: `RemoteChromium`, same interface as the local `SharedChromium` (open / aclose / available). The site MCP, the live probe (`/ops-status/<token>/probe`, including the example.com control run) and the browser agent all pick it automatically when the switch is on. Every report line says which browser ran: `browser=local` or `browser=remote:<provider>`.

Same safety as the local browser: the NetworkPolicy default-deny guard (only the site's own domains), light blocking of images / media / fonts, one isolated context per user, payment-looking clicks refused. Extra for cost: the paid session is released as soon as the last context closes, a per-run time cap (default 120 s, also sent to the provider as its own timeout), a daily session cap (20) and a daily INR estimate cap (Rs 50). Usage is kept in `var/sitemcp/remote_usage.json` and shown by `friday doctor`.

## Hard rules (the founder's, enforced in code and tested)
We never ask for: proxy, residential IP, stealth, anti-detection, fingerprint, captcha solving, "verified / advanced stealth"; never a custom user agent or navigator override. The create-session request sends those explicitly OFF (Browserbase turns captcha solving ON by default, so `solveCaptchas: false` is sent) and nothing else except the time cap, project id and recording OFF. `tests/remotebrowser` inspects the request body and fails if any such parameter is present and not false.

## Setup in 4 steps (non-technical)
1. Make an account at the provider (Browserbase or Steel) and read its privacy policy and pricing page. Copy the API key (and for Browserbase the project id).
2. On the server, as root, store the key (names only, you type the value hidden): `bash /opt/friday/deploy/set-key.sh BROWSERBASE_API_KEY` and `... BROWSERBASE_PROJECT_ID` (or `STEEL_API_KEY`). For any other provider that gives you a ready websocket address, `FRIDAY_REMOTE_BROWSER_CDP_URL` instead.
3. Choose the provider and switch on, using the settings helper you already use (`deploy/setenv.sh`): `FRIDAY_REMOTE_BROWSER_PROVIDER=browserbase` (or `steel` or `cdp`) and `FRIDAY_REMOTE_BROWSER_ENABLED=true`. Note: re-running `deploy/enable-web-test.sh` writes `FRIDAY_REMOTE_BROWSER_ENABLED=false` again on purpose; set it after that script.
4. Restart Friday, wait for the probe (or run `friday sitemcp report`) and open `/ops-status/<token>/probe`. The control line for example.com should say `browser=remote:<provider>` and `ok`. `friday doctor` shows today's sessions and the estimated INR.

## Cost (VERIFY on the provider's pricing page)
Providers bill by browser time (per minute or per hour) plus plan fees, sometimes per proxy GB. We use no proxy. The settings are guesses until you check: `FRIDAY_REMOTE_BROWSER_INR_PER_MIN` (default Rs 1 per started minute), `FRIDAY_REMOTE_BROWSER_DAILY_INR` (50), `FRIDAY_REMOTE_BROWSER_DAILY_SESSIONS` (20), `FRIDAY_REMOTE_BROWSER_MAX_RUN_S` (120). The INR figure is an ESTIMATE of ours, not the provider's invoice. Some features of the provider's free tiers differ (for example keep-alive needs a paid plan); we do not use them.

## Honest limits
- It may still be blocked. A managed browser is also a datacenter IP, and quick-commerce sites that answered our droplet with HTTP 429 or a blank page may do the same here. We do not use proxies or stealth to get around this (hard rule). Treat the example.com control run as the proof the browser works and the site lines as the real answer.
- Nothing here ran against a real service. Selector knowledge for the sites is still unverified.
- Per-user contexts over CDP (`browser.new_context`) are assumed to work on every provider; if one only allows its single default context, the second user would fail (UNVERIFIED).
- The per-run cap is per remote SESSION (it opens when the first context opens and closes when the last one closes or the cap fires), not per chat task.
- The daily budget file is read and written without a lock across processes; with one server process this is fine.

## UNVERIFIED parts
- Browserbase: create (`POST https://api.browserbase.com/v1/sessions`, header `X-BB-API-Key`, response `id` + `connectUrl`) and release (`POST /v1/sessions/{id}` with `{"status": "REQUEST_RELEASE"}`) were read from the official docs on 2026-10-29. Never called for real. `recordSession`, `logSession`, `verified`, `solveCaptchas` names come from the same docs page.
- Steel: the docs we could read show only the SDK (`sessions.create()`, `websocketUrl` plus `&apiKey=<key>` for connect_over_cdp, `sessions.release(id)`). The REST endpoint `https://api.steel.dev/v1/sessions`, header `steel-api-key`, body fields `useProxy`, `solveCaptcha`, `timeout` (milliseconds) and release path `/{id}/release` are FROM MEMORY.
- Generic `cdp` is the path the tests cover most directly (no provider API at all).
- Playwright `connect_over_cdp` against a real remote browser was not run.
