# Private browser runtime (Developer A notes, 23 Oct 2026)

Code: `friday/connectors/browser/**` (port, Playwright adapter, policy, backends, fake) and `friday/connectors/session/**` (manager, vault, live view, kill switch, audit). Design: `docs/PRIVATE_BROWSER_EM.md`. Default OFF.

## Settings (all `FRIDAY_BROWSER_*`, class `BrowserSettings`, not yet in `core/config.py`)
`ENABLED=false`, `ENABLED_USERS=` (comma ids or `*`; enabled with an empty list enables nobody), `BACKEND=local|cloud|fake`, `CLOUD_PROVIDER`, `HEADED=false`, `DISPLAY=:99`, `RESOLVE_DNS=true`, `TIMEOUT_MS=8000`, `TASK_MAX_SECONDS=600`, `MAX_PAGES=3`, `MAX_DOWNLOADS=0`, `MAX_PER_USER=1`, `MAX_GLOBAL=3`, `VAULT_TTL_DAYS=30`, `VAULT_DIR=var/browser_vault`, `LIVE_LINK_TTL_SECONDS=900`, `LIVE_VIEW_TTL_SECONDS=900`, `FRAME_MIN_INTERVAL_MS=400`, `TAKEOVER_MAX_SECONDS=300`.

## Use
```python
mgr = SessionManager(select_backend("local", headed=s.headed, display=s.display), vault, s, paused=pause_probe(core))
async with mgr.session(user, "zomato", task_id, policy=NetworkPolicy.for_hosts({"www.zomato.com", "*.zomato.com"}), recorder=rec) as page:
    ...  # page is a BrowserSession; connectors use it unchanged
```
Vault: `StorageVault(FileVaultStore(s.vault_dir), cipher_from_settings(core_settings))` (field key by name, `FRIDAY_FIELD_KEY`; live may pass the KMS cipher).

## Guarantees (each has a test)
- New context per task; saved login only from the (user, site) slot; AAD binds ciphertext to user+site; slots are blind indexes; 30-day expiry; `disconnect` / `disconnect_user`.
- Default-deny egress: exact or `*.` hosts only; empty list denies all; private, loopback, link-local, metadata blocked; DNS-rebinding check; enforced on goto and on every browser request (sub-resources, popups, websockets); violations audited.
- Limits: action timeout, task deadline (timer), max pages, max downloads (0); a tripped limit closes the session and skips the vault write. Caps per user and global are reserved before any await.
- Live view: link token (24 bytes, only the hash is stored) is single use and expires; opening it gives a view id with its own expiry; frames are rate limited and always paint over password / OTP / phone inputs. Takeover: Friday's calls wait, the user clicks/types/keys (validated, key allow-list, 200 chars max), give-back resumes. Typed content is forwarded only, never logged, recorded or kept (audit has a count). Takeover left idle beyond `TAKEOVER_MAX_SECONDS` closes the session without saving. We never read cookies during takeover; the vault is written only on a clean close in agent mode.
- Kill switch: `PauseWatcher` polls the same flag as `friday pause` and calls `kill_all`; `open` refuses while paused; `kill_task`, `kill_user`, `kill_all` close sessions, revoke links and views, and never write the vault.
- Audit (`AuditLog`): event, task, user, site, host, selector, counts; details pass through `scrub`; sink hook for persistence.

## Backends
`select_backend`: `local` (Playwright + Chromium from `PLAYWRIGHT_BROWSERS_PATH`, never `playwright install`), `fake` (tests), `cloud` (register a factory with `register_cloud_provider`; it must honour `SessionSpec`, keep CAPTCHA solving off and wrap provider live-view URLs in our token).
Headed Chromium on the founder's server: `Xvfb :99 -screen 0 1280x800x24 &` (or `xvfb-run -a friday serve`), set `FRIDAY_BROWSER_HEADED=true FRIDAY_BROWSER_DISPLAY=:99`.

## For the EM to wire (not mine)
Mount `LiveViewHttp(LiveViewService(mgr)).handle(method, path, body)` under `/live/*` (framework neutral; token page `/live/<token>`); start `PauseWatcher` in `friday serve`; add the settings to `core/config.py`; doctor lines; persist `AuditLog` via `sink`.

## Unverified
Real sites (Zomato etc.) and their anti-bot behaviour; headed mode under Xvfb (documented, not run); cloud provider (interface only); DNS-rebinding check against real DNS; takeover usability (masked password fields look blank to the user); several users on one server under load. The screenshot of a masked field hides the typed value from the user too, by design.
