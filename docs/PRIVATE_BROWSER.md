# Private browser (pilot): the single doc

Status 2026-10-23: built and tested on FAKE sites only. Nothing has run against a real site, a real login or a real order. Default OFF.
Design background: `docs/PRIVATE_BROWSER_EM.md`. This file is the one to read for running and reviewing it.

## 1. Architecture (one screen)
```
WhatsApp message --> chat flow (Dev B, friday/connectors/flow.py)  [NOT LANDED YET]
        --> tool layer (friday/mcp: schema, level, kill, approval, audit)
        --> site connector (friday/connectors/sites: reader, locator, executor, safety, verifier)
        --> TaskSession (friday/connectors/session: policy, limits, takeover, vault, audit)
        --> backend (friday/connectors/browser: local Chromium, or a cloud provider later)
```
- One fresh browser context per task; a saved login comes only from the vault slot of that user and site (AES-GCM, AAD = user+site, 30-day expiry, Disconnect deletes).
- Default-deny network per connector: allow-listed hosts only; private, loopback, metadata addresses blocked; checked on every request (redirects too).
- Friday never sees an OTP, password or card. Login: user takes over the live view or types the code on the one-time page (memory only, single use). Payment: stops at a QR / `upi://pay` link; there is no pay tool.
- Irreversible step (checkout, submit) needs a Grant the user approved (exact items, merchant, ceiling, expiry, one use). In code, not the model.
- Page text is untrusted data: injection sentences are stripped and reported, never obeyed.
- Tool layer (`friday/mcp`): six tools `browser.open_task`, `read_page`, `act`, `request_user_login`, `request_approval`, `get_summary`; levels read / reversible / irreversible (`act` with `intent=commit` is irreversible); schemas have no field that can carry a secret (a test enforces it); every call (allowed or refused) writes an audit entry with scrubbed, hashed args; per-tool and global kill switch; users not enabled see an empty catalogue.

## 2. Switches (all default OFF / safest)
| Name | Meaning |
|---|---|
| `FRIDAY_BROWSER_ENABLED` | master switch; alone it enables nobody |
| `FRIDAY_BROWSER_ENABLED_USERS` | comma separated tester ids (`*` = all; do not use in the pilot) |
| `FRIDAY_BROWSER_BACKEND` | `local` (default) / `cloud` / `fake` |
| `FRIDAY_BROWSER_HEADED`, `FRIDAY_BROWSER_DISPLAY` | headed Chromium in a virtual display (`:99`) |
| `FRIDAY_BROWSER_MAX_PER_USER`, `_MAX_GLOBAL`, `_TASK_MAX_SECONDS`, `_MAX_PAGES`, `_MAX_DOWNLOADS` | limits (1 / 3 / 600 s / 3 / 0) |
| `FRIDAY_BROWSER_VAULT_DIR`, `_VAULT_TTL_DAYS` | encrypted logins (`var/`, never in git), 30 days |
| `FRIDAY_CONNECTORS_KILL` | CSV of `site.use_case` or `all`: routes to the in-app deep link |

## 3. Doctor
`friday/connectors/doctor_checks.py::check_browser(env)` returns a doctor `Section` (switch state, kill list, playwright, chromium, Xvfb, `.env`/`var/` not tracked, self test of the tool layer on fakes). It is NOT registered yet. To register (5 lines in `friday/ops/doctor.py`; nobody else is editing it): add `"browser"` to `SECTIONS`; `TITLES["browser"] = "9. private browser"`; in `run_sections` runners add
`"browser": lambda: __import__("friday.connectors.doctor_checks", fromlist=["x"]).check_browser(os.environ),` (import `os`). Then add a section "9. private browser" to `docs/DOCTOR.md`.

## 4. Runbook: ONE supervised real-site test (founder, on his server)
Rules: you watch the whole time; use YOUR OWN account on one site; cap the order (a cheap item); you pay in your own UPI app or you do not pay at all and stop at the QR. Never give Friday or any chat your OTP, password or card. If anything looks wrong, use the kill switch (step 9). Legal has not cleared any real site: this is a technical probe, not a launch.

