# Browser connectors (internal MCP-style)

Design source: `docs/BROWSER_AGENT_PLAN.md` (Clarification and Internal MCP connectors). Code: `friday/connectors/`.

## Architecture
```
Friday brain  ->  ActionGate (allow / deny / ask)  ->  ConnectorRegistry.select(site, use_case)
                                                        |  official_mcp > deep_link > scripted_browser > llm_browser (live only)
                                                        v
                         FoodConnector (contract.py)  e.g. ZomatoFoodConnector (food/zomato.py)
                                                        v
                         BrowserSession port (browser/port.py)  ->  Playwright + Chromium  |  SimBrowserSession (tests)
```
- `contract.py`: pydantic models and the `FoodConnector` Protocol. Money is integer paise; `Cart` rejects totals
  that do not add up. `PaymentHandoff` can only hold a PNG QR and/or a `upi://pay` link with allow-listed
  fields, so it cannot carry a credential. There is no pay tool.
- `registry.py`: backends per (site, use case) with status (live/degraded/off), version, per-connector kill
  switch (`kill`, or env `FRIDAY_CONNECTORS_KILL=zomato.food,...` / `all`). A layout failure flips the backend to
  `degraded` and the flow returns a "finish in the app" deep link.
- `gate.py`: reads allowed; `build_cart` / `get_payment_handoff` need a `Grant` (task, connector, restaurant,
  exact items, max total, expiry, one-time). No grant or expired -> ask; scope mismatch -> deny; payment -> deny.
- `scrub.py`: strips OTP-like codes, cookies, bearer tokens, key=value secrets, long hex/base64 and phone numbers.
- `otp.py`: login OTP only, in memory, per task, single use, TTL, wiped on `take`, hidden from repr.
- `pizza_flow.py`: search -> choose -> menu -> pick -> ask -> Grant -> build_cart -> handoff.
- `recorder.py`, `watch.py`, `report.py`, `api/connectors_watch.py`: see "Watching a run".

## Watching a run
Every browser step is recorded as `{n, time, tool, action, url, note, screenshot}`. Typed values are never
recorded and password / tel / OTP inputs are painted over in each screenshot. Notes and URLs are scrubbed.
`/connectors/watch/{token}` (auto-refresh page), `.../state.json`, `.../latest.png`, `.../step/{n}.png`,
`.../trace.zip` (Playwright trace, when recorded). The token (24 random bytes) is the only credential in the
URL; it expires (default 30 min), unknown/expired/revoked tokens answer 404, and an admin can revoke with
`POST /connectors/admin/revoke/{token}` (admin bearer). The page is read-only. A later "takeover view" for the
login would reuse this page (stub: `watch.TakeoverHook`); it is NOT built.
Screenshots and traces show page content (names, addresses): keep the watch link private.

## Run it
```
uv sync --extra browser                                  # optional Playwright; uses the preinstalled Chromium
uv run friday connectors list
uv run friday connectors demo-pizza --fake               # real Chromium on the local fake site
uv run friday connectors demo-pizza --fake --engine sim  # no browser at all
uv run friday connectors demo-pizza --fake --watch --out var/demo   # live page URL + static report.html
```
Chromium comes from `PLAYWRIGHT_CHROMIUM_PATH` or `/opt/pw-browsers/chromium-*/`; never run `playwright install`.

## Add a site
1. New module `friday/connectors/food/<site>.py` implementing `FoodConnector` against `BrowserSession`
   (or an official-MCP / deep-link backend; nothing above changes).
2. Keep PATHS / SELECTORS / FIELDS in one dict block at the top of the file.
3. Register it in `defaults.py` with status `off` until fixtures pass, then `live`.
For a new use case (cab, movie, hotel) add a contract module next to `contract.py` and a pizza_flow-style orchestrator.

## Tune selectors
Only the three dicts at the top of `food/zomato.py` change. Save real pages as fixtures, run the connector against
them, and add a canary that flips the registry to `degraded` when a login-free step (search, menu price) fails.
Ids read from a page are validated (`^[A-Za-z0-9_.-]{1,64}$`) before being put in a selector or URL.

## Test strategy
- Always-on: pure-Python `SimBrowserSession` over the same fake-site data (`tests/connectors/`): contract, gate,
  scrub, OTP, registry, kill switch, degraded fallback, tampered totals, recorder, watch tokens (404s).
- Real Chromium on the localhost fake site (skipped without the `browser` extra or Chromium); requests to any
  other host are aborted by the session.
- No test touches the network except localhost.

## NOT verified
- Real Zomato pages, selectors, login modal, checkout and QR/UPI screen: unknown. The fake site only imitates structure.
- Real login and OTP delivery from the secure page to the worker (the page is not built; the channel is).
- Anti-bot behaviour, new-device checks, CAPTCHAs, cloud-IP blocks, site terms and legal read.
- Session persistence (`storage_state()` exists; encryption at rest, expiry and "Disconnect" are not built).
- The sim screenshot is a 1x1 placeholder; real screenshots only come from Chromium.