1. Server up to date: `git pull`; `uv sync --extra browser`; `uv run playwright install chromium`; `sudo apt install xvfb`.
2. Virtual display: `Xvfb :99 -screen 0 1280x800x24 &` (or run Friday under `xvfb-run`).
3. Offline proof first: `uv run pytest tests/integration_browser tests/mcp -q` must be green.
4. `uv run friday doctor` (after step in section 3): no FAIL in the browser section.
5. Env file (names only here, values in `.env`, never in git): `FRIDAY_BROWSER_ENABLED=true`, `FRIDAY_BROWSER_ENABLED_USERS=<your user id>`, `FRIDAY_BROWSER_HEADED=true`, `FRIDAY_BROWSER_DISPLAY=:99`, `FRIDAY_BROWSER_MAX_GLOBAL=1`. Restart Friday.
6. Start one task from your own WhatsApp ("order ..."). Friday opens the site, and asks you to log in: open the takeover link on your phone, type your phone and OTP on the SITE's screen yourself.
7. Check what you see: cart matches what you asked, total matches the promise, Friday asks for approval with the exact items and ceiling before adding anything irreversible; stop at the pay screen / QR.
8. Do NOT pay unless you intend to; close the task. Then run `grep -rn "<your OTP digits>" var/ logs` style check: the code must appear nowhere (the integration test does the same on fakes).
9. Kill switch drill: during a second task set `FRIDAY_CONNECTORS_KILL=all` and restart, or call `SessionManager.kill_all()`; the browser must close and you must get the app deep link. Then Disconnect (vault delete) and confirm a new task starts logged out.
10. Record: did the site block the server IP (challenge, reset)? how long did it take? any step Friday could not do? Write it in HANDOFF. If blocked, stop; never rotate IPs or solve CAPTCHAs.

## 5. What is unverified
- Everything against a real site (selectors, flows, blocks, terms of service). Zomato resets datacenter IPs (HANDOFF 17 Oct).
- Headed Chromium in Xvfb on the real server; the `LocalPlaywrightBackend` has run only where Chromium was preinstalled.
- WhatsApp-like chat flow (`friday/connectors/flow.py`) is not landed, so the end-to-end test through the handler is skipped.
- The tool layer (`friday/mcp`) is not yet connected to the real session manager or connectors (fakes only).
- Legal: site terms, DPDP for cookies/screenshots, RBI/NPCI for the QR handoff.
- CI has never run on GitHub (no push of the workflow has been observed); gitleaks version pinned from memory.

## 6. CI (what exists)
`.github/workflows/ci.yml`: secret scan + tracked-file check (`.github/scripts/secret_scan.sh`, prints pattern and file:line only), gitleaks, ruff, fast tests on PR/push (connectors, integration_browser, mcp, security, core, calls, tasks), full suite nightly, advisory dependency audit. CODEOWNERS has the placeholder `@OWNER`. Run the scan locally: `.github/scripts/secret_scan.sh`.

## 7. Review findings (EM, 2026-10-23) -- fix requests
Reviewed `friday/connectors/session`, `browser`, `sites` as pushed. Good: no logging in these packages; values never recorded; request-level route guard; vault AAD; slots reserved before await; takeover input validated and counted only. Requests:

**Developer A**
1. [high] `SessionManager.kill_all()` closes sessions but does not latch. A new `open()` right after succeeds unless the caller wires `paused`. Make `kill_all` set a flag that `open` checks until `revive()`. Test: `tests/integration_browser/test_sessions.py::test_kill_all_is_latched` (xfail strict; remove the mark when fixed).
2. [med] `TaskSession.fill` forwards any value to any selector. Selector keys are known only to Dev B's layer, so keep it there, but add a defence in depth: refuse `fill` when the target is `input[type=password]` (query the element type) unless the caller passes an explicit `allow_secret_field=False`-style flag that only the OTP path sets.
3. [low] `FileVaultStore.get` returns None on any parse error, silently hiding corruption; audit a `vault_unreadable` event (no content).
4. [low] `AuditLog` is in memory only (deque of 5000). The `sink` hook exists: wire a durable sink before the pilot or takeovers are lost on restart.

**Developer B**
1. [high] `GuardedSession.click`: `check_click` runs on the ORIGINAL selector only. A repaired selector (`locator.repair`) is clicked without re-checking, so a repaired selector could hit a pay or place-order control. Run `check_click` on every candidate and on the repaired selector before using it; never repair a click at all if its key is unknown.
2. [high] `GuardedSession.fill` with a repaired selector may land in a different (e.g. password) field. Do not repair `fill`, or check the field type first.
3. [med] `SiteSafety.check_fill`: when the selector is not in the dict (`key is None`) a non-numeric secret (a password) is accepted. Refuse fills for unknown keys.
4. [med] `pizza_flow.run_pizza_flow` (existing, now yours via flow): the kill switch is checked once at selection. A kill during approval still ends in `payment_ready`. Re-check `registry.is_killed` after `approve()` and before `build_cart` / handoff. Test: `tests/integration_browser/test_scenarios.py::test_kill_switch_mid_task_stops_everything_and_falls_back_to_link` (xfail strict).
5. [med] `friday/connectors/flow.py` and `tests/connectors_sites/` do not exist yet (the folder is empty). The WhatsApp-like handler test waits for them; please expose one public entry (message in, reply out, user id explicit) so the test can be written.
6. [low] `Verifier._BLOCK` also matches the word "captcha" anywhere in page text; a page that merely mentions it ends the run. Acceptable (fail closed) but note it.

**Lead**: ruff currently reports errors in `deploy/probe_saaras_realtime.py`, `deploy/probe_bulbul_ws.py` and `friday/core/config.py`; the CI lint job will fail until fixed (not browser code).
